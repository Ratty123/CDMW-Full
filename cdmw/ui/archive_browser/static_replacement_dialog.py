"""Static mesh replacement builder dialog facade for archive browser entries."""

from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dialog_prompt import (
    prompt_archive_static_replacement_options,
)


class ArchiveStaticReplacementDialogMixin:
    """Static mesh replacement builder dialog and preview wiring."""

    def _prompt_archive_static_replacement_options(
        self,
        entry: ArchiveEntry,
        obj_path: Path,
        supplemental_files: Sequence[Path] = (),
        import_diagnostics: Sequence[str] = (),
        scene_import_result: Optional[SceneImportResult] = None,
        source_skeleton: object | None = None,
        original_mesh: Optional[ParsedMesh] = None,
        preferred_rebuild_material_sidecar: Optional[bool] = None,
        preferred_complete_source_swap: bool = False,
        dialog_title: str = "",
        placement_context_note: str = "",
        source_texture_evidence: Sequence[Mapping[str, object]] = (),
        extra_supplemental_specs: Sequence[MeshImportSupplementalFileSpec] = (),
        defer_original_texture_preview: bool = False,
        runtime_export_target_entry: Optional[ArchiveEntry] = None,
        full_import_model_replacement: bool = False,
        embedded_host: Optional[QWidget] = None,
        continue_build_callback: Optional[
            Callable[
                [
                    StaticMeshReplacementOptions,
                    Optional[QWidget],
                    Callable[[str], None],
                    Callable[[str, bool], None],
                    str,
                ],
                bool,
            ]
        ] = None,
        on_accept: Optional[Callable[[StaticMeshReplacementOptions], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        return prompt_archive_static_replacement_options(
            self,
            entry,
            obj_path,
            supplemental_files=supplemental_files,
            import_diagnostics=import_diagnostics,
            scene_import_result=scene_import_result,
            source_skeleton=source_skeleton,
            original_mesh=original_mesh,
            preferred_rebuild_material_sidecar=preferred_rebuild_material_sidecar,
            preferred_complete_source_swap=preferred_complete_source_swap,
            dialog_title=dialog_title,
            placement_context_note=placement_context_note,
            source_texture_evidence=source_texture_evidence,
            extra_supplemental_specs=extra_supplemental_specs,
            defer_original_texture_preview=defer_original_texture_preview,
            runtime_export_target_entry=runtime_export_target_entry,
            full_import_model_replacement=full_import_model_replacement,
            embedded_host=embedded_host,
            continue_build_callback=continue_build_callback,
            on_accept=on_accept,
            on_cancel=on_cancel,
        )


__all__ = ["ArchiveStaticReplacementDialogMixin"]
