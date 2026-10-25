"""CLI: uv run python -m virtual_lab "<question>" [--mode fast|full] [--auto-approve]"""

import argparse
import asyncio
import time

from dotenv import load_dotenv

from .notebook import Run
from .pipeline import run_lab

DEMO_QUESTION = ("In triple-negative breast cancer, is higher cytotoxic immune infiltration associated with "
                 "longer overall survival, independent of age, stage and grade?")


async def follow(run: Run, start: float, auto: bool):
    async for e in run.stream():
        t = f"{time.time() - start:6.1f}s"
        first = (e["text"] or "").strip().splitlines()[0][:110] if e["text"] else ""
        if e["type"] == "stage":
            print(f"\n{t} ══ {e['text']}")
        elif e["type"] in ("agent_output", "verdict", "error", "approval"):
            took = f" ({e['ms'] / 1000:.1f}s)" if e["ms"] else ""
            print(f"{t} [{e['lane']:<8}] {e['agent']}{took}: {first}")
        elif e["type"] == "tool":
            print(f"{t} [{e['lane']:<8}] {e['agent']} · {e['data'].get('kind')}: {first}")
        elif e["type"] == "approval_request":
            print(f"\n{t} APPROVAL NEEDED: {e['text']}\n\n{e['data']['plan']}\n")
            if not auto:
                answer = await asyncio.to_thread(input, "Approve? [y/N] ")
                run.resolve_approval(answer.strip().lower().startswith("y"))
        elif e["type"] == "final":
            d = e["data"]
            print(f"\n{t} ══ {e['text']} · {d.get('elapsed_s')}s · {d.get('tokens')} tokens · ~${d.get('cost_usd')}")
            print(f"\nAnswer and files in {run.dir}")


async def main():
    parser = argparse.ArgumentParser(description="Run the Virtual Lab on a research question.")
    parser.add_argument("question", nargs="?", default=DEMO_QUESTION)
    parser.add_argument("--mode", choices=["fast", "full"], default="fast")
    parser.add_argument("--auto-approve", action="store_true")
    args = parser.parse_args()

    run = Run(args.question, args.mode)
    start = time.time()
    print(f"Run {run.id} ({args.mode} mode) → {run.dir}")
    await asyncio.gather(run_lab(run, auto_approve=args.auto_approve), follow(run, start, args.auto_approve))


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
