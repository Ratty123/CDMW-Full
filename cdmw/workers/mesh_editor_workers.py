"""Background workers for Mesh Editor long-running work."""

from __future__ import annotations

import threading
import time
import shutil
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.domain.mesh import MeshEditCommand
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.models import ModelPreviewData, ModelPreviewRenderSettings, PreparedModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.mesh_exporter import export_obj
from cdmw.modding.mesh_glb_interchange import export_glb, import_glb_with_sidecar
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.rendering.native_preview_package_writer import write_isolated_d3d11_preview_package
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    build_mesh_dotnet_experiment_package,
    import_mesh_dotnet_experiment_output,
    write_mesh_dotnet_experiment_evaluation,
)
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_texture_sources import resolve_mesh_texture_source

_LEGACY_DISPLAY_CLEANUP_ACTIONS = frozenset({"triangulate_display", "quadrangulate_display"})


def _editable_package_mesh_path(path: Path) -> Path:
    if path.is_dir():
        for name in ("mesh.glb", "edited_mesh.glb", "edited.glb", "mesh.obj", "edited_mesh.obj", "edited.obj"):
            candidate = path / name
            if candidate.is_file():
                return candidate
    return path


def _ensure_editable_package_sidecar_alias(mesh_path: Path) -> None:
    sidecar_path = Path(f"{mesh_path}.meta.json")
    if sidecar_path.is_file():
        return
    cdmeta_path = mesh_path.parent / "mesh.cdmeta.json"
    if cdmeta_path.is_file():
        shutil.copyfile(cdmeta_path, sidecar_path)


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


class MeshEditablePackageExportWorker(QObject):
    completed = Signal(int, object, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        service: MeshService,
        session_id: str,
        output_dir: Path | str,
        *,
        name: str = "mesh",
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.output_dir = Path(output_dir)
        self.name = str(name or "mesh")
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
            self.output_dir.mkdir(parents=True, exist_ok=True)
            glb_paths = tuple(Path(path) for path in export_glb(mesh, str(self.output_dir), self.name))
            exported_paths = glb_paths + tuple(Path(path) for path in export_obj(mesh, str(self.output_dir), self.name))
            glb_path = self.output_dir / f"{self.name}.glb"
            obj_path = self.output_dir / f"{self.name}.obj"
            sidecar_path = Path(f"{glb_path}.meta.json")
            cdmeta_path = self.output_dir / "mesh.cdmeta.json"
            original_hash_path = self.output_dir / "original_asset_hash.txt"
            if sidecar_path.is_file():
                shutil.copyfile(sidecar_path, cdmeta_path)
                payload = json.loads(cdmeta_path.read_text(encoding="utf-8"))
                original_hash_path.write_text(str(payload.get("source_asset_hash", "") or ""), encoding="utf-8")
            result = {
                "package_dir": self.output_dir,
                "mesh_path": glb_path,
                "obj_path": obj_path,
                "metadata_path": cdmeta_path,
                "original_asset_hash_path": original_hash_path,
                "files": exported_paths,
            }
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, result, elapsed_ms)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshEditablePackageImportWorker(QObject):
    completed = Signal(int, object, object, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        service: MeshService,
        session_id: str,
        package_path: Path | str,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.package_path = Path(package_path)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            started = time.perf_counter()
            mesh_path = _editable_package_mesh_path(self.package_path)
            _ensure_editable_package_sidecar_alias(mesh_path)
            mesh = import_glb_with_sidecar(mesh_path) if mesh_path.suffix.lower() == ".glb" else import_obj(str(mesh_path))
            if self.stop_event.is_set():
                return
            view = self.service.replace_working_mesh(self.session_id, mesh)
            validation = self.service.validate_export(self.session_id)
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, view, validation, elapsed_ms)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshNativePreviewPackageWorker(QObject):
    completed = Signal(int, object, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        mesh: ParsedMesh,
        render_settings: ModelPreviewRenderSettings,
        *,
        prepare_native_preview: Callable[[ParsedMesh], PreparedModelPreviewData],
        output_root: Path | str | None = None,
        model_preview_data: ModelPreviewData | None = None,
        use_textures: bool = False,
        high_quality_textures: bool = False,
        backend: str = "d3d11",
        display_mode: str = "replacement_only",
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.mesh = mesh
        self.prepare_native_preview = prepare_native_preview
        self.render_settings = render_settings
        self.output_root = Path(output_root) if output_root is not None else None
        self.model_preview_data = model_preview_data
        self.use_textures = bool(use_textures)
        self.high_quality_textures = bool(high_quality_textures)
        self.backend = str(backend or "d3d11")
        self.display_mode = str(display_mode or "replacement_only")
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        package_dir: Path | None = None
        try:
            if self.stop_event.is_set():
                return
            started = time.perf_counter()
            prepared_preview = self.prepare_native_preview(self.mesh)
            if not isinstance(prepared_preview, PreparedModelPreviewData):
                raise TypeError("prepare_native_preview did not return PreparedModelPreviewData")
            if self.stop_event.is_set():
                return
            package_dir = write_isolated_d3d11_preview_package(
                self.model_preview_data or ModelPreviewData(path=str(self.mesh.path or "mesh_editor.pac")),
                prepared_preview,
                output_root=self.output_root,
                render_settings=self.render_settings,
                use_textures=self.use_textures,
                high_quality_textures=self.high_quality_textures,
                backend=self.backend,
                display_mode=self.display_mode,
                stop_event=self.stop_event,
            )
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, package_dir, elapsed_ms)
            elif package_dir is not None:
                shutil.rmtree(package_dir, ignore_errors=True)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshEditCommandWorker(QObject):
    progress_changed = Signal(int, int, str)
    completed = Signal(int, object)
    cancelled = Signal(int, str)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        service: MeshService,
        session_id: str,
        command: MeshEditCommand,
        *,
        action_text: str = "",
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.command = command
        self.action_text = str(action_text or command.label or command.action or "mesh edit")
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                self.cancelled.emit(self.request_id, f"Cancelled {self.action_text}.")
                return
            self.progress_changed.emit(self.request_id, 0, f"Applying {self.action_text}...")
            command = self.command
            action = str(command.action or "").strip().lower()
            if action in _LEGACY_DISPLAY_CLEANUP_ACTIONS:
                raise RuntimeError(
                    f"{action} is legacy display-shape cleanup and is not available in active Mesh Editor"
                )
            if action == "undo":
                result = self.service.undo(self.session_id)
            elif action == "redo":
                result = self.service.redo(self.session_id)
            else:
                params = dict(command.params or {})
                params["stop_event"] = self.stop_event
                result = self.service.apply_command(self.session_id, replace(command, params=params))
            if self.stop_event.is_set():
                self.cancelled.emit(self.request_id, f"Cancelled {self.action_text}.")
                return
            self.progress_changed.emit(self.request_id, 100, f"Applied {self.action_text}.")
            self.completed.emit(self.request_id, result)
        except RunCancelled:
            self.cancelled.emit(self.request_id, f"Cancelled {self.action_text}.")
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
            else:
                self.cancelled.emit(self.request_id, f"Cancelled {self.action_text}.")
        finally:
            self.finished.emit()


