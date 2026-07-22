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
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.atomic_file import atomic_copy_file, atomic_publish_files, atomic_write_bytes, atomic_write_text
from cdmw.domain.mesh import MeshEditCommand
from cdmw.models import RunCancelled
from cdmw.modding.mesh_parser import ParsedMesh, parse_mesh
from cdmw.modding.mesh_exporter import export_obj
from cdmw.modding.mesh_glb_interchange import export_glb, import_glb_with_sidecar
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_state import MeshExportSnapshot, MeshExportTextureSnapshot
from cdmw.workers.mesh_editor_aux_workers import (
    MeshDotNetExperimentOutputImportWorker,
    MeshDotNetExperimentPackageWorker,
    MeshDotNetSceneFrameWorker,
    MeshExportValidationWorker,
    MeshFileSessionLoadWorker,
    MeshTextureSourceResolveWorker,
)
from cdmw.workers.mesh_export_readback import readback_editable_package_metadata
from cdmw.workers.mesh_dotnet_material_update_worker import MeshDotNetMaterialUpdateWorker

_LEGACY_DISPLAY_CLEANUP_ACTIONS = frozenset({"triangulate_display", "quadrangulate_display"})
_BASE_TEXTURE_CHANNELS = frozenset({"base", "base_color", "albedo", "diffuse"})

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
        atomic_copy_file(cdmeta_path, sidecar_path)


def _raise_export_cancelled(stop_event: threading.Event) -> None:
    if stop_event.is_set():
        raise RunCancelled("Mesh export cancelled.")


def _wait_for_texture_updates(
    waiter: Callable[[float], bool] | None,
    stop_event: threading.Event,
) -> None:
    _raise_export_cancelled(stop_event)
    if waiter is None:
        return
    deadline = time.monotonic() + 5.0
    while True:
        _raise_export_cancelled(stop_event)
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            raise RuntimeError("resident texture updates did not become idle before export")
        if waiter(min(0.05, remaining)):
            return


def _artifact_row(path: Path, root: Path, role: str, **extra: object) -> dict[str, object]:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        "role": str(role),
        "path": path.relative_to(root).as_posix(),
        "size": int(path.stat().st_size),
        "sha256": digest,
        **extra,
    }


