"""One-window Compact Workspace visual harness orchestration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from tools.compact_shell_visual.capture import (
    capture_window,
    clipped_button_error,
    geometry_payload,
    unflattened_surface_error,
)
from tools.compact_shell_visual.contracts import (
    REFERENCE_FILENAMES,
    build_capture_plan,
    capture_sizes,
)
from tools.compact_shell_visual.fixtures import (
    _install_safe_workspace_fixture,
    _seed_in_memory_rows,
)
from tools.compact_shell_visual.runtime import (
    _apply_presentation,
    _assert_real_texture_editor,
    _process_events,
    _registered_widgets,
    _resize_frame,
    _resolve_tool_widget,
    _settle_resident_host_resize,
)


class _PlacementBaselineGuard:
    """Prevent Placement Studio from opening a user baseline during harness setup."""

    def __enter__(self) -> None:
        from tools.placement_studio.corpus import Baseline

        self._original = Baseline.__dict__["load"]

        def no_user_baseline(_cls, _root=None):
            raise FileNotFoundError("visual harness uses an in-memory empty baseline")

        Baseline.load = classmethod(no_user_baseline)

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        from tools.placement_studio.corpus import Baseline

        Baseline.load = self._original


def _configure_fixture_settings(settings: object, theme: str) -> None:
    values = {
        "ui/shell_variant": "compact_rail",
        "appearance/compact_shell_theme": theme,
        # Keep Classic independent so this run proves the compact key wins.
        "appearance/theme": "graphite",
        "preferences/auto_load_archive_on_startup": False,
        "preferences/restore_last_active_tab": False,
        "archive/package_root": "",
        "model_library/local_roots_json": "[]",
        "model_library/results_view": "local",
        "model_library/auto_preview": False,
        "item_icons/library_roots": "[]",
    }
    for key, value in values.items():
        settings.setValue(key, value)  # type: ignore[attr-defined]
    settings.sync()  # type: ignore[attr-defined]


def _selected_keys(arguments: argparse.Namespace) -> tuple[str, ...]:
    if arguments.all:
        return tuple(REFERENCE_FILENAMES)
    selected = tuple(dict.fromkeys(arguments.tool or ()))
    if not selected:
        raise ValueError("choose --all or at least one --tool")
    return selected


def run_harness(arguments: argparse.Namespace) -> dict[str, object]:
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output_root = Path(arguments.output).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    keys = _selected_keys(arguments)
    primary = arguments.size
    report: dict[str, object] = {
        "schema_version": 1,
        "theme": arguments.theme,
        "data_scope": "synthetic_local_only",
        "game_or_archive_data_loaded": False,
        "primary_size": f"{primary[0]}x{primary[1]}",
        "sizes": [f"{width}x{height}" for width, height in capture_sizes(primary)],
        "references": dict(REFERENCE_FILENAMES),
        "captures": [],
    }

    minimum_size_error = ""
    with tempfile.TemporaryDirectory(prefix="cdmw-compact-visual-") as temporary:
        fixture_root = Path(temporary)
        settings = create_settings(settings_file_path=fixture_root / "settings.ini")
        _configure_fixture_settings(settings, arguments.theme)
        from cdmw.ui.shell.compact.config import active_shell_theme_key
        from cdmw.ui.shell.theme_controller import apply_app_theme

        active_theme = active_shell_theme_key(settings)
        if active_theme != arguments.theme:
            raise RuntimeError(
                f"Requested compact theme {arguments.theme!r}, but settings resolved {active_theme!r}."
            )
        app.setStyle("Fusion")
        applied_theme = apply_app_theme(app, settings, active_theme)
        if applied_theme != arguments.theme:
            raise RuntimeError(
                f"Requested compact theme {arguments.theme!r}, but QApplication applied {applied_theme!r}."
            )
        report["active_compact_theme"] = active_theme
        report["classic_theme"] = str(settings.value("appearance/theme", ""))
        context = AppContext(
            settings=settings,
            services=ServiceContainer.create_default(settings=settings),
            event_bus=AppEventBus(),
        )
        with _PlacementBaselineGuard():
            window = MainWindow(app_context=context)
            try:
                _resize_frame(window, primary)
                if str(getattr(window, "current_theme_key", "")) != arguments.theme:
                    raise RuntimeError(
                        f"Requested compact theme {arguments.theme!r}, but MainWindow uses "
                        f"{getattr(window, 'current_theme_key', '')!r}."
                    )
                _registered_widgets(window)
                # Availability is a harness precondition even for a subset pass.
                texture_editor = _resolve_tool_widget(window, "texture_editor")
                _assert_real_texture_editor(texture_editor)
                _apply_presentation(window, "texture_editor", texture_editor)

                fixture_evidence_by_key: dict[str, dict[str, object]] = {}
                fixtures_by_key: dict[str, dict[str, int]] = {}
                widgets_by_key: dict[str, QWidget] = {}
                for key in keys:
                    widget = _resolve_tool_widget(window, key)
                    fixture_evidence_by_key[key] = _install_safe_workspace_fixture(
                        key,
                        widget,
                        fixture_root,
                    )
                    _apply_presentation(window, key, widget)
                    fixtures_by_key[key] = _seed_in_memory_rows(widget)
                    widgets_by_key[key] = widget
                    _process_events()

                captures = report["captures"]
                assert isinstance(captures, list)
                for key, size, relative_path in build_capture_plan(keys, primary):
                    widget = widgets_by_key[key]
                    getattr(window, "_activate_tool_key")(key)
                    _resize_frame(window, size)
                    _apply_presentation(window, key, widget)
                    _process_events(5)
                    _settle_resident_host_resize(widget)
                    geometry = geometry_payload(window, key, widget)
                    method, image_size = capture_window(
                        window,
                        output_root / relative_path,
                        expected_size=size,
                    )
                    geometry.update(
                        {
                            "requested_size": f"{size[0]}x{size[1]}",
                            "capture_path": relative_path.as_posix(),
                            "capture_method": method,
                            "capture_size": {
                                "width": image_size[0],
                                "height": image_size[1],
                            },
                            "fixture_rows": fixtures_by_key[key],
                            "fixture_evidence": fixture_evidence_by_key[key],
                            "within_requested_client": bool(
                                window.width() <= size[0] + 2 and window.height() <= size[1] + 2
                            ),
                        }
                    )
                    captures.append(geometry)

                inaccessible = [
                    row
                    for row in captures
                    if row["requested_size"] == "1120x720" and not row["within_requested_client"]
                ]
                if inaccessible:
                    details = ", ".join(
                        f"{row['key']}="
                        f"{row['window_geometry']['width']}x{row['window_geometry']['height']}"
                        for row in inaccessible
                    )
                    minimum_size_error = (
                        "Compact minimum-size client exceeded 1120x720 for: " + details
                    )
            finally:
                finalize = getattr(window, "_finalize_close", None)
                if callable(finalize):
                    finalize()
                window.close()
                window.deleteLater()
                _process_events(3)

    report_path = output_root / "compact-shell-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    capture_rows = report["captures"]
    clipping_error = clipped_button_error(capture_rows if isinstance(capture_rows, list) else ())
    flat_surface_error = unflattened_surface_error(
        capture_rows if isinstance(capture_rows, list) else ()
    )
    failures = tuple(
        message
        for message in (minimum_size_error, clipping_error, flat_surface_error)
        if message
    )
    if failures:
        raise RuntimeError(" ".join(failures))
    return report
