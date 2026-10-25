"""The Virtual Lab relay: every stage from the original request to the blind test."""

import asyncio
import json
import re
import time

import pandas as pd

from . import agents as A
from . import sandbox
from .config import ARGON, CACHE_DIR, DATA_CSV, DATA_DICT, DEEP_RESEARCH, FLASH, GEMMA, LITE, MODES
from .llm import ask, client, usage_of
from .notebook import Run

LESSONS = CACHE_DIR / "lessons"
RESEARCH = CACHE_DIR / "research"
EXECUTOR_TOKEN_CAP = 600_000
SEARCH = [{"type": "google_search"}]
SOURCE_LINE = re.compile(r"^\W*SOURCE\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$", re.M)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:80]


def register_sources(run: Run, sources: list[dict], by: str) -> tuple[list[dict], dict]:
    """Catalogue sources; returns them with new IDs plus an old→new ID map for cached text."""
    out, remap = [], {}
    for s in sources:
        sid = run.add_source("evidence", s["title"], s["where"], by)
        if s.get("id"):
            remap[s["id"]] = sid
        out.append({**s, "id": sid})
    return out, remap


def remap_ids(text: str, remap: dict) -> str:
    return re.sub(r"\b[EL]-\d{3}\b", lambda m: remap.get(m.group(0), m.group(0)), text)


def parse_sources(text: str) -> list[dict]:
    return [{"title": t, "where": w, "finding": f} for t, w, f in SOURCE_LINE.findall(text or "")]


def source_list(sources: list[dict]) -> str:
    return "\n".join(f"[{s['id']}] {s['title']} ({s['where']}): {s['finding']}" for s in sources)


async def deep_research(run: Run, agent: str, lane: str, prompt: str) -> str | None:
    """Deep Research agent in the background, polled until done (minutes; full mode only)."""
    run.emit("agent_start", agent=agent, lane=lane, model=DEEP_RESEARCH)
    start = time.time()
    try:
        i = await client().aio.interactions.create(agent=DEEP_RESEARCH, input=prompt, background=True)
        while i.status in ("in_progress", "queued"):
            await asyncio.sleep(10)
            i = await client().aio.interactions.get(id=i.id)
    except Exception as e:
        run.emit("error", agent=agent, lane=lane, text=f"{type(e).__name__}: {str(e)[:300]}")
        return None
    run.add_usage(*usage_of(i))
    run.emit("agent_output", agent=agent, lane=lane, model=DEEP_RESEARCH, text=i.output_text or "",
             ms=int((time.time() - start) * 1000))
    return i.output_text


# 2. Readiness check and school ---------------------------------------------------------------------

async def ready_team(run: Run, question: str) -> str:
    cfg = MODES[run.mode]
    LESSONS.mkdir(parents=True, exist_ok=True)
    cached = {p.stem: json.loads(p.read_text()) for p in LESSONS.glob("*.json")}
    listing = "\n".join(f"- {slug}: {c['topic']}" for slug, c in cached.items()) or "(none yet)"
    r = await ask(run, "TeamReadinessAgent", LITE, A.READINESS_PROMPT.format(question=question, lessons=listing),
                  schema=A.READINESS_SCHEMA, lane="School")
    reuse = [s for s in (r or {}).get("reuse", []) if s in cached]
    topics = (r or {}).get("new_topics", [])
    if not cfg["live_school"] and reuse:
        topics = []  # fast mode: what the team already learned is enough
    if not reuse and not topics:
        topics = [question]

    lessons = []
    for slug in reuse:
        lesson = cached[slug]
        sources, remap = register_sources(run, lesson["sources"], "Librarian (cached)")
        lid = run.add_source("lesson", lesson["topic"], f"knowledge base: {slug}", "LessonWriter (cached)")
        remap[lesson.get("id", "")] = lid
        run.emit("agent_output", agent="TeamReadinessAgent", lane="School",
                 text=f"Reusing lesson **{lid}: {lesson['topic']}** with {len(sources)} sources from the team's knowledge base.")
        lessons.append(f"[{lid}] {lesson['topic']}\n{remap_ids(lesson['lesson'], remap)}\n{source_list(sources)}")
    for topic in topics[:2]:
        lesson = await study(run, topic, question)
        if lesson:
            lessons.append(lesson)
    run.set("lessons", lessons)
    run.handoff("TeamReadinessAgent", "PI_Kickoff", "lessons", lane="School")
    return "\n\n".join(lessons)


