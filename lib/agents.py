"""CLI Agent wrappers for claude/codex/gemini."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

SUPPORTED_AGENT_TOOLS = ("claude", "codex", "gemini")

_NON_INTERACTIVE_PREFIX = {
    "claude": ("-p",),
    "codex": ("exec",),
    "gemini": ("-p",),
}


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """统一返回结构，便于记录执行结果和 dry-run 产物。"""

    tool: str
    mode: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    dry_run: bool
    cwd: str | None


class CLIAgent:
    """CLI Agent 封装。

    提供 interactive 与 non-interactive 两种调用方式，支持 dry-run。
    """

    def __init__(
        self,
        tool: str,
        *,
        binary: str | None = None,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        normalized_tool = tool.strip().lower()
        if normalized_tool not in SUPPORTED_AGENT_TOOLS:
            raise ValueError(f"Unsupported tool: {tool!r}")

        self.tool = normalized_tool
        self.binary = binary or normalized_tool
        self.cwd = str(Path(cwd).expanduser()) if cwd is not None else None
        self.env = self._build_env(env)

    @staticmethod
    def _build_env(extra_env: Mapping[str, str] | None) -> Mapping[str, str] | None:
        if extra_env is None:
            return None
        merged = os.environ.copy()
        merged.update({str(key): str(value) for key, value in extra_env.items()})
        return merged

    def build_interactive_command(
        self,
        *,
        prompt: str | None = None,
        extra_args: Sequence[str] | None = None,
    ) -> list[str]:
        command = [self.binary]
        if prompt:
            command.append(prompt)
        if extra_args:
            command.extend(str(arg) for arg in extra_args)
        return command

    def build_non_interactive_command(
        self,
        prompt: str,
        extra_args: Sequence[str] | None = None,
    ) -> list[str]:
        command = [self.binary, *_NON_INTERACTIVE_PREFIX[self.tool], prompt]
        if extra_args:
            command.extend(str(arg) for arg in extra_args)
        return command

    def run_interactive(
        self,
        *,
        prompt: str | None = None,
        extra_args: Sequence[str] | None = None,
        dry_run: bool = False,
        timeout_sec: float | None = None,
    ) -> AgentRunResult:
        command = self.build_interactive_command(prompt=prompt, extra_args=extra_args)
        return self._run(
            mode="interactive",
            command=command,
            dry_run=dry_run,
            capture_output=False,
            timeout_sec=timeout_sec,
        )

    def run_non_interactive(
        self,
        prompt: str,
        *,
        extra_args: Sequence[str] | None = None,
        dry_run: bool = False,
        timeout_sec: float | None = None,
    ) -> AgentRunResult:
        command = self.build_non_interactive_command(prompt=prompt, extra_args=extra_args)
        return self._run(
            mode="non_interactive",
            command=command,
            dry_run=dry_run,
            capture_output=True,
            timeout_sec=timeout_sec,
        )

    def _run(
        self,
        *,
        mode: str,
        command: list[str],
        dry_run: bool,
        capture_output: bool,
        timeout_sec: float | None,
    ) -> AgentRunResult:
        if dry_run:
            return AgentRunResult(
                tool=self.tool,
                mode=mode,
                command=tuple(command),
                returncode=0,
                stdout="",
                stderr="",
                dry_run=True,
                cwd=self.cwd,
            )

        try:
            completed = subprocess.run(
                command,
                cwd=self.cwd,
                env=self.env,
                text=True,
                capture_output=capture_output,
                check=False,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            timeout_stdout = exc.stdout or ""
            timeout_stderr = exc.stderr or ""
            if isinstance(timeout_stdout, bytes):
                timeout_stdout = timeout_stdout.decode("utf-8", errors="replace")
            if isinstance(timeout_stderr, bytes):
                timeout_stderr = timeout_stderr.decode("utf-8", errors="replace")
            return AgentRunResult(
                tool=self.tool,
                mode=mode,
                command=tuple(command),
                returncode=124,
                stdout=timeout_stdout,
                stderr=f"timeout after {timeout_sec}s; {timeout_stderr}".strip(),
                dry_run=False,
                cwd=self.cwd,
            )
        return AgentRunResult(
            tool=self.tool,
            mode=mode,
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            dry_run=False,
            cwd=self.cwd,
        )
