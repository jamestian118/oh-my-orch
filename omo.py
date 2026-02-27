"""omo CLI entrypoint."""

from __future__ import annotations

import argparse
import importlib.metadata as importlib_metadata
import json
import logging
import sys
import tomllib
from pathlib import Path
from textwrap import dedent
from typing import Any

from lib.logging_config import configure_logging
from lib.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

_OUTPUT_CHOICES = ("json", "text")
_DIST_NAME = "oh-my-orch"


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _stringify_text_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    if value is None:
        return "null"
    return str(value)


def _print_text(payload: dict[str, Any]) -> None:
    rows = [(key, _stringify_text_value(payload[key])) for key in sorted(payload)]
    field_width = max(len("Field"), *(len(key) for key, _ in rows))
    lines = [
        f"{'Field'.ljust(field_width)} | Value",
        f"{'-' * field_width}-+-{'-' * len('Value')}",
    ]
    for key, value in rows:
        chunks = value.splitlines() or [""]
        lines.append(f"{key.ljust(field_width)} | {chunks[0]}")
        for chunk in chunks[1:]:
            lines.append(f"{' '.ljust(field_width)} | {chunk}")
    print("\n".join(lines))


def _emit_payload(payload: dict[str, Any], output: str) -> None:
    if output == "text":
        _print_text(payload)
        return
    _print_json(payload)


def _resolve_output_mode(raw: str) -> str:
    output = raw.strip().lower()
    if output not in _OUTPUT_CHOICES:
        raise ValueError(f"`--output` 仅支持 {','.join(_OUTPUT_CHOICES)}，收到 `{raw}`。")
    return output


def _parse_common_flags(tokens: list[str]) -> tuple[str, bool, bool, bool, bool, str, list[str]]:
    cwd = "."
    dry_run = False
    no_auto_confirm = False
    verbose = False
    debug = False
    output = "json"
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
        if token in {"-v", "--verbose"}:
            verbose = True
            i += 1
            continue
        if token == "--debug":
            debug = True
            i += 1
            continue
        if token == "--output":
            if i + 1 >= len(tokens):
                raise ValueError("`--output` 缺少参数，示例：`@codex chat 修复登录 --output text`")
            output = _resolve_output_mode(tokens[i + 1])
            i += 2
            continue
        if token.startswith("--output="):
            output = _resolve_output_mode(token.split("=", 1)[1])
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
                f"`@agent` 不支持参数 `{token}`。仅支持 `--cwd`/`--dry-run`/"
                "`--no-auto-confirm`/`--verbose`/`-v`/`--debug`/`--output`；"
                "若 prompt 以 `-` 开头，请使用 `--` 分隔。"
            )
        remaining.append(token)
        i += 1
    return cwd, dry_run, no_auto_confirm, verbose, debug, output, remaining


def _parse_at_agent(argv: list[str]) -> dict[str, Any] | None:
    if not argv or not argv[0].startswith("@"):
        return None
    agent = argv[0][1:].strip()
    if not agent:
        raise ValueError("agent 不能为空，例如 `@codex chat 实现功能`")
    cwd, dry_run, no_auto_confirm, verbose, debug, output, rest = _parse_common_flags(argv[1:])
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
        "verbose": verbose,
        "debug": debug,
        "output": output,
    }


def _resolve_cli_version() -> str:
    try:
        return importlib_metadata.version(_DIST_NAME)
    except importlib_metadata.PackageNotFoundError:
        pass

    pyproject = Path(__file__).resolve().with_name("pyproject.toml")
    try:
        parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return "unknown"
    version = parsed.get("project", {}).get("version")
    if isinstance(version, str) and version.strip():
        return version.strip()
    return "unknown"


