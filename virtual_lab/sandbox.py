"""Executors on the Antigravity managed agent: a pre-warmed sandbox with the cohort, run on Argon."""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import agents
from .config import (ANTIGRAVITY, ARGON, CACHE_DIR, DATA_CSV, DATA_DICT, FLASH, SANDBOX_DATA, SANDBOX_DICT,
                     SANDBOX_OUT)
from .llm import ask, client, usage_of
from .notebook import Run

ENV_CACHE = CACHE_DIR / "sandbox.json"
ENV_MAX_AGE = timedelta(days=6)  # environments are kept for 7 days after last use
OUTPUTS = ["results.json", "summary.md", "km.png", "analysis.py"]
FILE_TIMEOUT = 45  # seconds per upload/download
SETUP_TIMEOUT = 300
AGENT_TIMEOUT = {"fast": 240, "full": 900}

SETUP_PROMPT = f"""Run this shell command and reply with only the last line it prints:
pip install -q --break-system-packages lifelines matplotlib pandas && mkdir -p {SANDBOX_OUT} && \
python3 -c "import pandas as pd, lifelines; print('ready', pd.read_csv('{SANDBOX_DATA}').shape, 'lifelines', lifelines.__version__)\""""


def workdir(run: Run) -> str:
    """Each run writes only under its own directory, so runs sharing a sandbox never see each other's files."""
    return f"/workspace/runs/{run.id}"


async def _file_call(fn, **kwargs):
    return await asyncio.wait_for(asyncio.to_thread(fn, **kwargs), FILE_TIMEOUT)


async def ensure(run: Run) -> str | None:
    """Return a sandbox with the data and packages installed, reusing a recent one when possible."""
    if ENV_CACHE.exists():
        cached = json.loads(ENV_CACHE.read_text())
        if datetime.now() - datetime.fromisoformat(cached["created"]) < ENV_MAX_AGE:
            try:  # wakes the snapshotted sandbox now, and fails fast if it has expired
                await _file_call(client().environments.files.upload, environment=cached["id"],
                                 path=f"{workdir(run)}/.wake", file=b"1", overwrite=True)
            except Exception:
                return await create(run)
            run.emit("agent_output", agent="SandboxSetup", lane="Sandbox", model=ANTIGRAVITY,
                     text=f"Reusing pre-warmed sandbox `{cached['id']}` (METABRIC + lifelines installed).")
            return cached["id"]
    return await create(run)


async def create(run: Run) -> str | None:
    """New sandbox: upload the cohort and install packages. Setup only; no analysis runs here."""
    run.emit("agent_start", agent="SandboxSetup", lane="Sandbox", model=ANTIGRAVITY)
    start = time.time()
    try:
        interaction = await asyncio.wait_for(client().aio.interactions.create(
            agent=ANTIGRAVITY,
            agent_config={"type": "antigravity", "model": FLASH},
            input=SETUP_PROMPT,
            environment={
                "type": "remote",
                "sources": [
                    {"type": "inline", "content": DATA_CSV.read_text(), "target": SANDBOX_DATA},
                    {"type": "inline", "content": DATA_DICT.read_text(), "target": SANDBOX_DICT},
                ],
            },
        ), SETUP_TIMEOUT)
    except Exception as e:
        run.emit("error", agent="SandboxSetup", lane="Sandbox", text=f"{type(e).__name__}: {str(e)[:300]}")
        return None
    run.add_usage(*usage_of(interaction))
    env_id = interaction.environment_id
    ENV_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ENV_CACHE.write_text(json.dumps({"id": env_id, "created": datetime.now().isoformat()}))
    run.emit("agent_output", agent="SandboxSetup", lane="Sandbox", model=ANTIGRAVITY,
             text=f"New sandbox `{env_id}`: {interaction.output_text}", ms=int((time.time() - start) * 1000))
    return env_id


async def write_code(run: Run, plan: str, experts: str) -> str | None:
    """Fast mode: Argon writes the whole analysis.py in one call (runs while the approval card waits)."""
    reply = await ask(run, "ExecutorCoder", ARGON, agents.CODER_PROMPT.format(
        experts=experts, plan=plan, data=SANDBOX_DATA, dictionary=DATA_DICT.read_text(), out=f"{workdir(run)}/out"),
        system=agents.LAB_RULES, thinking="low", lane="Sandbox",
        show="Wrote `analysis.py` for the sandbox (code below). It runs only after approval.")
    code = _python_block(reply or "")
    if code:
        run.emit("tool", agent="ExecutorCoder", lane="Sandbox", text=code, data={"kind": "code"})
    return code or None


@dataclass
class Execution:
    files: dict[str, str] = field(default_factory=dict)  # output name -> catalogue ID, for files that exist
    results: str = ""  # validated results.json text ("" if the run produced none)
    tokens: int = 0  # sandbox tokens spent, counted against the approved budget
    downloads: asyncio.Task | None = None  # resolves to the full {name: ID} once files are on disk

    async def all_files(self) -> dict[str, str]:
        return await self.downloads if self.downloads else self.files


