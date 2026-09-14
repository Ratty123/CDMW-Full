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
from cdmw.domain.hair_characters import HAIR_CHARACTERS, hair_character
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_totals import refresh_mesh_totals
from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids


def hair_target_supported(session):
    path = str(session.working_mesh.path).replace("\\", "/").casefold()
    return (session.mesh_format == "pac" and session.lod_index == 0
            and any(profile.accepts_hair(path) for profile in HAIR_CHARACTERS))


def validate_hair_donor(mesh, character="Damiane", lod_index=0):
    """Preflight the original PAC; never infer its layout from preview geometry."""
    from cdmw.modding.mesh_skinning import PAC_SKIN_WEIGHT_LAYOUT
    import math
    if lod_index != 0 or not hair_character(character).accepts_hair(mesh.path):
        raise ValueError("Choose a registered player hairstyle at LOD0.")
    if not mesh.submeshes or not any(p.vertices for p in mesh.submeshes):
        raise ValueError("The hairstyle has no editable geometry at LOD0.")
    if len(mesh.lod_levels) > 1:
        raise ValueError("This donor has additional PAC LODs requiring a verified hair LOD writer.")
    for part in mesh.submeshes:
        if not part.vertices:
            continue
        if part.source_vertex_stride != 40:
            raise ValueError(f"{part.name}: PAC vertex stride {part.source_vertex_stride} is unsupported; expected proven 40-byte.")
        if (part.source_skin_weight_layout != PAC_SKIN_WEIGHT_LAYOUT
                or len(part.bone_indices) != len(part.vertices) or len(part.bone_weights) != len(part.vertices)
                or any(not 1 <= len(weights) <= 8 or len(indices) != len(weights)
                       or any(type(index) is not int or index < 0 for index in indices)
                       or any(not math.isfinite(weight) or weight < 0 for weight in weights)
                       or sum(weights) <= 0
                       for indices, weights in zip(part.bone_indices, part.bone_weights))):
            raise ValueError(f"{part.name}: complete original PAC skin records are required.")


def _scaled_reference(snapshot, appearance, scale):
    import math
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("The mounted reference has an invalid component scale.")
    mesh = appearance.to_neutral(snapshot.mesh) if appearance is not None else copy.deepcopy(snapshot.mesh)
    for part in mesh.submeshes:
        part.vertices = [tuple(value * scale for value in point) for point in part.vertices]
    return mesh


def _head_component_scale(mesh, scale, skeleton, appearance, source_data, *, body=False):
    """HeadScale is local to the head joint, never a translation from the feet.

    CharacterScale is a common parent of head, body and hair. Authoring uses
    the donor PAC's units, so that common parent is cancelled for every part.
    Body vertices blend the head scale by their original head-joint lineage.
    """
    if scale == 1.0:
        return mesh
    bones = tuple(getattr(skeleton, "bones", ()))
    heads = [bone for bone in bones if bone.name.casefold() in {"head", "bip01 head", "bip01_head"}]
    if len(heads) != 1:
        raise ValueError("The mounted character needs one resolved head joint for its authored scale.")
    head = heads[0]
    pivot = tuple(head.bind_matrix[12:15])
    if appearance is not None:
        pivot = appearance.bone_position(head.index, pivot)
    descendants = {head.index}
    for _ in bones:
        expanded = descendants | {b.index for b in bones if b.parent_index in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    if body:
        from cdmw.modding.mesh_parser import resolve_pac_bone_palette
        palette = appearance.bone_palette if appearance is not None else resolve_pac_bone_palette(source_data, skeleton)
    for part in mesh.submeshes:
        vertices = []
        for i, point in enumerate(part.vertices):
            amount = (sum(weight for slot, weight in zip(part.bone_indices[i], part.bone_weights[i])
                          if 0 <= slot < len(palette) and palette[slot] in descendants) if body else 1.0)
            factor = 1.0 + (scale - 1.0) * amount
            vertices.append(tuple(pivot[axis] + (point[axis] - pivot[axis]) * factor for axis in range(3)))
        part.vertices = vertices
    return mesh


def _reference_geometry_identity(source, positions, triangles, references):
    """Appearance transforms can change the scalp while its PAC bytes stay equal."""
    digest = hashlib.sha256(source.encode("utf-8"))
    for mesh in [dict(positions=positions, triangles=triangles), *references]:
        digest.update(struct.pack("<QQ", len(mesh["positions"]), len(mesh["triangles"])))
        for point in mesh["positions"]:
            digest.update(struct.pack("<3d", *point))
        for face in mesh["triangles"]:
            digest.update(struct.pack("<3I", *face))
    return "hair-reference:" + digest.hexdigest()


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
              "reason": "" if available else "Use Hair Tools to choose a playable character and a registered hairstyle at LOD0."}
    if state is not None:
        from cdmw.services.mesh_hair_output import material_texture_paths
        material_path = state.payload["template"]["path"].replace("character/model/", "character/modelproperty/", 1).casefold() + "_xml"
        output = session.replacement_state
        files = {f.path.casefold(): f.data for f in (*output.dependencies, *output.companion_files)} if output else {}
        result["textures"] = list(material_texture_paths(files[material_path])[1]) if material_path in files else []
        result["materials_ready"] = bool(result["textures"]) and all(path.casefold() in files for path in result["textures"])
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
    return prepare_hair_setup(authoring.shadow_service, authoring.shadow_session_id, args, stop_event,
                             neutral_appearance=authoring.neutral_appearance)


