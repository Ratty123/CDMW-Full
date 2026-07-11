"""Model Library bridge actions for shell MainWindow."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

from PySide6.QtWidgets import QMessageBox

from cdmw.services.preview_workflow_service import (
    attach_scene_preview_textures,
    parsed_mesh_to_preview_model,
)
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.library.models import IMPORTABLE_MODEL_EXTENSIONS, is_importable_model_path
from cdmw.services.mesh_workflow_service import SCENE_TEXTURE_SOURCE_EXTENSIONS, SceneImportResult, import_scene_mesh_with_report
from cdmw.models import ArchivePreviewResult, RunCancelled
from cdmw.services.preview_rendering_service import prepare_model_preview
from cdmw.services.diagnostics_service import is_expected_cancellation_message
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11


class ModelLibraryShellBridgeMixin:
    """Route Model Library signals into archive preview/import workflows."""

    @staticmethod
    def _model_library_supplemental_suffixes() -> set[str]:
        return set(SCENE_TEXTURE_SOURCE_EXTENSIONS) | {
            ".xml",
            ".pami",
            ".pac_xml",
            ".pam_xml",
            ".pamlod_xml",
            ".app_xml",
            ".prefabdata_xml",
        }

    @staticmethod
    def _dedupe_model_library_paths(paths: Sequence[Path]) -> Tuple[Path, ...]:
        seen: set[str] = set()
        result: List[Path] = []
        for path in paths:
            try:
                resolved = path.expanduser().resolve()
            except Exception:
                continue
            key = str(resolved).lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(resolved)
        return tuple(result)

    def _model_library_texture_search_roots(
        self,
        scene_path: Path,
        metadata: Mapping[str, object],
    ) -> Tuple[Path, ...]:
        candidates: List[Path] = [
            scene_path.parent,
            scene_path.parent / "textures",
            scene_path.parent / "texture",
            scene_path.parent.parent / "textures",
            scene_path.parent.parent / "texture",
        ]
        for key in ("asset_dir", "archive_path", "path", "import_path"):
            text = str(metadata.get(key, "") or "").strip()
            if not text:
                continue
            candidate = Path(text).expanduser()
            if candidate.is_file():
                candidates.append(candidate.parent)
            elif candidate.is_dir():
                candidates.append(candidate)
        return self._dedupe_model_library_paths(candidates)

    def _discover_model_library_supplemental_files(
        self,
        scene_path: Path,
        metadata: Mapping[str, object],
        *,
        limit: int = 512,
        scan_limit: int = 10000,
        stop_event: object = None,
    ) -> Tuple[Path, ...]:
        supported_suffixes = self._model_library_supplemental_suffixes()
        recursive_root_keys: set[str] = set()
        asset_dir_text = str(metadata.get("asset_dir", "") or "").strip()
        if asset_dir_text:
            asset_dir = Path(asset_dir_text).expanduser()
            if asset_dir.is_dir():
                try:
                    recursive_root_keys.add(str(asset_dir.resolve()).lower())
                except OSError:
                    recursive_root_keys.add(str(asset_dir.absolute()).lower())
        discovered: List[Path] = []
        seen: set[str] = set()
        scanned = 0
        for root in self._model_library_texture_search_roots(scene_path, metadata):
            raise_if_cancelled(stop_event, "Model Library companion scan cancelled.")
            if not root.is_dir():
                continue
            try:
                root_key = str(root.resolve()).lower()
            except OSError:
                root_key = str(root.absolute()).lower()
            recursive = root_key in recursive_root_keys or root.name.lower() in {"texture", "textures"}
            try:
                iterator = root.rglob("*") if recursive else root.iterdir()
                for candidate in iterator:
                    raise_if_cancelled(stop_event, "Model Library companion scan cancelled.")
                    scanned += 1
                    if scanned > scan_limit or len(discovered) >= limit:
                        break
                    if not candidate.is_file() or candidate.suffix.lower() not in supported_suffixes:
                        continue
                    try:
                        resolved = candidate.expanduser().resolve()
                    except Exception:
                        continue
                    key = str(resolved).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    discovered.append(resolved)
            except OSError:
                continue
            if scanned > scan_limit or len(discovered) >= limit:
                break
        return tuple(discovered)

    def _augment_model_library_scene_import_result(
        self,
        scene_path: Path,
        scene_import_result: SceneImportResult,
        metadata: Mapping[str, object],
        *,
        stop_event: object = None,
    ) -> SceneImportResult:
        if not isinstance(scene_import_result, SceneImportResult):
            return scene_import_result
        companion_files = self._discover_model_library_supplemental_files(
            scene_path,
            metadata,
            stop_event=stop_event,
        )
        existing_keys = {
            str(path.expanduser().resolve()).lower()
            for path in tuple(scene_import_result.discovered_texture_files or ())
            + tuple(scene_import_result.extracted_embedded_files or ())
            + tuple(getattr(scene_import_result, "discovered_supplemental_files", ()) or ())
            if isinstance(path, Path) and path.is_file()
        }
        extra_textures: List[Path] = []
        extra_sidecars: List[Path] = []
        for candidate in companion_files:
            raise_if_cancelled(stop_event, "Model Library companion scan cancelled.")
            try:
                resolved = candidate.expanduser().resolve()
            except Exception:
                continue
            key = str(resolved).lower()
            if key in existing_keys or not resolved.is_file():
                continue
            existing_keys.add(key)
            if resolved.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                extra_textures.append(resolved)
            else:
                extra_sidecars.append(resolved)
        if extra_textures:
            scene_import_result.discovered_texture_files = tuple(scene_import_result.discovered_texture_files or ()) + tuple(extra_textures)
        if extra_sidecars:
            scene_import_result.discovered_supplemental_files = tuple(
                getattr(scene_import_result, "discovered_supplemental_files", ()) or ()
            ) + tuple(extra_sidecars)
        all_texture_count = sum(
            1
            for path in tuple(scene_import_result.discovered_texture_files or ())
            + tuple(scene_import_result.extracted_embedded_files or ())
            if isinstance(path, Path) and path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
        )
        diagnostics = list(scene_import_result.diagnostics or ())
        if extra_textures or extra_sidecars:
            diagnostics.append(
                f"Model Library companion scan added {len(extra_textures):,} local texture file(s) and {len(extra_sidecars):,} sidecar file(s)."
            )
        elif all_texture_count <= 0:
            diagnostics.append(
                "Warning: No local texture files were found for this Model Library item. The import will load geometry only unless you add files."
            )
        scene_import_result.diagnostics = tuple(diagnostics)
        return scene_import_result

    def _import_local_model_to_current_archive(self, import_path_text: str, model_payload: object) -> None:
        scene_path = Path(str(import_path_text or "")).expanduser()
        if not is_importable_model_path(scene_path):
            supported = ", ".join(sorted(IMPORTABLE_MODEL_EXTENSIONS))
            self.set_status_message(f"Model library file is not supported by mesh import: {scene_path.suffix}. Supported: {supported}", error=True)
            return
        current_entry = self._current_archive_mesh_entry()
        if current_entry is None:
            self._activate_tool_widget(self.archive_browser_tab)
            message = (
                "Import Mesh replaces an existing game mesh. Select a supported .pac, .pam, or .pamlod mesh "
                "in Archive Browser first, then run Import Mesh from Model Library again."
            )
            self.set_status_message(message, error=True)
            QMessageBox.information(self, "Import Mesh", message)
            return
        if self._background_task_active():
            self.set_status_message(
                "Another background task is still running. Wait for it to finish before importing this model.",
                error=True,
            )
            return
        metadata = dict(model_payload) if isinstance(model_payload, Mapping) else {}
        model_name = str(metadata.get("name", "") or scene_path.stem).strip()
        creator = str(
            metadata.get("creator_name", "")
            or metadata.get("creatorName", "")
            or metadata.get("creator_username", "")
            or metadata.get("creatorUsername", "")
        ).strip()
        license_label = str(metadata.get("license_label", "") or metadata.get("licenseLabel", "") or "").strip()
        viewer_url = str(metadata.get("viewer_url", "") or metadata.get("viewerUrl", "") or "").strip()
        source_name = str(metadata.get("source", "") or "Model Library").strip()
        source_parts = [f"{source_name}: {model_name}"]
        if creator:
            source_parts.append(f"by {creator}")
        if license_label:
            source_parts.append(f"license: {license_label}")
        if viewer_url:
            source_parts.append(viewer_url)
        source_path = str(metadata.get("path", "") or metadata.get("import_path", "") or scene_path)
        if source_path:
            source_parts.append(source_path)
        source_label = " | ".join(source_parts)
        request_id = int(getattr(self, "_model_library_import_request_id", 0) or 0) + 1
        self._model_library_import_request_id = request_id
        entry_key = self._archive_entry_identity_key(current_entry)

        def task(_log: Callable[[str], None], stop_event: object) -> object:
            try:
                raise_if_cancelled(stop_event, "Model Library scene import cancelled.")
                if not scene_path.is_file():
                    raise FileNotFoundError(f"Model library import file is missing: {scene_path}")
                scene_import_result = import_scene_mesh_with_report(scene_path, stop_event=stop_event)
                return self._augment_model_library_scene_import_result(
                    scene_path,
                    scene_import_result,
                    metadata,
                    stop_event=stop_event,
                )
            except RunCancelled:
                raise
            except Exception as exc:
                return exc

        def on_error(message: str) -> None:
            if (
                request_id != int(getattr(self, "_model_library_import_request_id", 0) or 0)
                or bool(getattr(self, "_shutting_down", False))
                or is_expected_cancellation_message(message)
            ):
                return
            QMessageBox.warning(
                self,
                "Mesh Import Unsupported",
                f"{scene_path.name} could not be imported.\n\n{message}",
            )
            self.set_status_message(f"Model library import failed: {message}", error=True)

        def on_complete(value: object) -> None:
            if request_id != int(getattr(self, "_model_library_import_request_id", 0) or 0):
                return
            if isinstance(value, Exception):
                on_error(str(value))
                return
            if bool(getattr(self, "_shutting_down", False)) or not isinstance(value, SceneImportResult):
                return
            if self._archive_entry_identity_key(self._current_archive_mesh_entry()) != entry_key:
                self.set_status_message("Model library import result ignored because the selected archive mesh changed.", error=True)
                return
            self._open_mesh_editor_for_entry(
                current_entry,
                mode="external_import",
                source_path=scene_path,
                scene_import_result=value,
                activate=True,
            )
            setup = self._prompt_archive_mesh_import_setup(
                current_entry,
                scene_path,
                title="Model Library Mesh Import Setup",
                scene_import_result=value,
                source_label=source_label,
            )
            if setup is None:
                return
            setup.source_label = source_label
            self.set_status_message(f"Opening mesh replacement workflow for model library item: {model_name}.")
            self._start_archive_mesh_patch(current_entry, preset_setup=setup)

        self._run_utility_task(
            status_message=f"Importing model library scene: {model_name}...",
            task=task,
            on_complete=on_complete,
            on_error=on_error,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _preview_model_library_mesh(self, import_path_text: str, model_payload: object) -> None:
        scene_path = Path(str(import_path_text or "")).expanduser()
        if not is_importable_model_path(scene_path):
            supported = ", ".join(sorted(IMPORTABLE_MODEL_EXTENSIONS))
            self.set_status_message(f"Model library file is not supported by preview: {scene_path.suffix}. Supported: {supported}", error=True)
            return
        if self._background_task_active():
            self.set_status_message(
                "Another background task is still running. Wait for it to finish before previewing this model.",
                error=True,
            )
            return
        metadata = dict(model_payload) if isinstance(model_payload, Mapping) else {}
        model_name = str(metadata.get("name", "") or scene_path.stem).strip()
        source_name = str(metadata.get("source", "") or metadata.get("kind", "") or "Model Library").strip()
        license_label = str(metadata.get("license_label", "") or metadata.get("licenseLabel", "") or "").strip()
        viewer_url = str(metadata.get("viewer_url", "") or metadata.get("viewerUrl", "") or "").strip()
        render_settings = self._current_model_preview_render_settings()
        request_id = self.archive_preview_request_id + 1
        self.archive_preview_request_id = request_id
        self.archive_preview_requested_loose = False
        self.archive_preview_title_label.setText(model_name)
        self.archive_preview_meta_label.setText("Preparing model library preview...")
        self.archive_preview_role_badge.setText("Model Library")
        self.archive_preview_role_badge.setVisible(True)
        self._set_archive_preview_health_message(
            "Resolving local model geometry and texture paths...",
            visible=True,
        )
        self._populate_archive_texture_reference_list(())
        self.archive_preview_warning_badge.clear()
        self.archive_preview_warning_badge.setVisible(False)
        self.archive_preview_warning_label.clear()
        self.archive_preview_warning_label.setVisible(False)
        self._set_archive_preview_base_detail_text(
            f"Preparing model library preview for {scene_path}...",
            include_current_model_debug=False,
        )
        self.archive_preview_info_edit.setPlainText(f"Preparing model library preview for {scene_path}...")
        self.archive_preview_stack.setCurrentWidget(self.archive_preview_info_edit)
        self.archive_preview_tabs.setCurrentIndex(0)
        if self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11:
            self._clear_archive_isolated_renderer_surface_for_request()

        def task(_log: Callable[[str], None], stop_event: object) -> object:
            raise_if_cancelled(stop_event, "Model Library preview cancelled.")
            if not scene_path.is_file():
                raise FileNotFoundError(f"Model library preview file is missing: {scene_path}")
            scene_result = import_scene_mesh_with_report(scene_path, stop_event=stop_event)
            scene_result = self._augment_model_library_scene_import_result(
                scene_path,
                scene_result,
                metadata,
                stop_event=stop_event,
            )
            raise_if_cancelled(stop_event, "Model Library preview cancelled.")
            preview_model = parsed_mesh_to_preview_model(scene_result.mesh)
            texture_count = self._attach_model_library_preview_textures(
                preview_model,
                scene_result,
                scene_path,
            )
            raise_if_cancelled(stop_event, "Model Library preview cancelled.")
            mesh_count = len(getattr(preview_model, "meshes", ()) or ())
            prepared_model, prepared_preview_model = prepare_model_preview(
                preview_model,
                render_settings=render_settings,
            )
            raise_if_cancelled(stop_event, "Model Library preview cancelled.")
            detail_lines = [
                f"Source: {source_name}",
                f"Path: {scene_path}",
                f"Format: {scene_path.suffix.lower() or scene_result.mesh.format}",
                f"Meshes: {mesh_count:,}",
                f"Vertices: {scene_result.mesh.total_vertices:,}",
                f"Faces: {scene_result.mesh.total_faces:,}",
                f"Resolved preview texture slots: {texture_count:,}",
            ]
            if license_label:
                detail_lines.append(f"License: {license_label}")
            if viewer_url:
                detail_lines.append(f"Page: {viewer_url}")
            discovered_textures = tuple(scene_result.discovered_texture_files or ()) + tuple(scene_result.extracted_embedded_files or ())
            if discovered_textures:
                detail_lines.append("")
                detail_lines.append(f"Discovered texture file(s): {len(discovered_textures):,}")
                detail_lines.extend(f"- {path}" for path in discovered_textures[:20])
                if len(discovered_textures) > 20:
                    detail_lines.append(f"- ... {len(discovered_textures) - 20:,} more")
            if scene_result.diagnostics:
                detail_lines.append("")
                detail_lines.append("Importer diagnostics:")
                detail_lines.extend(f"- {line}" for line in scene_result.diagnostics[:20])
            return ArchivePreviewResult(
                status="ok",
                title=model_name,
                metadata_summary=(
                    f"Model Library | {scene_path.suffix.lower().lstrip('.') or scene_result.mesh.format}"
                    f" | {scene_result.mesh.total_vertices:,} vertices | {scene_result.mesh.total_faces:,} faces"
                ),
                detail_text="\n".join(detail_lines),
                preview_model=prepared_model,
                prepared_preview_model=prepared_preview_model,
                preferred_view="model",
                warning_badge="External Model",
                warning_text=(
                    "This is a model-library preview. It has not been imported or written into any game archive."
                ),
            )

        def on_complete(result: object) -> None:
            if request_id != self.archive_preview_request_id or bool(getattr(self, "_shutting_down", False)):
                return
            if not isinstance(result, ArchivePreviewResult):
                self.set_status_message("Model library preview finished with an unexpected response.", error=True)
                return
            self.archive_preview_requested_loose = False
            self._activate_tool_widget(self.archive_browser_tab)
            self._apply_archive_preview_result(result, request_id=request_id, source="model_library_preview")
            self.archive_preview_role_badge.setText("Model Library")
            self.archive_preview_role_badge.setVisible(True)
            self._set_archive_preview_health_message(
                "External model preview using resolved local texture paths.",
                visible=True,
            )
            self.set_status_message(f"Previewing model library item: {model_name}.")

        self._run_utility_task(
            status_message=f"Preparing model library preview for {model_name}...",
            task=task,
            on_complete=on_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _attach_model_library_preview_textures(
        self,
        preview_model: object,
        scene_result: SceneImportResult,
        scene_path: Path,
    ) -> int:
        return attach_scene_preview_textures(preview_model, scene_result, scene_path)


__all__ = ["ModelLibraryShellBridgeMixin"]
