"""Publish prepared replacement textures through the existing material contract."""

from __future__ import annotations

import copy
import hashlib
from contextlib import contextmanager
from dataclasses import fields, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.mesh.replacement import bound_part_indices
from cdmw.services.mesh_replacement_materials import _sidecar_text, material_binding_name
from cdmw.services.mesh_rust_preview_package import conserve_preview_core_material_graph


def replacement_material_key(mesh, state):
    if any(part.translucency is not None or part.emission is not None or part.shader_controls is not None for part in state.parts):
        source = replace(state, parts=tuple(replace(part, translucency=None, translucency_surface=None, emission=None, shader_controls=None) for part in state.parts))
        return hashlib.sha256(repr((replacement_material_key(mesh, source), bound_part_indices(mesh, state),
                                   [(p.part_id, p.translucency, p.translucency_surface, p.emission, p.shader_controls) for p in state.parts])).encode()).hexdigest()[:32]
    has_imported = any(part.material_choice == "imported" for part in state.parts)
    has_dds_companion = any(str(file.path or "").replace("\\", "/").casefold().endswith(".dds") for file in state.companion_files)
    if not has_imported and not has_dds_companion:
        return "base"
    digest = hashlib.sha256(repr((bound_part_indices(mesh, state), [(p.part_id, p.material_choice) for p in state.parts])).encode())
    for file in sorted(state.companion_files, key=lambda item: str(item.path or "").replace("\\", "/").casefold()):
        digest.update(file.path.encode())
        digest.update(file.data)
    return digest.hexdigest()[:32]


def _replacement_texture_path(value):
    """A cache hit needs the complete DDS payload, not just its magic bytes."""
    from cdmw.core.dds_native import inspect_dds_native_path
    from cdmw.services.mesh_rust_authoring import _resolved_dds_path, RustMeshProtocolError

    path = _resolved_dds_path(value)
    if path is not None:
        info = inspect_dds_native_path(path)
        if not info.mip_levels:
            raise RustMeshProtocolError(f"Replacement preview texture is invalid: {path.name}: {info.reason}")
    return path


