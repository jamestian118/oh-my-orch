from __future__ import annotations

from pathlib import Path

from lib.integrations import CSMIntegration, HandoffIntegration, build_integrations


def test_build_integrations_uses_stub_on_dry_run(tmp_path) -> None:
    hub = build_integrations(tmp_path, dry_run=True)
    result = hub.policy_check()
    assert result.ok is True
    assert result.data["strict_result"] == "pass"


def test_csm_integration_reports_unavailable_for_missing_root(tmp_path) -> None:
    client = CSMIntegration(csm_root=tmp_path / "missing-csm")
    result = client.list_sessions()
    assert result.ok is False
    assert "CSM unavailable" in result.error


def test_handoff_integration_prefers_richer_snapshot(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir(parents=True)

    local_snap_dir = project / ".ai" / "handoff" / "sessions"
    local_snap_dir.mkdir(parents=True)
    local_path = local_snap_dir / "codex-abc.md"
    rich_snapshot = (
        "# snapshot\n"
        "Repo root / 仓库根目录\n"
        "## Repo State / 仓库状态\n"
        "Repo Handoff File (excerpt)\n"
    )
    local_path.write_text(
        rich_snapshot,
        encoding="utf-8",
    )

    global_root = tmp_path / "global-handoff"
    global_snap_dir = global_root / "sessions"
    global_snap_dir.mkdir(parents=True)
    (global_snap_dir / "codex-abc.md").write_text("# weak snapshot\n", encoding="utf-8")

    monkeypatch.setenv("CSM_HANDOFF_ROOTS", str(global_root))

    handoff = HandoffIntegration(project_root=project)
    result = handoff.read_snapshot("abc", "codex", project=str(project))
    assert result.ok is True
    assert Path(result.data["path"]) == local_path
    assert "Repo State" in result.data["content"]
