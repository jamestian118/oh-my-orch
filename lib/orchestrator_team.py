"""Team-mode command implementation for Orchestrator."""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

from .agents import AgentRunResult
from .decision_arbiter import arbiter
from .run_registry import ensure_project_registry

_BJT = ZoneInfo("Asia/Shanghai")
_RISK_HINTS = (
    "risk",
    "风险",
    "security",
    "critical",
    "high risk",
    "low risk",
    "breaking",
    "severe",
    "data-loss",
)
_ACTION_HINTS = (
    "action",
    "建议",
    "修复",
    "implement",
    "add ",
    "update",
    "migrate",
    "refactor",
    "rollback",
    "步骤",
    "todo",
    "plan",
)
_VERIFY_HINTS = ("verify", "verification", "验证", "测试", "test")
_VERIFY_PREFIXES = (
    "./",
    "scripts/",
    "pytest",
    "python ",
    "python3 ",
    "npm ",
    "pnpm ",
    "yarn ",
    "make ",
    "go test",
    "cargo test",
    "uv ",
    "bash ",
    "sh ",
    "node ",
)


def _arbiter_gate_mode() -> str:
    raw = os.getenv("OMO_TEAM_ARBITER_GATE", "").strip().lower()
    if raw in {"1", "true", "strict"}:
        return "strict"
    if raw in {"0", "false", "off"}:
        return "off"
    if raw in {"", "soft"}:
        return "soft"
    return "soft"