@contextmanager
def prepared_replacement_material_mesh(mesh, files, *, required, stop_event=None):
    """Bind captured DDS bytes for the duration of normal material compilation."""
    from cdmw.core.archive_model_references import _parse_archive_model_sidecar_texture_bindings
    from cdmw.core.final_package_preview_model import _material_semantics_for_binding
    from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput
    from cdmw.modding.asset_replacement import classify_texture_binding
    from cdmw.services.mesh_rust_authoring import (
        _TEXTURE_RESOURCE_SPECS, _mesh_lods, _material_input_texture_role, RustMeshProtocolError,
    )

    files = {file.path.replace("\\", "/").casefold(): file for file in files}
    bindings = []
    for file in files.values():
        raise_if_cancelled(stop_event, "Replacement material preparation cancelled.")
        if Path(file.path).suffix.lower() not in {".pac_xml", ".pami"}:
            continue
        try:
            text = _sidecar_text(file.data)
        except ValueError:
            if required:
                raise
            continue
        bindings.extend(_parse_archive_model_sidecar_texture_bindings(text, sidecar_path=file.path))
    incoming = copy.copy(mesh)
    incoming.lod_levels = [[copy.copy(part) for part in level] for level in _mesh_lods(mesh)]
    incoming.submeshes = incoming.lod_levels[0]
    with TemporaryDirectory(prefix="cdmw-replacement-preview-") as temporary:
        staged = {}

        def staged_path(key):
            if key not in staged:
                path = Path(temporary) / f"{len(staged)}.dds"
                path.write_bytes(files[key].data)
                _replacement_texture_path(path)
                staged[key] = path
            return staged[key]

        for level in incoming.lod_levels:
            for part in level:
                raise_if_cancelled(stop_event, "Replacement material preparation cancelled.")
                retained_roles = set()
                invalid_roles = {}
                if not required:
                    # Preserve resolved owner/layer metadata, including native
                    # bindings whose wrapper differs from the geometry name.
                    existing = getattr(part, "preview_material_texture_inputs", ())
                    if existing:
                        rebound = []
                        for item in existing:
                            key = str(getattr(item, "source_texture_path", "")).replace("\\", "/").casefold()
                            if key in files:
                                previous_paths = {str(getattr(item, attribute, "")).replace("\\", "/").casefold()
                                                  for attribute in ("source_dds_path", "preview_texture_path", "source_texture_path")}
                                previous_paths.discard("")
                                path = str(staged_path(key))
                                # The direct DDS and its input must remain the
                                # same binding after relocating captured bytes.
                                for _role, attributes in _TEXTURE_RESOURCE_SPECS:
                                    for attribute in attributes:
                                        if str(getattr(part, attribute, "")).replace("\\", "/").casefold() in previous_paths:
                                            setattr(part, attribute, path)
                                item = copy.copy(item)
                                item.source_dds_path = item.preview_texture_path = path
                            rebound.append(item)
                        part.preview_material_texture_inputs = tuple(rebound)
                        continue
                    for role, attributes in _TEXTURE_RESOURCE_SPECS:
                        for attribute in attributes:
                            try:
                                if _replacement_texture_path(getattr(part, attribute, "")) is not None:
                                    retained_roles.add(role)
                            except (OSError, RustMeshProtocolError) as exc:
                                invalid_roles[role] = exc
                                setattr(part, attribute, "")
                # Match the same single owner as material conversion. A PAC can
                # give several parts the same embedded material label, including
                # another part's wrapper name; that label must not merge owners.
                binding_names = {name.casefold() for binding in bindings for name in
                                 (binding.material_name, binding.submesh_name, binding.part_name) if name}
                owner_name = material_binding_name(part, binding_names)
                owned = [binding for binding in bindings
                         if owner_name in {name.casefold() for name in
                                           (binding.material_name, binding.submesh_name, binding.part_name) if name}
                         and _material_input_texture_role(binding) not in retained_roles]
                missing = [binding.texture_path for binding in owned
                           if binding.texture_path.replace("\\", "/").casefold() not in files]
                recovered_roles = {_material_input_texture_role(binding) for binding in owned} if not missing else set()
                for role, error in invalid_roles.items():
                    if role not in retained_roles | recovered_roles:
                        raise error
                if not owned or missing:
                    if required:
                        if missing:
                            raise ValueError(f"Missing prepared texture for {part.name}: {missing[0]}")
                        raise ValueError(f"Imported material has no prepared texture binding: {part.name}")
                    # Incomplete original sidecars must not block geometry-only
                    # recovery or discard bindings supplied by Archive Browser.
                    continue
                inputs = []
                for binding in owned:
                    key = binding.texture_path.replace("\\", "/").casefold()
                    file = files[key]
                    path = staged_path(key)
                    classification = classify_texture_binding(binding.parameter_name, binding.texture_path)
                    semantic, subtype, channels = _material_semantics_for_binding(binding.parameter_name, binding.texture_path)
                    values = {field.name: getattr(binding, field.name) for field in fields(PreviewMaterialTextureInput) if hasattr(binding, field.name)}
                    values.update(slot_kind=classification.slot_kind, source_texture_path=file.path, source_dds_path=str(path),
                                  preview_texture_path=str(path), texture_name=Path(file.path).name,
                                  semantic_type=semantic, semantic_subtype=subtype, packed_channels=channels,
                                  confidence="sidecar", visualized=True)
                    inputs.append(PreviewMaterialTextureInput(**values))
                for _role, attributes in _TEXTURE_RESOURCE_SPECS:
                    if _role in retained_roles:
                        continue
                    for attribute in attributes:
                        setattr(part, attribute, "")
                part.preview_material_texture_inputs = tuple(inputs)
                if required:
                    # The replacement sidecar owns both the new textures and
                    # their parameter vector. Original DDS references would
                    # otherwise look like dropped bindings to the compiler.
                    parameters = []
                    for binding in owned:
                        for parameter in binding.material_parameters:
                            if parameter not in parameters:
                                parameters.append(parameter)
                    part.preview_material_parameters = tuple(parameters)
                    part.preview_sidecar_shader_family = next(
                        (binding.shader_family for binding in owned if binding.shader_family), "")
                    # Native preview factors describe the original sidecar.
                    # Keep its unchanged surface/layer policy, but read the
                    # replacement shader's glow from its new parameter vector.
                    overrides = copy.deepcopy(getattr(part, "preview_native_material_overrides", {}) or {})
                    overrides.pop("preview_core_material_source", None)
                    for key in tuple(overrides):
                        if key.startswith(("emissive_", "emission_")) or key in {"glow_surface_color", "material_shader_family"}:
                            overrides.pop(key)
                    hints = overrides.get("native_material_hints")
                    if isinstance(hints, dict):
                        for key in tuple(hints):
                            if key.startswith("emissive_"):
                                hints.pop(key)
                    part.preview_native_material_overrides = overrides
        yield incoming


