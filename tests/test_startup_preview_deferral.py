from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.preview_settings import ArchivePreviewSettingsMixin
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin
from cdmw.ui.shell.settings_persistence import SettingsPersistenceMixin
from cdmw.ui.shell.startup_restore import ShellStartupRestoreMixin


REPO_ROOT = Path(__file__).resolve().parents[1]


class _Tree:
    @staticmethod
    def currentItem() -> None:
        return None


class _Timer:
    @staticmethod
    def isActive() -> bool:
        return False


def test_idle_startup_defers_preview_state_application() -> None:
    window = SimpleNamespace(
        archive_tree=_Tree(),
        archive_preview_debounce_timer=_Timer(),
        current_archive_preview_result=None,
        archive_preview_thread=None,
        archive_preview_worker=None,
        pending_archive_preview_request=None,
        scheduled_archive_preview_request=None,
        model_preview_settings_dialog=None,
        _modal_model_preview_settings_dialogs=(),
        _ensure_archive_preview_startup_state=lambda: (_ for _ in ()).throw(
            AssertionError("idle startup applied preview state")
        ),
    )

    ShellStartupRestoreMixin._prepare_archive_preview_startup_state(window)  # type: ignore[arg-type]

    assert window._archive_preview_startup_state_pending is True


def test_first_preview_state_use_reads_saved_settings_before_apply_and_clear() -> None:
    loaded = ModelPreviewRenderSettings(d3d11_tone_gamma=1.23)
    events: list[tuple[str, object]] = []
    window = SimpleNamespace(
        _archive_preview_startup_state_pending=True,
        _archive_preview_startup_state_applying=False,
        _model_preview_settings_read_pending=True,
        _model_preview_render_settings=ModelPreviewRenderSettings(),
        _read_model_preview_render_settings=lambda: events.append(("read", None)) or loaded,
        _handle_model_preview_settings_changed=lambda value: events.append(("apply", value)),
        _clear_archive_preview=lambda message: events.append(("clear", message)),
    )

    ShellStartupRestoreMixin._ensure_archive_preview_startup_state(window)  # type: ignore[arg-type]

    assert events == [
        ("read", None),
        ("apply", loaded),
        ("clear", "Select an archive file to preview it here."),
    ]
    assert window._model_preview_settings_read_pending is False
    assert window._archive_preview_startup_state_pending is False
    assert window._archive_preview_startup_state_applying is False


@pytest.mark.parametrize(
    "entrypoint",
    (
        ArchivePreviewWorkerMixin._render_archive_preview,
        ArchivePreviewSettingsMixin._open_model_preview_settings_dialog,
        ArchivePreviewSettingsMixin._open_modal_model_preview_settings_dialog,
    ),
)
def test_preview_and_settings_entrypoints_force_pending_state_first(entrypoint: object) -> None:
    class _FirstUseReached(RuntimeError):
        pass

    window = SimpleNamespace(
        _ensure_archive_preview_startup_state=lambda: (_ for _ in ()).throw(_FirstUseReached),
    )
    args = (window, None) if entrypoint is not ArchivePreviewSettingsMixin._open_model_preview_settings_dialog else (window,)

    with pytest.raises(_FirstUseReached):
        entrypoint(*args)  # type: ignore[operator]


def test_pending_preview_settings_are_not_overwritten_by_save() -> None:
    writes: list[tuple[str, object]] = []
    window = SimpleNamespace(
        _model_preview_settings_read_pending=True,
        settings=SimpleNamespace(setValue=lambda key, value: writes.append((key, value))),
        _current_model_preview_render_settings=lambda: (_ for _ in ()).throw(
            AssertionError("pending settings were read during save")
        ),
    )

    saved = SettingsPersistenceMixin._save_model_preview_settings_if_loaded(window)  # type: ignore[arg-type]

    assert saved is False
    assert writes == []


def test_loaded_preview_settings_keep_existing_persistence_keys() -> None:
    writes: dict[str, object] = {}
    preview_settings = ModelPreviewRenderSettings(
        use_textures_by_default=True,
        high_quality_by_default=True,
        preview_texture_max_dimension=2048,
        d3d11_tone_gamma=1.23,
        gizmo_x_axis_color="#123456",
        gizmo_line_thickness_pixels=2.5,
        alignment_use_final_output_preview=True,
    )
    window = SimpleNamespace(
        _model_preview_settings_read_pending=False,
        settings=SimpleNamespace(setValue=writes.__setitem__),
        _current_model_preview_render_settings=lambda: preview_settings,
    )

    saved = SettingsPersistenceMixin._save_model_preview_settings_if_loaded(window)  # type: ignore[arg-type]

    assert saved is True
    assert len(writes) == 77
    assert writes["archive/model_use_textures"] is True
    assert writes["archive/model_high_quality"] is True
    assert writes["preview/texture_max_dimension"] == 2048
    assert writes["preview/d3d11_tone_gamma"] == 1.23
    assert writes["preview/gizmo_x_axis_color"] == "#123456"
    assert writes["preview/gizmo_line_thickness_pixels"] == 2.5
    assert "preview/alignment_use_final_output_preview" not in writes


