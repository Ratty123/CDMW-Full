"""Host validation and publication for Rust-owned hair authoring."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import struct
from pathlib import PurePosixPath

from cdmw.domain.mesh.hair import hair_state_from_payload
from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE, REPLACEMENT_POLICY
from cdmw.domain.hair_registration import validate_hair_stem
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_totals import refresh_mesh_totals
from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids


def hair_target_supported(session):
    path = str(session.working_mesh.path).replace("\\", "/").casefold()
    return (session.mesh_format == "pac" and session.lod_index == 0
            and "1_pc/2_phw/head/hair/" in path and path.endswith("_player.pac"))


def template_card_uv_rect(part):
    """Reuse an actual connected donor card's atlas region, not the whole atlas."""
    if len(part.uvs) != len(part.vertices) or not part.faces:
        return [0., 0., 1., 1.]
    parents = list(range(len(part.vertices)))
    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    for a, b, c in part.faces:
        parents[find(b)] = find(a)
        parents[find(c)] = find(a)
    islands = {}
    for index, uv in enumerate(part.uvs):
        islands.setdefault(find(index), []).append(uv)
    for island in sorted(islands.values(), key=len, reverse=True):
        u0, v0 = (min(uv[i] for uv in island) for i in range(2))
        u1, v1 = (max(uv[i] for uv in island) for i in range(2))
        if u1-u0 > .0001 and v1-v0 > .0001:
            return [u0, v0, u1, v1]
    return [0., 0., 1., 1.]


def hair_ui_state(authoring):
    from cdmw.services.mesh_rust_authoring import _atomic_write_payload
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    state = session.hair_state
    available = hair_target_supported(session) and session.archive_refit_context is None
    result = {"available": available, "active": state is not None, "game_verified": False,
              "start_mode": authoring.hair_start_mode if available and state is None else "",
              "reason": "" if available else "Open a Damiane player hair PAC at LOD0 to create or edit hair."}
    if state is not None:
        from cdmw.services.mesh_hair_output import material_texture_paths
        material_path = state.payload["template"]["path"].replace("character/model/", "character/modelproperty/", 1).casefold() + "_xml"
        output = session.replacement_state
        files = {f.path.casefold(): f.data for f in (*output.dependencies, *output.companion_files)} if output else {}
        result["textures"] = list(material_texture_paths(files[material_path])[1]) if material_path in files else []
        result["revision"] = state.revision
        cached = authoring.hair_file_cache
        if cached is None or cached[0] != state.canonical:
            reference = _atomic_write_payload(
                authoring.root, "hair-state.json", state.payload, data_type="hair_authoring_json",
                expected_root_identity=authoring.root_identity,
            )
            authoring.hair_file_cache = (state.canonical, reference)
        result["file"] = dict(authoring.hair_file_cache[1])
    return result


