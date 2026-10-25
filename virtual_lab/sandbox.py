"""Executors on the Antigravity managed agent: a pre-warmed sandbox with the cohort, run on Argon."""

import asyncio
import json
import math
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
RECONCILE_TIMEOUT = 15
PRIMARY_NUMBERS = ("hr", "ci_low", "ci_high", "p")

SETUP_PROMPT = f"""Run this shell command and reply with only the last line it prints:
pip install -q --break-system-packages lifelines matplotlib pandas && mkdir -p {SANDBOX_OUT} && \
python3 -c "import pandas as pd, lifelines; print('ready', pd.read_csv('{SANDBOX_DATA}').shape, 'lifelines', lifelines.__version__)\""""


class SandboxError(RuntimeError):
    """A failed sandbox attempt, carrying the tokens it consumed (or reserved, when unknown)."""

    def __init__(self, message: str, tokens: int):
        super().__init__(message)
        self.tokens = tokens


def workdir(run: Run) -> str:
    """Each run writes only under its own directory, so runs sharing a sandbox never see each other's files."""
    return f"/workspace/runs/{run.id}"


async def upload(env_id: str, path: str, data: bytes):
    await asyncio.wait_for(client().aio.environments.files.upload(
        environment=env_id, path=path, file=data, overwrite=True), FILE_TIMEOUT)


async def fetch(env_id: str, path: str) -> bytes | None:
    try:
        return await asyncio.wait_for(client().aio.environments.files.download(environment=env_id, path=path),
                                      FILE_TIMEOUT)
    except Exception:
        return None


async def wake(run: Run) -> str | None:
    """Wake the cached sandbox (a file upload, no model spend). None if there is none or it expired."""
    if not ENV_CACHE.exists():
        return None
    cached = json.loads(ENV_CACHE.read_text())
    if datetime.now() - datetime.fromisoformat(cached["created"]) >= ENV_MAX_AGE:
        return None
    try:
        await upload(cached["id"], f"{workdir(run)}/.wake", b"1")
    except Exception:
        return None
    run.emit("agent_output", agent="SandboxSetup", lane="Sandbox", model=ANTIGRAVITY,
             text=f"Reusing pre-warmed sandbox `{cached['id']}` (METABRIC + lifelines installed).")
    return cached["id"]


async def create(run: Run) -> str | None:
    """New sandbox: upload the cohort and install packages (a paid agent call, so only after approval)."""
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
    if interaction.status != "completed" or "ready" not in (interaction.output_text or ""):
        run.emit("error", agent="SandboxSetup", lane="Sandbox",
                 text=f"Sandbox setup did not finish (status {interaction.status}): {(interaction.output_text or '')[:200]}")
        return None
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
    files: dict[str, str] = field(default_factory=dict)  # output name -> catalogue ID, for files on disk
    results: str = ""  # validated results JSON ("" if the attempt produced none)
    tokens: int = 0  # sandbox tokens consumed (or reserved), counted against the approved budget
    downloads: asyncio.Task | None = None  # resolves to the full {name: ID} once files are on disk

    async def all_files(self) -> dict[str, str]:
        return await self.downloads if self.downloads else self.files


async def execute(run: Run, plan: str, experts: str, max_tokens: int, env_id: str,
                  code: str | None = None) -> Execution:
    """Run the approved plan in the sandbox. Never raises (except cancellation): a failed attempt returns
    an Execution with empty results and the tokens it used.

    With `code` (fast mode): upload it and the sandbox agent runs it, fixing only if it fails; the script
    prints its results on stdout, so synthesis can start while the files download in the background.
    Without (full mode): the sandbox agent on Argon writes, runs and iterates on its own.
    """
    base = workdir(run)
    out_dir, script = f"{base}/out", f"{base}/analysis.py"
    clean = f"First run `rm -rf {out_dir} && mkdir -p {out_dir}`.\n\n"
    paths = {name: f"{out_dir}/{name}" for name in OUTPUTS}
    tokens = 0
    try:
        if code:
            await upload(env_id, script, code.encode())
            stdout, tokens = await _agent(run, clean + agents.RUNNER_PROMPT.format(
                script=script, data=SANDBOX_DATA, out=out_dir), max_tokens, env_id, model=FLASH)  # runs Argon's script
            paths["analysis.py"] = script
        else:
            stdout, tokens = await _agent(run, clean + agents.EXECUTOR_PROMPT.format(
                experts=experts, data=SANDBOX_DATA, dictionary=SANDBOX_DICT, plan=plan, out=out_dir), max_tokens, env_id)

        files: dict[str, str] = {}
        results = parse_results(stdout)
        if results:  # keep the printed result as this run's results.json; the download will not replace it
            run.write("sandbox/results.json", results)
            files["results.json"] = run.add_source("file", "results.json", "sandbox/results.json", "Executor")
            run.emit("tool", agent="Executor", lane="Sandbox", text=f"[{files['results.json']}] results.json",
                     data={"kind": "file", "path": "sandbox/results.json"})
        downloads = asyncio.create_task(download(run, env_id, paths, files))
        if not results:  # nothing usable printed: use the downloaded file, validated the same way
            on_disk = await downloads
            if "results.json" in on_disk:
                text = (run.dir / "sandbox" / "results.json").read_bytes().decode("utf-8", errors="replace")
                results = validate_results(text)
            files = dict(on_disk) if results else {}
        return Execution(files, results, tokens, downloads)
    except SandboxError as e:
        run.emit("error", agent="Executor", lane="Sandbox", text=f"Sandbox attempt failed: {e}")
        return Execution(tokens=e.tokens)
    except Exception as e:
        run.emit("error", agent="Executor", lane="Sandbox", text=f"Sandbox attempt failed: {type(e).__name__}: {str(e)[:300]}")
        return Execution(tokens=tokens)


