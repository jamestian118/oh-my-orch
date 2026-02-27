"""Logging helpers for OMO CLI."""

from __future__ import annotations

import logging
import os
import shlex
from typing import Sequence

_DEFAULT_LEVEL_NAME = "WARNING"
_LEVEL_MAP = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _parse_level(raw_value: str | None) -> tuple[int, bool]:
    raw = (raw_value or "").strip()
    if not raw:
        return _LEVEL_MAP[_DEFAULT_LEVEL_NAME], False

    upper = raw.upper()
    if upper in _LEVEL_MAP:
        return _LEVEL_MAP[upper], False

    if raw.lstrip("-").isdigit():
        return int(raw), False

    return _LEVEL_MAP[_DEFAULT_LEVEL_NAME], True


def configure_logging(*, verbose: bool = False, debug: bool = False) -> int:
    """Configure root logging from OMO_LOG_LEVEL with CLI overrides."""
    env_value = os.environ.get("OMO_LOG_LEVEL", "")
    level, invalid = _parse_level(env_value)

    if verbose and level > logging.INFO:
        level = logging.INFO
    if debug:
        level = logging.DEBUG

    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        for handler in root.handlers:
            handler.setLevel(level)
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

    logger = logging.getLogger(__name__)
    if invalid:
        logger.warning("Invalid OMO_LOG_LEVEL=%r, fallback to %s", env_value, _DEFAULT_LEVEL_NAME)
    logger.debug(
        "omo logging configured level=%s verbose=%s debug=%s env=%r",
        logging.getLevelName(level),
        verbose,
        debug,
        env_value,
    )
    return level


def format_command(command: Sequence[str]) -> str:
    """Render subprocess command as shell-like string for debug logs."""
    try:
        return shlex.join(str(part) for part in command)
    except Exception:
        return " ".join(str(part) for part in command)


def stderr_preview(stderr: str, *, limit: int = 500) -> tuple[str, bool]:
    text = stderr or ""
    if len(text) <= limit:
        return text, False
    return text[:limit], True
