"""Publish prepared replacement textures through the existing material contract."""

from __future__ import annotations

import copy
import hashlib
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory

from cdmw.core.common import raise_if_cancelled
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
                owned = [binding for binding in bindings
                         if {binding.material_name, binding.submesh_name, binding.part_name} & {part.name, part.material}
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


def stage_replacement_materials(authoring, mesh, state, stop_event=None):
    from cdmw.services.mesh_rust_authoring import (
        _atomic_write_payload, _mesh_texture_payloads, _mesh_lods,
        _canonical_json_bytes, _RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES,
        _RustMaterialSynthesisState, _mesh_material_presentations,
    )
    key = replacement_material_key(mesh, state)
    if key not in authoring.archive_refit_material_cache:
        indices = bound_part_indices(mesh, state)
        selected = [indices[part.part_id] for part in state.parts if part.material_choice == "imported"]
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
