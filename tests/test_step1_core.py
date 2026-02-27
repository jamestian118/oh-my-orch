from __future__ import annotations

import logging
import subprocess

import pytest

from lib import CLIAgent, MessageBus


def test_cli_agent_dry_run_for_both_modes() -> None:
    agent = CLIAgent("codex", binary="codex")

    non_interactive = agent.run_non_interactive(
        "hello world",
        extra_args=["--model", "gpt-5"],
        dry_run=True,
    )
    assert non_interactive.dry_run is True
    assert non_interactive.returncode == 0
    assert list(non_interactive.command) == ["codex", "exec", "hello world", "--model", "gpt-5"]
    assert non_interactive.mode == "non_interactive"

    interactive = agent.run_interactive(extra_args=["--profile", "harness"], dry_run=True)
    assert interactive.dry_run is True
    assert interactive.returncode == 0
    assert list(interactive.command) == ["codex", "--profile", "harness"]
    assert interactive.mode == "interactive"


def test_cli_agent_rejects_unknown_tool() -> None:
    with pytest.raises(ValueError):
        CLIAgent("unknown-tool")


def test_message_bus_jsonl_persistence_and_reset(tmp_path) -> None:
    session_file = tmp_path / ".omo" / "session.jsonl"

    first = {"role": "user", "content": "ping"}
    second = {"role": "assistant", "content": "pong"}

    bus_a = MessageBus(session_file)
    bus_a.add(first)
    assert session_file.exists()
    assert bus_a.history() == [first]

    bus_b = MessageBus(session_file)
    assert bus_b.load() == [first]

    bus_b.add(second)
    assert bus_b.history() == [first, second]

    bus_c = MessageBus(session_file)
    assert bus_c.load() == [first, second]

    bus_c.reset()
    assert bus_c.history() == []
    assert not session_file.exists()


def test_message_bus_load_invalid_jsonl_rebuilds_store(tmp_path, caplog) -> None:
    session_file = tmp_path / ".omo" / "session.jsonl"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("{invalid-json}\n", encoding="utf-8")

    bus = MessageBus(session_file)
    with caplog.at_level(logging.WARNING):
        loaded = bus.load()

    assert loaded == []
    assert bus.history() == []
    assert "clearing and rebuilding" in caplog.text
    assert session_file.read_text(encoding="utf-8") == ""


def test_cli_agent_timeout_converts_bytes_output(monkeypatch) -> None:
    agent = CLIAgent("claude", binary="claude")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["claude", "-p", "hello"],
            timeout=1,
            output=b"partial-bytes",
            stderr=b"stderr-bytes",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = agent.run_non_interactive("hello", timeout_sec=1)

    assert result.returncode == 124
    assert result.stdout == "partial-bytes"
    assert "timeout after 1s" in result.stderr


def test_cli_agent_retries_with_exponential_backoff(monkeypatch) -> None:
    agent = CLIAgent("codex", binary="codex")
    call_count = {"value": 0}
    sleep_calls: list[float] = []

    def fake_run(*args, **kwargs):
        _ = args, kwargs
        call_count["value"] += 1
        returncode = 1 if call_count["value"] < 3 else 0
        return subprocess.CompletedProcess(
            ["codex", "exec", "hello"],
            returncode=returncode,
            stdout="ok" if returncode == 0 else "",
            stderr="fail" if returncode != 0 else "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("lib.agents.time.sleep", sleep_calls.append)

    result = agent.run_non_interactive("hello")

    assert result.returncode == 0
    assert call_count["value"] == 3
    assert sleep_calls == [0.5, 1.0]


def test_cli_agent_debug_logs_full_subprocess_command(monkeypatch, caplog) -> None:
    agent = CLIAgent("codex", binary="codex")

    def fake_run(*args, **kwargs):
        _ = args, kwargs
        return subprocess.CompletedProcess(
            ["codex", "exec", "hello", "--model", "gpt-5"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with caplog.at_level(logging.DEBUG):
        result = agent.run_non_interactive("hello", extra_args=["--model", "gpt-5"], dry_run=False)

    assert result.returncode == 0
    assert "subprocess command: codex exec hello --model gpt-5" in caplog.text
