from __future__ import annotations

from lib.decision_arbiter import arbiter, score_model_decision


def test_arbiter_high_scores_and_alignment_no_ask() -> None:
    codex = {
        "model": "codex",
        "status": "success",
        "actions": ["update migration script", "add rollback hook"],
        "risks": ["low"],
        "verification": ["./scripts/test tests/test_step1_core.py", "rollback smoke"],
    }
    gemini = {
        "model": "gemini",
        "status": "success",
        "actions": ["add rollback hook", "update migration script"],
        "risks": ["low"],
        "verification": ["rollback smoke", "./scripts/test tests/test_step1_core.py"],
    }

    result = arbiter(codex, gemini)

    assert result["winner"] in {"merge", "codex", "gemini"}
    assert result["winner"] != "fail"
    assert result["ask"] is False


def test_arbiter_mid_scores_with_risk_mismatch_asks_for_human() -> None:
    codex = {
        "model": "codex",
        "status": "success",
        "actions": ["migrate table schema"],
        "risks": ["high security impact"],
        "verification": ["./scripts/test tests/test_step2_context.py"],
    }
    gemini = {
        "model": "gemini",
        "status": "success",
        "actions": ["migrate table schema"],
        "risks": ["low"],
        "verification": ["./scripts/test tests/test_step2_context.py"],
    }

    result = arbiter(codex, gemini)

    assert "risk_mismatch" in result["conflicts"]
    assert result["ask"] is True


def test_arbiter_low_score_fails() -> None:
    codex = {
        "model": "codex",
        "status": "blocked",
        "actions": [],
        "risks": ["critical data-loss risk"],
        "verification": [],
    }
    gemini = {
        "model": "gemini",
        "status": "fail",
        "actions": [],
        "risks": ["high security risk"],
        "verification": [],
    }

    result = arbiter(codex, gemini)

    assert result["winner"] == "fail"


def test_score_model_decision_range_and_penalties() -> None:
    baseline = {
        "model": "codex",
        "status": "success",
        "actions": ["apply patch", "prepare rollback plan"],
        "risks": ["low"],
        "verification": ["pytest -q"],
    }
    missing_schema = {
        "status": "success",
        "actions": ["apply patch", "prepare rollback plan"],
        "risks": ["low"],
        "verification": ["pytest -q"],
    }
    empty_output = {
        "model": "codex",
        "status": "success",
        "actions": [],
        "risks": ["low"],
        "verification": [],
    }
    high_risk_without_rollback = {
        "model": "codex",
        "status": "success",
        "actions": ["apply patch"],
        "risks": ["critical security risk"],
        "verification": ["pytest -q"],
    }

    score_baseline = score_model_decision(baseline)
    score_missing_schema = score_model_decision(missing_schema)
    score_empty_output = score_model_decision(empty_output)
    score_high_risk = score_model_decision(high_risk_without_rollback)

    for score in (score_baseline, score_missing_schema, score_empty_output, score_high_risk):
        assert 0.0 <= score <= 1.0

    assert score_missing_schema < score_baseline
    assert score_empty_output < score_baseline
    assert score_high_risk < score_baseline
