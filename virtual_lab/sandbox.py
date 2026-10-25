"""Executors on the Antigravity managed agent: a pre-warmed sandbox with the cohort, run on Argon."""

import asyncio
import json
import time
from datetime import datetime, timedelta

from . import agents
from .config import (ANTIGRAVITY, ARGON, CACHE_DIR, DATA_CSV, DATA_DICT, FLASH, SANDBOX_DATA, SANDBOX_DICT,
                     SANDBOX_OUT)
from .llm import client, usage_of
from .notebook import Run

ENV_CACHE = CACHE_DIR / "sandbox.json"
ENV_MAX_AGE = timedelta(days=6)  # environments are kept for 7 days after last use
OUTPUTS = ["results.json", "summary.md", "km.png", "analysis.py"]

SETUP_PROMPT = f"""Run this shell command and reply with only the last line it prints:
pip install -q --break-system-packages lifelines matplotlib pandas && mkdir -p {SANDBOX_OUT} && \
python3 -c "import pandas as pd, lifelines; print('ready', pd.read_csv('{SANDBOX_DATA}').shape, 'lifelines', lifelines.__version__)\""""


async def ensure(run: Run) -> str | None:
    """Return a sandbox with the data and packages installed, reusing a recent one when possible."""
    if ENV_CACHE.exists():
        cached = json.loads(ENV_CACHE.read_text())
        if datetime.now() - datetime.fromisoformat(cached["created"]) < ENV_MAX_AGE:
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


async def execute(run: Run, plan: str, experts: str, max_tokens: int, env_id: str) -> dict:
    """Run the approved plan in the sandbox; stream each code step to the live page; download outputs."""
    prompt = f"First run `rm -rf {SANDBOX_OUT} && mkdir -p {SANDBOX_OUT}`.\n\n" + agents.EXECUTOR_PROMPT.format(
        experts=experts, data=SANDBOX_DATA, dictionary=SANDBOX_DICT, plan=plan, out=SANDBOX_OUT)
    run.emit("agent_start", agent="Executor", lane="Sandbox", model=f"{ANTIGRAVITY} · {ARGON}")
    start = time.time()
    final_text, interaction = [], None
    stream = await client().aio.interactions.create(
        agent=ANTIGRAVITY,
        agent_config={"type": "antigravity", "model": ARGON, "max_total_tokens": max_tokens},
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

    tokens = 0
    if interaction is not None:
        tin, tout = usage_of(interaction)
        run.add_usage(tin, tout)
        tokens = tin + tout
        for step in interaction.steps or []:
            s = step.model_dump(exclude_none=True)
            if s.get("type", "").endswith("_result"):
                out = s.get("result") or s.get("output") or s.get("content")
                if out:
                    run.emit("tool", agent="Executor", lane="Sandbox", text=str(out)[:2000], data={"kind": "output"})

    files = await download(run, env_id)
    run.emit("agent_output", agent="Executor", lane="Sandbox", model=f"{ANTIGRAVITY} · {ARGON}",
             text="".join(final_text) or "(no summary)", ms=int((time.time() - start) * 1000), tokens=tokens,
             data={"status": getattr(interaction, "status", None), "files": list(files)})
    return files


async def download(run: Run, env_id: str) -> dict[str, str]:
    """Fetch the executor's outputs into runs/<id>/sandbox/ and catalogue them. Returns {name: F-id}."""
    found = {}
    for name in OUTPUTS:
        try:
            data = await asyncio.to_thread(client().environments.files.download,
                                           environment=env_id, path=f"{SANDBOX_OUT}/{name}")
        except Exception:
            continue
        run.write(f"sandbox/{name}", data)
        found[name] = run.add_source("file", name, f"sandbox/{name}", "Executor")
        run.emit("tool", agent="Executor", lane="Sandbox", text=f"[{found[name]}] {name}",
                 data={"kind": "file", "path": f"sandbox/{name}"})
    return found