async def study(run: Run, topic: str, question: str) -> str | None:
    """Curriculum → Librarian → Teacher → Student → Grader (repeat) → LessonWriter."""
    lane, cfg = "School", MODES[run.mode]
    run.emit("stage", lane=lane, text=f"School: {topic}")
    cur = await ask(run, "Curriculum", FLASH, A.CURRICULUM_PROMPT.format(topic=topic, question=question),
                    schema=A.CURRICULUM_SCHEMA, lane=lane)
    questions = "\n".join(f"- {q}" for q in (cur or {}).get("questions", [topic]))
    run.handoff("Curriculum", "Librarian", "curriculum_questions", lane=lane)

    prompt = A.LIBRARIAN_PROMPT.format(topic=topic, questions=questions)
    found = (await deep_research(run, "Librarian", lane, prompt) if cfg["deep_research"]
             else await ask(run, "Librarian", FLASH, prompt, tools=SEARCH, lane=lane))
    sources, _ = register_sources(run, parse_sources(found), "Librarian")
    if not sources:
        return None
    run.handoff("Librarian", "Teacher", "sources", lane=lane)

    teaching = await ask(run, "Teacher", FLASH, A.TEACHER_PROMPT.format(
        topic=topic, questions=questions, sources=source_list(sources)), system=A.LAB_RULES, lane=lane)
    for _ in range(2):
        answers = await ask(run, "Student", FLASH, A.STUDENT_PROMPT.format(lesson=teaching), lane=lane)
        grade = await ask(run, "Grader", FLASH, A.GRADER_PROMPT.format(lesson=teaching, answers=answers),
                          schema=A.GRADER_SCHEMA, lane=lane)
        if not grade or grade["passed"]:
            break
        teaching = await ask(run, "Teacher", FLASH, A.TEACHER_PROMPT.format(
            topic=topic, questions=questions, sources=source_list(sources))
            + f"\n\nThe student failed last time. Grader feedback: {grade['feedback']}", system=A.LAB_RULES, lane=lane)

    lesson = await ask(run, "LessonWriter", FLASH, A.LESSON_PROMPT.format(
        topic=topic, sources=source_list(sources), lesson=teaching), system=A.LAB_RULES, lane=lane)
    if not lesson:
        return None
    slug = slugify(topic)
    lid = run.add_source("lesson", topic, f"knowledge base: {slug}", "LessonWriter")
    (LESSONS / f"{slug}.json").write_text(json.dumps(
        {"id": lid, "topic": topic, "lesson": lesson, "sources": [
            {"id": s["id"], "title": s["title"], "where": s["where"], "finding": s["finding"]} for s in sources]},
        indent=2))
    return f"[{lid}] {topic}\n{lesson}\n{source_list(sources)}"


# 3. Fact-checking ------------------------------------------------------------------------------------

async def fact_check(run: Run, question: str, dictionary: str) -> str:
    lane, cfg = "Research", MODES[run.mode]
    gap = await ask(run, "EvidenceGapAgent", LITE, A.EVIDENCE_GAP_PROMPT.format(
        question=question, dictionary=dictionary), schema=A.EVIDENCE_GAP_SCHEMA, lane=lane)
    query = (gap or {}).get("research_query") or question
    run.handoff("EvidenceGapAgent", "web_research", "research_query", lane=lane)

    RESEARCH.mkdir(parents=True, exist_ok=True)
    cache = RESEARCH / f"{slugify(question)}.json"
    if cache.exists() and not cfg["deep_research"]:
        saved = json.loads(cache.read_text())
        sources, remap = register_sources(run, saved["sources"], "web_research (cached)")
        summary = remap_ids(saved["summary"], remap)
        run.emit("agent_output", agent="web_research", lane=lane,
                 text=f"Reusing the team's earlier literature search ({len(sources)} sources).\n\n{summary}")
    else:
        prompt = A.WEB_RESEARCH_PROMPT.format(query=query)
        found = (await deep_research(run, "web_research", lane, prompt) if cfg["deep_research"]
                 else await ask(run, "web_research", FLASH, prompt, tools=SEARCH, lane=lane)) or ""
        sources, _ = register_sources(run, parse_sources(found), "web_research")
        summary = found.split("Sources:")[0].strip()
        cache.write_text(json.dumps({"summary": summary, "sources": sources}, indent=2))

    can = "\n".join(f"- {x}" for x in (gap or {}).get("data_can_answer", []))
    cannot = "\n".join(f"- {x}" for x in (gap or {}).get("data_cannot_answer", []))
    result = (f"Published evidence:\n{summary}\n{source_list(sources)}\n\n"
              f"Our data can answer:\n{can}\nOur data cannot answer:\n{cannot}")
    run.set("evidence", result)
    return result


