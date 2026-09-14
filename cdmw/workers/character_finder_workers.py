"""Cancellable production Rust preview and 256px thumbnail jobs."""

from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QImage

from cdmw.domain.character_finder import CharacterPreviewInputs, CharacterRenderResult, character_preview_detail
from cdmw.domain.character_context import NativePreviewContextComponent
from cdmw.models import ModelPreviewRenderSettings, RunCancelled
from cdmw.services.mesh_rust_contract import RUST_MESH_RENDERER, RUST_PREVIEW_BACKEND, resolve_rust_mesh_editor
from cdmw.services.mesh_rust_preview_cache import RUST_PREVIEW_CACHE_SCHEMA
from cdmw.services.mesh_rust_preview_package import rust_preview_package_from_path
from cdmw.rendering.dotnet_preview_package_cache import (
    acquire_dotnet_preview_package_cache_lease_for_path, dotnet_preview_package_cache_build_lock,
)

_CHARACTER_RENDER_SCHEMA = 5


def character_row_cache_root(cache_root, fingerprint, settings):
    identity = {"schema": _CHARACTER_RENDER_SCHEMA, "fingerprint": fingerprint,
        "renderer": RUST_MESH_RENDERER, "backend": RUST_PREVIEW_BACKEND,
        "package_schema": RUST_PREVIEW_CACHE_SCHEMA, "camera": "renderer-front-v2", "settings": asdict(settings)}
    namespace = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return cache_root / "character_finder" / "rows" / namespace


def _row_cache_path(root, row_key):
    return root / (sha256(row_key.encode()).hexdigest() + ".json")


def remember_character_thumbnail(root, row_key, result):
    path = _row_cache_path(root, row_key)
    temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
    try:
        root.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({"row": row_key, "render": result.key}), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass  # The optional row index must not prevent an existing preview from loading.
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def cached_character_row(cache_root, row_root, row_key):
    path = _row_cache_path(row_root, row_key)
    try:
        if path.stat().st_size > 4096:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        key = value["render"]
        if value["row"] != row_key or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            return None
        return cached_character_render(cache_root, key, require_package=False)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def character_render_key(detail, fingerprint: str, settings: ModelPreviewRenderSettings) -> str:
    detail = character_preview_detail(detail)
    identity = {"row": detail.row.key, "context": detail.context_key}
    needed = {entry_id for c in detail.components for entry_id in (*c.model_entry_ids, *c.context_entry_ids)}
    available = {f.entry_id for f in detail.files} | {m.entry_id for m in detail.models}
    if detail.components and detail.models and needed.issubset(available) and detail.total_file_count <= len(detail.files):
        # Identical heads and bodies can belong to many named characters. Share
        # only complete render inputs, retaining scale, prefab, PABC, material,
        # customization and primary model order instead of an ownership key.
        identity = {"role": detail.row.role, "embedded_face": detail.row.embedded_face,
                    "components": [asdict(c) for c in detail.components],
                    "models": [m.entry_id for m in detail.models], "files": [asdict(f) for f in detail.files]}
    context = {"schema": _CHARACTER_RENDER_SCHEMA, "fingerprint": fingerprint, "identity": identity,
               "renderer": RUST_MESH_RENDERER, "backend": RUST_PREVIEW_BACKEND,
               "package_schema": RUST_PREVIEW_CACHE_SCHEMA,
               "camera": "renderer-front-v2",
               "settings": asdict(settings)}
    return sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()


def cached_character_render(cache_root: Path, key: str, *, require_package: bool = True) -> CharacterRenderResult | None:
    path = cache_root / "character_finder" / "thumbnails" / (key + ".json")
    try:
        if path.stat().st_size > 64 * 1024:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        image = path.with_suffix(".png")
        package = Path(value["package_path"])
        if not image.is_file() or value["key"] != key:
            return None
        if require_package and not (package / "manifest.json").is_file():
            return None
        return CharacterRenderResult(key, str(package), str(image), value["status"], tuple(value["notes"]), True)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cached_character_package(cache_root: Path, key: str) -> CharacterRenderResult | None:
    """Reuse complete 3D output even if its later thumbnail capture was interrupted."""
    path = cache_root / "character_finder" / "thumbnails" / (key + ".package.json")
    try:
        if path.stat().st_size > 64 * 1024:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["key"] != key:
            return None
        package = rust_preview_package_from_path(value["package_path"])
        return CharacterRenderResult(key, str(package.package_dir), "", value["status"], tuple(value["notes"]), True)
    except (OSError, ValueError, KeyError, TypeError):
        return None


