"""Pipeline-oriented command implementations for Orchestrator."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

from .agents import SUPPORTED_AGENT_TOOLS
from .logging_config import stderr_preview
from .protocols import OrchestratorProtocol, StageResultProtocol
from .run_registry import ensure_project_registry, write_run_registry

_BJT = ZoneInfo("Asia/Shanghai")
LOGGER = logging.getLogger(__name__)


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


@dataclass(slots=True)
class PipelineLockState:
    acquired: bool
    lock_file: Path
    pid_file: Path
    handle: Any | None = None
    owner_pid: int = 0
    owner_run_id: str = ""


def _read_pipeline_owner(pid_file: Path) -> tuple[int, str]:
    if not pid_file.exists():
        return 0, ""
    try:
        payload = json.loads(pid_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, ""
    if not isinstance(payload, dict):
        return 0, ""
    pid_raw = payload.get("pid", 0)
    try:
        pid = int(pid_raw)
    except (TypeError, ValueError):
        pid = 0
    run_id = str(payload.get("run_id", "") or "")
    return pid, run_id


def _acquire_pipeline_lock(
    orch: OrchestratorProtocol,
    *,
    run_id: str,
    task: str,
    utc_now: Callable[[], str],
) -> PipelineLockState:
    lock_file = orch.omo_dir / "pipeline.lock"
    pid_file = orch.omo_dir / "pipeline.pid"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_file.open("a+", encoding="utf-8")

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        owner_pid, owner_run_id = _read_pipeline_owner(pid_file)
        handle.close()
        return PipelineLockState(
            acquired=False,
            lock_file=lock_file,
            pid_file=pid_file,
            owner_pid=owner_pid,
            owner_run_id=owner_run_id,
        )

    payload = {
        "pid": os.getpid(),
        "run_id": run_id,
        "task": task,
        "started_at": utc_now(),
    }
    pid_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return PipelineLockState(
        acquired=True,
        lock_file=lock_file,
        pid_file=pid_file,
        handle=handle,
        owner_pid=int(payload["pid"]),
        owner_run_id=run_id,
    )


def _release_pipeline_lock(lock_state: PipelineLockState) -> None:
    if lock_state.handle is None:
        return
    try:
        fcntl.flock(lock_state.handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        lock_state.handle.close()
    except OSError:
        pass
    lock_state.handle = None
    if not lock_state.acquired:
        return
    try:
        lock_state.pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def _return_with_lock_release(
    lock_state: PipelineLockState,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _release_pipeline_lock(lock_state)
    return payload


def _copy_text(src: Path, dst: Path) -> bool:
    if not src.exists() or not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _sync_root_artifact_to_worktree(
    orch: OrchestratorProtocol,
    *,
    artifact_name: str,
    worktree_path: Path,
) -> None:
    root_file = orch._artifact_abs(artifact_name, cwd=orch.root)
    worktree_file = orch._artifact_abs(artifact_name, cwd=worktree_path)
    if not root_file.exists():
        return
    if root_file.resolve(strict=False) == worktree_file.resolve(strict=False):
        return
    _copy_text(root_file, worktree_file)


def _sync_pipeline_artifacts(
    orch: OrchestratorProtocol,
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


def _safe_stage_slug(stage: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", stage).strip("-").lower()
    return slug or "stage"


def _normalize_command(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    if raw is None:
        return []
    return [str(raw)]


def _persist_stage_agent_runs(
    run_dir: Path,
    *,
    stage_entry: dict[str, Any],
    stage_index: int,
    stage_total: int,
) -> str | None:
    details = stage_entry.get("details", {})
    if not isinstance(details, dict):
        return None

    raw_runs = details.get("agent_runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        return None

    normalized_runs: list[dict[str, Any]] = []
    for raw in raw_runs:
        if not isinstance(raw, dict):
            continue
        try:
            returncode = int(raw.get("returncode", 0) or 0)
        except (TypeError, ValueError):
            returncode = 0
        stderr_raw = raw.get("stderr")
        if stderr_raw is None:
            stderr_raw = raw.get("stderr_preview", "")
        preview, truncated = stderr_preview(str(stderr_raw or ""), limit=500)
        normalized_runs.append(
            {
                "agent": str(raw.get("agent", "") or ""),
                "mode": str(raw.get("mode", "") or ""),
                "cwd": str(raw.get("cwd", "") or ""),
                "command": _normalize_command(raw.get("command")),
                "returncode": returncode,
                "stderr_preview": preview,
                "stderr_truncated": bool(raw.get("stderr_truncated")) or truncated,
            }
        )

    if not normalized_runs:
        return None

    stage_name = str(stage_entry.get("stage", "unknown"))
    agents_dir = run_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    retry = stage_entry.get("retry")
    retry_suffix = ""
    if isinstance(retry, int) and retry > 0:
        retry_suffix = f"-retry{retry}"
    output_file = (
        agents_dir / f"{stage_index:02d}-{_safe_stage_slug(stage_name)}{retry_suffix}.json"
    )
    payload = {
        "stage": stage_name,
        "stage_index": stage_index,
        "stage_total": stage_total,
        "ok": bool(stage_entry.get("ok", False)),
        "duration_sec": round(float(stage_entry.get("duration_sec", 0.0) or 0.0), 3),
        "agent_results": normalized_runs,
    }
    output_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    details["agent_result_file"] = str(output_file)
    return str(output_file)


def _collect_stage_durations(
    stage_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], float]:
    durations: list[dict[str, Any]] = []
    total = 0.0
    for item in stage_results:
        if not isinstance(item, dict):
            continue
        raw_duration = item.get("duration_sec")
        if not isinstance(raw_duration, (int, float)):
            continue
        duration = round(float(raw_duration), 3)
        total += duration
        duration_row: dict[str, Any] = {
            "stage": str(item.get("stage", "unknown")),
            "duration_sec": duration,
            "ok": bool(item.get("ok", False)),
        }
        if "retry" in item:
            duration_row["retry"] = int(item.get("retry", 0) or 0)
        durations.append(duration_row)
    return durations, round(total, 3)


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
    orch: OrchestratorProtocol,
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
    decisions_dir = run_dir / "decisions"
    context_pack_path = decisions_dir / "context-pack.json"
    stage_results_path = decisions_dir / "stage-results.json"
    final_gate_path = decisions_dir / "final-gate.json"

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

    context_pack_payload = {
        "run_id": run_id,
        "task": task,
        "mode": mode,
        "status": status,
        "current_stage": state["pipeline"].get("current_stage", ""),
        "retry_count": state["pipeline"].get("retry_count", 0),
    }
    orch._write_json(context_pack_path, context_pack_payload)
    stage_results_path.parent.mkdir(parents=True, exist_ok=True)
    stage_results_path.write_text(
        json.dumps(stage_results, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    final_gate_payload = {
        "status": status,
        "error": error,
        "finished_at": state["pipeline"].get("finished_at", ""),
        "verify_hint": "./scripts/verify",
    }
    orch._write_json(final_gate_path, final_gate_payload)

    decision_files = {
        "context-pack.json": str(context_pack_path),
        "stage-results.json": str(stage_results_path),
        "final-gate.json": str(final_gate_path),
    }
    stage_durations, pipeline_duration_sec = _collect_stage_durations(stage_results)

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
        "stage_durations": stage_durations,
        "pipeline_duration_sec": pipeline_duration_sec,
        "artifacts": artifacts,
        "agents_dir": str(run_dir / "agents"),
        "decisions_dir": str(decisions_dir),
        "decision_files": decision_files,
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
    state["pipeline"]["decisions_dir"] = str(decisions_dir)
    state["pipeline"]["decision_files"] = decision_files

    project_registry_path = ensure_project_registry(
        orch.root,
        orch.state_path,
        default_timezone="Asia/Shanghai",
    )
    project_registry_payload = json.loads(project_registry_path.read_text(encoding="utf-8"))
    run_payload = {
        "schema_version": 1,
        "run_id": run_id,
        "project_id": str(project_registry_payload.get("project_id", "")),
        "kind": "pipeline",
        "mode": mode,
        "status": status,
        "task": task,
        "started_at": state["pipeline"].get("started_at", ""),
        "finished_at": state["pipeline"].get("finished_at", ""),
        "current_stage": state["pipeline"].get("current_stage", ""),
        "completed_stages": list(state["pipeline"].get("completed_stages", [])),
        "retry_count": state["pipeline"].get("retry_count", 0),
        "worktree_path": str(worktree_path),
        "worktree_branch": worktree_branch,
        "error": error,
        "summary_file": str(summary_path),
        "meta_file": str(meta_path),
    }
    registry_artifacts = {
        "pipeline-summary.md": str(summary_path),
        "meta.json": str(meta_path),
        "decisions/context-pack.json": str(context_pack_path),
        "decisions/stage-results.json": str(stage_results_path),
        "decisions/final-gate.json": str(final_gate_path),
    }
    registry_artifacts.update(artifacts)
    write_run_registry(
        orch.root,
        kind="pipeline",
        run_id=run_id,
        run_payload=run_payload,
        artifacts=registry_artifacts,
        decisions=stage_results,
    )

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "summary_file": str(summary_path),
        "meta_file": str(meta_path),
        "latest_summary_file": str(latest_summary_path),
        "latest_meta_file": str(latest_meta_path),
        "artifacts": artifacts,
        "decisions_dir": str(decisions_dir),
        "decision_files": decision_files,
    }


@dataclass(slots=True)
class PipelineRunContext:
    orch: OrchestratorProtocol
    lock_state: PipelineLockState
    state: dict[str, Any]
    run_id: str
    run_dir: Path
    latest_dir: Path
    task: str
    mode: str
    run_dry: bool
    utc_now: Callable[[], str]
    pipeline_stages: Sequence[str]
    stage_result_cls: type[Any]
    worktree_path: Path
    worktree_branch: str
    stage_results: list[dict[str, Any]]


def _resolve_pipeline_dir(root: Path, *, raw: str, fallback: Path) -> Path:
    target = Path(raw) if raw else fallback
    if target.is_absolute():
        return target
    return (root / target).resolve(strict=False)


def _prepare_pipeline_context(
    orch: OrchestratorProtocol,
    *,
    state: dict[str, Any],
    lock_state: PipelineLockState,
    run_id: str,
    task: str,
    run_dry: bool,
    mode: str,
    resume: bool,
    pipeline_stages: Sequence[str],
    stage_result_cls: type[Any],
    utc_now: Callable[[], str],
) -> PipelineRunContext:
    pipeline_root = orch.ai_dir / "pipeline"
    run_dir_raw = str(state["pipeline"].get("run_dir", "") or "").strip() if resume else ""
    latest_dir_raw = str(state["pipeline"].get("latest_dir", "") or "").strip() if resume else ""
    run_dir = _resolve_pipeline_dir(
        orch.root,
        raw=run_dir_raw,
        fallback=pipeline_root / "runs" / run_id,
    )
    latest_dir = _resolve_pipeline_dir(
        orch.root,
        raw=latest_dir_raw,
        fallback=pipeline_root / "latest",
    )

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
    return PipelineRunContext(
        orch=orch,
        lock_state=lock_state,
        state=state,
        run_id=run_id,
        run_dir=run_dir,
        latest_dir=latest_dir,
        task=task,
        mode=mode,
        run_dry=run_dry,
        utc_now=utc_now,
        pipeline_stages=pipeline_stages,
        stage_result_cls=stage_result_cls,
        worktree_path=Path(state["pipeline"].get("worktree_path", "") or orch.root),
        worktree_branch=str(state["pipeline"].get("worktree_branch", "") or ""),
        stage_results=[],
    )


def _pipeline_lock_conflict_payload(lock_state: PipelineLockState, *, mode: str) -> dict[str, Any]:
    owner = []
    if lock_state.owner_pid:
        owner.append(f"pid={lock_state.owner_pid}")
    if lock_state.owner_run_id:
        owner.append(f"run_id={lock_state.owner_run_id}")
    owner_hint = f" ({', '.join(owner)})" if owner else ""
    return _return_with_lock_release(
        lock_state,
        {
            "ok": False,
            "command": "pipeline",
            "mode": mode,
            "error": f"pipeline already running{owner_hint}",
            "lock_file": str(lock_state.lock_file),
            "pid_file": str(lock_state.pid_file),
        },
    )


def _persist_pipeline_result(
    ctx: PipelineRunContext,
    *,
    ok: bool,
    status: str,
    error: str,
    include_stage_results: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not status.startswith("stopped_after_"):
        ctx.state["pipeline"]["status"] = status
    if status == "completed":
        ctx.state["pipeline"]["current_stage"] = ""
        ctx.state["pipeline"]["finished_at"] = ctx.utc_now()
        ctx.state["pipeline"]["last_error"] = ""
    else:
        ctx.state["pipeline"]["last_error"] = error

    persisted = _persist_pipeline_outputs(
        ctx.orch,
        state=ctx.state,
        run_id=ctx.run_id,
        run_dir=ctx.run_dir,
        latest_dir=ctx.latest_dir,
        task=ctx.task,
        mode=ctx.mode,
        status=status,
        stage_results=ctx.stage_results,
        error=error,
        worktree_path=ctx.worktree_path,
        worktree_branch=ctx.worktree_branch,
    )
    ctx.orch.save_state(ctx.state)

    payload: dict[str, Any] = {"ok": ok, "command": "pipeline", "mode": ctx.mode, **persisted}
    if include_stage_results:
        payload["stage_results"] = ctx.stage_results
    if error:
        payload["error"] = error
    if ok:
        payload["state_file"] = str(ctx.orch.state_path)
    if extra:
        payload.update(extra)
    return _return_with_lock_release(ctx.lock_state, payload)


def _missing_agent_tools() -> list[str]:
    return [tool for tool in SUPPORTED_AGENT_TOOLS if shutil.which(tool) is None]


def _run_preflight(ctx: PipelineRunContext) -> dict[str, Any] | None:
    if ctx.run_dry:
        return None

    missing_agents = _missing_agent_tools()
    if missing_agents:
        return _persist_pipeline_result(
            ctx,
            ok=False,
            status="blocked",
            error=f"missing agent CLI(s): {', '.join(missing_agents)}",
            include_stage_results=False,
            extra={"missing_agents": missing_agents},
        )

    try:
        preflight = ctx.orch.integrations.policy_check(cwd=ctx.orch.root)
    except Exception as exc:  # pragma: no cover - defensive integration boundary.
        return _return_with_lock_release(
            ctx.lock_state,
            {
                "ok": False,
                "command": "pipeline",
                "mode": ctx.mode,
                "error": f"policy check exception: {exc}",
                "lock_file": str(ctx.lock_state.lock_file),
                "pid_file": str(ctx.lock_state.pid_file),
            },
        )
    if preflight.ok:
        return None
    return _persist_pipeline_result(
        ctx,
        ok=False,
        status="blocked",
        error=preflight.error or "policy check failed",
        include_stage_results=False,
    )


def _stage_result_details(result: StageResultProtocol) -> dict[str, Any]:
    return result.details if isinstance(result.details, dict) else {}


def _record_stage_entry(
    ctx: PipelineRunContext,
    *,
    result: StageResultProtocol,
    stage_index: int,
    stage_total: int,
    stage_duration: float,
) -> None:
    details = _stage_result_details(result)
    stage_entry = {
        "stage": result.stage,
        "ok": result.ok,
        "details": details,
        "duration_sec": stage_duration,
    }
    ctx.stage_results.append(stage_entry)
    agent_result_file = _persist_stage_agent_runs(
        ctx.run_dir,
        stage_entry=stage_entry,
        stage_index=stage_index,
        stage_total=stage_total,
    )
    if agent_result_file:
        stage_entry["agent_result_file"] = agent_result_file
        details["agent_result_file"] = agent_result_file


def _run_stage5_review_with_retry(
    ctx: PipelineRunContext,
    *,
    stage_index: int,
    stage_total: int,
) -> StageResultProtocol:
    if not ctx.worktree_path.exists():
        ctx.worktree_path = ctx.orch.root

    review_result: StageResultProtocol | None = None
    for attempt in range(ctx.orch.max_review_loops + 1):
        ctx.state["pipeline"]["retry_count"] = attempt
        review_result = ctx.orch._stage5_final_review(run_dry=ctx.run_dry, cwd=ctx.worktree_path)
        if review_result.ok:
            break
        if attempt >= ctx.orch.max_review_loops:
            continue
        retry_started = perf_counter()
        fix_result = ctx.orch._stage4_codex_fix(run_dry=ctx.run_dry, cwd=ctx.worktree_path)
        retry_details = _stage_result_details(fix_result)
        retry_entry = {
            "stage": fix_result.stage,
            "ok": fix_result.ok,
            "details": retry_details,
            "retry": attempt + 1,
            "duration_sec": round(perf_counter() - retry_started, 3),
        }
        ctx.stage_results.append(retry_entry)
        agent_result_file = _persist_stage_agent_runs(
            ctx.run_dir,
            stage_entry=retry_entry,
            stage_index=stage_index,
            stage_total=stage_total,
        )
        if agent_result_file:
            retry_entry["agent_result_file"] = agent_result_file
            retry_details["agent_result_file"] = agent_result_file
        LOGGER.info(
            "[stage %s/%s] %s retry-%s %s (%.3fs)",
            stage_index,
            stage_total,
            fix_result.stage,
            attempt + 1,
            "PASS" if fix_result.ok else "FAIL",
            retry_entry["duration_sec"],
        )

    if review_result is not None:
        return review_result
    return ctx.stage_result_cls("stage5_final_review", False, {"reason": "no review result"})


def _execute_stage1_exec_plan(
    ctx: PipelineRunContext,
) -> tuple[StageResultProtocol, dict[str, Any] | None]:
    orch = ctx.orch
    result = orch._stage1_exec_plan(ctx.task, run_dry=ctx.run_dry, cwd=orch.root)
    exec_plan = orch._artifact_abs("exec_plan", cwd=orch.root)
    if not exec_plan.exists():
        orch._write_text(exec_plan, orch._fallback_exec_plan(ctx.task))
    if not orch.auto_confirm and sys.stdin.isatty() and not ctx.run_dry:
        answer = input("执行方案已生成，继续执行？[Y/n] ").strip().lower()
        if answer in {"n", "no"}:
            return result, _persist_pipeline_result(
                ctx,
                ok=False,
                status="blocked",
                error="user aborted after exec-plan confirmation",
                include_stage_results=True,
            )
    history_text = orch._history_text(limit=120)
    compact = orch.context.compress_context(
        history_text or ctx.task,
        target_agent="codex",
        dry_run=ctx.run_dry,
    )
    ctx.state["pipeline"]["codex_handoff"] = compact.summary
    return result, None


def _execute_stage2_codex_execute(ctx: PipelineRunContext) -> StageResultProtocol:
    orch = ctx.orch
    if not ctx.worktree_branch:
        worktree_path, worktree_branch = orch._create_worktree(ctx.task, run_dry=ctx.run_dry)
        ctx.worktree_path = worktree_path
        ctx.worktree_branch = worktree_branch
        ctx.state["pipeline"]["worktree_path"] = str(worktree_path)
        ctx.state["pipeline"]["worktree_branch"] = worktree_branch
    if ctx.worktree_path != orch.root:
        _sync_root_artifact_to_worktree(
            orch,
            artifact_name="project_brief",
            worktree_path=ctx.worktree_path,
        )
        _sync_root_artifact_to_worktree(
            orch,
            artifact_name="exec_plan",
            worktree_path=ctx.worktree_path,
        )
    summary = str(ctx.state["pipeline"].get("codex_handoff", "") or "")
    return orch._stage2_codex_execute(
        summary=summary,
        run_dry=ctx.run_dry,
        cwd=ctx.worktree_path,
    )


def _execute_stage(
    ctx: PipelineRunContext,
    *,
    stage: str,
    stage_index: int,
    stage_total: int,
) -> tuple[StageResultProtocol, dict[str, Any] | None]:
    orch = ctx.orch
    if stage == "stage0_project_brief":
        return orch._stage0_project_brief(ctx.task, run_dry=ctx.run_dry, cwd=orch.root), None

    if stage == "stage1_exec_plan":
        return _execute_stage1_exec_plan(ctx)

    if stage == "stage2_codex_execute":
        return _execute_stage2_codex_execute(ctx), None

    if stage == "stage3_gemini_review":
        if not ctx.worktree_path.exists():
            ctx.worktree_path = orch.root
        result = orch._stage3_gemini_review(run_dry=ctx.run_dry, cwd=ctx.worktree_path)
        if ctx.worktree_path != orch.root:
            sandbox_review = orch._artifact_abs("review", cwd=ctx.worktree_path)
            root_review = orch._artifact_abs("review", cwd=orch.root)
            if sandbox_review.exists():
                orch._write_text(root_review, sandbox_review.read_text(encoding="utf-8"))
        return result, None

    if stage == "stage4_codex_fix":
        if not ctx.worktree_path.exists():
            ctx.worktree_path = orch.root
        return orch._stage4_codex_fix(run_dry=ctx.run_dry, cwd=ctx.worktree_path), None

    if stage == "stage5_final_review":
        return (
            _run_stage5_review_with_retry(
                ctx,
                stage_index=stage_index,
                stage_total=stage_total,
            ),
            None,
        )

    return ctx.stage_result_cls(stage, False, {"error": "unknown stage"}), None


def _run_pipeline_stage_loop(
    ctx: PipelineRunContext,
    *,
    start_index: int,
    stop_after: int | None,
) -> dict[str, Any] | None:
    total_stages = len(ctx.pipeline_stages)
    for index, stage in enumerate(ctx.pipeline_stages[start_index:], start=start_index):
        ctx.state["pipeline"]["current_stage"] = stage
        ctx.orch.save_state(ctx.state)
        stage_no = index + 1
        LOGGER.info("[stage %s/%s] %s started", stage_no, total_stages, stage)
        stage_started = perf_counter()

        result, early_payload = _execute_stage(
            ctx,
            stage=stage,
            stage_index=stage_no,
            stage_total=total_stages,
        )
        if early_payload is not None:
            return early_payload

        stage_duration = round(perf_counter() - stage_started, 3)
        _record_stage_entry(
            ctx,
            result=result,
            stage_index=stage_no,
            stage_total=total_stages,
            stage_duration=stage_duration,
        )
        LOGGER.info(
            "[stage %s/%s] %s %s (%.3fs)",
            stage_no,
            total_stages,
            stage,
            "PASS" if result.ok else "FAIL",
            stage_duration,
        )

        if result.ok:
            if stage not in ctx.state["pipeline"]["completed_stages"]:
                ctx.state["pipeline"]["completed_stages"].append(stage)
        else:
            return _persist_pipeline_result(
                ctx,
                ok=False,
                status="failed",
                error=f"{stage} failed",
                include_stage_results=True,
            )

        ctx.orch.save_state(ctx.state)
        if stop_after is not None and index >= stop_after:
            return _persist_pipeline_result(
                ctx,
                ok=True,
                status=f"stopped_after_{index}",
                error=str(ctx.state["pipeline"].get("last_error", "") or ""),
                include_stage_results=True,
                extra={"stopped_after": index},
            )
    return None


def _finalize_pipeline_success(ctx: PipelineRunContext) -> dict[str, Any]:
    if ctx.worktree_branch and not ctx.run_dry:
        merged, merge_log = ctx.orch._merge_worktree_branch(ctx.worktree_branch)
        if not merged:
            return _persist_pipeline_result(
                ctx,
                ok=False,
                status="failed",
                error=f"merge failed: {merge_log}",
                include_stage_results=True,
            )
        ctx.orch._remove_worktree(path=ctx.worktree_path, branch=ctx.worktree_branch, force=False)
    return _persist_pipeline_result(
        ctx,
        ok=True,
        status="completed",
        error="",
        include_stage_results=True,
    )


def run_pipeline(
    orch: OrchestratorProtocol,
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
    run_id_raw = str(state["pipeline"].get("run_id", "") or "").strip() if resume else ""
    run_id = run_id_raw or _build_pipeline_run_id(task)
    lock_state = _acquire_pipeline_lock(orch, run_id=run_id, task=task, utc_now=utc_now)
    if not lock_state.acquired:
        return _pipeline_lock_conflict_payload(lock_state, mode=mode)

    ctx = _prepare_pipeline_context(
        orch,
        state=state,
        lock_state=lock_state,
        run_id=run_id,
        task=task,
        run_dry=run_dry,
        mode=mode,
        resume=resume,
        pipeline_stages=pipeline_stages,
        stage_result_cls=stage_result_cls,
        utc_now=utc_now,
    )

    preflight_payload = _run_preflight(ctx)
    if preflight_payload is not None:
        return preflight_payload

    start_index = 0
    if resume and ctx.state["pipeline"]["current_stage"] in pipeline_stages:
        start_index = pipeline_stages.index(ctx.state["pipeline"]["current_stage"])

    try:
        loop_payload = _run_pipeline_stage_loop(ctx, start_index=start_index, stop_after=stop_after)
        if loop_payload is not None:
            return loop_payload
        return _finalize_pipeline_success(ctx)
    except Exception as exc:
        return _persist_pipeline_result(
            ctx,
            ok=False,
            status="failed",
            error=str(exc),
            include_stage_results=True,
        )


def run_resume(
    orch: OrchestratorProtocol,
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


def _parse_worktree_list(porcelain_text: str) -> list[tuple[Path, str]]:
    entries: list[tuple[Path, str]] = []
    current_path: str | None = None
    current_branch = ""
    for line in porcelain_text.splitlines() + [""]:
        stripped = line.strip()
        if not stripped:
            if current_path:
                entries.append((Path(current_path), current_branch))
            current_path = None
            current_branch = ""
            continue
        if stripped.startswith("worktree "):
            current_path = stripped.split(" ", 1)[1].strip()
            continue
        if stripped.startswith("branch "):
            ref = stripped.split(" ", 1)[1].strip()
            prefix = "refs/heads/"
            current_branch = ref[len(prefix) :] if ref.startswith(prefix) else ref
    return entries


def _is_orphan_sandbox_entry(path: Path, branch: str) -> bool:
    return "omo-sandbox-" in str(path) or branch.startswith("omo-sandbox-")


def _remove_orphan_sandbox_entry(
    orch: OrchestratorProtocol,
    *,
    path: Path,
    branch: str,
) -> bool:
    proc = orch._run_subprocess(
        ["git", "-C", str(orch.root), "worktree", "remove", str(path), "--force"],
    )
    if proc.returncode != 0 and path.exists():
        orch._remove_worktree(path=path, branch=branch, force=True)
    if branch and branch.startswith("omo-sandbox-"):
        orch._run_subprocess(["git", "-C", str(orch.root), "branch", "-D", branch])
    return not path.exists()


def _cleanup_orphan_worktrees(
    orch: OrchestratorProtocol,
    *,
    removed: list[str],
    skipped: list[str],
    known_paths: set[str],
) -> None:
    proc = orch._run_subprocess(
        ["git", "-C", str(orch.root), "worktree", "list", "--porcelain"],
    )
    if proc.returncode != 0:
        LOGGER.warning("cleanup: failed to list git worktrees: %s", proc.stderr.strip())
        return

    for worktree_path, worktree_branch in _parse_worktree_list(proc.stdout or ""):
        resolved = orch._resolve_path(worktree_path)
        resolved_text = str(resolved)
        if resolved_text in known_paths:
            continue
        if not _is_orphan_sandbox_entry(resolved, worktree_branch):
            continue
        if _remove_orphan_sandbox_entry(orch, path=resolved, branch=worktree_branch):
            if resolved_text not in removed:
                removed.append(resolved_text)
            continue
        if resolved_text not in skipped:
            skipped.append(resolved_text)


def run_cleanup(orch: OrchestratorProtocol) -> dict[str, Any]:
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

    known_paths = {str(orch._resolve_path(sandbox))}
    if worktree_path is not None:
        known_paths.add(str(orch._resolve_path(worktree_path)))
    _cleanup_orphan_worktrees(
        orch,
        removed=removed,
        skipped=skipped,
        known_paths=known_paths,
    )

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
