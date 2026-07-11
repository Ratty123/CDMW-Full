from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from tests.static_replacement_source_support import static_replacement_ui_section_source
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog

from cdmw.ui.archive_browser.static_replacement_texture_async import (
    AdvancedDdsRowScanRequest,
    DdsDetailPreviewResult,
    StaticReplacementAdvancedDdsController,
    StaticReplacementDdsDetailController,
    MaterialAuthorityResourceResult,
    StaticReplacementMaterialAuthorityResourceController,
)
from cdmw.ui.archive_browser.static_replacement_dialog_material_authority_callbacks import (
    _material_resource_bindings_for_preview_model,
    create_material_authority_adjustment_callbacks,
)
from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot
from cdmw.modding.material_profiles import (
    get_complete_swap_material_profile,
    serialize_complete_swap_manual_material_profile,
)
from cdmw.ui.shell.close_controller import (
    iter_transient_shutdown_workers,
    request_transient_shutdowns,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, *, timeout: float = 3.0) -> None:  # type: ignore[no-untyped-def]
    app = _app()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.003)
    app.processEvents()
    assert predicate()


def test_advanced_dds_row_scan_returns_immediately_and_runs_off_ui_thread() -> None:
    app = _app()
    owner = QObject()
    dialog = QDialog()
    controller = StaticReplacementAdvancedDdsController(owner, dialog)
    main_thread_id = threading.get_ident()
    worker_threads: list[int] = []
    completed: list[object] = []
    idle = threading.Event()
    mapping = SimpleNamespace(target_submesh_name="body", source_submesh_indices=(0,))
    binding = SimpleNamespace(texture_path="character/body_base.dds", parameter_name="BaseColor")

    def slow_best(*_args: object, **_kwargs: object) -> str:
        worker_threads.append(threading.get_ident())
        time.sleep(0.15)
        return "source.png"

    request = AdvancedDdsRowScanRequest(
        request_id=0,
        suggested_mappings=(mapping,),
        sidecar_bindings=(binding,),
        texture_sets=(),
        seen_texture_rows=frozenset(),
        binding_matches_target=lambda _binding, _target: True,
        best_source_for_slot=slow_best,
        texture_is_shared=lambda _path: False,
    )
    started_at = time.perf_counter()
    assert controller.start(
        request,
        on_complete=completed.append,
        on_error=lambda message: (_ for _ in ()).throw(AssertionError(message)),
        on_idle=idle.set,
    )
    assert time.perf_counter() - started_at < 0.05
    _wait_until(idle.is_set)

    assert len(completed) == 1
    assert worker_threads == [worker_threads[0]]
    assert worker_threads[0] != main_thread_id
    assert QThread.currentThread() is app.thread()
    assert not controller.iter_shutdown_workers()
    dialog.deleteLater()


