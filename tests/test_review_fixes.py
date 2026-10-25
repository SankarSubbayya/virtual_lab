"""Regression tests for the code review of a728f54 (no network, no model calls)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from virtual_lab import pipeline, sandbox
from virtual_lab.agents import JUDGE_SCHEMA, READINESS_SCHEMA
from virtual_lab.llm import check
from virtual_lab.notebook import Run


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr("virtual_lab.notebook.RUNS_DIR", tmp_path)
    r = Run("q")
    r.add_source("evidence", "A paper", "J Clin 2020", "web_research")  # E-001
    r.add_source("file", "results.json", "sandbox/results.json", "Executor")  # F-001
    return r


# 9. a win needs both orderings
@pytest.mark.parametrize("winners, expected", [
    (["lab", "lab"], "lab"), (["lab", "tie"], "tie"), (["lab", "failed"], "tie"),
    (["lab", "baseline"], "tie"), (["baseline", "baseline"], "baseline"), ([], "tie")])
def test_outcome_requires_both_orderings(winners, expected):
    assert pipeline.outcome(winners) == expected


# 10. lab notes stripped for the judge; references exactly once
@pytest.mark.parametrize("heading", ["**Lab notes**", "### Lab notes", "**Lab notes:**", "Lab notes:"])
def test_judge_never_sees_lab_notes(run, heading):
    answer = f"**Answer**\nYes [F-001].\n\n{heading}\n- changed from draft [E-001]\n\n**References**\n- old list"
    judged = pipeline.for_judge(run, answer)
    assert "changed from draft" not in judged and "old list" not in judged
    assert judged.count("**References**") == 1 and "[F-001]" in judged


def test_body_line_starting_with_lab_notes_is_kept(run):
    answer = "**Answer**\nLab notes are kept in the run folder [F-001].\n\n**Limitations**\nSmall cohort."
    assert "Small cohort." in pipeline.for_judge(run, answer)


def test_references_appear_once(run):
    answer = "**Answer**\nYes [E-001].\n\n**References**\n- [E-001] model-written list"
    out = pipeline.with_references(run, answer)
    assert out.count("**References**") == 1 and "model-written" not in out


# 7. stdout results: last valid marker wins; truncated JSON rejected
def test_parse_results():
    assert sandbox.parse_results('RESULTS_JSON {"primary": {"hr": 0.6}, "ci":') == ""
    full = '"ci_low": 0.5, "ci_high": 0.9, "p": 0.01'
    two = f'RESULTS_JSON {{"primary": {{"hr": 0.9, {full}}}}}\nlog\nRESULTS_JSON {{"primary": {{"hr": 0.7, {full}}}}}'
    assert '"hr": 0.7' in sandbox.parse_results(two)
    assert sandbox.parse_results('RESULTS_JSON {"secondary": []}') == ""


# 5. schema validation
@pytest.mark.parametrize("value, schema", [([1], READINESS_SCHEMA), ({"score_a": 1, "winner": "A", "reason": ""}, JUDGE_SCHEMA),
                                           ({"score_a": 1, "score_b": 2, "winner": "C", "reason": ""}, JUDGE_SCHEMA)])
def test_schema_rejects_bad_output(value, schema):
    with pytest.raises(ValueError):
        check(value, schema)


# 4. a subscriber that pauses during backlog replay still receives the final event
def test_stream_drains_after_run_finishes(run):
    async def scenario():
        run.emit("stage", text="one")
        received = []
        stream = run.stream()
        received.append(await stream.__anext__())  # backlog event 0, then the subscriber pauses
        run.emit("stage", text="two")
        run.emit("final", text="done")
        async for event in stream:
            received.append(event)
        return [e["type"] for e in received]
    assert asyncio.run(scenario()) == ["stage", "stage", "final"]


# 13. run ids cannot escape runs/
def test_files_endpoint_blocks_traversal():
    from virtual_lab.server import app
    client = TestClient(app)
    for url in ["/api/runs/%2e%2e/files/README.md", "/api/runs/../files/.env", "/api/runs/..%2f..%2f/files/x"]:
        assert client.get(url).status_code == 404, url


# ---- second review (464b486) -------------------------------------------------------------------------

# R5: removing references/notes never removes other sections
def test_limitations_after_references_survive(run):
    answer = "HR=0.6 [E-001].\n## References\n- paper\n## Limitations\nThe model did not converge."
    assert "did not converge" in pipeline.for_judge(run, answer)
    assert "did not converge" in pipeline.with_references(run, answer)


def test_two_reference_sections_become_one(run):
    answer = "**Answer**\nYes [E-001].\n\n**References**\n- a\n\n**Limitations**\nx\n\n**References:**\n- b"
    out = pipeline.with_references(run, answer)
    assert out.count("**References**") == 1 and "- a" not in out and "- b" not in out and "x" in out


def test_limitations_after_lab_notes_reach_judge(run):
    answer = "**Answer**\nYes.\n\n### Lab notes ###\n- changed\n\n**Limitations**\nSmall n."
    judged = pipeline.for_judge(run, answer)
    assert "Small n." in judged and "changed" not in judged


# R3: only the last marker counts, and it must carry finite numbers
def test_parse_results_uses_last_marker_only():
    stale_then_broken = 'RESULTS_JSON {"primary": {"hr": 0.6, "ci_low": 0.5, "ci_high": 0.7, "p": 0.01}}\nRESULTS_JSON {"primary": {"hr": 1.4,'
    assert sandbox.parse_results(stale_then_broken) == ""
    assert sandbox.parse_results('RESULTS_JSON {"primary": {}}') == ""
    assert sandbox.parse_results('RESULTS_JSON {"primary": {"hr": NaN, "ci_low": 0.5, "ci_high": 0.7, "p": 0.01}}') == ""
    good = 'RESULTS_JSON {"primary": {"hr": 0.78, "ci_low": 0.66, "ci_high": 0.92, "p": 0.003}}'
    assert '"hr": 0.78' in sandbox.parse_results(good)


# R6: a failing coroutine cancels its siblings
def test_together_cancels_siblings():
    from virtual_lab.llm import together
    state = {}

    async def slow():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    async def boom():
        await asyncio.sleep(0.01)
        raise KeyError("track A")

    with pytest.raises(ExceptionGroup):
        asyncio.run(together(slow(), boom()))
    assert state.get("cancelled")


GOOD = 'RESULTS_JSON {"primary": {"hr": 0.78, "ci_low": 0.66, "ci_high": 0.92, "p": 0.003}}'


def fake_sandbox(monkeypatch, stdout="", tokens=10, error=None, files=None):
    async def upload(*a, **k):
        return None

    async def agent(*a, **k):
        if error:
            raise error
        return stdout, tokens

    async def fetch(env_id, path):
        return (files or {}).get(path.rsplit("/", 1)[-1])

    monkeypatch.setattr(sandbox, "upload", upload)
    monkeypatch.setattr(sandbox, "_agent", agent)
    monkeypatch.setattr(sandbox, "fetch", fetch)


# R7: a printed result is saved locally before it is cited, and survives a failed download
def test_printed_result_is_saved_even_if_download_fails(run, monkeypatch):
    fake_sandbox(monkeypatch, stdout=GOOD)
    work = asyncio.run(sandbox.execute(run, "plan", "x", 600_000, "env", code="print(1)"))
    assert work.results and "results.json" in work.files
    assert (run.dir / "sandbox" / "results.json").exists()


# R2: an undecodable results file is a failed attempt, not a crash
def test_bad_results_file_is_a_failed_attempt(run, monkeypatch):
    fake_sandbox(monkeypatch, stdout="no marker", tokens=42, files={"results.json": '{"primary": 1}'.encode("utf-16")})
    work = asyncio.run(sandbox.execute(run, "plan", "x", 600_000, "env", code="print(1)"))
    assert work.results == "" and work.tokens == 42 and work.files == {}


# R8: a failed attempt reports the tokens it consumed
def test_failed_attempt_keeps_its_tokens(run, monkeypatch):
    fake_sandbox(monkeypatch, error=sandbox.SandboxError("stream dropped", 500_000))
    work = asyncio.run(sandbox.execute(run, "plan", "x", 600_000, "env", code="print(1)"))
    assert work.results == "" and work.tokens == 500_000


# R4: setup that did not complete is never cached
def test_failed_setup_is_not_cached(run, monkeypatch, tmp_path):
    class Interaction:
        status, output_text, environment_id, usage = "failed", "", "env_bad", None

    class Fake:
        class aio:
            class interactions:
                @staticmethod
                async def create(**kwargs):
                    return Interaction()

    monkeypatch.setattr(sandbox, "client", lambda: Fake)
    monkeypatch.setattr(sandbox, "ENV_CACHE", tmp_path / "sandbox.json")
    assert asyncio.run(sandbox.create(run)) is None
    assert not (tmp_path / "sandbox.json").exists()
