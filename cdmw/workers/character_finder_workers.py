"""Cancellable production Rust preview and serial 256px thumbnail jobs."""

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

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage

from cdmw.domain.character_finder import CharacterPreviewInputs, CharacterRenderResult, character_preview_detail
from cdmw.domain.character_context import NativePreviewContextComponent
from cdmw.models import ModelPreviewRenderSettings, RunCancelled
from cdmw.services.mesh_rust_contract import RUST_MESH_RENDERER, RUST_PREVIEW_BACKEND, resolve_rust_mesh_editor
from cdmw.services.mesh_rust_preview_cache import RUST_PREVIEW_CACHE_SCHEMA


def character_render_key(detail, fingerprint: str, settings: ModelPreviewRenderSettings) -> str:
    detail = character_preview_detail(detail)
    identity = {"row": detail.row.key, "context": detail.context_key}
    if detail.row.embedded_face and detail.components and all(c.role in {"body", "whole_character"} for c in detail.components):
        # Labels/ownership do not change a combined body's rendered base appearance.
        # Keep authored scale, prefab, PABC/material dependencies and primary order.
        identity = {"combined_body": [asdict(c) for c in detail.components],
                    "models": [m.entry_id for m in detail.models], "files": [asdict(f) for f in detail.files]}
    context = {"schema": 4, "fingerprint": fingerprint, "identity": identity,
               "renderer": RUST_MESH_RENDERER, "backend": RUST_PREVIEW_BACKEND,
               "package_schema": RUST_PREVIEW_CACHE_SCHEMA,
               "camera": "renderer-front-v2",
               "settings": asdict(settings)}
    return sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()


def cached_character_render(cache_root: Path, key: str) -> CharacterRenderResult | None:
    path = cache_root / "character_finder" / "thumbnails" / (key + ".json")
    try:
        if path.stat().st_size > 64 * 1024:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        image = path.with_suffix(".png")
        package = Path(value["package_path"])
        if not image.is_file() or not (package / "manifest.json").is_file() or value["key"] != key:
            return None
        return CharacterRenderResult(key, str(package), str(image), value["status"], tuple(value["notes"]), True)
    except (OSError, ValueError, KeyError, TypeError):
        return None


