"""Step 2 context 模块：预算计算 + 压缩管理。"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable

AGENT_PROFILES: dict[str, dict[str, int]] = {
    "claude": {"window": 200_000, "overhead": 18_000},
    "gemini": {"window": 1_000_000, "overhead": 5_000},
    "codex": {"window": 128_000, "overhead": 15_000},
}

SOFT_RATIO = 0.15
HARD_RATIO = 0.25
ABS_CAP = 50_000
COMPRESS_TARGET = 5_000


@dataclass(frozen=True)
class BudgetLimits:
    soft_limit: int
    hard_limit: int
    abs_cap: int = ABS_CAP


@dataclass(frozen=True)
class BudgetStatus:
    target_agent: str
    estimated_tokens: int
    limits: BudgetLimits
    warning: bool
    must_compress: bool


@dataclass(frozen=True)
class CompressionResult:
    summary: str
    compressed: bool
    used_fallback: bool
    dry_run: bool
    reason: str
    budget: BudgetStatus


Compressor = Callable[[str], str]


def _normalize_agent(target_agent: str) -> str:
    key = target_agent.strip().lower()
    if key not in AGENT_PROFILES:
        supported = ", ".join(sorted(AGENT_PROFILES))
        raise ValueError(f"Unsupported target_agent={target_agent!r}; expected one of: {supported}")
    return key


def estimate_tokens(text: str) -> int:
    """用字符长度粗估 token 数：len(text)//3。"""
    return len(text) // 3


def calculate_limits(target_agent: str) -> BudgetLimits:
    """按目标 agent 计算 soft/hard 预算阈值，并受 ABS_CAP 限制。"""
    agent = _normalize_agent(target_agent)
    profile = AGENT_PROFILES[agent]
    available_window = max(profile["window"] - profile["overhead"], 0)

    soft_limit = min(ABS_CAP, int(available_window * SOFT_RATIO))
    hard_limit = min(ABS_CAP, int(available_window * HARD_RATIO))
    if hard_limit < soft_limit:
        hard_limit = soft_limit
    return BudgetLimits(soft_limit=soft_limit, hard_limit=hard_limit)


