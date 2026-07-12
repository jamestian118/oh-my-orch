"""Run registry helpers for pipeline/team dual-write compatibility."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

RunKind = Literal["pipeline", "team"]
_SCHEMA_VERSION = 1


def _utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalized_path(path: Path) -> Path:
    return path.resolve(strict=False)


def _project_id_for_root(root: Path) -> str:
    repo_root = str(_normalized_path(root))
    digest = hashlib.sha256(repo_root.encode("utf-8")).hexdigest()[:16]
    return f"proj-{digest}"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def ensure_project_registry(
    root: Path,
    state_path: Path,
    default_timezone: str = "Asia/Shanghai",
) -> Path:
    repo_root = _normalized_path(root)
    state_file = state_path if state_path.is_absolute() else repo_root / state_path
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "project_id": _project_id_for_root(repo_root),
        "repo_root": str(repo_root),
        "default_timezone": default_timezone,
        "state_file": str(_normalized_path(state_file)),
        "updated_at": _utc_now_iso8601(),
    }
    project_registry_path = repo_root / ".omo" / "project.json"
    _write_json(project_registry_path, payload)
    return project_registry_path


def write_run_registry(
    root: Path,
    kind: RunKind,
    run_id: str,
    run_payload: dict,
    artifacts: dict | None = None,
    decisions: list[dict] | None = None,
) -> dict[str, Path]:
    repo_root = _normalized_path(root)
    run_dir = repo_root / ".omo" / "runs" / kind / run_id
    run_file = run_dir / "run.json"
    artifacts_file = run_dir / "artifacts.json"
    decisions_file = run_dir / "decisions.jsonl"
    latest_file = repo_root / ".omo" / "latest" / f"{kind}.json"

    normalized_run_payload = dict(run_payload)
    normalized_run_payload.setdefault("schema_version", _SCHEMA_VERSION)
    normalized_run_payload.setdefault("kind", kind)
    normalized_run_payload.setdefault("run_id", run_id)
    _write_json(run_file, normalized_run_payload)

    _write_json(artifacts_file, dict(artifacts or {}))

    decisions_file.parent.mkdir(parents=True, exist_ok=True)
    rows = decisions or []
    with decisions_file.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    _write_json(
        latest_file,
        {
            "schema_version": _SCHEMA_VERSION,
            "kind": kind,
            "run_id": run_id,
            "run_file": str(run_file),
            "artifacts_file": str(artifacts_file),
            "decisions_file": str(decisions_file),
            "updated_at": _utc_now_iso8601(),
        },
    )

    return {
        "run_dir": run_dir,
        "run_file": run_file,
        "artifacts_file": artifacts_file,
        "decisions_file": decisions_file,
        "latest_file": latest_file,
    }
