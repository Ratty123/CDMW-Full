"""Detached replacement preparation; publication uses the existing transaction."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from uuid import uuid4

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.mesh.replacement import (
    MeshReplacementState, ReplacementPart, ReplacementFile, PART_ID_ATTRIBUTE,
    REPLACEMENT_POLICY, bound_part_indices,
)
from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs
from cdmw.modding.mesh_totals import refresh_mesh_totals
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.modding.static_mesh_replacer import (
    _clone_parsed_mesh_fast, build_static_replacement_preview_mesh,
    StaticSubmeshMapping, suggest_static_submesh_mappings,
)
from cdmw.services.mesh_replacement_output import manual_replacement_options, prepare_replacement_output
from cdmw.services.mesh_service_native_clone import _clone_mesh_for_service_native_snapshot


def archive_location(entry):
    return (str(entry.pamt_path), str(entry.paz_file), entry.offset, entry.comp_size,
            entry.orig_size, entry.flags, entry.paz_index)


def archive_entry(file: ReplacementFile):
    from cdmw.models import ArchiveEntry
    if file.archive_location is None:
        return None
    pamt, paz, offset, comp_size, orig_size, flags, paz_index = file.archive_location
    return ArchiveEntry(file.path, Path(pamt), Path(paz), offset, comp_size, orig_size, flags, paz_index)


def initial_replacement_state(snapshot, entry=None, dependencies=()):
    if snapshot.archive_refit_context is not None:
        raise ValueError("Undo the active Morph & Refit archive bindings before using replacement.")
    if not snapshot.original_data or snapshot.mesh.format.lower() not in {"pac", "pam", "pamlod"}:
        raise ValueError("Replacement requires an eligible original PAC, PAM or PAMLOD archive mesh.")
    original = parse_mesh(snapshot.original_data, snapshot.mesh.path)
    if len(original.submeshes) != len(snapshot.mesh.submeshes):
        raise ValueError("Replacement requires the original target part layout. Undo added or deleted parts first.")
    digest = hashlib.sha256(snapshot.original_data).hexdigest()
    parts = tuple(ReplacementPart(f"{digest[:16]}:{index}", index) for index in range(len(original.submeshes)))
    return MeshReplacementState(
        str(snapshot.mesh.path), digest, parts,
        target_location=archive_location(entry) if entry is not None else None,
        dependencies=tuple(dependencies),
    )


def mesh_with_part_ids(snapshot, state):
    mesh = _clone_mesh_for_service_native_snapshot(snapshot.mesh, "replacement.compose", "Replacement snapshot failed")
    if snapshot.replacement_state is None:
        for part, binding in zip(mesh.submeshes, state.parts):
            setattr(part, PART_ID_ATTRIBUTE, binding.part_id)
    bound_part_indices(mesh, state)
    return mesh


@dataclass(frozen=True, slots=True)
class PendingMeshReplacement:
    snapshot: object
    state: MeshReplacementState
    source: object
    source_path: str
    source_sha256: str
    target_part_ids: tuple[str, ...]
    suggested_targets: tuple[str, ...]
    token: str
    source_files: tuple[tuple[str, str], ...] = ()
    material_source_files: tuple[tuple[str, str], ...] = ()
    material_error: str = ""


def _import_source_files(path, *, include_materials=True):
    """Keep required geometry separate from optional imported materials."""
    from urllib.parse import unquote
    from cdmw.modding.scene_texture_discovery import (
        _obj_material_texture_references, _obj_material_library_paths,
        _resolve_local_texture_reference,
    )
    files, references = [path], []
    if include_materials and path.suffix.lower() == ".obj":
        libraries = _obj_material_library_paths(path)
        explicit = {str((path.parent / value).resolve()) for line in path.read_text(encoding="utf-8-sig").splitlines()
                    if line.lstrip().lower().startswith("mtllib ") for value in line.strip()[7:].split()}
        for library in libraries:
            if library.is_file():
                files.append(library)
            elif str(library) in explicit:
                raise ValueError(f"Missing imported material library: {library}")
        references = list(_obj_material_texture_references(path))
    elif include_materials and path.suffix.lower() == ".dae":
        from xml.etree import ElementTree
        root = ElementTree.parse(path).getroot()
        references = [node.text.strip() for image in root.iter() if image.tag.rsplit("}", 1)[-1] == "image"
                      for node in image.iter() if node.tag.rsplit("}", 1)[-1] in {"init_from", "ref"} and node.text and node.text.strip()]
    elif path.suffix.lower() in {".gltf", ".glb"}:
        if path.suffix.lower() == ".glb":
            from cdmw.modding.scene_gltf_import import _read_glb
            document, _ = _read_glb(path)
        else:
            import json
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        resources = list(document.get("buffers", ()))
        if include_materials:
            resources.extend(document.get("images", ()))
        for item in resources:
            uri = str(item.get("uri", ""))
            if uri and not uri.startswith("data:"):
                local = path.parent / unquote(uri)
                if not local.is_file():
                    raise ValueError(f"Missing imported dependency: {uri}")
                files.append(local)
    for reference in references:
        resolved = _resolve_local_texture_reference(path, reference)
        if resolved is None:
            raise ValueError(f"Missing imported texture: {reference}")
        files.append(resolved)
    return tuple(dict.fromkeys(file.resolve() for file in files))


def verify_import_sources(pending, *, include_materials=False):
    if include_materials and pending.material_error:
        raise ValueError(pending.material_error)
    files = pending.source_files + (pending.material_source_files if include_materials else ())
    for path, digest in files:
        try:
            unchanged = hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        except OSError:
            unchanged = False
        if not unchanged:
            raise ValueError(f"Imported dependency changed during preparation: {path}. Import again.")


def prepare_import(snapshot, path, *, target_part_ids=(), entry=None, dependencies=(), stop_event=None):
    """Run on the managed protocol worker. The existing session is untouched."""
    from cdmw.modding.scene_importer import import_scene_mesh_with_report
    raise_if_cancelled(stop_event, "Replacement import cancelled.")
    source_path = Path(path).expanduser().resolve(strict=True)
    if source_path.suffix.lower() not in {".obj", ".dae", ".gltf", ".glb"}:
        raise ValueError("Choose an OBJ, DAE, glTF or GLB replacement.")
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    chosen = tuple(target_part_ids) or tuple(part.part_id for part in state.parts)
    if len(set(chosen)) != len(chosen) or not set(chosen).issubset({part.part_id for part in state.parts}):
        raise ValueError("The selected replacement parts are no longer available.")
    captured = {str(file): hashlib.sha256(file.read_bytes()).hexdigest()
                for file in _import_source_files(source_path, include_materials=False)}
    digest = captured[str(source_path)]
    material_files, material_error = {}, ""
    try:
        material_files = {str(file): hashlib.sha256(file.read_bytes()).hexdigest()
                          for file in _import_source_files(source_path) if str(file) not in captured}
    except (OSError, ValueError) as exc:
        # The material choice follows geometry preparation. Retain its failure
        # for imported-material mode without blocking Keep Original Materials.
        material_error = str(exc)
    source = import_scene_mesh_with_report(source_path, tolerate_missing_texture_files=True, stop_event=stop_event)
    if not source.mesh.submeshes or not source.mesh.total_faces:
        raise ValueError("The imported model has no editable triangle geometry.")
    if source.mesh.has_bones or any(part.bone_weights for part in source.mesh.submeshes):
        raise ValueError("Imported skinning is not supported by this replacement workflow. Import an unskinned model.")
    if not material_error:
        try:
            for binding in source.material_bindings:
                for role, texture_path in binding.texture_slots:
                    if not Path(texture_path).is_file():
                        raise ValueError(f"Missing imported {role} texture: {texture_path}")
            for file in source.discovered_texture_files:
                material_files.setdefault(str(file), hashlib.sha256(Path(file).read_bytes()).hexdigest())
        except (OSError, ValueError) as exc:
            material_error = str(exc)
    mesh = mesh_with_part_ids(snapshot, state)
    indices = bound_part_indices(mesh, state)
    target = _clone_parsed_mesh_fast(mesh)
    target.submeshes = [mesh.submeshes[indices[key]] for key in chosen]
    suggestions = suggest_static_submesh_mappings(target, source.mesh)
    suggested = [""] * len(source.mesh.submeshes)
    for mapping in suggestions:
        for index in mapping.source_submesh_indices:
            if 0 <= index < len(suggested) and 0 <= mapping.target_submesh_index < len(chosen):
                suggested[index] = chosen[mapping.target_submesh_index]
    raise_if_cancelled(stop_event, "Replacement import cancelled.")
    pending = PendingMeshReplacement(snapshot, state, source, str(source_path), digest, chosen, tuple(suggested), uuid4().hex,
                                    tuple(captured.items()), tuple(material_files.items()), material_error)
    verify_import_sources(pending)
    return pending


def compose_import(pending, source_targets, *, material_choice="original", companion_files=None):
    """Compose a full editable candidate without collapsing any excluded part."""
    if material_choice not in {"original", "imported"}:
        raise ValueError("Choose original or imported materials.")
    verify_import_sources(pending, include_materials=material_choice == "imported")
    if material_choice == "imported" and companion_files is None:
        raise ValueError("Imported materials require a complete prepared material and texture bundle.")
    targets = tuple(str(value) for value in source_targets)
    if len(targets) != len(pending.source.mesh.submeshes) or any(key not in pending.target_part_ids for key in targets):
        raise ValueError("Choose a target part for every imported part before applying replacement.")
    candidate = mesh_with_part_ids(pending.snapshot, pending.state)
    indices = bound_part_indices(candidate, pending.state)
    mappings = [StaticSubmeshMapping(
        indices[key], candidate.submeshes[indices[key]].name,
        [index for index, target in enumerate(targets) if target == key], indices[key],
    ) for key in pending.target_part_ids]
    preview = build_static_replacement_preview_mesh(candidate, pending.source.mesh, manual_replacement_options(mappings))
    parts = []
    for binding in pending.state.parts:
        if binding.part_id not in pending.target_part_ids:
            parts.append(binding)
            continue
        index = indices[binding.part_id]
        source_indices = [i for i, target in enumerate(targets) if target == binding.part_id]
        if not source_indices:
            parts.append(replace(binding, included=False))
            continue
        donor = candidate.submeshes[index]
        imported = preview.submeshes[index]
        if material_choice == "imported" and len(source_indices) != 1:
            raise ValueError("Imported materials require one source material part per target part. Split the mapping before applying.")
        # Keep target ownership and original preview metadata. Imported material
        # presentation comes from the prepared sidecar/DDS bundle, not source paths.
        imported.name, imported.material, imported.texture = donor.name, donor.material, donor.texture
        copy_extra_submesh_attrs(donor, imported)
        if pending.state.neutral_appearance is not None:
            # Transfer on the displayed target surface before any inverse
            # transform. Never let the writer guess weights in source space.
            from cdmw.modding.mesh_skinning import ensure_final_target_skin_weights, SOURCE_VERTEX_MAP_TOPOLOGY
            imported.source_vertex_map_authority = SOURCE_VERTEX_MAP_TOPOLOGY
            ensure_final_target_skin_weights(imported, donor, target_index=index, summary=None)
        setattr(imported, PART_ID_ATTRIBUTE, binding.part_id)
        candidate.submeshes[index] = imported
        parts.append(replace(binding, included=True, material_choice=material_choice,
            source_label=Path(pending.source_path).name,
            source_part_ids=tuple(f"{pending.source_sha256}:{i}" for i in source_indices),
            import_positions=tuple(tuple(float(v) for v in position) for position in imported.vertices),
            import_normals=tuple(tuple(float(v) for v in normal) for normal in imported.normals)))
    refresh_mesh_totals(candidate)
    if material_choice == "original" and companion_files is None:
        from cdmw.services.mesh_replacement_materials import restore_original_materials
        companion_files = restore_original_materials(pending, targets)
    state = replace(pending.state, parts=tuple(parts), revision=pending.state.revision + 1,
                    companion_files=tuple(companion_files) if companion_files is not None else pending.state.companion_files)
    return candidate, state


def commit_replacement(service, snapshot, candidate, state, *, label, stop_event=None):
    raise_if_cancelled(stop_event, "Replacement cancelled.")
    session = service._session(snapshot.session_id)
    with session.export_lock:
        if session.revision != snapshot.mesh_revision or session.closed:
            raise ValueError("Replacement is stale because the mesh changed. Import again.")
    prepared = service.prepare_working_mesh_replacement(snapshot.session_id, candidate,
        replacement_state=state, validation_output_policy=REPLACEMENT_POLICY)
    if prepared.expected_revision != snapshot.mesh_revision:
        raise ValueError("Replacement is stale because the mesh changed. Import again.")
    # Prove the final writer before touching live geometry, materials or history.
    output = prepare_replacement_output(replace(snapshot, mesh=candidate, replacement_state=state))
    raise_if_cancelled(stop_event, "Replacement cancelled.")
    view = service.commit_prepared_working_mesh_replacement(prepared,
        history_action="mesh_replacement", history_label=label,
        output_policy=REPLACEMENT_POLICY, require_reversible_history=True)
    with session.export_lock:
        if session.revision == view.revision:
            report = replace(output.report, export_snapshot={
                **output.report.export_snapshot, "mesh_revision": view.revision,
            })
            session.replacement_output = replace(output, report=report,
                revision=(view.revision, view.revision, session.material_generation))
    return view


def set_part_inclusion(service, snapshot, part_ids, included, *, entry=None, dependencies=(), stop_event=None):
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    keys = set(part_ids)
    if not keys or not keys.issubset({part.part_id for part in state.parts}):
        raise ValueError("Choose valid parts to include in the mod.")
    candidate = mesh_with_part_ids(snapshot, state)
    state = replace(state, revision=state.revision + 1,
        parts=tuple(replace(part, included=bool(included)) if part.part_id in keys else part for part in state.parts))
    return commit_replacement(service, snapshot, candidate, state, label="Include parts in mod" if included else "Exclude parts from mod", stop_event=stop_event)


def reset_or_fit_import(service, snapshot, *, fit=False, stop_event=None):
    state = snapshot.replacement_state
    if state is None or not any(part.import_positions for part in state.parts):
        raise ValueError("Import a replacement before adjusting its placement.")
    candidate = mesh_with_part_ids(snapshot, state)
    indices = bound_part_indices(candidate, state)
    affected = [part for part in state.parts if part.import_positions]
    points = [point for part in affected for point in part.import_positions]
    source_min = tuple(min(point[axis] for point in points) for axis in range(3))
    source_max = tuple(max(point[axis] for point in points) for axis in range(3))
    scale, offset = 1.0, (0.0, 0.0, 0.0)
    if fit:
        original = parse_mesh(snapshot.original_data, state.target_path)
        if state.neutral_appearance is not None:
            original = state.neutral_appearance.to_neutral(original)
        reference = [point for part in affected for point in original.submeshes[part.target_index].vertices]
        low = tuple(min(point[axis] for point in reference) for axis in range(3))
        high = tuple(max(point[axis] for point in reference) for axis in range(3))
        lengths = [source_max[axis] - source_min[axis] for axis in range(3)]
        ratios = [(high[axis] - low[axis]) / length for axis, length in enumerate(lengths)
                  if length > 1e-12 and high[axis] - low[axis] > 1e-12]
        scale = min(ratios) if ratios else 0.0
        if scale <= 0:
            raise ValueError("The original mesh bounds cannot provide a usable uniform fit.")
        offset = tuple((low[axis] + high[axis] - scale * (source_min[axis] + source_max[axis])) / 2 for axis in range(3))
    for binding in affected:
        part = candidate.submeshes[indices[binding.part_id]]
        if len(part.vertices) != len(binding.import_positions):
            raise ValueError("Import topology changed; undo topology edits before resetting placement.")
        if binding.import_normals is None:
            raise ValueError("This older replacement draft has no saved import normals. Import the model again before using Reset Placement or Fit to Original.")
        if len(binding.import_normals) not in {0, len(binding.import_positions)}:
            raise ValueError("Saved import normals do not match the replacement geometry.")
        part.vertices = [tuple(point[axis] * scale + offset[axis] for axis in range(3)) for point in binding.import_positions]
        part.normals = list(binding.import_normals)
    from cdmw.services.mesh_service_kernel import _invalidate_tangents_after_edit
    _invalidate_tangents_after_edit(candidate, "transform", {indices[part.part_id] for part in affected},
                                    None, topology_changed=False)
    refresh_mesh_totals(candidate)
    return commit_replacement(service, snapshot, candidate, replace(state, revision=state.revision + 1),
        label="Fit replacement to original" if fit else "Reset replacement placement", stop_event=stop_event)