class ContextManager:
    """管理 context 预算检测与压缩回退。"""

    def __init__(
        self,
        compressor: Compressor | None = None,
        compress_target: int = COMPRESS_TARGET,
    ) -> None:
        self._compressor = compressor or self._default_compressor
        self.compress_target = compress_target

    def inspect_budget(self, text: str, target_agent: str) -> BudgetStatus:
        agent = _normalize_agent(target_agent)
        limits = calculate_limits(agent)
        estimated = estimate_tokens(text)
        warning = estimated >= limits.soft_limit
        must_compress = estimated >= limits.hard_limit
        return BudgetStatus(
            target_agent=agent,
            estimated_tokens=estimated,
            limits=limits,
            warning=warning,
            must_compress=must_compress,
        )

    def should_compress(self, text: str, target_agent: str) -> bool:
        return self.inspect_budget(text, target_agent).must_compress

    def build_compression_prompt(self, text: str, target_agent: str) -> str:
        """构建 target-aware 压缩 prompt。"""
        agent = _normalize_agent(target_agent)
        focus_map = {
            "codex": (
                "重点写清需要修改的文件、目标行为、验收命令。保留任务拆解与执行顺序，减少抽象讨论。"
            ),
            "claude": "重点写清设计决策、约束条件、权衡与风险。",
            "gemini": "重点写清原始方案意图、变更范围、review 关注点。",
        }
        focus = focus_map[agent]

        return (
            "You are a context compressor for oh-my-orch.\n"
            f"Target agent: {agent}\n"
            f"Compress to around {self.compress_target} tokens.\n"
            "Keep high-signal technical details and drop repetition.\n"
            "Output Markdown with exactly these sections:\n"
            "1. Task Goal\n"
            "2. Key Decisions and Rationale\n"
            "3. Progress and Remaining Work\n"
            "4. Code Change Summary\n"
            f"Target-aware focus: {focus}\n\n"
            "Source context starts below:\n"
            "----- BEGIN CONTEXT -----\n"
            f"{text}\n"
            "----- END CONTEXT -----\n"
        )

    def compress_context(
        self,
        text: str,
        target_agent: str,
        *,
        dry_run: bool = False,
    ) -> CompressionResult:
        budget = self.inspect_budget(text, target_agent)
        if not budget.must_compress:
            return CompressionResult(
                summary=text,
                compressed=False,
                used_fallback=False,
                dry_run=dry_run,
                reason="below-hard-limit",
                budget=budget,
            )

        if dry_run:
            fallback = self._build_fallback_summary(text, budget, reason="dry-run")
            return CompressionResult(
                summary=fallback,
                compressed=False,
                used_fallback=True,
                dry_run=True,
                reason="dry-run",
                budget=budget,
            )

        prompt = self.build_compression_prompt(text, budget.target_agent)
        try:
            compressed = self._compressor(prompt).strip()
            if compressed:
                return CompressionResult(
                    summary=compressed,
                    compressed=True,
                    used_fallback=False,
                    dry_run=False,
                    reason="compressed",
                    budget=budget,
                )
            reason = "compressor-empty-output"
        except Exception as exc:  # pragma: no cover - 覆盖由单测驱动触发
            reason = f"compressor-failed: {exc.__class__.__name__}"

        fallback = self._build_fallback_summary(text, budget, reason=reason)
        return CompressionResult(
            summary=fallback,
            compressed=False,
            used_fallback=True,
            dry_run=False,
            reason=reason,
            budget=budget,
        )

    def _default_compressor(self, prompt: str) -> str:
        completed = subprocess.run(
            ["gemini", "-p", prompt],
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    def _build_fallback_summary(
        self,
        text: str,
        budget: BudgetStatus,
        *,
        reason: str,
    ) -> str:
        key_points = self._extract_key_points(text, max_items=5)
        file_refs = self._extract_file_refs(text, max_items=6)
        excerpt = self._excerpt(text, max_chars=900)
        task_goal = (
            key_points[0] if key_points else "No clear goal extracted; keep source files as truth."
        )

        key_points_md = (
            "\n".join(f"- {point}" for point in key_points[1:])
            or "- Keep `.ai/exec-plan.md` as source of truth."
        )
        file_refs_md = (
            "\n".join(f"- `{path}`" for path in file_refs) or "- No explicit file path found."
        )

        return (
            "# Context Compression Fallback\n\n"
            f"- target_agent: {budget.target_agent}\n"
            f"- reason: {reason}\n"
            f"- estimated_tokens: {budget.estimated_tokens}\n"
            f"- soft_limit: {budget.limits.soft_limit}\n"
            f"- hard_limit: {budget.limits.hard_limit}\n\n"
            "## Task Goal\n"
            f"{task_goal}\n\n"
            "## Key Decisions and Rationale\n"
            f"{key_points_md}\n\n"
            "## Progress and Remaining Work\n"
            "- Compression fallback was used; read authoritative files before execution.\n"
            "- Continue from current milestone and validate with repo verify/test commands.\n\n"
            "## Code Change Summary\n"
            f"{file_refs_md}\n\n"
            "## Excerpt\n"
            f"{excerpt}\n"
        )

    @staticmethod
    def _extract_key_points(text: str, *, max_items: int) -> list[str]:
        points: list[str] = []
        for line in text.splitlines():
            cleaned = " ".join(line.strip().split())
            if len(cleaned) < 10:
                continue
            points.append(cleaned.lstrip("-* "))
            if len(points) >= max_items:
                break
        if points:
            return points

        compact = " ".join(text.split()).strip()
        if compact:
            return [compact[:160]]
        return []

    @staticmethod
    def _extract_file_refs(text: str, *, max_items: int) -> list[str]:
        pattern = r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|md|json|yaml|yml|toml|sh)"
        matches = sorted(set(re.findall(pattern, text)))
        return matches[:max_items]

    @staticmethod
    def _excerpt(text: str, *, max_chars: int) -> str:
        compact = " ".join(text.split()).strip()
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars].rstrip() + " ..."
