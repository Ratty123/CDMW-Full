"""Independent Mesh Editor load, validation, and .NET package workers."""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Mapping, Sequence
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
from cdmw.services.mesh_texture_sources import resolve_mesh_texture_source
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
from cdmw.modding.mesh_parser import ParsedMesh


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
        comparison_mode: str = "side_by_side",
        interaction_mode: str = "placement",
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.output_root = Path(output_root) if output_root is not None else None
        self.reference_mesh = reference_mesh
        self.comparison_mode = str(comparison_mode or "side_by_side")
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
            reference_mesh = clone_mesh_for_editing(self.reference_mesh) if self.reference_mesh is not None else None
            if self.stop_event.is_set():
                return
            package = build_mesh_dotnet_experiment_package(
                mesh,
                output_root=self.output_root,
                reference_mesh=reference_mesh,
                comparison_mode=self.comparison_mode,
                interaction_mode=self.interaction_mode,
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
    "MeshDotNetExperimentOutputImportWorker",
    "MeshDotNetExperimentPackageWorker",
    "MeshExportValidationWorker",
    "MeshFileSessionLoadWorker",
    "MeshTextureSourceResolveWorker",
]
