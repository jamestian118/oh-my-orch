"""omo CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from lib.orchestrator import Orchestrator


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _parse_common_flags(tokens: list[str]) -> tuple[str, bool, bool, list[str]]:
    cwd = "."
    dry_run = False
    no_auto_confirm = False
    remaining: list[str] = []

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--":
            remaining.extend(tokens[i + 1 :])
            break
        if token == "--dry-run":
            dry_run = True
            i += 1
            continue
        if token == "--no-auto-confirm":
            no_auto_confirm = True
            i += 1
            continue
        if token == "--cwd":
            if i + 1 >= len(tokens):
                raise ValueError(
                    "`--cwd` 缺少路径参数。示例：`@codex chat 修复登录 --cwd /path/to/repo`"
                )
            cwd = tokens[i + 1]
            i += 2
            continue
        if token.startswith("--cwd="):
            cwd = token.split("=", 1)[1].strip()
            if not cwd:
                raise ValueError(
                    "`--cwd` 缺少路径参数。示例：`@codex chat 修复登录 --cwd /path/to/repo`"
                )
            i += 1
            continue
        if token.startswith("-"):
            raise ValueError(
                f"`@agent` 不支持参数 `{token}`。仅支持 `--cwd`/`--dry-run`/`--no-auto-confirm`；"
                "若 prompt 以 `-` 开头，请使用 `--` 分隔。"
            )
        remaining.append(token)
        i += 1
    return cwd, dry_run, no_auto_confirm, remaining


def _parse_at_agent(argv: list[str]) -> dict[str, Any] | None:
    if not argv or not argv[0].startswith("@"):
        return None
    agent = argv[0][1:].strip()
    if not agent:
        raise ValueError("agent 不能为空，例如 `@codex chat 实现功能`")
    cwd, dry_run, no_auto_confirm, rest = _parse_common_flags(argv[1:])
    if rest and rest[0] in {
        "pipeline",
        "team",
        "status",
        "history",
        "compress",
        "reset",
        "resume",
        "cleanup",
    }:
        command = rest[0]
        raise ValueError(
            f"`@{agent}` 快捷语法仅支持 `chat`。"
            f"检测到子命令 `{command}`，请改用 `omo {command} ...`"
        )
    if rest and rest[0] == "chat":
        rest = rest[1:]
    prompt = " ".join(rest).strip()
    if not prompt:
        raise ValueError(
            f"`@{agent}` 缺少 prompt。用法：`@{agent} chat 你的问题` 或 `omo chat {agent} 你的问题`"
        )
    return {
        "agent": agent,
        "prompt": prompt,
        "cwd": cwd,
        "dry_run": dry_run,
        "no_auto_confirm": no_auto_confirm,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat = subparsers.add_parser("chat", help="chat with one agent")
    chat.add_argument("agent", help="claude/codex/gemini or @claude")
    chat.add_argument("prompt", nargs="+", help="chat prompt")
    chat.add_argument("--cwd", default=".", help="project root")
    chat.add_argument("--dry-run", action="store_true", help="skip external CLI calls")
    chat.add_argument("--no-auto-confirm", action="store_true", help="disable auto confirm")

    pipeline = subparsers.add_parser("pipeline", help="run pipeline flow")
    pipeline.add_argument("task", nargs="+", help="task description")
    pipeline.add_argument("--cwd", default=".", help="project root")
    pipeline.add_argument("--dry-run", action="store_true", help="skip external CLI calls")
    pipeline.add_argument("--stop-after", type=int, default=None, help="stop after stage index")
    pipeline.add_argument("--no-auto-confirm", action="store_true", help="disable auto confirm")

    team = subparsers.add_parser("team", help="run team mode")
    team.add_argument("topic", nargs="+", help="discussion topic")
    team.add_argument("--cwd", default=".", help="project root")
    team.add_argument("--dry-run", action="store_true", help="skip external CLI calls")
    team.add_argument("--no-auto-confirm", action="store_true", help="disable auto confirm")

    status = subparsers.add_parser("status", help="show state")
    status.add_argument("--cwd", default=".", help="project root")

    history = subparsers.add_parser("history", help="show message history")
    history.add_argument("--cwd", default=".", help="project root")
    history.add_argument("--limit", type=int, default=20, help="history entries")

    compress = subparsers.add_parser("compress", help="compress context history")
    compress.add_argument("--cwd", default=".", help="project root")
    compress.add_argument("--dry-run", action="store_true", help="skip external CLI calls")
    compress.add_argument("--target-agent", default="codex", help="claude/codex/gemini")
    compress.add_argument("--max-chars", type=int, default=5000, help="max output chars")

    reset = subparsers.add_parser("reset", help="reset local orchestration state")
    reset.add_argument("--cwd", default=".", help="project root")

    resume = subparsers.add_parser("resume", help="resume interrupted pipeline")
    resume.add_argument("--cwd", default=".", help="project root")
    resume.add_argument("--dry-run", action="store_true", help="resume in dry-run mode")
    resume.add_argument("--no-auto-confirm", action="store_true", help="disable auto confirm")

    cleanup = subparsers.add_parser("cleanup", help="cleanup residual worktree/sandbox")
    cleanup.add_argument("--cwd", default=".", help="project root")

    return parser


def _make_orchestrator(cwd: str, dry_run: bool, no_auto_confirm: bool) -> Orchestrator:
    return Orchestrator(root_dir=cwd, dry_run=dry_run, auto_confirm=not no_auto_confirm)


def _dispatch(ns: argparse.Namespace) -> dict[str, Any]:
    command = ns.command
    dry_run = bool(getattr(ns, "dry_run", False))
    no_auto_confirm = bool(getattr(ns, "no_auto_confirm", False))
    orch = _make_orchestrator(getattr(ns, "cwd", "."), dry_run, no_auto_confirm)

    if command == "chat":
        return orch.chat(
            agent=ns.agent,
            prompt=" ".join(ns.prompt).strip(),
            dry_run=dry_run,
        )
    if command == "pipeline":
        return orch.pipeline(
            task=" ".join(ns.task).strip(),
            dry_run=dry_run,
            stop_after=ns.stop_after,
        )
    if command == "team":
        return orch.team(topic=" ".join(ns.topic).strip(), dry_run=dry_run)
    if command == "status":
        return orch.status()
    if command == "history":
        return {"ok": True, "command": "history", "history": orch.history(limit=ns.limit)}
    if command == "compress":
        return orch.compress(
            target_agent=ns.target_agent,
            max_chars=ns.max_chars,
            dry_run=dry_run,
        )
    if command == "reset":
        return orch.reset()
    if command == "resume":
        return orch.resume(dry_run=dry_run)
    if command == "cleanup":
        return orch.cleanup()
    raise ValueError(f"unsupported command: {command}")


def _resolve_exit_code(payload: dict[str, Any], *, ok_default: bool) -> int:
    exit_code = payload.get("exit_code")
    if type(exit_code) is int:
        return exit_code
    return 0 if bool(payload.get("ok", ok_default)) else 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    try:
        at_call = _parse_at_agent(args)
        if at_call is not None:
            orch = _make_orchestrator(
                at_call["cwd"],
                at_call["dry_run"],
                at_call["no_auto_confirm"],
            )
            payload = orch.chat(
                agent=at_call["agent"],
                prompt=at_call["prompt"],
                dry_run=at_call["dry_run"],
            )
            _print_json(payload)
            return _resolve_exit_code(payload, ok_default=False)

        parser = _build_parser()
        ns = parser.parse_args(args)
        payload = _dispatch(ns)
        _print_json(payload)
        return _resolve_exit_code(payload, ok_default=True)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
