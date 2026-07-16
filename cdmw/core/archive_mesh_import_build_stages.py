from __future__ import annotations

import dataclasses
from pathlib import Path

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_mesh_import_build_state import MeshImportBuildState
from cdmw.core.common import raise_if_cancelled
from cdmw.modding.static_mesh_replacer import StaticMeshReplacementOptions


def _public_api():
    from cdmw.core import archive_mesh_import_preview as public

    return public


def load_mesh_import_sources(state: MeshImportBuildState) -> None:
    api = _public_api()
    raise_if_cancelled(state.stop_event, "Mesh import preview cancelled.")
    if state.scene_import_result is None:
        state.scene_import_result = api.import_scene_mesh_with_report(
            state.obj_path,
            stop_event=state.stop_event,
        )
    state.imported_mesh = state.scene_import_result.mesh
    state.imported_mesh.path = state.entry.path
    state.imported_mesh.format = state.entry.extension.lstrip(".").lower()
    state.manifest_payload = (
        api._load_obj_roundtrip_sidecar(str(state.obj_path))
        if state.obj_path.suffix.lower() == ".obj" and state.obj_path.expanduser().is_file()
        else None
    )
    state.original_baseline = api.read_archive_entry_baseline_data(
        state.entry,
        read_entry_data=lambda entry: read_archive_entry_data(entry, stop_event=state.stop_event),
    )
    state.original_data = state.original_baseline.data
    state.original_mesh = api.parse_mesh(state.original_data, state.entry.path)
    if state.texture_entries_by_basename is not None:
        state.original_sidecars_for_static = api._collect_original_mesh_sidecar_texts(
            state.entry,
            state.texture_entries_by_basename,
            stop_event=state.stop_event,
        )
    raise_if_cancelled(state.stop_event, "Mesh import preview cancelled.")


def rebuild_mesh_import(state: MeshImportBuildState) -> None:
    api = _public_api()
    state.normalized_import_mode = str(state.import_mode or "roundtrip").strip().lower()
    state.effective_static_source_mesh = state.imported_mesh
    if state.normalized_import_mode in {"static", "static_replacement", "static-mesh-replacement"}:
        options = state.static_replacement_options or StaticMeshReplacementOptions()
        if bool(getattr(options, "full_import_model_replacement", False)) and not state.original_sidecars_for_static:
            raise ValueError(
                "Full Import Model Replacement requires a target material sidecar (.pac_xml/.pami) so "
                "the imported model can own texture/material bindings instead of inheriting old target slots."
            )
        state.effective_static_source_mesh = api.effective_static_replacement_source_mesh(
            state.original_mesh,
            state.imported_mesh,
            options,
        )
        state.enable_missing_base_color_parameters = bool(
            getattr(options, "enable_missing_base_color_parameters", False)
        )
        state.static_mappings = options.submesh_mappings or api.suggest_static_submesh_mappings(
            state.original_mesh,
            state.effective_static_source_mesh,
        )
        if not options.submesh_mappings:
            options = dataclasses.replace(options, submesh_mappings=state.static_mappings)
        if bool(getattr(options, "complete_external_swap", False)):
            names = api._source_owned_target_names_from_sidecars(
                state.original_sidecars_for_static,
                original_mesh=state.original_mesh,
            )
            if names:
                options = dataclasses.replace(options, source_owned_target_names=list(names))
        state.rebuilt_data, state.static_report = api.build_static_mesh_replacement(
            state.original_data,
            state.original_mesh,
            state.imported_mesh,
            options,
        )
        state.normalized_import_mode = "static_replacement"
    else:
        if state.obj_path.suffix.lower() != ".obj":
            raise ValueError(
                "Round-trip edit import only supports OBJ. Use Mesh Replacement for DAE, GLB, or glTF imports."
            )
        state.rebuilt_data = api.build_mesh(state.imported_mesh, state.original_data)
        state.static_report = None
        state.normalized_import_mode = "roundtrip"
    raise_if_cancelled(state.stop_event, "Mesh import preview cancelled.")
    state.parsed_mesh = api.parse_mesh(state.rebuilt_data, state.entry.path)
    restored = api._restore_rebuilt_mesh_texture_identity(state.imported_mesh, state.parsed_mesh)
    state.preview_model = api.parsed_mesh_to_preview_model(state.parsed_mesh)
    start_mesh_import_summary(state, restored)


