from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from cdmw.core.mod_package import ModPackageExportOptions
from cdmw.core.mod_package_retrofit import (
    ModPackageRetrofitResult,
    RetrofitPathRepairSummary,
    RetrofitPayloadMapping,
    RetrofittableModPackage,
)
from cdmw.models import ModPackageInfo, RunCancelled
from cdmw.ui.tools.mod_package_retrofit import ArchiveModPackageRetrofitDialogMixin
from cdmw.ui.tools.mod_package_retrofit_tasks import (
    ModPackageRetrofitTaskController,
    ModPackageRetrofitToolWidget,
)
from cdmw.workers.mod_package_retrofit_workers import (
    RetrofitConversionItem,
    RetrofitConversionRequest,
    RetrofitScanResult,
    collect_retrofittable_packages,
    convert_retrofit_request,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for(predicate: object, timeout: float = 4.0) -> None:
    app = _app()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def _package(root: Path, name: str = "Example") -> RetrofittableModPackage:
    return RetrofittableModPackage(
        root=root,
        name=name,
        kind="file_replacement",
        package_info=ModPackageInfo(title=name, version="1.0", author="Tester"),
        payload_paths=("character/model/example.pac",),
    )


def _summary() -> RetrofitPathRepairSummary:
    return RetrofitPathRepairSummary(
        mappings=(
            RetrofitPayloadMapping(
                source_path="character/model/example.pac",
                target_path="character/model/example.pac",
            ),
        )
    )


class _ToolOwner(ArchiveModPackageRetrofitDialogMixin, QObject):
    def __init__(self, base_dir: Path) -> None:
        QObject.__init__(self)
        self.settings_file_path = base_dir / "settings.json"
        self.ui_localizer = None

    def collect_config(self) -> object:
        return SimpleNamespace(mod_ready_export_root="", mod_ready_manager_profile="dmm")


def test_recursive_scan_finds_nested_package_and_skips_converted_output(tmp_path: Path) -> None:
    package_root = tmp_path / "nested" / "mods" / "Example"
    payload = package_root / "character" / "model" / "example.pac"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"PAC")
    skipped = tmp_path / "converted" / "Old" / "character" / "model" / "old.pac"
    skipped.parent.mkdir(parents=True)
    skipped.write_bytes(b"OLD")

    packages = collect_retrofittable_packages(tmp_path)

    assert [(package.name, package.root) for package in packages] == [("Example", package_root)]


def test_tool_scan_and_conversion_clicks_return_under_50ms_and_close_drains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    owner = _ToolOwner(tmp_path)
    widget = ModPackageRetrofitToolWidget()
    owner._build_mod_package_retrofit_tool(widget, run_initial_scan=False)
    controller = widget._retrofit_task_controller
    assert isinstance(controller, ModPackageRetrofitTaskController)
    package = _package(tmp_path / "source")
    heartbeat: list[float] = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.append(time.perf_counter()))
    timer.start()

    def slow_scan(request, **_kwargs: object) -> RetrofitScanResult:
        time.sleep(0.2)
        return RetrofitScanResult(request.request_id, (package,), (_summary(),))

    monkeypatch.setattr("cdmw.workers.mod_package_retrofit_workers.scan_retrofit_request", slow_scan)
    scan_button = widget.findChild(QPushButton, "retrofit_scan_button")
    assert scan_button is not None
    started = time.perf_counter()
    scan_button.click()
    assert (time.perf_counter() - started) * 1000.0 < 50.0
    _wait_for(lambda: not controller.iter_shutdown_workers())

    conversion_started = threading.Event()

    def slow_conversion(_request, *, stop_event: threading.Event, **_kwargs: object) -> object:
        conversion_started.set()
        stop_event.wait(2.0)
        raise RunCancelled("Retrofit conversion cancelled.")

    monkeypatch.setattr("cdmw.workers.mod_package_retrofit_workers.convert_retrofit_request", slow_conversion)
    convert_button = widget.findChild(QPushButton, "retrofit_convert_button")
    assert convert_button is not None
    _wait_for(convert_button.isEnabled)
    started = time.perf_counter()
    convert_button.click()
    assert (time.perf_counter() - started) * 1000.0 < 50.0
    assert conversion_started.wait(1.0)
    started = time.perf_counter()
    widget.request_shutdown()
    assert (time.perf_counter() - started) * 1000.0 < 50.0
    _wait_for(lambda: not controller.iter_shutdown_workers())
    timer.stop()

    gaps = [later - earlier for earlier, later in zip(heartbeat, heartbeat[1:])]
    assert heartbeat and (not gaps or max(gaps) < 0.2)
    widget.deleteLater()
    owner.deleteLater()
    app.processEvents()


