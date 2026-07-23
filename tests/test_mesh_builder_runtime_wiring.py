from __future__ import annotations

import builtins
import dis
import os
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QPushButton,
    QWidget,
)

from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import (
    verify_mesh_builder_startup_smoke_target,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_state_callbacks import (
    create_static_replacement_prompt_state_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_state_context import (
    StaticReplacementPromptStateControls,
)
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext


_APPLICATION = QApplication.instance() or QApplication([])
_ROOT = Path(__file__).resolve().parents[1]


def _nested_code_objects(code: types.CodeType):
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from _nested_code_objects(value)


def _unresolved_runtime_globals(function: object) -> tuple[str, ...]:
    available = set(function.__globals__) | set(dir(builtins))
    unresolved: set[str] = set()
    for code in _nested_code_objects(function.__code__):
        for instruction in dis.get_instructions(code):
            if (
                instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}
                and instruction.argval not in available
            ):
                unresolved.add(str(instruction.argval))
    return tuple(sorted(unresolved))


def _control_mapping(parent: QWidget) -> dict[str, object]:
    return {
        "alignment_d3d11_reload_timer": QTimer(parent),
        "alignment_d3d11_status_timer": QTimer(parent),
        "alignment_d3d11_view_mode_combo": QComboBox(parent),
        "alignment_preview_settings_button": QPushButton(parent),
        "alignment_use_global_preview_button": QPushButton(parent),
        "overlay_original_locked_checkbox": QCheckBox(parent),
        "preview_depth_spin": QDoubleSpinBox(parent),
        "preview_disable_brightness_checkbox": QCheckBox(parent),
        "preview_disable_tint_checkbox": QCheckBox(parent),
        "preview_disable_uv_scale_checkbox": QCheckBox(parent),
        "preview_mesh_view_combo": QComboBox(parent),
        "preview_mode_combo": QComboBox(parent),
        "preview_render_mode_combo": QComboBox(parent),
        "preview_renderer_combo": QComboBox(parent),
        "preview_rough_spin": QDoubleSpinBox(parent),
        "preview_shine_spin": QDoubleSpinBox(parent),
        "preview_support_maps_checkbox": QCheckBox(parent),
        "preview_visible_mode_combo": QComboBox(parent),
    }


def test_state_callback_owner_has_no_unresolved_runtime_globals() -> None:
    assert _unresolved_runtime_globals(create_static_replacement_prompt_state_callbacks) == ()


def test_runtime_global_audit_detects_a_missing_builder_control() -> None:
    namespace: dict[str, object] = {}
    exec(
        compile(
            "def broken_builder_wiring():\n"
            "    return missing_builder_control.currentIndex()\n",
            "<synthetic-builder-wiring>",
            "exec",
        ),
        namespace,
    )

    assert _unresolved_runtime_globals(namespace["broken_builder_wiring"]) == (
        "missing_builder_control",
    )


def test_typed_state_controls_require_the_mesh_view_control() -> None:
    parent = QWidget()
    try:
        context = _control_mapping(parent)
        expected = context.pop("preview_mesh_view_combo")
        try:
            StaticReplacementPromptStateControls.from_mapping(context)
        except TypeError as exc:
            assert "preview_mesh_view_combo" in str(exc)
            assert "missing" in str(exc)
        else:
            raise AssertionError(f"missing typed control was accepted: {expected!r}")
    finally:
        parent.deleteLater()
        _APPLICATION.processEvents()


def test_import_and_modify_original_builders_complete_offscreen(tmp_path: Path) -> None:
    settings = create_settings(settings_file_path=tmp_path / "mesh-builder-smoke.cfg")
    context = AppContext(
        settings=settings,
        services=ServiceContainer.create_default(settings=settings),
        event_bus=AppEventBus(),
    )
    window = MainWindow(app_context=context)
    try:
        assert verify_mesh_builder_startup_smoke_target(window, _APPLICATION) == (
            "Import Mesh",
            "Modify Original",
        )
    finally:
        for dialog in tuple(window._modeless_alignment_dialogs.values()):
            dialog.reject()
        _APPLICATION.processEvents()
        window._finalize_close()
        window.deleteLater()
        _APPLICATION.processEvents()


def test_mesh_builder_runtime_wiring_is_owned_by_mesh_unit() -> None:
    gate = (_ROOT / "scripts" / "codex_check.ps1").read_text(encoding="utf-8")
    for test_name in (
        "tests/test_mesh_builder_runtime_wiring.py",
        "tests/test_mesh_builder_construction_lifecycle.py",
        "tests/test_static_replacement_post_open_state.py",
        "tests/test_static_replacement_dotnet_presentation.py",
    ):
        assert f'"{test_name}"' in gate