def prepare_hair_setup(service, session_id, args, stop_event, *, neutral_appearance=None, neutral_coordinates=True):
    """Validate and commit setup to an isolated session before replacing a scene."""
    from cdmw.domain.cancellation import raise_if_cancelled
    raise_if_cancelled(stop_event, "Hair setup cancelled")
    session = service._session(session_id)
    character = args.get("character") or (session.hair_state.payload["template"]["character"] if session.hair_state else "Damiane")
    profile = hair_character(character)
    if not hair_target_supported(session) or session.archive_refit_context is not None:
        raise ValueError("Hair creation needs a registered player hair PAC without active Morph & Refit.")
    if not profile.accepts_hair(session.working_mesh.path):
        raise ValueError("The selected hairstyle does not belong to this character's hair family.")
    incoming = args.get("_archive_snapshot")
    if incoming is None:
        raise ValueError("Choose the reference head through the archive picker.")
    head = args["_archive_entry"]
    path = head.path.replace("\\", "/").casefold()
    if not profile.accepts_reference(path, "head"):
        raise ValueError("Choose a head from the selected character's mounted appearance.")
    appearance = args.get("_archive_neutral_appearance")
    head_scale = float(args.get("_head_scale", 1.0))
    reference = _head_component_scale(_scaled_reference(incoming, appearance, 1.0), head_scale,
        args.get("_archive_skeleton"), appearance, incoming.original_data)
    positions, triangles = [], []
    detail_positions, detail_triangles = [], []
    for part in reference.submeshes:
        name = (part.name + " " + part.material).casefold()
        if any(word in name for word in ("eyecover", "eye_cover")):
            # These fitted caps follow the eyelid opening. The game's separate
            # eyeballs contain raised iris/lens geometry for its eye shaders.
            first = len(detail_positions)
            detail_positions.extend([list(p) for p in part.vertices])
            detail_triangles.extend([[first + i for i in face] for face in part.faces])
            continue
        if any(word in name for word in ("eyelash", "eyebrow")):
            continue
        first = len(positions)
        positions.extend([list(p) for p in part.vertices])
        triangles.extend([[first + i for i in face] for face in part.faces])
    identity = path + ":" + hashlib.sha256(incoming.original_data).hexdigest()
    face_count = len(triangles)
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
        if not profile.accepts_reference(body_path, "body"):
            raise ValueError("Choose the selected character's base body for the neck and shoulder reference.")
        appearance = args.get("_body_neutral_appearance")
        mesh = _head_component_scale(_scaled_reference(body, appearance, 1.0), head_scale,
            args.get("_body_skeleton"), appearance, body.original_data, body=True)
        vertices, faces = [], []
        cutoff = bounds_min[1] - height * .9
        neck_top = bounds_min[1]
        scalp_bottom = bounds_max[1] - height * .02
        face_back = bounds_max[2] - height * .02
        for part in mesh.submeshes:
            # The separate head PAC can be only a face mask. The base body's
            # crown/back completes the scalp; keep its neck/shoulders separate.
            scalp_faces = [face for face in part.faces
                if sum(part.vertices[i][1] for i in face) / 3 >= neck_top
                and (sum(part.vertices[i][1] for i in face) / 3 >= scalp_bottom
                     or sum(part.vertices[i][2] for i in face) / 3 >= face_back)]
            scalp_indices = sorted({i for face in scalp_faces for i in face})
            scalp_map = {index: i + len(positions) for i, index in enumerate(scalp_indices)}
            positions.extend([list(part.vertices[i]) for i in scalp_indices])
            triangles.extend([[scalp_map[i] for i in face] for face in scalp_faces])
            # Keep the lower body once; the face perimeter is joined below.
            scalp_face_set = set(tuple(face) for face in scalp_faces)
            selected = [face for face in part.faces if tuple(face) not in scalp_face_set
                        and all(part.vertices[i][1] >= cutoff for i in face)
                        and sum(part.vertices[i][1] for i in face) / 3 <= neck_top]
            indices = sorted({i for face in selected for i in face})
            mapping = {index: i + len(vertices) for i, index in enumerate(indices)}
            vertices.extend([list(part.vertices[i]) for i in indices])
            faces.extend([[mapping[i] for i in face] for face in selected])
        if not faces:
            raise ValueError("The selected body does not overlap the head's neck and shoulder area.")
        references = [dict(identity=body_path + ":" + hashlib.sha256(body.original_data).hexdigest(),
                           positions=vertices, triangles=faces)]
        from cdmw.domain.mesh.hair_reference import join_face_reference
        positions, triangles = join_face_reference(positions, triangles, face_count, vertices, faces)
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
    detail_sources = hashlib.sha256()
    if detail_triangles:
        detail_sources.update(incoming.original_data)
    for detail in (() if detail_triangles else args.get("_prepared_head_details", ())):
        source = detail["_archive_snapshot"]
        appearance = detail["_archive_neutral_appearance"]
        mesh = _head_component_scale(_scaled_reference(source, appearance, 1.0), detail["_scale"],
            args.get("_archive_skeleton"), args.get("_archive_neutral_appearance"), source.original_data)
        detail_sources.update(source.original_data)
        for part in mesh.submeshes:
            first = len(detail_positions)
            detail_positions.extend([list(p) for p in part.vertices])
            detail_triangles.extend([[first + i for i in face] for face in part.faces])
    # Eyes are head-rigid fitting references, not planting/collision
    # surfaces. Keep them in one existing reference slot (old drafts need no migration).
    references = [r for r in references if not r["identity"].startswith("head:")]
    if detail_triangles:
        references.append(dict(identity="head:" + path + ":" + detail_sources.hexdigest(),
                               positions=detail_positions, triangles=detail_triangles))
    identity = _reference_geometry_identity(identity, positions, triangles, references)
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
        from secrets import randbelow
        prefix = "phw" if profile.hair_family == "2_phw" else "phm"
        target_stem = str(args.get("target_stem") or f"cd_{prefix}_00_hair_00_{1000 + randbelow(8000):04d}_01_player")
        validate_hair_stem(target_stem)
        span = max(bounds_max[i] - bounds_min[i] for i in range(3))
        part_index = max(range(len(session.working_mesh.submeshes)), key=lambda i: len(session.working_mesh.submeshes[i].vertices))
        payload = {
            "version": 2, "revision": 0, "converted": False,
            "locks": [], "next_lock_id": 1, "style_name": "My hairstyle",
            "startup_preset": args.get("start_preset", "bob"),
            "scalp": {"identity": identity, "positions": positions, "triangles": triangles},
            "bound_reference": identity, "reference_parts": [],
            "template": {"path": str(session.working_mesh.path), "sha256": digest,
                         "target_stem": target_stem, "character": profile.name, "physics_profile": "Hair"},
            "groups": [{"id": 0, "name": session.working_mesh.submeshes[part_index].name, "part": part_index, "mode": mode, "width": max(span * .08, .001),
                        "cards_per_guide": 6, "uv_rect": template_card_uv_rect(session.working_mesh.submeshes[part_index])}],
            "guides": [], "bindings": [], "collisions": [],
        }
        if mode == "existing":
            payload["groups"] = [dict(id=i, name=part.name, part=i, mode=mode,
                width=max(span * .08, .001), cards_per_guide=6, uv_rect=template_card_uv_rect(part))
                for i, part in enumerate(session.working_mesh.submeshes)]
    payload["references"] = references
    payload["collisions"] = collisions
    hair = hair_state_from_payload(payload)
    snapshot = service.capture_export_snapshot(session_id, stop_event=stop_event)
    output = snapshot.replacement_state
    if output is None:
        from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies
        dependencies = capture_replacement_dependencies(args.get("_target_entry"), args.get("_target_dependencies"), stop_event)
        output = initial_replacement_state(snapshot, args.get("_target_entry"), dependencies)
        if neutral_appearance is not None:
            output = replace(output, neutral_appearance=neutral_appearance, neutral_coordinates=neutral_coordinates)
    candidate = mesh_with_part_ids(snapshot, output)
    prepared = service.prepare_working_mesh_replacement(
        session_id, candidate, replacement_state=output, hair_state=hair, replace_hair_state=True,
        validation_output_policy=REPLACEMENT_POLICY,
    )
    raise_if_cancelled(stop_event, "Hair setup cancelled")
    service.commit_prepared_working_mesh_replacement(
        prepared, history_action="hair_setup", history_label="Set hair reference",
        output_policy=REPLACEMENT_POLICY, require_reversible_history=True,
    )
    return {"status": "ready", "reference": path}


