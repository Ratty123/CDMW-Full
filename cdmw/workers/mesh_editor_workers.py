"""Background workers for Mesh Editor long-running work."""

from __future__ import annotations

import threading
import time
import shutil
import json
import os
import tempfile
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.atomic_file import atomic_copy_file, atomic_publish_files, atomic_publish_paths, atomic_write_bytes, atomic_write_text
from cdmw.core.mod_package import (
    MeshLooseModAsset,
    MeshLooseModFile,
    write_mesh_loose_mod_package_metadata,
    write_mod_package_manifest,
)
from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_MANAGER_PROFILES,
    mod_package_export_options_for_manager,
    normalize_mod_package_manager_profile,
)
from cdmw.domain.mesh import MeshEditCommand
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest
from cdmw.models import ModPackageInfo, RunCancelled
from cdmw.modding.mesh_parser import ParsedMesh, parse_mesh
from cdmw.modding.mesh_exporter import export_obj
from cdmw.modding.mesh_glb_interchange import export_glb, import_glb_with_sidecar
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_state import MeshExportSnapshot, MeshExportTextureSnapshot
from cdmw.services.archive_overlay_package_service import export_archive_overlay_package
from cdmw.domain.archives.filters import archive_entry_game_root, archive_entry_package_group
from cdmw.services.archive_overlay_install import (
    OverlayInstallPreparation,
    apply_overlay_install,
    prepare_overlay_install,
    restore_last_overlay_install,
)
from cdmw.services.new_item_service import game_is_running
from cdmw.workers.mesh_editor_aux_workers import (
    MeshArchiveMaterialContextResult,
    MeshArchiveMaterialContextWorker,
    MeshArchiveSessionLoadResult,
    MeshArchiveSessionLoadWorker,
    MeshDotNetExperimentPackageWorker,
    MeshDotNetSceneFrameWorker,
    MeshExportValidationWorker,
    MeshFileSessionLoadWorker,
    MeshTextureSourceResolveWorker,
)
from cdmw.workers.mesh_editor_export_support import (
    artifact_row as _artifact_row,
    texture_artifact_name as _texture_artifact_name,
)
from cdmw.services.mesh_interchange_export import (
    export_editable_mesh, _raise_export_cancelled, _wait_for_texture_updates,
    _apply_export_texture_bindings, _package_reparse_report,
)
from cdmw.workers.mesh_dotnet_material_update_worker import MeshDotNetMaterialUpdateWorker

_LEGACY_DISPLAY_CLEANUP_ACTIONS = frozenset({"triangulate_display", "quadrangulate_display"})
_BASE_TEXTURE_CHANNELS = frozenset({"base", "base_color", "albedo", "diffuse"})

def _editable_package_mesh_path(path: Path) -> Path:
    if path.is_dir():
        from cdmw.services.mesh_export_support import editable_package_mesh_in_folder
        candidate = editable_package_mesh_in_folder(path)
        if candidate is not None:
            return candidate
    return path


def _game_original_reader(stop_event: threading.Event | None) -> Callable[[object], bytes]:
    """Read what a Build Mod output replaces in the game, never an earlier pass's result.

    A later edit pass reads its source and inherited outputs from the prepared
    copy of the previous result. Recorded as their own original, Update Mod sees
    no change in them and puts the game file back. The entry still names its
    game location, which is read instead; an unreadable one stays unknown.
    """

    from cdmw.services.archive_read_service import read_archive_entry_data
    from cdmw.services.mesh_archive_results import RESULT_NOTES

    def read(entry) -> bytes:
        if getattr(entry, "prepared_path", None) is not None and entry.prepared_note in RESULT_NOTES:
            entry = replace(entry, prepared_path=None, prepared_sha256="", prepared_size=None, prepared_note="")
        return read_archive_entry_data(entry, stop_event=stop_event)[0]

    return read


