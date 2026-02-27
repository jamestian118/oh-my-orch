from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import lib.integrations as integrations
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


def test_csm_integration_invokes_external_driver_file(tmp_path, monkeypatch) -> None:
    csm_root = tmp_path / "csm"
    csm_lib = csm_root / "lib"
    csm_lib.mkdir(parents=True)
    (csm_lib / "store.py").write_text("# stub store\n", encoding="utf-8")
    (csm_lib / "models.py").write_text("# stub models\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"ok": true, "data": []}',
            stderr="",
        )

    monkeypatch.setattr(integrations.subprocess, "run", fake_run)

    result = CSMIntegration(csm_root=csm_root).list_sessions(tool_filter="codex", limit=7)

    assert result.ok is True
    command = captured["cmd"]
    assert isinstance(command, list)
    assert command[0] == sys.executable
    assert command[1].endswith("csm_driver.py")
    assert "-c" not in command

    payload = json.loads(command[2])
    assert payload["root"] == str(csm_root)
    assert payload["action"] == "list_sessions"
    assert payload["tool_filter"] == "codex"
    assert payload["limit"] == 7
