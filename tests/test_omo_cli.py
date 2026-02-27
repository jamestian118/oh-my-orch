"""CLI parsing tests for omo entrypoint."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import omo


@dataclass
class _StubOrchestrator:
    cwd: str
    dry_run: bool
    no_auto_confirm: bool
    verbose: bool = False
    debug: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    def chat(self, *, agent: str, prompt: str, dry_run: bool | None = None) -> dict[str, Any]:
        self.calls.append(
            {
                "command": "chat",
                "agent": agent,
                "prompt": prompt,
                "dry_run": dry_run,
            }
        )
        return {
            "ok": True,
            "command": "chat",
            "agent": agent,
            "reply": "stub-reply",
        }

    def pipeline(
        self,
        *,
        task: str,
        dry_run: bool | None = None,
        stop_after: int | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "command": "pipeline",
                "task": task,
                "dry_run": dry_run,
                "stop_after": stop_after,
                "resume": resume,
            }
        )
        return {
            "ok": True,
            "command": "pipeline",
            "mode": "dry-run" if dry_run else "live",
            "stopped_after": stop_after,
        }

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        self.calls.append({"command": "history", "limit": limit})
        return [{"idx": 1, "limit": limit}]

    def compress(
        self,
        *,
        target_agent: str = "codex",
        max_chars: int = 5000,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "command": "compress",
                "target_agent": target_agent,
                "max_chars": max_chars,
                "dry_run": dry_run,
            }
        )
        return {
            "ok": True,
            "command": "compress",
            "target_agent": target_agent,
            "summary": "stub-summary",
        }


def _install_stub_orchestrator(monkeypatch) -> list[_StubOrchestrator]:
    instances: list[_StubOrchestrator] = []

    def _factory(
        cwd: str,
        dry_run: bool,
        no_auto_confirm: bool,
        verbose: bool = False,
        debug: bool = False,
    ) -> _StubOrchestrator:
        stub = _StubOrchestrator(
            cwd=cwd,
            dry_run=dry_run,
            no_auto_confirm=no_auto_confirm,
            verbose=verbose,
            debug=debug,
        )
        instances.append(stub)
        return stub

    monkeypatch.setattr(omo, "_make_orchestrator", _factory)
    return instances


def test_at_agent_missing_prompt_returns_clear_error(capsys) -> None:
    exit_code = omo.main(["@codex", "chat", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "`@codex` 缺少 prompt" in captured.err
    assert "omo chat codex" in captured.err


def test_at_agent_cwd_missing_value_returns_clear_error(capsys) -> None:
    exit_code = omo.main(["@codex", "chat", "修复登录逻辑", "--cwd"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "`--cwd` 缺少路径参数" in captured.err


def test_parser_help_contains_description_and_examples() -> None:
    parser = omo._build_parser()
    help_text = parser.format_help()

    assert "Orchestrate Claude Code, Codex CLI, and Gemini CLI tasks." in help_text
    assert "Examples:" in help_text
    assert "omo chat codex 修复登录 bug --cwd /path/to/repo" in help_text
    assert "omo pipeline 实现 OMO Phase 6 --dry-run --output text" in help_text


def test_pipeline_stop_after_forwarded_to_orchestrator(monkeypatch, capsys) -> None:
    instances = _install_stub_orchestrator(monkeypatch)

    exit_code = omo.main(
        ["pipeline", "优化", "CI", "--cwd", "/tmp/repo", "--dry-run", "--stop-after", "2"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["command"] == "pipeline"
    assert payload["stopped_after"] == 2

    assert len(instances) == 1
    stub = instances[0]
    assert stub.cwd == "/tmp/repo"
    assert stub.dry_run is True
    assert stub.calls == [
        {
            "command": "pipeline",
            "task": "优化 CI",
            "dry_run": True,
            "stop_after": 2,
            "resume": False,
        }
    ]


def test_history_and_compress_flags_forwarded(monkeypatch, capsys) -> None:
    instances = _install_stub_orchestrator(monkeypatch)

    history_code = omo.main(["history", "--cwd", "/tmp/repo", "--limit", "7"])
    history_out = capsys.readouterr()
    history_payload = json.loads(history_out.out)

    assert history_code == 0
    assert history_payload["ok"] is True
    assert history_payload["command"] == "history"
    assert history_payload["history"] == [{"idx": 1, "limit": 7}]

    compress_code = omo.main(
        [
            "compress",
            "--cwd",
            "/tmp/repo",
            "--dry-run",
            "--target-agent",
            "gemini",
            "--max-chars",
            "128",
        ]
    )
    compress_out = capsys.readouterr()
    compress_payload = json.loads(compress_out.out)

    assert compress_code == 0
    assert compress_payload["ok"] is True
    assert compress_payload["command"] == "compress"
    assert compress_payload["target_agent"] == "gemini"

    assert len(instances) == 2
    history_stub = instances[0]
    compress_stub = instances[1]
    assert history_stub.calls == [{"command": "history", "limit": 7}]
    assert compress_stub.calls == [
        {
            "command": "compress",
            "target_agent": "gemini",
            "max_chars": 128,
            "dry_run": True,
        }
    ]


def test_main_prefers_payload_exit_code(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        omo,
        "_dispatch",
        lambda _ns: {"ok": True, "command": "status", "exit_code": 42},
    )

    exit_code = omo.main(["status"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 42
    assert payload["ok"] is True
    assert payload["exit_code"] == 42


def test_text_output_mode_renders_human_readable_table(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        omo,
        "_dispatch",
        lambda _ns: {
            "ok": True,
            "command": "status",
            "meta": {"stage": 6, "items": ["6.1", "6.2", "6.3"]},
        },
    )

    exit_code = omo.main(["status", "--output", "text"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Field" in captured.out
    assert "Value" in captured.out
    assert "command" in captured.out
    assert "status" in captured.out
    assert '"stage": 6' in captured.out


def test_at_agent_supports_output_text(monkeypatch, capsys) -> None:
    instances = _install_stub_orchestrator(monkeypatch)

    exit_code = omo.main(["@codex", "chat", "总结今天进度", "--dry-run", "--output", "text"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Field" in captured.out
    assert "chat" in captured.out

    assert len(instances) == 1
    stub = instances[0]
    assert stub.calls == [
        {
            "command": "chat",
            "agent": "codex",
            "prompt": "总结今天进度",
            "dry_run": True,
        }
    ]


def test_version_flag_prints_version_and_exits(monkeypatch, capsys) -> None:
    monkeypatch.setattr(omo, "_resolve_cli_version", lambda: "9.9.9")

    exit_code = omo.main(["--version"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == "omo 9.9.9"
    assert captured.err == ""


def test_global_verbose_and_debug_flags_forwarded(monkeypatch, capsys) -> None:
    instances = _install_stub_orchestrator(monkeypatch)

    exit_code = omo.main(
        [
            "-v",
            "--debug",
            "pipeline",
            "优化",
            "日志",
            "--cwd",
            "/tmp/repo",
            "--dry-run",
            "--stop-after",
            "1",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["command"] == "pipeline"

    assert len(instances) == 1
    stub = instances[0]
    assert stub.cwd == "/tmp/repo"
    assert stub.verbose is True
    assert stub.debug is True
    assert stub.calls == [
        {
            "command": "pipeline",
            "task": "优化 日志",
            "dry_run": True,
            "stop_after": 1,
            "resume": False,
        }
    ]
