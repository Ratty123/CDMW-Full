"""Stage experiment resources without decoding the material's base maps again."""
import copy
from dataclasses import replace
from pathlib import Path
from xml.sax.saxutils import escape

from cdmw.core.common import raise_if_cancelled
from cdmw.core.material_shader_controls import control_material_sources, control_material_variants, equipment_glass_needs_bake
from cdmw.domain.mesh.replacement import bound_part_indices
from cdmw.domain.mesh.shader_controls import GLASS_FAMILIES, family_for, preview_factors
from cdmw.services.mesh_replacement_materials import _sidecar_text, material_binding_name, material_binding_names
from cdmw.services.shader_controls_preview import EFFECT_NORMAL_PARAMETER, publish_preview_texture, attach_source_masks, shader_control_diagnostic, preview_material_variant


def stage_shader_preview(authoring, mesh, state, payload, presentations, stop_event):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_shader_controls import build_shader_control_files, shader_settings
    from cdmw.services.mesh_rust_authoring import _mesh_lods, _publish_rust_texture_resources

    session = authoring.shadow_service._session(authoring.shadow_session_id)
    original = parse_mesh(session.original_data, state.target_path)
    selected_names = dict(shader_settings(state, original))
    source_names = material_binding_names(state)
    files = {file.path.replace("\\", "/").casefold(): file for file in state.dependencies}
    files.update({file.path.replace("\\", "/").casefold(): file for file in state.companion_files})
    baked_names = set()
    for path, file in files.items():
        if path.endswith(".pac_xml"):
            for variant in control_material_variants(_sidecar_text(file.data)):
                for name, (shader, values, textures) in variant.items():
                    if (name in selected_names and selected_names[name].shader == "SkinnedMeshTranslucent"
                            and equipment_glass_needs_bake(shader, {*values, *textures})):
                        baked_names.add(name)
    files.update({file.path.replace("\\", "/").casefold(): file
                  for file in build_shader_control_files(state, original, state.companion_files, stop_event=stop_event)})
    materials = {}
    for path, file in files.items():
        if path.endswith((".pac_xml", ".pami")):
            text = _sidecar_text(file.data)
            if path.endswith(".pac_xml"):
                decoded = {}
                for part in mesh.submeshes:
                    name = material_binding_name(part, source_names)
                    if name in selected_names:
                        source = control_material_sources(preview_material_variant(text, part))
                        if name in source:
                            decoded[name] = source[name]
            else:
                decoded = control_material_sources(text, static=True)
            for name, value in decoded.items():
                if name not in selected_names:
                    continue
                if name in materials and materials[name] != value:
                    controls = selected_names[name]
                    # Glass uses the already resolved base/normal/surface maps.
                    # PAMI variants can differ in tint and export-only shadow
                    # colour without changing these added absorption factors.
                    same_glass = (family_for(controls.shader) in GLASS_FAMILIES
                        and preview_factors(controls, materials[name][1])[4:6] == preview_factors(controls, value[1])[4:6])
                    if not same_glass:
                        raise ValueError(f"{name}: multiple source material variants need separate shader previews.")
                materials[name] = value
    if baked_names:
        _stage_baked_glass_materials(authoring, mesh, files, baked_names, source_names, payload, presentations, stop_event)
    indices = bound_part_indices(mesh, state)
    selected = {indices[part.part_id]: part for part in state.parts if part.shader_controls is not None}
    names = {material_binding_name(mesh.submeshes[index], source_names): part
             for index, part in selected.items()}
    lods = _mesh_lods(mesh)
    bindings, resources, diagnostics = {}, {}, {}
    touched = set()
    for lod_index, level in enumerate(lods):
        for index, part in enumerate(level):
            rule = selected.get(index) if lod_index == 0 else names.get(material_binding_name(part, source_names))
            if rule is None:
                continue
            source = original.submeshes[rule.target_index]
            if len(getattr(part, "shader_masks", ())) != len(part.vertices):
                attach_source_masks(part, source)
            name = material_binding_name(source, source_names)
            _, authored, textures = materials[name]
            controls = rule.shader_controls
            if lod_index == 0:
                diagnostics[rule.part_id] = shader_control_diagnostic(part, controls, authored)
            family = family_for(controls.shader)
            row = presentations.setdefault((lod_index, index), {"lod_index": lod_index, "material_index": index})
            row["shader_controls"] = list(preview_factors(controls, authored))
            touched.add((lod_index, index))
            for parameter, role in ((family.mask, "shader_mask"), (EFFECT_NORMAL_PARAMETER, "shader_normal")):
                path = textures.get(parameter, "")
                if not path or (role == "shader_normal" and controls.shader != "SkinnedMeshAnisotropy"):
                    continue
                raise_if_cancelled(stop_event)
                file = files.get(path.replace("\\", "/").casefold())
                if file is None:
                    raise ValueError(f"The shader preview mask is missing: {path}. Reopen this mesh from Browse Archives.")
                resource = publish_preview_texture(file.data)
                resources[resource] = Path(resource)
                bindings.setdefault((resource, role), [set() for _ in lods])[lod_index].add(index)
    retained = []
    for texture in payload["textures"]:
        row = copy.deepcopy(texture)
        if row["role"] in {"shader_mask", "shader_normal"}:
            row["material_indices_by_lod"] = [[index for index in level if (lod, index) not in touched]
                                               for lod, level in enumerate(row["material_indices_by_lod"])]
        if any(row["material_indices_by_lod"]):
            retained.append(row)
    # Numeric edits reuse the session's already published mask resources as well
    # as its base material cache. A new filename would make the helper reload an
    # identical DDS on every slider adjustment.
    cached = {}
    for previous in authoring.archive_refit_material_cache.values():
        for row in previous["textures"]:
            if row["role"] in {"shader_mask", "shader_normal"}:
                cached[(row["file"]["sha256"].upper(), row["role"])] = row
    added, pending = [], {}
    for (resource, role), ownership in bindings.items():
        row = cached.get((Path(resource).stem.upper(), role))
        if row is None:
            pending[(resource, role)] = ownership
        else:
            row = copy.deepcopy(row)
            row["material_indices_by_lod"] = [sorted(level) for level in ownership]
            added.append(row)
    raise_if_cancelled(stop_event)
    added.extend(_publish_rust_texture_resources(authoring.root, pending, resources, stop_event, authoring.root_identity))
    payload["textures"] = [*retained, *added]
    payload["shader_diagnostics"] = diagnostics


