"""Stable error codes for Mesh Editor failures.

A Mesh Editor failure used to be identifiable only by its message, and the
messages are written for the reader: they are localized, they name panes rather
than roles, and they get reworded. Nothing downstream -- a diagnostic bundle, a
support ticket, a regression test, a retry decision -- could key on them.

These codes are the stable half. They travel in runtime events and in the
diagnostic snapshot beside the human message, never instead of it, and they are
deliberately coarse: one code per thing a reader could actually do something
about, not one per raise site.
"""

from __future__ import annotations

from enum import Enum


class MeshEditorErrorCode(str, Enum):
    """Every code the Mesh Editor is allowed to report.

    Adding one is a contract change: the value is what a bundle or a test keys
    on, so values are never reworded once shipped, only deprecated.
    """

    # Material publication and textured view.
    MAT_IMPORT_MANIFEST_MISSING = "MAT_IMPORT_MANIFEST_MISSING"
    MAT_COMPILE_FAILED = "MAT_COMPILE_FAILED"
    MAT_PUBLICATION_STALE = "MAT_PUBLICATION_STALE"
    MAT_PUBLICATION_SEND_FAILED = "MAT_PUBLICATION_SEND_FAILED"
    MAT_ROLE_ACK_TIMEOUT = "MAT_ROLE_ACK_TIMEOUT"
    MAT_ROLE_UPDATE_REJECTED = "MAT_ROLE_UPDATE_REJECTED"
    MAT_REQUIRED_TEXTURE_MISSING = "MAT_REQUIRED_TEXTURE_MISSING"
    MAT_NO_TEXTURE_RESOURCES = "MAT_NO_TEXTURE_RESOURCES"

    # Display mode ownership.
    VIEW_MODE_STALE_UPDATE = "VIEW_MODE_STALE_UPDATE"
    VIEW_MODE_SEND_FAILED = "VIEW_MODE_SEND_FAILED"

    # Edit Mesh session and command correlation.
    EDIT_REQUEST_STALE = "EDIT_REQUEST_STALE"
    EDIT_SELECTION_GENERATION_MISMATCH = "EDIT_SELECTION_GENERATION_MISMATCH"
    EDIT_FINISH_PENDING_COMMANDS = "EDIT_FINISH_PENDING_COMMANDS"
    EDIT_SESSION_RECOVERY_REQUIRED = "EDIT_SESSION_RECOVERY_REQUIRED"

    # Writeback and topology safety.
    WRITEBACK_EXACT_WRITER_REQUIRED = "WRITEBACK_EXACT_WRITER_REQUIRED"
    WRITEBACK_TOPOLOGY_UNSUPPORTED = "WRITEBACK_TOPOLOGY_UNSUPPORTED"
    WRITEBACK_PROVENANCE_MISSING = "WRITEBACK_PROVENANCE_MISSING"
    WRITEBACK_OUTPUT_SIGNATURE_MISMATCH = "WRITEBACK_OUTPUT_SIGNATURE_MISMATCH"

    # Packaging.
    PACKAGE_RESOURCE_REFERENCE_MISSING = "PACKAGE_RESOURCE_REFERENCE_MISSING"
    PACKAGE_ATOMIC_COMMIT_FAILED = "PACKAGE_ATOMIC_COMMIT_FAILED"

    # Resident renderer lifecycle.
    RENDERER_PROCESS_UNAVAILABLE = "RENDERER_PROCESS_UNAVAILABLE"
    RENDERER_GENERATION_RETIRED = "RENDERER_GENERATION_RETIRED"


# What a reader can do about each code. These are deliberately not user-facing
# sentences: the UI phrases its own, localized. This is the machine-readable
# hint a diagnostic bundle and a retry decision both read.
RECOVERY_ACTION_BY_CODE: dict[MeshEditorErrorCode, str] = {
    MeshEditorErrorCode.MAT_IMPORT_MANIFEST_MISSING: "reresolve_imported_textures",
    MeshEditorErrorCode.MAT_COMPILE_FAILED: "retry_material_role",
    MeshEditorErrorCode.MAT_PUBLICATION_STALE: "none",
    MeshEditorErrorCode.MAT_PUBLICATION_SEND_FAILED: "restart_resident_renderer",
    MeshEditorErrorCode.MAT_ROLE_ACK_TIMEOUT: "retry_material_role",
    MeshEditorErrorCode.MAT_ROLE_UPDATE_REJECTED: "retry_material_role",
    MeshEditorErrorCode.MAT_REQUIRED_TEXTURE_MISSING: "reresolve_imported_textures",
    MeshEditorErrorCode.MAT_NO_TEXTURE_RESOURCES: "reresolve_imported_textures",
    MeshEditorErrorCode.VIEW_MODE_STALE_UPDATE: "none",
    MeshEditorErrorCode.VIEW_MODE_SEND_FAILED: "restart_resident_renderer",
    MeshEditorErrorCode.EDIT_REQUEST_STALE: "none",
    MeshEditorErrorCode.EDIT_SELECTION_GENERATION_MISMATCH: "reselect",
    MeshEditorErrorCode.EDIT_FINISH_PENDING_COMMANDS: "wait_for_pending_commands",
    MeshEditorErrorCode.EDIT_SESSION_RECOVERY_REQUIRED: "return_to_pre_edit_candidate",
    MeshEditorErrorCode.WRITEBACK_EXACT_WRITER_REQUIRED: "none",
    MeshEditorErrorCode.WRITEBACK_TOPOLOGY_UNSUPPORTED: "none",
    MeshEditorErrorCode.WRITEBACK_PROVENANCE_MISSING: "return_to_pre_edit_candidate",
    MeshEditorErrorCode.WRITEBACK_OUTPUT_SIGNATURE_MISMATCH: "none",
    MeshEditorErrorCode.PACKAGE_RESOURCE_REFERENCE_MISSING: "none",
    MeshEditorErrorCode.PACKAGE_ATOMIC_COMMIT_FAILED: "retry_build",
    MeshEditorErrorCode.RENDERER_PROCESS_UNAVAILABLE: "restart_resident_renderer",
    MeshEditorErrorCode.RENDERER_GENERATION_RETIRED: "none",
}


def recovery_action_for(code: object) -> str:
    """The recovery hint for a code, or ``unknown`` for anything unrecognised."""

    try:
        resolved = MeshEditorErrorCode(str(code.value if isinstance(code, Enum) else code))
    except (AttributeError, TypeError, ValueError):
        return "unknown"
    return RECOVERY_ACTION_BY_CODE.get(resolved, "unknown")


def error_payload(code: object, detail: str = "") -> dict[str, str]:
    """The event fields a failure carries: the stable code, a hint, and the detail."""

    resolved = str(code.value if isinstance(code, Enum) else (code or "")).strip()
    return {
        "error_code": resolved,
        "recovery_action": recovery_action_for(resolved),
        "error_detail": str(detail or ""),
    }


__all__ = [
    "RECOVERY_ACTION_BY_CODE",
    "MeshEditorErrorCode",
    "error_payload",
    "recovery_action_for",
]
