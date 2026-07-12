"""Pipeline resume / cleanup boundary tests."""

from __future__ import annotations

import json
import sys

from lib.agents import AgentRunResult
from lib.orchestrator import PIPELINE_STAGES, Orchestrator


def test_resume_in_progress_pipeline_completes_in_dry_run(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)

    staged = orch.pipeline(task="恢复中断任务", dry_run=True, stop_after=2)
    assert staged["ok"] is True
    assert staged["stopped_after"] == 2

    resumed = orch.resume(dry_run=True)
    assert resumed["ok"] is True
    assert resumed["command"] == "resume"
    assert resumed["can_resume"] is True
    assert resumed["resume_from"] == "stage2_codex_execute"

    state = json.loads((tmp_path / ".omo" / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["pipeline"]["status"] == "completed"
    assert state["pipeline"]["completed_stages"] == PIPELINE_STAGES


def test_resume_idle_state_returns_can_resume_false(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)
    state = orch.load_state()
    state["pipeline"]["task"] = "已有任务但空闲"
    state["pipeline"]["status"] = "idle"
    state["pipeline"]["current_stage"] = "stage2_codex_execute"
    orch.save_state(state)

    resumed = orch.resume(dry_run=True)
    assert resumed["ok"] is True
    assert resumed["command"] == "resume"
    assert resumed["can_resume"] is False
    assert "当前状态为 idle" in resumed["message"]


def test_resume_without_task_returns_can_resume_false(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)
    state = orch.load_state()
    state["pipeline"]["task"] = ""
    state["pipeline"]["status"] = "in_progress"
    state["pipeline"]["current_stage"] = "stage1_exec_plan"
    orch.save_state(state)

    resumed = orch.resume(dry_run=True)
    assert resumed["ok"] is True
    assert resumed["command"] == "resume"
    assert resumed["can_resume"] is False
    assert resumed["message"] == "无可恢复 pipeline 任务。"


def test_cleanup_handles_managed_sandbox_and_skips_unmanaged_worktree(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)
    sandbox = tmp_path / ".omo" / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "marker.txt").write_text("sandbox", encoding="utf-8")

    foreign = tmp_path / "foreign-worktree"
    foreign.mkdir(parents=True, exist_ok=True)
    (foreign / "keep.txt").write_text("keep", encoding="utf-8")

    state = orch.load_state()
    state["pipeline"]["worktree_path"] = str(foreign)
    state["pipeline"]["worktree_branch"] = "main"
    state["pipeline"]["current_stage"] = "stage4_codex_fix"
    orch.save_state(state)

    cleaned = orch.cleanup()
    assert cleaned["ok"] is True
    assert cleaned["command"] == "cleanup"
    assert str(sandbox.resolve()) in cleaned["removed_paths"]
    assert str(foreign.resolve()) in cleaned["skipped_paths"]

    assert not sandbox.exists()
    assert foreign.exists()

    post_state = orch.load_state()
    assert post_state["pipeline"]["worktree_path"] == ""
    assert post_state["pipeline"]["worktree_branch"] == ""
    assert post_state["pipeline"]["current_stage"] == ""


def test_stage1_skips_resume_when_shell_is_not_tty(tmp_path, monkeypatch) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=False)
    calls: list[dict[str, object]] = []

    def fake_run_agent(self, **kwargs):
        calls.append(kwargs)
        stdout = '{"session_id":"sid-live-smoke"}' if len(calls) == 1 else ""
        return AgentRunResult(
            tool=str(kwargs["agent"]),
            mode="interactive" if bool(kwargs["interactive"]) else "non_interactive",
            command=("stub",),
            returncode=0,
            stdout=stdout,
            stderr="",
            dry_run=False,
            cwd=str(kwargs["cwd"]),
        )

    class _NoTTY:
        @staticmethod
        def isatty() -> bool:
            return False

    monkeypatch.setattr(Orchestrator, "_run_agent", fake_run_agent)
    monkeypatch.setattr(sys, "stdin", _NoTTY())

    result = orch._stage1_exec_plan("live smoke stage1", run_dry=False, cwd=tmp_path)
    assert result.ok is True
    assert result.details["resumed"] is False
    assert "non-interactive shell" in result.details["resume_skipped_reason"]
    assert len(calls) == 1
    assert (tmp_path / ".ai" / "exec-plan.md").exists()
