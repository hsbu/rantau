"""Deterministic fraud rules independent of any language-model result."""

import re

from backend.fraud.models import AdvisorySignal, HardFinding, TrustedFraudFacts

_TEXT_RULES: tuple[tuple[AdvisorySignal, re.Pattern[str]], ...] = (
    (
        AdvisorySignal.URGENCY,
        re.compile(r"\b(urgent|immediately|right now|within (?:an )?hour|today only)\b", re.I),
    ),
    (
        AdvisorySignal.SECRECY,
        re.compile(r"\b(keep (?:this|it) secret|do not tell|don't tell|tell nobody)\b", re.I),
    ),
    (
        AdvisorySignal.IMPERSONATION,
        re.compile(
            r"\b(pretend to be|act as|impersonat\w*|from the (?:bank|university)|"
            r"(?:i am|i'm) (?:your|the) (?:parent|father|mother|guardian))\b",
            re.I,
        ),
    ),
    (
        AdvisorySignal.EMERGENCY_REQUEST,
        re.compile(r"\b(emergency|arrest|detained|fine today|rescue fee)\b", re.I),
    ),
    (
        AdvisorySignal.BENEFICIARY_CHANGE,
        re.compile(
            r"\b(change|replace|switch|update)\b.{0,50}"
            r"\b(beneficiar\w*|payee|recipient|account details)\b"
            r"|\b(new|different|another|alternate|revised)\b.{0,20}"
            r"\b(beneficiar\w*|payee|recipient|account)\b",
            re.I,
        ),
    ),
    (
        AdvisorySignal.PROMPT_INJECTION,
        re.compile(
            r"\b(ignore (?:all )?(?:previous|prior|the) (?:instructions|rules|guidance)|"
            r"override (?:the )?policy|bypass (?:approval|verification)|"
            r"reveal (?:the )?system prompt|(?:remove|clear|release) (?:the )?security hold)\b",
            re.I,
        ),
    ),
)


def hard_findings(
    message: str, facts: TrustedFraudFacts
) -> tuple[HardFinding, ...]:
    findings: list[HardFinding] = []
    if not facts.beneficiary_verified:
        findings.append(HardFinding.BENEFICIARY_UNVERIFIED)
    if not facts.beneficiary_matches_current_intent:
        findings.append(HardFinding.BENEFICIARY_MISMATCH)
    if facts.beneficiary_change_requested or any(
        signal == AdvisorySignal.BENEFICIARY_CHANGE for signal, pattern in _TEXT_RULES
        if pattern.search(message[:5000])
    ):
        findings.append(HardFinding.BENEFICIARY_CHANGE_REQUESTED)
    return tuple(findings)


def local_advisory_signals(message: str) -> tuple[AdvisorySignal, ...]:
    bounded = message[:5000]
    return tuple(signal for signal, pattern in _TEXT_RULES if pattern.search(bounded))
