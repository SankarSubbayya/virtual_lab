# Virtual Lab

A team of 20+ Gemini agents that answers a research question the way a real lab would: it studies
the topic, plans in meetings, critiques the plan, asks a human to approve the cost, runs analysis
code on real data in a Gemini managed-agent sandbox, and then has to beat a single-model answer in
a blind test.

Built at the **Gemini 4 Argon SF Hackathon** (Cerebral Valley × Google DeepMind, 2026-10-25).

## What existed before vs. what we built at the hackathon

**Before the event:** our team had a Virtual Lab prototype (first full run 2026-10-21). It used
Gemma via Ollama for drafts and Claude as the baseline, took about 45 minutes of agent time to reach
a plan, and ran no analysis code on data. We kept its agent design (the roles and the relay) but none
of its code: this repository was written from scratch on 2026-10-25.

**Built on 2026-10-25 (hackathon):** everything in this repository (see `git log`).

- The whole relay on the Gemini Interactions API: 20+ agents from `CaptureOriginalRequest` to `AnswerJudge`
  ([virtual_lab/pipeline.py](virtual_lab/pipeline.py), prompts in [virtual_lab/agents.py](virtual_lab/agents.py)).
  Argon leads (PI, Critic, PI_Aggregator, synthesis, judge); Flash runs the specialists and school in parallel;
  Flash-Lite routes; Gemma 4 writes the first draft.
- **Executors on Gemini Managed Agents**: the Antigravity agent runs Argon in a pre-warmed Google sandbox
  holding the cohort, writes and runs the survival analysis, and returns `results.json`, a Kaplan–Meier plot and
  its code ([virtual_lab/sandbox.py](virtual_lab/sandbox.py)). The budget a human approves becomes the agent's
  `max_total_tokens` cap.
- **ScopeGuard**: patient-care questions are not answered as asked; the lab answers the closest research question.
- **Blind test against Argon alone**: judged twice with the order swapped.
- **Fast mode** (< 3 minutes live): lessons and literature searches are cached and reused; full mode runs the
  school and Deep Research live.
- Public data: METABRIC via the cBioPortal API ([virtual_lab/data.py](virtual_lab/data.py)).
- Live page: FastAPI + server-sent events, every hand-off as it happens, with the approval card.

The idea of a lab made of AI agents (a PI, specialists and a critic meeting to plan) comes from
Swanson et al., *The Virtual Lab* (Nature, 2025).

## Run

```bash
cp .env.example .env                 # add GEMINI_API_KEY (Argon needs a paid tier)
uv sync
uv run python -m virtual_lab.data    # fetch METABRIC from cBioPortal into data/
uv run python -m virtual_lab --auto-approve           # CLI, demo question, fast mode
uv run uvicorn virtual_lab.server:app --port 8000     # live page at http://localhost:8000
```

`uv run python scripts/smoke_test.py` checks every model and the sandbox. Each run writes
`runs/<id>/` with `events.jsonl`, `notebook.json`, `catalog.json`, `answer.md` and the sandbox outputs.

Data: METABRIC (Curtis et al. Nature 2012; Pereira et al. Nat Commun 2016; Rueda et al. Nature 2019),
from [cBioPortal](https://www.cbioportal.org/study/summary?id=brca_metabric). This is a research tool;
it does not give medical advice.

`.claude/skills/gemini-api-dev/` is Google's Gemini API skill (Apache-2.0, from
[google-gemini/gemini-skills](https://github.com/google-gemini/gemini-skills)), vendored for our coding agents.
