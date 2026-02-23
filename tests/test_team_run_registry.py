"""Team run registry dual-write tests."""

from __future__ import annotations

import json
from pathlib import Path

from lib.orchestrator import Orchestrator


def test_team_dry_run_writes_omo_run_registry_and_keeps_legacy_contract(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)

    result = orch.team(topic="team registry dual-write", dry_run=True)

    run_dir = Path(result["run_dir"])
    run_id = run_dir.name
    team_registry_dir = tmp_path / ".omo" / "runs" / "team" / run_id
    run_json = team_registry_dir / "run.json"
    artifacts_json = team_registry_dir / "artifacts.json"
    decisions_jsonl = team_registry_dir / "decisions.jsonl"
    latest_team_json = tmp_path / ".omo" / "latest" / "team.json"

    assert run_json.exists()
    assert artifacts_json.exists()
    assert decisions_jsonl.exists()
    assert latest_team_json.exists()

    latest_payload = json.loads(latest_team_json.read_text(encoding="utf-8"))
    assert latest_payload["run_id"] == run_id

    run_payload = json.loads(run_json.read_text(encoding="utf-8"))
    assert run_payload["run_id"] == run_id
    assert run_payload["kind"] == "team"
    assert run_payload["status"] in {"completed", "failed"}

    assert Path(result["summary_file"]).exists()
    assert Path(result["meta_file"]).exists()