async def check_draft(run: Run, evidence: str, initial: asyncio.Task) -> str:
    """Gemma's draft vs the evidence; runs alongside the planning meetings."""
    draft = await initial or "(no draft)"
    run.set("initial_answer", draft)
    check = await ask(run, "EvidenceGapAgent", FLASH, A.DRAFT_CHECK_PROMPT.format(evidence=evidence, draft=draft),
                      lane="Research")
    return f"Gemma's first draft:\n{draft}\n\nCheck of the first draft against the evidence:\n{check or '(not checked)'}"


# 4. Planning meetings ----------------------------------------------------------------------------------

async def planning_track(run: Run, t: str, question: str, knowledge: str, dictionary: str) -> str | None:
    lane, track, rounds = f"Track {t}", A.TRACKS[t], MODES[run.mode]["critic_rounds"]
    kickoff = await ask(run, f"PI_{t}", ARGON, A.PI_KICKOFF_PROMPT.format(
        track=track, question=question, knowledge=knowledge, dictionary=dictionary),
        system=A.LAB_RULES, thinking="low", lane=lane)
    if not kickoff:
        return None
    for name in A.SPECIALISTS:
        run.handoff(f"PI_{t}", f"{name}_{t}", "agenda", lane=lane)
    ideas = await asyncio.gather(*(
        ask(run, f"{name}_{t}", FLASH, A.SPECIALIST_PROMPT.format(track=track, kickoff=kickoff, dictionary=dictionary),
            system=f"{A.LAB_RULES}\n\n{role}", lane=lane)
        for name, role in A.SPECIALISTS.items()))
    meeting = f"PI: {kickoff}\n\n" + "\n\n".join(f"{n}: {i}" for n, i in zip(A.SPECIALISTS, ideas) if i)
    plan = await ask(run, f"PI_{t}", ARGON, A.PI_PLAN_PROMPT.format(track=track, question=question, meeting=meeting),
                     system=A.LAB_RULES, thinking="low", lane=lane)
    for _ in range(rounds):
        if not plan:
            break
        critique = await ask(run, f"Critic_{t}", ARGON, A.CRITIC_PROMPT.format(plan=plan, dictionary=dictionary),
                             schema=A.CRITIC_SCHEMA, system=A.LAB_RULES, thinking="low", lane=lane)
        if not critique or critique["verdict"] == "accept":
            break
        revised = await ask(run, f"PlanReviser_{t}", FLASH, A.REVISER_PROMPT.format(
            plan=plan, concerns="\n".join(f"- {c}" for c in critique["concerns"])), system=A.LAB_RULES, lane=lane)
        plan = revised or plan
    run.set(f"plan_{t}", plan)
    return plan


# 5. Checks and approval --------------------------------------------------------------------------------

async def check_feasibility(run: Run, plan: str, dictionary: str) -> str:
    cols = await ask(run, "PlanFeasibilityAgent", LITE, A.FEASIBILITY_PROMPT.format(plan=plan),
                     schema=A.FEASIBILITY_SCHEMA)
    required = [c.strip("` ") for c in (cols or {}).get("required_columns", [])]
    actual = set(pd.read_csv(DATA_CSV, nrows=0).columns)
    missing = [c for c in required if c not in actual]
    run.emit("tool", agent="PlanFeasibilityAgent", text=(
        f"Code check against `metabric.csv`: {len(required) - len(missing)}/{len(required)} required columns present"
        + (f"; missing: {', '.join(missing)}" if missing else ".")), data={"kind": "output", "missing": missing})
    if not missing:
        return plan
    fixed = await ask(run, "PlanFeasibilityAgent", FLASH, A.FEASIBILITY_FIX_PROMPT.format(
        missing=", ".join(missing), plan=plan, dictionary=dictionary), system=A.LAB_RULES)
    return fixed or plan


