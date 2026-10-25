# Virtual Lab — Gemini 4 Argon SF hackathon (Sun 2026-10-25)

A team of 20+ AI agents that answers a research question the way a real lab would: learn the topic,
plan in meetings, critique, check feasibility, get human approval, run code on real data, then
prove the answer beats a single-model baseline in a blind test. Inspired by Swanson et al.,
"The Virtual Lab" (Nature, 2025). Extends our pre-event prototype; see README for the old/new split.

## Hackathon rules that shape the code

- Repo must be **public**; demo must show **only what we built today**. We extend a pre-event prototype, so keep
  prototype commits (original dates) separate from 2026-10-25 commits and keep the README old/new list current.
- Banned: Streamlit apps, basic RAG, projects where a **dashboard is the main feature**, and
  **AI that generates medical advice**. So: no Streamlit (FastAPI + one HTML page); the live view is a
  window onto the agents, not the product; frame questions as **research** questions for a scientist
  (hypotheses, analyses, citations), never treatment advice for a patient.
- Judges (DeepMind builder guide): a specific problem for a named real person; must *need* Argon
  (multi-agent orchestration, verification loops); humans stay in control of costly actions;
  **runs live with real inputs in under 3 minutes**.
- Prize: "Best use of Managed Agents" ($5K) → Executors run in the Antigravity managed agent.
- Submission: public repo + 1-minute demo video via the Cerebral Valley form.

## Model map

| Role | Model / agent |
|---|---|
| PI, Critic, Plan Reviser, PI_Aggregator, ExecutionSynthesis, AnswerJudge | `gemini-4-argon` (`thinking_level` medium; high only for aggregator) |
| Specialists (Immunologist, ML Specialist, Comp Biologist), school roles, TeamFormation | `gemini-3.8-flash` (run in parallel) |
| Routers / guardrails (TeamReadiness, EvidenceGap decision) | `gemini-3.5-flash-lite` |
| InitialAnswer | `gemma-4-31b-it` via API (local Gemma 4 E4B optional) |
| Librarian / web_research | `deep-research-preview-04-2026` (slow: cache results) |
| PlanFeasibility, Executors | `antigravity-preview-09-2026` with `agent_config={"type": "antigravity", "model": "gemini-4-argon"}` |
| BaselineAnswer (sealed) | `gemini-4-argon` single call, so the claim is "an Argon team beats Argon alone" |

## Demo question and data

A research question over a **public** cohort (TCGA-BRCA or METABRIC via cBioPortal), e.g. "Is immune
infiltration associated with overall survival in TNBC?". The executors fit the model in the sandbox and
report effect sizes. Never commit or demo restricted data (e.g. AURORA), and never output patient care advice.

## Gemini API notes (google-genai 2.33; see `.claude/skills/gemini-api-dev/`)

- Use `client.interactions.create(model=... | agent=..., input=...)`; never `generate_content` or legacy SDKs.
- Argon: put `thinking_level` in `generation_config`; drop `temperature`/`top_p`/`top_k`; hard prompts
  can take minutes, so use 15-minute HTTP timeouts or `background=True` + poll `client.interactions.get(id=...)`.
- Argon is **not on the free tier**: needs the hackathon credits.
- Antigravity: needs `environment=`; data in via `environment={"type": "remote", "sources": [{"type": "inline",
  "content": ..., "target": "/workspace/..."}]}` (1 MB/file) or `client.environments.files.upload`; results out via
  `client.environments.files.download(environment=env_id, path=...)`. Reuse a sandbox by passing
  `environment=<environment_id>`. No structured output and no sampling params on the agent path.
- Multi-turn: `previous_interaction_id`. Streaming: `stream=True`, events `step.start/step.delta/step.stop`.

## Commands

- `uv run python scripts/smoke_test.py [--deep-research]`: check every model/agent and print latencies.
