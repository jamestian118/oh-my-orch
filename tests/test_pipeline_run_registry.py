"""Pipeline run-registry dual-write regression tests."""

from __future__ import annotations

import json
from pathlib import Path

from lib.orchestrator import Orchestrator


def test_pipeline_dual_writes_run_registry_without_breaking_legacy_contract(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)

    result = orch.pipeline(task="pipeline run registry dual write", dry_run=True)
    run_id = str(result["run_id"])

    project_registry_path = tmp_path / ".omo" / "project.json"
    assert project_registry_path.exists()
    project_payload = json.loads(project_registry_path.read_text(encoding="utf-8"))
    assert project_payload["default_timezone"] == "Asia/Shanghai"

    run_root = tmp_path / ".omo" / "runs" / "pipeline" / run_id
    run_file = run_root / "run.json"
    artifacts_file = run_root / "artifacts.json"
    decisions_file = run_root / "decisions.jsonl"
    latest_file = tmp_path / ".omo" / "latest" / "pipeline.json"

    assert run_file.exists()
    run_payload = json.loads(run_file.read_text(encoding="utf-8"))
    assert run_payload["kind"] == "pipeline"

    assert artifacts_file.exists()
    assert decisions_file.exists()

    assert latest_file.exists()
    latest_payload = json.loads(latest_file.read_text(encoding="utf-8"))
    assert latest_payload["run_id"] == run_id

    assert Path(result["meta_file"]).exists()
    assert Path(result["summary_file"]).exists()
