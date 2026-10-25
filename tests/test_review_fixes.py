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
    two = 'RESULTS_JSON {"primary": {"hr": 0.9}}\nlog\nRESULTS_JSON {"primary": {"hr": 0.7}}'
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
