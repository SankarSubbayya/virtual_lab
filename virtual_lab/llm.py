"""Gemini calls for every agent: retries, timeouts, JSON output and event logging."""

import asyncio
import json
import time

from google import genai

from .config import ARGON, FLASH, GEMMA
from .notebook import Run

_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        # transport backstop (ms, per network operation); callers also enforce their own total deadlines
        _client = genai.Client(http_options={"timeout": 300_000})
    return _client


async def together(*coros) -> list:
    """Run coroutines concurrently; if one raises, the rest are cancelled (no orphaned siblings)."""
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(c) for c in coros]
    return [t.result() for t in tasks]


def usage_of(interaction) -> tuple[int, int]:
    u = getattr(interaction, "usage", None)
    if not u:
        return 0, 0
    out = (u.total_output_tokens or 0) + (u.total_thought_tokens or 0)
    return u.total_input_tokens or 0, out


async def ask(run: Run, agent: str, model: str, prompt: str, *, lane: str = "Pipeline", system: str | None = None,
              thinking: str | None = None, schema: dict | None = None, tools: list | None = None,
              timeout: float = 120, retries: int = 2, show: bool | str = True):
    """Run one agent turn. Returns text, a dict when `schema` is given, or None if every attempt failed."""
    run.emit("agent_start", agent=agent, lane=lane, model=model)
    kwargs: dict = {"model": model, "input": prompt}
    if system:
        if model == GEMMA:
            kwargs["input"] = f"{system}\n\n{prompt}"
        else:
            kwargs["system_instruction"] = system
    if model == FLASH and thinking is None and run.mode == "fast":
        thinking = "low"  # Flash's default thinking doubles latency for little gain on these short turns
    if thinking and model in (ARGON, FLASH):
        kwargs["generation_config"] = {"thinking_level": thinking}
    if schema:
        kwargs["response_format"] = {"type": "text", "mime_type": "application/json", "schema": schema}
    if tools:
        kwargs["tools"] = tools

    start = time.time()
    tokens = 0
    for attempt in range(retries + 1):
        try:
            interaction = await asyncio.wait_for(client().aio.interactions.create(**kwargs), timeout)
            tin, tout = usage_of(interaction)  # billed even if the reply is rejected below
            run.add_usage(tin, tout)
            tokens += tin + tout
            text = interaction.output_text or ""
            if interaction.status not in (None, "completed") or not text.strip():
                raise ValueError(f"no usable output (status {interaction.status})")
            result = json.loads(text) if schema else text
            if schema:
                check(result, schema)
            break
        except Exception as e:  # retry anything: timeouts, 429/5xx, empty, malformed or off-schema JSON
            if attempt == retries:
                run.emit("error", agent=agent, lane=lane, model=model, text=f"{type(e).__name__}: {str(e)[:300]}",
                         ms=int((time.time() - start) * 1000))
                return None
            run.emit("error", agent=agent, lane=lane, model=model,
                     text=f"retrying after {type(e).__name__}: {str(e)[:160]}", data={"attempt": attempt + 1})
            if "generation_config" in kwargs:  # Argon at medium/high sometimes returns malformed_tool_call
                kwargs["generation_config"] = {"thinking_level": "low"}
            await asyncio.sleep(2 * (attempt + 1))

    run.emit("agent_output", agent=agent, lane=lane, model=model,
             text=render(result) if show is True else (show or "(sealed until the blind test)"),
             data=result if isinstance(result, dict) else {}, ms=int((time.time() - start) * 1000), tokens=tokens)
    return result


def check(value, schema: dict, where: str = "output"):
    """Minimal JSON-schema check (type, required, enum, items) so callers can index results safely."""
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float)}
    if kind in types and (not isinstance(value, types[kind]) or (kind in ("integer", "number") and isinstance(value, bool))):
        raise ValueError(f"{where}: expected {kind}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{where}: {value!r} not in {schema['enum']}")
    if kind == "object":
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{where}: missing {key}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                check(value[key], sub, f"{where}.{key}")
    if kind == "array":
        for i, item in enumerate(value):
            check(item, schema.get("items", {}), f"{where}[{i}]")


def render(result) -> str:
    """Readable markdown for the live page; JSON outputs become short field lists."""
    if not isinstance(result, dict):
        return result
    lines = []
    for k, v in result.items():
        label = k.replace("_", " ").capitalize()
        if isinstance(v, list):
            lines.append(f"**{label}:**")
            lines += [f"- {json.dumps(i) if isinstance(i, dict) else i}" for i in v]
        else:
            lines.append(f"**{label}:** {v}")
    return "\n".join(lines)
