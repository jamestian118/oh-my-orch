"""Pipeline run-registry dual-write regression tests."""

from __future__ import annotations

import json
from pathlib import Path

from lib.orchestrator import Orchestrator


def test_pipeline_dual_writes_run_registry_without_breaking_legacy_contract(tmp_path) -> None:
    orch = Orchestrator(root_dir=tmp_path, dry_run=True)

    result = orch.pipeline(task="pipeline run registry dual write", dry_run=True)
    run_id = str(result["run_id"])
    run_dir = Path(result["run_dir"])

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

    decisions_dir = run_dir / "decisions"
    context_pack_file = decisions_dir / "context-pack.json"
    stage_results_file = decisions_dir / "stage-results.json"
    final_gate_file = decisions_dir / "final-gate.json"
    decision_files = dict(result["decision_files"])

    assert Path(result["decisions_dir"]) == decisions_dir
    assert context_pack_file.exists()
    assert stage_results_file.exists()
    assert final_gate_file.exists()
    assert decision_files["context-pack.json"] == str(context_pack_file)
    assert decision_files["stage-results.json"] == str(stage_results_file)
    assert decision_files["final-gate.json"] == str(final_gate_file)

    context_pack_payload = json.loads(context_pack_file.read_text(encoding="utf-8"))
    assert context_pack_payload["run_id"] == run_id
    assert context_pack_payload["task"] == "pipeline run registry dual write"

    stage_results_payload = json.loads(stage_results_file.read_text(encoding="utf-8"))
    assert isinstance(stage_results_payload, list)
    assert stage_results_payload
    assert stage_results_payload[0]["stage"] == "stage0_project_brief"

    final_gate_payload = json.loads(final_gate_file.read_text(encoding="utf-8"))
    assert final_gate_payload["status"] == "completed"
    assert "verify_hint" in final_gate_payload
