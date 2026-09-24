"""Worker-owned island discovery and reversible PAC output inclusion."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import numpy as np

from cdmw.domain.mesh.replacement import bound_part_indices
from cdmw.modding.mesh_islands import mesh_islands
from cdmw.services.mesh_replacement_import import (
    initial_replacement_state, mesh_with_part_ids, commit_replacement,
)


def island_ui_state(authoring, replacement):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    mesh = session.working_mesh
    selection = session.selection
    selected = set(selection.source_indices)
    for mapping in (selection.vertex_map(), selection.edge_map(), selection.face_map()):
        selected.update(mapping)
    selected = sorted(index for index in selected if 0 <= index < len(mesh.submeshes))
    if selected:
        authoring.mesh_island_focus = tuple(selected)
    else:
        selected = [index for index in authoring.mesh_island_focus if index < len(mesh.submeshes)]
    bindings = {part.target_index: part for part in session.replacement_state.parts} if session.replacement_state else {}
    cache = authoring.mesh_island_cache
    rows = []
    reason = replacement['reason']
    if session.mesh_format != 'pac':
        reason = 'Mod inclusion requires an original PAC; island selection and viewport controls remain available.'
    elif session.hair_state is not None:
        reason = 'Finish the hair workflow before changing island output.'
    for index in selected:
        part = mesh.submeshes[index]
        signature = hashlib.sha256(np.asarray(part.vertices, dtype='<f8').tobytes()
                                   + np.asarray(part.faces, dtype='<i8').tobytes()).digest()
        cached = cache.get(index)
        if cached is None or cached[0] != signature:
            groups = mesh_islands(part, stop_event=authoring._cancel_event)
            cache[index] = signature, groups
        else:
            groups = cached[1]
        binding = bindings.get(index)
        excluded = set(binding.excluded_island_faces) if binding else set()
        part_reason = reason
        if binding and binding.import_positions:
            part_reason = 'Save and reopen the imported PAC before using reversible island inclusion.'
        if binding and not binding.included:
            part_reason = 'Include this part in the mod before changing its islands.'
        part_id = next((row['id'] for row in replacement['parts'] if row['index'] == index), '')
        rows.append({'index': index, 'part_id': part_id, 'name': part.name,
                     'available': not part_reason, 'reason': part_reason,
                     'islands': [{'id': f'{index}:{faces[0]}', 'faces': list(faces),
                                  'included': not bool(excluded.intersection(faces))}
                                 for faces in groups]})
    # One current entry per part; no unbounded retention of old mesh versions.
    for index in set(cache).difference(range(len(mesh.submeshes))):
        del cache[index]
    return {'parts': rows, 'join_seams': True}


def set_island_inclusion(authoring, snapshot, args, *, entry=None, dependencies=(), stop_event=None):
    allowed = {'part_id', 'faces', 'included', '_archive_entry', '_archive_dependencies'}
    if set(args).difference(allowed) or type(args.get('included')) is not bool:
        raise ValueError('Invalid island inclusion request.')
    session = authoring.shadow_service._session(snapshot.session_id)
    if snapshot.mesh.format.lower() != 'pac' or session.lod_index != 0:
        raise ValueError('Reversible island inclusion requires an original PAC at LOD0.')
    if snapshot.hair_state is not None:
        raise ValueError('Finish the hair workflow before changing island output.')
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    part = next((part for part in state.parts if part.part_id == args.get('part_id')), None)
    if part is None or not part.included:
        raise ValueError('Choose a valid included part before changing islands.')
    if part.import_positions:
        raise ValueError('Save and reopen the imported PAC before using reversible island inclusion.')
    candidate = mesh_with_part_ids(snapshot, state)
    current = candidate.submeshes[bound_part_indices(candidate, state)[part.part_id]]
    values = args.get('faces')
    if (not isinstance(values, list) or not values or len(values) > len(current.faces)
            or any(type(v) is not int or not 0 <= v < len(current.faces) for v in values)
            or len(set(values)) != len(values)):
        raise ValueError('Choose valid island faces from the current part.')
    selected = set(values)
    groups = mesh_islands(current, stop_event=stop_event)
    if any(selected.intersection(group) and not selected.issuperset(group) for group in groups):
        raise ValueError('Select whole mesh islands before changing their output inclusion.')
    excluded = set(part.excluded_island_faces)
    if args['included']:
        excluded.difference_update(selected)
    else:
        excluded.update(selected)
    if excluded == set(part.excluded_island_faces):
        return authoring.shadow_service.session_view(snapshot.session_id)
    from cdmw.modding.mesh_parser import parse_mesh
    original = parse_mesh(snapshot.original_data, state.target_path).submeshes[part.target_index]
    if current.faces != original.faces or len(current.vertices) != len(original.vertices):
        raise ValueError('Island inclusion requires unchanged source topology. Use Free Edit to delete rebuilt geometry.')
    next_state = replace(state, revision=state.revision + 1, parts=tuple(
        replace(value, excluded_island_faces=tuple(sorted(excluded))) if value.part_id == part.part_id else value
        for value in state.parts))
    return commit_replacement(authoring.shadow_service, snapshot, candidate, next_state,
        label='Restore mesh island' if args['included'] else 'Exclude mesh island', stop_event=stop_event)