def retain_replacement_material_textures(authoring, original, prepared, textures, stop_event=None):
    """Keep already accepted direct roles when adding recovered sidecar roles."""
    from cdmw.services.mesh_rust_authoring import (
        _TEXTURE_RESOURCE_SPECS, _mesh_lods,
        _publish_rust_texture_resources,
    )

    lods = _mesh_lods(original)
    bindings, sources, retained = {}, {}, {}
    for lod_index, (before, after) in enumerate(zip(lods, _mesh_lods(prepared), strict=True)):
        for index, (source, recovered) in enumerate(zip(before, after, strict=True)):
            raise_if_cancelled(stop_event, "Replacement material preparation cancelled.")
            if (getattr(source, "preview_material_texture_inputs", ())
                    or not getattr(recovered, "preview_material_texture_inputs", ())):
                continue
            for role, attributes in _TEXTURE_RESOURCE_SPECS:
                path = next((path for attribute in attributes
                             if (path := _replacement_texture_path(getattr(recovered, attribute, ""))) is not None), None)
                if path is None:
                    continue
                sources[str(path)] = path
                bindings.setdefault((str(path), role), [set() for _ in lods])[lod_index].add(index)
                retained.setdefault((role, lod_index), set()).add(index)
    if not bindings:
        return textures
    # Publish through the same bounded, hashed DDS transport. Keep the old
    # role's authority; do not invent owner-bound sidecar rows for direct maps.
    kept = _publish_rust_texture_resources(authoring.root, bindings, sources, stop_event, authoring.root_identity)
    result = []
    for texture in textures:
        row = copy.deepcopy(texture)
        row["material_indices_by_lod"] = [
            [index for index in indices if index not in retained.get((row["role"], lod_index), ())]
            for lod_index, indices in enumerate(row["material_indices_by_lod"])]
        if any(row["material_indices_by_lod"]):
            result.append(row)
    return [*result, *kept]


def _apply_restaged_textures_to_payload(payload, levels, ordered, added, added_presentations, owners):
    presentations = {(row["lod_index"], row["material_index"]): row for row in payload["material_presentations"]}
    for row in added_presentations:
        lod, index = ordered[row["material_index"]]
        updated_row = dict(row, lod_index=lod, material_index=index)
        if (lod, index) in presentations:
            presentations[(lod, index)].update(updated_row)
        else:
            presentations[(lod, index)] = updated_row
            payload["material_presentations"].append(presentations[(lod, index)])
    for row in payload["textures"]:
        row["material_indices_by_lod"] = [[index for index in indices if (lod, index) not in owners]
                                          for lod, indices in enumerate(row["material_indices_by_lod"])]
    for row in added:
        targets = [ordered[index] for index in row["material_indices_by_lod"][0]]
        row["material_indices_by_lod"] = [[index for level, index in targets if level == lod] for lod in range(len(levels))]
    payload["textures"] = [row for row in payload["textures"] if any(row["material_indices_by_lod"])] + added
    if graph := payload.get("preview_core_material_graph"):
        graph["materials"] = [row for row in graph["materials"] if (row["lod_index"], row["material_index"]) not in owners]


