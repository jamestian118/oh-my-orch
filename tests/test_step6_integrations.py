from __future__ import annotations

import importlib
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


def _mcp_frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def test_csm_integration_uses_mcp_stdio_by_default(tmp_path, monkeypatch) -> None:
    csm_root = tmp_path / "csm"
    csm_lib = csm_root / "lib"
    csm_lib.mkdir(parents=True)
    (csm_lib / "store.py").write_text("# stub store\n", encoding="utf-8")
    (csm_lib / "models.py").write_text("# stub models\n", encoding="utf-8")
    (csm_root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (csm_root / "csm.py").write_text("# stub csm entrypoint\n", encoding="utf-8")

    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, cmd: list[str], **_: object) -> None:
            captured["cmd"] = cmd
            self.returncode = 0

        def communicate(
            self,
            input: bytes | None = None,  # noqa: A002
            timeout: float | None = None,
        ) -> tuple[bytes, bytes]:
            captured["stdin"] = input or b""
            captured["timeout"] = timeout
            response = _mcp_frame(
                {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}
            ) + _mcp_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "structuredContent": [
                            {"session_id": "sid-1", "tool_slug": "codex"},
                        ]
                    },
                }
            )
            return response, b""

    def fail_driver(_: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("driver fallback should not be used when MCP succeeds")

    monkeypatch.setattr(integrations.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(integrations.subprocess, "run", fail_driver)

    result = CSMIntegration(csm_root=csm_root).list_sessions(tool_filter="codex", limit=7)
    assert result.ok is True
    assert isinstance(result.data, list)
    assert result.data[0]["session_id"] == "sid-1"

    command = captured["cmd"]
    assert isinstance(command, list)
    assert command[:2] == [sys.executable, str(csm_root / "csm.py")]
    assert command[2] == "mcp"

    raw_stdin = captured["stdin"]
    assert isinstance(raw_stdin, bytes)
    decoded = raw_stdin.decode("utf-8", errors="replace")
    assert '"method": "initialize"' in decoded
    assert '"method": "tools/call"' in decoded
    assert '"name": "list_sessions"' in decoded


def test_csm_integration_falls_back_to_driver_when_mcp_unavailable(tmp_path, monkeypatch) -> None:
    csm_root = tmp_path / "csm"
    csm_lib = csm_root / "lib"
    csm_lib.mkdir(parents=True)
    (csm_lib / "store.py").write_text("# stub store\n", encoding="utf-8")
    (csm_lib / "models.py").write_text("# stub models\n", encoding="utf-8")
    (csm_root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (csm_root / "csm.py").write_text("# stub csm entrypoint\n", encoding="utf-8")

    captured: dict[str, object] = {}

    class FailingPopen:
        def __init__(self, cmd: list[str], **_: object) -> None:
            captured["mcp_cmd"] = cmd
            self.returncode = 1

        def communicate(
            self,
            input: bytes | None = None,  # noqa: A002
            timeout: float | None = None,
        ) -> tuple[bytes, bytes]:
            captured["mcp_stdin"] = input or b""
            return b"", "启动 MCP Server 失败: No module named 'mcp'".encode("utf-8")

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured["driver_cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"ok": true, "data": [{"session_id": "sid-driver"}]}',
            stderr="",
        )

    monkeypatch.setattr(integrations.subprocess, "Popen", FailingPopen)
    monkeypatch.setattr(integrations.subprocess, "run", fake_run)

    result = CSMIntegration(csm_root=csm_root).list_sessions(tool_filter="codex", limit=3)

    assert result.ok is True
    assert isinstance(result.data, list)
    assert result.data[0]["session_id"] == "sid-driver"

    driver_cmd = captured["driver_cmd"]
    assert isinstance(driver_cmd, list)
    assert driver_cmd[1].endswith("csm_driver.py")


def test_csm_integration_mcp_mode_reports_version_incompatibility(tmp_path) -> None:
    csm_root = tmp_path / "csm"
    csm_lib = csm_root / "lib"
    csm_lib.mkdir(parents=True)
    (csm_lib / "store.py").write_text("# stub store\n", encoding="utf-8")
    (csm_lib / "models.py").write_text("# stub models\n", encoding="utf-8")
    (csm_root / "VERSION").write_text("0.0.1\n", encoding="utf-8")
    (csm_root / "csm.py").write_text("# stub csm entrypoint\n", encoding="utf-8")

    client = CSMIntegration(csm_root=csm_root, transport="mcp", min_version="0.1.0")
    result = client.list_sessions(tool_filter="codex", limit=2)

    assert result.ok is False
    assert "requires >= 0.1.0" in result.error
    assert "OMO_CSM_TRANSPORT=driver" in result.error


def test_omo_code_root_overrides_default_paths(monkeypatch) -> None:
    monkeypatch.setenv("OMO_CODE_ROOT", "/tmp/omo-custom-root")
    monkeypatch.delenv("OMO_CSM_ROOT", raising=False)
    monkeypatch.delenv("OMO_UHK_ROOT", raising=False)
    monkeypatch.delenv("OMO_HANDOFF_ROOT", raising=False)

    importlib.reload(integrations)
    try:
        assert str(integrations.CSM_ROOT) == "/tmp/omo-custom-root/claude-session-manager"
        assert str(integrations.UHK_ROOT) == "/tmp/omo-custom-root/universal-harness-kit"
        assert str(integrations.HANDOFF_ROOT) == "/tmp/omo-custom-root/cli-handoff-bundle/_handoff"
    finally:
        importlib.reload(integrations)