async def get_approval(run: Run, plan: str, auto: bool) -> bool:
    blended = (0.8 * 2.0 + 0.2 * 10.0) / 1e6  # Argon $/token, assuming 80% input
    est = EXECUTOR_TOKEN_CAP * blended + 40_000 * blended  # executor cap + synthesis and judges
    decision = run.request_approval(
        f"The plan is ready. Running it needs one sandbox session on Argon, capped at "
        f"{EXECUTOR_TOKEN_CAP:,} tokens (about ${est:.2f} at most). Spent so far: ${run.cost_usd:.2f}.",
        {"est_tokens": EXECUTOR_TOKEN_CAP, "est_cost_usd": round(est, 2), "spent_usd": round(run.cost_usd, 2),
         "plan": plan})
    if auto:
        run.resolve_approval(True)
    approved = await decision
    run.emit("approval", agent="BudgetAndApprovalAgent", text="Approved" if approved else "Rejected",
             data={"approved": approved, "by": "auto" if auto else "human"})
    return approved


# 7. The blind test -------------------------------------------------------------------------------------

async def blind_test(run: Run, question: str, lab: str, baseline: str) -> list[str]:
    orders = [("lab_first", lab, baseline), ("baseline_first", baseline, lab)]
    results = await asyncio.gather(*(
        ask(run, f"AnswerJudge_{n + 1}", ARGON, A.JUDGE_PROMPT.format(question=question, a=a, b=b),
            schema=A.JUDGE_SCHEMA, thinking="low", lane="Judge")
        for n, (_, a, b) in enumerate(orders)))
    winners = []
    for n, ((order, _, _), r) in enumerate(zip(orders, results)):
        if not r:
            continue
        lab_is_a = order == "lab_first"
        winner = "tie" if r["winner"] == "tie" else ("lab" if (r["winner"] == "A") == lab_is_a else "baseline")
        scores = {"lab": r["score_a"] if lab_is_a else r["score_b"], "baseline": r["score_b"] if lab_is_a else r["score_a"]}
        winners.append(winner)
        run.emit("verdict", agent=f"AnswerJudge_{n + 1}", lane="Judge",
                 text=f"{'Lab' if lab_is_a else 'Baseline'} shown first → winner: **{winner}** "
                      f"({scores['lab']} vs {scores['baseline']})",
                 data={"order": order, "winner": winner, "scores": scores, "reason": r["reason"]})
    return winners


# the whole relay ---------------------------------------------------------------------------------------

