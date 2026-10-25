# Virtual Lab

A lab of 28 Gemini agents that answers a cancer research question the way a real lab would. It studies
the topic, plans in three parallel meetings, critiques the plan, asks a human to approve the budget,
runs the analysis on real patient data in a Gemini managed-agent sandbox, and then has to beat
**Gemini 4 Argon answering alone** in a blind test. One run takes about 2.5 minutes and costs about $0.35.

Built at the **Gemini 4 Argon SF Hackathon** (Cerebral Valley × Google DeepMind, 2026-10-25).

## Results

Demo question: *"In triple-negative breast cancer, is higher cytotoxic immune infiltration associated with
longer overall survival, independent of age, stage and grade?"* Data: 1,980 METABRIC patients, of whom
the lab itself selects the 320 triple-negative cases (168 deaths).

| | |
|---|---|
| Blind test (judged twice, order swapped, lab must win **both**) | **won 10 of 11 runs**; 1 split |
| Lab's finding, every run | HR **0.76–0.80** per SD of cytolytic score, 95% CI excluding 1, p = 0.002–0.012 |
| Question to verdict, live with a human approval click | **150–198 s** (6 of 7 fast-mode runs under 3 minutes) |
| Cost per run | about $0.35 (≈120k tokens) |

The judges' reason was the same each time: the lab ran the survival analysis on the data, while Argon alone
could only reason from the literature and estimate. Different runs planned the analysis differently
(complete-case adjustment for stage, n = 227, or stage proxies, n = 293–320), and the hazard ratio held
across all of them.

## How it works

| Stage | Agents | Model |
|---|---|---|
| Intake | CaptureOriginalRequest, ScopeGuard | code, Flash-Lite |
| Drafts | InitialAnswer ∥ BaselineAnswer (sealed until the blind test) | Gemma 4 ∥ **Argon** |
| School | TeamReadiness → Curriculum, Librarian, Teacher, Student, Grader, LessonWriter | Flash-Lite, Flash, Google Search / Deep Research |
| Fact-check | EvidenceGapAgent, web_research | Flash-Lite, Flash + Search / Deep Research |
| Planning ×3 in parallel | PI, Immunologist, ML Specialist, Computational Biologist, Critic, PlanReviser | **Argon** leads, Flash specialists |
| Merge and checks | PI_Aggregator, PlanFeasibilityAgent (column check in code), TeamFormation | **Argon**, Flash-Lite, Flash |
| **Human approval** | BudgetAndApprovalAgent: the approved budget becomes the sandbox agent's `max_total_tokens` | person |
| Work | ExecutorCoder writes `analysis.py`; the **Antigravity managed agent** runs it in a pre-warmed sandbox | **Argon**, Managed Agents |
| Answer | ExecutionSynthesisAgent: what the data shows, what research says, limitations, references | **Argon** |
| Blind test | AnswerJudge ×2, order swapped | **Argon** |

Lessons and literature searches are saved as team knowledge and reused, which is what lets **fast mode**
finish in under 3 minutes. **Full mode** runs the school and Deep Research live, allows up to four critic
rounds, and lets Argon in the sandbox write, run and iterate on its own (slower; experimental).

Every run writes `runs/<id>/`: `events.jsonl` (every message, tool call and hand-off), `notebook.json`,
`catalog.json` (sources, lessons, files), `answer.md`, `baseline.md` and the sandbox outputs (`results.json`,
`km.png`, `analysis.py`).

## Run it

```bash
cp .env.example .env                                  # add GEMINI_API_KEY (Argon needs a paid tier)
uv sync
uv run python -m virtual_lab.data                     # fetch METABRIC from cBioPortal into data/
uv run uvicorn virtual_lab.server:app --port 8010     # live page at http://localhost:8010
uv run python -m virtual_lab --auto-approve           # or the CLI: demo question, fast mode
```

The first run is slow (about 10 minutes) because it builds the team's lessons and sets up the sandbox;
later runs reuse both. `uv run pytest -q tests` runs the regression tests (no API calls);
`uv run python scripts/smoke_test.py` checks every model and the sandbox. Demo steps: [docs/DEMO.md](docs/DEMO.md).

## Safety and data

This is a research tool and does not give medical advice. ScopeGuard catches patient-care questions
("what is the next step for this patient?") and answers the closest population-level research question
instead; the synthesis is instructed never to give treatment or dosing advice. Data is public: METABRIC
(Curtis et al. Nature 2012; Pereira et al. Nat Commun 2016; Rueda et al. Nature 2019) from
[cBioPortal](https://www.cbioportal.org/study/summary?id=brca_metabric), fetched by script and not committed.

## What existed before vs. what we built at the hackathon

**Before the event:** our team had a Virtual Lab prototype (first full run 2026-10-21). It used Gemma via
Ollama for drafts and Claude as the baseline, took about 45 minutes of agent time to reach a plan, ran no
analysis code on data, and lost its blind test. We kept its agent design (the roles and the relay) but
none of its code.

**Built on 2026-10-25 (hackathon):** everything in this repository (see `git log`): the relay on the Gemini
Interactions API, the managed-agent executor with the approval-set budget, fast mode, ScopeGuard, the
blind judge, the live page, and the tests. Two rounds of independent code review (Codex) were fixed the
same day.

The idea of a lab made of AI agents (a PI, specialists and a critic meeting to plan) comes from
Swanson et al., *The Virtual Lab* (Nature, 2025).

## Layout

| Path | What |
|---|---|
| [virtual_lab/pipeline.py](virtual_lab/pipeline.py) | the relay, stage by stage |
| [virtual_lab/agents.py](virtual_lab/agents.py) | every role's instructions and output schema |
| [virtual_lab/sandbox.py](virtual_lab/sandbox.py) | Antigravity managed-agent executor |
| [virtual_lab/llm.py](virtual_lab/llm.py) | Gemini calls: retries, schema checks, usage |
| [virtual_lab/notebook.py](virtual_lab/notebook.py) | shared notebook, event log, approval |
| [virtual_lab/server.py](virtual_lab/server.py), [virtual_lab/web/index.html](virtual_lab/web/index.html) | live page (FastAPI + server-sent events) |
| [docs/PRD.md](docs/PRD.md), [docs/PLAN.md](docs/PLAN.md) | product spec and hackathon plan |

`.claude/skills/gemini-api-dev/` is Google's Gemini API skill (Apache-2.0, from
[google-gemini/gemini-skills](https://github.com/google-gemini/gemini-skills)), vendored for our coding agents.
