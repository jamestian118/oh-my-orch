"""Step 3-5 orchestrator dry-run skeleton tests."""

from __future__ import annotations

import json

import omo
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


def test_team_dry_run_persists_summary(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)

    result = orch.team(topic="微服务还是单体", dry_run=True)

    assert result["ok"] is True
    assert result["command"] == "team"
    assert result["mode"] == "dry-run"
    assert result["agent_count"] == 3
    assert [item["agent"] for item in result["outputs"]] == ["claude", "codex", "gemini"]

    state = json.loads((tmp_path / ".omo" / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["team"]["topic"] == "微服务还是单体"
    assert state["team"]["last_mode"] == "dry-run"


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
