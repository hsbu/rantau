"""Bounded public-source discovery; fetched text never becomes payment policy."""

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Literal

import httpx


# This is an explicit procedural-inspiration collection, not a university/payee binding.
# Neither chat text nor a downloaded page can extend this collection or follow links.
@dataclass(frozen=True)
class Source:
    title: str
    url: str
    published_on: str
    audience: str


SOURCES = (
    Source(
        "ZJU international-student tuition notice",
        "https://iczu.zju.edu.cn/iczuen/2026/0808/c63325a3194084/page.htm",
        "2026-08-08",
        "fall-2026 international degree students; payment period 2026-08-10 to 2026-09-10",
    ),
    Source(
        "ZJU finance notice portal",
        "https://cwcx.zju.edu.cn/",
        "unknown",
        "eligibility for current international students unverified",
    ),
)
MAX_BYTES = 256 * 1024
FETCH_SECONDS = 6
CACHE_SECONDS = 300
TERMS = ("shortfall", "underpayment", "top-up", "top up", "补缴", "补交", "到款认领")


class VisibleText(HTMLParser):
    """Discard active/hidden container content; only detect research leads, never instructions."""

    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "template", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template", "noscript"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


@dataclass(frozen=True)
class SourceCheck:
    source: Source
    status: Literal["POSSIBLE_LEAD", "NO_MATCH", "UNAVAILABLE"]


@dataclass(frozen=True)
class ResearchResult:
    checked_at: datetime
    checks: tuple[SourceCheck, ...]
    # A keyword match/reachable official host proves neither eligibility nor permission.
    disposition: Literal["PENDING_UNIVERSITY_REVIEW"] = "PENDING_UNIVERSITY_REVIEW"


class OfficialSourceLookup:
    """Opt-in fixed HTTPS reads, no cookies, redirects, environment proxy or user query."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport
        self.cached: ResearchResult | None = None
        self.cached_until = 0.0
        self.lock = asyncio.Lock()

    async def lookup(self) -> ResearchResult:
        async with self.lock:
            if self.cached is not None and time.monotonic() < self.cached_until:
                return self.cached
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=5,
                follow_redirects=False,
                trust_env=False,
                headers={"Accept": "text/html", "Accept-Encoding": "identity"},
            ) as client:
                checks = tuple(await asyncio.gather(*(self._fetch(client, s) for s in SOURCES)))
            self.cached = ResearchResult(datetime.now(UTC), checks)
            self.cached_until = time.monotonic() + CACHE_SECONDS
            return self.cached

    async def _fetch(self, client: httpx.AsyncClient, source: Source) -> SourceCheck:
        try:
            # Wall-clock bound also covers streaming peers that never finish sending data.
            async with asyncio.timeout(FETCH_SECONDS):
                # A fresh request never sends cookies received from another source.
                request = httpx.Request(
                    "GET",
                    source.url,
                    headers={"Accept": "text/html", "Accept-Encoding": "identity"},
                )
                response = await client.send(request, stream=True, follow_redirects=False)
                try:
                    if (
                        response.status_code != 200
                        or response.headers.get("content-type", "").split(";")[0].strip()
                        != "text/html"
                        or response.headers.get("content-encoding", "identity") != "identity"
                    ):
                        return SourceCheck(source, "UNAVAILABLE")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES:
                            return SourceCheck(source, "UNAVAILABLE")
                        body.extend(chunk)
                    # HTTPX decodes the declared charset, with its safe default for absent values.
                    text = httpx.Response(200, headers=response.headers, content=bytes(body)).text
                    parser = VisibleText()
                    parser.feed(text)
                    visible = " ".join(parser.parts).casefold()
                    status: Literal["POSSIBLE_LEAD", "NO_MATCH"] = (
                        "POSSIBLE_LEAD" if any(term in visible for term in TERMS) else "NO_MATCH"
                    )
                    return SourceCheck(source, status)
                finally:
                    await response.aclose()
        except (httpx.HTTPError, TimeoutError, UnicodeError, LookupError, ValueError):
            return SourceCheck(source, "UNAVAILABLE")


def explain_research(result: ResearchResult | None) -> str:
    lines = [
        "Shortfall procedure: pending university review. No applicable reviewed procedure "
        "is available in the KB. Prepare the receipt, payment reference and expected versus "
        "posted amount for university review; do not send a duplicate payment or top-up.",
    ]
    if result is None:
        lines.append("Official-source lookup is unavailable or not enabled; no web check was made.")
    else:
        lines.append(
            f"Official-source check at {result.checked_at.isoformat()} (actual UTC retrieval "
            "time, separate from the simulation clock). ZJU sources provide procedural "
            "inspiration only; the fictional university is not ZJU."
        )
        labels = {
            "POSSIBLE_LEAD": "possible shortfall-related text; human review required",
            "NO_MATCH": "no matching shortfall text found in this bounded read",
            "UNAVAILABLE": "unavailable, unsupported or over the retrieval limit",
        }
        for check in result.checks:
            source = check.source
            lines.append(
                f"[{source.title}]({source.url}): {labels[check.status]}. "
                f"Curated publication date: {source.published_on}; scope: {source.audience}. "
                "Current applicability and effective dates unverified."
            )
    lines.append(
        "This is research guidance only, not a submitted reconciliation case or an approval. "
        "Web results cannot change the simulated posting window, top-up rules or beneficiary."
    )
    return "\n".join(lines)