async def run_lab(run: Run, auto_approve: bool = False):
    cfg = MODES[run.mode]
    start = time.time()
    dictionary = DATA_DICT.read_text()

    # 1. Getting started
    run.stage("1 · Getting started")
    run.set("original_request", run.question)
    run.emit("agent_output", agent="CaptureOriginalRequest", text=f"Saved the exact question:\n\n> {run.question}")
    sandbox_ready = asyncio.create_task(sandbox.ensure(run))
    scope = await ask(run, "ScopeGuard", LITE, A.SCOPE_PROMPT.format(question=run.question), schema=A.SCOPE_SCHEMA)
    question = run.question
    if scope and scope["kind"] == "off_topic":
        run.emit("final", text="Out of scope for a cancer research lab.", data={"answer": scope["reason"], "baseline": "",
                                                                                 "lab_wins": False, "files": []})
        return
    if scope and scope["kind"] == "patient_care":
        question = scope["research_question"]
        run.emit("agent_output", agent="ScopeGuard", text=(
            "This lab does not give care advice for an individual patient. It will answer the closest "
            f"research question instead:\n\n> {question}"))
    run.set("question", question)
    initial = asyncio.create_task(ask(run, "InitialAnswer", GEMMA, question, system=A.LAB_RULES + " Answer from memory in under 200 words."))
    baseline = asyncio.create_task(ask(run, "BaselineAnswer", ARGON, A.BASELINE_PROMPT.format(
        question=question, dictionary=dictionary), thinking="medium", show=False))

    # 2-3. School and fact-checking
    run.stage("2 · Readiness check and school")
    lessons = await ready_team(run, question)
    run.stage("3 · Fact-checking")
    evidence = await fact_check(run, question, dictionary)
    knowledge = f"{lessons}\n\n{evidence}"
    draft_checked = asyncio.create_task(check_draft(run, evidence, initial))

    # 4. Planning meetings
    run.stage("4 · Planning meetings (three teams in parallel)")
    plans = await asyncio.gather(*(planning_track(run, t, question, knowledge, dictionary) for t in A.TRACKS))
    merged = "\n\n".join(f"=== Plan from Track {t} ===\n{p}" for t, p in zip(A.TRACKS, plans) if p)
    for t in A.TRACKS:
        run.handoff(f"PI_{t}", "PI_Aggregator", f"plan_{t}")
    plan = await ask(run, "PI_Aggregator", ARGON, A.AGGREGATOR_PROMPT.format(
        question=question, plans=merged, dictionary=dictionary), system=A.LAB_RULES,
        thinking="medium" if run.mode == "full" else "low")

    # 5. Checks and approval
    run.stage("5 · Checks and approval")
    plan = await check_feasibility(run, plan, dictionary)
    run.set("final_plan", plan)
    team = asyncio.create_task(ask(run, "TeamFormationAgent", FLASH, A.TEAM_PROMPT.format(plan=plan), schema=A.TEAM_SCHEMA))
    if not await get_approval(run, plan, auto_approve):
        team.cancel()
        sandbox_ready.cancel()
        run.emit("final", text="Rejected at approval; nothing was run.",
                 data={"answer": "Plan rejected by the reviewer before any analysis ran.", "baseline": "",
                       "lab_wins": False, "files": []})
        return

    # 6. Doing the work
    run.stage("6 · Doing the work")
    experts = "; ".join(f"{e['role']} ({e['focus']})" for e in ((await team) or {}).get("experts", [])) or "Survival Analyst"
    env_id = await sandbox_ready
    files = await sandbox.execute(run, plan, experts, EXECUTOR_TOKEN_CAP, env_id) if env_id else {}
    if env_id and "results.json" not in files:  # stale sandbox or failed run: one retry on a fresh sandbox
        env_id = await sandbox.create(run)
        files = await sandbox.execute(run, plan, experts, EXECUTOR_TOKEN_CAP, env_id) if env_id else {}
    draft = await draft_checked
    results = "\n\n".join(f"[{fid}] {name}:\n{(run.dir / 'sandbox' / name).read_text()}"
                          for name, fid in files.items() if name in ("results.json", "summary.md"))
    def synth_prompt(feedback: str = "") -> str:
        return A.SYNTHESIS_PROMPT.format(question=question, files=", ".join(files.values()) or "none",
                                         results=results or "The analysis produced no results.",
                                         knowledge=knowledge, draft=draft, feedback=feedback)

    answer = await ask(run, "ExecutionSynthesisAgent", ARGON, synth_prompt(), system=A.LAB_RULES, thinking="medium")

    # 7. The blind test
    run.stage("7 · Blind test against Argon alone")
    sealed = await baseline or ""
    run.emit("agent_output", agent="BaselineAnswer", lane="Judge", text=sealed)
    winners = await blind_test(run, question, answer, sealed)
    for _ in range(cfg["judge_retries"]):
        if "baseline" not in winners and "lab" in winners:
            break
        reasons = " ".join(e["data"]["reason"] for e in run.events if e["type"] == "verdict")
        answer = await ask(run, "ExecutionSynthesisAgent", ARGON, synth_prompt(
            f"\n\nA reviewer preferred another answer. Fix these weaknesses: {reasons}"),
            system=A.LAB_RULES, thinking="medium") or answer
        winners = await blind_test(run, question, answer, sealed)

    lab_wins = "lab" in winners and "baseline" not in winners
    run.write("answer.md", answer or "")
    run.write("baseline.md", sealed)
    run.set("answer", answer)
    run.emit("final", text="Lab wins the blind test" if lab_wins else "Lab does not beat the baseline",
             data={"answer": answer, "baseline": sealed, "lab_wins": lab_wins, "winners": winners,
                   "files": [f"sandbox/{n}" for n in files], "elapsed_s": round(time.time() - start),
                   "tokens": run.tokens_in + run.tokens_out, "cost_usd": round(run.cost_usd, 2)})