def _original_hair_skin_donor(authoring, snapshot, part_id):
    """Keep source records in authoring coordinates across generated edits."""
    donor = authoring.hair_skin_donor_mesh
    if donor is None:
        from cdmw.modding.mesh_parser import parse_mesh
        donor = parse_mesh(snapshot.original_data, snapshot.replacement_state.target_path)
        if authoring.neutral_appearance is not None:
            donor = authoring.neutral_appearance.to_neutral(donor)
        for binding in snapshot.replacement_state.parts:
            if not 0 <= binding.target_index < len(donor.submeshes):
                raise ValueError("Hair part has no original skin donor.")
            setattr(donor.submeshes[binding.target_index], PART_ID_ATTRIBUTE, binding.part_id)
        authoring.hair_skin_donor_mesh = donor
    matches = [part for part in donor.submeshes if getattr(part, PART_ID_ATTRIBUTE, None) == part_id]
    if len(matches) != 1:
        raise ValueError("Hair part has no unambiguous original skin donor.")
    return matches[0]


def apply_hair_candidate(authoring, payload, label, stop_event=None):
    from cdmw.services.mesh_rust_authoring import _finite_rows, _integer_values, _preserve_unchanged_rust_channel
    from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs
    from cdmw.modding.static_mesh_replacer import StaticSubmeshMapping, build_static_replacement_preview_mesh
    from cdmw.services.mesh_replacement_output import manual_replacement_options

    service, session_id = authoring.shadow_service, authoring.shadow_session_id
    update = payload.get("hair_update")
    vertices_only = isinstance(update, dict) and update.get("parts") == [] and payload.get("submeshes") == []
    if vertices_only:
        from types import SimpleNamespace
        live = service._session(session_id)
        with live.export_lock:
            if live.closed or live.native_editor_mesh_dirty:
                raise ValueError("Hair edit requires a current Rust authoring session.")
            snapshot = SimpleNamespace(mesh=live.working_mesh, mesh_revision=live.revision,
                hair_state=live.hair_state, replacement_state=live.replacement_state,
                original_data=live.original_data)
    else:
        snapshot = service.capture_export_snapshot(session_id, stop_event=stop_event)
    if snapshot.hair_state is None or snapshot.replacement_state is None:
        raise ValueError("Start hair authoring before submitting guides.")
    old = snapshot.hair_state.payload
    incoming = payload.get("hair")
    if update is not None:
        if (not isinstance(update, dict) or update.get("version") != 2 or update.get("reference") != old["scalp"]["identity"]
                or not isinstance(incoming, dict) or any(key in incoming for key in ("scalp", "references", "collisions"))):
            raise ValueError("Incremental hair update has a stale reference or unsupported version.")
        incoming = {**incoming, **{field: old.get(field, []) for field in ("scalp", "references", "collisions")}}
        reuse = update.get("reuse", [])
        if (not isinstance(reuse, list) or any(not isinstance(field, str) or field not in {"bindings", "locks", "guides", "groups", "vertex_sources", "prepared_parts"} for field in reuse)
                or len(reuse) != len(set(reuse)) or any(field in incoming for field in reuse)
                or (reuse and update.get("base_hair_revision") != old["revision"])):
            raise ValueError("Incremental hair state has a stale or conflicting base revision.")
        incoming.update({field: old[field] for field in reuse})
    from cdmw.domain.mesh.hair import _validated_hair_state
    state, new = _validated_hair_state(incoming, allow_unbound=False)
    if state is None:
        raise ValueError("Hair transaction omitted its rest state.")
    if new["revision"] <= old["revision"] or new["revision"] > old["revision"] + 100_000:
        raise ValueError("Hair transaction has a stale or invalid revision.")
    def wire(value):
        # Rust stores geometry as f32 and JSON prints its shortest decimal. Match
        # that exact f32 value, then retain the host's original reference bytes.
        if isinstance(value, float):
            return struct.pack("<f", value)
        if isinstance(value, (list, tuple)):
            return [wire(item) for item in value]
        if isinstance(value, dict):
            return {key: wire(item) for key, item in value.items()}
        return value
    if (update is None and wire(new["scalp"]) != wire(old["scalp"])) or new["template"]["sha256"] != old["template"]["sha256"]:
        raise ValueError("Hair transaction changed its reference or donor provenance.")
    if update is None and (wire(new.get("references", [])) != wire(old.get("references", [])) or wire(new["collisions"]) != wire(old["collisions"])):
        raise ValueError("Change fitting references through the host-owned reference picker.")
    if update is None:
        for field in ("scalp", "references", "collisions"):
            new[field] = old.get(field, [])
        state = hair_state_from_payload(new, allow_unbound=False)
    for field in ("path", "character", "physics_profile"):
        if new["template"].get(field) != old["template"].get(field):
            raise ValueError("Hair transaction changed its export template.")
    validate_hair_stem(new["template"]["target_stem"])
    if old["converted"] and not new["converted"]:
        raise ValueError("Restore editable guides through Undo.")
    raw_parts = payload.get("submeshes")
    vertex_updates = {}
    if update is not None:
        indices = update.get("parts")
        if (not isinstance(indices, list) or not isinstance(raw_parts, list) or len(indices) != len(raw_parts)
                or any(type(i) is not int or not 0 <= i < len(snapshot.mesh.submeshes) for i in indices) or len(set(indices)) != len(indices)):
            raise ValueError("Invalid incremental hair part list.")
        sparse = dict(zip(indices, raw_parts, strict=True))
        raw_parts = [sparse.get(i) for i in range(len(snapshot.mesh.submeshes))]
        rows = update.get("vertex_updates", [])
        if not isinstance(rows, list) or len(rows) > len(raw_parts):
            raise ValueError("Invalid incremental hair vertex updates.")
        for row in rows:
            if not isinstance(row, dict) or type(row.get("part")) is not int:
                raise ValueError("Invalid incremental hair material part.")
            part = row["part"]
            if not 0 <= part < len(raw_parts) or part in vertex_updates or part in sparse:
                raise ValueError("Conflicting incremental hair geometry updates.")
            vertices = _integer_values(row.get("indices"), "hair vertex updates")
            positions = _finite_rows(row.get("positions"), 3, "hair vertex positions")
            normals = _finite_rows(row.get("normals"), 3, "hair vertex normals")
            if (len(vertices) != len(set(vertices)) or len(vertices) != len(positions) or len(vertices) != len(normals)
                    or any(v < 0 or v >= min(len(snapshot.mesh.submeshes[part].vertices), len(snapshot.mesh.submeshes[part].normals)) for v in vertices)):
                raise ValueError("Invalid incremental hair vertex range.")
            vertex_updates[part] = (vertices, positions, normals)
    if not isinstance(raw_parts, list) or len(raw_parts) != len(snapshot.mesh.submeshes):
        raise ValueError("Hair transaction changed the template's material part layout.")
    owned = {group["part"] for group in new["groups"]}
    if any(i >= len(raw_parts) for i in owned):
        raise ValueError("Hair group refers to a missing material part.")
    if vertices_only:
        from cdmw.services.mesh_service_hair_transaction import commit_hair_vertices
        commit_hair_vertices(authoring, snapshot, state, new, old, vertex_updates, label, stop_event)
        return
    candidate = mesh_with_part_ids(snapshot, snapshot.replacement_state)
    generated_source = ParsedMesh(format="obj", submeshes=[])
    changed_topology = []
    retained_topology_changed = False
    empty_parts = set()
    donor_mesh = None
    for index, (raw, original) in enumerate(zip(raw_parts, candidate.submeshes, strict=True)):
        if raw is None and update is not None:
            if index in vertex_updates:
                if index not in owned:
                    raise ValueError("Hair transaction changed an unassigned part.")
                vertices, positions, normals = vertex_updates[index]
                original.vertices = list(original.vertices)
                original.normals = list(original.normals)
                for vertex, position, normal in zip(vertices, positions, normals, strict=True):
                    original.vertices[vertex] = tuple(position)
                    original.normals[vertex] = tuple(normal)
            generated_source.submeshes.append(original)
            continue
        if not isinstance(raw, dict):
            raise ValueError("Invalid hair geometry record.")
        vertices = _finite_rows(raw.get("positions"), 3, "hair positions")
        normals = _finite_rows(raw.get("normals"), 3, "hair normals")
        uvs = _finite_rows(raw.get("uvs"), 2, "hair UVs")
        indices = _integer_values(raw.get("indices"), "hair indices")
        if not vertices and not indices and index in owned:
            if any(lock["part"] == index and lock["vertices"] for lock in new["locks"]):
                raise ValueError("Deleted hair still has visible lock ownership.")
            empty_parts.add(index)
            generated_source.submeshes.append(original)
            continue
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
        existing = any(g["part"] == index and g["mode"] == "existing" for g in new["groups"])
        if existing and (uvs != list(original.uvs) or faces != list(original.faces)):
            from cdmw.modding.mesh_parser import parse_mesh
            from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TARGET_DONOR
            if donor_mesh is None:
                donor_mesh = parse_mesh(snapshot.original_data, snapshot.mesh.path)
            donor = donor_mesh.submeshes[index]
            source = raw.get("source_vertices")
            if (not isinstance(source, list) or len(source) != len(vertices) or len(set(source)) != len(source)
                    or any(type(i) is not int or not 0 <= i < len(donor.vertices) for i in source)):
                raise ValueError("Cut and deleted existing hair require exact original vertex provenance.")
            if new["vertex_sources"].get(str(index)) != source:
                raise ValueError("Hair geometry and original vertex provenance were not published together.")
            original_faces = set(tuple(face) for face in donor.faces)
            if any(tuple(source[i] for i in face) not in original_faces for face in faces):
                raise ValueError("Existing hair cuts may only retain original card triangles.")
            expected_uvs = [donor.uvs[i] for i in source]
            if wire(uvs) != wire(expected_uvs):
                raise ValueError("Cut hair changed its original UV layout.")
            retained = copy.deepcopy(original)
            retained.vertices, retained.normals, retained.uvs, retained.faces = vertices, normals, expected_uvs, faces
            for channel in ("bone_indices", "bone_weights", "source_vertex_offsets", "tangents"):
                rows = getattr(donor, channel)
                setattr(retained, channel, [rows[i] for i in source] if len(rows) == len(donor.vertices) else [])
            retained.source_vertex_map = list(source)
            retained.source_vertex_map_authority = SOURCE_VERTEX_MAP_TARGET_DONOR
            retained.vertex_count, retained.face_count = len(vertices), len(faces)
            retained_topology_changed = True
            candidate.submeshes[index] = retained
            generated_source.submeshes.append(retained)
            continue
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
            skin_donor = _original_hair_skin_donor(authoring, snapshot, getattr(donor, PART_ID_ATTRIBUTE))
            ensure_final_target_skin_weights(target, skin_donor, target_index=i, summary=None)
            setattr(target, PART_ID_ATTRIBUTE, getattr(donor, PART_ID_ATTRIBUTE))
            candidate.submeshes[i] = target
    for binding in new["bindings"]:
        if binding["vertex"] >= len(candidate.submeshes[binding["part"]].vertices):
            raise ValueError("Hair binding refers to a removed vertex.")
    for lock in new["locks"]:
        if any(v >= len(candidate.submeshes[lock["part"]].vertices) for v in lock["vertices"]):
            raise ValueError("Hair lock refers to removed geometry.")
    from cdmw.services.mesh_service_kernel import _invalidate_tangents_after_edit
    _invalidate_tangents_after_edit(candidate, "transform", owned, {}, topology_changed=bool(changed_topology) or retained_topology_changed)
    refresh_mesh_totals(candidate)
    generated_only = all(group["mode"] == "generated" for group in new["groups"])
    active_parts = {group["part"] for group in new["groups"]
                    if any(guide["group"] == group["id"] for guide in new["guides"])}
    parts = tuple(replace(part, import_positions=tuple(candidate.submeshes[part.target_index].vertices),
                          import_normals=tuple(candidate.submeshes[part.target_index].normals),
                          included=(part.target_index in active_parts if generated_only else part.included) and part.target_index not in empty_parts,
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
