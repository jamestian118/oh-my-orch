"""Shared Protocol definitions for orchestrator modules."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Protocol


class CompressionResultProtocol(Protocol):
    summary: str


class ContextManagerProtocol(Protocol):
    def compress_context(
        self,
        text: str,
        *,
        target_agent: str,
        dry_run: bool,
    ) -> CompressionResultProtocol: ...


class PolicyCheckResultProtocol(Protocol):
    ok: bool
    error: str


class IntegrationsProtocol(Protocol):
    def policy_check(self, *, cwd: Path) -> PolicyCheckResultProtocol: ...


class StageResultProtocol(Protocol):
    stage: str
    ok: bool
    details: dict[str, Any]


class OrchestratorProtocol(Protocol):
    root: Path
    omo_dir: Path
    ai_dir: Path
    state_path: Path
    auto_confirm: bool
    max_review_loops: int
    context: ContextManagerProtocol
    integrations: IntegrationsProtocol

    def _resolve_mode(self, dry_run: bool | None) -> tuple[bool, str]: ...

    def load_state(self) -> dict[str, Any]: ...

    def save_state(self, state: dict[str, Any]) -> dict[str, Any]: ...

    def _artifact_abs(self, name: str, cwd: Path | None = None) -> Path: ...

    def _write_text(self, path: Path, content: str) -> None: ...

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None: ...

    def _history_text(self, limit: int = 80) -> str: ...

    def _fallback_exec_plan(self, task: str) -> str: ...

    def _run_subprocess(
        self,
        command: list[str],
        *,
        cwd: Path | str | None = None,
        capture_output: bool = True,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]: ...

    def _stage0_project_brief(
        self, task: str, *, run_dry: bool, cwd: Path
    ) -> StageResultProtocol: ...

    def _stage1_exec_plan(self, task: str, *, run_dry: bool, cwd: Path) -> StageResultProtocol: ...

    def _stage2_codex_execute(
        self,
        *,
        summary: str,
        run_dry: bool,
        cwd: Path,
    ) -> StageResultProtocol: ...

    def _stage3_gemini_review(self, *, run_dry: bool, cwd: Path) -> StageResultProtocol: ...

    def _stage4_codex_fix(self, *, run_dry: bool, cwd: Path) -> StageResultProtocol: ...

    def _stage5_final_review(self, *, run_dry: bool, cwd: Path) -> StageResultProtocol: ...

    def _create_worktree(self, task: str, run_dry: bool) -> tuple[Path, str]: ...

    def _merge_worktree_branch(self, branch: str) -> tuple[bool, str]: ...

    def _remove_worktree(self, *, path: Path, branch: str, force: bool = False) -> None: ...

    def _resolve_path(self, path: Path) -> Path: ...

    def _is_managed_worktree_path(self, path: Path) -> bool: ...

    def _is_managed_worktree_branch(self, branch: str) -> bool: ...

    def pipeline(
        self,
        *,
        task: str,
        dry_run: bool | None = None,
        stop_after: int | None = None,
        resume: bool = False,
    ) -> dict[str, Any]: ...
