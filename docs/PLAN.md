# Hackathon plan — Virtual Lab on Gemini 4 Argon

Sun 2026-10-25 · Gemini 4 Argon SF (Cerebral Valley × Google DeepMind) · plan written 11:00 AM.
Times assume a **5:00 PM submission cutoff**; confirm the real one at kickoff and shift everything.

## The pitch (one breath)

A cancer researcher has a public cohort and a hypothesis. Today, getting from question to a tested,
cited analysis takes days. Our Virtual Lab is a team of Gemini agents (a PI, specialists, a critic,
executors) that plans the study, gets a human to approve the cost, **runs the analysis on the real data in
a Gemini managed-agent sandbox**, and must then beat Argon answering alone in a blind test, live, in
under 3 minutes.

## Requirements → how we satisfy them

| Requirement | How | Status |
|---|---|---|
| Public repo | github.com/SankarSubbayya/virtual_lab | ✅ |
| Team of 1–4, all added to the submission | list members at submit time | ☐ |
| Demo shows only work built today | prototype history merged with original dates; README old/new list; video says "built today" | ☐ |
| New work only | same, plus disclose the prototype and ask a mentor at kickoff | ☐ |
| Not "AI medical advice" | research questions on cohorts only; intake **scope guard** turns patient-care questions into research questions; synthesis forbids treatment/dosing advice | ☐ |
| Not Streamlit, not dashboard-as-product | FastAPI + one HTML page; the product is the verified answer, the page is a window onto the agents | ☐ |
| Rights to code/data | METABRIC via cBioPortal API (public, cited); fetched by script, not committed; Gemini skill is Apache-2.0 | ✅ verified |
| Judges: named user with a specific problem | the researcher above; the question below | ☐ |
| Judges: needs Argon | Argon leads (PI, critic, aggregator, judge) and orchestrates Flash sub-agents; verification loops (critic, feasibility, blind judge) | ☐ |
| Judges: human in control | BudgetAndApproval gate: the approved budget becomes the executor's `max_total_tokens` cap | ☐ |
| Judges: live, real inputs, < 3 min | fast mode (below), pre-warmed sandbox, recorded full run as backup | ☐ |
| Prize: Best use of Managed Agents | executors are a custom Antigravity agent running Argon; audit trail of every sandbox command in the live view | ☐ |
| Submission: 1-min video + form | script below; record from 3:30 PM | ☐ |

## Demo scenario

**Question:** "In triple-negative breast cancer, is higher cytotoxic immune infiltration associated with
longer overall survival, independent of age, stage and grade?"

**Data:** METABRIC (Curtis 2012, Pereira 2016, Rueda 2019) via the cBioPortal API. Verified 11:00 AM:
320 TNBC patients (ER−/PR−/HER2−), 168 deaths, all with expression for CD8A, GZMA, PRF1, CD274, CXCL13.

**Why the lab should win the blind test:** Argon alone can only cite literature. The lab returns hazard
ratios with confidence intervals and a Kaplan–Meier figure computed from 320 real patients, plus the
literature, plus what changed from Gemma's first draft. The prototype lost to Claude 15–25 because it
never ran code on data, and this fixes exactly that.

## Pipeline and models

Fast mode is what judges see live; full mode runs every agent (used for the video and real use).

| Stage | Agents | Model | Fast mode | Budget |
|---|---|---|---|---|
| Intake | CaptureOriginalRequest, ScopeGuard | code, `gemini-3.5-flash-lite` | same | 2 s |
| Drafts | InitialAnswer ∥ BaselineAnswer (sealed) | `gemma-4-31b-it` ∥ `gemini-4-argon` | run in background | (≤40 s, overlapped) |
| School | TeamReadiness → Curriculum, Librarian, Teacher, Student, Grader, LessonWriter | flash-lite; `gemini-3.8-flash`; Librarian = Deep Research | reuse cached lesson | 2 s |
| Fact-check | EvidenceGap, web_research | flash-lite; Deep Research | reuse cached evidence | 3 s |
| Planning ×3 tracks ∥ | PI, Immunologist, ML Specialist, Comp Biologist, Critic, PlanReviser | PI/Critic Argon (`thinking_level` low); specialists Flash ∥ | 1 critic round (full: up to 4) | 60 s |
| Merge | PI_Aggregator | Argon medium | same | 20 s |
| Checks | PlanFeasibility, BudgetAndApproval | code check of dataset columns + Flash; **human click** | same | 10 s |
| Work | TeamFormation, Executors | Flash; **custom Antigravity agent on Argon** in a pre-warmed sandbox | same | 60 s |
| Answer | ExecutionSynthesis | Argon | same | 15 s |
| Blind test | AnswerJudge ×2 (order swapped, ∥) | Argon low | no revise loop (full: revise and retry) | 10 s |
| | | | **total** | **≈ 180 s** |

