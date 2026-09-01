"""Mesh Editor Character Context presentation and resident-package routing."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QTimer

from cdmw.domain.character_context import appearance_model_body_family, appearance_model_slot
from cdmw.models import ArchiveEntry


class MeshEditorCharacterContextMixin:
    def _hide_mesh_character_context_until_rebuild(self) -> None:
        indices = tuple(
            int(index)
            for index in tuple(getattr(self, "character_context_loaded_source_indices", ()) or ())
            if int(index) >= 0
        )
        host = getattr(self, "standalone_native_host_frame", None)
        hide = getattr(host, "set_hidden_source_submeshes", None)
        if indices and callable(hide):
            hide(indices)
            self.character_context_visibility_restore_pending = True

    def _restore_mesh_character_context_visibility(self, *, accepted: bool) -> None:
        if accepted:
            self.character_context_loaded_source_indices = tuple(
                getattr(self, "character_context_next_source_indices", ()) or ()
            )
        if not bool(getattr(self, "character_context_visibility_restore_pending", False)):
            return
        host = getattr(self, "standalone_native_host_frame", None)
        hide = getattr(host, "set_hidden_source_submeshes", None)
        if callable(hide):
            hide(())
        self.character_context_visibility_restore_pending = False

    @staticmethod
    def _mesh_character_context_source_indices(package_path: str) -> tuple[int, ...]:
        if not str(package_path or "").strip():
            return ()
        try:
            manifest = json.loads(
                (Path(package_path) / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, TypeError, ValueError):
            return ()
        batches = manifest.get("batches") if isinstance(manifest, dict) else None
        indices: set[int] = set()
        if isinstance(batches, list):
            for batch in batches:
                identity = batch.get("editor_identity") if isinstance(batch, dict) else None
                if not isinstance(identity, dict) or not bool(identity.get("context_component", False)):
                    continue
                try:
                    indices.add(int(identity.get("source_submesh_index", -1)))
                except (TypeError, ValueError):
                    continue
        return tuple(sorted(index for index in indices if index >= 0))

    def _set_mesh_editor_character_context_source(self, entry: ArchiveEntry | None) -> None:
        panel = getattr(self, "character_context_panel", None)
        button = getattr(self, "character_context_toggle_button", None)
        if panel is None or button is None or not hasattr(panel, "set_source_entry"):
            return
        path = str(getattr(entry, "path", "") or "")
        slot = appearance_model_slot(path)
        eligible = bool(appearance_model_body_family(path) and slot == "head")
        panel.set_source_entry(entry if eligible else None)
        button.setVisible(eligible)
        button.setEnabled(eligible)
        if not eligible:
            button.setChecked(False)

    def _toggle_mesh_editor_character_context(self, checked: bool) -> None:
        panel = getattr(self, "character_context_panel", None)
        splitter = getattr(self, "character_context_splitter", None)
        if panel is None or splitter is None or not hasattr(panel, "activate"):
            return
        panel.setVisible(bool(checked))
        sizes = splitter.sizes()
        if checked:
            panel.activate()
            service = getattr(self, "character_context_service", None)
            entry = getattr(self, "current_archive_selection", None)
            cached_result = getattr(service, "cached_result", None)
            request_package = getattr(service, "request_native_package", None)
            if (
                isinstance(entry, ArchiveEntry)
                and callable(cached_result)
                and cached_result(entry) is not None
                and callable(request_package)
            ):
                request_package(entry)
            splitter.setSizes([max(640, sizes[0] if sizes else 920), 340])
        else:
            splitter.setSizes([max(640, sizes[0] if sizes else 920), 0])

    def _restore_cached_mesh_character_context(self, entry: ArchiveEntry) -> None:
        service = getattr(self, "character_context_service", None)
        if (
            service is not None
            and service.cached_result(entry) is not None
            and service.selected_native_components(entry)
        ):
            service.request_native_package(entry)

    def _reset_mesh_character_context_session(self) -> None:
        self.character_context_native_package_path = ""
        self.character_context_loaded_source_indices = ()
        self.character_context_next_source_indices = ()
        self.character_context_visibility_restore_pending = False
        self.character_context_resident_swap_pending = False

    def _handle_mesh_character_context_selection(
        self,
        source_key: str,
        _selection: object,
        _components: object,
    ) -> None:
        service = getattr(self, "character_context_service", None)
        entry = getattr(self, "current_archive_selection", None)
        if service is None or not isinstance(entry, ArchiveEntry):
            return
        if source_key != service.source_key(entry):
            return
        self._hide_mesh_character_context_until_rebuild()
        self.character_context_repackage_generation = int(
            getattr(self, "character_context_repackage_generation", 0)
        ) + 1
        service.request_native_package(entry)

    def _handle_mesh_character_context_package_started(self, source_key: str) -> None:
        service = getattr(self, "character_context_service", None)
        entry = getattr(self, "current_archive_selection", None)
        if service is None or not isinstance(entry, ArchiveEntry) or source_key != service.source_key(entry):
            return
        self.status_message_requested.emit("Building preview-only Character Context geometry...", False)

    def _handle_mesh_character_context_package_ready(
        self,
        source_key: str,
        package_path: str,
        elapsed_ms: float,
    ) -> None:
        service = getattr(self, "character_context_service", None)
        entry = getattr(self, "current_archive_selection", None)
        if service is None or not isinstance(entry, ArchiveEntry) or source_key != service.source_key(entry):
            return
        self.character_context_native_package_path = str(package_path or "").strip()
        self.character_context_next_source_indices = self._mesh_character_context_source_indices(
            self.character_context_native_package_path
        )
        generation = int(getattr(self, "character_context_repackage_generation", 0))
        self._start_mesh_character_context_repackage(generation)
        status = (
            f"Character Context package ready in {float(elapsed_ms):.0f} ms."
            if package_path
            else "Character Context cleared."
        )
        self.status_message_requested.emit(status, False)

    def _handle_mesh_character_context_package_failed(self, source_key: str, message: str) -> None:
        service = getattr(self, "character_context_service", None)
        entry = getattr(self, "current_archive_selection", None)
        if service is None or not isinstance(entry, ArchiveEntry) or source_key != service.source_key(entry):
            return
        self._restore_mesh_character_context_visibility(accepted=False)
        self.status_message_requested.emit(
            f"Character Context preview kept the previous scene: {message}",
            True,
        )

    def _handle_mesh_character_context_resident_package_applied(self) -> None:
        if not bool(getattr(self, "character_context_resident_swap_pending", False)):
            return
        self.character_context_resident_swap_pending = False
        self._restore_mesh_character_context_visibility(accepted=True)

    def _handle_mesh_character_context_repackage_failed(self) -> None:
        self.character_context_resident_swap_pending = False
        self._restore_mesh_character_context_visibility(accepted=False)

    def _start_mesh_character_context_repackage(self, generation: int, attempt: int = 0) -> None:
        if generation != int(getattr(self, "character_context_repackage_generation", 0)):
            return
        if bool(getattr(self, "_shutting_down", False)):
            return
        if self._standalone_dotnet_package_worker_active():
            if attempt < 500:
                QTimer.singleShot(
                    10,
                    lambda: self._start_mesh_character_context_repackage(generation, attempt + 1),
                )
            else:
                self._handle_mesh_character_context_repackage_failed()
                self.status_message_requested.emit(
                    "Character Context could not replace the busy resident preview; the previous scene was restored.",
                    True,
                )
            return
        controller = getattr(self, "standalone_controller", None)
        if controller is None:
            self._handle_mesh_character_context_repackage_failed()
            return
        executable = self._dotnet_editor_executable_path()
        if executable is None or not Path(executable).is_file():
            self._handle_mesh_character_context_repackage_failed()
            self.status_message_requested.emit(
                "Character Context is selected, but the resident Rust Preview helper is unavailable.",
                True,
            )
            return
        self.character_context_resident_swap_pending = True
        self._start_standalone_dotnet_package_worker(
            controller,
            embedded=False,
            executable=Path(executable),
        )


__all__ = ["MeshEditorCharacterContextMixin"]