def start_mesh_import_summary(state: MeshImportBuildState, restored_texture_count: int) -> None:
    state.summary_lines = [
        f"Preview rebuilt mesh for {state.entry.path}",
        f"Import mode: {'Mesh replacement' if state.normalized_import_mode == 'static_replacement' else 'Round-trip edit'}",
        f"Vertices: {state.parsed_mesh.total_vertices:,}",
        f"Faces: {state.parsed_mesh.total_faces:,}",
        f"Submeshes: {len(state.parsed_mesh.submeshes):,}",
        f"Rebuilt size: {len(state.rebuilt_data):,} bytes",
    ]
    if state.source_display_label.strip():
        state.summary_lines.append(f"Replacement source: {state.source_display_label.strip()}")
    if state.original_baseline.message:
        state.summary_lines.append(f"Original mesh donor: {state.original_baseline.message}")
    if state.scene_import_result.diagnostics:
        state.summary_lines.append("Scene import notes:")
        state.summary_lines.extend(f"  {line}" for line in state.scene_import_result.diagnostics)
    if state.static_report is not None:
        report = state.static_report
        state.summary_lines.append(
            "Static replacement analysis: "
            f"original {report.original_submesh_count} submesh(es), "
            f"replacement {report.replacement_submesh_count} source submesh(es)."
        )
        for label, lines in (
            ("Static replacement mapping:", report.mapping_summary),
            ("Static replacement warnings:", report.warnings),
            ("Static replacement alignment:", report.alignment_summary),
        ):
            if lines:
                state.summary_lines.append(label)
                state.summary_lines.extend(f"  {line}" for line in lines)
    if restored_texture_count:
        state.summary_lines.append(
            f"Restored {restored_texture_count:,} imported submesh texture identifier(s) onto rebuilt preview metadata."
        )


def resolve_mesh_import_supplemental_files(state: MeshImportBuildState) -> None:
    api = _public_api()
    state.resolved_supplemental_files = tuple(
        path.expanduser().resolve()
        for path in state.supplemental_files
        if isinstance(path, Path) and path.expanduser().resolve().is_file()
    )
    if state.normalized_import_mode == "static_replacement":
        discovered = tuple(
            path
            for path in (
                tuple(state.scene_import_result.discovered_texture_files)
                + tuple(state.scene_import_result.extracted_embedded_files)
                + tuple(getattr(state.scene_import_result, "discovered_supplemental_files", ()) or ())
                + (
                    tuple(api.discover_scene_texture_files(state.obj_path, state.imported_mesh))
                    if state.obj_path.expanduser().is_file()
                    else ()
                )
            )
            if path.is_file()
        )
        seen = {str(path).lower() for path in state.resolved_supplemental_files}
        appended = [path for path in discovered if str(path).lower() not in seen]
        if appended:
            state.resolved_supplemental_files += tuple(appended)
            state.summary_lines.append(
                f"Auto-discovered {len(appended):,} supplemental texture/sidecar file(s) next to the imported mesh."
            )
    if state.resolved_supplemental_files:
        state.summary_lines.append(f"Selected supplemental files: {len(state.resolved_supplemental_files):,}")
        state.summary_lines.extend(
            api._summarize_crimson_companion_supplemental_files(state.resolved_supplemental_files)
        )


