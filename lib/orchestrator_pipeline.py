"""Pipeline-oriented command implementations for Orchestrator."""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

_BJT = ZoneInfo("Asia/Shanghai")


def _readable_keywords(text: str) -> str:
    """提取可读关键词：保留中英文/数字，其它符号折叠为连字符。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text, flags=re.UNICODE).strip("-_")
    cleaned = re.sub(r"-{2,}", "-", cleaned).replace("_", "-")
    return cleaned.lower()


def _task_summary(task: str, *, max_len: int = 24) -> str:
    normalized = task.strip().replace("\\", "/")
    candidate = normalized.rstrip("/").split("/")[-1] if "/" in normalized else normalized
    candidate = candidate or normalized
    summary = _readable_keywords(candidate) or _readable_keywords(task) or "pipeline"
    return summary[:max_len]


def _build_pipeline_run_id(task: str) -> str:
    now_bj = datetime.now(_BJT)
    date_part = now_bj.strftime("%Y%m%d")
    time_part = now_bj.strftime("%H%M%S")
    summary_part = _task_summary(task)
    short_hash = uuid4().hex[:8]
    return f"{date_part}-{time_part}-{summary_part}-{short_hash}"


def _copy_text(src: Path, dst: Path) -> bool:
    if not src.exists() or not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _sync_root_artifact_to_worktree(orch: Any, *, artifact_name: str, worktree_path: Path) -> None:
    root_file = orch._artifact_abs(artifact_name, cwd=orch.root)
    worktree_file = orch._artifact_abs(artifact_name, cwd=worktree_path)
    if not root_file.exists():
        return
    if root_file.resolve(strict=False) == worktree_file.resolve(strict=False):
        return
    _copy_text(root_file, worktree_file)


def _sync_pipeline_artifacts(
    orch: Any,
    *,
    run_dir: Path,
    latest_dir: Path,
    worktree_path: Path,
) -> dict[str, str]:
    root_project_brief = orch._artifact_abs("project_brief", cwd=orch.root)
    root_exec_plan = orch._artifact_abs("exec_plan", cwd=orch.root)
    root_review = orch._artifact_abs("review", cwd=orch.root)
    sandbox_review = orch._artifact_abs("review", cwd=worktree_path)

    if sandbox_review.exists() and sandbox_review.resolve(strict=False) != root_review.resolve(
        strict=False
    ):
        _copy_text(sandbox_review, root_review)

    artifacts: dict[str, Path] = {
        "project-brief.md": root_project_brief,
        "exec-plan.md": root_exec_plan,
        "review.md": root_review if root_review.exists() else sandbox_review,
    }

    materialized: dict[str, str] = {}
    for filename, src in artifacts.items():
        if not src.exists():
            continue
        run_path = run_dir / filename
        latest_path = latest_dir / filename
        _copy_text(src, run_path)
        _copy_text(src, latest_path)
        materialized[filename] = str(run_path)
    return materialized


def _build_pipeline_summary(
    *,
    run_id: str,
    task: str,
    mode: str,
    status: str,
    started_at: str,
    finished_at: str,
    worktree_path: Path,
    worktree_branch: str,
    error: str,
    stage_results: list[dict[str, Any]],
    artifacts: dict[str, str],
) -> str:
    lines = [
        "# Pipeline Summary",
        "",
        f"- run_id: {run_id}",
        f"- task: {task}",
        f"- mode: {mode}",
        f"- status: {status}",
        f"- started_at: {started_at or 'N/A'}",
        f"- finished_at: {finished_at or 'N/A'}",
        f"- worktree_path: {worktree_path}",
        f"- worktree_branch: {worktree_branch or 'N/A'}",
    ]
    if error:
        lines.append(f"- error: {error}")

    lines.extend(["", "## Stage Results"])
    if stage_results:
        for item in stage_results:
            retry_suffix = f" (retry={item['retry']})" if "retry" in item else ""
            status_text = "PASS" if item.get("ok") else "FAIL"
            lines.append(f"- {status_text} `{item.get('stage', 'unknown')}`{retry_suffix}")
    else:
        lines.append("- no stage results")

    lines.extend(["", "## Artifacts"])
    if artifacts:
        for name, path in artifacts.items():
            lines.append(f"- `{name}` -> `{path}`")
    else:
        lines.append("- no materialized artifacts")
    return "\n".join(lines)


def _persist_pipeline_outputs(
    orch: Any,
    *,
    state: dict[str, Any],
    run_id: str,
    run_dir: Path,
    latest_dir: Path,
    task: str,
    mode: str,
    status: str,
    stage_results: list[dict[str, Any]],
    error: str,
    worktree_path: Path,
    worktree_branch: str,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)

    artifacts = _sync_pipeline_artifacts(
        orch,
        run_dir=run_dir,
        latest_dir=latest_dir,
        worktree_path=worktree_path,
    )

    summary_path = run_dir / "pipeline-summary.md"
    latest_summary_path = latest_dir / "pipeline-summary.md"
    meta_path = run_dir / "meta.json"
    latest_meta_path = latest_dir / "run.json"

    summary_content = _build_pipeline_summary(
        run_id=run_id,
        task=task,
        mode=mode,
        status=status,
        started_at=str(state["pipeline"].get("started_at", "")),
        finished_at=str(state["pipeline"].get("finished_at", "")),
        worktree_path=worktree_path,
        worktree_branch=worktree_branch,
        error=error,
        stage_results=stage_results,
        artifacts=artifacts,
    )
    orch._write_text(summary_path, summary_content)
    orch._write_text(latest_summary_path, summary_content)

    meta_payload = {
        "run_id": run_id,
        "task": task,
        "mode": mode,
        "status": status,
        "started_at": state["pipeline"].get("started_at", ""),
        "finished_at": state["pipeline"].get("finished_at", ""),
        "worktree_path": str(worktree_path),
        "worktree_branch": worktree_branch,
        "error": error,
        "stage_results": stage_results,
        "artifacts": artifacts,
        "state_file": str(orch.state_path),
    }
    orch._write_json(meta_path, meta_payload)
    orch._write_json(
        latest_meta_path,
        {
            "run_id": run_id,
            "task": task,
            "mode": mode,
            "status": status,
            "summary_file": str(summary_path),
            "meta_file": str(meta_path),
        },
    )

    state["pipeline"]["run_id"] = run_id
    state["pipeline"]["run_dir"] = str(run_dir)
    state["pipeline"]["latest_dir"] = str(latest_dir)
    state["pipeline"]["summary_file"] = str(summary_path)
    state["pipeline"]["meta_file"] = str(meta_path)
    state["pipeline"]["latest_summary_file"] = str(latest_summary_path)
    state["pipeline"]["latest_meta_file"] = str(latest_meta_path)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "summary_file": str(summary_path),
        "meta_file": str(meta_path),
        "latest_summary_file": str(latest_summary_path),
        "latest_meta_file": str(latest_meta_path),
        "artifacts": artifacts,
    }


def run_pipeline(
    orch: Any,
    *,
    task: str,
    dry_run: bool | None = None,
    stop_after: int | None = None,
    resume: bool = False,
    pipeline_stages: Sequence[str],
    stage_result_cls: type[Any],
    utc_now: Callable[[], str],
) -> dict[str, Any]:
    run_dry, mode = orch._resolve_mode(dry_run)
    task = task.strip()
    if not task:
        raise ValueError("pipeline task 不能为空")

    state = orch.load_state()
    pipeline_root = orch.ai_dir / "pipeline"

    run_id_raw = str(state["pipeline"].get("run_id", "") or "").strip() if resume else ""
    run_id = run_id_raw or _build_pipeline_run_id(task)

    run_dir_raw = str(state["pipeline"].get("run_dir", "") or "").strip() if resume else ""
    run_dir = Path(run_dir_raw) if run_dir_raw else pipeline_root / "runs" / run_id
    if not run_dir.is_absolute():
        run_dir = (orch.root / run_dir).resolve(strict=False)

    latest_dir_raw = str(state["pipeline"].get("latest_dir", "") or "").strip() if resume else ""
    latest_dir = Path(latest_dir_raw) if latest_dir_raw else pipeline_root / "latest"
    if not latest_dir.is_absolute():
        latest_dir = (orch.root / latest_dir).resolve(strict=False)

    if not resume:
        state["pipeline"].update(
            {
                "task": task,
                "status": "in_progress",
                "current_stage": pipeline_stages[0],
                "completed_stages": [],
                "retry_count": 0,
                "worktree_path": "",
                "worktree_branch": "",
                "run_id": run_id,
                "run_dir": str(run_dir),
                "latest_dir": str(latest_dir),
                "summary_file": str(run_dir / "pipeline-summary.md"),
                "meta_file": str(run_dir / "meta.json"),
                "latest_summary_file": str(latest_dir / "pipeline-summary.md"),
                "latest_meta_file": str(latest_dir / "run.json"),
                "started_at": utc_now(),
                "finished_at": "",
                "last_error": "",
            }
        )
    else:
        state["pipeline"]["run_id"] = run_id
        state["pipeline"]["run_dir"] = str(run_dir)
        state["pipeline"]["latest_dir"] = str(latest_dir)
        state["pipeline"].setdefault("summary_file", str(run_dir / "pipeline-summary.md"))
        state["pipeline"].setdefault("meta_file", str(run_dir / "meta.json"))
        state["pipeline"].setdefault("latest_summary_file", str(latest_dir / "pipeline-summary.md"))
        state["pipeline"].setdefault("latest_meta_file", str(latest_dir / "run.json"))

    state["last_action"] = "pipeline"
    orch.save_state(state)

    worktree_path = Path(state["pipeline"].get("worktree_path", "") or orch.root)
    worktree_branch = state["pipeline"].get("worktree_branch", "")
    stage_results: list[dict[str, Any]] = []

    if not run_dry:
        preflight = orch.integrations.policy_check(cwd=orch.root)
        if not preflight.ok:
            state["pipeline"]["status"] = "blocked"
            state["pipeline"]["last_error"] = preflight.error or "policy check failed"
            persisted = _persist_pipeline_outputs(
                orch,
                state=state,
                run_id=run_id,
                run_dir=run_dir,
                latest_dir=latest_dir,
                task=task,
                mode=mode,
                status="blocked",
                stage_results=stage_results,
                error=state["pipeline"]["last_error"],
                worktree_path=worktree_path,
                worktree_branch=worktree_branch,
            )
            orch.save_state(state)
            return {
                "ok": False,
                "command": "pipeline",
                "mode": mode,
                "error": state["pipeline"]["last_error"],
                **persisted,
            }

    start_index = 0
    if resume and state["pipeline"]["current_stage"] in pipeline_stages:
        start_index = pipeline_stages.index(state["pipeline"]["current_stage"])

    try:
        for index, stage in enumerate(pipeline_stages[start_index:], start=start_index):
            state["pipeline"]["current_stage"] = stage
            orch.save_state(state)

            if stage == "stage0_project_brief":
                result = orch._stage0_project_brief(task, run_dry=run_dry, cwd=orch.root)
            elif stage == "stage1_exec_plan":
                result = orch._stage1_exec_plan(task, run_dry=run_dry, cwd=orch.root)
                exec_plan = orch._artifact_abs("exec_plan", cwd=orch.root)
                if not exec_plan.exists():
                    orch._write_text(exec_plan, orch._fallback_exec_plan(task))
                if not orch.auto_confirm and sys.stdin.isatty() and not run_dry:
                    answer = input("执行方案已生成，继续执行？[Y/n] ").strip().lower()
                    if answer in {"n", "no"}:
                        state["pipeline"]["status"] = "blocked"
                        state["pipeline"]["last_error"] = (
                            "user aborted after exec-plan confirmation"
                        )
                        persisted = _persist_pipeline_outputs(
                            orch,
                            state=state,
                            run_id=run_id,
                            run_dir=run_dir,
                            latest_dir=latest_dir,
                            task=task,
                            mode=mode,
                            status="blocked",
                            stage_results=stage_results,
                            error=state["pipeline"]["last_error"],
                            worktree_path=worktree_path,
                            worktree_branch=worktree_branch,
                        )
                        orch.save_state(state)
                        return {
                            "ok": False,
                            "command": "pipeline",
                            "mode": mode,
                            "stage_results": stage_results,
                            "error": state["pipeline"]["last_error"],
                            **persisted,
                        }

                history_text = orch._history_text(limit=120)
                compact = orch.context.compress_context(
                    history_text or task,
                    target_agent="codex",
                    dry_run=run_dry,
                )
                state["pipeline"]["codex_handoff"] = compact.summary
            elif stage == "stage2_codex_execute":
                if not worktree_branch:
                    worktree_path, worktree_branch = orch._create_worktree(task, run_dry=run_dry)
                    state["pipeline"]["worktree_path"] = str(worktree_path)
                    state["pipeline"]["worktree_branch"] = worktree_branch
                if worktree_path != orch.root:
                    _sync_root_artifact_to_worktree(
                        orch,
                        artifact_name="project_brief",
                        worktree_path=worktree_path,
                    )
                    _sync_root_artifact_to_worktree(
                        orch,
                        artifact_name="exec_plan",
                        worktree_path=worktree_path,
                    )
                summary = state["pipeline"].get("codex_handoff", "")
                result = orch._stage2_codex_execute(
                    summary=summary,
                    run_dry=run_dry,
                    cwd=worktree_path,
                )
            elif stage == "stage3_gemini_review":
                if not worktree_path.exists():
                    worktree_path = orch.root
                result = orch._stage3_gemini_review(run_dry=run_dry, cwd=worktree_path)
                if worktree_path != orch.root:
                    sandbox_review = orch._artifact_abs("review", cwd=worktree_path)
                    root_review = orch._artifact_abs("review", cwd=orch.root)
                    if sandbox_review.exists():
                        orch._write_text(root_review, sandbox_review.read_text(encoding="utf-8"))
            elif stage == "stage4_codex_fix":
                if not worktree_path.exists():
                    worktree_path = orch.root
                result = orch._stage4_codex_fix(run_dry=run_dry, cwd=worktree_path)
            elif stage == "stage5_final_review":
                if not worktree_path.exists():
                    worktree_path = orch.root

                review_result = None
                for attempt in range(orch.max_review_loops + 1):
                    state["pipeline"]["retry_count"] = attempt
                    review_result = orch._stage5_final_review(run_dry=run_dry, cwd=worktree_path)
                    if review_result.ok:
                        break
                    if attempt < orch.max_review_loops:
                        fix_result = orch._stage4_codex_fix(run_dry=run_dry, cwd=worktree_path)
                        stage_results.append(
                            {
                                "stage": fix_result.stage,
                                "ok": fix_result.ok,
                                "details": fix_result.details,
                                "retry": attempt + 1,
                            }
                        )
                if review_result is None:
                    review_result = stage_result_cls(stage, False, {"reason": "no review result"})
                result = review_result
            else:
                result = stage_result_cls(stage, False, {"error": "unknown stage"})

            stage_results.append(
                {"stage": result.stage, "ok": result.ok, "details": result.details}
            )
            if result.ok:
                if stage not in state["pipeline"]["completed_stages"]:
                    state["pipeline"]["completed_stages"].append(stage)
            else:
                state["pipeline"]["status"] = "failed"
                state["pipeline"]["last_error"] = f"{stage} failed"
                persisted = _persist_pipeline_outputs(
                    orch,
                    state=state,
                    run_id=run_id,
                    run_dir=run_dir,
                    latest_dir=latest_dir,
                    task=task,
                    mode=mode,
                    status="failed",
                    stage_results=stage_results,
                    error=state["pipeline"]["last_error"],
                    worktree_path=worktree_path,
                    worktree_branch=worktree_branch,
                )
                orch.save_state(state)
                return {
                    "ok": False,
                    "command": "pipeline",
                    "mode": mode,
                    "stage_results": stage_results,
                    "error": state["pipeline"]["last_error"],
                    **persisted,
                }

            orch.save_state(state)
            if stop_after is not None and index >= stop_after:
                persisted = _persist_pipeline_outputs(
                    orch,
                    state=state,
                    run_id=run_id,
                    run_dir=run_dir,
                    latest_dir=latest_dir,
                    task=task,
                    mode=mode,
                    status=f"stopped_after_{index}",
                    stage_results=stage_results,
                    error=state["pipeline"].get("last_error", ""),
                    worktree_path=worktree_path,
                    worktree_branch=worktree_branch,
                )
                orch.save_state(state)
                return {
                    "ok": True,
                    "command": "pipeline",
                    "mode": mode,
                    "stopped_after": index,
                    "stage_results": stage_results,
                    "state_file": str(orch.state_path),
                    **persisted,
                }

        if worktree_branch and not run_dry:
            merged, merge_log = orch._merge_worktree_branch(worktree_branch)
            if not merged:
                state["pipeline"]["status"] = "failed"
                state["pipeline"]["last_error"] = f"merge failed: {merge_log}"
                persisted = _persist_pipeline_outputs(
                    orch,
                    state=state,
                    run_id=run_id,
                    run_dir=run_dir,
                    latest_dir=latest_dir,
                    task=task,
                    mode=mode,
                    status="failed",
                    stage_results=stage_results,
                    error=state["pipeline"]["last_error"],
                    worktree_path=worktree_path,
                    worktree_branch=worktree_branch,
                )
                orch.save_state(state)
                return {
                    "ok": False,
                    "command": "pipeline",
                    "mode": mode,
                    "stage_results": stage_results,
                    "error": state["pipeline"]["last_error"],
                    **persisted,
                }
            orch._remove_worktree(path=worktree_path, branch=worktree_branch, force=False)

        state["pipeline"]["status"] = "completed"
        state["pipeline"]["current_stage"] = ""
        state["pipeline"]["finished_at"] = utc_now()
        state["pipeline"]["last_error"] = ""
        persisted = _persist_pipeline_outputs(
            orch,
            state=state,
            run_id=run_id,
            run_dir=run_dir,
            latest_dir=latest_dir,
            task=task,
            mode=mode,
            status="completed",
            stage_results=stage_results,
            error="",
            worktree_path=worktree_path,
            worktree_branch=worktree_branch,
        )
        orch.save_state(state)
        return {
            "ok": True,
            "command": "pipeline",
            "mode": mode,
            "stage_results": stage_results,
            "state_file": str(orch.state_path),
            **persisted,
        }
    except Exception as exc:
        state["pipeline"]["status"] = "failed"
        state["pipeline"]["last_error"] = str(exc)
        persisted = _persist_pipeline_outputs(
            orch,
            state=state,
            run_id=run_id,
            run_dir=run_dir,
            latest_dir=latest_dir,
            task=task,
            mode=mode,
            status="failed",
            stage_results=stage_results,
            error=str(exc),
            worktree_path=worktree_path,
            worktree_branch=worktree_branch,
        )
        orch.save_state(state)
        return {
            "ok": False,
            "command": "pipeline",
            "mode": mode,
            "stage_results": stage_results,
            "error": str(exc),
            **persisted,
        }


def run_resume(
    orch: Any,
    *,
    dry_run: bool | None = None,
    pipeline_stages: Sequence[str],
) -> dict[str, Any]:
    state = orch.load_state()
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
    if stage and stage not in pipeline_stages:
        stage = pipeline_stages[0]
        state["pipeline"]["current_stage"] = stage
        orch.save_state(state)
    resumed = orch.pipeline(task=task, dry_run=dry_run, resume=True)
    resumed["command"] = "resume"
    resumed["can_resume"] = True
    resumed["resume_from"] = stage or pipeline_stages[0]
    return resumed


def run_cleanup(orch: Any) -> dict[str, Any]:
    state = orch.load_state()
    removed: list[str] = []
    skipped: list[str] = []
    worktree_raw = str(state["pipeline"].get("worktree_path", "") or "").strip()
    worktree_path = Path(worktree_raw) if worktree_raw else None
    worktree_branch = state["pipeline"].get("worktree_branch", "")

    if worktree_path is not None:
        if orch._is_managed_worktree_path(worktree_path):
            resolved_worktree = orch._resolve_path(worktree_path)
            if resolved_worktree.exists():
                orch._remove_worktree(path=resolved_worktree, branch=worktree_branch, force=True)
                if not resolved_worktree.exists():
                    removed.append(str(resolved_worktree))
        elif worktree_raw:
            skipped.append(str(orch._resolve_path(worktree_path)))

    sandbox = orch.omo_dir / "sandbox"
    if sandbox.exists():
        sandbox_branch = (
            worktree_branch
            if worktree_path is not None
            and orch._resolve_path(worktree_path) == orch._resolve_path(sandbox)
            else ""
        )
        orch._remove_worktree(path=sandbox, branch=sandbox_branch, force=True)
        if not sandbox.exists():
            sandbox_path = str(orch._resolve_path(sandbox))
            if sandbox_path not in removed:
                removed.append(sandbox_path)

    state["last_action"] = "cleanup"
    state["pipeline"]["worktree_path"] = ""
    state["pipeline"]["worktree_branch"] = ""
    state["pipeline"]["current_stage"] = ""
    orch.save_state(state)
    return {
        "ok": True,
        "command": "cleanup",
        "removed_paths": removed,
        "skipped_paths": skipped,
    }
