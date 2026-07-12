"""Regression tests for team arbiter gate behavior and decision artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.agents import AgentRunResult
from lib.orchestrator import Orchestrator


def _build_fake_run_agent():
    def fake_run_agent(self, **kwargs) -> AgentRunResult:
        agent = str(kwargs["agent"])
        prompt = str(kwargs["prompt"])
        interactive = bool(kwargs["interactive"])
        run_dry = bool(kwargs["run_dry"])
        cwd = str(kwargs["cwd"])

        def _result(stdout: str, *, returncode: int = 0, stderr: str = "") -> AgentRunResult:
            return AgentRunResult(
                tool=agent,
                mode="interactive" if interactive else "non_interactive",
                command=("stub",),
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                dry_run=run_dry,
                cwd=cwd,
            )

        if agent == "claude" and "从架构设计和长期维护角度讨论。" in prompt:
            return _result("# claude viewpoint\n\n- suggestion: stage rollout by batch\n")

        if agent == "codex" and "从实现复杂度和开发效率角度分析。" in prompt:
            decision = {
                "model": "codex",
                "status": "success",
                "actions": ["migrate table schema"],
                "risks": ["high security impact"],
                "verification": ["./scripts/test tests/test_step3_to_step5_orchestrator.py"],
            }
            return _result(json.dumps(decision, ensure_ascii=False))

        if agent == "gemini" and "从成本、性能、团队规模角度分析。" in prompt:
            decision = {
                "model": "gemini",
                "status": "success",
                "actions": ["migrate table schema"],
                "risks": ["low"],
                "verification": ["./scripts/test tests/test_step3_to_step5_orchestrator.py"],
            }
            return _result(json.dumps(decision, ensure_ascii=False))

        if agent == "gemini" and "你是 team 模式的唯一总结 agent" in prompt:
            return _result("# Team Summary\n\n- synthesized: true\n")

        if agent == "claude" and "你是项目技术负责人" in prompt:
            return _result("# Project Brief\n\n- scope: team arbiter regression\n")

        return _result("# fallback stage output\n")

    return fake_run_agent


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_arbiter_shape(payload: dict[str, Any], *, ask_expected: bool) -> None:
    assert isinstance(payload, dict)
    for key in ("winner", "confidence", "ask", "conflicts"):
        assert key in payload

    confidence = payload["confidence"]
    assert isinstance(confidence, dict)
    for key in ("codex", "gemini", "agreement", "joint"):
        assert key in confidence

    assert payload["ask"] is ask_expected
    assert isinstance(payload["conflicts"], list)
    assert "risk_mismatch" in payload["conflicts"]


def _assert_decisions_artifacts(run_dir: Path, *, ask_expected: bool) -> None:
    decisions_dir = run_dir / "decisions"
    assert (decisions_dir / "context-pack.json").exists()
    assert (decisions_dir / "codex.json").exists()
    assert (decisions_dir / "gemini.json").exists()
    assert (decisions_dir / "arbiter.json").exists()
    if ask_expected:
        assert (decisions_dir / "ask.json").exists()


def test_team_arbiter_gate_off_keeps_compatibility_and_writes_decisions(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("OMO_TEAM_ARBITER_GATE", raising=False)
    monkeypatch.setattr(Orchestrator, "_run_agent", _build_fake_run_agent())
    orch = Orchestrator(root_dir=tmp_path, dry_run=False)

    result = orch.team(topic="team arbiter gate off compatibility", dry_run=False)

    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["arbiter"]["gate_mode"] == "soft"
    run_dir = Path(result["run_dir"])
    _assert_decisions_artifacts(run_dir, ask_expected=True)

    arbiter_payload = _read_json(run_dir / "decisions" / "arbiter.json")
    _assert_arbiter_shape(arbiter_payload, ask_expected=True)


def test_team_arbiter_gate_on_blocks_when_ask_true_and_returns_arbiter(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OMO_TEAM_ARBITER_GATE", "strict")
    monkeypatch.setattr(Orchestrator, "_run_agent", _build_fake_run_agent())
    orch = Orchestrator(root_dir=tmp_path, dry_run=False)

    result = orch.team(topic="team arbiter gate on ask true", dry_run=False)

    assert result["ok"] is False
    assert result["exit_code"] == 42
    assert result["arbiter"]["gate_mode"] == "strict"
    _assert_arbiter_shape(result["arbiter"], ask_expected=True)

    run_dir = Path(result["run_dir"])
    _assert_decisions_artifacts(run_dir, ask_expected=True)

    meta_payload = _read_json(Path(result["meta_file"]))
    _assert_arbiter_shape(meta_payload["arbiter"], ask_expected=True)