class CharacterFinderRenderWorker(QObject):
    package_ready = Signal(int, object)
    completed = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, token: int, inputs: CharacterPreviewInputs, *, cache_root: Path,
                 fingerprint: str, settings: ModelPreviewRenderSettings) -> None:
        super().__init__()
        self.token = token
        self.inputs = inputs
        self.cache_root = cache_root
        self.fingerprint = fingerprint
        self.settings = replace(settings, use_textures_by_default=True)
        self._stop = threading.Event()
        self._capture_report = {}

    def stop(self) -> None:
        self._stop.set()

    def _check(self) -> None:
        if self._stop.is_set():
            raise RunCancelled("Character preview cancelled.")

    def run(self) -> None:
        try:
            self._check()
            key = character_render_key(self.inputs.detail, self.fingerprint, self.settings)
            cached = cached_character_render(self.cache_root, key)
            if cached:
                self.package_ready.emit(self.token, cached)
                self.completed.emit(self.token, cached)
                return
            package, status, notes = self._build_package(key)
            result = CharacterRenderResult(key, str(package.package_dir), "", status, notes)
            self._check()
            self.package_ready.emit(self.token, result)
            image_path = self._capture(package, key)
            self._check()
            result = replace(result, thumbnail_path=str(image_path))
            metadata = image_path.with_suffix(".json")
            temporary = metadata.with_suffix(".json.tmp")
            try:
                temporary.write_text(json.dumps({**asdict(result), "capture": self._capture_report}, ensure_ascii=False), encoding="utf-8")
                self._check()
                os.replace(temporary, metadata)
            finally:
                temporary.unlink(missing_ok=True)
            self.completed.emit(self.token, result)
        except RunCancelled:
            pass
        except Exception as error:
            if not self._stop.is_set():
                self.failed.emit(self.token, str(error))
        finally:
            self.finished.emit()

    def _build_package(self, key: str):
        from cdmw.core.archive import build_archive_entry_path_index, build_archive_entry_basename_index, read_archive_entry_data
        from cdmw.core.archive_mesh_appearance import apply_archive_mesh_appearance_for_preview
        from cdmw.modding.mesh_parser import parse_mesh
        from cdmw.rendering.native_preview_core import run_native_preview_core_preview_job
        from cdmw.services.mesh_rust_preview_cache import build_or_lookup_rust_preview_package
        from cdmw.services.preview_material_status import native_preview_missing_texture_reason
        from cdmw.workers.archive_preview_native import _native_presentation_geometry_payload, native_preview_model_property_indices
        from cdmw.workers.character_context_workers import prepare_character_context_presentation_components
        from cdmw.rendering.dotnet_preview_package_cache import dotnet_preview_package_cache_budget

        detail = self.inputs.detail
        entries = self.inputs.entries
        paths = build_archive_entry_path_index(entries)
        basenames = build_archive_entry_basename_index(entries)
        source = self.inputs.entries_by_id[detail.models[0].entry_id]
        source_component = next((c for c in detail.components if detail.models[0].entry_id in c.model_entry_ids), None)
        components = []
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
                components.append(NativePreviewContextComponent(entry, slot, component.name, "authored",
                    component.scale, detail.appearance_path, entries, self.inputs.dependencies_complete))
        components, notes = prepare_character_context_presentation_components(components, path_index=paths,
            basename_index=basenames, context_entries=entries, stop_event=self._stop)
        if combined_body:
            notes = (*notes, "Combined body/head preview. Separate facial components remain available in Faces; replacing the embedded head requires customization support.")
        self._check()
        payload = b""
        presentation_source = ""
        source_scale = source_component.scale if source_component else 1.0
        # The primary model is separate from native context components. Apply its
        # supported PABC deformation and authored scale through the same immutable
        # presentation-geometry ABI, avoiding a duplicate primary mesh.
        if source.extension == ".pac" or source_scale != 1.0:
            data = read_archive_entry_data(source, stop_event=self._stop)[0]
            parsed = parse_mesh(data, source.path)
            presentation, source_notes = apply_archive_mesh_appearance_for_preview(source, parsed, data, paths, basenames, entries, self._stop)
            notes = tuple(dict.fromkeys((*notes, *source_notes)))
            presentation_source = str(getattr(presentation, "_cdmw_skeleton_variation_source", "") or "")
            if source_scale != 1.0:
                presentation = replace(presentation, submeshes=[replace(mesh,
                    vertices=[tuple(float(v) * source_scale for v in point) for point in mesh.vertices]) for mesh in presentation.submeshes])
                presentation_source = (presentation_source + "; " if presentation_source else "") + f"authored scale {source_scale}"
            if presentation_source:
                payload = _native_presentation_geometry_payload(presentation, self._stop)
        authored_stems = [c.name.casefold() for c in detail.components]
        ordered_entries = tuple(sorted(entries, key=lambda e: authored_stems.index(Path(e.path).stem.casefold())
            if e.extension == ".prefab" and Path(e.path).stem.casefold() in authored_stems else len(authored_stems)))
        indices = native_preview_model_property_indices(ordered_entries, self._stop)

        def run(settings, output_root):
            return run_native_preview_core_preview_job(source, cache_root=self.cache_root / "character_finder" / "native",
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
            maximum, target = dotnet_preview_package_cache_budget("balanced")
            package = build_or_lookup_rust_preview_package(attempt.package_path, cache_root=self.cache_root,
                archive_identity=key, cache_mode="balanced", max_bytes=maximum, target_bytes=target,
                cancelled=self._stop.is_set,
                metadata={"entry_path": source.path, "character_catalogue_key": detail.row.key})
        return package, status, tuple(notes)

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
                    "--capture-output", str(capture), "--capture-report-json", str(report)]
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
            temporary = target.with_suffix(".png.tmp")
            try:
                if not image.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation).save(str(temporary), "PNG"):
                    raise RuntimeError("The thumbnail could not be saved.")
                self._check()
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return target