def _bake_edited_native_layers(authoring, mesh, payload, owners, stop_event):
    """Material controls consume the same composed maps as before GPU layers."""
    from cdmw.services.mesh_rust_authoring import (
        _mesh_lods, _mesh_texture_payloads, _mesh_material_presentations, _RustMaterialSynthesisState,
    )

    graph = payload.get("preview_core_material_graph")
    if not graph:
        return
    owners = owners.intersection((row["lod_index"], row["material_index"]) for row in graph["materials"])
    if not owners:
        return
    local = copy.copy(mesh)
    ordered = sorted(owners)
    levels = _mesh_lods(mesh)
    local.submeshes = [copy.copy(levels[lod][index]) for lod, index in ordered]
    local.lod_levels = [local.submeshes]
    for part in local.submeshes:
        part.preview_native_material_overrides = dict(part.preview_native_material_overrides)
        part.preview_native_material_overrides.pop("preview_core_material_source", None)
    synthesis = _RustMaterialSynthesisState()
    added = _mesh_texture_payloads(authoring.root, local, expected_root_identity=authoring.root_identity,
                                   stop_event=stop_event, synthesis_state=synthesis)
    if synthesis.diagnostics:
        raise ValueError("Edited source material preview could not be compiled: " + str(synthesis.diagnostics[0]))
    added_presentations = _mesh_material_presentations(local, generated_overrides=synthesis.presentation_overrides)
    _apply_restaged_textures_to_payload(payload, levels, ordered, added, added_presentations, owners)


