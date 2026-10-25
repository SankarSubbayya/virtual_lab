# Virtual Lab

A team of 20+ Gemini agents that answers a research question the way a real lab would: it studies
the topic, plans in meetings, critiques the plan, asks a human to approve the cost, runs analysis
code on real data in a Gemini managed-agent sandbox, and then has to beat a single-model answer in
a blind test.

Built at the **Gemini 4 Argon SF Hackathon** (Cerebral Valley × Google DeepMind, 2026-10-25).

## What existed before vs. what we built at the hackathon

**Before the event:** our team had a Virtual Lab prototype (first full run 2026-10-21). It used
Gemma via Ollama for drafts and Claude as the baseline, took about 45 minutes of agent time to reach
a plan, and ran no analysis code on data. Its code is merged into this repo with its original commit
history and dates, so `git log` shows exactly where it ends.

**Built on 2026-10-25 (hackathon):** every commit dated 2026-10-25 in this repository.

- _(updated as features land)_

The idea of a lab made of AI agents (a PI, specialists and a critic meeting to plan) comes from
Swanson et al., *The Virtual Lab* (Nature, 2025).

## Run

```bash
cp .env.example .env   # add GEMINI_API_KEY
uv sync
uv run python scripts/smoke_test.py
```

`.claude/skills/gemini-api-dev/` is Google's Gemini API skill (Apache-2.0, from
[google-gemini/gemini-skills](https://github.com/google-gemini/gemini-skills)), vendored for our coding agents.
