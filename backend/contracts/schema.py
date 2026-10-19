"""Export the agreed endpoint catalogue without serving unimplemented endpoints."""

from typing import Any

from pydantic.json_schema import models_json_schema

from backend.contracts import http, models
from backend.contracts.agent_details import AgentDetailSnapshot
from backend.contracts.auth import ConsentRequest, ConsentSummary, LoginRequest, SessionSummary
from backend.contracts.authority import ApprovalView, MandateRequest, MandateView
from backend.contracts.security import SecurityCaseList, SecurityCaseView

SCHEMA_MODELS = (
    AgentDetailSnapshot,
    models.ActorContext,
    models.Money,
    models.FxQuote,
    models.TuitionObligation,
    models.TrustedBeneficiary,
    models.UniversityPolicy,
    models.PaymentIntent,
    models.Approval,
    models.PolicyDecision,
    models.PaymentResult,
    models.ReconciliationCase,
    models.DomainError,
    models.PermissionSummary,
    models.TuitionObligationDetail,
    models.PaymentIntentView,
    models.PaymentOptions,
    models.FundingAccountOption,
    models.UntrustedDocument,
    models.ProviderStatusRef,
    models.FraudAssessment,
    models.ApprovalRequest,
    models.IntentProposal,
    models.CaseSubmission,
    http.AgentMessage,
    http.AgentResponse,
    http.IntentCreated,
    http.ExecutionResult,
    http.SponsorDecisionRequest,
    http.SponsorDecisionResult,
    http.CaseCreated,
    http.ExecuteRequest,
    http.ScenarioInfo,
    http.ResetRequest,
    http.ResetResult,
    http.AdvanceClockRequest,
    http.FaultRequest,
    http.TickResult,
    http.DocumentInjectRequest,
    http.AuditEntry,
    LoginRequest,
    SessionSummary,
    ConsentRequest,
    ConsentSummary,
    ApprovalView,
    MandateRequest,
    MandateView,
    SecurityCaseView,
    SecurityCaseList,
)


FINANCE_PREFIXES = (
    "/tuition/",
    "/quotes",
    "/payment-intents",
    "/transfers",
    "/reconciliations",
    "/audit",
    "/demo/",
)
# Approval requests and sponsor decisions belong to Dev B and are not served by this module.
FINANCE_EXCLUDED = ("/payment-intents/{id}/approval-requests",)


def _finance_implemented(path: str) -> bool:
    return path.startswith(FINANCE_PREFIXES) and path not in FINANCE_EXCLUDED