def hair_texture_command(authoring, args, stop_event, *, export=False):
    """DDS edits use captured logical material paths and one reversible transaction."""
    from pathlib import Path
    from cdmw.core.dds_native import inspect_dds_native
    from cdmw.core.pathc_format import dds_shape
    from cdmw.core.temp_cache import app_temp_cache_path, app_temp_cache_build
    from cdmw.services.atomic_file_service import atomic_write_bytes
    from cdmw.domain.mesh.replacement import ReplacementFile

    service, sid = authoring.shadow_service, authoring.shadow_session_id
    snapshot = service.capture_export_snapshot(sid, stop_event=stop_event)
    if snapshot.hair_state is None or snapshot.replacement_state is None:
        raise ValueError("Start Hair authoring before editing its textures.")
    logical = str(args.get("texture_path", "")).replace("\\", "/").casefold()
    declared = {path.casefold() for path in hair_ui_state(authoring).get("textures", ())}
    if logical not in declared:
        raise ValueError("Choose a texture declared by this hairstyle's material.")
    output = snapshot.replacement_state
    files = {f.path.casefold(): f for f in (*output.dependencies, *output.companion_files)}
    before = files.get(logical)
    if before is None:
        raise ValueError("The required hair DDS was not captured from the archive.")
    if export:
        data = before.data
    else:
        source = Path(str(args.get("_dds_path", "")))
        if not source.is_file() or not 128 <= source.stat().st_size <= 128 * 1024 * 1024:
            raise ValueError("Choose a complete DDS file smaller than 128 MiB.")
        data = source.read_bytes()
    inspect_dds_native(data)
    if dds_shape(data) != dds_shape(before.data):
        raise ValueError("Keep the template DDS dimensions, format and mip count when editing hair textures.")
    digest = hashlib.sha256(data).hexdigest()
    local = app_temp_cache_path("mesh_hair_textures", digest, PurePosixPath(logical).name)
    with app_temp_cache_build(local):
        local.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(local, data)
    authoring._raise_if_cancelled(stop_event)
    if export:
        return {"hair_texture_source": str(local), "texture_path": logical}
    old_digest = hashlib.sha256(before.data).hexdigest()
    candidate = mesh_with_part_ids(snapshot, output)
    replacements = 0

    def rewrite(container):
        nonlocal replacements
        if isinstance(container, dict):
            for key, value in list(container.items()):
                if isinstance(value, str) and Path(value).is_absolute() and value.lower().endswith(".dds"):
                    path = Path(value)
                    if path.is_file() and path.stat().st_size <= 128 * 1024 * 1024 and hashlib.sha256(path.read_bytes()).hexdigest() == old_digest:
                        container[key] = str(local)
                        paired = key.replace("_dds_path", "_path")
                        if paired != key and paired in container:
                            container[paired] = str(local)
                        replacements += 1
                elif isinstance(value, (dict, list, tuple)):
                    rewrite(value)
        elif isinstance(container, (list, tuple)):
            for value in container:
                rewrite(value)

    for part in candidate.submeshes:
        rewrite(vars(part))
    if not replacements:
        raise ValueError("The DDS has no resolved preview binding. Reload the hair with its complete material dependencies.")
    companions = {file.path.casefold(): file for file in output.companion_files}
    companions[logical] = ReplacementFile(logical, data)
    state = snapshot.hair_state.payload
    state["revision"] += 1
    prepared = service.prepare_working_mesh_replacement(sid, candidate,
        replacement_state=replace(output, companion_files=tuple(companions.values()), revision=output.revision + 1),
        hair_state=hair_state_from_payload(state), replace_hair_state=True, validation_output_policy=REPLACEMENT_POLICY)
    authoring._raise_if_cancelled(stop_event)
    service.commit_prepared_working_mesh_replacement(prepared, history_action="hair_texture", history_label="Apply hair DDS",
        output_policy=REPLACEMENT_POLICY, require_reversible_history=True)
    return {"texture_path": logical}


