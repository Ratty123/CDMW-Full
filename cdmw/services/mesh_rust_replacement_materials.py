"""Publish prepared replacement textures through the existing material contract."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory

from cdmw.domain.mesh.replacement import bound_part_indices
from cdmw.services.mesh_replacement_materials import _sidecar_text


def replacement_material_key(mesh, state):
    if not any(part.material_choice == "imported" for part in state.parts):
        return "base"
    digest = hashlib.sha256(repr((bound_part_indices(mesh, state), [(p.part_id, p.material_choice) for p in state.parts])).encode())
    for file in state.companion_files:
        digest.update(file.path.encode())
        digest.update(file.data)
    return digest.hexdigest()[:32]


def stage_replacement_materials(authoring, mesh, state, stop_event=None):
    from cdmw.core.archive_model_references import _parse_archive_model_sidecar_texture_bindings
    from cdmw.core.final_package_preview_model import _material_semantics_for_binding
    from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput
    from cdmw.services.mesh_rust_authoring import (
        _atomic_write_payload, _mesh_texture_payloads, _mesh_lods,
        _canonical_json_bytes, _RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES,
        _TEXTURE_RESOURCE_SPECS, _RustMaterialSynthesisState, _mesh_material_presentations,
    )
    key = replacement_material_key(mesh, state)
    if key not in authoring.archive_refit_material_cache:
        indices = bound_part_indices(mesh, state)
        selected = [indices[part.part_id] for part in state.parts if part.material_choice == "imported"]
        files = {file.path.replace("\\", "/").casefold(): file for file in (*state.dependencies, *state.companion_files)}
        bindings = [binding for file in files.values() if Path(file.path).suffix.lower() in {".pac_xml", ".pami"}
                    for binding in _parse_archive_model_sidecar_texture_bindings(_sidecar_text(file.data), sidecar_path=file.path)]
        incoming = copy.copy(mesh)
        incoming.submeshes = [copy.copy(mesh.submeshes[index]) for index in selected]
        incoming.lod_levels = [incoming.submeshes]
        synthesis = _RustMaterialSynthesisState()
        with TemporaryDirectory(prefix="cdmw-replacement-preview-") as temporary:
            for local_index, part in enumerate(incoming.submeshes):
                for _role, attributes in _TEXTURE_RESOURCE_SPECS:
                    for attribute in attributes:
                        setattr(part, attribute, "")
                part.preview_material_texture_inputs = ()
                target = mesh.submeshes[selected[local_index]]
                owned = [binding for binding in bindings if {binding.material_name, binding.submesh_name, binding.part_name} & {target.name, target.material}]
                inputs = []
                for binding_index, binding in enumerate(owned):
                    file = files.get(binding.texture_path.replace("\\", "/").casefold())
                    if file is None:
                        raise ValueError(f"Missing prepared texture for {target.name}: {binding.texture_path}")
                    path = Path(temporary) / f"{local_index}-{binding_index}.dds"
                    path.write_bytes(file.data)
                    from cdmw.modding.asset_replacement import classify_texture_binding
                    classification = classify_texture_binding(binding.parameter_name, binding.texture_path)
                    semantic, subtype, channels = _material_semantics_for_binding(binding.parameter_name, binding.texture_path)
                    values = {field.name: getattr(binding, field.name) for field in fields(PreviewMaterialTextureInput) if hasattr(binding, field.name)}
                    values.update(slot_kind=classification.slot_kind, source_texture_path=file.path, source_dds_path=str(path),
                                  preview_texture_path=str(path), texture_name=Path(file.path).name,
                                  semantic_type=semantic, semantic_subtype=subtype, packed_channels=channels,
                                  confidence="sidecar", visualized=True)
                    inputs.append(PreviewMaterialTextureInput(**values))
                if not inputs:
                    raise ValueError(f"Imported material has no prepared texture binding: {target.name}")
                part.preview_material_texture_inputs = tuple(inputs)
            added = _mesh_texture_payloads(authoring.root, incoming, expected_root_identity=authoring.root_identity,
                                          stop_event=stop_event, synthesis_state=synthesis)
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
        for row in _mesh_material_presentations(incoming, generated_overrides=synthesis.presentation_overrides):
            row["material_index"] = selected[row["material_index"]]
            presentations.append(row)
        authoring.archive_refit_material_cache[key] = {
            "key": key, "textures": [*textures, *added],
            "material_presentations": presentations, "reason": "",
        }
    for cache_key in ("base", key):
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
