"""Checked Morph & Refit payloads owned by an atomic geometry draft generation."""
from __future__ import annotations

import copy
import hashlib
import io
import math
from pathlib import Path
import tempfile
from uuid import uuid4

from cdmw.core.atomic_file import atomic_text_writer
from cdmw.core.streaming_json import read_json, write_json
from cdmw.services.mesh_morph_profiles import mesh_morph_profile_from_payload, _streamed_profile_payload, _read_object_stream


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class _CheckedReader(io.RawIOBase):
    """Hash exactly the bytes decoded, including across concurrent file writes."""
    def __init__(self, stream):
        super().__init__()
        self.stream = stream
        self.digest = hashlib.sha256()
        self.size = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        count = self.stream.readinto(buffer)
        self.digest.update(memoryview(buffer)[:count])
        self.size += count
        return count


def capture_morph_draft(service, session):
    cache = service._morph_sessions.get(session.session_id)
    if cache is None or cache.profile is None:
        return None
    if cache.authoring_baseline is not None or cache.correction_capture is not None:
        raise ValueError("Finish or cancel slider capture before saving a Morph & Refit draft.")
    state = service._capture_morph_session_state_locked(session)
    try:
        return {
            "format": "cdmw.morph_draft.v3" if state.native_snapshot["version"] == 3 else "cdmw.morph_draft.v2",
            "native": Path(state.native_snapshot["path"]).read_text(encoding="utf-8"),
            "profile": _streamed_profile_payload(cache.profile),
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
    with atomic_text_writer(path) as stream:
        write_json(stream, payload)
    return {"path": path.relative_to(project_root).as_posix(), "size": path.stat().st_size,
            "sha256": _file_sha256(path)}


def load_morph_draft(descriptor, project_root):
    if not isinstance(descriptor, dict):
        raise ValueError("Morph & Refit draft omitted its runtime state.")
    path = (project_root / str(descriptor.get("path", ""))).resolve()
    if project_root.resolve() not in path.parents or not path.is_file():
        raise ValueError("Morph & Refit draft path escapes its project or is missing.")
    if not 0 < path.stat().st_size == descriptor.get("size", 0):
        raise ValueError("Morph & Refit draft size does not match.")
    with path.open("rb") as source:
        checked = _CheckedReader(source)
        with io.TextIOWrapper(io.BufferedReader(checked), encoding="utf-8-sig") as stream:
            payload = _read_object_stream(stream, parse_definitions=True)
    if checked.size != descriptor.get("size") or checked.digest.hexdigest() != descriptor.get("sha256"):
        raise ValueError("Morph & Refit draft checksum does not match.")
    if not isinstance(payload, dict) or payload.get("format") not in {"cdmw.morph_draft.v2", "cdmw.morph_draft.v3"}:
        raise ValueError("Unsupported Morph & Refit draft format.")
    if not isinstance(payload.get("native"), str) or not isinstance(payload.get("profile"), dict):
        raise ValueError("Morph & Refit draft omitted its snapshot or profile.")
    native = read_json(io.StringIO(payload["native"]))
    expected_version = 3 if payload["format"] == "cdmw.morph_draft.v3" else 2
    if not isinstance(native, dict) or native.get("version") != expected_version:
        raise ValueError("Morph & Refit draft native snapshot version does not match its format.")
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
    native = read_json(io.StringIO(native_text))
    path = Path(tempfile.gettempdir()) / f"cdmw_mesh_preview_delta_{uuid4().hex}_morph_runtime_snapshot.json"
    descriptor = {key: native[key] for key in ("schema", "version", "snapshot_id", "source_session_id", "topology_digest")}
    # Retained bytes measure the in-memory runtime, independently of JSON spacing.
    cache = _MeshMorphSessionData(profile=profile, known_profiles={profile.profile_id: profile},
                                 preset_id=str(payload.get("preset_id") or ""))
    cache.topology_mesh = copy.deepcopy(session.working_mesh)
    for row in native["runtime"].get("neutral_positions", ()):
        cache.topology_mesh.submeshes[row["submesh_index"]].vertices = [tuple(v) for v in row["positions"]]
    for key in ("manual_values", "macro_values", "symmetry_enabled", "corrections_enabled"):
        if key in payload:
            setattr(cache, key, copy.deepcopy(payload[key]))
    state = None
    try:
        with path.open("w", encoding="utf-8", newline="") as stream:
            for start in range(0, len(native_text), 64 * 1024):
                stream.write(native_text[start:start + 64 * 1024])
        descriptor.update(path=str(path), sha256=_file_sha256(path), byte_length=path.stat().st_size,
                          retained_bytes=int(native["retained_bytes"]))
        state = _MeshMorphSessionState(present=True, native_snapshot=descriptor, cache=cache,
                                      retained_bytes=descriptor["retained_bytes"])
        service._install_morph_session_state_locked(session, state, reconcile_profiles=False)
    finally:
        if state is not None:
            service.dispose_morph_session_state(state)
        else:
            path.unlink(missing_ok=True)