def contract_schema() -> dict[str, Any]:
    _, schema = models_json_schema(
        [(model, "validation") for model in SCHEMA_MODELS],
        ref_template="#/components/schemas/{model}",
    )
    definitions = schema["$defs"]
    # Never expose internal ActorContext as a caller-supplied request schema.
    responses = {
        "/agent/messages": "AgentResponse",
        "/agent/runs/{run_id}": "AgentResponse",
        "/agent/conversations/{conversation_id}/details": "AgentDetailSnapshot",
        "/tuition/obligations": "TuitionObligationDetail",
        "/tuition/obligations/{id}": "TuitionObligationDetail",
        "/tuition/obligations/{id}/recheck": "TuitionObligationDetail",
        "/tuition/obligations/{id}/payment-options": "PaymentOptions",
        "/quotes": "FxQuote",
        "/payment-intents": "IntentCreated",
        "/payment-intents/{id}": "PaymentIntentView",
        "/payment-intents/{id}/approval-requests": "ApprovalRequest",
        "/sponsor/approvals": "ApprovalView",
        "/student/approvals": "ApprovalView",
        "/student/approvals/{id}/decision": "SponsorDecisionResult",
        "/sponsor/mandates": "MandateView",
        "/sponsor/mandates/{id}": "MandateView",
        "/sponsor/approvals/{id}/decision": "SponsorDecisionResult",
        "/payment-intents/{id}/execute": "ExecutionResult",
        "/payment-intents/{id}/cancel": "PaymentIntentView",
        "/payment-intents/{id}/revisions": "IntentCreated",
        "/documents": "UntrustedDocument",
        "/transfers/{id}": "PaymentResult",
        "/transfers/{id}/recheck": "PaymentResult",
        "/audit": "AuditEntry",
        "/demo/scenarios": "ScenarioInfo",
        "/demo/reset": "ResetResult",
        "/demo/university/tick": "TickResult",
        "/demo/audit": "AuditEntry",
        "/reconciliations/{id}": "ReconciliationCase",
        "/security-cases": "SecurityCaseList",
        "/security-cases/{id}": "SecurityCaseView",
        "/reconciliations": "CaseCreated",
        "/reconciliations/{id}/submit": "ReconciliationCase",
        "/kb/universities/{id}/payment-policy": "UniversityPolicy",
        "/auth/login": "SessionSummary",
        "/auth/session": "SessionSummary",
        "/student/sharing-consents/{sponsor_id}": "ConsentSummary",
    }
    requests = {
        "/agent/messages": "AgentMessage",
        "/payment-intents": "IntentProposal",
        "/sponsor/approvals/{id}/decision": "SponsorDecisionRequest",
        "/student/approvals/{id}/decision": "SponsorDecisionRequest",
        "/sponsor/mandates": "MandateRequest",
        "/sponsor/mandates/{id}": "MandateRequest",
        "/reconciliations": "CaseSubmission",
        "/payment-intents/{id}/execute": "ExecuteRequest",
        "/payment-intents/{id}/revisions": "IntentProposal",
        "/demo/documents": "DocumentInjectRequest",
        "/demo/reset": "ResetRequest",
        "/demo/clock/advance": "AdvanceClockRequest",
        "/demo/faults": "FaultRequest",
        "/auth/login": "LoginRequest",
        "/student/sharing-consents/{sponsor_id}": "ConsentRequest",
    }
    arrays = {
        "/tuition/obligations",
        "/quotes",
        "/sponsor/approvals",
        "/audit",
        "/documents",
        "/demo/scenarios",
        "/demo/audit",
        "/student/approvals",
        "/sponsor/mandates",
    }
    paths: dict[str, Any] = {}
    for method, full_path in http.HTTP_ENDPOINTS:
        path = full_path.removeprefix("/api/v1")
        model_name = responses.get(path)
        result: dict[str, Any] = (
            {"$ref": f"#/components/schemas/{model_name}"} if model_name else {"type": "object"}
        )
        if path in arrays and method == "GET":
            result = {"type": "array", "items": result}
        operation_name = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
        operation: dict[str, Any] = {
            "operationId": f"{method.lower()}_{operation_name}",
            "security": [{"Session": []}],
            "x-owner": "A" if path.startswith("/agent") else "B/C",
            "x-implementation": "implemented" if _finance_implemented(path) else "catalogue-only",
            "responses": {
                "200": {
                    "description": "Scoped response",
                    "content": {"application/json": {"schema": result}},
                },
                "401": {"description": "Authentication required"},
                "404": {"description": "Resource unavailable in actor scope"},
                "503": {"description": "Trusted integration unavailable"},
            },
        }
        is_auth = path.startswith(("/auth/", "/student/sharing-consents/"))
        if path == "/security-cases":
            operation["x-owner"] = "B"
            operation["x-implementation"] = "implemented-requires-finance"
        if path == "/security-cases/{id}":
            operation["x-owner"] = "B"
            operation["x-implementation"] = "implemented-requires-finance"
            operation["responses"]["422"] = {"description": "Invalid identifier (sanitized)"}
        if _finance_implemented(path):
            operation["x-owner"] = "C"
        is_authority = path.startswith(
            ("/sponsor/approvals", "/student/approvals", "/sponsor/mandates")
        ) or path.endswith("/approval-requests")
        if is_auth or is_authority:
            operation["x-owner"] = "B"
            operation["x-implementation"] = "implemented"
            operation["responses"]["403"] = {"description": "Trusted origin required"}
            operation["responses"]["422"] = {"description": "Invalid request (sanitized)"}
        if is_authority:
            operation["x-implementation"] = "implemented-requires-finance"
            operation["responses"]["409"] = {"description": "Authority is stale or conflicting"}
        if path == "/auth/login":
            operation["security"] = []
            operation["responses"]["429"] = {"description": "Login attempt limit reached"}
        if path == "/auth/logout" or method == "DELETE":
            operation["responses"].pop("200")
            operation["responses"]["204"] = {"description": "Completed without response body"}
        parameters: list[dict[str, Any]] = []
        if "{" in path:
            parameter = path.split("{")[1].split("}")[0]
            parameters.append(
                {"name": parameter, "in": "path", "required": True, "schema": {"type": "string"}}
            )
        if path == "/agent/conversations/{conversation_id}/details":
            operation["x-implementation"] = "implemented"
            parameters.append(
                {
                    "name": "run_id",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string", "minLength": 1, "maxLength": 128},
                }
            )
        if path.endswith("/execute"):
            parameters.append(
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "minLength": 1},
                }
            )
        if (is_auth or is_authority) and method != "GET":
            parameters.append(
                {
                    "name": "Origin",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                }
            )
        if parameters:
            operation["parameters"] = parameters
        if method in {"POST", "PUT"} and path in requests:
            operation["requestBody"] = {
                "required": not path.endswith("/execute"),
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{requests[path]}"}
                    }
                },
            }
        paths.setdefault(full_path, {})[method.lower()] = operation
    return {
        "openapi": "3.1.0",
        "info": {"title": "Rantau v1 contract catalogue", "version": "0.1.0"},
        "paths": paths,
        "components": {
            "schemas": definitions,
            "securitySchemes": {"Session": {"type": "apiKey", "in": "cookie", "name": "session"}},
        },
        "x-note": (
            "Catalogue only. Runtime app implements a subset; B owns final session transport."
        ),
    }
