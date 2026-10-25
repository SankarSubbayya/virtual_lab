# Live demo runbook

The judges want a working demo with real inputs in under 3 minutes. Fast mode does it in about
2.5 minutes, including your Approve click. Practise it twice before going on stage.

## Any time before (do it now and forget it)

1. The server can start any time and stay up all day. It is running now. If the laptop restarts or the
   terminal closes, start it again from the repo folder:
   ```bash
   cd ~/projects/virtual_lab
   uv run uvicorn virtual_lab.server:app --host 127.0.0.1 --port 8010
   ```
   (Port 8000 is taken on this laptop by an old Gemma server; 8010 avoids it.) Check it with
   http://127.0.0.1:8010 in a browser.
2. Keep the laptop from sleeping: run `caffeinate -dims` in a spare terminal (Ctrl-C to stop).
3. Open two Chrome tabs: **http://127.0.0.1:8010** (the live demo) and a **backup tab** with a finished
   run, which replays from disk even with no internet:
   **http://127.0.0.1:8010/?run=20261025-125814-20bd** (153 s, lab wins 24–15 and 24–17).
4. Have a phone hotspot ready in case the venue wifi drops.

## 10–15 minutes before your slot (the only timed step)

**Warm-up run:** click **Run** (Fast), Approve, let it finish. It proves, right before you present,
that the API key and quota work and that the sandbox answers. (The sandbox sleeps after 15 idle
minutes; the app wakes it automatically, but a recent successful run is the real check.) Then click
**New run** so the page is clean, and put Chrome in full screen (⌃⌘F), zoom 100%; the page is laid out
for 1920×1080.

## On stage (about 2.5 minutes)

| Clock | Do | Say |
|---|---|---|
| 0:00 | Question is prefilled. **Fast** is selected. Click **Run**. | "A cancer researcher has a public cohort and a hypothesis. Normally this is days of work. Watch a lab of Gemini agents do it." |
| 0:05 | Point at the left lanes. | "First it captures the question and checks it is research, not patient advice. Gemma writes a first draft; Argon answers alone in a sealed envelope, to beat later." |
| 0:10 | Point at the three middle lanes. | "Three independent planning meetings, in parallel. In each, an Argon PI runs the meeting, three Flash specialists contribute, and an Argon critic attacks the plan." |
| ~0:55 | **Approval card** appears. Pause on it. | "Nothing touches the sandbox until a human approves. The budget I approve becomes a hard token cap on the managed agent." Click **Approve**. |
| 1:05 | Point at the Sandbox lane. | "While I was reading, Argon wrote the analysis. A Gemini managed agent now runs it on 1,980 real patients in a Google sandbox." |
| ~2:10 | Kaplan–Meier plot and files appear. | "A Cox model, the survival curves, and the code that produced them." |
| ~2:30 | **Lab wins** banner. Scroll to the two answers. | "A blind judge compared the lab with Argon alone, twice, swapping the order. The lab wins because it measured: hazard ratio about 0.78, confidence interval excluding 1. Argon alone could only estimate." |

Then one sentence on what you built today and the repo URL.

## Questions judges are likely to ask

- **Is this medical advice?** No. It answers research questions about populations. A patient question
  ("what is the next step for this patient?") is caught by ScopeGuard and turned into a research
  question. It uses public data only.
- **Is the blind test fair?** The baseline is Argon itself, given the same question and the same data
  description, told it cannot run code. The judge is blind, sees both orders, and the lab must win both.
  It did in 10 of 11 runs; one split.
- **Why does this need Argon?** Argon leads: it runs the meetings, critiques, merges the plans, writes
  the analysis code, writes the answer and judges. Flash handles the leaf tasks in parallel (the
  orchestration pattern in the DeepMind builder guide).
- **What do Managed Agents add?** A pre-warmed Google sandbox holding the cohort; the agent runs and
  repairs the code; the human-approved budget is enforced as `max_total_tokens`; each run is isolated.
- **Is the result real?** Across nine runs with differently designed plans, the hazard ratio was
  0.76–0.80 every time. It matches the literature: more cytotoxic immune infiltration, longer survival.
- **What did you build today?** All of the code. An earlier prototype of the agent design existed
  (Gemma + Claude, no code execution, lost its blind test); we reused the design, not the code.

## If something goes wrong

| Problem | Do |
|---|---|
| Page stuck or reloaded by accident | Reload with `?run=<id>` (the id is top right); it re-attaches and replays. |
| No approval card after about 2 minutes, or the run stalls past 4 minutes | Switch to the backup tab and narrate the finished run. |
| Errors mentioning 429 / quota | Put a backup key in `.env`, restart the server (Ctrl-C, then the command above). |
| No internet | Use the backup tab; the replay is served from disk. |

Never demo **Full** mode live: it runs the school and Deep Research and takes 10+ minutes.