def validate_results(text: str) -> str:
    """The results object re-serialized, if its primary result has finite HR, CI and p; else ""."""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return ""
    primary = obj.get("primary") if isinstance(obj, dict) else None
    if not isinstance(primary, dict):
        return ""
    for key in PRIMARY_NUMBERS:
        value = primary.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            return ""
    return json.dumps(obj, indent=1)


def parse_results(stdout: str) -> str:
    """Validated results from the LAST RESULTS_JSON line only; "" (use the file) if that line is unusable."""
    markers = [line for line in stdout.splitlines() if "RESULTS_JSON " in line]
    return validate_results(markers[-1].split("RESULTS_JSON ", 1)[1].strip()) if markers else ""


def _python_block(text: str) -> str:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


async def _agent(run: Run, prompt: str, max_tokens: int, env_id: str, model: str = ARGON) -> tuple[str, int]:
    """One Antigravity interaction, streaming each code step to the live page. Returns (stdout, tokens).

    Raises SandboxError (with the tokens used, reconciled from the server or reserved in full when unknown)
    on a stream error, a missing or non-completed terminal status, or the mode's deadline.
    """
    run.emit("agent_start", agent="Executor", lane="Sandbox", model=f"{ANTIGRAVITY} · {model}")
    start = time.time()
    final_text, seen = [], {}

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
            if kind == "interaction.created":
                seen["id"] = event.interaction.id
            elif kind == "step.start":
                step = event.step.model_dump(exclude_none=True)
                code = (step.get("arguments") or {}).get("code") or step.get("code")
                if code:
                    run.emit("tool", agent="Executor", lane="Sandbox", text=code, data={"kind": "code"})
            elif kind == "step.delta":
                delta = event.delta.model_dump(exclude_none=True)
                if delta.get("type") == "text":
                    final_text.append(delta.get("text", ""))
            elif kind == "interaction.completed":
                seen["interaction"] = event.interaction
            elif kind == "error":
                raise RuntimeError(f"stream error: {str(getattr(event, 'error', event))[:200]}")

    try:
        await asyncio.wait_for(consume(), AGENT_TIMEOUT[run.mode])
    except Exception as e:
        tokens = await _reconcile(run, seen, max_tokens)
        raise SandboxError(f"{type(e).__name__}: {str(e)[:250]}", tokens) from e

    interaction = seen.get("interaction")
    if interaction is None:
        raise SandboxError("the sandbox agent stream ended without completing", await _reconcile(run, seen, max_tokens))
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
    if interaction.status != "completed":
        raise SandboxError(f"sandbox agent finished with status {interaction.status}", tin + tout)
    return "\n".join(outputs), tin + tout


async def _reconcile(run: Run, seen: dict, max_tokens: int) -> int:
    """Tokens a failed interaction used: from its completion event, else from the server, else the full cap."""
    interaction = seen.get("interaction")
    if interaction is None and seen.get("id"):
        try:
            interaction = await asyncio.wait_for(client().aio.interactions.get(id=seen["id"]), RECONCILE_TIMEOUT)
        except Exception:
            interaction = None
    used = sum(usage_of(interaction)) if interaction is not None else 0
    if interaction is not None and getattr(interaction, "usage", None):
        run.add_usage(*usage_of(interaction))
        return used
    return max_tokens if seen.get("id") else 0  # started but unknown: reserve the whole allowance


async def download(run: Run, env_id: str, paths: dict[str, str], have: dict[str, str]) -> dict[str, str]:
    """Fetch outputs into runs/<id>/sandbox/ (keeping files already saved), cataloguing each that exists."""
    wanted = {name: path for name, path in paths.items() if name not in have}
    found = dict(have)
    blobs = await asyncio.gather(*(fetch(env_id, path) for path in wanted.values()))
    for name, data in zip(wanted, blobs):
        if data is None:
            continue
        run.write(f"sandbox/{name}", data)
        found[name] = run.add_source("file", name, f"sandbox/{name}", "Executor")
        run.emit("tool", agent="Executor", lane="Sandbox", text=f"[{found[name]}] {name}",
                 data={"kind": "file", "path": f"sandbox/{name}"})
    return found
