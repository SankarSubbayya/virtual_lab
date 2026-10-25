# PRD — Virtual Lab (Gemini 4 Argon SF hackathon, 2026-10-25)

Status: building · Owner: team · Schedule and checklist: [PLAN.md](PLAN.md)

## 1. Problem

A cancer researcher with a public cohort and a hypothesis needs a tested, cited answer. Getting there
today means a literature review, an analysis plan, someone to poke holes in it, and code run against the
data, which takes days. A single LLM answer is fast but untested: it cites papers and never touches the
data.

**User:** a translational cancer researcher (our teammate is one) who asks a research question about a
cohort they can share with the lab.

## 2. Product

A team of 20+ Gemini agents that works like a lab. It learns the topic, plans in three independent
meetings, critiques and revises, checks the plan against the data, asks a human to approve the budget,
runs the analysis in a Gemini managed-agent sandbox, writes an answer that separates published evidence
from what the data shows, and then has to beat Argon answering alone in a blind test.

### Goals
- G1. Answer a research question with **numbers computed from the real data** plus citations.
- G2. Prove the lift: lab answer beats a sealed single-call Argon answer in a blind, order-swapped judge.
- G3. Keep a human in control: no sandbox spend without approval; the approved budget is enforced.
- G4. Run live end to end with real inputs in **under 3 minutes** (fast mode).
- G5. Make every hand-off visible as it happens.

