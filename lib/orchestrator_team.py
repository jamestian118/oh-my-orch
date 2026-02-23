"""Team-mode command implementation for Orchestrator."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

from .agents import AgentRunResult

_BJT = ZoneInfo("Asia/Shanghai")


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
    orch._write_text(latest_dir / "team-summary.md", summary_content)
    run_meta = {
        "run_id": run_id,
        "topic": topic,
        "mode": mode,
        "ran_at": utc_now(),
        "stage0_ok": stage0.ok,
        "viewpoints_ok": viewpoints_ok,
        "viewpoint_failures": viewpoint_failures,
        "outputs": outputs,
        "summary_steps": summary_steps,
        "summary_file": str(summary_path),
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
            "ran_at": run_meta["ran_at"],
            "summary_file": str(summary_path),
            "meta_file": str(meta_path),
        },
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
    orch.save_state(state)
    team_ok = stage0.ok and viewpoints_ok and all(item["returncode"] == 0 for item in summary_steps)
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
    }
