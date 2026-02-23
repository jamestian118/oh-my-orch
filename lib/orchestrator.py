"""oh-my-orch orchestrator.

中文说明：
- Step 3: chat 模式最小可用
- Step 4: pipeline 状态机 + worktree 隔离 + review 循环
- Step 5: team 模式并行思考（单终端顺序执行）
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents import AgentRunResult, CLIAgent
from .bus import MessageBus
from .context import ContextManager
from .integrations import IntegrationHub, build_integrations

PIPELINE_STAGES = [
    "stage0_project_brief",
    "stage1_exec_plan",
    "stage2_codex_execute",
    "stage3_gemini_review",
    "stage4_codex_fix",
    "stage5_final_review",
]

ARTIFACT_PATHS = {
    "project_brief": Path(".ai/project-brief.md"),
    "exec_plan": Path(".ai/exec-plan.md"),
    "review": Path(".ai/review.md"),
}

TEAM_AGENTS = ("claude", "codex", "gemini")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(text: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return clean or "task"


def _normalize_agent(agent: str) -> str:
    value = agent.lower().strip()
    if value.startswith("@"):
        value = value[1:]
    if value not in {"claude", "codex", "gemini"}:
        raise ValueError(f"unsupported agent: {agent}")
    return value


@dataclass(slots=True)
class StageResult:
    stage: str
    ok: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Orchestrator:
    root_dir: str | Path = "."
    dry_run: bool = False
    integrations: IntegrationHub | None = None
    max_review_loops: int = 2
    auto_confirm: bool = True
    root: Path = field(init=False)
    omo_dir: Path = field(init=False)
    ai_dir: Path = field(init=False)
    state_path: Path = field(init=False)
    chat_history_path: Path = field(init=False)
    bus: MessageBus = field(init=False)
    context: ContextManager = field(init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root_dir).resolve()
        self.omo_dir = self.root / ".omo"
        self.ai_dir = self.root / ".ai"
        self.state_path = self.omo_dir / "pipeline-state.json"
        self.chat_history_path = self.omo_dir / "chat-history.jsonl"

        self.omo_dir.mkdir(parents=True, exist_ok=True)
        self.ai_dir.mkdir(parents=True, exist_ok=True)

        self.bus = MessageBus(self.omo_dir / "session.jsonl")
        self.bus.load()
        self.context = ContextManager()

        if self.integrations is None:
            self.integrations = build_integrations(self.root, dry_run=self.dry_run, mode="auto")

    # ---------------------------------------------------------------------
    # State
    # ---------------------------------------------------------------------
    def _default_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": _utc_now(),
            "last_action": None,
            "chat": {
                "count": len(self.bus.history()),
                "last_agent": "",
                "last_prompt": "",
                "last_mode": "",
            },
            "pipeline": {
                "task": "",
                "status": "idle",  # idle/in_progress/blocked/completed/failed
                "current_stage": "",
                "completed_stages": [],
                "retry_count": 0,
                "worktree_path": "",
                "worktree_branch": "",
                "started_at": "",
                "finished_at": "",
                "artifacts": {name: str(path) for name, path in ARTIFACT_PATHS.items()},
                "last_error": "",
            },
            "team": {
                "topic": "",
                "ran_at": "",
                "last_mode": "",
                "outputs": [],
            },
        }

    def load_state(self) -> dict[str, Any]:
        state = self._default_state()
        if self.state_path.exists():
            try:
                raw = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    state.update(
                        {k: v for k, v in raw.items() if k in state and not isinstance(v, dict)}
                    )
                    for scope in ("chat", "pipeline", "team"):
                        if isinstance(raw.get(scope), dict):
                            state[scope].update(raw[scope])
            except json.JSONDecodeError:
                pass
        state["chat"]["count"] = len(self.bus.history())
        return state

    def save_state(self, state: dict[str, Any]) -> dict[str, Any]:
        state["updated_at"] = _utc_now()
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return state

    # ---------------------------------------------------------------------
    # Bus / history helpers
    # ---------------------------------------------------------------------
    def _append_chat_history(self, payload: dict[str, Any]) -> None:
        self.chat_history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.chat_history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _push_message(
        self,
        *,
        role: str,
        content: str,
        agent: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ts": _utc_now(),
            "role": role,
            "agent": agent,
            "content": content,
            "metadata": metadata or {},
        }
        message = self.bus.add(payload)
        self._append_chat_history(message)
        return message

    def _history_text(self, limit: int = 80) -> str:
        rows = self.bus.history()
        if limit > 0:
            rows = rows[-limit:]
        lines: list[str] = []
        for row in rows:
            role = row.get("role", "unknown")
            agent = row.get("agent", "")
            tag = f"{role}:{agent}" if agent else role
            lines.append(f"[{tag}] {row.get('content', '')}")
        return "\n".join(lines).strip()

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.bus.history()
        if limit <= 0:
            return rows
        return rows[-limit:]

    # ---------------------------------------------------------------------
    # Generic helpers
    # ---------------------------------------------------------------------
    def _resolve_mode(self, dry_run: bool | None) -> tuple[bool, str]:
        run_dry = self.dry_run if dry_run is None else dry_run
        return run_dry, "dry-run" if run_dry else "live"

    def _resolve_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path.resolve(strict=False)
        return (self.root / path).resolve(strict=False)

    def _is_managed_worktree_path(self, path: Path) -> bool:
        resolved = self._resolve_path(path)
        managed_root = self.omo_dir.resolve(strict=False)
        if resolved in {self.root.resolve(strict=False), managed_root}:
            return False
        try:
            resolved.relative_to(managed_root)
            return True
        except ValueError:
            return False

    def _is_managed_worktree_branch(self, branch: str) -> bool:
        return bool(branch) and branch.startswith("omo-sandbox-")

    def _artifact_abs(self, name: str, cwd: Path | None = None) -> Path:
        base = cwd or self.root
        return base / ARTIFACT_PATHS[name]

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")

    def _fallback_project_brief(self, task: str) -> str:
        return (
            "# Project Brief\n\n"
            f"- task: {task}\n"
            "- note: generated by fallback\n"
            "- source: orchestrator\n"
        )

    def _fallback_exec_plan(self, task: str) -> str:
        return (
            "# Execution Plan / 实施方案\n\n"
            "## Goal / 目标\n"
            f"{task}\n\n"
            "## Tasks / 任务拆解\n"
            "### Task 1: Implement baseline orchestration\n"
            "- Files: `omo.py`, `lib/orchestrator.py`\n"
            "- Change: add command routing and stage machine\n"
            "- Depends on: Step 1/2 core modules\n"
            "- Parallel: yes\n\n"
            "## Interfaces / 关键接口定义\n"
            "- `Orchestrator.pipeline(task, dry_run)`\n"
            "- `Orchestrator.team(topic, dry_run)`\n\n"
            "## Constraints / 约束条件\n"
            "- 真实信息通过 `.ai/*` 产物传递\n"
            "- dry-run 不依赖外部 CLI\n\n"
            "## Verification / 验收命令\n"
            "- `./scripts/verify`\n"
        )

    def _fallback_review(self) -> str:
        return (
            "# Code Review Results\n\n"
            "## Blocking Issues (必须修复)\n"
            "- 无（fallback）\n\n"
            "## Non-blocking Issues (建议修复)\n"
            "- 建议补充真实 CLI 集成 smoke。\n"
        )

    def _extract_session_id(self, text: str) -> str:
        match = re.search(r'"session_id"\s*:\s*"([^"]+)"', text)
        return match.group(1) if match else ""

    def _run_agent(
        self,
        *,
        agent: str,
        prompt: str,
        cwd: Path,
        interactive: bool,
        run_dry: bool,
        extra_args: list[str] | None = None,
        timeout_sec: float | None = None,
    ) -> AgentRunResult:
        cli = CLIAgent(agent, cwd=cwd)
        if interactive:
            return cli.run_interactive(
                prompt=prompt,
                extra_args=extra_args,
                dry_run=run_dry,
                timeout_sec=timeout_sec,
            )
        return cli.run_non_interactive(
            prompt,
            extra_args=extra_args,
            dry_run=run_dry,
            timeout_sec=timeout_sec,
        )

    # ---------------------------------------------------------------------
    # Worktree
    # ---------------------------------------------------------------------
    def _create_worktree(self, task: str, run_dry: bool) -> tuple[Path, str]:
        sandbox = self.omo_dir / "sandbox"
        branch = (
            f"omo-sandbox-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{_slug(task)[:16]}"
        )

        if run_dry:
            sandbox.mkdir(parents=True, exist_ok=True)
            return sandbox, branch

        if sandbox.exists():
            self._remove_worktree(path=sandbox, branch="", force=True)

        proc = subprocess.run(
            ["git", "-C", str(self.root), "worktree", "add", str(sandbox), "-b", branch],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {proc.stderr.strip()}")
        return sandbox, branch

    def _remove_worktree(self, *, path: Path, branch: str, force: bool = False) -> None:
        managed_path = self._resolve_path(path)
        if not self._is_managed_worktree_path(managed_path):
            return

        if managed_path.exists():
            cmd = ["git", "-C", str(self.root), "worktree", "remove", str(managed_path)]
            if force:
                cmd.append("--force")
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0 and force:
                shutil.rmtree(managed_path, ignore_errors=True)
        if self._is_managed_worktree_branch(branch):
            subprocess.run(
                ["git", "-C", str(self.root), "branch", "-D", branch],
                capture_output=True,
                text=True,
                check=False,
            )

    def _merge_worktree_branch(self, branch: str) -> tuple[bool, str]:
        proc = subprocess.run(
            ["git", "-C", str(self.root), "merge", "--ff-only", branch],
            capture_output=True,
            text=True,
            check=False,
        )
        ok = proc.returncode == 0
        return ok, (proc.stdout + proc.stderr).strip()

    # ---------------------------------------------------------------------
    # Stage implementations
    # ---------------------------------------------------------------------
    def _stage0_project_brief(self, task: str, *, run_dry: bool, cwd: Path) -> StageResult:
        path = self._artifact_abs("project_brief", cwd=cwd)
        prompt = (
            "请分析当前项目并输出项目简报，写出项目结构、技术栈、与任务相关的关键文件。\n"
            f"任务：{task}\n"
            "输出使用 Markdown。"
        )
        if run_dry:
            dry_content = self._fallback_project_brief(task) + "\n- mode: DRY-RUN\n"
            self._write_text(path, dry_content)
            return StageResult("stage0_project_brief", True, {"path": str(path), "mode": "dry-run"})

        result = self._run_agent(
            agent="gemini",
            prompt=prompt,
            cwd=cwd,
            interactive=False,
            run_dry=False,
            timeout_sec=60,
        )
        content = result.stdout.strip() or self._fallback_project_brief(task)
        self._write_text(path, content)
        return StageResult(
            "stage0_project_brief",
            result.returncode == 0,
            {"path": str(path), "returncode": result.returncode},
        )

    def _stage1_exec_plan(self, task: str, *, run_dry: bool, cwd: Path) -> StageResult:
        path = self._artifact_abs("exec_plan", cwd=cwd)
        prompt = (
            "读取 .ai/project-brief.md，启用 agent team 并行探索方案。\n"
            "讨论后将最终方案写入 .ai/exec-plan.md，格式遵循 Execution Plan 模板。\n"
            f"任务：{task}"
        )

        if run_dry:
            dry_content = self._fallback_exec_plan(task) + "\n<!-- mode: DRY-RUN -->\n"
            self._write_text(path, dry_content)
            return StageResult("stage1_exec_plan", True, {"path": str(path), "mode": "dry-run"})

        # 先用 -p 创建上下文，尝试提取 session_id，再进入 resume 交互。
        init_result = self._run_agent(
            agent="claude",
            prompt=prompt,
            cwd=cwd,
            interactive=False,
            run_dry=False,
            extra_args=["--output-format", "json"],
            timeout_sec=60,
        )
        session_id = self._extract_session_id(init_result.stdout)
        resume_code = 0
        resumed = False
        resume_skipped = ""
        if session_id and sys.stdin.isatty():
            resume = self._run_agent(
                agent="claude",
                prompt="",
                cwd=cwd,
                interactive=True,
                run_dry=False,
                extra_args=["--resume", session_id],
            )
            resume_code = resume.returncode
            resumed = True
        elif session_id:
            resume_skipped = "non-interactive shell, skipped claude --resume"
        if not path.exists():
            content = init_result.stdout.strip() or self._fallback_exec_plan(task)
            self._write_text(path, content)

        ok = init_result.returncode == 0 and resume_code == 0
        return StageResult(
            "stage1_exec_plan",
            ok,
            {
                "path": str(path),
                "session_id": session_id,
                "returncode": init_result.returncode,
                "resumed": resumed,
                "resume_skipped_reason": resume_skipped,
            },
        )

    def _stage2_codex_execute(
        self,
        *,
        summary: str,
        run_dry: bool,
        cwd: Path,
    ) -> StageResult:
        prompt = (
            f"{summary}\n\n"
            "完整方案在 .ai/exec-plan.md，严格按此执行。"
            " 启用多 agent 子代理并行实现。"
        )
        result = self._run_agent(
            agent="codex",
            prompt=prompt,
            cwd=cwd,
            interactive=True,
            run_dry=run_dry,
        )
        return StageResult(
            "stage2_codex_execute",
            result.returncode == 0,
            {"cwd": str(cwd), "returncode": result.returncode},
        )

    def _stage3_gemini_review(self, *, run_dry: bool, cwd: Path) -> StageResult:
        path = self._artifact_abs("review", cwd=cwd)
        prompt = (
            "读取 .ai/exec-plan.md 了解方案意图。"
            " 使用 conductor 扩展 review 当前项目，结果写入 .ai/review.md。"
        )
        if run_dry:
            dry_content = self._fallback_review() + "\n<!-- mode: DRY-RUN -->\n"
            self._write_text(path, dry_content)
            return StageResult("stage3_gemini_review", True, {"path": str(path), "mode": "dry-run"})

        result = self._run_agent(
            agent="gemini",
            prompt=prompt,
            cwd=cwd,
            interactive=True,
            run_dry=False,
        )
        if not path.exists():
            self._write_text(path, result.stdout.strip() or self._fallback_review())
        return StageResult(
            "stage3_gemini_review",
            result.returncode == 0,
            {"path": str(path), "returncode": result.returncode},
        )

    def _stage4_codex_fix(self, *, run_dry: bool, cwd: Path) -> StageResult:
        prompt = "读取 .ai/review.md，启用多 agent 子代理并行修复所有 blocking issues。"
        result = self._run_agent(
            agent="codex",
            prompt=prompt,
            cwd=cwd,
            interactive=True,
            run_dry=run_dry,
        )
        return StageResult(
            "stage4_codex_fix",
            result.returncode == 0,
            {"cwd": str(cwd), "returncode": result.returncode},
        )

    def _stage5_final_review(self, *, run_dry: bool, cwd: Path) -> StageResult:
        if run_dry:
            return StageResult("stage5_final_review", True, {"mode": "dry-run"})

        verify_result = self.integrations.verify_project(cwd=cwd)
        prompt = (
            "请对照 .ai/exec-plan.md + .ai/review.md + git diff 做最终审查。"
            " 若通过请输出 PASS，否则输出 FAIL 与问题清单。"
        )
        review_result = self._run_agent(
            agent="claude",
            prompt=prompt,
            cwd=cwd,
            interactive=False,
            run_dry=False,
        )
        pass_text = review_result.stdout.upper()
        passed = verify_result.ok and review_result.returncode == 0 and "FAIL" not in pass_text
        return StageResult(
            "stage5_final_review",
            passed,
            {
                "verify_ok": verify_result.ok,
                "verify_exit_code": verify_result.exit_code,
                "review_returncode": review_result.returncode,
            },
        )

    # ---------------------------------------------------------------------
    # Public commands
    # ---------------------------------------------------------------------
    def chat(self, *, agent: str, prompt: str, dry_run: bool | None = None) -> dict[str, Any]:
        target = _normalize_agent(agent)
        run_dry, mode = self._resolve_mode(dry_run)

        self._push_message(role="user", content=prompt, agent=target, metadata={"mode": mode})

        context_text = self._history_text(limit=80)
        compressed = self.context.compress_context(
            context_text, target_agent=target, dry_run=run_dry
        )
        final_prompt = prompt
        if compressed.used_fallback or compressed.compressed:
            final_prompt = "以下是上下文摘要：\n" f"{compressed.summary}\n\n" f"当前请求：{prompt}"

        result = self._run_agent(
            agent=target,
            prompt=final_prompt,
            cwd=self.root,
            interactive=not run_dry,
            run_dry=run_dry,
        )
        assistant_message = (
            f"{target} run finished (returncode={result.returncode}, dry_run={result.dry_run})"
        )
        self._push_message(
            role="assistant",
            content=assistant_message,
            agent=target,
            metadata={"returncode": result.returncode, "mode": mode},
        )

        state = self.load_state()
        state["last_action"] = "chat"
        state["chat"]["last_agent"] = target
        state["chat"]["last_prompt"] = prompt
        state["chat"]["last_mode"] = mode
        state["chat"]["count"] = len(self.bus.history())
        self.save_state(state)
        return {
            "ok": result.returncode == 0,
            "command": "chat",
            "agent": target,
            "mode": mode,
            "dry_run": run_dry,
            "returncode": result.returncode,
            "compressed": compressed.compressed,
            "fallback_used": compressed.used_fallback,
        }

    def pipeline(
        self,
        *,
        task: str,
        dry_run: bool | None = None,
        stop_after: int | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        run_dry, mode = self._resolve_mode(dry_run)
        task = task.strip()
        if not task:
            raise ValueError("pipeline task 不能为空")

        state = self.load_state()
        if not resume:
            state["pipeline"].update(
                {
                    "task": task,
                    "status": "in_progress",
                    "current_stage": PIPELINE_STAGES[0],
                    "completed_stages": [],
                    "retry_count": 0,
                    "worktree_path": "",
                    "worktree_branch": "",
                    "started_at": _utc_now(),
                    "finished_at": "",
                    "last_error": "",
                }
            )
        state["last_action"] = "pipeline"
        self.save_state(state)

        if not run_dry:
            preflight = self.integrations.policy_check(cwd=self.root)
            if not preflight.ok:
                state["pipeline"]["status"] = "blocked"
                state["pipeline"]["last_error"] = preflight.error or "policy check failed"
                self.save_state(state)
                return {
                    "ok": False,
                    "command": "pipeline",
                    "mode": mode,
                    "error": state["pipeline"]["last_error"],
                }

        start_index = 0
        if resume and state["pipeline"]["current_stage"] in PIPELINE_STAGES:
            start_index = PIPELINE_STAGES.index(state["pipeline"]["current_stage"])

        worktree_path = Path(state["pipeline"].get("worktree_path", "") or self.root)
        worktree_branch = state["pipeline"].get("worktree_branch", "")
        stage_results: list[dict[str, Any]] = []

        try:
            for index, stage in enumerate(PIPELINE_STAGES[start_index:], start=start_index):
                state["pipeline"]["current_stage"] = stage
                self.save_state(state)

                if stage == "stage0_project_brief":
                    result = self._stage0_project_brief(task, run_dry=run_dry, cwd=self.root)
                elif stage == "stage1_exec_plan":
                    result = self._stage1_exec_plan(task, run_dry=run_dry, cwd=self.root)
                    exec_plan = self._artifact_abs("exec_plan", cwd=self.root)
                    if not exec_plan.exists():
                        self._write_text(exec_plan, self._fallback_exec_plan(task))
                    if not self.auto_confirm and sys.stdin.isatty() and not run_dry:
                        answer = input("执行方案已生成，继续执行？[Y/n] ").strip().lower()
                        if answer in {"n", "no"}:
                            state["pipeline"]["status"] = "blocked"
                            state["pipeline"]["last_error"] = (
                                "user aborted after exec-plan confirmation"
                            )
                            self.save_state(state)
                            return {
                                "ok": False,
                                "command": "pipeline",
                                "mode": mode,
                                "stage_results": stage_results,
                                "error": state["pipeline"]["last_error"],
                            }

                    history_text = self._history_text(limit=120)
                    compact = self.context.compress_context(
                        history_text or task,
                        target_agent="codex",
                        dry_run=run_dry,
                    )
                    state["pipeline"]["codex_handoff"] = compact.summary
                elif stage == "stage2_codex_execute":
                    if not worktree_branch:
                        worktree_path, worktree_branch = self._create_worktree(
                            task, run_dry=run_dry
                        )
                        state["pipeline"]["worktree_path"] = str(worktree_path)
                        state["pipeline"]["worktree_branch"] = worktree_branch
                    summary = state["pipeline"].get("codex_handoff", "")
                    result = self._stage2_codex_execute(
                        summary=summary,
                        run_dry=run_dry,
                        cwd=worktree_path,
                    )
                elif stage == "stage3_gemini_review":
                    if not worktree_path.exists():
                        worktree_path = self.root
                    result = self._stage3_gemini_review(run_dry=run_dry, cwd=worktree_path)
                    if run_dry and worktree_path != self.root:
                        sandbox_review = self._artifact_abs("review", cwd=worktree_path)
                        root_review = self._artifact_abs("review", cwd=self.root)
                        if sandbox_review.exists():
                            self._write_text(
                                root_review, sandbox_review.read_text(encoding="utf-8")
                            )
                elif stage == "stage4_codex_fix":
                    if not worktree_path.exists():
                        worktree_path = self.root
                    result = self._stage4_codex_fix(run_dry=run_dry, cwd=worktree_path)
                elif stage == "stage5_final_review":
                    if not worktree_path.exists():
                        worktree_path = self.root

                    review_result = None
                    for attempt in range(self.max_review_loops + 1):
                        state["pipeline"]["retry_count"] = attempt
                        review_result = self._stage5_final_review(
                            run_dry=run_dry, cwd=worktree_path
                        )
                        if review_result.ok:
                            break
                        if attempt < self.max_review_loops:
                            fix_result = self._stage4_codex_fix(run_dry=run_dry, cwd=worktree_path)
                            stage_results.append(
                                {
                                    "stage": fix_result.stage,
                                    "ok": fix_result.ok,
                                    "details": fix_result.details,
                                    "retry": attempt + 1,
                                }
                            )
                    if review_result is None:
                        review_result = StageResult(stage, False, {"reason": "no review result"})
                    result = review_result
                else:
                    result = StageResult(stage, False, {"error": "unknown stage"})

                stage_results.append(
                    {"stage": result.stage, "ok": result.ok, "details": result.details}
                )
                if result.ok:
                    if stage not in state["pipeline"]["completed_stages"]:
                        state["pipeline"]["completed_stages"].append(stage)
                else:
                    state["pipeline"]["status"] = "failed"
                    state["pipeline"]["last_error"] = f"{stage} failed"
                    self.save_state(state)
                    return {
                        "ok": False,
                        "command": "pipeline",
                        "mode": mode,
                        "stage_results": stage_results,
                        "error": state["pipeline"]["last_error"],
                    }

                self.save_state(state)
                if stop_after is not None and index >= stop_after:
                    return {
                        "ok": True,
                        "command": "pipeline",
                        "mode": mode,
                        "stopped_after": index,
                        "stage_results": stage_results,
                        "state_file": str(self.state_path),
                    }

            if worktree_branch and not run_dry:
                merged, merge_log = self._merge_worktree_branch(worktree_branch)
                if not merged:
                    state["pipeline"]["status"] = "failed"
                    state["pipeline"]["last_error"] = f"merge failed: {merge_log}"
                    self.save_state(state)
                    return {
                        "ok": False,
                        "command": "pipeline",
                        "mode": mode,
                        "stage_results": stage_results,
                        "error": state["pipeline"]["last_error"],
                    }
                self._remove_worktree(path=worktree_path, branch=worktree_branch, force=False)

            state["pipeline"]["status"] = "completed"
            state["pipeline"]["current_stage"] = ""
            state["pipeline"]["finished_at"] = _utc_now()
            state["pipeline"]["last_error"] = ""
            self.save_state(state)
            return {
                "ok": True,
                "command": "pipeline",
                "mode": mode,
                "stage_results": stage_results,
                "state_file": str(self.state_path),
            }
        except Exception as exc:
            state["pipeline"]["status"] = "failed"
            state["pipeline"]["last_error"] = str(exc)
            self.save_state(state)
            return {
                "ok": False,
                "command": "pipeline",
                "mode": mode,
                "stage_results": stage_results,
                "error": str(exc),
            }

    def team(self, *, topic: str, dry_run: bool | None = None) -> dict[str, Any]:
        run_dry, mode = self._resolve_mode(dry_run)
        topic = topic.strip()
        if not topic:
            raise ValueError("team topic 不能为空")

        stage0 = self._stage0_project_brief(topic, run_dry=run_dry, cwd=self.root)
        outputs: list[dict[str, Any]] = []
        prompts = {
            "claude": "从架构设计和长期维护角度讨论。",
            "codex": "从实现复杂度和开发效率角度分析。",
            "gemini": "从成本、性能、团队规模角度分析。",
        }

        for agent in TEAM_AGENTS:
            agent_prompt = f"{topic}\n\n{prompts[agent]}"
            result = self._run_agent(
                agent=agent,
                prompt=agent_prompt,
                cwd=self.root,
                interactive=not run_dry,
                run_dry=run_dry,
            )
            outputs.append(
                {
                    "agent": agent,
                    "returncode": result.returncode,
                    "dry_run": result.dry_run,
                }
            )

        synth_prompt = "请把 claude/codex/gemini 三方观点压缩为对比表。"
        synth = self._run_agent(
            agent="gemini",
            prompt=synth_prompt,
            cwd=self.root,
            interactive=False,
            run_dry=run_dry,
        )

        summary_prompt = (
            "请综合三方观点给出结论与推荐路径。"
            f"\nTopic: {topic}\n"
            f"\nGemini synthesis:\n{synth.stdout}"
        )
        final = self._run_agent(
            agent="claude",
            prompt=summary_prompt,
            cwd=self.root,
            interactive=False,
            run_dry=run_dry,
        )
        summary_path = self.ai_dir / "team-summary.md"
        summary_content = (
            final.stdout.strip() or f"# Team Summary\n\n- topic: {topic}\n- mode: {mode}\n"
        )
        self._write_text(summary_path, summary_content)

        state = self.load_state()
        state["last_action"] = "team"
        state["team"]["topic"] = topic
        state["team"]["ran_at"] = _utc_now()
        state["team"]["last_mode"] = mode
        state["team"]["outputs"] = outputs
        self.save_state(state)
        return {
            "ok": stage0.ok and all(item["returncode"] == 0 for item in outputs),
            "command": "team",
            "mode": mode,
            "topic": topic,
            "agent_count": len(outputs),
            "outputs": outputs,
            "summary_file": str(summary_path),
        }

    def status(self) -> dict[str, Any]:
        state = self.load_state()
        artifacts = {
            name: {
                "path": str(path),
                "exists": (self.root / path).exists(),
            }
            for name, path in ARTIFACT_PATHS.items()
        }
        self.save_state(state)
        return {
            "ok": True,
            "command": "status",
            "root": str(self.root),
            "state_file": str(self.state_path),
            "chat_history_file": str(self.chat_history_path),
            "artifacts": artifacts,
            "state": state,
        }

    def compress(
        self,
        *,
        target_agent: str = "codex",
        max_chars: int = 5000,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        run_dry, mode = self._resolve_mode(dry_run)
        target = _normalize_agent(target_agent)
        source = self._history_text(limit=200)
        result = self.context.compress_context(source, target_agent=target, dry_run=run_dry)
        summary = result.summary
        if max_chars > 0 and len(summary) > max_chars:
            summary = summary[:max_chars]
        state = self.load_state()
        state["last_action"] = "compress"
        self.save_state(state)
        return {
            "ok": True,
            "command": "compress",
            "mode": mode,
            "target_agent": target,
            "compressed": result.compressed,
            "fallback_used": result.used_fallback,
            "reason": result.reason,
            "summary": summary,
        }

    def reset(self) -> dict[str, Any]:
        removed: list[str] = []
        if self.chat_history_path.exists():
            self.chat_history_path.unlink()
            removed.append(str(self.chat_history_path.relative_to(self.root)))
        self.bus.reset()
        if self.state_path.exists():
            self.state_path.unlink()
            removed.append(str(self.state_path.relative_to(self.root)))
        state = self._default_state()
        self.save_state(state)
        return {
            "ok": True,
            "command": "reset",
            "removed_paths": removed,
            "state_file": str(self.state_path),
        }

    def resume(self, *, dry_run: bool | None = None) -> dict[str, Any]:
        state = self.load_state()
        task = state["pipeline"].get("task", "")
        stage = state["pipeline"].get("current_stage", "")
        status = state["pipeline"].get("status", "")
        if not task:
            return {
                "ok": True,
                "command": "resume",
                "can_resume": False,
                "message": "无可恢复 pipeline 任务。",
            }
        if status not in {"in_progress", "blocked", "failed"}:
            return {
                "ok": True,
                "command": "resume",
                "can_resume": False,
                "message": f"当前状态为 {status}，无需恢复。",
            }
        if stage and stage not in PIPELINE_STAGES:
            stage = PIPELINE_STAGES[0]
            state["pipeline"]["current_stage"] = stage
            self.save_state(state)
        resumed = self.pipeline(task=task, dry_run=dry_run, resume=True)
        resumed["command"] = "resume"
        resumed["can_resume"] = True
        resumed["resume_from"] = stage or PIPELINE_STAGES[0]
        return resumed

    def cleanup(self) -> dict[str, Any]:
        state = self.load_state()
        removed: list[str] = []
        skipped: list[str] = []
        worktree_raw = str(state["pipeline"].get("worktree_path", "") or "").strip()
        worktree_path = Path(worktree_raw) if worktree_raw else None
        worktree_branch = state["pipeline"].get("worktree_branch", "")

        if worktree_path is not None:
            if self._is_managed_worktree_path(worktree_path):
                resolved_worktree = self._resolve_path(worktree_path)
                if resolved_worktree.exists():
                    self._remove_worktree(
                        path=resolved_worktree, branch=worktree_branch, force=True
                    )
                    if not resolved_worktree.exists():
                        removed.append(str(resolved_worktree))
            elif worktree_raw:
                skipped.append(str(self._resolve_path(worktree_path)))

        sandbox = self.omo_dir / "sandbox"
        if sandbox.exists():
            sandbox_branch = (
                worktree_branch
                if worktree_path is not None
                and self._resolve_path(worktree_path) == self._resolve_path(sandbox)
                else ""
            )
            self._remove_worktree(path=sandbox, branch=sandbox_branch, force=True)
            if not sandbox.exists():
                sandbox_path = str(self._resolve_path(sandbox))
                if sandbox_path not in removed:
                    removed.append(sandbox_path)

        state["last_action"] = "cleanup"
        state["pipeline"]["worktree_path"] = ""
        state["pipeline"]["worktree_branch"] = ""
        state["pipeline"]["current_stage"] = ""
        self.save_state(state)
        return {
            "ok": True,
            "command": "cleanup",
            "removed_paths": removed,
            "skipped_paths": skipped,
        }