def resolve_mesh_import_sidecars(state: MeshImportBuildState) -> None:
    api = _public_api()
    from cdmw.core.archive_model_references import (
        _extract_archive_model_sidecar_texture_references,
        _normalize_model_visible_texture_mode,
    )

    state.normalized_visible_texture_mode = _normalize_model_visible_texture_mode(state.visible_texture_mode)
    if state.resolved_supplemental_files:
        (
            state.selected_sidecar_texture_references,
            state.selected_sidecar_reference_paths,
            state.selected_sidecar_texts_by_normalized_path,
            state.selected_sidecar_texts_by_basename,
        ) = api._build_selected_sidecar_texture_bindings(state.resolved_supplemental_files)
        if state.selected_sidecar_texture_references:
            state.summary_lines.append(
                f"Using {len(state.selected_sidecar_texture_references):,} texture binding(s) from selected local sidecar file(s): "
                f"{', '.join(state.selected_sidecar_reference_paths[:3])}"
                + (" ..." if len(state.selected_sidecar_reference_paths) > 3 else "")
            )
    if state.texture_entries_by_basename is not None:
        (
            state.original_archive_sidecar_texture_references,
            state.original_archive_sidecar_reference_paths,
            state.sidecar_texts_by_normalized_path,
            state.sidecar_texts_by_basename,
        ) = _extract_archive_model_sidecar_texture_references(
            state.entry,
            archive_entries_by_basename=dict(state.texture_entries_by_basename),
        )
        if state.original_archive_sidecar_texture_references and not state.selected_sidecar_texture_references:
            paths = state.original_archive_sidecar_reference_paths
            suffix = f" from {', '.join(paths[:2])}" if paths else ""
            suffix += " ..." if len(paths) > 2 else ""
            state.summary_lines.append(
                f"Companion material sidecar data contributed "
                f"{len(state.original_archive_sidecar_texture_references):,} texture binding(s){suffix}."
            )
            state.summary_lines.append(
                "Loose mesh mods may still need the matching companion .xml sidecar when custom material or texture remaps are involved."
            )
    if state.original_archive_sidecar_texture_references:
        state.sidecar_texture_references = state.original_archive_sidecar_texture_references
        state.sidecar_reference_paths = state.original_archive_sidecar_reference_paths
    if state.selected_sidecar_texture_references:
        state.sidecar_texture_references = state.selected_sidecar_texture_references
        state.sidecar_reference_paths = state.selected_sidecar_reference_paths
        state.sidecar_texts_by_normalized_path = state.selected_sidecar_texts_by_normalized_path
        state.sidecar_texts_by_basename = state.selected_sidecar_texts_by_basename
    state.summary_lines.extend(
        api._mesh_import_runtime_sibling_warning_lines(
            state.entry,
            state.parsed_mesh,
            state.texture_entries_by_basename,
            state.original_sidecars_for_static,
        )
    )


def attach_mesh_import_texture_previews(state: MeshImportBuildState) -> None:
    api = _public_api()
    from cdmw.core import archive_model_textures as textures

    kwargs = dict(
        texture_entries_by_normalized_path=(
            dict(state.texture_entries_by_normalized_path)
            if state.texture_entries_by_normalized_path is not None
            else None
        ),
        texture_entries_by_basename=(
            dict(state.texture_entries_by_basename) if state.texture_entries_by_basename is not None else None
        ),
        sidecar_texts_by_normalized_path=state.sidecar_texts_by_normalized_path,
        sidecar_texts_by_basename=state.sidecar_texts_by_basename,
        stop_event=state.stop_event,
    )
    if state.sidecar_texture_references:
        state.summary_lines.extend(
            textures._attach_model_sidecar_texture_preview_paths(
                state.entry,
                state.preview_model,
                parsed_mesh=state.parsed_mesh,
                sidecar_texture_bindings=state.sidecar_texture_references,
                visible_texture_mode=state.normalized_visible_texture_mode,
                **kwargs,
            )
        )
    state.summary_lines.extend(
        textures._attach_model_texture_preview_paths(
            state.entry,
            state.preview_model,
            **kwargs,
        )
    )
    if state.sidecar_texture_references and state.normalized_visible_texture_mode == "mesh_base_first":
        state.summary_lines.extend(
            textures._attach_model_sidecar_texture_preview_paths(
                state.entry,
                state.preview_model,
                parsed_mesh=state.parsed_mesh,
                sidecar_texture_bindings=state.sidecar_texture_references,
                visible_texture_mode="layer_aware_visible",
                fallback_only=True,
                **kwargs,
            )
        )
        state.summary_lines.extend(
            textures._attach_model_texture_preview_paths(
                state.entry,
                state.preview_model,
                override_existing_base=True,
                prefer_material_name_for_base=True,
                **kwargs,
            )
        )
    state.summary_lines.extend(
        textures._attach_model_support_texture_preview_paths(
            state.entry,
            state.preview_model,
            parsed_mesh=state.parsed_mesh,
            sidecar_texture_bindings=state.sidecar_texture_references,
            **kwargs,
        )
    )
    if state.resolved_supplemental_files:
        by_path, by_name = api._build_mesh_import_local_dds_lookup(state.resolved_supplemental_files)
        if state.selected_sidecar_texture_references:
            state.summary_lines.extend(
                api._apply_mesh_import_local_sidecar_texture_overrides(
                    state.preview_model,
                    state.parsed_mesh,
                    state.selected_sidecar_texture_references,
                    by_path,
                    by_name,
                )
            )
            state.summary_lines.extend(
                api._apply_mesh_import_local_support_texture_overrides(
                    state.preview_model,
                    state.parsed_mesh,
                    state.selected_sidecar_texture_references,
                    by_path,
                    by_name,
                )
            )
        state.summary_lines.extend(
            api._apply_mesh_import_local_texture_overrides(
                state.preview_model,
                by_path,
                by_name,
            )
        )


