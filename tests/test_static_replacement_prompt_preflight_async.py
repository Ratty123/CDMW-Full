from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.models import ArchiveEntry, ModelPreviewData, RunCancelled
from cdmw.modding.asset_replacement import ReplacementAssetProfile
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.scene_importer import SceneImportResult
from cdmw.ui.archive_browser import static_replacement_prompt_preflight as preflight
from cdmw.ui.archive_browser import static_replacement_dialog_prompt as prompt_module


def _entry() -> ArchiveEntry:
    return ArchiveEntry("character/test.pac", Path("0.pamt"), Path("0.paz"), 4, 8, 8, 0, 0)


def _profile() -> ReplacementAssetProfile:
    return ReplacementAssetProfile(
        source_path="character/test.pac",
        mesh_format="pac",
        category_hint="object",
        asset_family="character",
        support_level="Supported",
        replacement_support="Supported",
        export_supported=True,
        geometry_mode="static",
        lod_mode="selected",
        sidecar_mode="preserve",
    )


def _result(request_id: int) -> preflight.StaticReplacementPromptPreflightResult:
    mesh = ParsedMesh(path="source.obj")
    scene = SceneImportResult(mesh=mesh)
    preview = ModelPreviewData(path="source.obj")
    return preflight.StaticReplacementPromptPreflightResult(
        request_id=request_id,
        scene_import_result=scene,
        original_mesh=mesh,
        replacement_mesh_base=mesh,
        replacement_mesh=mesh,
        original_preview_model=preview,
        replacement_preview_model=preview,
        asset_profile=_profile(),
        suggested_mappings=(),
        texture_files=(),
        auto_texture_sources=(),
        texture_sets={},
        texture_entries_by_normalized_path={},
        texture_entries_by_basename={},
        sidecar_bindings=(),
        sidecar_text_values=(),
        sidecar_texts_by_normalized_path={},
        sidecar_texts_by_basename={},
        modify_original_clone_mode=False,
        scene_flip_v=False,
        placement_fit=None,
        source_bounds=None,
        reference_bounds=None,
        texture_lookup_source="global_indexes",
        texture_lookup_dds_count=0,
        texture_lookup_sidecar_count=0,
        texture_lookup_reference_count=0,
    )


class _Owner:
    def __init__(self) -> None:
        self.archive_entries_by_normalized_path: dict[str, tuple[ArchiveEntry, ...]] = {}
        self.archive_entries_by_basename: dict[str, tuple[ArchiveEntry, ...]] = {}
        self.archive_entries_by_extension: dict[str, tuple[ArchiveEntry, ...]] = {}
        self._static_replacement_prompt_preflight_request_id = 0
        self._shutting_down = False
        self.worker_kwargs: list[dict[str, object]] = []
        self.threads: list[threading.Thread] = []
        self.stop_events: list[threading.Event] = []
        self.statuses: list[tuple[str, bool]] = []

    def _run_utility_task_when_idle(self, **kwargs: object) -> None:
        self.worker_kwargs.append(dict(kwargs))
        stop_event = threading.Event()
        self.stop_events.append(stop_event)

        def run() -> None:
            try:
                task = kwargs["task"]
                payload = task(  # type: ignore[operator]
                    lambda _message: None,
                    lambda _current, _total, _detail: None,
                    stop_event,
                )
            except Exception as exc:
                callback = kwargs.get("on_error")
                if callable(callback):
                    callback(str(exc))
            else:
                callback = kwargs.get("on_complete")
                if callable(callback):
                    callback(payload)

        thread = threading.Thread(target=run)
        self.threads.append(thread)
        thread.start()

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.statuses.append((message, error))


def _wait(thread: threading.Thread) -> None:
    thread.join(5.0)
    assert not thread.is_alive()


def test_static_prompt_preflight_dispatch_is_under_50ms_with_slow_io() -> None:
    owner = _Owner()
    completed: list[preflight.StaticReplacementPromptPreflightResult] = []

    def slow_prepare(request: preflight.StaticReplacementPromptPreflightRequest, **_kwargs: object):
        time.sleep(0.2)
        return _result(request.request_id)

    with patch.object(preflight, "prepare_static_replacement_prompt_preflight", side_effect=slow_prepare):
        started = time.perf_counter()
        preflight.dispatch_static_replacement_prompt_preflight(
            owner,
            _entry(),
            Path("source.obj"),
            supplemental_files=(),
            scene_import_result=None,
            original_mesh=None,
            on_complete=completed.append,
        )
        elapsed = time.perf_counter() - started
        _wait(owner.threads[0])

    assert elapsed < 0.05
    assert completed and completed[0].request_id == 1
    assert owner.worker_kwargs[0]["task_accepts_progress"] is True
    assert owner.worker_kwargs[0]["task_accepts_cancel"] is True


def test_public_static_prompt_handler_only_dispatches() -> None:
    owner = _Owner()
    owner._modeless_alignment_dialog_key = lambda *_args: "prompt-key"  # type: ignore[attr-defined]
    owner._activate_modeless_alignment_dialog = lambda _key: False  # type: ignore[attr-defined]
    dispatched: list[dict[str, object]] = []

    def capture_dispatch(*_args: object, **kwargs: object) -> int:
        dispatched.append(kwargs)
        return 1

    with patch.object(prompt_module, "dispatch_static_replacement_prompt_preflight", side_effect=capture_dispatch):
        started = time.perf_counter()
        prompt_module.prompt_archive_static_replacement_options(
            owner,
            _entry(),
            Path("source.obj"),
            dialog_title="Mesh Replacement Builder",
        )
        elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert len(dispatched) == 1
    assert callable(dispatched[0]["on_complete"])


