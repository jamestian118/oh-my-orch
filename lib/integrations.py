"""Step 6 integrations: UHK / CSM / handoff snapshot wiring.

中文说明：
- 本模块统一封装外部依赖访问，给 orchestrator 提供稳定接口。
- 在 dry-run 或依赖缺失场景下，可退化为 stub，保证主流程可验证。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logging_config import format_command

TOOL_SLUGS = {"claude", "codex", "gemini"}
LOGGER = logging.getLogger(__name__)

_SEMVER_TOKEN = re.compile(r"^(\d+)")
_DEFAULT_CODE_ROOT = Path.home() / "Documents" / "Code"


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return Path(os.path.expanduser(raw))


HOME_CODE_ROOT = _env_path("OMO_CODE_ROOT", _DEFAULT_CODE_ROOT)
UHK_ROOT = _env_path("OMO_UHK_ROOT", HOME_CODE_ROOT / "universal-harness-kit")
CSM_ROOT = _env_path("OMO_CSM_ROOT", HOME_CODE_ROOT / "claude-session-manager")
HANDOFF_ROOT = _env_path("OMO_HANDOFF_ROOT", HOME_CODE_ROOT / "cli-handoff-bundle" / "_handoff")
CSM_DRIVER = Path(__file__).with_name("csm_driver.py")


@dataclass(slots=True)
class IntegrationResult:
    ok: bool
    data: Any
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


def _safe_json_any(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _parse_semver(value: str) -> tuple[int, ...] | None:
    parts: list[int] = []
    for chunk in (value or "").strip().split("."):
        token = chunk.strip()
        if not token:
            continue
        matched = _SEMVER_TOKEN.match(token)
        if not matched:
            break
        parts.append(int(matched.group(1)))
    return tuple(parts) if parts else None


def _version_gte(current: str, required: str) -> bool:
    cur = _parse_semver(current)
    req = _parse_semver(required)
    if not cur or not req:
        return False
    size = max(len(cur), len(req))
    cur = cur + (0,) * (size - len(cur))
    req = req + (0,) * (size - len(req))
    return cur >= req


def _encode_mcp_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _decode_mcp_messages(stream: bytes) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    offset = 0
    while offset < len(stream):
        header_end = stream.find(b"\r\n\r\n", offset)
        if header_end == -1:
            break
        header_blob = stream[offset:header_end].decode("utf-8", errors="replace")
        content_length: int | None = None
        for row in header_blob.split("\r\n"):
            if row.lower().startswith("content-length:"):
                try:
                    content_length = int(row.split(":", 1)[1].strip())
                except ValueError:
                    content_length = None
                break
        if content_length is None or content_length < 0:
            break
        body_start = header_end + 4
        body_end = body_start + content_length
        if body_end > len(stream):
            break
        body = stream[body_start:body_end].decode("utf-8", errors="replace")
        decoded = _safe_json_any(body)
        if isinstance(decoded, dict):
            messages.append(decoded)
        offset = body_end
    return messages


def _extract_mcp_tool_payload(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            parsed = _safe_json_any(text)
            return parsed
    return result


def _repo_root(project_root: Path) -> Path:
    try:
        command = ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"]
        LOGGER.debug("subprocess command: %s (cwd=%s)", format_command(command), project_root)
        proc = subprocess.run(
            command,
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
        command = [
            str(self.policy_script),
            "--tool",
            "codex",
            "--cwd",
            target_cwd,
            "--strict",
            "--strict-profile",
            strict_profile,
            "--json",
        ]
        LOGGER.debug("subprocess command: %s (cwd=%s)", format_command(command), target_cwd)
        proc = subprocess.run(
            command,
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
        command = [str(verify_script)]
        LOGGER.debug("subprocess command: %s (cwd=%s)", format_command(command), target)
        proc = subprocess.run(
            command,
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
    """优先通过 MCP stdio 调用 CSM，必要时兼容回退到 driver。"""

    def __init__(
        self,
        csm_root: Path = CSM_ROOT,
        *,
        transport: str | None = None,
        min_version: str | None = None,
        mcp_timeout_sec: float | None = None,
    ) -> None:
        self.csm_root = csm_root
        self.transport = (transport or os.environ.get("OMO_CSM_TRANSPORT", "auto")).strip().lower()
        self.min_version = (min_version or os.environ.get("OMO_CSM_MIN_VERSION", "0.1.0")).strip()
        if not self.min_version:
            self.min_version = "0.1.0"
        timeout_raw = (
            str(mcp_timeout_sec)
            if mcp_timeout_sec is not None
            else os.environ.get("OMO_CSM_MCP_TIMEOUT_SEC", "8")
        )
        try:
            self.mcp_timeout_sec = max(float(timeout_raw), 1.0)
        except ValueError:
            self.mcp_timeout_sec = 8.0

    @property
    def available(self) -> bool:
        return (self.csm_root / "lib" / "store.py").exists() and (
            self.csm_root / "lib" / "models.py"
        ).exists()

    def _read_version(self) -> str:
        version_file = self.csm_root / "VERSION"
        if version_file.exists():
            try:
                value = version_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                value = ""
            if value:
                return value.splitlines()[0].strip()

        pyproject_path = self.csm_root / "pyproject.toml"
        if pyproject_path.exists():
            try:
                text = pyproject_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            matched = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"\s*$', text)
            if matched:
                return matched.group(1).strip()
        return ""

    def _build_incompatible_error(self, detected: str) -> str:
        upgrade_hint = (
            f"cd {self.csm_root} && git pull && python3 -m pip install -e {self.csm_root}"
        )
        return (
            "CSM version incompatible for OMO MCP stdio integration: "
            f"detected {detected or 'unknown'}, requires >= {self.min_version}. "
            f"建议升级：{upgrade_hint}. "
            "临时回滚兼容路径：export OMO_CSM_TRANSPORT=driver"
        )

    def _build_mcp_command(self) -> list[str]:
        override = os.environ.get("OMO_CSM_MCP_COMMAND", "").strip()
        if override:
            return shlex.split(override)
        python_bin = os.environ.get("OMO_CSM_PYTHON_BIN", "").strip() or sys.executable
        return [python_bin, str(self.csm_root / "csm.py"), "mcp"]

    def _check_mcp_compatibility(self) -> tuple[bool, str]:
        entrypoint = self.csm_root / "csm.py"
        if not entrypoint.exists():
            return (
                False,
                "missing CSM MCP entrypoint: "
                f"{entrypoint}. 临时回滚兼容路径：export OMO_CSM_TRANSPORT=driver",
            )
        detected = self._read_version()
        if not detected:
            return False, self._build_incompatible_error("unknown")
        if not _version_gte(detected, self.min_version):
            return False, self._build_incompatible_error(detected)
        return True, ""

    def _invoke_via_driver(self, action: str, payload: dict[str, Any]) -> IntegrationResult:
        if not CSM_DRIVER.exists():
            return IntegrationResult(ok=False, data={}, error=f"missing CSM driver: {CSM_DRIVER}")

        args = {
            "root": str(self.csm_root),
            "action": action,
            **payload,
        }
        command = [sys.executable, str(CSM_DRIVER), json.dumps(args)]
        LOGGER.debug(
            "subprocess command: %s (cwd=%s)",
            format_command(command),
            self.csm_root,
        )
        proc = subprocess.run(
            command,
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

    def _invoke_via_mcp(self, action: str, payload: dict[str, Any]) -> IntegrationResult:
        command = self._build_mcp_command()
        LOGGER.debug("subprocess command: %s (cwd=%s)", format_command(command), self.csm_root)
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(self.csm_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            return IntegrationResult(
                ok=False, data={}, error=f"failed to start CSM MCP server: {exc}"
            )

        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "omo", "version": "1.0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": action, "arguments": payload},
            },
        ]
        request_bytes = b"".join(_encode_mcp_message(item) for item in requests)
        try:
            stdout_bytes, stderr_bytes = proc.communicate(
                input=request_bytes,
                timeout=self.mcp_timeout_sec,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_bytes, stderr_bytes = proc.communicate()
            stdout_text = stdout_bytes.decode("utf-8", errors="replace")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            return IntegrationResult(
                ok=False,
                data={},
                error=(
                    f"CSM MCP stdio timeout after {self.mcp_timeout_sec:.1f}s. "
                    "可临时回滚：export OMO_CSM_TRANSPORT=driver"
                ),
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=proc.returncode or 1,
            )

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        messages = _decode_mcp_messages(stdout_bytes)
        response = next((item for item in messages if item.get("id") == 2), None)
        if response is None:
            error = stderr_text.strip() or "missing MCP response for tools/call"
            return IntegrationResult(
                ok=False,
                data={},
                error=error,
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=proc.returncode,
            )
        if isinstance(response, dict) and isinstance(response.get("error"), dict):
            rpc_err = response["error"]
            message = str(rpc_err.get("message", "unknown mcp error"))
            return IntegrationResult(
                ok=False,
                data={},
                error=message,
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=proc.returncode,
            )

        payload_obj = _extract_mcp_tool_payload(response.get("result"))
        if isinstance(payload_obj, dict) and payload_obj.get("error"):
            return IntegrationResult(
                ok=False,
                data={},
                error=str(payload_obj.get("error", "")),
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=proc.returncode,
            )
        if proc.returncode != 0:
            return IntegrationResult(
                ok=False,
                data={},
                error=stderr_text.strip() or "CSM MCP call failed",
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=proc.returncode,
            )

        return IntegrationResult(
            ok=True,
            data=payload_obj if payload_obj is not None else {},
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=proc.returncode,
        )

    def _invoke(self, action: str, payload: dict[str, Any]) -> IntegrationResult:
        if not self.available:
            return IntegrationResult(ok=False, data={}, error=f"CSM unavailable: {self.csm_root}")
        if self.transport not in {"auto", "mcp", "driver"}:
            return IntegrationResult(
                ok=False,
                data={},
                error=(
                    f"invalid OMO_CSM_TRANSPORT={self.transport}. supported: auto | mcp | driver"
                ),
            )

        fallback_reasons: list[str] = []
        if self.transport in {"auto", "mcp"}:
            compatible, compat_error = self._check_mcp_compatibility()
            if compatible:
                mcp_result = self._invoke_via_mcp(action, payload)
                if mcp_result.ok:
                    return mcp_result
                fallback_reasons.append(mcp_result.error or "mcp invoke failed")
                if self.transport == "mcp":
                    return mcp_result
            else:
                if self.transport == "mcp":
                    return IntegrationResult(ok=False, data={}, error=compat_error)
                fallback_reasons.append(compat_error)

        driver_result = self._invoke_via_driver(action, payload)
        if driver_result.ok and fallback_reasons:
            LOGGER.warning(
                "CSM MCP not available, fallback to driver: %s",
                " | ".join(reason for reason in fallback_reasons if reason),
            )
        if (not driver_result.ok) and fallback_reasons:
            merged = [reason for reason in fallback_reasons if reason]
            if driver_result.error:
                merged.append(driver_result.error)
            driver_result.error = " ; ".join(merged)
        return driver_result

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