def setup_hair(authoring, args, stop_event):
    """The archive loader has prepared the explicit reference on this worker."""
    service, session_id = authoring.shadow_service, authoring.shadow_session_id
    session = service._session(session_id)
    if not hair_target_supported(session) or session.archive_refit_context is not None:
        raise ValueError("Hair creation needs a Damiane player hair PAC without active Morph & Refit.")
    incoming = args.get("_archive_snapshot")
    if incoming is None:
        raise ValueError("Choose the reference head through the archive picker.")
    head = args["_archive_entry"]
    path = head.path.replace("\\", "/").casefold()
    if "/head/head/" not in path or "/2_phw/" not in path:
        raise ValueError("Choose a compatible Damiane-family head, including its ears and neck.")
    appearance = args.get("_archive_neutral_appearance")
    reference = appearance.to_neutral(incoming.mesh) if appearance is not None else incoming.mesh
    positions, triangles = [], []
    for part in reference.submeshes:
        first = len(positions)
        positions.extend([list(p) for p in part.vertices])
        triangles.extend([[first + i for i in face] for face in part.faces])
    identity = path + ":" + hashlib.sha256(incoming.original_data).hexdigest()
    if not positions or not triangles:
        raise ValueError("The head reference has no usable scalp surface.")
    bounds_min = [min(p[i] for p in positions) for i in range(3)]
    bounds_max = [max(p[i] for p in positions) for i in range(3)]
    center = [(a + b) * .5 for a, b in zip(bounds_min, bounds_max)]
    height = max(bounds_max[1] - bounds_min[1], .01)
    radius = max(.001, max(bounds_max[0] - bounds_min[0], bounds_max[2] - bounds_min[2]) * .5)
    collisions = [dict(a=[center[0], bounds_min[1] + radius, center[2]],
                       b=[center[0], bounds_max[1] - radius, center[2]], radius=radius, follows_head=True)]
    references = session.hair_state.payload.get("references", []) if session.hair_state is not None else []
    body = args.get("_body_snapshot")
    if body is not None:
        body_path = str(args["_body_archive_entry"].path).replace("\\", "/").casefold()
        if "/1_pc/2_phw/" not in body_path or not any(word in body_path for word in ("nude", "/body/")):
            raise ValueError("Choose Damiane's base body for the neck and shoulder reference.")
        appearance = args.get("_body_neutral_appearance")
        mesh = appearance.to_neutral(body.mesh) if appearance is not None else body.mesh
        vertices, faces = [], []
        cutoff = bounds_min[1] - height * .9
        neck_top = bounds_min[1] + height * .1
        scalp_bottom = bounds_max[1] - height * .4
        for part in mesh.submeshes:
            # The separate head PAC can be only a face mask. The base body's
            # crown/back completes the scalp; keep its neck/shoulders separate.
            scalp_faces = [face for face in part.faces if all(part.vertices[i][1] >= scalp_bottom for i in face)]
            scalp_indices = sorted({i for face in scalp_faces for i in face})
            scalp_map = {index: i + len(positions) for i, index in enumerate(scalp_indices)}
            positions.extend([list(part.vertices[i]) for i in scalp_indices])
            triangles.extend([[scalp_map[i] for i in face] for face in scalp_faces])
            selected = [face for face in part.faces if all(cutoff <= part.vertices[i][1] <= neck_top for i in face)]
            indices = sorted({i for face in selected for i in face})
            mapping = {index: i + len(vertices) for i, index in enumerate(indices)}
            vertices.extend([list(part.vertices[i]) for i in indices])
            faces.extend([[mapping[i] for i in face] for face in selected])
        if not faces:
            raise ValueError("The selected body does not overlap the head's neck and shoulder area.")
        references = [dict(identity=body_path + ":" + hashlib.sha256(body.original_data).hexdigest(),
                           positions=vertices, triangles=faces)]
        identity = path + ":" + hashlib.sha256(incoming.original_data + body.original_data).hexdigest()
        bounds_min = [min(p[i] for p in positions) for i in range(3)]
        bounds_max = [max(p[i] for p in positions) for i in range(3)]
        center = [(a + b) * .5 for a, b in zip(bounds_min, bounds_max)]
        height = max(bounds_max[1] - bounds_min[1], .01)
        radius = max(.001, max(bounds_max[0] - bounds_min[0], bounds_max[2] - bounds_min[2]) * .5)
        collisions = [dict(a=[center[0], bounds_min[1] + radius, center[2]],
                           b=[center[0], bounds_max[1] - radius, center[2]], radius=radius, follows_head=True)]
    shoulder_y = bounds_min[1] - height * .42
    collisions.append(dict(a=[center[0], shoulder_y, center[2]], b=[center[0], bounds_min[1], center[2]],
                           radius=max(radius * .55, .001), follows_head=False))
    if references:
        body_min = min(p[0] for p in references[0]["positions"])
        body_max = max(p[0] for p in references[0]["positions"])
        half = min((body_max - body_min) * .4, (bounds_max[0] - bounds_min[0]) * 1.3)
        collisions.append(dict(a=[center[0] - half, shoulder_y, center[2]], b=[center[0] + half, shoulder_y, center[2]],
                               radius=max(height * .20, .001), follows_head=False))
    if session.hair_state is not None:
        payload = session.hair_state.payload
        payload["scalp"] = {"identity": identity, "positions": positions, "triangles": triangles}
        payload["revision"] += 1
        # Roots remain authored on their old reference until explicit Rebind.
    else:
        digest = hashlib.sha256(session.original_data).hexdigest()
        mode = str(args.get("mode", "existing"))
        if mode not in {"generated", "existing"}:
            raise ValueError("Choose Create Hair or Edit Hair.")
        target_stem = str(args.get("target_stem") or "cd_phw_00_hair_00_9001_01_player")
        validate_hair_stem(target_stem)
        span = max(bounds_max[i] - bounds_min[i] for i in range(3))
        part_index = max(range(len(session.working_mesh.submeshes)), key=lambda i: len(session.working_mesh.submeshes[i].vertices))
        payload = {
            "version": 1, "revision": 0, "converted": False,
            "scalp": {"identity": identity, "positions": positions, "triangles": triangles},
            "bound_reference": identity, "reference_parts": [],
            "template": {"path": str(session.working_mesh.path), "sha256": digest,
                         "target_stem": target_stem, "character": "Damiane", "physics_profile": "Hair"},
            "groups": [{"id": 0, "name": session.working_mesh.submeshes[part_index].name, "part": part_index, "mode": mode, "width": max(span * .08, .001),
                        "cards_per_guide": 6, "uv_rect": template_card_uv_rect(session.working_mesh.submeshes[part_index])}],
            "guides": [], "bindings": [], "collisions": [],
        }
    payload["references"] = references
    payload["collisions"] = collisions
    hair = hair_state_from_payload(payload)
    snapshot = service.capture_export_snapshot(session_id, stop_event=stop_event)
    output = snapshot.replacement_state
    if output is None:
        from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies
        dependencies = capture_replacement_dependencies(args.get("_target_entry"), args.get("_target_dependencies"), stop_event)
        output = initial_replacement_state(snapshot, args.get("_target_entry"), dependencies)
        if authoring.neutral_appearance is not None:
            output = replace(output, neutral_appearance=authoring.neutral_appearance, neutral_coordinates=True)
    candidate = mesh_with_part_ids(snapshot, output)
    prepared = service.prepare_working_mesh_replacement(
        session_id, candidate, replacement_state=output, hair_state=hair, replace_hair_state=True,
        validation_output_policy=REPLACEMENT_POLICY,
    )
    authoring._raise_if_cancelled(stop_event)
    service.commit_prepared_working_mesh_replacement(
        prepared, history_action="hair_setup", history_label="Set hair reference",
        output_policy=REPLACEMENT_POLICY, require_reversible_history=True,
    )
    return {"status": "ready", "reference": path}


