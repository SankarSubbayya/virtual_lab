"""Executors on the Antigravity managed agent: a pre-warmed sandbox with the cohort, run on Argon."""

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import agents
from .config import (ANTIGRAVITY, ARGON, CACHE_DIR, DATA_CSV, DATA_DICT, FLASH, SANDBOX_DATA, SANDBOX_DICT,
                     SANDBOX_OUT)
from .llm import ask, client, usage_of
from .notebook import Run

ENV_CACHE = CACHE_DIR / "sandbox.json"
ENV_MAX_AGE = timedelta(days=6)  # environments are kept for 7 days after last use
OUTPUTS = ["results.json", "summary.md", "km.png", "analysis.py"]
SCRIPT = "/workspace/run/analysis.py"  # fast mode: written by Argon, uploaded, run by the agent

SETUP_PROMPT = f"""Run this shell command and reply with only the last line it prints:
pip install -q --break-system-packages lifelines matplotlib pandas && mkdir -p {SANDBOX_OUT} && \
python3 -c "import pandas as pd, lifelines; print('ready', pd.read_csv('{SANDBOX_DATA}').shape, 'lifelines', lifelines.__version__)\""""


async def ensure(run: Run) -> str | None:
    """Return a sandbox with the data and packages installed, reusing a recent one when possible."""
    if ENV_CACHE.exists():
        cached = json.loads(ENV_CACHE.read_text())
        if datetime.now() - datetime.fromisoformat(cached["created"]) < ENV_MAX_AGE:
            try:  # wakes the snapshotted sandbox now, and fails fast if it has expired
                await asyncio.to_thread(client().environments.files.upload, environment=cached["id"],
                                        path="/workspace/run/.wake", file=b"1", overwrite=True)
            except Exception:
                return await create(run)
            run.emit("agent_output", agent="SandboxSetup", lane="Sandbox", model=ANTIGRAVITY,
                     text=f"Reusing pre-warmed sandbox `{cached['id']}` (METABRIC + lifelines installed).")
            return cached["id"]
    return await create(run)


async def create(run: Run) -> str | None:
    run.emit("agent_start", agent="SandboxSetup", lane="Sandbox", model=ANTIGRAVITY)
    start = time.time()
    try:
        interaction = await client().aio.interactions.create(
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
        )
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
        experts=experts, plan=plan, data=SANDBOX_DATA, dictionary=DATA_DICT.read_text(), out=SANDBOX_OUT),
        system=agents.LAB_RULES, thinking="low", lane="Sandbox",
        show="Wrote `analysis.py` for the sandbox (code below). It runs only after approval.")
    code = _python_block(reply or "")
    if code:
        run.emit("tool", agent="ExecutorCoder", lane="Sandbox", text=code, data={"kind": "code"})
    return code or None


@dataclass
class Execution:
    files: dict[str, str]  # output name -> catalogue ID
    results: str  # results.json text ("" if the run produced none)
    downloads: asyncio.Task  # resolves to {name: ID} for the files now in runs/<id>/sandbox/


async def execute(run: Run, plan: str, experts: str, max_tokens: int, env_id: str,
                  code: str | None = None) -> Execution:
    """Run the approved plan in the sandbox.

    With `code` (fast mode): upload it and the sandbox agent runs it, fixing only if it fails; the script
    prints its results on stdout, so synthesis can start while the files download in the background.
    Without (full mode): the sandbox agent on Argon writes, runs and iterates on its own.
    """
    clean = f"First run `rm -rf {SANDBOX_OUT} && mkdir -p {SANDBOX_OUT}`.\n\n"
    paths = {name: f"{SANDBOX_OUT}/{name}" for name in OUTPUTS}
    if code:
        await asyncio.to_thread(client().environments.files.upload, environment=env_id, path=SCRIPT,
                                file=code.encode(), overwrite=True)
        stdout = await _agent(run, clean + agents.RUNNER_PROMPT.format(script=SCRIPT, data=SANDBOX_DATA, out=SANDBOX_OUT),
                              max_tokens, env_id, model=FLASH)  # only runs Argon's script
        paths["analysis.py"] = SCRIPT
    else:
        stdout = await _agent(run, clean + agents.EXECUTOR_PROMPT.format(
            experts=experts, data=SANDBOX_DATA, dictionary=SANDBOX_DICT, plan=plan, out=SANDBOX_OUT), max_tokens, env_id)

    ids = {name: run.add_source("file", name, f"sandbox/{name}", "Executor") for name in paths}
    downloads = asyncio.create_task(download(run, env_id, paths, ids))
    found = re.search(r"RESULTS_JSON (\{.*\})", stdout)
    if found:
        return Execution(ids, found.group(1), downloads)
    on_disk = await downloads
    results = (run.dir / "sandbox" / "results.json").read_text() if "results.json" in on_disk else ""
    return Execution(ids, results, downloads)


def _python_block(text: str) -> str:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


async def _agent(run: Run, prompt: str, max_tokens: int, env_id: str, model: str = ARGON):
    """One Antigravity interaction, streaming each code step to the live page."""
    run.emit("agent_start", agent="Executor", lane="Sandbox", model=f"{ANTIGRAVITY} · {model}")
    start = time.time()
    final_text, interaction = [], None
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
            interaction = event.interaction

    tokens, outputs = 0, []
    if interaction is not None:
        tin, tout = usage_of(interaction)
        run.add_usage(tin, tout)
        tokens = tin + tout
        for step in interaction.steps or []:
            s = step.model_dump(exclude_none=True)
            if s.get("type", "").endswith("_result"):
                out = s.get("result") or s.get("output") or s.get("content")
                if out:
                    outputs.append(str(out))
                    run.emit("tool", agent="Executor", lane="Sandbox", text=str(out)[:2000], data={"kind": "output"})
    run.emit("agent_output", agent="Executor", lane="Sandbox", model=f"{ANTIGRAVITY} · {model}",
             text="".join(final_text) or "(no summary)", ms=int((time.time() - start) * 1000), tokens=tokens,
             data={"status": getattr(interaction, "status", None)})
    return "\n".join(outputs)


async def download(run: Run, env_id: str, paths: dict[str, str], ids: dict[str, str]) -> dict[str, str]:
    """Fetch the executor's outputs into runs/<id>/sandbox/. Returns {name: ID} for the files found."""
    found = {}

    async def fetch(path):
        try:
            return await asyncio.to_thread(client().environments.files.download, environment=env_id, path=path)
        except Exception:
            return None

    blobs = await asyncio.gather(*(fetch(path) for path in paths.values()))
    for name, data in zip(paths, blobs):
        if data is None:
            continue
        run.write(f"sandbox/{name}", data)
        found[name] = ids[name]
        run.emit("tool", agent="Executor", lane="Sandbox", text=f"[{found[name]}] {name}",
                 data={"kind": "file", "path": f"sandbox/{name}"})
    return found
