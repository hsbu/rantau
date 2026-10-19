"""Submission snapshots contain bounded current-run proof, never credentials or chat prose."""

import json

from scripts.capture_demo_evidence import capture
from tests.finance.test_agent_approval import confirmed
from tests.finance.test_agent_runtime import runtime as runtime


def test_capture_is_read_only_current_run_and_omits_auth_and_chat(runtime):
    services, _, _ = runtime
    confirmed(runtime)
    with services.database.connection() as c:
        before = c.execute("SELECT count(*) AS n FROM audit_events").fetchone()["n"]
        run = c.execute("SELECT run_no FROM demo_state").fetchone()["run_no"]
    result = capture(services.database, "demo_001")
    assert result["scenario"]["run_no"] == run
    assert len(result["intents"]) == 1
    assert result["transfers"] == result["ledger"] == result["postings"] == []
    assert len(result["agent_runs"]) == 3
    text = json.dumps(result, default=str)
    for forbidden in (
        "password",
        "session_id",
        "conversation_id",
        "cookie",
        "api_key",
        "Plan tuition",
        "Use my sponsor account",
    ):
        assert forbidden not in text
    with services.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM audit_events").fetchone()["n"] == before
