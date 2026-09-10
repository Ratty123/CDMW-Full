"""Real Qt construction at emulated desktop scales; no native renderer or game data.

Each case has a fresh QApplication, screen, font registry, and temporary settings.
The subprocess entry point also makes an individual failing scenario reproducible.
"""
from __future__ import annotations

import json
import gc
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


SCENARIOS = (
    (1366, 768, 1.0, 10, "en", "compact_rail"),
    (1920, 1080, 1.25, 10, "en", "compact_rail"),
    (1920, 1080, 1.5, 10, "en", "compact_rail"),
    (1920, 1080, 2.0, 10, "en", "compact_rail"),
    (2560, 1440, 2.0, 10, "en", "compact_rail"),
    (3840, 2160, 3.0, 10, "en", "compact_rail"),
    (1920, 1080, 1.0, 15, "en", "compact_rail"),
    (1920, 1080, 2.0, 15, "de", "compact_rail"),
    (1920, 1080, 2.0, 10, "en", "legacy"),
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda values: "-".join(map(str, values)))
def test_registered_tools_fit_desktop(scenario, tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root) + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()), *map(str, scenario)],
        cwd=tmp_path, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=90,
    )
    if result.returncode == 77:
        pytest.skip("The application's real font is unavailable")
    assert result.returncode == 0, result.stdout[-12000:] + result.stderr[-6000:]
    report = json.loads((tmp_path / "display-result.json").read_text(encoding="utf-8"))
    assert len(report["tools"]) == len(report["registered_tools"])
    assert report["failures"] == []


def _probe() -> int:
    width, height, scale, font, language, variant = sys.argv[1:]
    width, height, scale, font = int(width), int(height), float(scale), int(font)
    # Qt's offscreen config URL needs a relative path on Windows (drive colons
    # otherwise become platform option separators).
    Path("screen.json").write_text(json.dumps({
        "windowFrameMargins": True,
        "screens": [{"name": "display-test", "width": width,
                     "height": height - round(48 * scale),
                     "logicalDpi": round(96 * scale), "logicalBaseDpi": 96, "dpr": 1.0}],
    }), encoding="utf-8")
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=screen.json"
    os.environ["CDMW_GUI_STARTUP_SMOKE"] = "1"
    from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt
    from PySide6.QtGui import QFontDatabase, QFontInfo
    from PySide6.QtWidgets import QApplication, QAbstractButton, QPushButton, QToolButton, QStyle, QStyleOptionButton
    from cdmw.app.events import AppEventBus
    from cdmw.services.service_container import ServiceContainer
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext
    from cdmw.ui.shell.lazy_tool_tab import LazyToolTab
    from cdmw.ui.shell.theme_controller import apply_app_theme
    from tests.qt_font_metrics_support import ensure_default_ui_font_available
    from tools.compact_shell_visual.runner import _PlacementBaselineGuard

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    if not ensure_default_ui_font_available():
        return 77
    for filename in ("segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf", "consola.ttf", "consolab.ttf"):
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    settings = create_settings(settings_file_path=Path("settings.ini").resolve())
    for key, value in {
        "ui/shell_variant": variant, "appearance/theme": "crimson_desert",
        "appearance/ui_font_size": font, "appearance/data_font_size": font,
        "appearance/language": language, "preferences/auto_load_archive_on_startup": False,
        "preferences/restore_last_active_tab": False, "archive/package_root": "",
        "model_library/local_roots_json": "[]", "model_library/results_view": "local",
        "model_library/auto_preview": False, "item_icons/library_roots": "[]",
    }.items():
        settings.setValue(key, value)
    apply_app_theme(app, settings, "crimson_desert")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings), event_bus=AppEventBus())
    # A pre-existing PySide/Python background-GC failure was reproduced by the
    # audit. Geometry validation owns collection on the GUI thread; this fixture
    # is deliberately not evidence for worker/GC or native-renderer stability.
    gc.disable()
    available = app.primaryScreen().availableGeometry()
    target = QSize(available.width() - 16, available.height() - 32)
    failures = []
    report = {"tools": [], "failures": failures, "device_pixel_ratio": app.primaryScreen().devicePixelRatio(),
              "font": font, "font_family": QFontInfo(app.font()).family()}

    def settle():
        deadline = time.monotonic() + 0.12
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    def inspect(label):
        settle()
        if not available.contains(window.frameGeometry()):
            failures.append(f"{label}: window frame exceeds the work area")
        for button in window.findChildren(QAbstractButton):
            if not button.isVisibleTo(window) or button.visibleRegion().isEmpty() or not button.text():
                continue
            if isinstance(button, QToolButton) and button.toolButtonStyle() == Qt.ToolButtonIconOnly:
                continue
            text_width = button.fontMetrics().size(Qt.TextShowMnemonic, button.text()).width()
            if not button.icon().isNull():
                text_width += button.iconSize().width() + 4
            contents = button.contentsRect()
            if isinstance(button, QPushButton):
                option = QStyleOptionButton()
                button.initStyleOption(option)
                contents = button.style().subElementRect(QStyle.SE_PushButtonContents, option, button)
            if text_width > contents.width() + 2 or button.fontMetrics().height() > contents.height() + 2:
                failures.append(f"{label}: clipped {button.objectName()!r} {button.text()!r}")

    with _PlacementBaselineGuard():
        window = MainWindow(app_context=context)
        # MainWindow's class loader installs its own file-based fault handler.
        # Route native faults back into this subprocess's captured diagnostics.
        import faulthandler
        faulthandler.enable(file=sys.stderr)
        try:
            window.resize(target)
            window.show()
            settle()
            report["registered_tools"] = list(window._tool_widgets_by_key)
            for key, registered in window._tool_widgets_by_key.items():
                gc.collect()
                window._activate_tool_key(key)
                # Follow normal activation through asynchronous publication.
                # Forcing ensure_widget here would bypass the path under test
                # while its dependency preload can still be running.
                pending = [registered] if isinstance(registered, LazyToolTab) else []
                pending.extend(lazy for lazy in registered.findChildren(LazyToolTab) if lazy.isVisibleTo(window))
                for lazy in pending:
                    deadline = time.monotonic() + 10.0
                    while lazy.widget_if_created() is None and time.monotonic() < deadline:
                        settle()
                    assert lazy.widget_if_created() is not None, f"{key}: lazy tool did not finish loading"
                window.resize(target)
                inspect(key)
                if key == "settings":
                    tab = window.settings_tab
                    for index in range(tab.section_nav_list.count()):
                        tab.section_nav_list.setCurrentRow(index)
                        inspect(f"settings:{index}")
                report["tools"].append(key)
                print(key, flush=True)
            assert app.font().pointSize() == font
        finally:
            window._finalize_close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            gc.collect()
            gc.enable()
            app.quit()
    Path("display-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        print(json.dumps(failures, ensure_ascii=True), flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(_probe())