def test_latest_scan_wins_when_older_worker_finishes_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    owner = QObject()
    controller = ModPackageRetrofitTaskController(thread_parent=owner, parent=owner)
    delivered: list[str] = []
    controller.scan_completed.connect(lambda result: delivered.append(result.packages[0].name))

    def out_of_order_scan(request, **_kwargs: object) -> RetrofitScanResult:
        if request.source.name == "old":
            time.sleep(0.2)
            package = _package(tmp_path / "old", "old")
        else:
            time.sleep(0.03)
            package = _package(tmp_path / "new", "new")
        return RetrofitScanResult(request.request_id, (package,), (_summary(),))

    monkeypatch.setattr("cdmw.workers.mod_package_retrofit_workers.scan_retrofit_request", out_of_order_scan)
    controller.start_scan(tmp_path / "old")
    controller.start_scan(tmp_path / "new")
    _wait_for(lambda: not controller.iter_shutdown_workers())

    assert delivered == ["new"]
    controller.request_shutdown()
    owner.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_or_cancelled_conversion_preserves_prior_output_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancelled: bool,
) -> None:
    output_root = tmp_path / "output"
    prior_root = output_root / "Example_dmm"
    prior_root.mkdir(parents=True)
    (prior_root / "prior.txt").write_text("keep", encoding="utf-8")
    prior_zip = output_root / "Example_dmm.zip"
    prior_zip.write_bytes(b"prior zip")
    stop_event = threading.Event()
    started = threading.Event()

    def fail_after_partial(package, staging_root, **_kwargs: object) -> object:
        partial = Path(staging_root) / f"{package.name}_dmm"
        partial.mkdir(parents=True)
        (partial / "partial.txt").write_text("partial", encoding="utf-8")
        started.set()
        if cancelled:
            assert stop_event.wait(2.0)
            raise RunCancelled("Retrofit conversion cancelled.")
        raise OSError("conversion failed")

    monkeypatch.setattr("cdmw.workers.mod_package_retrofit_workers.retrofit_mod_package", fail_after_partial)
    request = RetrofitConversionRequest(
        1,
        output_root,
        (RetrofitConversionItem(_package(tmp_path / "source"), "dmm", ModPackageExportOptions(), _summary()),),
    )
    errors: list[BaseException] = []

    def run() -> None:
        try:
            result = convert_retrofit_request(request, stop_event=stop_event)
            assert result.failed == (("Example", "conversion failed"),)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(1.0)
    if cancelled:
        stop_event.set()
    thread.join(2.0)

    assert not thread.is_alive()
    assert (prior_root / "prior.txt").read_text(encoding="utf-8") == "keep"
    assert prior_zip.read_bytes() == b"prior zip"
    assert not (output_root / "Example_1_dmm").exists()
    assert not (output_root / "Example_1_dmm.zip").exists()
    assert not list(output_root.glob(".cdmw-retrofit-*"))
    if cancelled:
        assert len(errors) == 1 and isinstance(errors[0], RunCancelled)
    else:
        assert errors == []


def test_publication_failure_rolls_back_all_new_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"

    def staged_success(package, staging_root, **_kwargs: object) -> ModPackageRetrofitResult:
        package_root = Path(staging_root) / f"{package.name}_dmm"
        package_root.mkdir(parents=True)
        metadata = package_root / "manifest.json"
        metadata.write_text("{}", encoding="utf-8")
        zip_path = package_root.with_suffix(".zip")
        zip_path.write_bytes(b"zip")
        return ModPackageRetrofitResult(
            source_root=package.root,
            output_root=Path(staging_root),
            package_root=package_root,
            zip_path=zip_path,
            manager_profile="dmm",
            metadata_files=(metadata,),
            payload_paths=(),
        )

    monkeypatch.setattr("cdmw.workers.mod_package_retrofit_workers.retrofit_mod_package", staged_success)
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source: object, target: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publish failed")
        real_replace(source, target)

    monkeypatch.setattr("cdmw.workers.mod_package_retrofit_workers.os.replace", fail_second_replace)
    request = RetrofitConversionRequest(
        1,
        output_root,
        (RetrofitConversionItem(_package(tmp_path / "source"), "dmm", ModPackageExportOptions(), _summary()),),
    )

    with pytest.raises(OSError, match="publish failed"):
        convert_retrofit_request(request)

    assert not (output_root / "Example_dmm").exists()
    assert not (output_root / "Example_dmm.zip").exists()
    assert not list(output_root.glob(".cdmw-retrofit-*"))
