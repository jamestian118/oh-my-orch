from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

AUTO_PASS = 0.82
ASK_LOW = 0.70
FAIL_LOW = 0.55

_HIGH_RISK_KEYWORDS = (
    "high",
    "critical",
    "severe",
    "security",
    "data-loss",
    "breaking",
)
_ROLLBACK_KEYWORDS = ("rollback", "revert", "undo", "backout", "feature flag", "feature-flag")


class ModelDecision(TypedDict, total=False):
    model: str
    status: str
    actions: list[str]
    risks: list[str]
    verification: list[str]


class ArbiterConfidence(TypedDict):
    codex: float
    gemini: float
    agreement: float
    joint: float


class ArbiterDecision(TypedDict):
    winner: str
    confidence: ArbiterConfidence
    ask: bool
    conflicts: list[str]


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []

    if isinstance(value, (list, tuple, set)):
        normalized: list[str] = []
        for item in value:
            if item is None:
                continue
            stripped = str(item).strip()
            if stripped:
                normalized.append(stripped)
        return normalized

    return []


def _schema_fraction(decision: Mapping[str, Any]) -> float:
    required = ("model", "status", "actions", "risks", "verification")
    present = sum(1 for key in required if key in decision)
    return present / float(len(required))


def _status_score(status: str) -> float:
    normalized = status.strip().lower()
    if not normalized:
        return 0.0

    if any(token in normalized for token in ("fail", "error", "blocked", "unknown")):
        return 0.0

    if any(token in normalized for token in ("ok", "pass", "success", "done", "complete")):
        return 1.0

    return 0.5


def _has_keyword(items: list[str], keywords: tuple[str, ...]) -> bool:
    lowered = [item.lower() for item in items]
    return any(keyword in item for item in lowered for keyword in keywords)


def _risk_guard_score(decision: Mapping[str, Any]) -> float:
    risks = _normalize_list(decision.get("risks"))
    if not risks:
        return 0.6

    combined_steps = _normalize_list(decision.get("actions")) + _normalize_list(
        decision.get("verification")
    )
    high_risk = _has_keyword(risks, _HIGH_RISK_KEYWORDS)
    has_rollback = _has_keyword(combined_steps, _ROLLBACK_KEYWORDS)

    if high_risk and not has_rollback:
        return 0.0
    if high_risk and has_rollback:
        return 0.65
    return 1.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_model_decision(decision: dict[str, Any]) -> float:
    if not isinstance(decision, Mapping):
        return 0.0

    schema = _schema_fraction(decision)
    actions = _normalize_list(decision.get("actions"))
    verification = _normalize_list(decision.get("verification"))
    action_score = 1.0 if actions else 0.0
    verification_score = 1.0 if verification else 0.0
    status_score = _status_score(str(decision.get("status", "")))
    risk_guard_score = _risk_guard_score(decision)

    score = (
        0.22 * schema
        + 0.18 * status_score
        + 0.22 * action_score
        + 0.18 * verification_score
        + 0.20 * risk_guard_score
    )
    return round(_clamp01(score), 4)


def _alignment(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.5
    if not left or not right:
        return 0.0
    return len(left & right) / float(len(left | right))


def agreement_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    if not isinstance(a, Mapping) or not isinstance(b, Mapping):
        return 0.0

    actions_a = {item.lower() for item in _normalize_list(a.get("actions"))}
    actions_b = {item.lower() for item in _normalize_list(b.get("actions"))}
    verification_a = {item.lower() for item in _normalize_list(a.get("verification"))}
    verification_b = {item.lower() for item in _normalize_list(b.get("verification"))}
    risks_a = {item.lower() for item in _normalize_list(a.get("risks"))}
    risks_b = {item.lower() for item in _normalize_list(b.get("risks"))}

    score = (
        0.45 * _alignment(actions_a, actions_b)
        + 0.30 * _alignment(verification_a, verification_b)
        + 0.25 * _alignment(risks_a, risks_b)
    )
    return round(_clamp01(score), 4)


def _collect_conflicts(codex: Mapping[str, Any], gemini: Mapping[str, Any]) -> list[str]:
    conflicts: list[str] = []
    codex_status = str(codex.get("status", "")).strip().lower()
    gemini_status = str(gemini.get("status", "")).strip().lower()
    if codex_status != gemini_status:
        conflicts.append("status_mismatch")

    codex_actions = {item.lower() for item in _normalize_list(codex.get("actions"))}
    gemini_actions = {item.lower() for item in _normalize_list(gemini.get("actions"))}
    if codex_actions != gemini_actions:
        conflicts.append("action_mismatch")

    codex_verification = {item.lower() for item in _normalize_list(codex.get("verification"))}
    gemini_verification = {item.lower() for item in _normalize_list(gemini.get("verification"))}
    if codex_verification != gemini_verification:
        conflicts.append("verification_mismatch")

    codex_risks = {item.lower() for item in _normalize_list(codex.get("risks"))}
    gemini_risks = {item.lower() for item in _normalize_list(gemini.get("risks"))}
    if codex_risks != gemini_risks:
        conflicts.append("risk_mismatch")

    return conflicts


def arbiter(codex: dict[str, Any], gemini: dict[str, Any]) -> ArbiterDecision:
    codex_score = score_model_decision(codex)
    gemini_score = score_model_decision(gemini)
    agreement = agreement_score(codex, gemini)
    joint = round(_clamp01(0.4 * codex_score + 0.4 * gemini_score + 0.2 * agreement), 4)
    conflicts = _collect_conflicts(codex, gemini)
    risk_mismatch = "risk_mismatch" in conflicts

    delta = abs(codex_score - gemini_score)
    if codex_score < FAIL_LOW and gemini_score < FAIL_LOW:
        winner = "fail"
        ask = False
    elif (
        not risk_mismatch
        and joint >= AUTO_PASS
        and agreement >= ASK_LOW
        and min(codex_score, gemini_score) >= ASK_LOW
    ):
        if delta <= 0.03:
            winner = "merge"
        else:
            winner = "codex" if codex_score > gemini_score else "gemini"
        ask = False
    else:
        if max(codex_score, gemini_score) < FAIL_LOW:
            winner = "fail"
            ask = False
        else:
            winner = "codex" if codex_score >= gemini_score else "gemini"
            ask = (
                risk_mismatch
                or joint < ASK_LOW
                or agreement < ASK_LOW
                or (delta > 0.15 and min(codex_score, gemini_score) < AUTO_PASS)
            )

    return {
        "winner": winner,
        "confidence": {
            "codex": codex_score,
            "gemini": gemini_score,
            "agreement": agreement,
            "joint": joint,
        },
        "ask": ask,
        "conflicts": conflicts,
    }
