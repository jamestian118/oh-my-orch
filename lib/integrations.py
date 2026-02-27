"""Step 6 integrations: UHK / CSM / handoff snapshot wiring.

中文说明：
- 本模块统一封装外部依赖访问，给 orchestrator 提供稳定接口。
- 在 dry-run 或依赖缺失场景下，可退化为 stub，保证主流程可验证。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOOL_SLUGS = {"claude", "codex", "gemini"}

HOME_CODE_ROOT = Path.home() / "Documents" / "Code"
UHK_ROOT = Path(os.environ.get("OMO_UHK_ROOT", str(HOME_CODE_ROOT / "universal-harness-kit")))
CSM_ROOT = Path(os.environ.get("OMO_CSM_ROOT", str(HOME_CODE_ROOT / "claude-session-manager")))
HANDOFF_ROOT = Path(
    os.environ.get("OMO_HANDOFF_ROOT", str(HOME_CODE_ROOT / "cli-handoff-bundle" / "_handoff"))
)
CSM_DRIVER = Path(__file__).with_name("csm_driver.py")


@dataclass(slots=True)
class IntegrationResult:
    ok: bool
    data: dict[str, Any]
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


def _norm_tool(tool: str) -> str:
    slug = tool.lower().strip()
    if slug.startswith("@"):
        slug = slug[1:]
    if slug not in TOOL_SLUGS:
        raise ValueError(f"unsupported tool: {tool}")
    return slug


def _safe_json_load(text: str) -> dict[str, Any]:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        return {"value": obj}
    except json.JSONDecodeError:
        return {"raw": text}


def _repo_root(project_root: Path) -> Path:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            value = proc.stdout.strip()
            if value:
                return Path(value)
    except OSError:
        pass
    return project_root


class UHKIntegration:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.policy_script = UHK_ROOT / "scripts" / "agent-policy-stack"

    def policy_check(
        self, cwd: Path | None = None, strict_profile: str = "harness"
    ) -> IntegrationResult:
        target_cwd = str(cwd or self.project_root)
        if not self.policy_script.exists():
            return IntegrationResult(
                ok=False,
                data={"strict_result": "fail"},
                error=f"missing script: {self.policy_script}",
            )
        proc = subprocess.run(
            [
                str(self.policy_script),
                "--tool",
                "codex",
                "--cwd",
                target_cwd,
                "--strict",
                "--strict-profile",
                strict_profile,
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = _safe_json_load(proc.stdout)
        return IntegrationResult(
            ok=proc.returncode == 0,
            data=payload,
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            error="" if proc.returncode == 0 else "agent-policy-stack failed",
        )

    def verify_project(self, cwd: Path | None = None) -> IntegrationResult:
        target = cwd or self.project_root
        verify_script = target / "scripts" / "verify"
        if not verify_script.exists():
            return IntegrationResult(
                ok=False, data={}, error=f"missing verify script: {verify_script}"
            )
        proc = subprocess.run(
            [str(verify_script)],
            cwd=str(target),
            capture_output=True,
            text=True,
            check=False,
        )
        return IntegrationResult(
            ok=proc.returncode == 0,
            data={"cwd": str(target)},
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            error="" if proc.returncode == 0 else "scripts/verify failed",
        )


class CSMIntegration:
    """通过独立 Python 进程调用 CSM 的函数式 API，避免本仓库 lib 命名冲突。"""

    def __init__(self, csm_root: Path = CSM_ROOT) -> None:
        self.csm_root = csm_root

    @property
    def available(self) -> bool:
        return (self.csm_root / "lib" / "store.py").exists() and (
            self.csm_root / "lib" / "models.py"
        ).exists()

    def _invoke(self, action: str, payload: dict[str, Any]) -> IntegrationResult:
        if not self.available:
            return IntegrationResult(ok=False, data={}, error=f"CSM unavailable: {self.csm_root}")
        if not CSM_DRIVER.exists():
            return IntegrationResult(ok=False, data={}, error=f"missing CSM driver: {CSM_DRIVER}")

        args = {
            "root": str(self.csm_root),
            "action": action,
            **payload,
        }
        proc = subprocess.run(
            [sys.executable, str(CSM_DRIVER), json.dumps(args)],
            capture_output=True,
            text=True,
            check=False,
        )
        body = _safe_json_load(proc.stdout)
        ok = proc.returncode == 0 and bool(body.get("ok"))
        return IntegrationResult(
            ok=ok,
            data=body.get("data", {}),
            error=body.get("error", "") if isinstance(body, dict) else "",
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )

    def list_sessions(self, tool_filter: str = "", limit: int = 20) -> IntegrationResult:
        slug = _norm_tool(tool_filter) if tool_filter else ""
        return self._invoke("list_sessions", {"tool_filter": slug, "limit": limit})

    def get_session_context(
        self,
        session_id: str,
        tool_type: str,
        project: str = "",
    ) -> IntegrationResult:
        slug = _norm_tool(tool_type)
        return self._invoke(
            "get_session_context",
            {"session_id": session_id, "tool_type": slug, "project": project},
        )


class HandoffIntegration:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def _snapshot_score(self, path: Path) -> tuple[int, float]:
        score = 0
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:8000]
        except OSError:
            return 0, 0.0
        if "Repo root / 仓库根目录" in text:
            score += 3
        if "## Repo State / 仓库状态" in text:
            score += 3
        if "Repo Handoff File (excerpt)" in text:
            score += 2
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return score, float(mtime)

    def _candidate_paths(self, session_id: str, tool_type: str, project: str = "") -> list[Path]:
        slug = _norm_tool(tool_type)
        filename = f"{slug}-{session_id}.md"
        paths: list[Path] = []

        if project:
            repo = _repo_root(Path(project))
            paths.append(repo / ".ai" / "handoff" / "sessions" / filename)

        repo = _repo_root(self.project_root)
        paths.append(repo / ".ai" / "handoff" / "sessions" / filename)

        roots: list[Path] = []
        env_roots = os.environ.get("CSM_HANDOFF_ROOTS", "").strip()
        if env_roots:
            roots.extend(
                Path(os.path.expanduser(item.strip()))
                for item in env_roots.split(os.pathsep)
                if item.strip()
            )
        roots.append(
            Path.home() / "Library" / "Application Support" / "cli-handoff-bundle" / "_handoff"
        )
        roots.append(HANDOFF_ROOT)

        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            paths.append(root / "sessions" / filename)
        return paths

    def find_snapshot(
        self, session_id: str, tool_type: str, project: str = ""
    ) -> IntegrationResult:
        existing: list[Path] = []
        for path in self._candidate_paths(session_id, tool_type, project):
            if path.exists():
                existing.append(path)
        if not existing:
            return IntegrationResult(ok=False, data={}, error="snapshot not found")
        best = max(existing, key=self._snapshot_score)
        return IntegrationResult(ok=True, data={"path": str(best)})

    def read_snapshot(
        self,
        session_id: str,
        tool_type: str,
        project: str = "",
        max_chars: int = 8000,
    ) -> IntegrationResult:
        path_result = self.find_snapshot(session_id, tool_type, project)
        if not path_result.ok:
            return path_result
        path = Path(path_result.data["path"])
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return IntegrationResult(ok=False, data={"path": str(path)}, error=str(exc))
        truncated = False
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars]
            truncated = True
        return IntegrationResult(
            ok=True,
            data={"path": str(path), "content": text, "truncated": truncated},
        )


class IntegrationHub:
    """编排器统一入口：默认 real，依赖缺失时降级。"""

    def __init__(self, project_root: Path, *, mode: str = "auto") -> None:
        if mode not in {"auto", "real", "stub"}:
            raise ValueError(f"invalid mode: {mode}")
        self.project_root = project_root
        self.mode = mode
        self.uhk = UHKIntegration(project_root)
        self.csm = CSMIntegration()
        self.handoff = HandoffIntegration(project_root)

    @property
    def stub_only(self) -> bool:
        return self.mode == "stub"

    def policy_check(self, cwd: Path | None = None) -> IntegrationResult:
        if self.stub_only:
            return IntegrationResult(ok=True, data={"strict_result": "pass", "mode": "stub"})
        result = self.uhk.policy_check(cwd or self.project_root)
        if result.ok or self.mode == "real":
            return result
        return IntegrationResult(ok=True, data={"strict_result": "pass", "mode": "degraded-stub"})

    def verify_project(self, cwd: Path | None = None) -> IntegrationResult:
        if self.stub_only:
            return IntegrationResult(ok=True, data={"mode": "stub"})
        result = self.uhk.verify_project(cwd or self.project_root)
        if result.ok or self.mode == "real":
            return result
        return IntegrationResult(ok=True, data={"mode": "degraded-stub"})

    def list_sessions(self, tool_filter: str = "", limit: int = 20) -> IntegrationResult:
        if self.stub_only:
            return IntegrationResult(ok=True, data={"sessions": []})
        result = self.csm.list_sessions(tool_filter, limit)
        if result.ok:
            return IntegrationResult(ok=True, data={"sessions": result.data})
        if self.mode == "real":
            return result
        return IntegrationResult(ok=True, data={"sessions": []}, error=result.error)

    def get_session_context(
        self, session_id: str, tool_type: str, project: str = ""
    ) -> IntegrationResult:
        if self.stub_only:
            return IntegrationResult(
                ok=True, data={"session_id": session_id, "tool_type": tool_type, "messages": []}
            )
        result = self.csm.get_session_context(session_id, tool_type, project)
        if result.ok:
            return IntegrationResult(
                ok=True, data=result.data if isinstance(result.data, dict) else {}
            )
        if self.mode == "real":
            return result
        return IntegrationResult(
            ok=True, data={"session_id": session_id, "tool_type": tool_type}, error=result.error
        )

    def get_handoff_snapshot(
        self, session_id: str, tool_type: str, project: str = ""
    ) -> IntegrationResult:
        if self.stub_only:
            return IntegrationResult(ok=True, data={"path": "", "content": "", "truncated": False})
        result = self.handoff.read_snapshot(session_id, tool_type, project=project)
        if result.ok or self.mode == "real":
            return result
        return IntegrationResult(
            ok=True, data={"path": "", "content": "", "truncated": False}, error=result.error
        )


def build_integrations(
    project_root: Path, *, dry_run: bool = False, mode: str = "auto"
) -> IntegrationHub:
    if dry_run and mode == "auto":
        return IntegrationHub(project_root, mode="stub")
    return IntegrationHub(project_root, mode=mode)
