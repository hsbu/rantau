"""Export the agreed endpoint catalogue without serving unimplemented endpoints."""

from typing import Any

from pydantic.json_schema import models_json_schema

from backend.contracts import http, models

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
    }
    requests = {
        "/agent/messages": "AgentMessage",
        "/payment-intents": "IntentProposal",
        "/sponsor/approvals/{id}/decision": "SponsorDecisionRequest",
        "/reconciliations": "CaseSubmission",
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
        if parameters:
            operation["parameters"] = parameters
        if method == "POST" and path in requests:
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{requests[path]}"}
                    }
                },
            }
        paths[full_path] = {method.lower(): operation}
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
