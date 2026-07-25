"""Build an authoritative scene frame the helper will accept.

NetSceneState.TryApplyResidentUpdate rejects anything without correlation
(session_id / source_identity / request_id / scene_generation) and without
HasValidAuthoritativeRoles: both "editable" and "reference" roles carrying a
16-float model_matrix and a world_bounds min<=max.
"""

from __future__ import annotations

import json
from pathlib import Path

IDENTITY_MATRIX = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]


def _role() -> dict:
    return {
        "model_matrix": list(IDENTITY_MATRIX),
        "world_bounds": {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
    }


def scene_identity(package_dir: Path) -> tuple[str, str, int]:
    """Session id, source identity and current generation from the package."""
    scene = json.loads((Path(package_dir) / "dotnet_scene.json").read_text(encoding="utf-8-sig"))
    return (
        str(scene.get("session_id", "") or ""),
        str(scene.get("source_identity", "") or ""),
        int(scene.get("scene_generation", 0) or 0),
    )


def mesh_edit_scene_update(
    package_dir: Path,
    *,
    request_id: int,
    process_generation: int = 1,
    interaction_mode: str = "mesh_edit",
) -> dict:
    session_id, source_identity, generation = scene_identity(package_dir)
    return {
        "event": "scene_state_update",
        "session_id": session_id,
        "source_identity": source_identity,
        "process_generation": process_generation,
        "protocol_version": 2,
        "request_id": request_id,
        "scene_generation": generation + request_id,
        "interaction_mode": interaction_mode,
        "comparison_mode": "replacement_only",
        "roles": {"editable": _role(), "reference": _role()},
        "grid": {"visible": False, "origin": [0.0, -1.0, 0.0], "spacing": 0.25},
        "gizmo": {"visible": False, "tool": "move"},
        "bounds": {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
    }
