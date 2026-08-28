"""Independent Mesh Editor load, validation, and .NET package workers."""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    build_mesh_dotnet_experiment_package,
    import_mesh_dotnet_experiment_output,
    write_mesh_dotnet_experiment_evaluation,
)
from cdmw.services.mesh_service import MeshService
from cdmw.services.modify_original_workspace_service import (
    ModifyOriginalDraft,
    discover_modify_original_drafts,
)
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.archive_preview_service import build_archive_preview_result
from cdmw.services.mesh_dotnet_material_state import (
    copy_dotnet_preview_material_bindings,
    count_dotnet_own_material_bindings,
)
from cdmw.services.mesh_dotnet_material_bindings import (
    apply_dotnet_native_material_batch_bindings,
)
from cdmw.services.mesh_dotnet_reference_composite import (
    apply_dotnet_native_reference_materials,
    append_dotnet_native_reference_composite,
)
from cdmw.services.mesh_texture_sources import resolve_mesh_texture_source
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.static_mesh_scene_frame import selection_pivot_source_from_mesh
from cdmw.modding.static_mesh_scene_frame import build_authoritative_static_scene_frame
from cdmw.modding.static_mesh_types import StaticReplacementTransform


@dataclass(frozen=True, slots=True)
class MeshArchiveSessionLoadResult:
    service: MeshService
    view: object
    mesh: ParsedMesh
    source_sha256: str
    matching_drafts: tuple[ModifyOriginalDraft, ...] = ()
    resumed_manifest_path: Path | None = None