def _stage_companion_dds_materials(authoring, mesh, state, key, stop_event):
    """Publish original-material companion DDS overrides (such as hair color and DDS edits) for Rust."""
    from pathlib import PurePosixPath
    from cdmw.core.archive_model_references import _parse_archive_model_sidecar_texture_bindings
    from cdmw.core.dds_native import inspect_dds_native
    from cdmw.services.mesh_rust_authoring import (
        _RUST_TEXTURE_PATH_NAME_COMPANIONS, _TEXTURE_RESOURCE_SPECS, _RustMaterialSynthesisState,
        _mesh_lods, _mesh_material_presentations, _mesh_texture_payloads, _material_input_texture_role,
    )

    companion_dds = {
        str(file.path or "").replace("\\", "/").casefold(): file
        for file in state.companion_files
        if str(file.path or "").replace("\\", "/").casefold().endswith(".dds")
    }
    base_cache = authoring.archive_refit_material_cache.get("base")
    payload = copy.deepcopy(base_cache) if base_cache is not None else {
        "key": "base", "textures": [], "material_presentations": [], "reason": "",
        "material_contract": {}, "preview_core_material_graph": None,
    }
    levels = _mesh_lods(mesh)
    companion_digests = {
        logical: hashlib.sha256(file.data).digest()
        for logical, file in companion_dds.items()
    }
    original_digests = {
        str(file.path or "").replace("\\", "/").casefold(): hashlib.sha256(file.data).digest()
        for file in state.dependencies
        if str(file.path or "").replace("\\", "/").casefold() in companion_dds
    }
    sidecar_bindings = []
    for file in (*state.dependencies, *state.companion_files):
        if Path(file.path).suffix.lower() in {".pac_xml", ".pami"}:
            try:
                sidecar_bindings.extend(_parse_archive_model_sidecar_texture_bindings(_sidecar_text(file.data), sidecar_path=file.path))
            except ValueError:
                continue
    sidecar_owners = {
        name.casefold()
        for binding in sidecar_bindings
        if str(binding.texture_path or "").replace("\\", "/").casefold() in companion_dds
        for name in (binding.material_name, binding.submesh_name, binding.part_name)
        if name
    }
    sidecar_all_names = {
        name.casefold()
        for binding in sidecar_bindings
        for name in (binding.material_name, binding.submesh_name, binding.part_name)
        if name
    }

    with TemporaryDirectory(prefix="cdmw-hair-companion-preview-") as temporary:
        staged_files = {}

        def staged_dds_path(logical: str) -> Path:
            if logical not in staged_files:
                data = companion_dds[logical].data
                inspect_dds_native(data)
                path = Path(temporary) / f"{len(staged_files)}_{PurePosixPath(logical).name}"
                path.write_bytes(data)
                staged_files[logical] = path
            return staged_files[logical]

        def resolve_logical(hints, raw_path="") -> str | None:
            for value in hints:
                norm = str(value or "").replace("\\", "/").casefold()
                if norm in companion_dds:
                    return norm
            raw_text = str(raw_path or "")
            if raw_text:
                raw_obj = Path(raw_text)
                if raw_obj.is_file():
                    try:
                        digest = hashlib.sha256(raw_obj.read_bytes()).digest()
                        matches = [
                            k for k in companion_dds
                            if companion_digests.get(k) == digest or original_digests.get(k) == digest
                        ]
                        if len(matches) == 1:
                            return matches[0]
                    except OSError:
                        pass
            names = {PurePosixPath(str(v).replace("\\", "/")).name.casefold() for v in (*hints, raw_text) if v}
            by_name = [k for k in companion_dds if PurePosixPath(k).name.casefold() in names]
            return by_name[0] if len(by_name) == 1 else None

        rebound_parts: dict[tuple[int, int], object] = {}
        for lod_index, level in enumerate(levels):
            for part_index, original_part in enumerate(level):
                raise_if_cancelled(stop_event, "Hair material preparation cancelled.")
                part = copy.copy(original_part)
                matched = False
                inputs = tuple(getattr(part, "preview_material_texture_inputs", ()) or ())
                parameters = tuple(getattr(part, "preview_material_parameters", ()) or ())
                updated_inputs = []
                rewritten_aliases: dict[tuple[str, str], str] = {}
                for item in inputs:
                    declared = [
                        p.texture_path for p in (*getattr(item, "material_parameters", ()), *parameters)
                        if item.parameter_name and p.parameter_name == item.parameter_name
                    ]
                    owner = resolve_logical(
                        (getattr(item, "source_texture_path", ""), *declared, getattr(item, "texture_name", "")),
                        getattr(item, "source_dds_path", "") or getattr(item, "preview_texture_path", ""),
                    )
                    role = _material_input_texture_role(item)
                    for old_val in (getattr(item, "source_dds_path", ""), getattr(item, "preview_texture_path", "")):
                        if old_val and owner is not None:
                            rewritten_aliases[(role, str(old_val).replace("\\", "/").casefold())] = owner
                    if owner is not None:
                        local_path = str(staged_dds_path(owner))
                        item = replace(item, source_texture_path=owner, source_dds_path=local_path, preview_texture_path=local_path)
                        matched = True
                    updated_inputs.append(item)
                if inputs:
                    part.preview_material_texture_inputs = tuple(updated_inputs)
                for role, attributes in _TEXTURE_RESOURCE_SPECS:
                    for attribute in attributes:
                        cur_val = str(getattr(part, attribute, "") or "")
                        name_attr = _RUST_TEXTURE_PATH_NAME_COMPANIONS.get(attribute, "texture")
                        owner = rewritten_aliases.get((role, cur_val.replace("\\", "/").casefold()))
                        if owner is None:
                            owner = resolve_logical((getattr(part, name_attr, ""),), cur_val)
                        if owner is not None:
                            local_path = str(staged_dds_path(owner))
                            setattr(part, attribute, local_path)
                            paired = attribute.replace("_dds_path", "_path")
                            if paired != attribute and hasattr(part, paired):
                                setattr(part, paired, local_path)
                            matched = True
                if not matched and sidecar_owners:
                    owner_name = material_binding_name(part, sidecar_all_names)
                    if owner_name in sidecar_owners:
                        matched = True
                if matched:
                    overrides = dict(getattr(part, "preview_native_material_overrides", {}) or {})
                    overrides.pop("preview_core_material_source", None)
                    part.preview_native_material_overrides = overrides
                    rebound_parts[(lod_index, part_index)] = part

        if not rebound_parts and companion_dds:
            # Synthetic or direct-attribute-free sessions: stage every LOD0 part cleanly.
            for part_index, original_part in enumerate(levels[0]):
                part = copy.copy(original_part)
                overrides = dict(getattr(part, "preview_native_material_overrides", {}) or {})
                overrides.pop("preview_core_material_source", None)
                part.preview_native_material_overrides = overrides
                rebound_parts[(0, part_index)] = part

        ordered = sorted(rebound_parts)
        if ordered:
            subset = copy.copy(mesh)
            subset.submeshes = [rebound_parts[loc] for loc in ordered]
            subset.lod_levels = [subset.submeshes]
            if any(not getattr(p, "preview_material_texture_inputs", ()) for p in subset.submeshes) and any(
                Path(f.path).suffix.lower() in {".pac_xml", ".pami"} for f in (*state.dependencies, *state.companion_files)
            ):
                ctx = prepared_replacement_material_mesh(subset, (*state.dependencies, *state.companion_files), required=False, stop_event=stop_event)
            else:
                from contextlib import nullcontext
                ctx = nullcontext(subset)
            with ctx as compiled_mesh:
                synthesis = _RustMaterialSynthesisState()
                added = _mesh_texture_payloads(
                    authoring.root, compiled_mesh, expected_root_identity=authoring.root_identity,
                    stop_event=stop_event, synthesis_state=synthesis,
                )
                if synthesis.diagnostics:
                    raise ValueError("Edited source material preview could not be compiled: " + str(synthesis.diagnostics[0]))
                added_presentations = _mesh_material_presentations(compiled_mesh, generated_overrides=synthesis.presentation_overrides)
                _apply_restaged_textures_to_payload(payload, levels, ordered, added, added_presentations, set(ordered))
    payload["key"] = key
    conserve_preview_core_material_graph(payload)
    authoring.archive_refit_material_cache[key] = payload