### Non-goals
- Patient care, diagnosis, treatment or dosing advice (hackathon ban, and not our user's job).
- Restricted or private patient data; only public cohorts.
- A general chatbot, a RAG app, or a dashboard as the product.

## 3. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | `python -m virtual_lab "<question>" [--mode fast\|full] [--auto-approve]` runs the lab from the CLI. |
| FR-2 | `uvicorn virtual_lab.server:app` serves the live page; a run can be started, watched and approved there. |
| FR-3 | **CaptureOriginalRequest** stores the exact question; every agent reads it from the notebook. |
| FR-4 | **ScopeGuard** classifies the question. Patient-care questions are not answered as asked: the lab says so and proceeds with a research reframing. |
| FR-5 | **InitialAnswer** (Gemma) and **BaselineAnswer** (Argon, single call) run at the start in the background. The baseline is sealed until the judge. |
| FR-6 | **TeamReadinessAgent** decides if the team knows the topic. If not, the **school** runs: Curriculum → Librarian → Teacher → Student → Grader (repeat ≤2 on fail) → LessonWriter. Lessons are cited, saved, and reused next time. |
| FR-7 | **EvidenceGapAgent** decides what the dataset can and cannot answer and sends **web_research** for literature; findings are cited and catalogued. |
| FR-8 | Three planning tracks run in parallel. Each: **PI** frames, **Immunologist**, **ML Specialist**, **Computational Biologist** add ideas, PI writes a plan, **Critic** attacks, **PlanReviser** fixes (fast: 1 round, full: ≤4). |
| FR-9 | **PI_Aggregator** merges the three plans into one. |
| FR-10 | **PlanFeasibilityAgent** checks every variable the plan needs against the real dataset columns in code, and cuts what is impossible. |
| FR-11 | **BudgetAndApprovalAgent** estimates tokens and cost and waits for a human. Approve sets the executor's `max_total_tokens`; reject ends the run. |
| FR-12 | **TeamFormationAgent** picks the experts to hire (e.g. Survival Analyst); they brief the executor. |
| FR-13 | **Executors** run in the Antigravity managed agent on `gemini-4-argon`, in a sandbox pre-warmed with the data. They write and run Python and return `results.json`, figures and the code. Every sandbox step is logged. |
| FR-14 | **ExecutionSynthesisAgent** writes the final answer: what the research says, what the data shows (with effect sizes and CIs), what changed from Gemma's draft, and limitations. No treatment advice. |
| FR-15 | **AnswerJudge** compares lab vs baseline twice with the order swapped, blind to which is which. Full mode: if the lab does not win, it revises and retries (≤2). |
| FR-16 | Every run writes `runs/<id>/` with `events.jsonl`, `notebook.json`, `catalog.json`, sandbox outputs and `answer.md`. |
| FR-17 | Any agent failure is retried with backoff, then recorded and skipped; the run never crashes on one agent. |

## 4. Models

| Role | Model |
|---|---|
| PI, Critic, PI_Aggregator, ExecutionSynthesis, AnswerJudge, BaselineAnswer | `gemini-4-argon` |
| Specialists, PlanReviser, school roles, TeamFormation, Feasibility mapping | `gemini-3.8-flash` |
| ScopeGuard, TeamReadiness, EvidenceGap decisions | `gemini-3.5-flash-lite` |
| InitialAnswer | `gemma-4-31b-it` |
| Librarian / web_research | full: `deep-research-preview-04-2026`; fast: Flash + `google_search` tool, or cache |
| Executors, sandbox pre-warm | `antigravity-preview-09-2026` with `agent_config={"type": "antigravity", "model": "gemini-4-argon", "max_total_tokens": <approved>}` |

## 5. Data

METABRIC (Curtis 2012, Pereira 2016, Rueda 2019), fetched from the public cBioPortal API by
`python -m virtual_lab.data` into `data/metabric.csv` (not committed) with a data dictionary. All
patients with receptor status, survival (OS, RFS), clinical covariates and immune-gene expression; the
lab itself must define the TNBC subset (ER−, PR−, HER2−: 320 patients, 168 deaths).

Demo question: *"In triple-negative breast cancer, is higher cytotoxic immune infiltration associated
with longer overall survival, independent of age, stage and grade?"*

## 6. Live page

One HTML page (no Streamlit). A question box and a fast/full toggle; lanes for Pipeline, School,
Research, Track A/B/C, Sandbox and Judge, filled live from server-sent events; an **approval card** with
the estimate and Approve / Reject; the sandbox's code and figures; and at the end the lab answer next to
the baseline with the judge's verdicts. It is a window onto the agents, not the product.

### Event schema (one JSON object per line in `events.jsonl`, streamed as SSE)

```json
{"seq": 12, "ts": "2026-10-25T11:20:03.120Z", "run_id": "20261025-112000-ab12",
 "type": "agent_start | agent_output | handoff | tool | stage | approval_request | approval | error | final | verdict",
 "agent": "PI_A", "lane": "Pipeline | School | Research | Track A | Track B | Track C | Sandbox | Judge",
 "model": "gemini-4-argon", "text": "markdown body", "data": {}, "ms": 5321, "tokens": 1830}
```

- `approval_request.data`: `{"est_tokens": int, "est_cost_usd": float, "plan": str}`
- `verdict.data`: `{"order": "lab_first|baseline_first", "winner": "lab|baseline|tie", "scores": {...}, "reason": str}`
- `final.data`: `{"answer": str, "baseline": str, "lab_wins": bool, "files": [str]}`

API: `POST /api/runs {question, mode}` → `{run_id}`; `GET /api/runs/{id}/events` (SSE, replays from
the start); `POST /api/runs/{id}/approve {approved: bool}`; `GET /api/runs/{id}/files/{path}`.

## 7. Non-functional

| | Target |
|---|---|
| Latency | fast mode < 180 s wall clock, question to verdict, including a human click |
| Cost | approval shows an estimate at Argon rates ($2 / $10 per 1M in/out); executor capped |
| Safety | ScopeGuard on input; synthesis prompt forbids care advice; public data only |
| Reliability | retries with backoff; per-agent timeouts; a recorded run can be replayed |
| Provenance | every claim in the answer tagged as "from published evidence" or "from the data" with source IDs |

## 8. Acceptance (demo day)

1. The demo question in fast mode finishes in < 3 min three times in a row, with a real hazard ratio and CI from the sandbox.
2. The lab beats the baseline in both judge orderings on the demo question.
3. A patient-care question is caught by ScopeGuard and reframed.
4. Reject at the approval card stops the run before any sandbox spend.
5. A fresh clone runs with only `GEMINI_API_KEY` set.
