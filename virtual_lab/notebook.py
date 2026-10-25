"""The shared notebook: one Run holds every agent's output, the event log and the run folder."""

import asyncio
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .config import RUNS_DIR, USD_PER_M_INPUT, USD_PER_M_OUTPUT


class Run:
    def __init__(self, question: str, mode: str = "fast"):
        now = datetime.now()
        self.id = f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        self.question = question
        self.mode = mode
        self.dir = RUNS_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []
        self.notebook: dict = {}
        self.catalog: list[dict] = []
        self.tokens_in = self.tokens_out = 0
        self.done = False
        self._subscribers: list[asyncio.Queue] = []
        self._approval: asyncio.Future | None = None

    # events -------------------------------------------------------------

    def emit(self, type: str, agent: str | None = None, lane: str = "Pipeline", model: str | None = None,
             text: str = "", data: dict | None = None, ms: int | None = None, tokens: int | None = None) -> dict:
        event = {
            "seq": len(self.events), "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.id, "type": type, "agent": agent, "lane": lane, "model": model,
            "text": text, "data": data or {}, "ms": ms, "tokens": tokens,
        }
        self.events.append(event)
        with open(self.dir / "events.jsonl", "a") as f:
            f.write(json.dumps(event) + "\n")
        for q in self._subscribers:
            q.put_nowait(event)
        if type == "final":
            self.done = True
            for q in self._subscribers:
                q.put_nowait(None)
        return event

    async def stream(self):
        """Every event so far, then new ones until the run ends."""
        q: asyncio.Queue = asyncio.Queue()
        backlog = list(self.events)
        self._subscribers.append(q)
        try:
            for event in backlog:
                yield event
            if self.done:
                return
            while (event := await q.get()) is not None:
                if event["seq"] >= len(backlog):
                    yield event
        finally:
            self._subscribers.remove(q)

    def stage(self, text: str):
        self.emit("stage", text=text)

    def handoff(self, src: str, dst: str, key: str, lane: str = "Pipeline"):
        self.emit("handoff", agent=src, lane=lane, text=f"{src} → {dst}", data={"from": src, "to": dst, "key": key})

    # shared state ---------------------------------------------------------

    def set(self, key: str, value):
        self.notebook[key] = value
        self._save("notebook.json", self.notebook)

    def get(self, key: str, default=None):
        return self.notebook.get(key, default)

    def add_source(self, kind: str, title: str, source: str, by: str) -> str:
        prefix = {"evidence": "E", "lesson": "L", "file": "F", "note": "N"}[kind]
        sid = f"{prefix}-{sum(1 for c in self.catalog if c['kind'] == kind) + 1:03d}"
        self.catalog.append({"id": sid, "kind": kind, "title": title, "source": source, "by": by})
        self._save("catalog.json", self.catalog)
        return sid

    def add_usage(self, tokens_in: int, tokens_out: int):
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

    @property
    def cost_usd(self) -> float:
        return (self.tokens_in * USD_PER_M_INPUT + self.tokens_out * USD_PER_M_OUTPUT) / 1e6

    def write(self, name: str, content: str | bytes) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content) if isinstance(content, bytes) else path.write_text(content)
        return path

    def _save(self, name: str, obj):
        (self.dir / name).write_text(json.dumps(obj, indent=2, default=str))

    # human approval -----------------------------------------------------

    def request_approval(self, text: str, data: dict) -> asyncio.Future:
        """Emit the approval card; the future resolves when a person (or --auto-approve) decides."""
        self._approval = asyncio.get_running_loop().create_future()
        self.emit("approval_request", agent="BudgetAndApprovalAgent", text=text, data=data)
        return self._approval

    def resolve_approval(self, approved: bool) -> bool:
        if self._approval is None or self._approval.done():
            return False
        self._approval.set_result(approved)
        return True