def apply_hair_candidate(authoring, payload, label, stop_event=None):
    from cdmw.services.mesh_rust_authoring import _finite_rows, _integer_values, _preserve_unchanged_rust_channel
    from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs
    from cdmw.modding.static_mesh_replacer import StaticSubmeshMapping, build_static_replacement_preview_mesh
    from cdmw.services.mesh_replacement_output import manual_replacement_options

    service, session_id = authoring.shadow_service, authoring.shadow_session_id
    snapshot = service.capture_export_snapshot(session_id, stop_event=stop_event)
    if snapshot.hair_state is None or snapshot.replacement_state is None:
        raise ValueError("Start hair authoring before submitting guides.")
    old = snapshot.hair_state.payload
    state = hair_state_from_payload(payload.get("hair"), allow_unbound=False)
    if state is None:
        raise ValueError("Hair transaction omitted its rest state.")
    new = state.payload
    if new["revision"] <= old["revision"] or new["revision"] > old["revision"] + 100_000:
        raise ValueError("Hair transaction has a stale or invalid revision.")
    def wire(value):
        # Rust stores geometry as f32 and JSON prints its shortest decimal. Match
        # that exact f32 value, then retain the host's original reference bytes.
        if isinstance(value, float):
            return struct.pack("<f", value)
        if isinstance(value, list):
            return [wire(item) for item in value]
        if isinstance(value, dict):
            return {key: wire(item) for key, item in value.items()}
        return value
    if wire(new["scalp"]) != wire(old["scalp"]) or new["template"]["sha256"] != old["template"]["sha256"]:
        raise ValueError("Hair transaction changed its reference or donor provenance.")
    if wire(new.get("references", [])) != wire(old.get("references", [])) or wire(new["collisions"]) != wire(old["collisions"]):
        raise ValueError("Change fitting references through the host-owned reference picker.")
    for field in ("scalp", "references", "collisions"):
        new[field] = copy.deepcopy(old.get(field, []))
    state = hair_state_from_payload(new, allow_unbound=False)
    for field in ("path", "character", "physics_profile"):
        if new["template"].get(field) != old["template"].get(field):
            raise ValueError("Hair transaction changed its export template.")
    validate_hair_stem(new["template"]["target_stem"])
    if old["converted"] and not new["converted"]:
        raise ValueError("Restore editable guides through Undo.")
    raw_parts = payload.get("submeshes")
    if not isinstance(raw_parts, list) or len(raw_parts) != len(snapshot.mesh.submeshes):
        raise ValueError("Hair transaction changed the template's material part layout.")
    owned = {group["part"] for group in new["groups"]}
    if any(i >= len(raw_parts) for i in owned):
        raise ValueError("Hair group refers to a missing material part.")
    candidate = mesh_with_part_ids(snapshot, snapshot.replacement_state)
    generated_source = ParsedMesh(format="obj", submeshes=[])
    changed_topology = []
    for index, (raw, original) in enumerate(zip(raw_parts, candidate.submeshes, strict=True)):
        vertices = _finite_rows(raw.get("positions"), 3, "hair positions")
        normals = _finite_rows(raw.get("normals"), 3, "hair normals")
        uvs = _finite_rows(raw.get("uvs"), 2, "hair UVs")
        indices = _integer_values(raw.get("indices"), "hair indices")
        if (not vertices or len(vertices) > 500_000 or len(normals) != len(vertices)
                or len(uvs) != len(vertices) or not indices or len(indices) % 3
                or any(i < 0 or i >= len(vertices) for i in indices)):
            raise ValueError("Hair geometry is incomplete or has invalid indices.")
        faces = [tuple(indices[i:i+3]) for i in range(0, len(indices), 3)]
        vertices = _preserve_unchanged_rust_channel(list(original.vertices), vertices)
        normals = _preserve_unchanged_rust_channel(list(original.normals), normals)
        uvs = _preserve_unchanged_rust_channel(list(original.uvs), uvs)
        if index not in owned and (vertices != list(original.vertices) or faces != list(original.faces)
                                   or normals != list(original.normals) or uvs != list(original.uvs)):
            raise ValueError("Hair transaction changed an unassigned part.")
        if any(g["part"] == index and g["mode"] == "existing" for g in new["groups"]) and (
                uvs != list(original.uvs) or faces != list(original.faces)):
            raise ValueError("Reshaping existing hair must preserve its topology and UV layout.")
        generated_source.submeshes.append(SubMesh(vertices=vertices, normals=normals, uvs=uvs, faces=faces))
        if index not in owned:
            continue
        if len(vertices) != len(original.vertices) or faces != list(original.faces):
            changed_topology.append(index)
        else:
            original.vertices, original.normals, original.uvs = vertices, normals, uvs
    if changed_topology:
        mappings = [StaticSubmeshMapping(i, candidate.submeshes[i].name, [i], i) for i in changed_topology]
        rebuilt = build_static_replacement_preview_mesh(candidate, generated_source, manual_replacement_options(mappings))
        for i in changed_topology:
            donor, target = candidate.submeshes[i], rebuilt.submeshes[i]
            target.name, target.material, target.texture = donor.name, donor.material, donor.texture
            copy_extra_submesh_attrs(donor, target)
            from cdmw.modding.mesh_skinning import ensure_final_target_skin_weights, SOURCE_VERTEX_MAP_TOPOLOGY
            target.source_vertex_map_authority = SOURCE_VERTEX_MAP_TOPOLOGY
            ensure_final_target_skin_weights(target, donor, target_index=i, summary=None)
            setattr(target, PART_ID_ATTRIBUTE, getattr(donor, PART_ID_ATTRIBUTE))
            candidate.submeshes[i] = target
    for binding in new["bindings"]:
        if binding["vertex"] >= len(candidate.submeshes[binding["part"]].vertices):
            raise ValueError("Hair binding refers to a removed vertex.")
    from cdmw.services.mesh_service_kernel import _invalidate_tangents_after_edit
    _invalidate_tangents_after_edit(candidate, "transform", owned, {}, topology_changed=bool(changed_topology))
    refresh_mesh_totals(candidate)
    generated_only = all(group["mode"] == "generated" for group in new["groups"])
    active_parts = {group["part"] for group in new["groups"]
                    if any(guide["group"] == group["id"] for guide in new["guides"])}
    parts = tuple(replace(part, import_positions=tuple(candidate.submeshes[part.target_index].vertices),
                          import_normals=tuple(candidate.submeshes[part.target_index].normals),
                          included=part.target_index in active_parts if generated_only else part.included,
                          source_label="Hair guides")
                  if part.target_index in owned else replace(part, included=False) if generated_only else part
                  for part in snapshot.replacement_state.parts)
    replacement = replace(snapshot.replacement_state, parts=parts, revision=snapshot.replacement_state.revision + 1)
    prepared = service.prepare_working_mesh_replacement(
        session_id, candidate, replacement_state=replacement, hair_state=state,
        replace_hair_state=True, validation_output_policy=REPLACEMENT_POLICY,
    )
    if not prepared.validation_report.ok:
        from cdmw.domain.mesh.export_validation import describe_mesh_export_issue
        raise ValueError(describe_mesh_export_issue(prepared.validation_report.blockers[0]))
    authoring._preflight_mesh_document_capacity(prepared.working_mesh)
    authoring._raise_if_cancelled(stop_event)
    service.commit_prepared_working_mesh_replacement(
        prepared, history_action="hair_groom", history_label=label,
        output_policy=REPLACEMENT_POLICY, require_reversible_history=True,
    )