def _stage_baked_glass_materials(authoring, mesh, files, names, source_names, payload, presentations, stop_event):
    """Publish the export's baked DDS, replacing the selected layered graph only."""
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.mesh_rust_replacement_materials import prepared_replacement_material_mesh
    from cdmw.services.mesh_rust_authoring import _mesh_lods, _mesh_texture_payloads, _mesh_material_presentations

    files = dict(files)
    for path, file in tuple(files.items()):
        if not path.endswith(".pac_xml"):
            continue
        text, selected = _sidecar_text(file.data), {}
        for part in mesh.submeshes:
            name = material_binding_name(part, source_names)
            if name not in names:
                continue
            variant = preview_material_variant(text, part)
            for row in find_material_wrappers(variant):
                if row.submesh_name.casefold() == name:
                    label = escape(row.submesh_name, {'"': '&quot;'})
                    selected[name] = f'<SkinnedMeshMaterialWrapper _subMeshName="{label}">{variant[row.start:row.end]}</SkinnedMeshMaterialWrapper>'
        files[path] = replace(file, data=("<root>" + "".join(selected.values()) + "</root>").encode())
    wrappers = {row.submesh_name.casefold(): row.submesh_name for path, file in files.items()
                if path.endswith(".pac_xml") for row in find_material_wrappers(_sidecar_text(file.data))}
    ownership, levels = [], []
    for level in _mesh_lods(mesh):
        indices, parts = [], []
        for index, part in enumerate(level):
            name = material_binding_name(part, source_names)
            if name in names:
                indices.append(index)
                # No cached native layer graph or original tints may survive the bake.
                parts.append(SubMesh(name=wrappers[name], material=wrappers[name], vertices=part.vertices,
                                     faces=part.faces, uvs=part.uvs, normals=part.normals))
        ownership.append(indices)
        levels.append(parts)
    incoming = ParsedMesh(path=mesh.path, format=mesh.format, submeshes=levels[0], lod_levels=levels)
    with prepared_replacement_material_mesh(incoming, tuple(files.values()), required=True, stop_event=stop_event) as prepared:
        textures = _mesh_texture_payloads(authoring.root, prepared, expected_root_identity=authoring.root_identity,
                                         stop_event=stop_event, enable_material_synthesis=False)
        rows = _mesh_material_presentations(prepared)
    retained = []
    for texture in payload["textures"]:
        row = copy.deepcopy(texture)
        row["material_indices_by_lod"] = [[index for index in indices if index not in ownership[lod]]
                                           for lod, indices in enumerate(row["material_indices_by_lod"])]
        if any(row["material_indices_by_lod"]):
            retained.append(row)
    for row in textures:
        row["material_indices_by_lod"] = [[ownership[lod][index] for index in indices]
                                           for lod, indices in enumerate(row["material_indices_by_lod"])]
    payload["textures"] = [*retained, *textures]
    for row in rows:
        row["material_index"] = ownership[row["lod_index"]][row["material_index"]]
        presentations[(row["lod_index"], row["material_index"])] = row