def stage_replacement_materials(authoring, mesh, state, stop_event=None):
    from cdmw.services.mesh_rust_authoring import (
        _atomic_write_payload, _mesh_texture_payloads, _mesh_lods,
        _canonical_json_bytes, _RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES,
        _RustMaterialSynthesisState, _mesh_material_presentations,
    )
    key = replacement_material_key(mesh, state)
    if key not in authoring.archive_refit_material_cache and any(part.translucency is not None or part.emission is not None or part.shader_controls is not None for part in state.parts):
        source = replace(state, parts=tuple(replace(part, translucency=None, translucency_surface=None, emission=None, shader_controls=None) for part in state.parts))
        source_key = stage_replacement_materials(authoring, mesh, source, stop_event)
        payload = copy.deepcopy(authoring.archive_refit_material_cache[source_key])
        indices = bound_part_indices(mesh, state)
        rules = {indices[part.part_id]: (part.translucency, part.translucency_surface, part.emission, part.shader_controls)
                 for part in state.parts if part.translucency is not None or part.emission is not None or part.shader_controls is not None}
        presentations = {(row["lod_index"], row["material_index"]): row for row in payload["material_presentations"]}
        from cdmw.services.mesh_replacement_materials import material_binding_name, material_binding_names
        bindings = material_binding_names(state)
        names = {material_binding_name(mesh.submeshes[index], bindings): value
                 for index, value in rules.items()}
        _bake_edited_native_layers(authoring, mesh, payload,
            {(lod, index) for lod, level in enumerate(_mesh_lods(mesh)) for index, part in enumerate(level)
             if (rules.get(index) if lod == 0 else names.get(material_binding_name(part, bindings))) is not None}, stop_event)
        for lod_index, level in enumerate(_mesh_lods(mesh)):
            for index, part in enumerate(level):
                value = rules.get(index) if lod_index == 0 else names.get(material_binding_name(part, bindings))
                if value is not None:
                    row = presentations.setdefault((lod_index, index), {"lod_index": lod_index, "material_index": index})
                    if value[0] is not None:
                        row["translucency"] = list(value[0])
                        row["translucency_surface"] = list(value[1]) if value[1] is not None else None
                    if value[2] is not None:
                        row["emissive_color"] = list(value[2].color)
                        row["emissive_intensity"] = value[2].intensity
                        row["emission_animation"] = list(value[2].animation.factors())
                        row["emission_reveal"] = list(value[2].rgb.factors()) if value[2].rgb is not None else [0.0, 1.0, 0.0, -1.0]
        if any(part.shader_controls is not None for part in state.parts):
            from cdmw.services.mesh_shader_controls_preview import stage_shader_preview
            stage_shader_preview(authoring, mesh, state, payload, presentations, stop_event)
        payload.update(key=key, material_presentations=list(presentations.values()))
        # The bake and the shader preview replaced graph rows and textures.
        conserve_preview_core_material_graph(payload)
        authoring.archive_refit_material_cache[key] = payload
    if key not in authoring.archive_refit_material_cache:
        indices = bound_part_indices(mesh, state)
        selected = [indices[part.part_id] for part in state.parts if part.material_choice == "imported"]
        if not selected:
            _stage_companion_dds_materials(authoring, mesh, state, key, stop_event)
        else:
            incoming = copy.copy(mesh)
            incoming.submeshes = [mesh.submeshes[index] for index in selected]
            incoming.lod_levels = [incoming.submeshes]
            synthesis = _RustMaterialSynthesisState()
            with prepared_replacement_material_mesh(incoming, (*state.dependencies, *state.companion_files),
                                                    required=True, stop_event=stop_event) as incoming:
                added = _mesh_texture_payloads(authoring.root, incoming, expected_root_identity=authoring.root_identity,
                                              stop_event=stop_event, synthesis_state=synthesis)
                added_presentations = _mesh_material_presentations(incoming, generated_overrides=synthesis.presentation_overrides)
                if synthesis.diagnostics:
                    raise ValueError("Prepared replacement material preview could not be compiled: " + str(synthesis.diagnostics[0]))
                if not added:
                    raise ValueError("Prepared replacement materials produced no renderer resources.")
            retained = authoring.archive_refit_material_cache["base"]
            textures = []
            for texture in retained["textures"]:
                row = copy.deepcopy(texture)
                row["material_indices_by_lod"][0] = [index for index in row["material_indices_by_lod"][0] if index not in selected]
                if any(row["material_indices_by_lod"]):
                    textures.append(row)
            for texture in added:
                texture["material_indices_by_lod"] = [[selected[index] for index in texture["material_indices_by_lod"][0]],
                                                      *([] for _ in range(len(_mesh_lods(mesh)) - 1))]
            presentations = [row for row in retained["material_presentations"] if row["lod_index"] != 0 or row["material_index"] not in selected]
            for row in added_presentations:
                row["material_index"] = selected[row["material_index"]]
                presentations.append(row)
            authoring.archive_refit_material_cache[key] = {
                "key": key, "textures": [*textures, *added],
                "material_presentations": presentations, "reason": "",
                "material_contract": copy.deepcopy(retained.get("material_contract", {})),
                "preview_core_material_graph": copy.deepcopy(retained.get("preview_core_material_graph")),
            }
            if graph := authoring.archive_refit_material_cache[key]["preview_core_material_graph"]:
                graph["materials"] = [row for row in graph["materials"] if row["lod_index"] != 0 or row["material_index"] not in selected]
            # The imported parts left the graph and brought their own textures: the
            # editor refuses a graph whose totals no longer match (or that is empty).
            conserve_preview_core_material_graph(authoring.archive_refit_material_cache[key])
    for cache_key in (("base", key) if "base" in authoring.archive_refit_material_cache else (key,)):
        if cache_key in authoring.archive_refit_material_references:
            continue
        authoring._raise_if_cancelled(stop_event)
        payload = authoring.archive_refit_material_cache[cache_key]
        if len(_canonical_json_bytes(payload)) > _RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES:
            raise ValueError("Replacement material metadata exceeds the 16 MiB session limit")
        authoring.archive_refit_material_references[cache_key] = _atomic_write_payload(
            authoring.root, f"material-state-{cache_key}.json", payload, data_type="mesh_materials_json",
            element_count=1, expected_root_identity=authoring.root_identity)
    return key