def test_dds_detail_latest_request_wins_and_shutdown_is_nonblocking(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    app = _app()
    owner = QObject()
    dialog = QDialog()
    controller = StaticReplacementDdsDetailController(owner, dialog)
    from cdmw.ui.archive_browser import static_replacement_texture_async as worker_module

    first_started = threading.Event()

    def delayed_resolve(raw_path: object, *_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        if str(raw_path) == "first.dds":
            first_started.set()
            time.sleep(0.2)
            color = QColor("red")
        else:
            color = QColor("green")
        image = QImage(8, 8, QImage.Format_RGBA8888)
        image.fill(color)
        preview_path = tmp_path / f"{Path(str(raw_path)).stem}.png"
        assert image.save(str(preview_path), "PNG")
        return preview_path, "ready"

    monkeypatch.setattr(worker_module, "resolve_dds_detail_preview_path", delayed_resolve)
    results: list[DdsDetailPreviewResult] = []
    errors: list[str] = []
    controller.start(
        source_path="first.dds",
        slot_kind="base",
        texconv_path=None,
        on_complete=results.append,
        on_error=errors.append,
    )
    assert first_started.wait(1.0)
    started_at = time.perf_counter()
    controller.start(
        source_path="second.dds",
        slot_kind="normal",
        texconv_path=None,
        on_complete=results.append,
        on_error=errors.append,
    )
    assert time.perf_counter() - started_at < 0.05
    _wait_until(lambda: not controller.iter_shutdown_workers())

    assert errors == []
    assert len(results) == 1
    assert results[0].preview_path == tmp_path / "second.png"
    assert results[0].image.pixelColor(4, 4).green() > results[0].image.pixelColor(4, 4).red()

    controller.start(
        source_path="first.dds",
        slot_kind="base",
        texconv_path=None,
        on_complete=results.append,
        on_error=errors.append,
    )
    assert [name for name, _thread, _worker in iter_transient_shutdown_workers(owner)] == [
        "transient.dds_detail_preview"
    ]
    started_at = time.perf_counter()
    request_transient_shutdowns(owner)
    assert time.perf_counter() - started_at < 0.05
    _wait_until(lambda: not controller.iter_shutdown_workers())
    dialog.deleteLater()
    app.processEvents()


def test_static_texture_ui_has_no_nested_event_pump_or_sync_detail_decode() -> None:
    sections = static_replacement_ui_section_source(Path.cwd())
    details = Path(
        "cdmw/ui/archive_browser/static_replacement_dialog_texture_detail_uv_callbacks.py"
    ).read_text(encoding="utf-8")
    table = Path("cdmw/ui/archive_browser/static_replacement_dialog_texture_callbacks.py").read_text(encoding="utf-8")

    assert "QApplication.processEvents" not in sections
    assert "QApplication.processEvents" not in table
    load_start = sections.index("        def _load_advanced_dds_override_rows")
    load_end = sections.index("        def _ensure_advanced_dds_overrides_loaded", load_start)
    assert "advanced_dds_controller.start(" in sections[load_start:load_end]
    refresh_start = details.index("    def _refresh_dds_detail_thumbnail")
    refresh_end = details.index("    def _set_texture_transform_controls_enabled", refresh_start)
    refresh_body = details[refresh_start:refresh_end]
    assert "dds_detail_controller.start(" in refresh_body
    assert "_resolve_dds_detail_preview_path(" not in refresh_body
    assert "_read_preview_pixmap(" not in refresh_body


def _material_profile(**updates: object) -> object:
    values = {
        "base_binding_mode": "overlay_texture",
        "mask_binding_mode": "disabled",
        "support_policy": "source_only",
        "emissive_mode": "disabled",
        "base_color_scale": 0.75,
        **updates,
    }
    return get_complete_swap_material_profile(serialize_complete_swap_manual_material_profile(values))


def test_material_resource_worker_is_latest_wins_dds_safe_and_ack_cleaned(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    from PIL import Image
    from cdmw.core.dds_native import inspect_dds_native_path
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services import material_authority_resource_service as resource_service

    owner = QObject()
    dialog = QDialog()
    controller = StaticReplacementMaterialAuthorityResourceController(owner, dialog)
    first_png = tmp_path / "first.png"
    second_png = tmp_path / "second.png"
    Image.new("RGBA", (8, 8), (32, 64, 96, 255)).save(first_png)
    Image.new("RGBA", (8, 8), (96, 64, 32, 255)).save(second_png)
    first_started = threading.Event()
    worker_threads: list[int] = []
    original_encode = resource_service._encode_owned_dds
    encode_count = 0

    def delayed_encode(source: Path, target: Path, channel: str, stop_event: threading.Event) -> None:
        nonlocal encode_count
        encode_count += 1
        worker_threads.append(threading.get_ident())
        if encode_count == 1:
            first_started.set()
            for _index in range(80):
                time.sleep(0.003)
                raise_if_cancelled(stop_event, "cancelled")
        original_encode(source, target, channel, stop_event)

    monkeypatch.setattr(resource_service, "_encode_owned_dds", delayed_encode)
    results: list[MaterialAuthorityResourceResult] = []
    errors: list[str] = []
    idle = threading.Event()

    def accept(result: MaterialAuthorityResourceResult) -> bool:
        results.append(result)
        return True

    def texture_set(path: Path) -> ReplacementTextureSet:
        return ReplacementTextureSet("body", slots={"base": ReplacementTextureSlot("body", "base", path)})

    assert controller.start(
        texture_sets={"body": texture_set(first_png)},
        material_profile=_material_profile(),
        affected_channels=("base",),
        reason="first",
        on_complete=accept,
        on_error=errors.append,
    )
    assert first_started.wait(1.0)
    assert controller.start(
        texture_sets={"body": texture_set(second_png)},
        material_profile=_material_profile(),
        affected_channels=("base",),
        reason="second",
        on_complete=accept,
        on_error=errors.append,
        on_idle=idle.set,
    )
    _wait_until(idle.is_set, timeout=10.0)

    assert errors == []
    assert len(results) == 1
    result = results[0]
    binding = result.bindings[0]
    dds_path = Path(str(binding["source_dds_path"]))
    info = inspect_dds_native_path(dds_path)
    assert dds_path.suffix.lower() == ".dds"
    assert info.width == 8 and info.height == 8 and not info.reason
    assert worker_threads and all(thread_id != threading.get_ident() for thread_id in worker_threads)

    preview = SimpleNamespace(meshes=(SimpleNamespace(material_name="body"),))
    mapped, affected = _material_resource_bindings_for_preview_model(preview, result.bindings)
    assert affected == (0,)
    assert mapped[0]["affected_submeshes"] == (0,)
    assert result.output_root.is_dir()
    controller.finish(1, True, result.bindings)
    assert not result.output_root.exists()

    removal_results: list[MaterialAuthorityResourceResult] = []
    removal_idle = threading.Event()
    assert controller.start(
        texture_sets={"body": texture_set(second_png)},
        material_profile=_material_profile(base_binding_mode="disabled"),
        affected_channels=("base",),
        reason="remove",
        on_complete=lambda item: removal_results.append(item) or True,
        on_error=errors.append,
        on_idle=removal_idle.set,
    )
    _wait_until(removal_idle.is_set)
    removal = removal_results[0]
    assert removal.bindings[0]["remove"] is True
    assert removal.bindings[0]["resource_id"] == binding["resource_id"]
    assert removal.bindings[0]["logical_path"] == str(second_png)
    controller.finish(2, True, removal.bindings)
    assert not removal.output_root.exists()

    first_root = tmp_path / "first-removal"
    second_root = tmp_path / "second-removal"
    first_root.mkdir()
    second_root.mkdir()
    first_removal = MaterialAuthorityResourceResult(
        3, first_root, ({"resource_id": "first", "channel": "base", "path": "", "remove": True},), (), "first"
    )
    second_removal = MaterialAuthorityResourceResult(
        4, second_root, ({"resource_id": "second", "channel": "base", "path": "", "remove": True},), (), "second"
    )
    controller._owned_results.extend((first_removal, second_removal))
    controller.finish(3, True, first_removal.bindings)
    assert not first_root.exists()
    assert second_root.is_dir()
    controller.request_shutdown()
    assert not second_root.exists()
    dialog.deleteLater()


def test_material_resource_dialog_close_cancels_thread_and_cleans_owned_roots(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services import material_authority_resource_service as resource_service
    from cdmw.ui.archive_browser import static_replacement_texture_async as worker_module

    owner = QObject()
    dialog = QDialog()
    callbacks = create_material_authority_adjustment_callbacks({"self": owner, "dialog": dialog})
    controller = callbacks.material_resource_controller
    owned_root = tmp_path / "ack-pending"
    owned_root.mkdir()
    controller._owned_results.append(
        MaterialAuthorityResourceResult(
            1, owned_root, ({"resource_id": "pending", "channel": "base"},), ("base",), "pending"
        )
    )
    started = threading.Event()

    def blocked_generate(*_args: object, **kwargs: object) -> tuple[dict[str, object], ...]:
        started.set()
        stop_event = kwargs.get("stop_event") or _args[-1]
        while True:
            time.sleep(0.003)
            raise_if_cancelled(stop_event, "cancelled")

    monkeypatch.setattr(resource_service, "generate_material_authority_resource_bindings", blocked_generate)
    real_mkdtemp = worker_module.tempfile.mkdtemp
    generated_roots: list[Path] = []

    def owned_mkdtemp(*, prefix: str) -> str:
        path = tmp_path / f"{prefix}{len(generated_roots)}"
        path.mkdir()
        generated_roots.append(path)
        return str(path)

    monkeypatch.setattr(worker_module.tempfile, "mkdtemp", owned_mkdtemp)
    assert controller.start(
        texture_sets=(),
        material_profile=None,
        affected_channels=("base",),
        reason="close",
        on_complete=lambda _result: True,
        on_error=lambda _message: None,
    )
    assert started.wait(1.0)
    dialog.reject()
    _wait_until(lambda: not controller.iter_shutdown_workers())

    assert not owned_root.exists()
    assert generated_roots and all(not path.exists() for path in generated_roots)
    monkeypatch.setattr(worker_module.tempfile, "mkdtemp", real_mkdtemp)