class CharacterFinderRenderWorker(QObject):
    package_ready = Signal(int, object)
    completed = Signal(int, object)
    failed = Signal(int, str)
    cache_missed = Signal(int)
    finished = Signal()

    def __init__(self, token: int, inputs: CharacterPreviewInputs, *, cache_root: Path,
                 fingerprint: str, settings: ModelPreviewRenderSettings, cache_only: bool = False) -> None:
        super().__init__()
        self.token = token
        self.inputs = inputs
        self.cache_root = cache_root
        self.fingerprint = fingerprint
        self.settings = replace(settings, use_textures_by_default=True)
        self._stop = threading.Event()
        self._capture_report = {}
        self._cache_only = cache_only

    def stop(self) -> None:
        self._stop.set()

    def _check(self) -> None:
        if self._stop.is_set():
            raise RunCancelled("Character preview cancelled.")

    @Slot()
    def run(self) -> None:
        try:
            self._check()
            key = character_render_key(self.inputs.detail, self.fingerprint, self.settings)
            # Character names can share exact shape/material inputs. Coordinate
            # their expensive jobs across Finder and startup controllers, while
            # leaving unrelated render keys free to run in parallel.
            lock = dotnet_preview_package_cache_build_lock(self.cache_root / "character_finder", key)
            announced_package = False
            while not lock.acquire(timeout=0.05):
                self._check()
                if not announced_package:
                    ready = cached_character_package(self.cache_root, key)
                    if ready is not None:
                        # A matching job may still be capturing its image. Its
                        # completed 3D package is already usable by the selection.
                        self.package_ready.emit(self.token, ready)
                        announced_package = True
            try:
                self._check()
                self._render_or_reuse(key)
            finally:
                lock.release()
        except RunCancelled:
            pass
        except Exception as error:
            if not self._stop.is_set():
                self.failed.emit(self.token, str(error))
        finally:
            self.finished.emit()

    def _render_or_reuse(self, key):
        cached = cached_character_render(self.cache_root, key)
        if cached:
            self._remember_thumbnail(cached)
            self.package_ready.emit(self.token, cached)
            self.completed.emit(self.token, cached)
            return
        result = cached_character_package(self.cache_root, key)
        if result is not None:
            package = rust_preview_package_from_path(result.package_path)
        elif self._cache_only:
            self.cache_missed.emit(self.token)
            return
        else:
            package, status, notes = self._build_package(key)
            result = CharacterRenderResult(key, str(package.package_dir), "", status, notes)
            # Publish the finished 3D package separately from the image. A
            # cancelled/failed capture must not discard expensive model work.
            self._write_metadata(self.cache_root / "character_finder" / "thumbnails" / (key + ".package.json"), result)
        lease = acquire_dotnet_preview_package_cache_lease_for_path(package.package_dir)
        try:
            self._check()
            self.package_ready.emit(self.token, result)
            image_path = self._capture(package, key)
            self._check()
            result = replace(result, thumbnail_path=str(image_path))
            self._write_metadata(image_path.with_suffix(".json"), result)
            self._remember_thumbnail(result)
            self.completed.emit(self.token, result)
        finally:
            if lease is not None:
                lease.release()

    def _write_metadata(self, metadata, result):
        metadata.parent.mkdir(parents=True, exist_ok=True)
        temporary = metadata.with_name(metadata.name + f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps({**asdict(result), "capture": self._capture_report}, ensure_ascii=False), encoding="utf-8")
            self._check()
            os.replace(temporary, metadata)
        finally:
            temporary.unlink(missing_ok=True)

    def _remember_thumbnail(self, result):
        self._check()
        remember_character_thumbnail(character_row_cache_root(self.cache_root, self.fingerprint, self.settings),
                                     self.inputs.detail.row.key, result)

    def _build_package(self, key: str):
        if not self.inputs.dependencies_complete:
            raise ValueError("Character preview dependencies are incomplete. Inspect the selected model's files and resolution evidence.")
        from cdmw.core.archive import build_archive_entry_path_index, build_archive_entry_basename_index, read_archive_entry_data
        from cdmw.core.archive_mesh_appearance import apply_archive_mesh_appearance
        from cdmw.modding.mesh_parser import parse_mesh
        from cdmw.rendering.native_preview_core import run_native_preview_core_preview_job
        from cdmw.services.mesh_rust_preview_cache import build_or_lookup_rust_preview_package
        from cdmw.services.preview_material_status import native_preview_missing_texture_reason
        from cdmw.workers.archive_preview_native import _native_presentation_geometry_payload, native_preview_model_property_indices
        from cdmw.rendering.dotnet_preview_package_cache import dotnet_preview_package_cache_budget

        detail = self.inputs.detail
        entries = self.inputs.entries
        paths = build_archive_entry_path_index(entries)
        basenames = build_archive_entry_basename_index(entries)
        source = self.inputs.entries_by_id[detail.models[0].entry_id]
        source_component = next((c for c in detail.components if detail.models[0].entry_id in c.model_entry_ids), None)
        def presentation_geometry(entry, component, scale=1.0):
            self._check()
            if entry.extension != ".pac" and scale == 1.0:
                return b"", "", ()
            descriptor = self._authored_descriptor(component)
            data = read_archive_entry_data(entry, stop_event=self._stop)[0]
            parsed = parse_mesh(data, entry.path)
            presentation, notes = apply_archive_mesh_appearance(entry, parsed, data,
                archive_entries_by_normalized_path=paths, archive_entries_by_basename=basenames,
                context_entries=entries, stop_event=self._stop, authored_descriptor=descriptor)
            source_path = str(getattr(presentation, "_cdmw_skeleton_variation_source", "") or "")
            if scale != 1.0:
                presentation = replace(presentation, submeshes=[replace(mesh,
                    vertices=[tuple(float(v) * scale for v in point) for point in mesh.vertices]) for mesh in presentation.submeshes])
                source_path = (source_path + "; " if source_path else "") + f"authored scale {scale}"
            payload = _native_presentation_geometry_payload(presentation, self._stop) if source_path else b""
            return payload, source_path, notes

        components = []
        notes = ()
        seen = {source.path.casefold()}
        combined_body = detail.row.embedded_face and detail.row.role in {"body", "whole_character"}
        for component in detail.components:
            # A PAC can already contain the character's head. Adding the separately
            # authored face prefab would superimpose two independently scaled heads.
            if combined_body and component.role not in {"body", "whole_character"}:
                continue
            for model_id in component.model_entry_ids:
                entry = self.inputs.entries_by_id.get(model_id)
                if entry is None or entry.path.casefold() in seen:
                    continue
                seen.add(entry.path.casefold())
                slot = "body" if component.role in {"body", "whole_character"} else "hair" if component.role == "hair" else "face"
                payload, presentation_source, component_notes = presentation_geometry(entry, component)
                notes = (*notes, *component_notes)
                components.append(NativePreviewContextComponent(entry, slot, component.name, "authored",
                    component.scale, detail.appearance_path, entries, self.inputs.dependencies_complete,
                    presentation_geometry_payload=payload, presentation_geometry_source=presentation_source))
        if combined_body:
            notes = (*notes, "Combined body/head preview. Separate facial components remain available in Faces; replacing the embedded head requires customization support.")
        self._check()
        source_scale = source_component.scale if source_component else 1.0
        # The primary model is separate from native context components. Apply its
        # supported PABC deformation and authored scale through the same immutable
        # presentation-geometry ABI, avoiding a duplicate primary mesh.
        payload, presentation_source, source_notes = presentation_geometry(source, source_component, source_scale)
        notes = tuple(dict.fromkeys((*notes, *source_notes)))
        authored_stems = [c.name.casefold() for c in detail.components]
        ordered_entries = tuple(sorted(entries, key=lambda e: authored_stems.index(Path(e.path).stem.casefold())
            if e.extension == ".prefab" and Path(e.path).stem.casefold() in authored_stems else len(authored_stems)))
        indices = native_preview_model_property_indices(ordered_entries, self._stop)

        def run(settings, output_root):
            # A job must not prune DDS files another native decoder is still
            # preparing. These scratch inputs live until the Rust package owns
            # its immutable copies, then leave with this job's staging directory.
            return run_native_preview_core_preview_job(source, cache_root=output_root.parent / "native-cache",
                render_settings=settings, dependency_entries=ordered_entries,
                dependency_entries_complete=self.inputs.dependencies_complete, preview_context_components=components,
                model_property_indices=indices, package_root=None, timeout_seconds=45.0, stop_event=self._stop,
                presentation_geometry_payload=payload, presentation_geometry_source=presentation_source,
                output_root=output_root, use_service=False)
        # This finder owns each native process and its staging directory. Cancellation
        # waits for that process to exit before the directory or next job is touched.
        stage_root = self.cache_root / "character_finder" / "staging"
        stage_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="native-", dir=stage_root) as stage_text:
            attempt = run(self.settings, Path(stage_text) / "textured")
            self._check()
            if not attempt.succeeded:
                raise RuntimeError(attempt.fallback_reason or "The native preview could not decode this model.")
            missing = native_preview_missing_texture_reason(attempt.package_path)
            status = "base_appearance"
            if missing:
                notes = (*notes, missing)
                status = "textures_unavailable"
                attempt = run(replace(self.settings, use_textures_by_default=False), Path(stage_text) / "geometry")
                self._check()
                if not attempt.succeeded:
                    raise RuntimeError(attempt.fallback_reason or "The geometry preview could not be prepared.")
            # Multi-page lookahead needs room to retain the models it prepares.
            # Reuse the existing 2 GiB policy rather than the 512 MiB default.
            maximum, target = dotnet_preview_package_cache_budget("aggressive")
            package = build_or_lookup_rust_preview_package(attempt.package_path, cache_root=self.cache_root,
                archive_identity=key, cache_mode="aggressive", max_bytes=maximum, target_bytes=target,
                cancelled=self._stop.is_set,
                metadata={"entry_path": source.path, "character_catalogue_key": detail.row.key})
        return package, status, tuple(notes)

    def _authored_descriptor(self, component):
        if component is None:
            return None
        name = Path(component.name.replace("\\", "/")).stem.casefold()
        descriptors = [entry for entry_id in component.context_entry_ids
            if (entry := self.inputs.entries_by_id.get(entry_id)) is not None
            and Path(entry.path).name.casefold() in {name + ".prefabdata_xml", name + ".prefabdata.xml"}]
        if len(descriptors) > 1:
            raise ValueError(f"More than one authored appearance descriptor was resolved for {component.name}.")
        return descriptors[0] if descriptors else None

    def _capture(self, package, key: str) -> Path:
        resolution = resolve_rust_mesh_editor()
        if not resolution.resolved_path:
            raise RuntimeError("The Rust preview helper is unavailable. Rebuild the helper or use a current CDMW build.")
        # The renderer requires captures outside its immutable session directory.
        # Only this job's temporary directory is removed after its process exits.
        capture_root = self.cache_root / "character_finder" / "captures"
        capture_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="finder-", dir=capture_root) as stage_text:
            stage = Path(stage_text)
            capture = stage / "preview.bmp"
            report = stage / "report.json"
            # Use the renderer's shared startup view, as the interactive host does.
            # Near-zero yaw points at the back of character heads.
            args = [str(resolution.resolved_path), "--capture-cdmw-preview-session", str(package.manifest_path),
                    "--capture-output", str(capture), "--capture-report-json", str(report), "--capture-size", "256"]
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 45
            try:
                while True:
                    self._check()
                    if time.monotonic() > deadline:
                        raise TimeoutError("Character thumbnail capture timed out.")
                    try:
                        stdout, stderr = process.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                if process.returncode != 0:
                    raise RuntimeError((stderr or stdout)[-2000:].decode("utf-8", "replace"))
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.communicate(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=3.0)
            self._check()
            if report.is_file() and report.stat().st_size <= 48 * 1024:
                self._capture_report = json.loads(report.read_text(encoding="utf-8"))
            image = QImage(str(capture))
            if image.isNull():
                raise RuntimeError("The renderer did not publish a readable thumbnail.")
            target = self.cache_root / "character_finder" / "thumbnails" / (key + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + f".{uuid4().hex}.tmp")
            try:
                if not image.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation).save(str(temporary), "PNG"):
                    raise RuntimeError("The thumbnail could not be saved.")
                self._check()
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return target
