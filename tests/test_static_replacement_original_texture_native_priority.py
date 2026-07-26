from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_dialog_callbacks_texture_original_texture_material_part_01 import (
    _texture_original_texture_material_step_009,
)


class _PreviewModel:
    def __init__(self, name: str) -> None:
        self.name = name
        self.meshes = [SimpleNamespace(name=name)]


class _Signal:
    def connect(self, *_args: object, **_kwargs: object) -> None:
        return None


class _Thread:
    def __init__(self, _parent: object = None) -> None:
        self.started = _Signal()

    def start(self) -> None:
        return None

    def quit(self) -> None:
        return None


class _TextValue:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def text(self) -> str:
        return self.value


def _captured_original_texture_resolver(*, native_batches: int) -> tuple[object, dict[str, int]]:
    captured: dict[str, object] = {}
    calls = {
        "native": 0,
        "native_textures": 0,
        "python_preview": 0,
        "lookup": 0,
        "images": 0,
        "paths": 0,
    }

    class _Worker:
        def __init__(self, _request_id: int, resolver: object) -> None:
            captured["resolver"] = resolver
            self.completed = _Signal()
            self.error = _Signal()
            self.finished = _Signal()

        def moveToThread(self, _thread: object) -> None:
            return None

        def run(self) -> None:
            return None

        def deleteLater(self) -> None:
            return None

    def clone(model: _PreviewModel) -> _PreviewModel:
        return _PreviewModel(f"{model.name}-clone")

    def native_manifest(
        _model: object,
        _package_root: str,
        render_settings: object | None = None,
    ) -> int:
        calls["native"] += 1
        calls["native_textures"] += int(
            bool(getattr(render_settings, "use_textures_by_default", False))
        )
        return native_batches

    def build_python_preview(*_args: object, **_kwargs: object) -> object:
        calls["python_preview"] += 1
        return SimpleNamespace(preview_model=_PreviewModel("python"))

    def texture_lookup() -> tuple[dict[str, object], dict[str, object]]:
        calls["lookup"] += 1
        return {}, {}

    def attach_paths(*_args: object, **_kwargs: object) -> None:
        calls["paths"] += 1

    def attach_images(_model: object) -> None:
        calls["images"] += 1

    load_state = SimpleNamespace(
        should_start=True,
        progress_message="Loading",
        detail="Loading",
        performance=SimpleNamespace(summary="Loading", details="Loading"),
        outcome="started",
    )
    owner = SimpleNamespace(
        texconv_path_edit=_TextValue(),
        archive_package_root_edit=_TextValue("D:/cache"),
        archive_entries_by_normalized_path={},
        archive_entries_by_basename={},
        archive_sidecar_entries_by_texture_path={},
        archive_sidecar_entries_by_texture_basename={},
        _find_archive_preview_companion_entry=lambda _entry: None,
        _archive_preview_support_texture_slots=lambda _settings: (),
        _attach_archive_model_preview_images=attach_images,
    )
    state = SimpleNamespace(
        original_reference_texture_preview_state={},
        original_reference_preview_model=_PreviewModel("original"),
        _original_reference_texture_preview_load_start_state_helper=lambda *_args, **_kwargs: load_state,
        _set_alignment_d3d11_progress=lambda *_args, **_kwargs: None,
        _set_preview_performance_status=lambda *_args, **_kwargs: None,
        self=owner,
        Path=Path,
        _current_preview_render_settings=lambda: SimpleNamespace(visible_texture_mode="mesh_base_first"),
        _normalize_model_visible_texture_mode=lambda value: value,
        _current_archive_original_preview_model=lambda: None,
        entry=SimpleNamespace(path="character.pac"),
        ModelPreviewData=_PreviewModel,
        build_archive_preview_result=build_python_preview,
        _clone_preview_model=clone,
        _load_native_preview_core_material_manifest_for_alignment=native_manifest,
        _alignment_texture_lookup_indexes=texture_lookup,
        _attach_model_texture_preview_paths=attach_paths,
        _attach_model_sidecar_texture_preview_paths=attach_paths,
        _attach_model_support_texture_preview_paths=attach_paths,
        original_mesh_for_mapping=None,
        sidecar_bindings=(),
        sidecar_texts_by_normalized_path={},
        sidecar_texts_by_basename={},
        RunCancelled=RuntimeError,
        _stop_original_reference_texture_worker=lambda: None,
        _alignment_d3d11_next_original_texture_worker_request_id_helper=lambda _state: 1,
        alignment_d3d11_state={},
        AlignmentOriginalTexturePreviewWorker=_Worker,
        QThread=_Thread,
        dialog=None,
        Qt=SimpleNamespace(QueuedConnection=object()),
        original_texture_worker_receiver=SimpleNamespace(
            handle_completed=lambda *_args: None,
            handle_error=lambda *_args: None,
            watch_thread=lambda *_args: None,
        ),
        _cleanup_original_reference_texture_worker_refs=lambda *_args, **_kwargs: None,
        _alignment_d3d11_record_original_texture_worker_refs_helper=lambda *_args, **_kwargs: None,
    )
    _texture_original_texture_material_step_009(state)
    state._load_original_reference_texture_preview()
    return captured["resolver"], calls


def test_native_manifest_success_skips_python_texture_preparation() -> None:
    resolver, calls = _captured_original_texture_resolver(native_batches=3)

    preview_model, batches = resolver(threading.Event())

    assert batches == 3
    assert preview_model.name == "original-clone"
    assert calls == {
        "native": 1,
        "native_textures": 1,
        "python_preview": 0,
        "lookup": 0,
        "images": 0,
        "paths": 0,
    }


def test_native_manifest_unavailable_runs_existing_python_fallback_once() -> None:
    resolver, calls = _captured_original_texture_resolver(native_batches=0)

    preview_model, batches = resolver(threading.Event())

    assert batches == 0
    assert preview_model.name == "python-clone"
    assert calls == {
        "native": 1,
        "native_textures": 1,
        "python_preview": 1,
        "lookup": 1,
        "images": 1,
        "paths": 0,
    }