class MeshArchiveSessionLoadWorker(QObject):
    """Open one exact archive mesh as a resident authoring session off-thread."""

    loaded = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        entry: ArchiveEntry,
        *,
        session_id: str = "",
        mode: str = "edit",
        draft_root: Path | str | None = None,
        resume_manifest_path: Path | str | None = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.entry = entry
        self.session_id = str(session_id or "")
        self.mode = str(mode or "edit")
        self.draft_root = Path(draft_root).expanduser() if draft_root is not None else None
        self.resume_manifest_path = (
            Path(resume_manifest_path).expanduser().resolve()
            if resume_manifest_path is not None
            else None
        )
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            payload, _decompressed, _note = read_archive_entry_data(
                self.entry,
                stop_event=self.stop_event,
            )
            if self.stop_event.is_set():
                return
            service = MeshService()
            mesh = service.load_mesh_bytes(payload, self.entry.path, run_roundtrip=True)
            source_sha256 = str(getattr(mesh, "_cdmw_mesh_asset_source_hash", "") or "")
            drafts = (
                discover_modify_original_drafts(self.draft_root, source_sha256)
                if self.draft_root is not None
                else ()
            )
            resumed_manifest_path: Path | None = None
            if self.resume_manifest_path is not None:
                draft = next(
                    (item for item in drafts if item.manifest_path == self.resume_manifest_path),
                    None,
                )
                if draft is None:
                    raise ValueError("Requested Mesh Editor draft is unavailable or belongs to another source")
                setattr(mesh, "_cdmw_modify_original_workspace_manifest_path", str(draft.manifest_path))
                setattr(mesh, "_cdmw_mesh_layer_project_path", str(draft.mesh_layer_project_path))
                setattr(mesh, "_cdmw_modify_original_workspace_mode", draft.workspace_mode)
                resumed_manifest_path = draft.manifest_path
            if self.stop_event.is_set():
                return
            view = service.open_edit_session(
                mesh,
                session_id=self.session_id or f"mesh-editor-archive:{self.entry.path}",
                mode=self.mode,
            )
            if not self.stop_event.is_set():
                self.loaded.emit(
                    self.request_id,
                    MeshArchiveSessionLoadResult(
                        service=service,
                        view=view,
                        mesh=mesh,
                        source_sha256=source_sha256,
                        matching_drafts=drafts,
                        resumed_manifest_path=resumed_manifest_path,
                    ),
                )
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshArchiveMaterialContextWorker(QObject):
    """Resolve the source archive's read-only material model off-thread."""

    resolved = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        entry: ArchiveEntry,
        *,
        companion_entry: ArchiveEntry | None = None,
        material_package_path: Path | str | None = None,
        entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]] | None = None,
        entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None = None,
        sidecar_entries_by_texture_path: Mapping[str, Sequence[ArchiveEntry]] | None = None,
        sidecar_entries_by_texture_basename: Mapping[str, Sequence[ArchiveEntry]] | None = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.entry = entry
        self.companion_entry = companion_entry
        self.material_package_path = (
            Path(material_package_path) if material_package_path else None
        )
        self.entries_by_normalized_path = entries_by_normalized_path or {}
        self.entries_by_basename = entries_by_basename or {}
        self.sidecar_entries_by_texture_path = sidecar_entries_by_texture_path or {}
        self.sidecar_entries_by_texture_basename = sidecar_entries_by_texture_basename or {}
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def _native_package_material_model(self) -> object | None:
        package_path = self.material_package_path
        if package_path is None:
            return None
        manifest_path = package_path / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        batches = manifest.get("batches") if isinstance(manifest, Mapping) else None
        if not isinstance(batches, Sequence) or isinstance(
            batches,
            (str, bytes, bytearray),
        ) or not batches:
            return None
        material_sources = [
            SimpleNamespace(source_submesh_index=index)
            for index in range(len(batches))
        ]
        preview_model = SimpleNamespace(
            path=str(self.entry.path or ""),
            meshes=material_sources,
            submeshes=material_sources,
        )
        if apply_dotnet_native_material_batch_bindings(preview_model, batches) <= 0:
            return None
        return (
            preview_model
            if count_dotnet_own_material_bindings(preview_model) > 0
            else None
        )

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            preview_model = self._native_package_material_model()
            if self.stop_event.is_set():
                return
            if preview_model is not None:
                self.resolved.emit(self.request_id, preview_model)
                return
            result = build_archive_preview_result(
                self.entry,
                (),
                companion_entry=self.companion_entry,
                texture_entries_by_normalized_path=self.entries_by_normalized_path,
                texture_entries_by_basename=self.entries_by_basename,
                sidecar_entries_by_texture_path=self.sidecar_entries_by_texture_path,
                sidecar_entries_by_texture_basename=self.sidecar_entries_by_texture_basename,
                include_loose_preview_assets=False,
                visible_texture_mode="mesh_base_first",
                support_texture_slots=("normal", "material", "height", "emissive"),
                quality_tier="full",
                enable_hkx_visual_preview=False,
                stop_event=self.stop_event,
            )
            if self.stop_event.is_set():
                return
            preview_model = getattr(result, "preview_model", None)
            if preview_model is None or count_dotnet_own_material_bindings(preview_model) <= 0:
                detail = str(
                    getattr(result, "warning_text", "")
                    or getattr(result, "detail_text", "")
                    or "The archive material resolver returned no resolved texture bindings."
                ).strip()
                self.error.emit(self.request_id, detail)
                return
            self.resolved.emit(self.request_id, preview_model)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshFileSessionLoadWorker(QObject):
    loaded = Signal(int, object, object, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        path: Path | str,
        *,
        session_id: str = "",
        mode: str = "object",
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.path = Path(path)
        self.session_id = str(session_id or "")
        self.mode = str(mode or "object")
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            service = MeshService()
            mesh = service.load_mesh_file(self.path, run_roundtrip=True)
            if self.stop_event.is_set():
                return
            view = service.open_edit_session(
                mesh,
                session_id=self.session_id or f"mesh-editor-file:{self.path.name}",
                mode=self.mode,
            )
            if not self.stop_event.is_set():
                self.loaded.emit(self.request_id, service, view, mesh)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshTextureSourceResolveWorker(QObject):
    resolved = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        texture: str,
        *,
        target_entry: object | None = None,
        entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]] | None = None,
        entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.texture = str(texture or "")
        self.target_entry = target_entry
        self.entries_by_normalized_path = entries_by_normalized_path or {}
        self.entries_by_basename = entries_by_basename or {}
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            result = resolve_mesh_texture_source(
                self.texture,
                target_entry=self.target_entry,
                entries_by_normalized_path=self.entries_by_normalized_path,
                entries_by_basename=self.entries_by_basename,
                stop_event=self.stop_event,
            )
            if self.stop_event.is_set():
                return
            if result.ok:
                self.resolved.emit(self.request_id, result)
            else:
                self.error.emit(self.request_id, result.message or "Mesh Editor texture source could not be resolved.")
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshExportValidationWorker(QObject):
    completed = Signal(int, object, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request_id: int, service: MeshService, session_id: str) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            started = time.perf_counter()
            report = self.service.validate_export(self.session_id)
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, report, elapsed_ms)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshDotNetExperimentPackageWorker(QObject):
    completed = Signal(int, object, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        service: MeshService,
        session_id: str,
        *,
        output_root: Path | str | None = None,
        reference_mesh: ParsedMesh | None = None,
        reference_material_source: object | None = None,
        editable_material_source: object | None = None,
        reference_native_package: Path | str | None = None,
        mirror_reference_materials_to_editable: bool = False,
        comparison_mode: str = "side_by_side",
        interaction_mode: str = "placement",
        scene_transform: StaticReplacementTransform | None = None,
        scene_generation: int = 1,
        include_material_resources: bool = True,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.output_root = Path(output_root) if output_root is not None else None
        self.reference_mesh = reference_mesh
        self.reference_material_source = reference_material_source
        self.editable_material_source = editable_material_source
        self.reference_native_package = Path(reference_native_package) if reference_native_package else None
        self.mirror_reference_materials_to_editable = bool(
            mirror_reference_materials_to_editable
        )
        self.comparison_mode = str(comparison_mode or "side_by_side")
        self.interaction_mode = str(interaction_mode or "placement")
        self.scene_transform = scene_transform
        self.scene_generation = max(1, int(scene_generation))
        self.include_material_resources = bool(include_material_resources)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            started = time.perf_counter()
            mesh = self.service.working_mesh(self.session_id, clone=True)
            if self.editable_material_source is not None:
                copy_dotnet_preview_material_bindings(mesh, self.editable_material_source)
            view = self.service.session_view(self.session_id)
            selection_pivot = selection_pivot_source_from_mesh(mesh, view.selection)
            reference_mesh = clone_mesh_for_editing(self.reference_mesh) if self.reference_mesh is not None else None
            if reference_mesh is not None and self.reference_material_source is not None:
                copy_dotnet_preview_material_bindings(
                    reference_mesh,
                    self.reference_material_source,
                )
            if reference_mesh is not None and self.reference_native_package is not None:
                apply_dotnet_native_reference_materials(
                    reference_mesh,
                    self.reference_native_package,
                    cancelled=self.stop_event.is_set,
                )
                append_dotnet_native_reference_composite(
                    reference_mesh,
                    self.reference_native_package,
                    cancelled=self.stop_event.is_set,
                )
            if reference_mesh is not None and self.mirror_reference_materials_to_editable:
                copy_dotnet_preview_material_bindings(mesh, reference_mesh)
            if self.stop_event.is_set():
                return
            package = build_mesh_dotnet_experiment_package(
                mesh,
                output_root=self.output_root,
                reference_mesh=reference_mesh,
                comparison_mode=self.comparison_mode,
                interaction_mode=self.interaction_mode,
                scene_transform=self.scene_transform,
                scene_generation=self.scene_generation,
                scene_session_id=self.session_id,
                selection_pivot_source=selection_pivot,
                include_material_resources=self.include_material_resources,
                cancelled=self.stop_event.is_set,
            )
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            if self.stop_event.is_set():
                shutil.rmtree(package.package_dir, ignore_errors=True)
                return
            self.completed.emit(self.request_id, package, elapsed_ms)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshDotNetSceneFrameWorker(QObject):
    """Calculate one correlated resident frame without touching the Qt thread."""

    completed = Signal(int, object, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        service: MeshService,
        session_id: str,
        reference_mesh: ParsedMesh,
        transform: StaticReplacementTransform,
        *,
        source_identity: str,
        scene_generation: int,
        comparison_mode: str,
        interaction_mode: str,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.reference_mesh = reference_mesh
        self.transform = transform
        self.source_identity = str(source_identity or "")
        self.scene_generation = max(1, int(scene_generation))
        self.comparison_mode = str(comparison_mode or "replacement_only")
        self.interaction_mode = str(interaction_mode or "placement")
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            started = time.perf_counter()
            mesh = self.service.working_mesh(self.session_id, clone=True)
            view = self.service.session_view(self.session_id)
            reference = clone_mesh_for_editing(self.reference_mesh)
            if self.stop_event.is_set():
                return
            frame = build_authoritative_static_scene_frame(
                reference,
                mesh,
                self.transform,
                source_identity=self.source_identity,
                scene_generation=self.scene_generation,
                comparison_mode=self.comparison_mode,
                interaction_mode=self.interaction_mode,
                selection_pivot_source=selection_pivot_source_from_mesh(mesh, view.selection),
                cancelled=self.stop_event.is_set,
            )
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, frame, elapsed_ms)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshDotNetExperimentOutputImportWorker(QObject):
    completed = Signal(int, object, object, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        service: MeshService,
        session_id: str,
        package: MeshDotNetExperimentPackage,
        status_payload: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.package = package
        self.status_payload = dict(status_payload or {})
        self.stop_event = threading.Event()
        self._commit_gate = threading.Lock()
        self._commit_started = False

    def stop(self) -> bool:
        """Cancel preparation, or report that the noninterruptible commit began."""

        with self._commit_gate:
            if self._commit_started:
                return False
            self.stop_event.set()
            return True

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            started = time.perf_counter()
            mesh = import_mesh_dotnet_experiment_output(self.package, self.status_payload)
            if mesh is None:
                raise RuntimeError("Mesh .NET editor did not produce an edited OBJ package.")
            if self.stop_event.is_set():
                return
            prepared = self.service.prepare_working_mesh_replacement(self.session_id, mesh)
            validation = prepared.validation_report
            if validation.blockers:
                raise ValueError(
                    "Mesh .NET output failed pre-commit export validation: "
                    + str(validation.blockers[0].message)
                )
            with self._commit_gate:
                if self.stop_event.is_set():
                    return
                self._commit_started = True
            view = self.service.commit_prepared_working_mesh_replacement(prepared)
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            # Once commit starts its terminal result is always published. A late
            # cancellation cannot turn a successful mutation into a silent one.
            self.completed.emit(self.request_id, view, validation, elapsed_ms)
        except Exception as exc:
            if self._commit_started or not self.stop_event.is_set():
                message = f"{type(exc).__name__}: {exc}"
                try:
                    evaluation_path = write_mesh_dotnet_experiment_evaluation(
                        self.package,
                        self.status_payload,
                        validation_report=SimpleNamespace(ok=False, blockers=(message,), warnings=()),
                    )
                    message = f"{message} Evaluation: {evaluation_path}"
                except Exception:
                    pass
                self.error.emit(self.request_id, message)
        finally:
            self.finished.emit()


__all__ = [
    "MeshArchiveMaterialContextWorker",
    "MeshDotNetExperimentOutputImportWorker",
    "MeshDotNetExperimentPackageWorker",
    "MeshExportValidationWorker",
    "MeshFileSessionLoadWorker",
    "MeshTextureSourceResolveWorker",
]
