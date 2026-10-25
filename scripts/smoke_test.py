"""Smoke-test every model and managed agent the Virtual Lab depends on.

Run after claiming hackathon credits:  uv run python scripts/smoke_test.py [--deep-research]
Prints latency per call so we can budget the <3 minute live demo.
"""

import argparse
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

OUT = Path("runs/smoke")
SAMPLE_CSV = "group,value\nA,1.0\nA,2.0\nB,5.0\nB,7.0\nC,3.0\n"


def timed(label, fn):
    start = time.time()
    try:
        result = fn()
        print(f"[ OK ] {label:<34} {time.time() - start:6.1f}s  {str(result)[:90]!r}")
        return result
    except Exception as e:  # report and keep going so one bad model doesn't hide the others
        print(f"[FAIL] {label:<34} {time.time() - start:6.1f}s  {type(e).__name__}: {e}")
        return None


def text_call(client, model, **gen):
    def run():
        kwargs = {"generation_config": gen} if gen else {}
        return client.interactions.create(model=model, input="Reply with exactly: OK", **kwargs).output_text
    return run


def antigravity_call(client):
    def run():
        interaction = client.interactions.create(
            agent="antigravity-preview-09-2026",
            agent_config={"type": "antigravity", "model": "gemini-4-argon"},
            input=(
                "Using pandas, read /workspace/data/sample.csv, compute the mean of `value` per `group`, "
                "write the table to /workspace/out/summary.csv and print it."
            ),
            environment={
                "type": "remote",
                "sources": [{"type": "inline", "content": SAMPLE_CSV, "target": "/workspace/data/sample.csv"}],
            },
        )
        data = client.environments.files.download(
            environment=interaction.environment_id, path="/workspace/out/summary.csv"
        )
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "summary.csv").write_bytes(data)
        return f"env={interaction.environment_id} downloaded {len(data)} bytes; agent said: {interaction.output_text}"
    return run


def deep_research_call(client):
    def run():
        interaction = client.interactions.create(
            agent="deep-research-preview-04-2026",
            input="In two paragraphs with citations: what is the Stanford 'Virtual Lab' multi-agent system (Swanson et al.)?",
            background=True,
        )
        while interaction.status in ("in_progress", "queued"):
            time.sleep(10)
            interaction = client.interactions.get(id=interaction.id)
        return f"{interaction.status}: {interaction.output_text}"
    return run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep-research", action="store_true", help="also test the (slow) Deep Research agent")
    args = parser.parse_args()

    client = genai.Client()
    timed("gemini-4-argon (thinking low)", text_call(client, "gemini-4-argon", thinking_level="low"))
    timed("gemini-3.8-flash", text_call(client, "gemini-3.8-flash"))
    timed("gemini-3.5-flash-lite", text_call(client, "gemini-3.5-flash-lite"))
    timed("gemma-4-31b-it", text_call(client, "gemma-4-31b-it"))
    timed("antigravity + argon (CSV in/out)", antigravity_call(client))
    if args.deep_research:
        timed("deep-research-preview-04-2026", deep_research_call(client))


if __name__ == "__main__":
    main()
