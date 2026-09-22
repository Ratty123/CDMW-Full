"""Stage experiment resources without decoding the material's base maps again."""
import copy
from pathlib import Path

from cdmw.core.common import raise_if_cancelled
from cdmw.core.material_shader_controls import control_material_sources
from cdmw.domain.mesh.replacement import bound_part_indices
from cdmw.domain.mesh.shader_controls import family_for, preview_factors
from cdmw.services.mesh_replacement_materials import _sidecar_text, material_binding_name, material_binding_names
from cdmw.services.shader_controls_preview import EFFECT_NORMAL_PARAMETER, publish_preview_texture, attach_source_masks, shader_control_diagnostic


def stage_shader_preview(authoring, mesh, state, payload, presentations, stop_event):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_shader_controls import build_shader_control_files, shader_settings
    from cdmw.services.mesh_rust_authoring import _mesh_lods, _publish_rust_texture_resources

    session = authoring.shadow_service._session(authoring.shadow_session_id)
    original = parse_mesh(session.original_data, state.target_path)
    selected_names = dict(shader_settings(state, original))
    source_names = material_binding_names(state)
    files = {file.path.replace("\\", "/").casefold(): file for file in state.dependencies}
    files.update({file.path.replace("\\", "/").casefold(): file
                  for file in build_shader_control_files(state, original, state.companion_files, stop_event=stop_event)})
    materials = {}
    for path, file in files.items():
        if path.endswith((".pac_xml", ".pami")):
            for name, value in control_material_sources(_sidecar_text(file.data), static=path.endswith(".pami")).items():
                if name not in selected_names:
                    continue
                if name in materials and materials[name] != value:
                    raise ValueError(f"{name}: multiple source material variants need separate shader previews.")
                materials[name] = value
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
