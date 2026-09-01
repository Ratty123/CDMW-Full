"""Lightweight Rust Mesh Editor executable and protocol contract."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

RUST_MESH_EDITOR_PROTOCOL = "cdmw_rust_mesh_editor_protocol_v1"
RUST_MESH_AUTHORING_PACKAGE = "cdmw_rust_mesh_authoring_package_v1"
RUST_MESH_CANDIDATE = "cdmw_rust_mesh_candidate_v1"
RUST_MESH_RENDERER = "wgpu_d3d12_rust"
RUST_MESH_EDIT_BACKEND = "cdmw_rust_mesh_0.1"
RUST_MESH_EDITOR_BINARY = "cdmw_mesh_lab.exe"
RUST_MESH_MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
RUST_MESH_PROVENANCE_SCHEMA = "cdmw_rust_mesh_editor_build_provenance_v1"
RUST_MESH_PROVENANCE_FILE = "cdmw_mesh_lab.manifest.json"
RUST_MESH_CONTROL_CONTRACT_FILE = "cdmw_mesh_lab.control-contract.json"
RUST_MESH_CONTROL_CONTRACT_SCHEMA = "cdmw_rust_mesh_editor_control_contract_v2"
RUST_MESH_REQUIRED_CAPABILITIES = ("embedded_child_window_v1",)


@dataclass(frozen=True, slots=True)
class RustMeshExecutableResolution:
    resolved_path: str = ""
    source: str = "missing"
    exists: bool = False
    is_file: bool = False
    configured_path: str = ""
    env_path: str = ""
    frozen_root: str = ""
    exe_root: str = ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rust_mesh_editor_candidate_paths(
    *,
    configured_path: Path | str | None = None,
    env_path: str = "",
    frozen_root: Path | None = None,
    exe_root: Path | None = None,
) -> tuple[tuple[str, Path], ...]:
    candidates: list[tuple[str, Path]] = []
    configured_text = str(configured_path or "").strip()
    if configured_text:
        candidates.append(("configured", Path(configured_text).expanduser()))
    if str(env_path or "").strip():
        candidates.append(("environment", Path(env_path).expanduser()))
    for source, root in (("frozen", frozen_root), ("executable", exe_root)):
        if root is None:
            continue
        candidates.extend(
            (
                (source, root / "native" / "rust_mesh_editor" / RUST_MESH_EDITOR_BINARY),
                (
                    f"{source}_internal",
                    root
                    / "_internal"
                    / "native"
                    / "rust_mesh_editor"
                    / RUST_MESH_EDITOR_BINARY,
                ),
            )
        )
    root = _repo_root()
    candidates.extend(
        (
            (
                "native_release",
                root
                / "native"
                / "rust_mesh_editor"
                / "build"
                / "Release"
                / RUST_MESH_EDITOR_BINARY,
            ),
            (
                "source_release",
                root
                / "tools"
                / "rust_mesh_lab"
                / "target"
                / "release"
                / RUST_MESH_EDITOR_BINARY,
            ),
            (
                "source_debug",
                root
                / "tools"
                / "rust_mesh_lab"
                / "target"
                / "debug"
                / RUST_MESH_EDITOR_BINARY,
            ),
        )
    )
    return tuple(candidates)


def resolve_rust_mesh_editor(
    configured_path: Path | str | None = None,
) -> RustMeshExecutableResolution:
    configured_text = str(configured_path or "").strip()
    env_path = os.environ.get("CDMW_RUST_MESH_EDITOR_EXE", "").strip()
    frozen_root = (
        Path(str(getattr(sys, "_MEIPASS", "")))
        if str(getattr(sys, "_MEIPASS", "") or "").strip()
        else None
    )
    exe_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    first_existing: tuple[str, Path] | None = None
    for source, candidate in rust_mesh_editor_candidate_paths(
        configured_path=configured_path,
        env_path=env_path,
        frozen_root=frozen_root,
        exe_root=exe_root,
    ):
        if candidate.exists() and first_existing is None:
            first_existing = (source, candidate)
        if candidate.is_file():
            return RustMeshExecutableResolution(
                resolved_path=str(candidate.resolve()),
                source=source,
                exists=True,
                is_file=True,
                configured_path=configured_text,
                env_path=env_path,
                frozen_root=str(frozen_root or ""),
                exe_root=str(exe_root or ""),
            )
    if first_existing is not None:
        source, candidate = first_existing
        return RustMeshExecutableResolution(
            resolved_path=str(candidate.resolve()),
            source=source,
            exists=True,
            is_file=False,
            configured_path=configured_text,
            env_path=env_path,
            frozen_root=str(frozen_root or ""),
            exe_root=str(exe_root or ""),
        )
    missing = Path(configured_text).expanduser() if configured_text else None
    if missing is None and env_path:
        missing = Path(env_path).expanduser()
    return RustMeshExecutableResolution(
        resolved_path=str(missing or ""),
        source="missing",
        configured_path=configured_text,
        env_path=env_path,
        frozen_root=str(frozen_root or ""),
        exe_root=str(exe_root or ""),
    )


def rust_mesh_editor_file_signature(resolution: RustMeshExecutableResolution) -> str:
    """Return a cheap cache identity for both executable and provenance inputs.

    This signature is only a cache invalidation aid. Launch authorization always
    re-runs :func:`validate_rust_mesh_editor_package`, including its SHA-256
    check, immediately before starting the integrated process.
    """

    resolved_text = str(resolution.resolved_path or "").strip()
    if not resolved_text:
        return ""
    executable = Path(resolved_text)
    manifest = executable.with_name(RUST_MESH_PROVENANCE_FILE)
    control_contract = executable.with_name(RUST_MESH_CONTROL_CONTRACT_FILE)

    def file_identity(path: Path) -> str:
        try:
            stat = path.stat()
        except OSError:
            return f"{path.resolve()}|missing"
        return (
            f"{path.resolve()}|{stat.st_dev}|{stat.st_ino}|"
            f"{stat.st_size}|{stat.st_mtime_ns}"
        )

    return (
        f"executable={file_identity(executable)}|manifest={file_identity(manifest)}|"
        f"control_contract={file_identity(control_contract)}"
    )


def validate_rust_mesh_editor_package(
    resolution: RustMeshExecutableResolution,
) -> str:
    """Return a visible incompatibility reason for an integrated Rust helper."""

    if not resolution.is_file:
        return "cdmw_mesh_lab.exe was not found"
    executable = Path(resolution.resolved_path)
    if not executable.is_file():
        return "cdmw_mesh_lab.exe was not found"
    manifest_path = executable.with_name(RUST_MESH_PROVENANCE_FILE)
    if not manifest_path.is_file():
        return "Rust provenance manifest is missing"
    try:
        if manifest_path.stat().st_size > 256 * 1024:
            return "Rust provenance manifest is oversized"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return "Rust provenance manifest is unreadable"
    if not isinstance(payload, dict):
        return "Rust provenance manifest is unreadable"
    expected = {
        "schema": RUST_MESH_PROVENANCE_SCHEMA,
        "renderer": RUST_MESH_RENDERER,
        "edit_backend": RUST_MESH_EDIT_BACKEND,
        "protocol": RUST_MESH_EDITOR_PROTOCOL,
        "authoring_package": RUST_MESH_AUTHORING_PACKAGE,
        "control_contract": RUST_MESH_CONTROL_CONTRACT_FILE,
        "control_contract_schema": RUST_MESH_CONTROL_CONTRACT_SCHEMA,
    }
    for key, value in expected.items():
        if str(payload.get(key, "") or "") != value:
            return f"Rust provenance {key} does not match"
    if payload.get("locked_dependencies") is not True:
        return "Rust helper was not built with locked dependencies"
    capabilities = payload.get("capabilities", ())
    if not isinstance(capabilities, list) or not set(RUST_MESH_REQUIRED_CAPABILITIES).issubset(
        {str(value or "") for value in capabilities}
    ):
        return "Rust helper does not support embedded child windows"
    expected_hash = str(payload.get("executable_sha256", "") or "").strip().lower()
    if len(expected_hash) != 64:
        return "Rust provenance executable hash is invalid"
    digest = hashlib.sha256()
    try:
        with executable.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "Rust executable could not be hashed"
    if digest.hexdigest().lower() != expected_hash:
        return "Rust executable hash does not match its provenance manifest"
    contract_path = executable.with_name(RUST_MESH_CONTROL_CONTRACT_FILE)
    if not contract_path.is_file():
        return "Rust control contract is missing"
    expected_contract_hash = str(payload.get("control_contract_sha256", "") or "").strip().lower()
    if len(expected_contract_hash) != 64:
        return "Rust provenance control contract hash is invalid"
    contract_digest = hashlib.sha256()
    try:
        if contract_path.stat().st_size > 8 * 1024 * 1024:
            return "Rust control contract is oversized"
        with contract_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                contract_digest.update(chunk)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return "Rust control contract is unreadable"
    if contract_digest.hexdigest().lower() != expected_contract_hash:
        return "Rust control contract hash does not match its provenance manifest"
    if not isinstance(contract, dict) or contract.get("schema") != RUST_MESH_CONTROL_CONTRACT_SCHEMA:
        return "Rust control contract schema does not match"
    if contract.get("ok") is not True:
        return "Rust control contract did not pass"
    return ""


__all__ = [
    "RUST_MESH_AUTHORING_PACKAGE",
    "RUST_MESH_CANDIDATE",
    "RUST_MESH_EDITOR_BINARY",
    "RUST_MESH_CONTROL_CONTRACT_FILE",
    "RUST_MESH_CONTROL_CONTRACT_SCHEMA",
    "RUST_MESH_EDITOR_PROTOCOL",
    "RUST_MESH_EDIT_BACKEND",
    "RUST_MESH_MAX_PAYLOAD_BYTES",
    "RUST_MESH_PROVENANCE_FILE",
    "RUST_MESH_PROVENANCE_SCHEMA",
    "RUST_MESH_RENDERER",
    "RUST_MESH_REQUIRED_CAPABILITIES",
    "RustMeshExecutableResolution",
    "resolve_rust_mesh_editor",
    "rust_mesh_editor_candidate_paths",
    "rust_mesh_editor_file_signature",
    "validate_rust_mesh_editor_package",
]
