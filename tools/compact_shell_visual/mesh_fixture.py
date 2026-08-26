"""Synthetic Mesh Editor package, helper, and readiness evidence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from PySide6.QtWidgets import QWidget

from tools.compact_shell_visual.contracts import (
    EXPECTED_MESH_EDIT_BACKEND,
    EXPECTED_MESH_RENDERER_BACKEND,
    MESH_RENDERER_READY_TIMEOUT_SECONDS,
    SYNTHETIC_MESH_SESSION_ID,
    SYNTHETIC_MESH_SOURCE_PATH,
    _BUNDLED_HELPER_RESOLUTION_SOURCES,
)
from tools.compact_shell_visual.runtime import _wait_until


def _require_bundled_mesh_helper(widget: QWidget) -> dict[str, object]:
    resolver = getattr(widget, "_dotnet_editor_executable_resolution", None)
    if not callable(resolver):
        raise RuntimeError(
            "Compact Mesh capture requires the production .NET/Vortice helper resolver."
        )
    resolution = resolver(log=False)
    resolved_path = Path(str(getattr(resolution, "resolved_path", "") or ""))
    source = str(getattr(resolution, "source", "") or "")
    if not bool(getattr(resolution, "is_file", False)) or not resolved_path.is_file():
        raise RuntimeError(
            "Compact Mesh capture requires the bundled resident .NET/Vortice helper, "
            "but cdmw-mesh-dotnet-editor.exe was not found. Build the bundled Release helper first."
        )
    if resolved_path.name.casefold() != "cdmw-mesh-dotnet-editor.exe":
        raise RuntimeError(
            "Compact Mesh capture resolved an unexpected renderer executable: "
            f"{resolved_path.name or '<empty>'}."
        )
    if source not in _BUNDLED_HELPER_RESOLUTION_SOURCES:
        raise RuntimeError(
            "Compact Mesh capture must exercise the bundled resident helper; "
            f"the production resolver selected {source or 'an unknown source'} instead."
        )
    return {
        "available": True,
        "resolution_source": source,
        "executable": str(resolved_path),
    }


def _synthetic_mesh_package_evidence(
    widget: QWidget,
    *,
    expected_source_identity: str,
) -> dict[str, object] | None:
    package = getattr(widget, "standalone_dotnet_experiment_package", None)
    if package is None:
        return None
    scene_frame = getattr(package, "scene_frame", None)
    session_id = str(getattr(package, "scene_session_id", "") or "")
    source_identity = str(getattr(scene_frame, "source_identity", "") or "")
    if session_id != SYNTHETIC_MESH_SESSION_ID:
        raise RuntimeError(
            "Resident Mesh helper loaded the wrong package session: "
            f"expected {SYNTHETIC_MESH_SESSION_ID!r}, got {session_id!r}."
        )
    if source_identity != expected_source_identity:
        raise RuntimeError(
            "Resident Mesh helper package source identity did not match the generated synthetic mesh."
        )
    required_paths = {
        "mesh": Path(str(getattr(package, "mesh_path", "") or "")),
        "metadata": Path(str(getattr(package, "cdmeta_path", "") or "")),
        "scene": Path(str(getattr(package, "scene_manifest_path", "") or "")),
        "launch": Path(str(getattr(package, "launch_manifest_path", "") or "")),
    }
    missing = tuple(name for name, path in required_paths.items() if not path.is_file())
    if missing:
        raise RuntimeError(
            "Resident Mesh helper synthetic package is incomplete: " + ", ".join(missing)
        )
    if str(getattr(package, "material_signature", "") or "") != "geometry_only":
        raise RuntimeError(
            "Compact Mesh fixture unexpectedly included external material resources."
        )
    if str(getattr(scene_frame, "interaction_mode", "") or "") != "mesh_edit":
        raise RuntimeError("Compact Mesh fixture did not prepare the Mesh Editor interaction mode.")
    return {
        "session_id": session_id,
        "synthetic_source_path": SYNTHETIC_MESH_SOURCE_PATH,
        "source_identity": source_identity,
        "package_dir": str(getattr(package, "package_dir", "") or ""),
        "editable_submeshes": int(getattr(package, "editable_submesh_count", 0) or 0),
        "reference_submeshes": int(getattr(package, "reference_submesh_count", 0) or 0),
        "material_signature": "geometry_only",
    }


def _synthetic_mesh_renderer_evidence(
    widget: QWidget,
    *,
    expected_source_identity: str,
) -> dict[str, object] | None:
    package_evidence = _synthetic_mesh_package_evidence(
        widget,
        expected_source_identity=expected_source_identity,
    )
    if package_evidence is None:
        return None
    host = getattr(widget, "standalone_native_host_frame", None)
    controller = getattr(host, "controller", None)
    if controller is None:
        raise RuntimeError("Compact Mesh capture could not find the resident .NET/Vortice host.")
    status = getattr(widget, "standalone_dotnet_status_payload", {})
    renderer = status.get("renderer") if isinstance(status, Mapping) else None
    renderer_payload = dict(renderer) if isinstance(renderer, Mapping) else {}
    backend = str(renderer_payload.get("backend", "") or "")
    if backend and backend != EXPECTED_MESH_RENDERER_BACKEND:
        raise RuntimeError(
            "Compact Mesh capture refused a non-production renderer backend: "
            f"{backend!r}."
        )
    package_dir = str(package_evidence["package_dir"])
    applied_package = str(getattr(controller, "applied_package_path", "") or "")
    applied_matches = bool(
        applied_package
        and os.path.normcase(os.path.abspath(applied_package))
        == os.path.normcase(os.path.abspath(package_dir))
    )
    capabilities = tuple(
        sorted(str(item) for item in getattr(widget, "standalone_dotnet_capabilities", ()) or ())
    )
    provenance_required = "helper_build_provenance_v1" in capabilities
    provenance_verified = bool(
        getattr(widget, "standalone_dotnet_provenance_verified", False)
    )
    readiness = {
        "process_running": bool(getattr(controller, "is_running", False)),
        "protocol_ready": bool(getattr(controller, "_protocol_ready", False)),
        "renderer_ready": bool(getattr(controller, "_renderer_ready", False)),
        "session_established": bool(getattr(controller, "_session_established", False)),
        "localization_established": bool(
            getattr(controller, "_localization_initial_established", False)
        ),
        "applied_package_matches": applied_matches,
        "serving_prewarm_placeholder": bool(
            getattr(controller, "serving_prewarm_placeholder", False)
        ),
        "provenance_verified": provenance_verified,
    }
    ready = bool(
        backend == EXPECTED_MESH_RENDERER_BACKEND
        and all(
            readiness[key]
            for key in (
                "process_running",
                "protocol_ready",
                "renderer_ready",
                "session_established",
                "localization_established",
                "applied_package_matches",
            )
        )
        and not readiness["serving_prewarm_placeholder"]
        and (not provenance_required or provenance_verified)
    )
    if not ready:
        return None
    native_available = bool(getattr(widget, "standalone_native_editor_available", False))
    if not native_available:
        raise RuntimeError(
            "Compact Mesh capture requires the resident cdmw_mesh_core edit backend; it is unavailable."
        )
    return {
        **package_evidence,
        "helper_profile": "authoring",
        "renderer_backend": backend,
        "edit_backend": EXPECTED_MESH_EDIT_BACKEND,
        "process_id": int(getattr(controller, "process_id", 0) or 0),
        "capabilities": list(capabilities),
        "readiness": readiness,
        "no_game_or_archive_data": True,
    }


def _wait_for_synthetic_mesh_renderer(
    widget: QWidget,
    *,
    expected_source_identity: str,
) -> dict[str, object]:
    evidence: dict[str, object] = {}

    def renderer_is_ready() -> bool:
        current = _synthetic_mesh_renderer_evidence(
            widget,
            expected_source_identity=expected_source_identity,
        )
        if current is None:
            return False
        evidence.update(current)
        return True

    if _wait_until(
        renderer_is_ready,
        timeout_seconds=MESH_RENDERER_READY_TIMEOUT_SECONDS,
    ):
        return evidence
    status_label = getattr(widget, "standalone_status_label", None)
    status_text = str(status_label.text() if status_label is not None else "").strip()
    stderr_tail = str(getattr(widget, "standalone_dotnet_stderr_tail", "") or "").strip()
    host = getattr(widget, "standalone_native_host_frame", None)
    controller = getattr(host, "controller", None)
    retry_reason = str(getattr(controller, "_retry_reason", "") or "").strip()
    controller_stderr = str(getattr(controller, "_stderr_tail", "") or "").strip()
    controller_stdout = str(getattr(controller, "_stdout_tail", "") or "").strip()
    last_event = getattr(controller, "_last_event", None)
    controller_state = {
        "running": bool(getattr(controller, "is_running", False)),
        "visible": bool(getattr(controller, "_visible", False)),
        "closed": bool(getattr(controller, "_closed", False)),
        "process_generation": int(getattr(controller, "_process_generation", 0) or 0),
        "package_generation": int(getattr(controller, "_package_generation", 0) or 0),
        "has_desired_package": getattr(controller, "_desired_package", None) is not None,
    }
    package_thread = getattr(widget, "standalone_dotnet_package_thread", None)
    try:
        package_thread_running = bool(package_thread is not None and package_thread.isRunning())
    except RuntimeError:
        package_thread_running = False
    package_state = {
        "request_id": int(getattr(widget, "standalone_dotnet_package_request_id", 0) or 0),
        "worker_present": getattr(widget, "standalone_dotnet_package_worker", None) is not None,
        "thread_present": package_thread is not None,
        "thread_running": package_thread_running,
    }
    status_messages = tuple(
        str(value)
        for value in getattr(widget, "_cdmw_compact_mesh_status_messages", ())
    )
    detail = " | ".join(
        part
        for part in (
            status_text,
            f"controller={controller_state!r}",
            f"package={package_state!r}",
            f"status_messages={status_messages!r}" if status_messages else "",
            retry_reason,
            stderr_tail[-800:],
            controller_stderr[-800:],
            controller_stdout[-800:],
            f"last_event={last_event!r}" if last_event else "",
        )
        if part
    )
    raise RuntimeError(
        "Bundled resident .NET/Vortice helper did not become ready for the synthetic Mesh package "
        f"within {MESH_RENDERER_READY_TIMEOUT_SECONDS:.0f}s"
        + (f": {detail}" if detail else ".")
    )
