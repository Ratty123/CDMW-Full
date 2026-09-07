"""Read-only mesh loading for an additive Free Edit refit workspace."""

from __future__ import annotations

from pathlib import Path

from cdmw.core.common import read_file_bytes_cancellable
from cdmw.domain.cancellation import RunCancelled
from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.modding.mesh_glb_interchange import import_glb_with_sidecar
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.modding.mesh_parser import ParsedMesh, parse_mesh


MAX_REFIT_INPUT_BYTES = 256 * 1024 * 1024


def append_refit_mesh(current: ParsedMesh, path: str, role: str, *, stop_event=None):
    """Append to a caller-owned clone; never change the source file or live mesh."""
    if role not in {"body", "armor"}:
        raise ValueError("Refit mesh role must be body or armor")
    source = Path(path).expanduser().resolve(strict=True)
    suffix = source.suffix.lower()
    if suffix not in {".pac", ".pam", ".pamlod", ".obj", ".glb"}:
        raise ValueError("Load a PAC, PAM, PAMLOD, OBJ, or GLB mesh")
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_REFIT_INPUT_BYTES:
        raise ValueError("Refit mesh input must be a non-empty file no larger than 256 MiB")
    if stop_event is not None and stop_event.is_set():
        raise RunCancelled("Refit mesh loading cancelled")
    if suffix == ".glb":
        imported = import_glb_with_sidecar(source)
    elif suffix == ".obj":
        imported = import_obj(str(source))
    else:
        data = read_file_bytes_cancellable(str(source), stop_event=stop_event, max_bytes=MAX_REFIT_INPUT_BYTES)
        if len(data) > MAX_REFIT_INPUT_BYTES:
            raise ValueError("Refit mesh input exceeds 256 MiB")
        imported = parse_mesh(data, str(source))
    if stop_event is not None and stop_event.is_set():
        raise RunCancelled("Refit mesh loading cancelled")
    if not imported.submeshes or not any(part.faces for part in imported.submeshes):
        raise ValueError("Refit mesh has no usable triangle geometry")
    first = len(current.submeshes)
    for index, part in enumerate(imported.submeshes):
        part.name = f"{role.title()} / {source.stem} / {part.name or f'Part {index + 1}'}"
        # Appended geometry has no mapping to the original output asset.
        part.source_vertex_map = []
        part.source_vertex_map_authority = ""
        part.source_vertex_offsets = []
        part.source_index_offset = -1
        part.source_descriptor_offset = -1
        part.topology_provenance = None
    current.submeshes.extend(imported.submeshes)
    current.has_bones = current.has_bones or imported.has_bones
    current.has_uvs = current.has_uvs or imported.has_uvs
    refresh_mesh_totals(current)
    return current, tuple(range(first, len(current.submeshes)))


def stage_refit_morph_runtime(service, session_id, combined, *, driver_indices=None):
    """Rebuild a zero-preview runtime against the new Part table before publication."""
    from cdmw.services.mesh_service import MeshService
    from cdmw.services.mesh_service_state import _MeshMorphSessionState

    cache = service._morph_sessions.get(session_id)
    if (cache is None or cache.profile is None) and driver_indices is None:
        return _MeshMorphSessionState(present=False)
    from dataclasses import replace
    from cdmw.domain.mesh.morph import MeshMorphProfile, mesh_morph_driver_topology_fingerprint

    profile = cache.profile if cache is not None else None
    definitions = profile.definitions if profile is not None else ()
    fingerprint = mesh_morph_driver_topology_fingerprint(combined, definitions)
    profile = replace(profile, topology_fingerprint=fingerprint) if profile is not None else MeshMorphProfile(
        profile_id="archive-refit", name="Body & Armor", topology_fingerprint=fingerprint,
    )
    staged = MeshService(settings=service.settings)
    staged_id = staged.open_edit_session(combined, mode="edit").session_id
    try:
        staged.prime_morph_profile_cache(staged_id, freeze=True)
        staged._activate_morph_profile_locked(staged._session(staged_id), profile)
        staged_cache = staged._morph_sessions[staged_id]
        staged_cache.topology_mesh = staged.working_mesh(staged_id, clone=True)
        if cache is not None:
            staged_cache.known_profiles.update(cache.known_profiles)
            staged_cache.known_presets.update(cache.known_presets)
        if driver_indices is not None:
            staged.set_refit_driver(staged_id, driver_indices)
        elif cache is not None and cache.state is not None:
            state = cache.state
            if state.driver_submesh_indices:
                staged.set_refit_driver(staged_id, state.driver_submesh_indices)
        return staged.capture_morph_session_state(staged_id)
    finally:
        staged.close_edit_session(staged_id, force_without_saving=True)