def test_static_prompt_preflight_latest_request_wins() -> None:
    owner = _Owner()
    first_release = threading.Event()
    completed: list[int] = []

    def prepare(request: preflight.StaticReplacementPromptPreflightRequest, **_kwargs: object):
        if request.request_id == 1:
            first_release.wait(2.0)
        return _result(request.request_id)

    with patch.object(preflight, "prepare_static_replacement_prompt_preflight", side_effect=prepare):
        for name in ("first.obj", "second.obj"):
            preflight.dispatch_static_replacement_prompt_preflight(
                owner,
                _entry(),
                Path(name),
                supplemental_files=(),
                scene_import_result=None,
                original_mesh=None,
                on_complete=lambda result: completed.append(result.request_id),
            )
        _wait(owner.threads[1])
        first_release.set()
        _wait(owner.threads[0])

    assert completed == [2]


def test_static_prompt_preflight_cancel_does_not_publish_or_warn() -> None:
    owner = _Owner()
    started = threading.Event()
    completed: list[object] = []

    def cancellable_prepare(
        _request: preflight.StaticReplacementPromptPreflightRequest,
        *,
        stop_event: threading.Event,
        **_kwargs: object,
    ) -> object:
        started.set()
        while not stop_event.wait(0.005):
            pass
        raise RunCancelled("Static replacement preflight cancelled.")

    with patch.object(preflight, "prepare_static_replacement_prompt_preflight", side_effect=cancellable_prepare):
        preflight.dispatch_static_replacement_prompt_preflight(
            owner,
            _entry(),
            Path("source.obj"),
            supplemental_files=(),
            scene_import_result=None,
            original_mesh=None,
            on_complete=completed.append,
        )
        assert started.wait(1.0)
        owner.stop_events[0].set()
        _wait(owner.threads[0])

    assert completed == []
    assert owner.statuses == []


def test_static_prompt_preflight_honors_pre_cancel() -> None:
    stop_event = threading.Event()
    stop_event.set()
    request = preflight.StaticReplacementPromptPreflightRequest(
        1,
        _entry(),
        Path("source.obj"),
        (),
        None,
        None,
        {},
        {},
        {},
    )
    with pytest.raises(RunCancelled):
        preflight.prepare_static_replacement_prompt_preflight(request, stop_event=stop_event)


def test_million_vertex_preflight_keeps_heartbeat_below_200ms() -> None:
    owner = _Owner()
    entry = _entry()
    owner.archive_entries_by_normalized_path = {entry.path.casefold(): (entry,)}
    owner.archive_entries_by_basename = {"test.pac": (entry,)}
    vertex = (0.0, 0.0, 0.0)
    mesh = ParsedMesh(
        path="source.obj",
        format="obj",
        submeshes=[SubMesh(name="body", vertices=[vertex] * 1_000_000)],
        total_vertices=1_000_000,
    )
    scene = SceneImportResult(mesh=mesh)
    completed: list[object] = []

    with (
        patch.object(preflight, "_extract_archive_model_sidecar_texture_references", return_value=((), (), {}, {})),
        patch.object(preflight, "analyze_replacement_asset", return_value=_profile()),
        patch.object(preflight, "clone_mesh_for_static_replacement_native_first", side_effect=lambda value, *_a, **_k: value),
        patch.object(preflight, "parsed_mesh_to_preview_model", return_value=ModelPreviewData(path="source.obj")),
        patch.object(preflight, "attach_scene_preview_textures"),
        patch.object(preflight, "suggest_static_submesh_mappings", return_value=[]),
        patch.object(preflight, "discover_scene_texture_files", return_value=()),
        patch.object(preflight, "group_replacement_texture_sets", return_value={}),
    ):
        preflight.dispatch_static_replacement_prompt_preflight(
            owner,
            entry,
            Path("source.obj"),
            supplemental_files=(),
            scene_import_result=scene,
            original_mesh=mesh,
            on_complete=completed.append,
        )
        last_heartbeat = time.perf_counter()
        max_gap = 0.0
        while owner.threads[0].is_alive():
            now = time.perf_counter()
            max_gap = max(max_gap, now - last_heartbeat)
            last_heartbeat = now
            time.sleep(0.005)
        _wait(owner.threads[0])

    assert completed
    assert max_gap < 0.2


def test_prompt_construction_contains_no_fallback_io_or_nested_event_pump() -> None:
    prompt = Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt.py").read_text(encoding="utf-8")
    shell = Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_shell.py").read_text(encoding="utf-8")
    setup = Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup.py").read_text(encoding="utf-8")
    setup_body = shell + setup

    assert prompt.index("dispatch_static_replacement_prompt_preflight(") < prompt.index(
        "create_static_replacement_prompt_shell(prompt_shell_context)"
    )
    for forbidden in (
        "read_archive_entry_baseline_data(",
        "read_archive_entry_data(",
        "parse_mesh(",
        "analyze_replacement_asset(",
        "import_scene_mesh(",
        "clone_mesh_for_static_replacement_native_first(",
        "suggest_static_submesh_mappings(",
        "discover_scene_texture_files(",
        "QApplication.processEvents()",
    ):
        assert forbidden not in setup_body
