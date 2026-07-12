"""Message bus with JSONL persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class MessageBus:
    """内存消息总线 + JSONL 持久化。"""

    def __init__(self, store_path: str | Path = ".omo/session.jsonl") -> None:
        self.store_path = Path(store_path)
        self._messages: list[dict[str, Any]] = []

    def add(self, message: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(message, Mapping):
            raise TypeError("message must be a mapping type")

        payload = dict(message)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with self.store_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")

        self._messages.append(payload)
        return dict(payload)

    def history(self) -> list[dict[str, Any]]:
        return [dict(message) for message in self._messages]

    def reset(self) -> None:
        self._messages.clear()
        if self.store_path.exists():
            self.store_path.unlink()

    def load(self) -> list[dict[str, Any]]:
        self._messages.clear()

        if not self.store_path.exists():
            return []

        with self.store_path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL at line {line_number}") from exc

                if not isinstance(message, dict):
                    raise ValueError(f"Invalid message object at line {line_number}")

                self._messages.append(message)

        return self.history()
