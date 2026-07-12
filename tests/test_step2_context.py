"""Step 2: ContextManager 预算与压缩回退测试。"""

from __future__ import annotations

import pytest

from lib.context import (
    ABS_CAP,
    AGENT_PROFILES,
    HARD_RATIO,
    SOFT_RATIO,
    ContextManager,
    calculate_limits,
)


def _make_text_for_tokens(tokens: int) -> str:
    return "x" * (tokens * 3)


def test_calculate_limits_respects_ratios_and_abs_cap() -> None:
    claude_limits = calculate_limits("claude")
    claude_available = AGENT_PROFILES["claude"]["window"] - AGENT_PROFILES["claude"]["overhead"]
    assert claude_limits.soft_limit == int(claude_available * SOFT_RATIO)
    assert claude_limits.hard_limit == int(claude_available * HARD_RATIO)
    assert claude_limits.hard_limit <= ABS_CAP

    codex_limits = calculate_limits("codex")
    codex_available = AGENT_PROFILES["codex"]["window"] - AGENT_PROFILES["codex"]["overhead"]
    assert codex_limits.soft_limit == int(codex_available * SOFT_RATIO)
    assert codex_limits.hard_limit == int(codex_available * HARD_RATIO)
    assert codex_limits.soft_limit < codex_limits.hard_limit

    gemini_limits = calculate_limits("gemini")
    assert gemini_limits.soft_limit == ABS_CAP
    assert gemini_limits.hard_limit == ABS_CAP


def test_inspect_budget_soft_warning_and_hard_trigger() -> None:
    manager = ContextManager(compressor=lambda _: "unused")
    limits = calculate_limits("codex")

    below_soft = _make_text_for_tokens(limits.soft_limit - 1)
    status_below = manager.inspect_budget(below_soft, "codex")
    assert status_below.warning is False
    assert status_below.must_compress is False

    at_soft = _make_text_for_tokens(limits.soft_limit)
    status_soft = manager.inspect_budget(at_soft, "codex")
    assert status_soft.warning is True
    assert status_soft.must_compress is False

    at_hard = _make_text_for_tokens(limits.hard_limit)
    status_hard = manager.inspect_budget(at_hard, "codex")
    assert status_hard.warning is True
    assert status_hard.must_compress is True
    assert manager.should_compress(at_hard, "codex") is True


def test_build_compression_prompt_is_target_aware() -> None:
    manager = ContextManager(compressor=lambda _: "unused")
    source = "Task: update lib/context.py and tests/test_step2_context.py."

    codex_prompt = manager.build_compression_prompt(source, "codex")
    claude_prompt = manager.build_compression_prompt(source, "claude")
    gemini_prompt = manager.build_compression_prompt(source, "gemini")

    assert "Target agent: codex" in codex_prompt
    assert "需要修改的文件、目标行为、验收命令" in codex_prompt

    assert "Target agent: claude" in claude_prompt
    assert "设计决策、约束条件、权衡与风险" in claude_prompt

    assert "Target agent: gemini" in gemini_prompt
    assert "原始方案意图、变更范围、review 关注点" in gemini_prompt


def test_compress_context_fallback_on_dry_run() -> None:
    calls = {"count": 0}

    def compressor(_: str) -> str:
        calls["count"] += 1
        return "compressed text"

    manager = ContextManager(compressor=compressor)
    limits = calculate_limits("codex")
    large_text = _make_text_for_tokens(limits.hard_limit + 100)
    result = manager.compress_context(large_text, "codex", dry_run=True)

    assert calls["count"] == 0
    assert result.dry_run is True
    assert result.compressed is False
    assert result.used_fallback is True
    assert result.reason == "dry-run"
    assert "reason: dry-run" in result.summary
    assert "target_agent: codex" in result.summary


def test_compress_context_fallback_on_compressor_failure() -> None:
    def failing_compressor(_: str) -> str:
        raise RuntimeError("boom")

    manager = ContextManager(compressor=failing_compressor)
    limits = calculate_limits("codex")
    large_text = (
        "Implement Task 2 and keep .ai/exec-plan.md as source. "
        "Files: lib/context.py tests/test_step2_context.py\n"
    )
    large_text += _make_text_for_tokens(limits.hard_limit + 200)

    result = manager.compress_context(large_text, "codex", dry_run=False)
    assert result.compressed is False
    assert result.used_fallback is True
    assert result.reason == "compressor-failed: RuntimeError"
    assert "reason: compressor-failed: RuntimeError" in result.summary
    assert "`lib/context.py`" in result.summary


def test_calculate_limits_rejects_unknown_agent() -> None:
    with pytest.raises(ValueError):
        calculate_limits("unknown-agent")