async def execute(run: Run, plan: str, experts: str, max_tokens: int, env_id: str,
                  code: str | None = None) -> Execution:
    """Run the approved plan in the sandbox. Never raises: a failed attempt returns empty results.

    With `code` (fast mode): upload it and the sandbox agent runs it, fixing only if it fails; the script
    prints its results on stdout, so synthesis can start while the files download in the background.
    Without (full mode): the sandbox agent on Argon writes, runs and iterates on its own.
    """
    base = workdir(run)
    out_dir, script = f"{base}/out", f"{base}/analysis.py"
    clean = f"First run `rm -rf {out_dir} && mkdir -p {out_dir}`.\n\n"
    paths = {name: f"{out_dir}/{name}" for name in OUTPUTS}
    try:
        if code:
            await _file_call(client().environments.files.upload, environment=env_id, path=script,
                             file=code.encode(), overwrite=True)
            stdout, tokens = await _agent(run, clean + agents.RUNNER_PROMPT.format(
                script=script, data=SANDBOX_DATA, out=out_dir), max_tokens, env_id, model=FLASH)  # runs Argon's script
            paths["analysis.py"] = script
        else:
            stdout, tokens = await _agent(run, clean + agents.EXECUTOR_PROMPT.format(
                experts=experts, data=SANDBOX_DATA, dictionary=SANDBOX_DICT, plan=plan, out=out_dir), max_tokens, env_id)
    except Exception as e:
        run.emit("error", agent="Executor", lane="Sandbox", text=f"Sandbox attempt failed: {type(e).__name__}: {str(e)[:300]}")
        return Execution()

    results = parse_results(stdout)
    files = {"results.json": run.add_source("file", "results.json", "sandbox/results.json", "Executor")} if results else {}
    downloads = asyncio.create_task(download(run, env_id, paths, files))
    if not results:  # the script did not print its results: fall back to the downloaded file
        on_disk = await downloads
        if "results.json" in on_disk:
            results = parse_results("RESULTS_JSON " + (run.dir / "sandbox" / "results.json").read_text().replace("\n", " "))
        files = dict(on_disk)
    return Execution(files, results, tokens, downloads)


def parse_results(stdout: str) -> str:
    """The last RESULTS_JSON line that decodes to an object with a primary result, re-serialized; else ""."""
    for line in reversed(stdout.splitlines()):
        if "RESULTS_JSON " not in line:
            continue
        try:
            obj = json.loads(line.split("RESULTS_JSON ", 1)[1].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("primary"), dict):
            return json.dumps(obj, indent=1)
    return ""


def _python_block(text: str) -> str:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


async def _agent(run: Run, prompt: str, max_tokens: int, env_id: str, model: str = ARGON) -> tuple[str, int]:
    """One Antigravity interaction, streaming each code step to the live page. Returns (stdout, tokens).

    Raises on a stream error, a stream that never completes, or the mode's deadline.
    """
    run.emit("agent_start", agent="Executor", lane="Sandbox", model=f"{ANTIGRAVITY} · {model}")
    start = time.time()
    final_text, done = [], {}

    async def consume():
        stream = await client().aio.interactions.create(
            agent=ANTIGRAVITY,
            agent_config={"type": "antigravity", "model": model, "max_total_tokens": max_tokens},
            system_instruction=agents.LAB_RULES,
            input=prompt,
            environment=env_id,
            stream=True,
        )
        async for event in stream:
            kind = getattr(event, "event_type", "")
            if kind == "step.start":
                step = event.step.model_dump(exclude_none=True)
                code = (step.get("arguments") or {}).get("code") or step.get("code")
                if code:
                    run.emit("tool", agent="Executor", lane="Sandbox", text=code, data={"kind": "code"})
            elif kind == "step.delta":
                delta = event.delta.model_dump(exclude_none=True)
                if delta.get("type") == "text":
                    final_text.append(delta.get("text", ""))
            elif kind == "interaction.completed":
                done["interaction"] = event.interaction
            elif kind == "error":
                raise RuntimeError(f"stream error: {str(getattr(event, 'error', event))[:200]}")

    await asyncio.wait_for(consume(), AGENT_TIMEOUT[run.mode])
    interaction = done.get("interaction")
    if interaction is None:
        raise RuntimeError("the sandbox agent stream ended without completing")
    tin, tout = usage_of(interaction)
    run.add_usage(tin, tout)
    outputs = []
    for step in interaction.steps or []:
        s = step.model_dump(exclude_none=True)
        if s.get("type", "").endswith("_result"):
            out = s.get("result") or s.get("output") or s.get("content")
            if out:
                outputs.append(str(out))
                run.emit("tool", agent="Executor", lane="Sandbox", text=str(out)[:2000], data={"kind": "output"})
    run.emit("agent_output", agent="Executor", lane="Sandbox", model=f"{ANTIGRAVITY} · {model}",
             text="".join(final_text) or "(no summary)", ms=int((time.time() - start) * 1000), tokens=tin + tout,
             data={"status": interaction.status})
    if interaction.status != "completed":  # outputs are still this attempt's own; execute() validates them
        run.emit("error", agent="Executor", lane="Sandbox", text=f"Sandbox agent finished with status {interaction.status}")
    return "\n".join(outputs), tin + tout


async def download(run: Run, env_id: str, paths: dict[str, str], ids: dict[str, str]) -> dict[str, str]:
    """Fetch the outputs into runs/<id>/sandbox/; catalogue each file that exists. Returns {name: ID}."""
    async def fetch(path):
        try:
            return await _file_call(client().environments.files.download, environment=env_id, path=path)
        except Exception:
            return None

    found = {}
    blobs = await asyncio.gather(*(fetch(path) for path in paths.values()))
    for name, data in zip(paths, blobs):
        if data is None:
            continue
        run.write(f"sandbox/{name}", data)
        found[name] = ids.get(name) or run.add_source("file", name, f"sandbox/{name}", "Executor")
        run.emit("tool", agent="Executor", lane="Sandbox", text=f"[{found[name]}] {name}",
                 data={"kind": "file", "path": f"sandbox/{name}"})
    return found