The budget is tight. Levers, in order: pre-warm the sandbox at startup (data + `lifelines` installed,
reused by `environment_id`); overlap EvidenceGap with planning; cap Argon output tokens; Flash for every
leaf task. Backup: replay a recorded run in the same page if live fails.

Shared state: a run folder `runs/<id>/` with `events.jsonl` (every message, tool call and hand-off),
`notebook.json` (each agent's output), `catalog.json` (sources, lessons, files) and the sandbox outputs.
The live page streams `events.jsonl` over SSE. Every agent call has retry with backoff, and a failed
agent is recorded and skipped, never crashing the run.

## Measured on our key (11:00 AM)

| Call | Latency |
|---|---|
| `gemini-4-argon` (low) / `gemini-3.8-flash` / `gemini-3.5-flash-lite` / `gemma-4-31b-it` | 3.6 / 2.4 / 1.3 / 3.1 s |
| Antigravity + Argon, CSV in → pandas → file out | 37 s |
| Deep Research (short question) | 115 s, 8 KB cited report (too slow for live; cache it) |

Five of our existing keys reach Argon. `.env` uses the cancer_research one; the others are backups for rate limits.

## Build milestones

| By | Milestone | Done when |
|---|---|---|
| 11:30 | **M0 prep** | prototype code merged or fresh-build decided; `scripts/fetch_metabric.py` writes `data/metabric_tnbc.csv`; lesson + evidence cache started |
| 1:00 PM | **M1 walking skeleton (CLI)** | one command runs intake → drafts → 1 planning track → CLI approval → sandbox executor → synthesis → judge, and writes the run folder |
| 2:30 PM | **M2 the full lab** | 3 parallel tracks + aggregator + critic loop, feasibility, school (full mode) and caches (fast mode), custom managed agent with budget cap and audit trail |
| 3:30 PM | **M3 live page + fast mode** | FastAPI SSE page with lanes, approve button, sandbox log, answer vs baseline verdict; fast mode passes 3 runs in a row in < 3 min; **feature freeze** |
| 4:30 PM | **M4 ship** | 1-min video recorded; README "built today" list final; repo checked public; form submitted by 4:45 |

Roles if we are four (one person can hold several):
1. **Orchestrator:** run loop, shared state, events, retries, fast/full modes.
2. **Agents:** prompts for every role, scope guard, critic and judge rubrics.
3. **Data + sandbox:** METABRIC fetch, custom executor agent, pre-warm, figures, feasibility check.
4. **Live page + demo:** FastAPI/SSE page, approval button, video, README, submission.

## 60-second video script

| Time | Shows |
|---|---|
| 0–8 s | the researcher's problem in one line; question typed in |
| 8–25 s | live page: agents hand off; three planning tracks argue; critic objection → revision |
| 25–32 s | approval card ("~$1.20, 1 sandbox run"), human clicks Approve |
| 32–45 s | sandbox: Argon writes and runs the Cox model; KM plot and hazard ratio appear |
| 45–55 s | blind test: lab vs Argon-alone, judged twice with order swapped, and the lab wins with the reason |
| 55–60 s | "Built today: Gemini port, managed-agent executors, fast mode, live page" + repo URL |

## Submission checklist (4:30 PM)

- [ ] Repo public, `README.md` old/new list final, no `.env`, no restricted data, no prototype PDFs
- [ ] `uv sync && uv run python -m virtual_lab "<question>"` works from a fresh clone
- [ ] Video ≤ 60 s, shows only hackathon work, uploaded with link accessible
- [ ] All team members added on the form
- [ ] Live demo rehearsed 3×; replay backup ready

## Open items

1. **Prototype code:** we chose to extend it, but it isn't on this machine or our GitHub. If we have it by
   11:30, merge with history after a secrets/data scan; otherwise build fresh here and say so in the README.
2. **Submission cutoff** and whether extending a disclosed prototype is OK: ask at kickoff.
3. **Team members** and roles.
