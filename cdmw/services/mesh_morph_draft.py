"""Checked Morph & Refit payloads owned by an atomic geometry draft generation."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
from uuid import uuid4

from cdmw.core.atomic_file import atomic_write_text
from cdmw.services.mesh_morph_profiles import mesh_morph_profile_from_payload, mesh_morph_profile_payload


_MAX_BYTES = 256 * 1024 * 1024


def capture_morph_draft(service, session):
    cache = service._morph_sessions.get(session.session_id)
    if cache is None or cache.profile is None:
        return None
    if cache.authoring_baseline is not None or cache.correction_capture is not None:
        raise ValueError("Finish or cancel slider capture before saving a Morph & Refit draft.")
    state = service._capture_morph_session_state_locked(session)
    try:
        return {
            "format": "cdmw.morph_draft.v2",
            "native": Path(state.native_snapshot["path"]).read_text(encoding="utf-8"),
            "profile": mesh_morph_profile_payload(cache.profile),
            "preset_id": cache.preset_id,
            "manual_values": cache.manual_values,
            "macro_values": cache.macro_values,
            "symmetry_enabled": cache.symmetry_enabled,
            "corrections_enabled": cache.corrections_enabled,
        }
    finally:
        service.dispose_morph_session_state(state)


def persist_morph_draft(payload, generation_dir, project_root):
    path = generation_dir / "morph.json"
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_BYTES:
        raise ValueError("Morph & Refit draft size does not match.")
    atomic_write_text(path, encoded.decode("utf-8"))
    return {"path": path.relative_to(project_root).as_posix(), "size": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest()}


def load_morph_draft(descriptor, project_root):
    if not isinstance(descriptor, dict):
        raise ValueError("Morph & Refit draft omitted its runtime state.")
    path = (project_root / str(descriptor.get("path", ""))).resolve()
    if project_root.resolve() not in path.parents or not path.is_file():
        raise ValueError("Morph & Refit draft path escapes its project or is missing.")
    if not 0 < path.stat().st_size == descriptor.get("size", 0) <= _MAX_BYTES:
        raise ValueError("Morph & Refit draft size does not match.")
    with path.open("rb") as stream:
        encoded = stream.read(_MAX_BYTES + 1)
    if len(encoded) != descriptor.get("size") or hashlib.sha256(encoded).hexdigest() != descriptor.get("sha256"):
        raise ValueError("Morph & Refit draft checksum does not match.")
    payload = json.loads(encoded)
    if not isinstance(payload, dict) or payload.get("format") != "cdmw.morph_draft.v2":
        raise ValueError("Unsupported Morph & Refit draft format.")
    if not isinstance(payload.get("native"), str) or not isinstance(payload.get("profile"), dict):
        raise ValueError("Morph & Refit draft omitted its snapshot or profile.")
    native = json.loads(payload["native"])
    if not isinstance(native, dict) or native.get("version") != 2:
        raise ValueError("Morph & Refit draft requires a version 2 native snapshot.")
    runtime = native.get("runtime")
    if not isinstance(runtime, dict) or not isinstance(runtime.get("profile"), dict):
        raise ValueError("Morph & Refit draft omitted its native profile.")
    profile = mesh_morph_profile_from_payload(payload["profile"])
    if runtime["profile"].get("profile_id") != profile.profile_id:
        raise ValueError("Morph & Refit draft profile does not match its native state.")
    for key in ("symmetry_enabled", "corrections_enabled"):
        if type(payload.get(key)) is not bool:
            raise ValueError("Morph & Refit draft has invalid control flags.")
    for key in ("manual_values", "macro_values"):
        values = payload.get(key)
        if key == "manual_values" and values is None:
            continue
        if not isinstance(values, dict) or any(
            not isinstance(name, str) or isinstance(value, bool)
            or not isinstance(value, (int, float)) or not math.isfinite(value)
            for name, value in values.items()
        ):
            raise ValueError("Morph & Refit draft has invalid control values.")
    return payload


def restore_morph_draft(service, session, payload):
    from cdmw.services.mesh_service_morph import _MeshMorphSessionData
    from cdmw.services.mesh_service_state import _MeshMorphSessionState

    profile = mesh_morph_profile_from_payload(payload["profile"])
    native_text = payload["native"]
    native = json.loads(native_text)
    encoded = native_text.encode("utf-8")
    path = Path(tempfile.gettempdir()) / f"cdmw_mesh_preview_delta_{uuid4().hex}_morph_runtime_snapshot.json"
    descriptor = {key: native[key] for key in ("schema", "version", "snapshot_id", "source_session_id", "topology_digest")}
    # Retained bytes measure the in-memory runtime, independently of JSON spacing.
    descriptor.update(path=str(path), sha256=hashlib.sha256(encoded).hexdigest(), byte_length=len(encoded),
                      retained_bytes=int(native["retained_bytes"]))
    cache = _MeshMorphSessionData(profile=profile, known_profiles={profile.profile_id: profile},
                                 preset_id=str(payload.get("preset_id") or ""))
    cache.topology_mesh = copy.deepcopy(session.working_mesh)
    for row in native["runtime"].get("neutral_positions", ()):
        cache.topology_mesh.submeshes[row["submesh_index"]].vertices = [tuple(v) for v in row["positions"]]
    for key in ("manual_values", "macro_values", "symmetry_enabled", "corrections_enabled"):
        if key in payload:
            setattr(cache, key, copy.deepcopy(payload[key]))
    state = _MeshMorphSessionState(present=True, native_snapshot=descriptor, cache=cache,
                                  retained_bytes=descriptor["retained_bytes"])
    try:
        path.write_bytes(encoded)
        service._install_morph_session_state_locked(session, state, reconcile_profiles=False)
    finally:
        service.dispose_morph_session_state(state)
