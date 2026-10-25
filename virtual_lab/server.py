"""Live page server: uv run uvicorn virtual_lab.server:app --port 8010"""

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .config import RUNS_DIR
from .notebook import Run
from .pipeline import run_lab

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="Virtual Lab")
WEB = Path(__file__).parent / "web"
runs: dict[str, Run] = {}
tasks: set[asyncio.Task] = set()


class StartRun(BaseModel):
    question: str
    mode: str = "fast"
    auto_approve: bool = False


class Decision(BaseModel):
    approved: bool


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.post("/api/runs")
async def start_run(body: StartRun):
    run = Run(body.question.strip(), body.mode if body.mode in ("fast", "full") else "fast")
    runs[run.id] = run
    task = asyncio.create_task(run_lab(run, auto_approve=body.auto_approve))
    tasks.add(task)
    task.add_done_callback(lambda t: (tasks.discard(t), _report_crash(run, t)))
    return {"run_id": run.id}


def _report_crash(run: Run, task: asyncio.Task):
    if not task.cancelled() and task.exception() and not run.done:
        run.emit("error", text=f"Run stopped: {type(task.exception()).__name__}: {task.exception()}")
        run.emit("final", text="The run stopped with an error.",
                 data={"answer": "", "baseline": "", "lab_wins": False, "files": []})


@app.get("/api/runs")
def list_runs():
    """Past runs on disk, newest first (for replaying a recorded run)."""
    return [p.parent.name for p in sorted(RUNS_DIR.glob("*/events.jsonl"), reverse=True)]


@app.get("/api/runs/{run_id}/events")
async def events(run_id: str):
    run = runs.get(run_id)
    log = RUNS_DIR / run_id / "events.jsonl"
    if run is None and not log.exists():
        raise HTTPException(404, "unknown run")

    async def sse():
        source = run.stream() if run else _replay(log)
        async for event in source:
            yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
        while True:  # keep the stream open so the browser does not reconnect and replay
            yield ": done\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _replay(log: Path):
    for line in log.read_text().splitlines():
        yield json.loads(line)


@app.post("/api/runs/{run_id}/approve")
def approve(run_id: str, body: Decision):
    run = runs.get(run_id)
    if run is None or not run.resolve_approval(body.approved):
        raise HTTPException(409, "no approval pending for this run")
    return {"ok": True}


@app.get("/api/runs/{run_id}/files/{path:path}")
def files(run_id: str, path: str):
    base = (RUNS_DIR / run_id).resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(target)
