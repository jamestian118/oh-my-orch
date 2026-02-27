"""Message bus with JSONL persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

LOGGER = logging.getLogger(__name__)


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
                except json.JSONDecodeError:
                    return self._recover_invalid_store(
                        reason="invalid json line",
                        line_number=line_number,
                    )

                if not isinstance(message, dict):
                    return self._recover_invalid_store(
                        reason="message must be a JSON object",
                        line_number=line_number,
                    )

                self._messages.append(message)

        return self.history()

    def _recover_invalid_store(self, *, reason: str, line_number: int) -> list[dict[str, Any]]:
        LOGGER.warning(
            "MessageBus detected invalid store at %s line %s (%s); clearing and rebuilding.",
            self.store_path,
            line_number,
            reason,
        )
        self._messages.clear()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text("", encoding="utf-8")
        return []
