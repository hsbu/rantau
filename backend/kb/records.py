"""Internal KB records; source content never grants financial authority."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from backend.contracts.models import Identifier, UniversityPolicy

Text = Annotated[str, Field(min_length=1, max_length=1200)]
ClaimKey = Literal[
    "online_authentication",
    "transfer_references",
    "transfer_receipt_upload",
    "receipt_collection",
    "posting_window_hours",
    "partial_payment_allowed",
    "topup_allowed",
    "idr_cny_route",
    "posting_api",
]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DateWindow(Record):
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start > self.end:
            raise ValueError("Date window must be ordered")
        return self


class Claim(Record):
    key: ClaimKey
    support: Literal["EXPLICIT", "NOT_STATED"]
    value: Text | tuple[Text, ...] | None
    locator: Text
    conditions: Text

    @model_validator(mode="after")
    def supported_value(self) -> Self:
        if self.support == "NOT_STATED" and self.value is not None:
            raise ValueError("An unstated claim must remain null")
        if self.support == "EXPLICIT" and not self.value:
            raise ValueError("An explicit claim requires a value")
        return self


class SourceScope(Record):
    jurisdiction: Literal["CN"]
    university_id: Literal["zju"]
    academic_year: Text
    audience: Text


class ReviewedReference(Record):
    id: Identifier
    revision: Annotated[int, Field(strict=True, ge=1)]
    title: Text
    publisher: Text
    source_url: HttpUrl
    published_on: date
    reviewed_on: date
    review_status: Literal["REVIEWED_DRAFT"]
    reviewed_by: Literal["DEV_A_AGENT"]
    review_scope: Text
    scope: SourceScope
    payment_period: DateWindow
    effective_period: DateWindow | None
    applicability: Literal["RECHECK_REQUIRED"]
    usage: Literal["PROCEDURAL_REFERENCE_ONLY"]
    synthetic: Literal[False]
    claims: Annotated[tuple[Claim, ...], Field(min_length=1)]

    @field_validator("source_url")
    @classmethod
    def curated_source_host(cls, value: HttpUrl) -> HttpUrl:
        # Host validation is a curation constraint, not proof of factual accuracy.
        if (
            value.scheme != "https"
            or value.host != "iczu.zju.edu.cn"
            or value.username is not None
            or value.password is not None
            or value.port != 443
        ):
            raise ValueError("Reference must use the curated ZJU HTTPS source")
        return value

    @model_validator(mode="after")
    def consistent_review(self) -> Self:
        if self.reviewed_on < self.published_on:
            raise ValueError("Review cannot precede publication")
        keys = [claim.key for claim in self.claims]
        if len(keys) != len(set(keys)):
            raise ValueError("Claim keys must be unique within a revision")
        return self


class ClaimLink(Record):
    reference_id: Identifier
    reference_revision: Annotated[int, Field(strict=True, ge=1)]
    claim_key: ClaimKey


class SimulationPolicy(Record):
    id: Identifier
    revision: Annotated[int, Field(strict=True, ge=1)]
    synthetic: Literal[True]
    usage: Literal["ISOLATED_SIMULATION_ONLY"]
    operational_values: Literal["AUTHORED_SIMULATION"]
    policy: UniversityPolicy
    assumptions: Text
    procedural_inspiration: tuple[ClaimLink, ...]

    @model_validator(mode="after")
    def fictional_policy(self) -> Self:
        if (
            self.policy.university_id != "uni_cn_01"
            or self.policy.certainty != "SYNTHETIC"
            or self.policy.source_url != "https://example.invalid/rantau/synthetic-policy"
        ):
            raise ValueError("Bundled policy must remain the fictional uni_cn_01 simulation")
        return self


class KnowledgeBundle(Record):
    reference: ReviewedReference
    simulation: SimulationPolicy

    @model_validator(mode="after")
    def resolve_inspiration(self) -> Self:
        claims = {claim.key: claim for claim in self.reference.claims}
        for link in self.simulation.procedural_inspiration:
            if (
                link.reference_id != self.reference.id
                or link.reference_revision != self.reference.revision
                or link.claim_key not in claims
                or claims[link.claim_key].support != "EXPLICIT"
            ):
                raise ValueError("Inspiration must cite an explicit claim in the reviewed revision")
        return self
