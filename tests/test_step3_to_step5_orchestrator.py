"""Step 3-5 orchestrator dry-run skeleton tests."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import omo
from lib.agents import AgentRunResult
from lib.orchestrator import Orchestrator


def test_pipeline_dry_run_creates_contract_files_and_state(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)

    result = orch.pipeline(task="给项目添加用户认证", dry_run=True)

    assert result["ok"] is True
    assert result["command"] == "pipeline"
    assert result["mode"] == "dry-run"

    project_brief = tmp_path / ".ai" / "project-brief.md"
    exec_plan = tmp_path / ".ai" / "exec-plan.md"
    review = tmp_path / ".ai" / "review.md"
    for contract_file in (project_brief, exec_plan, review):
        assert contract_file.exists()
        assert "DRY-RUN" in contract_file.read_text(encoding="utf-8")

    run_dir = Path(result["run_dir"])
    assert run_dir.exists()
    assert re.match(r"^\d{8}-\d{6}-", run_dir.name), run_dir.name
    assert re.search(r"-[0-9a-f]{8}$", run_dir.name), run_dir.name
    assert (run_dir / "project-brief.md").exists()
    assert (run_dir / "exec-plan.md").exists()
    assert (run_dir / "review.md").exists()
    assert (run_dir / "pipeline-summary.md").exists()
    assert (run_dir / "meta.json").exists()
    assert Path(result["summary_file"]) == run_dir / "pipeline-summary.md"
    assert Path(result["latest_summary_file"]).exists()
    assert Path(result["meta_file"]) == run_dir / "meta.json"

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "completed"
    assert meta["run_id"] == run_dir.name

    state = json.loads((tmp_path / ".omo" / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["pipeline"]["status"] == "completed"
    assert state["pipeline"]["completed_stages"] == [
        "stage0_project_brief",
        "stage1_exec_plan",
        "stage2_codex_execute",
        "stage3_gemini_review",
        "stage4_codex_fix",
        "stage5_final_review",
    ]
    assert state["pipeline"]["run_dir"] == str(run_dir)
    assert state["pipeline"]["summary_file"] == str(run_dir / "pipeline-summary.md")
    assert state["pipeline"]["started_at"].endswith("+08:00")
    assert state["pipeline"]["finished_at"].endswith("+08:00")


def test_team_dry_run_persists_summary(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)
    topic = "API auth rollout plan"

    result = orch.team(topic=topic, dry_run=True)

    assert result["ok"] is True
    assert result["command"] == "team"
    assert result["mode"] == "dry-run"
    assert result["agent_count"] == 3
    assert [item["agent"] for item in result["outputs"]] == ["claude", "codex", "gemini"]
    for output in result["outputs"]:
        assert "stdout_empty" in output
        assert "stdout_len" in output
        assert isinstance(output["stdout_empty"], bool)
        assert isinstance(output["stdout_len"], int)
        assert output["stdout_len"] >= 0
        if output["stdout_empty"]:
            assert output["stdout_len"] == 0
    assert [item["step"] for item in result["summary_steps"]] == ["team_summary"]
    assert [item["agent"] for item in result["summary_steps"]] == ["gemini"]

    run_dir = Path(result["run_dir"])
    assert run_dir.exists()
    assert re.match(r"^\d{8}-\d{6}-", run_dir.name), run_dir.name
    assert "api-auth-rollout-plan" in run_dir.name
    assert re.search(r"-[0-9a-f]{8}$", run_dir.name), run_dir.name
    assert (run_dir / "agents" / "claude.md").exists()
    assert (run_dir / "agents" / "codex.md").exists()
    assert (run_dir / "agents" / "gemini.md").exists()
    assert (run_dir / "team-summary.md").exists()
    assert (run_dir / "meta.json").exists()

    assert Path(result["summary_file"]) == run_dir / "team-summary.md"
    assert Path(result["latest_summary_file"]).exists()
    assert Path(result["meta_file"]) == run_dir / "meta.json"

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["ran_at"].endswith("+08:00")

    state = json.loads((tmp_path / ".omo" / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["team"]["topic"] == topic
    assert state["team"]["last_mode"] == "dry-run"
    assert state["team"]["run_dir"] == str(run_dir)
    assert state["team"]["summary_file"] == str(run_dir / "team-summary.md")
    assert state["team"]["ran_at"].endswith("+08:00")


def test_team_live_empty_stdout_marks_failure_and_status(tmp_path, monkeypatch) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=False)

    def fake_run_agent(self, **kwargs):
        agent = str(kwargs["agent"])
        prompt = str(kwargs["prompt"])
        interactive = bool(kwargs["interactive"])
        stdout = f"# {agent} output\n\n- note: synthetic content\n"
        returncode = 0

        if agent == "claude" and "从架构设计和长期维护角度讨论。" in prompt:
            stdout = ""
            returncode = 1
        elif agent == "gemini" and (
            "请综合三方观点给出结论与推荐路径。" in prompt or "team-summary.md" in prompt
        ):
            stdout = ""

        return AgentRunResult(
            tool=agent,
            mode="interactive" if interactive else "non_interactive",
            command=("stub",),
            returncode=returncode,
            stdout=stdout,
            stderr="",
            dry_run=False,
            cwd=str(kwargs["cwd"]),
        )

    monkeypatch.setattr(Orchestrator, "_run_agent", fake_run_agent)

    result = orch.team(topic="live 空 stdout 回退", dry_run=False)

    assert result["ok"] is False
    assert result["mode"] == "live"

    claude_output = next(item for item in result["outputs"] if item["agent"] == "claude")
    claude_output_file = Path(claude_output["output_file"])
    assert claude_output_file.exists()
    assert "stdout empty" in claude_output_file.read_text(encoding="utf-8")

    def _is_step_marked(step: dict[str, object]) -> bool:
        if "status" in step:
            return str(step["status"]) in {"skipped", "fallback"}
        return bool(step.get("skipped")) or bool(step.get("fallback"))

    assert result["summary_steps"], "summary_steps 不能为空"
    assert all(_is_step_marked(step) for step in result["summary_steps"]), (
        "summary_steps 未按失败路径标记 skipped/fallback"
    )

    meta = json.loads(Path(result["meta_file"]).read_text(encoding="utf-8"))
    assert "viewpoints_ok" in meta, "meta.json 缺少新增状态字段 viewpoints_ok"
    assert meta["viewpoints_ok"] is False
    assert meta["viewpoint_failures"]


def test_team_viewpoint_stage_runs_in_parallel_and_keeps_output_order(
    tmp_path, monkeypatch
) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)
    viewpoint_barrier = threading.Barrier(3)
    viewpoint_calls: list[str] = []
    lock = threading.Lock()

    def fake_run_agent(self, **kwargs):
        agent = str(kwargs["agent"])
        prompt = str(kwargs["prompt"])
        interactive = bool(kwargs["interactive"])
        run_dry = bool(kwargs["run_dry"])

        is_viewpoint_call = (
            "从架构设计和长期维护角度讨论。" in prompt
            or "从实现复杂度和开发效率角度分析。" in prompt
            or "从成本、性能、团队规模角度分析。" in prompt
        )
        if is_viewpoint_call:
            with lock:
                viewpoint_calls.append(agent)
            try:
                viewpoint_barrier.wait(timeout=1.0)
            except threading.BrokenBarrierError as exc:
                raise AssertionError("team 观点阶段未并行执行（检测到串行路径）") from exc
            return AgentRunResult(
                tool=agent,
                mode="interactive" if interactive else "non_interactive",
                command=("stub",),
                returncode=0,
                stdout=f"# {agent} viewpoint\n\n- mode: {'dry-run' if run_dry else 'live'}\n",
                stderr="",
                dry_run=run_dry,
                cwd=str(kwargs["cwd"]),
            )

        if agent == "gemini" and (
            "请综合三方观点给出结论与推荐路径。" in prompt or "team-summary.md" in prompt
        ):
            return AgentRunResult(
                tool=agent,
                mode="interactive" if interactive else "non_interactive",
                command=("stub",),
                returncode=0,
                stdout="# summary\n\n- ok: true\n",
                stderr="",
                dry_run=run_dry,
                cwd=str(kwargs["cwd"]),
            )

        return AgentRunResult(
            tool=agent,
            mode="interactive" if interactive else "non_interactive",
            command=("stub",),
            returncode=0,
            stdout="# stage0\n",
            stderr="",
            dry_run=run_dry,
            cwd=str(kwargs["cwd"]),
        )

    monkeypatch.setattr(Orchestrator, "_run_agent", fake_run_agent)

    result = orch.team(topic="并行观点阶段回归测试", dry_run=True)

    assert result["ok"] is True
    assert set(viewpoint_calls) == {"claude", "codex", "gemini"}
    assert [item["agent"] for item in result["outputs"]] == ["claude", "codex", "gemini"]


def test_agent_chat_command_writes_history_in_dry_run(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = omo.main(["@codex", "chat", "实现 dry-run 路由", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["command"] == "chat"
    assert payload["mode"] == "dry-run"
    assert payload["agent"] == "codex"

    history_file = tmp_path / ".omo" / "chat-history.jsonl"
    assert history_file.exists()
    lines = history_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["agent"] == "codex"
    assert first["role"] == "user"
    assert second["role"] == "assistant"