def test_gizmo_preview_settings_restore_from_main_preview_config() -> None:
    values: dict[str, object] = {
        "archive/model_use_textures": True,
        "preview/d3d11_lighting_defaults_version": 6,
        "preview/gizmo_x_axis_color": "#123456",
        "preview/gizmo_y_axis_color": "#234567",
        "preview/gizmo_z_axis_color": "#345678",
        "preview/gizmo_highlight_color": "#456789",
        "preview/gizmo_label_color": "#56789A",
        "preview/gizmo_line_thickness_pixels": 2.75,
        "preview/gizmo_size_scale": 1.8,
        "preview/gizmo_label_size_pixels": 18.0,
        "preview/gizmo_handle_size_pixels": 11.0,
    }
    settings_store = SimpleNamespace(
        value=lambda key, default=None: values.get(key, default),
        setValue=values.__setitem__,
    )
    reader = SimpleNamespace(
        settings=settings_store,
        _read_bool=lambda key, default: bool(values.get(key, default)),
        _read_float=lambda key, default: float(values.get(key, default)),
        _read_int=lambda key, default: int(values.get(key, default)),
    )

    restored = ArchivePreviewSettingsMixin._read_model_preview_render_settings(reader)  # type: ignore[arg-type]

    assert restored.use_textures_by_default is True
    assert restored.gizmo_x_axis_color == "#123456"
    assert restored.gizmo_y_axis_color == "#234567"
    assert restored.gizmo_z_axis_color == "#345678"
    assert restored.gizmo_highlight_color == "#456789"
    assert restored.gizmo_label_color == "#56789A"
    assert restored.gizmo_line_thickness_pixels == 2.75
    assert restored.gizmo_size_scale == 1.8
    assert restored.gizmo_label_size_pixels == 18.0
    assert restored.gizmo_handle_size_pixels == 11.0


def test_main_window_keeps_saved_preview_values_and_placeholder_without_preview_use() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        settings_path = Path(temp_dir) / "settings.ini"
        script = "\n".join(
            (
                "import os, sys",
                "from pathlib import Path",
                "os.environ['QT_QPA_PLATFORM'] = 'offscreen'",
                "os.environ['CDMW_GUI_STARTUP_SMOKE'] = '1'",
                "os.environ['CDMW_MAIN_WINDOW_CLASS_ONLY'] = '1'",
                "from cdmw.services import settings_service",
                f"path = Path({str(settings_path)!r})",
                "settings_service.resolve_settings_file_path = lambda **_kwargs: path",
                "settings = settings_service.create_settings(settings_file_path=path)",
                "settings.setValue('preview/d3d11_tone_gamma', 1.23); settings.sync()",
                "from PySide6.QtWidgets import QApplication",
                "import cdmw.ui.shell.app_window as app_window",
                "app_window.resolve_settings_file_path = lambda: path",
                "MainWindow = app_window.run_gui()",
                "from cdmw.app.events import AppEventBus",
                "from cdmw.services.service_container import ServiceContainer",
                "from cdmw.ui.shell.app_context import AppContext",
                "app = QApplication.instance() or QApplication([])",
                "window = MainWindow(app_context=AppContext(settings, ServiceContainer.create_default(settings=settings), AppEventBus()))",
                "window.show(); app.processEvents()",
                "assert window.archive_preview_meta_label.text() == 'Select an archive file to preview it here.'",
                "assert window._archive_preview_startup_state_pending is True",
                "assert window.archive_preview_request_id == 0",
                "assert 'cdmw.ui.archive_browser.preview_settings' not in sys.modules",
                "window.hide(); window._finalize_close()",
                "settings.sync()",
                "assert float(settings.value('preview/d3d11_tone_gamma')) == 1.23",
                "import json",
                "heartbeat = json.loads((window.crash_reports_dir / 'app_heartbeat.json').read_text(encoding='utf-8'))",
                "assert heartbeat['clean_shutdown'] is True and heartbeat['phase'] == 'closed'",
                "assert 'cdmw.ui.archive_browser.preview_settings' not in sys.modules",
                "sys.stdout.flush(); sys.stderr.flush(); os._exit(0)",
            )
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )

    assert result.returncode == 0, result.stderr or result.stdout