def _texture_artifact_name(resource: MeshExportTextureSnapshot) -> str:
    digest = hashlib.sha256(
        f"{resource.resource_id}\0{resource.channel}".encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    semantic = "".join(ch if ch.isalnum() else "_" for ch in resource.channel).strip("_") or "base"
    return f"{semantic}_{digest}.dds"


def _encode_bgra_snapshot_dds(
    resource: MeshExportTextureSnapshot,
    target: Path,
    stop_event: threading.Event,
) -> None:
    from PIL import Image

    from cdmw.core import texture_native
    from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset

    if not resource.bgra_data or resource.width <= 0 or resource.height <= 0:
        raise ValueError(f"resident texture snapshot is incomplete: {resource.resource_id}")
    expected = int(resource.row_pitch) * int(resource.height)
    if resource.row_pitch != resource.width * 4 or len(resource.bgra_data) != expected:
        raise ValueError(f"resident texture snapshot has an invalid BGRA8 layout: {resource.resource_id}")
    if texture_native.find_directxtex_texture_binary() is None:
        raise RuntimeError("Native DirectXTex texture backend cd-texture-dx is missing.")
    target.parent.mkdir(parents=True, exist_ok=True)
    png_path = target.with_suffix(".source.png")
    try:
        Image.frombytes(
            "RGBA",
            (int(resource.width), int(resource.height)),
            resource.bgra_data,
            "raw",
            "BGRA",
        ).save(png_path, format="PNG")
        preset = resolve_texture_editor_dds_preset(
            "base_color",
            width=int(resource.width),
            height=int(resource.height),
        )
        report = texture_native.encode_dds_with_directxtex(
            png_path,
            target,
            dds_format=preset.dds_format,
            width=int(resource.width),
            height=int(resource.height),
            mip_count=preset.mip_count,
            overwrite=True,
            timeout_seconds=60.0,
            stop_event=stop_event,
        )
        if not report or not target.is_file():
            raise RuntimeError(f"Native DDS export failed for resident texture {resource.resource_id}.")
    finally:
        png_path.unlink(missing_ok=True)


def _stage_export_textures(
    snapshot: MeshExportSnapshot,
    staging_dir: Path,
    stop_event: threading.Event,
    *,
    relative_root: Path = Path("textures"),
) -> tuple[dict[str, object], ...]:
    from cdmw.core.dds_native import inspect_dds_native_path

    rows: list[dict[str, object]] = []
    for resource in snapshot.texture_resources:
        _raise_export_cancelled(stop_event)
        target = staging_dir / relative_root / _texture_artifact_name(resource)
        if resource.dds_data:
            atomic_write_bytes(target, resource.dds_data)
        else:
            _encode_bgra_snapshot_dds(resource, target, stop_event)
        info = inspect_dds_native_path(target)
        if info.width <= 0 or info.height <= 0 or info.mip_count <= 0 or info.reason:
            raise RuntimeError(
                f"resident texture DDS readback failed for {resource.resource_id}: "
                f"{info.reason or 'invalid dimensions or mip count'}"
            )
        rows.append(
            _artifact_row(
                target,
                staging_dir,
                "texture_dds",
                resource_id=resource.resource_id,
                channel=resource.channel,
                revision=int(resource.revision),
                logical_path=resource.logical_path,
                readback={
                    "status": "passed",
                    "format": info.format_name,
                    "width": int(info.width),
                    "height": int(info.height),
                    "mip_count": int(info.mip_count),
                    "reason": info.reason,
                },
            )
        )
    return tuple(rows)


def _apply_export_texture_bindings(
    snapshot: MeshExportSnapshot,
    texture_rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    paths = {
        (str(row.get("resource_id") or ""), str(row.get("channel") or "")): str(row.get("path") or "")
        for row in texture_rows
    }
    submeshes = tuple(snapshot.mesh.submeshes or ())
    bindings: list[dict[str, object]] = []
    for submesh_index, submesh in enumerate(submeshes):
        current_texture = _normalized_texture_binding_path(getattr(submesh, "texture", ""))
        candidates = [
            resource
            for resource in snapshot.texture_resources
            if (not resource.affected_submeshes or submesh_index in resource.affected_submeshes)
            and paths.get((resource.resource_id, resource.channel))
        ]
        groups: dict[str, list[MeshExportTextureSnapshot]] = {}
        for resource in candidates:
            semantic = "base" if resource.channel in _BASE_TEXTURE_CHANNELS else resource.channel
            groups.setdefault(semantic, []).append(resource)
        for semantic in sorted(groups):
            resource = max(
                groups[semantic],
                key=lambda item: (
                    bool(current_texture and _normalized_texture_binding_path(item.logical_path) == current_texture),
                    bool(item.bgra_data),
                    int(item.revision),
                    item.resource_id,
                ),
            )
            relative_path = paths[(resource.resource_id, resource.channel)]
            if semantic == "base":
                submesh.texture = relative_path
            bindings.append(
                {
                    "submesh_index": submesh_index,
                    "resource_id": resource.resource_id,
                    "channel": resource.channel,
                    "revision": int(resource.revision),
                    "path": relative_path,
                }
            )
    return tuple(bindings)


def _normalized_texture_binding_path(value: object) -> str:
    text = str(value or "").strip()
    return os.path.normcase(os.path.abspath(os.path.normpath(text))) if text else ""


def _package_reparse_report(
    staging_dir: Path,
    name: str,
    source_mesh: ParsedMesh,
    texture_rows: Sequence[Mapping[str, object]] = (),
    texture_bindings: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    metadata_readback = readback_editable_package_metadata(staging_dir, name, source_mesh)
    glb_mesh = import_glb_with_sidecar(staging_dir / f"{name}.glb")
    obj_mesh = import_obj(str(staging_dir / f"{name}.obj"))
    mtl_text = (staging_dir / f"{name}.mtl").read_text(encoding="utf-8", errors="replace")
    sidecar_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in staging_dir.glob("*.meta.json")
    )
    for binding in texture_bindings:
        relative_path = str(binding.get("path") or "")
        channel = str(binding.get("channel") or "").strip().lower()
        if relative_path not in sidecar_text or (channel in _BASE_TEXTURE_CHANNELS and relative_path not in mtl_text):
            raise RuntimeError(f"exported texture binding did not resolve in its sidecar/MTL contract: {relative_path}")
    return {
        "status": "passed",
        "glb_submesh_count": len(tuple(glb_mesh.submeshes or ())),
        "obj_submesh_count": len(tuple(obj_mesh.submeshes or ())),
        "dds_readback": [dict(row.get("readback") or {}) for row in texture_rows],
        "texture_bindings": [dict(binding) for binding in texture_bindings],
        **metadata_readback,
    }


def _package_artifact_rows(
    staging_dir: Path,
    texture_rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    rows = [dict(row) for row in texture_rows]
    known = {str(row.get("path") or "") for row in rows}
    for path in sorted(staging_dir.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(staging_dir).as_posix()
        if not path.is_file() or relative in known or path.name == "mesh_export_report.json":
            continue
        suffix = path.suffix.lower()
        role = {
            ".glb": "mesh_glb",
            ".obj": "mesh_obj",
            ".mtl": "mesh_material",
        }.get(suffix, "mesh_metadata" if suffix in {".json", ".txt"} else "mesh_artifact")
        rows.append(_artifact_row(path, staging_dir, role))
    return tuple(rows)


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
        try:
            _wait_for_texture_updates(self.texture_updates_waiter, self.stop_event)
            started = time.perf_counter()
            snapshot = self.service.capture_export_snapshot(
                self.session_id,
                stop_event=self.stop_event,
                expected_mesh_revision=self.expected_mesh_revision,
            )
            self.output_dir.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=f".{self.output_dir.name}.export-",
                dir=self.output_dir.parent,
            ) as staging_raw:
                staging_dir = Path(staging_raw)
                texture_rows = _stage_export_textures(snapshot, staging_dir, self.stop_event)
                texture_bindings = _apply_export_texture_bindings(snapshot, texture_rows)
                snapshot_payload = self.service.export_snapshot_report(snapshot)
                snapshot_payload["resolved_texture_bindings"] = [dict(binding) for binding in texture_bindings]
                sidecar_payload = {"export_snapshot": snapshot_payload}
                export_glb(
                    snapshot.mesh,
                    str(staging_dir),
                    self.name,
                    extra_payload=sidecar_payload,
                )
                export_obj(
                    snapshot.mesh,
                    str(staging_dir),
                    self.name,
                    extra_payload=sidecar_payload,
                )
                staged_glb_path = staging_dir / f"{self.name}.glb"
                staged_sidecar_path = Path(f"{staged_glb_path}.meta.json")
                if staged_sidecar_path.is_file():
                    cdmeta_path = staging_dir / "mesh.cdmeta.json"
                    atomic_copy_file(staged_sidecar_path, cdmeta_path)
                    payload = json.loads(cdmeta_path.read_text(encoding="utf-8"))
                    atomic_write_text(
                        staging_dir / "original_asset_hash.txt",
                        str(payload.get("source_asset_hash", "") or ""),
                    )
                _raise_export_cancelled(self.stop_event)
                reparse = _package_reparse_report(
                    staging_dir,
                    self.name,
                    snapshot.mesh,
                    texture_rows,
                    texture_bindings,
                )
                artifact_rows = _package_artifact_rows(staging_dir, texture_rows)
                snapshot_payload = self.service.export_snapshot_report(
                    snapshot,
                    artifacts=artifact_rows,
                    output_reparse=reparse,
                )
                snapshot_payload["resolved_texture_bindings"] = [dict(binding) for binding in texture_bindings]
                report_path = staging_dir / "mesh_export_report.json"
                atomic_write_text(report_path, json.dumps(snapshot_payload, indent=2) + "\n")
                _raise_export_cancelled(self.stop_event)
                staged_files = tuple(path for path in staging_dir.rglob("*") if path.is_file())
                atomic_publish_files(
                    {path: self.output_dir / path.relative_to(staging_dir) for path in staged_files}
                )
                exported_paths = tuple(self.output_dir / path.relative_to(staging_dir) for path in staged_files)
            glb_path = self.output_dir / f"{self.name}.glb"
            obj_path = self.output_dir / f"{self.name}.obj"
            cdmeta_path = self.output_dir / "mesh.cdmeta.json"
            original_hash_path = self.output_dir / "original_asset_hash.txt"
            result = {
                "package_dir": self.output_dir,
                "mesh_path": glb_path,
                "obj_path": obj_path,
                "metadata_path": cdmeta_path,
                "original_asset_hash_path": original_hash_path,
                "files": exported_paths,
                "report_path": self.output_dir / "mesh_export_report.json",
                "export_snapshot": snapshot_payload,
                "artifacts": artifact_rows,
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
        target = self.output_path
        source_text = str(getattr(snapshot.base_mesh or snapshot.mesh, "path", "") or "").strip()
        if source_text and target.resolve(strict=False) == Path(source_text).resolve(strict=False):
            raise RuntimeError("mesh rebuild output must not overwrite the original source asset")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{target.name}.rebuild-", dir=target.parent) as staging_raw:
            staging_dir = Path(staging_raw)
            staged_target = staging_dir / target.name
            atomic_write_bytes(staged_target, result.data)
            texture_root = Path(f"{target.name}.resources") / "textures"
            texture_rows = _stage_export_textures(
                snapshot,
                staging_dir,
                self.stop_event,
                relative_root=texture_root,
            )
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
    "MeshFileSessionLoadWorker",
    "MeshEditablePackageExportWorker",
    "MeshEditablePackageImportWorker",
    "MeshDotNetExperimentPackageWorker",
    "MeshDotNetMaterialUpdateWorker",
    "MeshDotNetSceneFrameWorker",
    "MeshDotNetExperimentOutputImportWorker",
    "MeshEditCommandWorker",
    "MeshExportValidationWorker",
    "MeshReportWriteWorker",
    "MeshRebuildReportWorker",
    "MeshTextureSourceResolveWorker",
]