class MeshExportValidationWorker(QObject):
    completed = Signal(int, object, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        service: MeshService,
        session_id: str,
    ) -> None:
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


class MeshRebuildReportWorker(QObject):
    progress_changed = Signal(int, int, str)
    completed = Signal(int, object)
    cancelled = Signal(int, str)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        service: MeshService,
        session_id: str,
        *,
        action_text: str = "Rebuild report",
        output_path: Path | str = "",
        developer_override: bool = False,
        developer_override_reason: str = "",
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.action_text = str(action_text or "Rebuild report")
        self.output_path = Path(output_path) if str(output_path or "").strip() else None
        self.developer_override = bool(developer_override)
        self.developer_override_reason = str(developer_override_reason or "")
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                self.cancelled.emit(self.request_id, f"Cancelled {self.action_text}.")
                return
            self.progress_changed.emit(self.request_id, 0, f"Running {self.action_text}...")
            if self.output_path is None:
                if self.developer_override:
                    report = self.service.rebuild_report(
                        self.session_id,
                        developer_override=True,
                        developer_override_reason=self.developer_override_reason,
                    )
                else:
                    report = self.service.rebuild_report(self.session_id)
            else:
                if self.developer_override:
                    report = self.service.rebuild_asset(
                        self.session_id,
                        self.output_path,
                        developer_override=True,
                        developer_override_reason=self.developer_override_reason,
                    )
                else:
                    report = self.service.rebuild_asset(self.session_id, self.output_path)
            if self.stop_event.is_set():
                self.cancelled.emit(self.request_id, f"Cancelled {self.action_text}.")
                return
            self.progress_changed.emit(self.request_id, 100, f"Finished {self.action_text}.")
            self.completed.emit(self.request_id, report)
        except RunCancelled:
            self.cancelled.emit(self.request_id, f"Cancelled {self.action_text}.")
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
            else:
                self.cancelled.emit(self.request_id, f"Cancelled {self.action_text}.")
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
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.output_root = Path(output_root) if output_root is not None else None
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
            if self.stop_event.is_set():
                return
            package = build_mesh_dotnet_experiment_package(mesh, output_root=self.output_root)
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

    def stop(self) -> None:
        self.stop_event.set()

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
            view = self.service.replace_working_mesh(self.session_id, mesh)
            validation = self.service.validate_export(self.session_id)
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, view, validation, elapsed_ms)
        except Exception as exc:
            if not self.stop_event.is_set():
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
    "MeshFileSessionLoadWorker",
    "MeshEditablePackageExportWorker",
    "MeshEditablePackageImportWorker",
    "MeshDotNetExperimentPackageWorker",
    "MeshDotNetExperimentOutputImportWorker",
    "MeshEditCommandWorker",
    "MeshExportValidationWorker",
    "MeshNativePreviewPackageWorker",
    "MeshRebuildReportWorker",
    "MeshTextureSourceResolveWorker",
]
