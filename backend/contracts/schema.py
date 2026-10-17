"""Export the agreed endpoint catalogue without serving unimplemented endpoints."""

from typing import Any

from pydantic.json_schema import models_json_schema

from backend.contracts import http, models
from backend.contracts.auth import ConsentRequest, ConsentSummary, LoginRequest, SessionSummary

SCHEMA_MODELS = (
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
    LoginRequest,
    SessionSummary,
    ConsentRequest,
    ConsentSummary,
)


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
        "/tuition/obligations": "TuitionObligation",
        "/tuition/obligations/{id}": "TuitionObligation",
        "/quotes": "FxQuote",
        "/payment-intents": "IntentCreated",
        "/payment-intents/{id}": "PaymentIntent",
        "/payment-intents/{id}/approval-requests": "ApprovalRequest",
        "/sponsor/approvals": "Approval",
        "/sponsor/approvals/{id}/decision": "SponsorDecisionResult",
        "/payment-intents/{id}/execute": "ExecutionResult",
        "/payment-intents/{id}/cancel": "PaymentIntent",
        "/transfers/{id}": "PaymentResult",
        "/reconciliations/{id}": "ReconciliationCase",
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
        "/reconciliations": "CaseSubmission",
        "/auth/login": "LoginRequest",
        "/student/sharing-consents/{sponsor_id}": "ConsentRequest",
    }
    arrays = {"/tuition/obligations", "/quotes", "/sponsor/approvals"}
    paths: dict[str, Any] = {}
    for method, full_path in http.HTTP_ENDPOINTS:
        path = full_path.removeprefix("/api/v1")
        model_name = responses.get(path)
        result: dict[str, Any] = (
            {"$ref": f"#/components/schemas/{model_name}"} if model_name else {"type": "object"}
        )
        if path in arrays:
            result = {"type": "array", "items": result}
        operation_name = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
        operation: dict[str, Any] = {
            "operationId": f"{method.lower()}_{operation_name}",
            "security": [{"Session": []}],
            "x-owner": "A" if path.startswith("/agent") else "B/C",
            "x-implementation": "catalogue-only",
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
        if is_auth:
            operation["x-owner"] = "B"
            operation["x-implementation"] = "implemented"
            operation["responses"]["403"] = {"description": "Trusted origin required"}
            operation["responses"]["422"] = {"description": "Invalid request (sanitized)"}
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
        if path.endswith("/execute"):
            parameters.append(
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "minLength": 1},
                }
            )
        if is_auth and method != "GET":
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
                "required": True,
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
