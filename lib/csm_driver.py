"""Standalone subprocess driver for CSM data access."""

from __future__ import annotations

import json
import sys
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _to_summary(item: Any) -> dict[str, Any]:
    return {
        "session_id": item.session_id,
        "tool": item.tool_type.label,
        "tool_slug": item.tool_type.name.lower(),
        "project": item.project,
        "first_message": item.first_display,
        "last_message": item.last_display,
        "message_count": item.message_count,
        "custom_name": item.custom_name or "",
    }


def _to_detail(item: Any) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for msg in item.messages:
        role = getattr(msg, "role", "")
        if role in {"user", "assistant"}:
            messages.append(
                {
                    "role": role,
                    "content": getattr(msg, "content", ""),
                    "timestamp": getattr(msg, "timestamp", ""),
                    "uuid": getattr(msg, "uuid", ""),
                }
            )
    return {
        "session_id": item.session_id,
        "tool": item.tool_type.label,
        "tool_slug": item.tool_type.name.lower(),
        "project": item.project,
        "cwd": item.cwd,
        "git_branch": item.git_branch,
        "model_provider": item.model_provider,
        "files_changed": item.files_changed,
        "commands_run": item.commands_run,
        "errors": item.errors,
        "messages": messages,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        _emit({"ok": False, "error": "missing request payload"})
        return 1

    try:
        req = json.loads(argv[1])
    except json.JSONDecodeError as exc:
        _emit({"ok": False, "error": f"invalid request payload: {exc}"})
        return 1

    root = str(req.get("root", "") or "").strip()
    if not root:
        _emit({"ok": False, "error": "missing csm root"})
        return 1
    sys.path.insert(0, root)

    try:
        from lib.models import ToolType  # type: ignore
        from lib.store import load_session_detail, load_sessions  # type: ignore
    except Exception as exc:  # pragma: no cover - import path issues are environment-dependent.
        _emit({"ok": False, "error": f"failed to import CSM modules: {exc}"})
        return 1

    tool_map = {
        "claude": ToolType.CLAUDE,
        "codex": ToolType.CODEX,
        "gemini": ToolType.GEMINI,
    }
    action = str(req.get("action", "") or "")

    if action == "list_sessions":
        tool_filter = str(req.get("tool_filter", "") or "")
        limit = int(req.get("limit", 20))
        tool_type = tool_map.get(tool_filter) if tool_filter else None
        rows = load_sessions(tool_type)
        _emit({"ok": True, "data": [_to_summary(item) for item in rows[:limit]]})
        return 0

    if action == "get_session_context":
        session_id = str(req.get("session_id", "") or "").strip()
        tool_slug = str(req.get("tool_type", "") or "").strip()
        project = str(req.get("project", "") or "")
        tool_type = tool_map.get(tool_slug)
        if not tool_type:
            _emit({"ok": False, "error": f"unsupported tool_type: {tool_slug}"})
            return 0
        detail = load_session_detail(session_id, tool_type, project)
        _emit({"ok": True, "data": _to_detail(detail) if detail else None})
        return 0

    _emit({"ok": False, "error": f"unsupported action: {action}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
