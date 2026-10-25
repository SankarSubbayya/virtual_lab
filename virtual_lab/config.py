from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_CSV = DATA_DIR / "metabric.csv"
DATA_DICT = DATA_DIR / "metabric_dictionary.md"
CACHE_DIR = DATA_DIR / "cache"  # lessons and research reused by fast mode
RUNS_DIR = ROOT / "runs"

ARGON = "gemini-4-argon"
FLASH = "gemini-3.8-flash"
LITE = "gemini-3.5-flash-lite"
GEMMA = "gemma-4-31b-it"
ANTIGRAVITY = "antigravity-preview-09-2026"
DEEP_RESEARCH = "deep-research-preview-04-2026"

# Argon list prices through 2026-11-30, used as an upper bound for every estimate
USD_PER_M_INPUT = 2.0
USD_PER_M_OUTPUT = 10.0

SANDBOX_DATA = "/workspace/data/metabric.csv"
SANDBOX_DICT = "/workspace/data/metabric_dictionary.md"
SANDBOX_OUT = "/workspace/out"

MODES = {
    # critic rounds per track, school/research live or cached, judge revise loop
    "fast": {"critic_rounds": 1, "live_school": False, "deep_research": False, "judge_retries": 0},
    "full": {"critic_rounds": 4, "live_school": True, "deep_research": True, "judge_retries": 2},
}