def _ensure_editable_package_sidecar_alias(mesh_path: Path) -> None:
    sidecar_path = Path(f"{mesh_path}.meta.json")
    if sidecar_path.is_file():
        return
    cdmeta_path = mesh_path.parent / "mesh.cdmeta.json"
    if cdmeta_path.is_file():
        atomic_copy_file(cdmeta_path, sidecar_path)


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
        expected_mesh_revision: int | None = None,
        texture_updates_waiter: Callable[[float], bool] | None = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.output_dir = Path(output_dir)
        self.name = str(name or "mesh")
        self.expected_mesh_revision = expected_mesh_revision
        self.texture_updates_waiter = texture_updates_waiter
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        started = time.perf_counter()
        try:
            result = export_editable_mesh(
                self.service, self.session_id, self.output_dir, name=self.name,
                expected_mesh_revision=self.expected_mesh_revision,
                texture_updates_waiter=self.texture_updates_waiter, stop_event=self.stop_event,
            )
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, result, (time.perf_counter() - started) * 1000.0)
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
        from cdmw.services.fbx_blender_conversion import configured_blender
        self.blender_path = configured_blender()
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
            if mesh_path.suffix.lower() == ".glb":
                mesh = import_glb_with_sidecar(mesh_path)
            elif mesh_path.suffix.lower() == ".fbx":
                from cdmw.modding.scene_importer import import_fbx
                from cdmw.modding.mesh_obj_importer import roundtrip_companion_path
                if roundtrip_companion_path(mesh_path) is None:
                    raise ValueError("FBX sidecar is required for editable mesh package import.")
                mesh = import_fbx(mesh_path, blender_path=self.blender_path, stop_event=self.stop_event)
            elif mesh_path.suffix.lower() == ".obj":
                mesh = import_obj(str(mesh_path))
            else:
                raise ValueError("Choose an edited GLB, FBX, or OBJ mesh.")
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
            time.sleep(0.01)
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
            elif action == "object_transform":
                params = dict(command.params or {})
                result = self.service.set_object_transform(
                    self.session_id,
                    location=params.get("location"),
                    rotation_degrees=params.get("rotation_degrees"),
                    scale=params.get("scale"),
                    label=str(command.label or self.action_text),
                    stop_event=self.stop_event,
                )
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
        expected_mesh_revision: int | None = None,
        texture_updates_waiter: Callable[[float], bool] | None = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.action_text = str(action_text or "Rebuild report")
        self.output_path = Path(output_path) if str(output_path or "").strip() else None
        self.developer_override = bool(developer_override)
        self.developer_override_reason = str(developer_override_reason or "")
        self.expected_mesh_revision = expected_mesh_revision
        self.texture_updates_waiter = texture_updates_waiter
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
            capture = getattr(self.service, "capture_export_snapshot", None)
            if not callable(capture):
                report = self._run_legacy_service()
            else:
                _wait_for_texture_updates(self.texture_updates_waiter, self.stop_event)
                snapshot = capture(
                    self.session_id,
                    stop_event=self.stop_event,
                    expected_mesh_revision=self.expected_mesh_revision,
                )
                report = self._run_snapshot_export(snapshot)
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

    def _run_legacy_service(self) -> object:
        kwargs = {
            "developer_override": True,
            "developer_override_reason": self.developer_override_reason,
        } if self.developer_override else {}
        if self.output_path is None:
            return self.service.rebuild_report(self.session_id, **kwargs)
        return self.service.rebuild_asset(self.session_id, self.output_path, **kwargs)

    def _run_snapshot_export(self, snapshot: MeshExportSnapshot) -> object:
        result, report = self.service.rebuild_result_from_snapshot(
            snapshot,
            output_path=str(self.output_path or ""),
            developer_override=self.developer_override,
            developer_override_reason=self.developer_override_reason,
        )
        if self.output_path is None:
            return report
        if getattr(result, "companion_files", ()):
            raise RuntimeError("This replacement requires companion files. Use Build Mod to export the complete result.")
        target = self.output_path
        source_text = str(getattr(snapshot.base_mesh or snapshot.mesh, "path", "") or "").strip()
        if source_text and target.resolve(strict=False) == Path(source_text).resolve(strict=False):
            raise RuntimeError("mesh rebuild output must not overwrite the original source asset")
        if snapshot.texture_resources or int(snapshot.material_generation) > 0:
            raise RuntimeError(
                "Export Mesh File cannot contain texture or material authoring changes"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{target.name}.rebuild-", dir=target.parent) as staging_raw:
            staging_dir = Path(staging_raw)
            staged_target = staging_dir / target.name
            atomic_write_bytes(staged_target, result.data)
            texture_rows: tuple[dict[str, object], ...] = ()
            reparsed = parse_mesh(result.data, str(target))
            output_reparse = {
                "status": "passed",
                "format": str(reparsed.format or ""),
                "submesh_count": len(tuple(reparsed.submeshes or ())),
                "vertex_count": int(reparsed.total_vertices),
                "face_count": int(reparsed.total_faces),
                "dds_readback": [dict(row.get("readback") or {}) for row in texture_rows],
            }
            artifacts = (_artifact_row(staged_target, staging_dir, "rebuilt_mesh"), *texture_rows)
            export_report = self.service.export_snapshot_report(
                snapshot,
                artifacts=artifacts,
                output_reparse=output_reparse,
            )
            report = replace(report, output_path=str(target), export_snapshot=export_report)
            staged_report = staging_dir / f"{target.name}.export.json"
            atomic_write_text(staged_report, json.dumps(asdict(report), indent=2) + "\n")
            _raise_export_cancelled(self.stop_event)
            staged_files = tuple(path for path in staging_dir.rglob("*") if path.is_file())
            atomic_publish_files(
                {path: target.parent / path.relative_to(staging_dir) for path in staged_files}
            )
        return report


@dataclass(frozen=True, slots=True)
class MeshDirectOutputResult:
    kind: str
    output_path: Path | None
    manager_profile: str = ""
    rebuild_report: object | None = None
    overlay_preparation: OverlayInstallPreparation | None = None
    install_result: object | None = None
    zip_path: Path | None = None
    archive_result: object | None = None
    # The Drafts & Mods record for a built mod, or why it failed.
    saved_work_record: Mapping[str, object] | None = None
    saved_work_error: str = ""


class MeshDirectOutputWorker(QObject):
    """Capture one immutable revision and publish a mesh-only output."""

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
        entry: object,
        *,
        kind: str,
        output_path: Path | str | None = None,
        manager_profile: str = "dmm",
        package_info: ModPackageInfo | None = None,
        create_zip: bool = False,
        expected_mesh_revision: int | None = None,
        texture_updates_waiter: Callable[[float], bool] | None = None,
        archive_dependency_sources: tuple = (),
        archive_material_sources: tuple = (),
        inherited_archive_outputs: tuple = (),
        saved_work_root: Path | str | None = None,
        include_refit_body: bool = False,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.entry = entry
        self.kind = str(kind or "").strip().lower()
        self.output_path = Path(output_path) if output_path is not None else None
        requested_profile = str(manager_profile or "").strip().lower()
        normalized_profile = normalize_mod_package_manager_profile(requested_profile)
        if requested_profile and requested_profile not in MOD_PACKAGE_MANAGER_PROFILES:
            raise ValueError(f"Unsupported mesh mod manager profile: {manager_profile}")
        if self.kind == "overlay_package" and normalized_profile != "dmm":
            raise ValueError("Mesh archive-group packages are supported only for the DMM manager profile")
        self.manager_profile = normalized_profile
        self.package_info = replace(package_info) if package_info is not None else None
        self.create_zip = bool(create_zip)
        self.expected_mesh_revision = expected_mesh_revision
        self.texture_updates_waiter = texture_updates_waiter
        self.archive_dependency_sources = archive_dependency_sources
        self.archive_material_sources = archive_material_sources
        self.inherited_archive_outputs = inherited_archive_outputs
        self.include_refit_body = bool(include_refit_body)
        self.saved_work_root = (
            Path(saved_work_root)
            if saved_work_root is not None and self.kind in {"loose_mod", "overlay_package"}
            else None
        )
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        replacement_baselines = None
        try:
            if self.stop_event.is_set():
                raise RunCancelled("Mesh output cancelled")
            self.progress_changed.emit(self.request_id, 0, "Capturing the validated Mesh Editor revision...")
            _wait_for_texture_updates(self.texture_updates_waiter, self.stop_event)
            snapshot = self.service.capture_export_snapshot(
                self.session_id,
                stop_event=self.stop_event,
                expected_mesh_revision=self.expected_mesh_revision,
            )
            if self.kind == "archive_result":
                from cdmw.services.mesh_archive_results import prepare_mesh_archive_result
                if self.output_path is None:
                    raise ValueError("An archive result needs a workspace output folder.")
                prepared = prepare_mesh_archive_result(self.service, snapshot, self.entry,
                    self.archive_dependency_sources, self.output_path, stop_event=self.stop_event,
                    material_contexts=self.archive_material_sources)
                self.completed.emit(self.request_id, MeshDirectOutputResult(
                    kind=self.kind, output_path=prepared.root, archive_result=prepared))
                return
            if snapshot.hair_state is not None:
                if self.kind != "overlay_package" or self.manager_profile != "dmm" or self.output_path is None:
                    raise ValueError("Hairstyles require Build Mod → DMM Archive Group to add the complete barber choice.")
                from cdmw.services.mesh_hair_output import export_hair_package
                rebuilt, report = self.service.rebuild_result_from_snapshot(snapshot)
                output = export_hair_package(snapshot, rebuilt, self.entry, self.output_path,
                    stop_event=self.stop_event,
                    on_log=lambda message: self.progress_changed.emit(self.request_id, 25, message))
                self.completed.emit(self.request_id, MeshDirectOutputResult(
                    kind=self.kind, output_path=output, manager_profile="dmm", rebuild_report=report))
                return
            if snapshot.texture_resources or int(snapshot.material_generation) > 0:
                raise RuntimeError(
                    "Mesh-only outputs cannot contain texture or material authoring changes"
                )
            from cdmw.services.mesh_archive_results import BODY_RESULT_NOTE
            if getattr(snapshot, "archive_refit_context", None) is None:
                components = ((self.entry, snapshot),)
            else:
                from cdmw.services.mesh_archive_refit import archive_refit_snapshots
                components = archive_refit_snapshots(snapshot)
                if components[0][0].identity != self.entry.identity:
                    raise RuntimeError("Archive Refit output target no longer matches the loaded source")
            body = self._fit_body_flags(snapshot, components)
            omitted_paths = [entry.path for (entry, _component), omit in zip(components, body) if omit]
            requests = []
            additions = []
            reports = []
            written = []
            report = None
            for index, (entry, component) in enumerate(components):
                _raise_export_cancelled(self.stop_event)
                if body[index] and index:
                    continue
                # The target's rebuild report describes the output, written or not.
                rebuilt, component_report = self.service.rebuild_result_from_snapshot(component)
                if not index:
                    report = component_report
                if body[index]:
                    continue
                if getattr(component, "replacement_state", None) is not None:
                    from cdmw.services.mesh_replacement_import import archive_entry, archive_location
                    state = component.replacement_state
                    if state.target_path.casefold() != entry.path.casefold() or (
                        state.target_location is not None and state.target_location != archive_location(entry)
                    ):
                        raise RuntimeError("Replacement output target no longer matches the captured archive identity.")
                    if replacement_baselines is None:
                        replacement_baselines = tempfile.TemporaryDirectory(prefix="cdmw-replacement-baselines-")

                    def captured_entry(item, data):
                        digest = hashlib.sha256(data).hexdigest()
                        path = Path(replacement_baselines.name) / digest
                        path.write_bytes(data)
                        return replace(item, prepared_path=path, prepared_sha256=digest, prepared_size=len(data))

                    entry = captured_entry(entry, component.original_data)
                    for file in rebuilt.companion_files:
                        companion_entry = archive_entry(file)
                        if companion_entry is not None:
                            baseline = next((item for item in state.dependencies if item.path.casefold() == file.path.casefold()), None)
                            if baseline is None:
                                raise ValueError(f"Replacement companion has no captured baseline: {file.path}")
                            companion_entry = captured_entry(companion_entry, baseline.data)
                            requests.append(ArchivePatchRequest(companion_entry, file.data))
                        else:
                            additions.append(ArchiveAddRequest(Path(entry.pamt_path), file.path, file.data))
                requests.append(ArchivePatchRequest(entry, rebuilt.data))
                reports.append(component_report)
                written.append((entry, component))
            if self.inherited_archive_outputs:
                from cdmw.services.mesh_archive_results import ADDED_RESULT_NOTE
                from cdmw.services.archive_read_service import read_archive_entry_data
                normalize = lambda path: str(path).replace("\\", "/").casefold()
                added_paths = {normalize(item.path) for item in self.inherited_archive_outputs
                               if item.prepared_note == ADDED_RESULT_NOTE}
                # A generated companion may already have become a prepared source
                # in the next pass. It still needs an addition in the final mod.
                for request in tuple(requests):
                    if normalize(request.entry.path) in added_paths:
                        requests.remove(request)
                        additions.append(ArchiveAddRequest.from_template(request.entry, request.entry.path, request.payload_data))
                included = {normalize(request.entry.path) for request in requests}
                included.update(normalize(request.path) for request in additions)
                # An earlier pass's copy of a body left out of this mod stays out too.
                included.update(normalize(path) for path in omitted_paths)
                for inherited in self.inherited_archive_outputs:
                    if normalize(inherited.path) in included:
                        continue
                    if inherited.prepared_note == BODY_RESULT_NOTE and not self.include_refit_body:
                        omitted_paths.append(inherited.path)
                        included.add(normalize(inherited.path))
                        continue
                    _raise_export_cancelled(self.stop_event)
                    data = read_archive_entry_data(inherited, stop_event=self.stop_event)[0]
                    if inherited.prepared_note == ADDED_RESULT_NOTE:
                        additions.append(ArchiveAddRequest.from_template(inherited, inherited.path, data))
                    else:
                        requests.append(ArchivePatchRequest(inherited, data))
                    included.add(normalize(inherited.path))
            if not requests and not additions:
                raise ValueError("Only the body is left to write. Turn on Include the body to build it.")
            if self.stop_event.is_set():
                raise RunCancelled("Mesh output cancelled")
            metadata = self._metadata(snapshot, report)
            if len(written) > 1 or omitted_paths:
                payload = json.loads(metadata)
                payload["assets"] = [
                    {"path": entry.path, "source_sha256": component.mesh_asset_source_hash,
                     "rebuild_report": asdict(component_report) if is_dataclass(component_report) else component_report}
                    for (entry, component), component_report in zip(written, reports, strict=True)
                ]
                if omitted_paths:
                    payload["omitted_body_assets"] = list(omitted_paths)
                metadata = (json.dumps(payload, indent=2, default=str) + "\n").encode("utf-8")
            if self.kind == "loose_mod":
                result = self._write_loose_mod(tuple(requests), metadata, report, additions=tuple(additions)) if additions else self._write_loose_mod(tuple(requests), metadata, report)
            elif self.kind == "overlay_package":
                result = self._write_overlay_package(tuple(requests), metadata, report, additions=tuple(additions)) if additions else self._write_overlay_package(tuple(requests), metadata, report)
            elif self.kind == "overlay_prepare":
                package_root = archive_entry_game_root(self.entry)
                preparation = prepare_overlay_install(
                    tuple(requests),
                    additions=tuple(additions),
                    package_root=package_root,
                    stop_event=self.stop_event,
                )
                result = MeshDirectOutputResult(
                    kind=self.kind,
                    output_path=None,
                    rebuild_report=report,
                    overlay_preparation=preparation,
                )
            else:
                raise ValueError(f"Unsupported Mesh Editor output kind: {self.kind}")
            result = self._register_saved_work(snapshot, result)
            self.progress_changed.emit(self.request_id, 100, "Mesh-only output is ready.")
            self.completed.emit(self.request_id, result)
        except RunCancelled:
            self.cancelled.emit(self.request_id, "Mesh output cancelled.")
        except Exception as exc:
            if self.stop_event.is_set():
                self.cancelled.emit(self.request_id, "Mesh output cancelled.")
            else:
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            if replacement_baselines is not None:
                replacement_baselines.cleanup()
            self.archive_material_sources = ()
            self.finished.emit()

    def _fit_body_flags(self, snapshot: MeshExportSnapshot, components: tuple) -> tuple[bool, ...]:
        """Mark the components that are the body a Fit follows.

        That body is a reference: shipping it would override every other mod
        that changes it, so it stays out unless Include the body was chosen.
        """
        from cdmw.services.mesh_archive_refit import archive_refit_body_assets
        from cdmw.services.mesh_archive_results import BODY_RESULT_NOTE

        if self.include_refit_body:
            return (False,) * len(components)
        context = getattr(snapshot, "archive_refit_context", None)
        if context is None:
            return (getattr(self.entry, "prepared_note", "") == BODY_RESULT_NOTE,)
        body = {asset.entry.identity for asset in archive_refit_body_assets(
            context, self.service.cached_morph_state(self.session_id))}
        return tuple(entry.identity in body for entry, _component in components)

    def _register_saved_work(self, snapshot: MeshExportSnapshot, result: MeshDirectOutputResult) -> MeshDirectOutputResult:
        """Keep the built mod and its editing state for Continue Earlier Work.

        The mod is already published, so a failure here is reported beside it
        and is never turned into a failed or cancelled build.
        """

        if self.saved_work_root is None or result.output_path is None:
            return result
        from cdmw.services.mesh_saved_work_service import register_built_mod

        try:
            # Hold the session's export lock while the draft is copied, so a
            # pending autosave cannot replace its generations mid-copy.
            with self.service._session(self.session_id).export_lock:
                draft = self.service.save_mesh_draft_for_revision(
                    self.session_id, expected_mesh_revision=snapshot.mesh_revision,
                )
                record = register_built_mod(
                    self.saved_work_root,
                    mod_root=result.output_path,
                    entry=self.entry,
                    source_sha256=snapshot.mesh_asset_source_hash,
                    draft_manifest_path=draft,
                    zip_path=result.zip_path,
                    manager_profile=result.manager_profile,
                    kind=self.kind,
                )
        except Exception as exc:
            return replace(result, saved_work_error=f"{type(exc).__name__}: {exc}")
        return replace(result, saved_work_record=record)

    def _metadata(self, snapshot: MeshExportSnapshot, report: object) -> bytes:
        payload = {
            "format": "cdmw_mesh_editor_output_v1",
            "source_path": str(getattr(self.entry, "path", "") or ""),
            "source_sha256": snapshot.mesh_asset_source_hash,
            "mesh_revision": snapshot.mesh_revision,
            "native_edit_revision": snapshot.native_edit_revision,
            "manager_profile": self.manager_profile if self.kind in {"loose_mod", "overlay_package"} else "",
            "materials": "inherited_unchanged",
            "textures": "inherited_unchanged",
            "contents": ["rebuilt_mesh", "validation_metadata"],
            "rebuild_report": asdict(report) if is_dataclass(report) else report,
        }
        state = getattr(snapshot, "replacement_state", None)
        if state is not None:
            payload.update(format="cdmw_mesh_editor_output_v2", replacement_revision=state.revision,
                           materials=[{"part_id": part.part_id, "choice": part.material_choice, "included": part.included} for part in state.parts],
                           textures="prepared_bundle", contents=["rebuilt_mesh", "prepared_companions", "validation_metadata"])
        return (json.dumps(payload, indent=2, default=str) + "\n").encode("utf-8")

    def _package_info(self, root: Path) -> ModPackageInfo:
        if self.package_info is not None:
            return self.package_info
        source_path = str(getattr(self.entry, "path", "") or "").replace("\\", "/").strip("/")
        return ModPackageInfo(
            title=root.name,
            version="1.0",
            description=f"Mesh Editor replacement for {source_path}.",
        )

    def _publish_mod_output(self, staging: Path, root: Path) -> Path | None:
        from cdmw.core.mod_export_history import retain_mod_history
        from cdmw.core.mod_package import _write_package_zip

        # DMM reads the same name/version/author/description from manifest.json.
        # Remove the duplicate before binding local history to the final files.
        if self.manager_profile == "dmm":
            (staging / "modinfo.json").unlink(missing_ok=True)
        elif self.manager_profile == "cdumm":
            # CDUMM detects modinfo.json + files/ and reads the mod details
            # from modinfo.json. Its importer derives encryption from the game.
            (staging / "manifest.json").unlink(missing_ok=True)
            (staging / ".no_encrypt").unlink(missing_ok=True)
        retain_mod_history(staging, stop_event=self.stop_event)
        (staging / "README.txt").unlink(missing_ok=True)
        zip_path = root.with_name(root.name + ".zip") if self.create_zip else None
        staged_zip = staging.with_name(staging.name + ".zip") if self.create_zip else None
        try:
            outputs = [(staging, root)]
            if staged_zip is not None:
                _write_package_zip(staging, zip_path=staged_zip, stop_event=self.stop_event)
                outputs.append((staged_zip, zip_path))
            _raise_export_cancelled(self.stop_event)
            atomic_publish_paths(outputs, replace_existing=False)
            return zip_path
        finally:
            if staged_zip is not None:
                staged_zip.unlink(missing_ok=True)

    def _write_loose_mod(
        self,
        requests: tuple[ArchivePatchRequest, ...],
        metadata: bytes,
        report: object,
        *,
        additions: tuple[ArchiveAddRequest, ...] = (),
    ) -> MeshDirectOutputResult:
        if self.output_path is None:
            raise ValueError("Loose Mesh Editor output needs a package folder")
        if self.manager_profile == "field_json":
            raise ValueError("Field-JSON only describes DDS assets and cannot safely package a mesh payload")
        root = self.output_path.resolve()
        if root.exists():
            raise FileExistsError(f"Mesh mod output already exists: {root}")
        assets = []
        files = []
        relative_paths = []
        for request in requests:
            relative = Path(str(request.entry.path or "").replace("\\", "/"))
            if relative.is_absolute() or relative.drive or ".." in relative.parts or not relative.name:
                raise ValueError("Archive mesh path escapes the loose package")
            if relative in relative_paths:
                raise ValueError("Archive Refit output has duplicate asset paths")
            relative_paths.append(relative)
            package_group = archive_entry_package_group(request.entry)
            mesh_format = relative.suffix.lstrip(".").lower()
            assets.append(MeshLooseModAsset(entry_path=relative.as_posix(), package_group=package_group,
                                           format=mesh_format, note="Validated Mesh Editor replacement"))
            files.append(MeshLooseModFile(path=relative.as_posix(), package_group=package_group,
                                         format=mesh_format, note="Validated Mesh Editor replacement"))
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.staging-", dir=root.parent))
        try:
            for request, relative in zip(requests, relative_paths, strict=True):
                _raise_export_cancelled(self.stop_event)
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(target, request.payload_data)
            for addition in additions:
                relative = Path(addition.path.replace("\\", "/"))
                if relative.is_absolute() or relative.drive or ".." in relative.parts or not relative.name or relative in relative_paths:
                    raise ValueError("Replacement companion has an invalid or duplicate package path")
                relative_paths.append(relative)
                package_group = archive_entry_package_group(addition)
                mesh_format = relative.suffix.lstrip(".").lower()
                assets.append(MeshLooseModAsset(entry_path=relative.as_posix(), package_group=package_group,
                                               format=mesh_format, note="Replacement companion"))
                files.append(MeshLooseModFile(path=relative.as_posix(), package_group=package_group,
                                             format=mesh_format, note="Replacement companion"))
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(target, addition.payload_data)
            atomic_write_bytes(staging / "mesh-editor-session.json", metadata)
            options = mod_package_export_options_for_manager(self.manager_profile)
            from cdmw.core.mod_compatibility import capture_patch_compatibility
            compatibility = capture_patch_compatibility(requests, additions,
                game_root=archive_entry_game_root(self.entry), stop_event=self.stop_event,
                read_entry=_game_original_reader(self.stop_event))
            write_mesh_loose_mod_package_metadata(
                staging,
                self._package_info(root),
                assets=tuple(assets),
                files=tuple(files),
                include_paired_lod=False,
                export_options=options,
                create_no_encrypt_file=bool(options.create_no_encrypt_file),
                compatibility=compatibility,
                stop_event=self.stop_event,
            )
            zip_path = self._publish_mod_output(staging, root)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return MeshDirectOutputResult(
            kind=self.kind,
            output_path=root,
            manager_profile=self.manager_profile,
            rebuild_report=report,
            zip_path=zip_path,
        )

    def _write_overlay_package(
        self,
        requests: tuple[ArchivePatchRequest, ...],
        metadata: bytes,
        report: object,
        *,
        additions: tuple[ArchiveAddRequest, ...] = (),
    ) -> MeshDirectOutputResult:
        if self.output_path is None:
            raise ValueError("DMM Mesh Editor output needs a package folder")
        root = self.output_path.resolve()
        if root.exists():
            raise FileExistsError(f"Mesh mod output already exists: {root}")
        game_root = archive_entry_game_root(self.entry)
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.staging-", dir=root.parent))
        try:
            from cdmw.core.mod_compatibility import capture_patch_compatibility
            metadata_files = (("mesh-editor-session.json", metadata),)
            exported = export_archive_overlay_package(
                requests,
                additions=additions,
                package_root=staging,
                game_root=game_root,
                metadata_files=metadata_files,
                stop_event=self.stop_event,
                compatibility=capture_patch_compatibility(
                    requests, additions, game_root=game_root, metadata_files=metadata_files,
                    read_entry=_game_original_reader(self.stop_event), stop_event=self.stop_event,
                ),
            )
            group = str(exported.group or "").strip()
            archive_files = (f"{group}/0.pamt", f"{group}/0.paz")
            for relative in archive_files:
                if not (staging / relative).is_file():
                    raise RuntimeError(f"DMM archive-group package is missing {relative}")
            payload_paths = [*archive_files]
            # DMM assigns the mounted group and rebuilds its own mount list.
            # The shared writer's copy belongs only to this staging directory.
            (staging / "meta" / "0.papgt").unlink(missing_ok=True)
            dmm_options = replace(
                mod_package_export_options_for_manager("dmm"),
                structure="game_relative",
                create_manifest_json=True,
            )
            write_mod_package_manifest(
                staging,
                self._package_info(root),
                kind="archive_override_mod",
                all_payload_paths=tuple(payload_paths),
                export_options=dmm_options,
                create_no_encrypt_file=False,
                extra_fields={
                    "structure": "archive_group",
                    "archive_group": group,
                    "file_count": int(exported.file_count),
                    "overrides": list(exported.paths),
                },
                stop_event=self.stop_event,
            )
            for relative in archive_files:
                if not (staging / relative).is_file():
                    raise RuntimeError(f"DMM package metadata changed archive-group payload {relative}")
            zip_path = self._publish_mod_output(staging, root)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return MeshDirectOutputResult(
            kind=self.kind,
            output_path=root,
            manager_profile="dmm",
            rebuild_report=report,
            zip_path=zip_path,
        )


class MeshOverlayApplyWorker(QObject):
    completed = Signal(int, object)
    cancelled = Signal(int, str)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        preparation: OverlayInstallPreparation,
        mutation_service: object,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.preparation = preparation
        self.mutation_service = mutation_service
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            def backup(paths, label):
                return self.mutation_service.backup_files(paths, description=label)

            def restore(path):
                return self.mutation_service.restore_backup(path, confirmed=True)

            result = apply_overlay_install(
                self.preparation,
                confirmed=True,
                backup=backup,
                restore_backup=restore,
                game_running=game_is_running,
                stop_event=self.stop_event,
            )
            self.completed.emit(
                self.request_id,
                MeshDirectOutputResult(
                    kind="overlay_install",
                    output_path=result.directory,
                    install_result=result,
                ),
            )
        except RunCancelled:
            self.cancelled.emit(self.request_id, "Overlay installation cancelled.")
        except Exception as exc:
            self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshOverlayRestoreWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request_id: int, receipt_path: Path | str, mutation_service: object) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.receipt_path = Path(receipt_path)
        self.mutation_service = mutation_service

    @Slot()
    def run(self) -> None:
        try:
            root = restore_last_overlay_install(
                self.receipt_path,
                confirmed=True,
                restore_backup=lambda path: self.mutation_service.restore_backup(path, confirmed=True),
                game_running=game_is_running,
            )
            self.completed.emit(self.request_id, root)
        except Exception as exc:
            self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MeshReportWriteWorker(QObject):
    """Stage and atomically publish a small Mesh Editor JSON report."""

    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        path: Path | str,
        payload: object,
        *,
        serializer: Callable[[object], object] | None = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.path = Path(path)
        self.payload = payload
        self.serializer = serializer
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        staged_path: Path | None = None
        try:
            if self.stop_event.is_set():
                return
            payload = self.serializer(self.payload) if self.serializer is not None else self.payload
            text = payload if isinstance(payload, str) else json.dumps(payload, indent=2) + "\n"
            if self.stop_event.is_set():
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, staged_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
            )
            staged_path = Path(staged_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if self.stop_event.is_set():
                return
            atomic_publish_files({staged_path: self.path})
            staged_path = None
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, self.path)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            if staged_path is not None:
                staged_path.unlink(missing_ok=True)
            self.finished.emit()


__all__ = [
    "MeshArchiveMaterialContextResult",
    "MeshArchiveMaterialContextWorker",
    "MeshArchiveSessionLoadResult",
    "MeshArchiveSessionLoadWorker",
    "MeshFileSessionLoadWorker",
    "MeshEditablePackageExportWorker",
    "MeshEditablePackageImportWorker",
    "MeshDotNetExperimentPackageWorker",
    "MeshDotNetMaterialUpdateWorker",
    "MeshDotNetSceneFrameWorker",
    "MeshDirectOutputResult",
    "MeshDirectOutputWorker",
    "MeshEditCommandWorker",
    "MeshExportValidationWorker",
    "MeshReportWriteWorker",
    "MeshRebuildReportWorker",
    "MeshOverlayApplyWorker",
    "MeshOverlayRestoreWorker",
    "MeshTextureSourceResolveWorker",
]
