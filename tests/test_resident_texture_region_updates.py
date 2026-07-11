from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.models import TextureEditorDocument, TextureEditorLayer, TextureEditorSourceBinding, TextureEditorToolSettings
from cdmw.ui.mesh_editor.resident_texture_update_queue import (
    ResidentTextureRegionRequest,
    ResidentTextureRegionUpdateQueue,
)
from cdmw.ui.texture_editor_tab import TextureEditorTab
from cdmw.ui.texture_workflow.editor_export_state import (
    texture_editor_handoff_source_binding,
    texture_editor_native_dds_action_text,
)
from cdmw.ui.texture_workflow.editor_resident_texture import (
    TextureEditorCompositeLease,
    build_texture_editor_resident_patch,
)
from cdmw.ui.texture_workflow.editor_view_state import texture_editor_composite_render_state


def _wait_for(app: QApplication, predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


class _CountingCompositeLease:
    def __init__(self, rgba: np.ndarray) -> None:
        self._lease = TextureEditorCompositeLease(rgba)
        self.release_count = 0

    def release(self) -> None:
        self.release_count += 1
        self._lease.release()


def _request(
    original: np.ndarray,
    *,
    rect: tuple[int, int, int, int],
    color: tuple[int, int, int, int],
    service: object | None = None,
    current: np.ndarray | None = None,
    output_root: Path | None = None,
    resource_id: str = "texture:body",
    composite_lease: object | None = None,
) -> ResidentTextureRegionRequest:
    x, y, width, height = rect
    row = bytes(color) * width
    current_rgba = original.copy() if current is None else current
    if current is None:
        current_rgba[y : y + height, x : x + width] = [color[2], color[1], color[0], color[3]]
    return ResidentTextureRegionRequest(
        session_id="session",
        edit_revision=7,
        document_texture_revision=9,
        resource_id=resource_id,
        channel="base",
        affected_submeshes=(0,),
        texture_width=int(original.shape[1]),
        texture_height=int(original.shape[0]),
        rect=rect,
        row_pitch=width * 4,
        bgra=row * height,
        current_rgba=current_rgba,
        composite_lease=(
            composite_lease if composite_lease is not None else TextureEditorCompositeLease(current_rgba)
        ),
        logical_path="character/body.dds",
        mesh_service=service,
        output_root=output_root,
    )


def test_resident_patch_builder_emits_tight_bgra_region() -> None:
    rgba = np.zeros((3, 4, 4), dtype=np.uint8)
    rgba[1:3, 1:3] = [10, 20, 30, 40]
    binding = TextureEditorSourceBinding(launch_origin="mesh_editor", mesh_channel="base")

    patch = build_texture_editor_resident_patch(
        binding,
        rgba,
        texture_revision=12,
        dirty_bounds=(1, 1, 2, 2),
    )

    assert patch.rect == (1, 1, 2, 2)
    assert patch.row_pitch == 8
    assert patch.bgra == bytes([30, 20, 10, 40]) * 4
    assert patch.texture_revision == 12
    assert not rgba.flags.writeable
    second_lease = TextureEditorCompositeLease(rgba)
    patch.composite_lease.release()
    assert not rgba.flags.writeable
    second_lease.release()
    assert rgba.flags.writeable


def test_mesh_dds_handoff_distinguishes_preview_from_assignment() -> None:
    binding = TextureEditorSourceBinding(
        launch_origin="mesh_editor",
        mesh_session_id="mesh-session",
        mesh_resource_id="body_base",
        mesh_submesh_indices=(2, 4),
        mesh_channel="base",
    )
    document = TextureEditorDocument("Linked", 4, 4, source_binding=binding)

    preview = texture_editor_handoff_source_binding(document, mesh_commit_mode="preview")
    assignment = texture_editor_handoff_source_binding(document, mesh_commit_mode="assign")

    assert preview.mesh_commit_mode == "preview"
    assert assignment.mesh_commit_mode == "assign"
    assert assignment.mesh_submesh_indices == (2, 4)
    assert binding.mesh_commit_mode == ""
    assert texture_editor_native_dds_action_text(document) == "Assign DDS..."
    assert texture_editor_native_dds_action_text(TextureEditorDocument("Plain", 4, 4)) == "Export DDS..."


def test_read_only_emitted_composite_uses_copy_on_write_for_next_dirty_edit() -> None:
    layer = TextureEditorLayer("base", "Base", "", revision=1)
    document = TextureEditorDocument(
        "COW",
        3,
        2,
        active_layer_id="base",
        layers=(layer,),
        source_binding=TextureEditorSourceBinding(launch_origin="mesh_editor", mesh_channel="base"),
    )
    pixels = np.zeros((2, 3, 4), dtype=np.uint8)
    pixels[..., 3] = 255
    initial = texture_editor_composite_render_state(
        document,
        {"base": pixels},
        None,
        revision=1,
        composite_cache=None,
        composite_cache_revision=-1,
        dirty_bounds=None,
    )
    old_cache = initial.cache
    patch = build_texture_editor_resident_patch(
        document.source_binding,
        old_cache,
        texture_revision=1,
        dirty_bounds=(1, 0, 1, 1),
    )
    old_bytes = old_cache.tobytes()
    pixels[0, 1] = [9, 8, 7, 255]
    changed_document = TextureEditorDocument(
        "COW",
        3,
        2,
        active_layer_id="base",
        layers=(TextureEditorLayer("base", "Base", "", revision=2),),
        source_binding=document.source_binding,
    )

    updated = texture_editor_composite_render_state(
        changed_document,
        {"base": pixels},
        None,
        revision=2,
        composite_cache=old_cache,
        composite_cache_revision=1,
        dirty_bounds=(1, 0, 1, 1),
    )

    assert updated.cache is not old_cache
    assert updated.cache[0, 1].tolist() == [9, 8, 7, 255]
    assert old_cache.tobytes() == old_bytes
    assert not old_cache.flags.writeable
    patch.composite_lease.release()
    assert old_cache.flags.writeable


def test_region_queue_keeps_one_active_and_coalesces_pending_union(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    sent: list[dict[str, object]] = []
    queue = ResidentTextureRegionUpdateQueue(lambda payload: sent.append(dict(payload)) or True, output_root=tmp_path)
    original = np.zeros((4, 4, 4), dtype=np.uint8)
    original[..., 3] = 255
    try:
        owned_root = tmp_path / "package" / "output" / "texture-regions"
        assert queue.enqueue(
            _request(
                original,
                rect=(0, 0, 1, 1),
                color=(1, 2, 3, 4),
                output_root=owned_root,
            )
        )
        assert _wait_for(app, lambda: len(sent) == 1)
        first_path = Path(sent[0]["binary"]["path"])
        assert first_path.is_file()
        assert first_path.resolve().is_relative_to(owned_root.resolve())

        current = original.copy()
        current[0, 0] = [3, 2, 1, 4]
        current[1, 1] = [7, 6, 5, 8]
        assert queue.enqueue(
            _request(original, rect=(1, 1, 1, 1), color=(5, 6, 7, 8), current=current.copy())
        )
        current[1, 2] = [11, 10, 9, 12]
        assert queue.enqueue(
            _request(original, rect=(2, 1, 1, 1), color=(9, 10, 11, 12), current=current.copy())
        )
        assert len(sent) == 1
        assert queue.metrics()["active_depth"] == 1
        assert queue.metrics()["pending_depth"] == 1
        assert queue.metrics()["pending_patch_count"] == 1

        assert queue.acknowledge(
            "texture_region_applied",
            {"resource_id": "texture:body", "generation": 1, "texture_revision": 9},
        )
        assert _wait_for(app, lambda: len(sent) == 2)
        assert not first_path.exists()
        second = sent[1]
        assert second["generation"] == 2
        assert second["rect"] == {"x": 1, "y": 1, "width": 2, "height": 1}
        second_path = Path(second["binary"]["path"])
        raw = second_path.read_bytes()
        assert raw == bytes((5, 6, 7, 8, 9, 10, 11, 12))
        assert second["binary"]["sha256"] == hashlib.sha256(raw).hexdigest()
        assert queue.metrics()["coalesced_updates"] == 1

        assert queue.acknowledge(
            "texture_region_applied",
            {"resource_id": "texture:body", "generation": 2, "texture_revision": 10},
        )
        assert queue.idle()
        assert queue.wait_idle(0.01)
        assert not second_path.exists()
        assert queue.metrics()["worker_resource_count"] == 1
        queue.reset()
        assert queue.metrics()["worker_resource_count"] == 0
        assert queue.metrics()["resource_count"] == 0
    finally:
        queue.shutdown()
        app.processEvents()


def test_region_queue_releases_submitted_snapshots_once_and_keeps_pending_owned(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    sent: list[dict[str, object]] = []
    original = np.zeros((2, 2, 4), dtype=np.uint8)
    queue = ResidentTextureRegionUpdateQueue(lambda payload: sent.append(dict(payload)) or True, output_root=tmp_path)
    first_current = original.copy()
    first_lease = _CountingCompositeLease(first_current)
    try:
        queue.enqueue(
            _request(
                original,
                rect=(0, 0, 1, 1),
                color=(1, 2, 3, 4),
                current=first_current,
                composite_lease=first_lease,
            )
        )
        assert _wait_for(app, lambda: len(sent) == 1)
        assert first_lease.release_count == 1

        queue.acknowledge("texture_region_failed", {"resource_id": "texture:body", "generation": 1})
        assert _wait_for(app, lambda: len(sent) == 2)
        assert first_lease.release_count == 1

        second_current = original.copy()
        second_current[0, 0] = [3, 2, 1, 4]
        second_lease = _CountingCompositeLease(second_current)
        queue.enqueue(
            _request(
                original,
                rect=(0, 0, 1, 1),
                color=(1, 2, 3, 4),
                current=second_current,
                composite_lease=second_lease,
            )
        )
        assert second_lease.release_count == 0
        assert not second_current.flags.writeable

        third_current = second_current.copy()
        third_current[1, 1] = [7, 6, 5, 8]
        third_lease = _CountingCompositeLease(third_current)
        queue.enqueue(
            _request(
                original,
                rect=(1, 1, 1, 1),
                color=(5, 6, 7, 8),
                current=third_current,
                composite_lease=third_lease,
            )
        )
        assert second_lease.release_count == 1
        assert second_current.flags.writeable
        assert third_lease.release_count == 0
        assert not third_current.flags.writeable

        queue.acknowledge("texture_region_applied", {"resource_id": "texture:body", "generation": 2})
        assert _wait_for(app, lambda: len(sent) == 3)
        assert third_lease.release_count == 1
        assert third_current.flags.writeable
        queue.acknowledge("texture_region_applied", {"resource_id": "texture:body", "generation": 3})
        assert queue.idle()
    finally:
        queue.shutdown()
        app.processEvents()


def test_region_queue_starts_pending_after_preparation_failure(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    preparation_started = threading.Event()
    release_preparation = threading.Event()
    sent: list[dict[str, object]] = []

    class FailFirstPreparationQueue(ResidentTextureRegionUpdateQueue):
        def _prepare_batch_owned(self, requests, generation, retry_rect, epoch):
            if generation == 1:
                preparation_started.set()
                if not release_preparation.wait(3.0):
                    raise TimeoutError("test preparation was not released")
                raise RuntimeError("injected preparation failure")
            return super()._prepare_batch_owned(requests, generation, retry_rect, epoch)

    queue = FailFirstPreparationQueue(lambda payload: sent.append(dict(payload)) or True, output_root=tmp_path)
    original = np.zeros((2, 2, 4), dtype=np.uint8)
    first = _request(original, rect=(0, 0, 1, 1), color=(1, 2, 3, 4))
    second = _request(original, rect=(1, 1, 1, 1), color=(5, 6, 7, 8))
    try:
        queue.enqueue(first)
        assert preparation_started.wait(1.0)
        queue.enqueue(second)
        assert not second.composite_lease.released

        release_preparation.set()

        assert _wait_for(app, lambda: len(sent) == 1, timeout=1.0)
        assert sent[0]["generation"] == 2
        assert first.composite_lease.released
        assert second.composite_lease.released
        queue.acknowledge("texture_region_applied", {"resource_id": "texture:body", "generation": 2})
        assert queue.idle()
    finally:
        release_preparation.set()
        queue.shutdown()
        app.processEvents()


def test_region_queue_retries_failure_once_and_reset_forces_full_current_patch(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    sent: list[dict[str, object]] = []
    original = np.zeros((3, 3, 4), dtype=np.uint8)
    original[..., 3] = 255
    current = original.copy()
    current[0, 0] = [90, 80, 70, 255]
    current[1, 1] = [30, 20, 10, 255]
    queue = ResidentTextureRegionUpdateQueue(lambda payload: sent.append(dict(payload)) or True, output_root=tmp_path)
    try:
        queue.enqueue(
            _request(
                original,
                rect=(1, 1, 1, 1),
                color=(10, 20, 30, 255),
                current=current,
            )
        )
        assert _wait_for(app, lambda: len(sent) == 1)
        assert sent[0]["rect"] == {"x": 0, "y": 0, "width": 3, "height": 3}
        assert Path(sent[0]["binary"]["path"]).read_bytes()[:4] == bytes((70, 80, 90, 255))
        queue.acknowledge(
            "texture_region_failed",
            {"resource_id": "texture:body", "generation": 1, "message": "injected"},
        )
        assert _wait_for(app, lambda: len(sent) == 2)
        queue.acknowledge(
            "texture_region_failed",
            {"resource_id": "texture:body", "generation": 2, "message": "injected again"},
        )
        assert _wait_for(app, queue.idle)
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert len(sent) == 2

        queue.reset()
        current[2, 2] = [60, 50, 40, 255]
        queue.enqueue(
            _request(
                original,
                rect=(2, 2, 1, 1),
                color=(40, 50, 60, 255),
                current=current,
            )
        )
        assert _wait_for(app, lambda: len(sent) == 3)
        assert sent[2]["rect"] == {"x": 0, "y": 0, "width": 3, "height": 3}
        queue.acknowledge(
            "texture_region_applied",
            {"resource_id": "texture:body", "generation": 1},
        )
    finally:
        queue.shutdown()
        app.processEvents()


def test_reset_keeps_queued_snapshot_immutable_until_worker_retires(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    worker_started = threading.Event()
    release_worker = threading.Event()

    class BlockingService:
        def commit_texture_snapshot(self, *_args: object, **_kwargs: object) -> int:
            worker_started.set()
            if not release_worker.wait(3.0):
                raise TimeoutError("test worker was not released")
            return 1

    queue = ResidentTextureRegionUpdateQueue(lambda _payload: True, output_root=tmp_path)
    first = np.zeros((2, 2, 4), dtype=np.uint8)
    queued_cache = np.zeros((2, 2, 4), dtype=np.uint8)
    queued_request = _request(
        queued_cache,
        rect=(0, 0, 1, 1),
        color=(1, 2, 3, 255),
        current=queued_cache,
        resource_id="texture:queued",
    )
    try:
        assert queue.enqueue(
            _request(
                first,
                rect=(0, 0, 1, 1),
                color=(1, 2, 3, 255),
                service=BlockingService(),
                resource_id="texture:blocking",
            )
        )
        assert worker_started.wait(1.0)
        assert queue.enqueue(queued_request)
        assert not queued_cache.flags.writeable

        queue.reset()

        assert not queued_cache.flags.writeable
        layer = TextureEditorLayer("base", "Base", "", revision=2)
        document = TextureEditorDocument("Reset COW", 2, 2, active_layer_id="base", layers=(layer,))
        changed_pixels = queued_cache.copy()
        changed_pixels[0, 0] = [9, 8, 7, 255]
        updated = texture_editor_composite_render_state(
            document,
            {"base": changed_pixels},
            None,
            revision=2,
            composite_cache=queued_cache,
            composite_cache_revision=1,
            dirty_bounds=(0, 0, 1, 1),
        )
        assert updated.cache is not queued_cache
        assert updated.cache[0, 0].tolist() == [9, 8, 7, 255]

        release_worker.set()
        assert _wait_for(app, lambda: queued_request.composite_lease.released)
        assert queued_cache.flags.writeable
    finally:
        release_worker.set()
        queue.shutdown()
        app.processEvents()


def test_region_queue_feature_detects_service_snapshot_and_region_commits(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    main_thread = threading.get_ident()
    calls: list[tuple[str, int]] = []
    sent: list[dict[str, object]] = []

    class Service:
        def commit_texture_snapshot(self, *_args: object, **_kwargs: object) -> int:
            calls.append(("snapshot", threading.get_ident()))
            return 40

        def commit_texture_region(self, *_args: object, **kwargs: object) -> int:
            calls.append(("region", threading.get_ident()))
            assert kwargs["expected_revision"] == 40
            return 41

    original = np.zeros((2, 2, 4), dtype=np.uint8)
    queue = ResidentTextureRegionUpdateQueue(lambda payload: sent.append(dict(payload)) or True, output_root=tmp_path)
    try:
        queue.enqueue(_request(original, rect=(0, 0, 1, 1), color=(1, 2, 3, 4), service=Service()))
        assert _wait_for(app, lambda: len(sent) == 1)
        assert sent[0]["texture_revision"] == 40
        assert [name for name, _thread in calls] == ["snapshot"]
        assert all(thread_id != main_thread for _name, thread_id in calls)
        queue.acknowledge("texture_region_applied", {"resource_id": "texture:body", "generation": 1})
        changed = original.copy()
        changed[1, 1] = [4, 3, 2, 1]
        queue.enqueue(
            _request(
                original,
                rect=(1, 1, 1, 1),
                color=(2, 3, 4, 1),
                service=Service(),
                current=changed,
            )
        )
        assert _wait_for(app, lambda: len(sent) == 2)
        assert sent[1]["texture_revision"] == 41
        assert [name for name, _thread in calls] == ["snapshot", "region"]
        queue.acknowledge("texture_region_applied", {"resource_id": "texture:body", "generation": 2})
    finally:
        queue.shutdown()
        app.processEvents()


def test_linked_texture_edit_emits_patch_after_pointer_handler_returns(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = TextureEditorTab(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
        base_dir=tmp_path,
        get_texconv_path=lambda: "",
        get_png_root=lambda: "",
    )
    pixels = np.zeros((16, 16, 4), dtype=np.uint8)
    pixels[..., 3] = 255
    binding = TextureEditorSourceBinding(
        launch_origin="mesh_editor",
        texture_type="mesh_material",
        mesh_session_id="session",
        mesh_submesh_indices=(0,),
        mesh_channel="base",
    )
    document = TextureEditorDocument(
        "Linked",
        16,
        16,
        active_layer_id="base",
        layers=(TextureEditorLayer("base", "Base", ""),),
        source_binding=binding,
    )
    emitted: list[object] = []
    tab.resident_texture_patch_ready.connect(emitted.append)
    try:
        tab._create_session(document, {"base": pixels}, label="Linked")
        tab._push_history("Base")
        tab.current_tool_settings = TextureEditorToolSettings(
            tool="paint",
            color_hex="#112233",
            size=2.0,
            spacing=20,
        )

        tab._handle_canvas_stroke({"points": [(8, 8)]})

        assert emitted == []
        assert _wait_for(app, lambda: len(emitted) == 1)
        patch = emitted[0]
        assert patch.pixel_format == "bgra8_unorm"
        assert patch.rect[2] < 16 and patch.rect[3] < 16
        assert not tab._sessions[0].original_flattened.flags.writeable

        tab.undo()
        assert _wait_for(app, lambda: len(emitted) == 2)
        tab._schedule_resident_texture_patch(None)
        assert _wait_for(app, lambda: len(emitted) == 3)
        assert emitted[2].rect == (0, 0, 16, 16)
    finally:
        tab.request_shutdown()
        tab.close()
        tab.deleteLater()
        app.processEvents()