def _add_output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        choices=_OUTPUT_CHOICES,
        default="json",
        help="output format",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omo",
        description="Orchestrate Claude Code, Codex CLI, and Gemini CLI tasks.",
        epilog=dedent(
            """\
            Examples:
              omo chat codex 修复登录 bug --cwd /path/to/repo
              omo pipeline 实现 OMO Phase 6 --dry-run --output text
              omo status --cwd /path/to/repo --output json
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_resolve_cli_version()}",
        help="show version and exit",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show stage-level progress logs"
    )
    parser.add_argument("--debug", action="store_true", help="show full subprocess commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat = subparsers.add_parser("chat", help="chat with one agent")
    chat.add_argument("agent", help="claude/codex/gemini or @claude")
    chat.add_argument("prompt", nargs="+", help="chat prompt")
    chat.add_argument("--cwd", default=".", help="project root")
    chat.add_argument("--dry-run", action="store_true", help="skip external CLI calls")
    chat.add_argument("--no-auto-confirm", action="store_true", help="disable auto confirm")
    _add_output_argument(chat)

    pipeline = subparsers.add_parser("pipeline", help="run pipeline flow")
    pipeline.add_argument("task", nargs="+", help="task description")
    pipeline.add_argument("--cwd", default=".", help="project root")
    pipeline.add_argument("--dry-run", action="store_true", help="skip external CLI calls")
    pipeline.add_argument("--stop-after", type=int, default=None, help="stop after stage index")
    pipeline.add_argument("--no-auto-confirm", action="store_true", help="disable auto confirm")
    _add_output_argument(pipeline)

    team = subparsers.add_parser("team", help="run team mode")
    team.add_argument("topic", nargs="+", help="discussion topic")
    team.add_argument("--cwd", default=".", help="project root")
    team.add_argument("--dry-run", action="store_true", help="skip external CLI calls")
    team.add_argument("--no-auto-confirm", action="store_true", help="disable auto confirm")
    _add_output_argument(team)

    status = subparsers.add_parser("status", help="show state")
    status.add_argument("--cwd", default=".", help="project root")
    _add_output_argument(status)

    history = subparsers.add_parser("history", help="show message history")
    history.add_argument("--cwd", default=".", help="project root")
    history.add_argument("--limit", type=int, default=20, help="history entries")
    _add_output_argument(history)

    compress = subparsers.add_parser("compress", help="compress context history")
    compress.add_argument("--cwd", default=".", help="project root")
    compress.add_argument("--dry-run", action="store_true", help="skip external CLI calls")
    compress.add_argument("--target-agent", default="codex", help="claude/codex/gemini")
    compress.add_argument("--max-chars", type=int, default=5000, help="max output chars")
    _add_output_argument(compress)

    reset = subparsers.add_parser("reset", help="reset local orchestration state")
    reset.add_argument("--cwd", default=".", help="project root")
    _add_output_argument(reset)

    resume = subparsers.add_parser("resume", help="resume interrupted pipeline")
    resume.add_argument("--cwd", default=".", help="project root")
    resume.add_argument("--dry-run", action="store_true", help="resume in dry-run mode")
    resume.add_argument("--no-auto-confirm", action="store_true", help="disable auto confirm")
    _add_output_argument(resume)

    cleanup = subparsers.add_parser("cleanup", help="cleanup residual worktree/sandbox")
    cleanup.add_argument("--cwd", default=".", help="project root")
    _add_output_argument(cleanup)

    return parser


def _make_orchestrator(
    cwd: str,
    dry_run: bool,
    no_auto_confirm: bool,
    verbose: bool = False,
    debug: bool = False,
) -> Orchestrator:
    return Orchestrator(
        root_dir=cwd,
        dry_run=dry_run,
        verbose=verbose,
        debug=debug,
        auto_confirm=not no_auto_confirm,
    )


def _dispatch(ns: argparse.Namespace) -> dict[str, Any]:
    command = ns.command
    dry_run = bool(getattr(ns, "dry_run", False))
    no_auto_confirm = bool(getattr(ns, "no_auto_confirm", False))
    verbose = bool(getattr(ns, "verbose", False))
    debug = bool(getattr(ns, "debug", False))
    orch = _make_orchestrator(
        getattr(ns, "cwd", "."),
        dry_run,
        no_auto_confirm,
        verbose=verbose,
        debug=debug,
    )

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
    bootstrap_verbose = any(token in {"-v", "--verbose"} for token in args)
    bootstrap_debug = "--debug" in args
    configure_logging(verbose=bootstrap_verbose, debug=bootstrap_debug)
    logger.debug("omo bootstrap argv=%s", args)
    try:
        at_call = _parse_at_agent(args)
        if at_call is not None:
            configure_logging(verbose=at_call["verbose"], debug=at_call["debug"])
            orch = _make_orchestrator(
                at_call["cwd"],
                at_call["dry_run"],
                at_call["no_auto_confirm"],
                verbose=at_call["verbose"],
                debug=at_call["debug"],
            )
            payload = orch.chat(
                agent=at_call["agent"],
                prompt=at_call["prompt"],
                dry_run=at_call["dry_run"],
            )
            _emit_payload(payload, at_call["output"])
            return _resolve_exit_code(payload, ok_default=False)

        parser = _build_parser()
        try:
            ns = parser.parse_args(args)
        except SystemExit as exc:
            return int(exc.code)
        configure_logging(verbose=bool(ns.verbose), debug=bool(ns.debug))
        payload = _dispatch(ns)
        _emit_payload(payload, ns.output)
        return _resolve_exit_code(payload, ok_default=True)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