def collect_mesh_import_references(state: MeshImportBuildState) -> None:
    api = _public_api()
    from cdmw.core import archive_model_textures as textures

    state.texture_references = tuple(
        textures.build_archive_model_texture_references(
            state.entry,
            state.preview_model,
            parsed_mesh=state.parsed_mesh,
            sidecar_texture_references=state.sidecar_texture_references,
            texture_entries_by_normalized_path=(
                dict(state.texture_entries_by_normalized_path)
                if state.texture_entries_by_normalized_path is not None
                else None
            ),
            texture_entries_by_basename=(
                dict(state.texture_entries_by_basename) if state.texture_entries_by_basename is not None else None
            ),
            sidecar_texts_by_normalized_path=state.sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=state.sidecar_texts_by_basename,
        )
    )
    state.supplemental_file_specs = api._build_mesh_import_supplemental_file_specs(
        state.entry,
        state.resolved_supplemental_files,
        state.texture_references,
        archive_entries_by_normalized_path=state.archive_entries_by_normalized_path,
        archive_entries_by_basename=state.texture_entries_by_basename,
        stop_event=state.stop_event,
    )


def prepare_mesh_import_paired_lod(state: MeshImportBuildState) -> None:
    if not (
        state.normalized_import_mode in {"roundtrip", "static_replacement"}
        and state.entry.extension == ".pam"
        and state.archive_entries_by_normalized_path is not None
    ):
        return
    api = _public_api()
    paired_path = Path(state.entry.path).with_suffix(".pamlod").as_posix()
    candidates = state.archive_entries_by_normalized_path.get(api._normalize_virtual_path(paired_path), ())
    if not candidates:
        return
    paired_entry = candidates[0]
    baseline = api.read_archive_entry_baseline_data(
        paired_entry,
        read_entry_data=lambda entry: read_archive_entry_data(entry, stop_event=state.stop_event),
    )
    source_mesh = state.parsed_mesh if state.normalized_import_mode == "static_replacement" else state.imported_mesh
    try:
        paired_mesh = api.transfer_pam_edit_to_pamlod_mesh(
            source_mesh,
            state.original_data,
            baseline.data,
            paired_entry.path,
        )
        state.paired_lod_data = api.build_mesh(paired_mesh, baseline.data)
        state.paired_lod_path = paired_entry.path
        state.summary_lines.append(f"Paired PAMLOD rebuild prepared: {paired_entry.path}")
        if baseline.message:
            state.summary_lines.append(f"Paired LOD donor: {baseline.message}")
    except Exception as exc:
        raise_if_cancelled(state.stop_event, "Mesh import preview cancelled.")
        state.summary_lines.append(f"Paired PAMLOD rebuild could not be prepared: {exc}")


def finish_mesh_import_preview(state: MeshImportBuildState):
    api = _public_api()
    diffs, issues, auto_fix, validation_lines = api._build_mesh_import_validation(
        state.entry,
        state.original_mesh,
        state.parsed_mesh,
        import_mode=state.normalized_import_mode,
        texture_references=state.texture_references,
        supplemental_file_specs=state.supplemental_file_specs,
        original_sidecar_bindings=state.original_archive_sidecar_texture_references,
        selected_sidecar_bindings=state.selected_sidecar_texture_references,
        paired_lod_path=state.paired_lod_path,
        manifest_payload=state.manifest_payload,
    )
    state.summary_lines.extend(validation_lines)
    raise_if_cancelled(state.stop_event, "Mesh import preview cancelled.")
    return api.MeshImportPreviewResult(
        rebuilt_data=state.rebuilt_data,
        parsed_mesh=state.parsed_mesh,
        preview_model=state.preview_model,
        summary_lines=state.summary_lines,
        import_mode=state.normalized_import_mode,
        texture_references=state.texture_references,
        supplemental_file_specs=state.supplemental_file_specs,
        paired_lod_data=state.paired_lod_data,
        paired_lod_path=state.paired_lod_path,
        import_diffs=diffs,
        import_issues=issues,
        auto_fix_result=auto_fix,
        roundtrip_manifest=state.manifest_payload if isinstance(state.manifest_payload, dict) else None,
        source_owned_output_draw_sections=tuple(getattr(state.static_report, "output_draw_sections", ()) or ()),
        material_authority_settings=state.material_authority_settings,
    )
