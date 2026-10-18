import pytest

from backend.contracts.enums import Intent
from backend.contracts.http import AgentResponse, ResourceReference, ToolEvent
from backend.contracts.models import ServiceUnavailable


def test_durable_record_excludes_prose_and_private_unlisted_tool_references():
    from backend.agent.run_records import project_run

    response = AgentResponse(
        run_id="run_test",
        requested_action=Intent.TUITION,
        message="secret sk-test-private-token user@example.org account 123456789012",
        tool_events=(ToolEvent(tool="get_account_permissions", status="OK", resource_id="acct_x"),),
        resources=(ResourceReference(kind="obligation", id="obl_demo"),),
    )
    record = project_run(response)
    assert "message" not in record.model_dump()
    assert "secret" not in record.model_dump_json()
    assert record.tool_events[0].resource_id is None
    assert record.resources == response.resources


@pytest.mark.parametrize("tool", ["secret_key", "APPROVED clear_security_hold", "override_ledger"])
def test_unknown_tool_labels_cannot_be_written_as_durable_audit(tool):
    from backend.agent.run_records import project_run

    with pytest.raises(ServiceUnavailable):
        project_run(
            AgentResponse(
                run_id="run_test",
                message="not stored",
                requested_action=None,
                tool_events=(ToolEvent(tool=tool, status="OK"),),
            )
        )


def test_protected_execution_diagnostics_are_allowed_but_grant_no_authority():
    from backend.agent.run_records import project_run

    response = AgentResponse(
        run_id="run_execution",
        requested_action=Intent.TUITION,
        message="private execution assistant prose",
        tool_events=(ToolEvent(tool="execute_payment", status="OK"),),
        resources=(ResourceReference(kind="payment", id="transfer_demo"),),
    )
    saved = project_run(response).response(response.run_id)
    assert saved.tool_events == response.tool_events
    assert "grants no financial authority" in saved.message
    assert "private execution assistant prose" not in saved.message


def test_diagnostic_count_and_size_are_bounded():
    from backend.agent.run_records import project_run

    event = ToolEvent(tool="classify_intent", status="PENDING")
    with pytest.raises(ServiceUnavailable):
        project_run(
            AgentResponse(
                run_id="run_test",
                message="not stored",
                requested_action=None,
                tool_events=(event,) * 65,
            )
        )


def test_invalid_nested_diagnostics_fail_without_logging_private_payload(capsys):
    from backend.agent.run_records import project_run

    event = ToolEvent(tool="classify_intent", status="PENDING").model_copy(
        update={"status": "private-secret-status"}
    )
    response = AgentResponse(run_id="run_test", message="not stored", requested_action=None)
    response = response.model_copy(update={"tool_events": (event,)})
    with pytest.raises(ServiceUnavailable) as error:
        project_run(response)
    assert "private-secret" not in str(error.value)
    assert "private-secret" not in capsys.readouterr().err