def _readable_keywords(text: str) -> str:
    """提取可读关键词：保留中英文/数字，其它符号折叠为连字符。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text, flags=re.UNICODE).strip("-_")
    cleaned = re.sub(r"-{2,}", "-", cleaned).replace("_", "-")
    return cleaned.lower()


def _topic_summary(topic: str, slug: Callable[[str], str], *, max_len: int = 24) -> str:
    """生成 run 梗概：topic 像路径时优先 basename，再回退原 topic。"""
    normalized = topic.strip().replace("\\", "/")
    candidate = normalized.rstrip("/").split("/")[-1] if "/" in normalized else normalized
    candidate = candidate or normalized
    summary = _readable_keywords(candidate)
    if not summary:
        summary = _readable_keywords(topic)
    if not summary:
        summary = slug(candidate)
    if not summary:
        summary = slug(topic)
    return (summary or "team")[:max_len]


def _build_team_run_id(topic: str, slug: Callable[[str], str]) -> str:
    now_bj = datetime.now(_BJT)
    date_part = now_bj.strftime("%Y%m%d")
    time_part = now_bj.strftime("%H%M%S")
    summary_part = _topic_summary(topic, slug)
    # 时间到秒便于阅读；附加短哈希降低同秒冲突概率。
    short_hash = uuid4().hex[:8]
    return f"{date_part}-{time_part}-{summary_part}-{short_hash}"


def _registry_root(orch: Any) -> Path:
    project_registry = ensure_project_registry(root=orch.root, state_path=orch.state_path)
    root_path = Path(project_registry).parent
    if not root_path.is_absolute():
        root_path = (orch.root / root_path).resolve(strict=False)
    root_path.mkdir(parents=True, exist_ok=True)
    return root_path


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _strip_md_list_prefix(text: str) -> str:
    stripped = re.sub(r"^\s*[-*+]\s+", "", text)
    stripped = re.sub(r"^\s*\d+[.)]\s+", "", stripped)
    return stripped.strip()


def _dedupe_keep_order(items: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return deduped


def _normalize_to_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, (list, tuple, set)):
        return _dedupe_keep_order([str(item).strip() for item in value if str(item).strip()])
    return []


def _looks_like_verification_command(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if lowered.startswith(_VERIFY_PREFIXES):
        return True
    return any(hint in lowered for hint in _VERIFY_HINTS)


def _extract_model_lists(stdout_text: str) -> tuple[list[str], list[str], list[str]]:
    actions: list[str] = []
    risks: list[str] = []
    verification: list[str] = []
    for raw_line in stdout_text.splitlines():
        line = _strip_md_list_prefix(raw_line)
        if not line:
            continue

        lower_line = line.lower()
        inline_code = [code.strip() for code in re.findall(r"`([^`]+)`", line) if code.strip()]
        for snippet in inline_code:
            if _looks_like_verification_command(snippet):
                verification.append(snippet)

        if _looks_like_verification_command(line):
            verification.append(line)

        if any(hint in lower_line for hint in _RISK_HINTS):
            risks.append(line)
            continue
        if any(hint in lower_line for hint in _ACTION_HINTS):
            actions.append(line)
            continue
        if any(hint in lower_line for hint in _VERIFY_HINTS):
            verification.append(line)

    return (
        _dedupe_keep_order(actions),
        _dedupe_keep_order(risks),
        _dedupe_keep_order(verification),
    )


def _infer_model_status(stdout_text: str, failure_reason: str, returncode: int) -> str:
    if returncode != 0 or failure_reason.strip():
        return "fail"
    lowered = stdout_text.lower()
    if any(token in lowered for token in ("blocked", "blocker", "failed", "failure", "error")):
        return "blocked"
    if stdout_text.strip():
        return "success"
    return "unknown"


def _build_model_decision(
    *,
    model: str,
    stdout_text: str,
    failure_reason: str,
    returncode: int,
) -> dict[str, Any]:
    structured_payload: dict[str, Any] | None = None
    stripped_stdout = stdout_text.strip()
    if stripped_stdout.startswith("{") and stripped_stdout.endswith("}"):
        try:
            parsed = json.loads(stripped_stdout)
            if isinstance(parsed, dict):
                structured_payload = parsed
        except json.JSONDecodeError:
            structured_payload = None

    if structured_payload is not None:
        actions = _normalize_to_str_list(structured_payload.get("actions"))
        risks = _normalize_to_str_list(structured_payload.get("risks"))
        verification = _normalize_to_str_list(structured_payload.get("verification"))
        status = str(structured_payload.get("status", "")).strip() or _infer_model_status(
            stdout_text, failure_reason, returncode
        )
    else:
        actions, risks, verification = _extract_model_lists(stdout_text)
        status = _infer_model_status(stdout_text, failure_reason, returncode)

    if failure_reason.strip():
        risks.append(f"viewpoint-failure: {failure_reason.strip()}")

    risks = _dedupe_keep_order(risks) or ["low"]
    verification = _dedupe_keep_order(verification) or ["./scripts/verify"]
    return {
        "model": model,
        "status": status,
        "actions": actions,
        "risks": risks,
        "verification": verification,
    }


def _arbiter_ask_reason(arbiter_result: dict[str, Any]) -> str:
    winner = str(arbiter_result.get("winner", "unknown"))
    conflicts = [str(item) for item in arbiter_result.get("conflicts", [])]
    conflict_text = ", ".join(conflicts) if conflicts else "no-explicit-conflicts"
    confidence = arbiter_result.get("confidence", {})
    joint = confidence.get("joint") if isinstance(confidence, dict) else None
    if isinstance(joint, (int, float)):
        return f"ask=true; winner={winner}; joint={joint:.4f}; conflicts={conflict_text}"
    return f"ask=true; winner={winner}; conflicts={conflict_text}"


def _persist_team_registry(
    orch: Any,
    *,
    run_id: str,
    mode: str,
    status: str,
    topic: str,
    ran_at: str,
    outputs: Sequence[dict[str, Any]],
    summary_path: Path,
    meta_path: Path,
    viewpoints_ok: bool,
    viewpoint_failures: Sequence[str],
    agents_dir: Path,
    team_agents: Sequence[str],
) -> None:
    registry_root = _registry_root(orch)
    team_run_dir = registry_root / "runs" / "team" / run_id
    run_file = team_run_dir / "run.json"
    artifacts_file = team_run_dir / "artifacts.json"
    decisions_file = team_run_dir / "decisions.jsonl"
    latest_file = registry_root / "latest" / "team.json"

    run_payload = {
        "schema_version": 1,
        "run_id": run_id,
        "kind": "team",
        "mode": mode,
        "status": status,
        "topic": topic,
        "ran_at": ran_at,
        "outputs_count": len(outputs),
        "summary_file": str(summary_path),
        "meta_file": str(meta_path),
        "viewpoints_ok": viewpoints_ok,
    }
    artifacts_payload = {
        "run_id": run_id,
        "kind": "team",
        "summary_file": str(summary_path),
        "meta_file": str(meta_path),
        "artifacts": {
            "team-summary.md": str(summary_path),
            "meta.json": str(meta_path),
            "agents/*.md": [str(agents_dir / f"{agent}.md") for agent in team_agents],
        },
    }
    decisions_payload = [
        {
            "ts": ran_at,
            "run_id": run_id,
            "kind": "team",
            "decision": "viewpoint_validation",
            "ok": viewpoints_ok,
            "failure_count": len(viewpoint_failures),
            "failures": list(viewpoint_failures),
        },
        {
            "ts": ran_at,
            "run_id": run_id,
            "kind": "team",
            "decision": "final_status",
            "status": status,
            "outputs_count": len(outputs),
        },
    ]
    latest_payload = {
        "schema_version": 1,
        "run_id": run_id,
        "kind": "team",
        "mode": mode,
        "status": status,
        "ran_at": ran_at,
        "run_file": str(run_file),
        "artifacts_file": str(artifacts_file),
        "decisions_file": str(decisions_file),
        "summary_file": str(summary_path),
        "meta_file": str(meta_path),
    }

    orch._write_json(run_file, run_payload)
    orch._write_json(artifacts_file, artifacts_payload)
    _write_jsonl(decisions_file, decisions_payload)
    orch._write_json(latest_file, latest_payload)


def run_team(
    orch: Any,
    *,
    topic: str,
    dry_run: bool | None = None,
    team_agents: Sequence[str],
    slug: Callable[[str], str],
    utc_now: Callable[[], str],
) -> dict[str, Any]:
    run_dry, mode = orch._resolve_mode(dry_run)
    topic = topic.strip()
    if not topic:
        raise ValueError("team topic 不能为空")

    stage0 = orch._stage0_project_brief(topic, run_dry=run_dry, cwd=orch.root)
    run_id = _build_team_run_id(topic, slug)
    team_root = orch.ai_dir / "team"
    run_dir = team_root / "runs" / run_id
    latest_dir = team_root / "latest"
    agents_dir = run_dir / "agents"
    outputs: list[dict[str, Any]] = []
    agent_notes: dict[str, str] = {}
    viewpoint_failures: list[str] = []
    viewpoint_stdout: dict[str, str] = {}
    prompts = {
        "claude": "从架构设计和长期维护角度讨论。",
        "codex": "从实现复杂度和开发效率角度分析。",
        "gemini": "从成本、性能、团队规模角度分析。",
    }

    agent_prompts = {agent: f"{topic}\n\n{prompts[agent]}" for agent in team_agents}
    viewpoint_results: dict[str, AgentRunResult] = {}

    def _viewpoint_exception_result(agent: str, message: str) -> AgentRunResult:
        return AgentRunResult(
            tool=agent,
            mode="non_interactive",
            command=(),
            returncode=1,
            stdout="",
            stderr=message,
            dry_run=run_dry,
            cwd=str(orch.root),
        )

    try:
        with ThreadPoolExecutor(max_workers=len(team_agents)) as executor:
            future_to_agent = {
                executor.submit(
                    orch._run_agent,
                    agent=agent,
                    prompt=agent_prompts[agent],
                    cwd=orch.root,
                    interactive=False,
                    run_dry=run_dry,
                ): agent
                for agent in team_agents
            }
            for future in as_completed(future_to_agent):
                agent = future_to_agent[future]
                try:
                    viewpoint_results[agent] = future.result()
                except Exception as exc:
                    viewpoint_results[agent] = _viewpoint_exception_result(
                        agent,
                        f"viewpoint execution exception: {type(exc).__name__}: {exc}",
                    )
    except Exception as exc:
        scheduler_failure = f"viewpoint scheduler exception: {type(exc).__name__}: {exc}"
        for agent in team_agents:
            viewpoint_results.setdefault(
                agent,
                _viewpoint_exception_result(agent, scheduler_failure),
            )

    for agent in team_agents:
        result = viewpoint_results.get(agent)
        if result is None:
            result = _viewpoint_exception_result(
                agent,
                "viewpoint internal error: missing result from scheduler",
            )
        stdout_text = result.stdout.strip()
        if run_dry and not stdout_text:
            stdout_text = (
                f"# {agent} viewpoint (dry-run)\n\n"
                f"- topic: {topic}\n"
                "- mode: dry-run\n"
                "- note: deterministic dry-run placeholder\n"
                f"- focus: {prompts[agent]}\n"
            )
        viewpoint_stdout[agent] = stdout_text
        stdout_empty = not bool(stdout_text.strip())
        stdout_len = len(stdout_text.strip())
        stderr_len = len(result.stderr.strip())
        failure_reasons: list[str] = []
        if result.returncode != 0:
            failure_reasons.append(f"returncode={result.returncode}")
        if stdout_empty:
            failure_reasons.append("stdout empty")
        failed = bool(failure_reasons)
        failure_reason = "; ".join(failure_reasons)
        if failed:
            viewpoint_failures.append(f"{agent}: {failure_reason}")

        output_path = agents_dir / f"{agent}.md"
        note = stdout_text.strip() or (
            f"# {agent} output\n\n"
            f"- topic: {topic}\n"
            f"- mode: {mode}\n"
            "- note: stdout empty\n"
            f"- returncode: {result.returncode}\n"
        )
        orch._write_text(output_path, note)
        agent_notes[agent] = note
        outputs.append(
            {
                "agent": agent,
                "returncode": result.returncode,
                "dry_run": result.dry_run,
                "stdout_empty": stdout_empty,
                "stdout_len": stdout_len,
                "stderr_len": stderr_len,
                "failed": failed,
                "failure_reason": failure_reason,
                "output_file": str(output_path),
            }
        )

    merged_notes = "\n\n".join(f"## {agent}\n{agent_notes[agent]}" for agent in team_agents)
    viewpoints_ok = len(viewpoint_failures) == 0
    failure_reason_text = "; ".join(viewpoint_failures)
    summary_path = run_dir / "team-summary.md"
    summary_steps: list[dict[str, Any]]
    if viewpoints_ok:
        summary_prompt = (
            "你是 team 模式的唯一总结 agent。请基于三方原始观点产出一次性最终总结。"
            "输出必须是 Markdown，并严格包含以下结构：\n"
            "1) 共同点（Common Ground）：逐条列出，且每条必须标注支持度 3/3 或 2/3。\n"
            "2) 不同点对比表（Differences Table）：用表格输出，列至少包含"
            " `议题 | Claude | Codex | Gemini | 影响/风险`。\n"
            "3) 优先级修复建议（Priority Fixes）：按 P0/P1/P2 分级，每项写明"
            " `建议动作 | 原因 | 预期收益 | owner 建议`。\n"
            "4) 最小验证命令（Minimal Verification Commands）：给 1-3 条可直接执行命令，"
            "用于验证推荐路径已落地。\n"
            "5) 结论：给出推荐路径（1-2 条）和不推荐路径（1-2 条），结论必须可执行。\n"
            f"\nTopic: {topic}\n"
            "\nRaw viewpoints:\n"
            f"{merged_notes}\n"
        )
        team_summary = orch._run_agent(
            agent="gemini",
            prompt=summary_prompt,
            cwd=orch.root,
            interactive=False,
            run_dry=run_dry,
        )
        summary_stdout = team_summary.stdout.strip()
        summary_content = summary_stdout or (
            "# Team Summary\n\n"
            f"- topic: {topic}\n"
            f"- mode: {mode}\n"
            "- note: team_summary stdout empty\n\n"
            "## Raw viewpoints\n"
            f"{merged_notes}\n"
        )
        orch._write_text(summary_path, summary_content)
        summary_steps = [
            {
                "step": "team_summary",
                "agent": "gemini",
                "returncode": team_summary.returncode,
                "dry_run": team_summary.dry_run,
                "stdout_empty": not bool(summary_stdout),
                "stdout_len": len(summary_stdout),
                "stderr_len": len(team_summary.stderr.strip()),
                "skipped": False,
                "output_file": str(summary_path),
            }
        ]
    else:
        summary_content = (
            "# Team Summary\n\n"
            f"- topic: {topic}\n"
            f"- mode: {mode}\n"
            "- skipped: true\n"
            "- reason: viewpoint stage failed\n"
            f"- details: {failure_reason_text}\n\n"
            "## Deterministic Fallback\n"
            "- single-step `team_summary` skipped to avoid false success.\n"
        )
        orch._write_text(summary_path, summary_content)
        summary_steps = [
            {
                "step": "team_summary",
                "agent": "gemini",
                "returncode": -1,
                "dry_run": run_dry,
                "stdout_empty": False,
                "stdout_len": len(summary_content),
                "stderr_len": 0,
                "skipped": True,
                "skip_reason": f"viewpoint stage failed: {failure_reason_text}",
                "output_file": str(summary_path),
            }
        ]

    output_by_agent = {str(item.get("agent", "")): item for item in outputs}
    codex_output = output_by_agent.get("codex", {})
    gemini_output = output_by_agent.get("gemini", {})
    codex_result = viewpoint_results.get("codex")
    gemini_result = viewpoint_results.get("gemini")
    if codex_result is None:
        codex_result = _viewpoint_exception_result(
            "codex",
            "viewpoint internal error: missing result from scheduler",
        )
    if gemini_result is None:
        gemini_result = _viewpoint_exception_result(
            "gemini",
            "viewpoint internal error: missing result from scheduler",
        )

    codex_decision = _build_model_decision(
        model="codex",
        stdout_text=viewpoint_stdout.get("codex", codex_result.stdout.strip()),
        failure_reason=str(codex_output.get("failure_reason", "")),
        returncode=int(codex_output.get("returncode", codex_result.returncode)),
    )
    gemini_decision = _build_model_decision(
        model="gemini",
        stdout_text=viewpoint_stdout.get("gemini", gemini_result.stdout.strip()),
        failure_reason=str(gemini_output.get("failure_reason", "")),
        returncode=int(gemini_output.get("returncode", gemini_result.returncode)),
    )
    arbiter_result = arbiter(codex_decision, gemini_decision)

    decisions_dir = run_dir / "decisions"
    context_pack_path = decisions_dir / "context-pack.json"
    codex_decision_path = decisions_dir / "codex.json"
    gemini_decision_path = decisions_dir / "gemini.json"
    arbiter_path = decisions_dir / "arbiter.json"
    ask_path = decisions_dir / "ask.json"

    context_pack = {
        "run_id": run_id,
        "topic": topic,
        "mode": mode,
        "team_agents": list(team_agents),
        "viewpoints_ok": viewpoints_ok,
    }
    orch._write_json(context_pack_path, context_pack)
    orch._write_json(codex_decision_path, codex_decision)
    orch._write_json(gemini_decision_path, gemini_decision)
    orch._write_json(arbiter_path, arbiter_result)

    ask_payload: dict[str, Any] | None = None
    if bool(arbiter_result.get("ask")):
        ask_payload = {
            "reason": _arbiter_ask_reason(arbiter_result),
            "conflicts": list(arbiter_result.get("conflicts", [])),
            "winner": arbiter_result.get("winner", ""),
            "confidence": dict(arbiter_result.get("confidence", {})),
        }
        orch._write_json(ask_path, ask_payload)

    gate_mode = _arbiter_gate_mode()
    gate_enabled = gate_mode == "strict"
    gate_failed = gate_enabled and bool(arbiter_result.get("ask"))
    gate_reason = ""
    if gate_failed:
        gate_reason = (
            ask_payload["reason"]
            if ask_payload is not None
            else _arbiter_ask_reason(arbiter_result)
        )
        viewpoint_failures.append(f"arbiter_gate: {gate_reason}")

    orch._write_text(latest_dir / "team-summary.md", summary_content)
    viewpoints_ok = len(viewpoint_failures) == 0
    team_ok = stage0.ok and viewpoints_ok and all(item["returncode"] == 0 for item in summary_steps)
    run_status = "completed" if team_ok else "failed"
    ran_at = utc_now()
    arbiter_payload = {
        **arbiter_result,
        "codex": codex_decision,
        "gemini": gemini_decision,
        "context_pack_file": str(context_pack_path),
        "codex_file": str(codex_decision_path),
        "gemini_file": str(gemini_decision_path),
        "arbiter_file": str(arbiter_path),
        "ask_file": str(ask_path) if ask_payload is not None else "",
        "ask_payload": ask_payload,
        "gate_mode": gate_mode,
        "gate_enabled": gate_enabled,
        "gate_failed": gate_failed,
        "gate_reason": gate_reason,
    }
    run_meta = {
        "run_id": run_id,
        "topic": topic,
        "mode": mode,
        "ran_at": ran_at,
        "stage0_ok": stage0.ok,
        "viewpoints_ok": viewpoints_ok,
        "viewpoint_failures": viewpoint_failures,
        "outputs": outputs,
        "summary_steps": summary_steps,
        "summary_file": str(summary_path),
        "arbiter": arbiter_payload,
    }
    meta_path = run_dir / "meta.json"
    orch._write_json(meta_path, run_meta)
    latest_meta_path = latest_dir / "run.json"
    orch._write_json(
        latest_meta_path,
        {
            "run_id": run_id,
            "topic": topic,
            "mode": mode,
            "ran_at": ran_at,
            "summary_file": str(summary_path),
            "meta_file": str(meta_path),
        },
    )
    _persist_team_registry(
        orch,
        run_id=run_id,
        mode=mode,
        status=run_status,
        topic=topic,
        ran_at=ran_at,
        outputs=outputs,
        summary_path=summary_path,
        meta_path=meta_path,
        viewpoints_ok=viewpoints_ok,
        viewpoint_failures=viewpoint_failures,
        agents_dir=agents_dir,
        team_agents=team_agents,
    )

    state = orch.load_state()
    state["last_action"] = "team"
    state["team"]["topic"] = topic
    state["team"]["ran_at"] = utc_now()
    state["team"]["last_mode"] = mode
    state["team"]["outputs"] = outputs
    state["team"]["summary_steps"] = summary_steps
    state["team"]["run_dir"] = str(run_dir)
    state["team"]["summary_file"] = str(summary_path)
    state["team"]["arbiter"] = arbiter_payload
    orch.save_state(state)
    return {
        "ok": team_ok,
        "command": "team",
        "mode": mode,
        "topic": topic,
        "agent_count": len(outputs),
        "outputs": outputs,
        "summary_steps": summary_steps,
        "run_dir": str(run_dir),
        "summary_file": str(summary_path),
        "latest_summary_file": str(latest_dir / "team-summary.md"),
        "meta_file": str(meta_path),
        "arbiter": arbiter_payload,
    }
