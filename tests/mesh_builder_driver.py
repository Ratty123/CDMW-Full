"""Reusable offscreen driver for the archive Mesh Builder dialog.

The Builder's regressions live in runtime enablement, signal wiring, and
teardown, so this driver constructs the real dialog offscreen and delivers real
Qt signals instead of asserting on source text. It generalises the local helper
that ``test_mesh_builder_preview_control_honesty`` proved out, so behaviour tests
can migrate off the source guards without each one re-deriving the synthetic
archive/preflight setup.

Guarantees, all inherited from the startup smoke contract: no visible window, no
renderer process, no licensed asset, and no archive I/O. Teardown asserts the
same invariants the startup smoke gate enforces -- clean dialog removal, no
leftover active timers, and no renderer start.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence, TypeVar

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import (
    active_builder_timer_names,
    configure_synthetic_archive_context,
    synthetic_archive_entry,
    synthetic_builder_preflight,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt import (
    prompt_archive_static_replacement_options,
)
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext


_WidgetT = TypeVar("_WidgetT", bound=QWidget)

APPLICATION = QApplication.instance() or QApplication([])

#: Qt creates these as parentless top-levels by design, so a Show event on one
#: is not a builder parenting defect.  Extend per test when a case is genuinely
#: framework-owned rather than ours.
QT_OWNED_TOPLEVEL_CLASSES = frozenset(
    {
        "QComboBoxPrivateContainer",
        "QMenu",
        "QToolTip",
        "QWidgetWindow",
        "QFrame",
    }
)


class ParentlessShow(QObject):
    """Records widgets that became visible while still parentless.

    A widget shown before it is added to a layout becomes a transient top-level
    window; by the time construction finishes it has been reparented and looks
    correct, so only watching the Show event itself catches it.
    """

    def __init__(self, ignored: QWidget) -> None:
        super().__init__()
        self._ignored = ignored
        self.records: list[tuple[str, str]] = []

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget):
            if watched is not self._ignored and watched.parentWidget() is None:
                self.records.append(
                    (type(watched).__name__, watched.objectName())
                )
        return False

    def leaks(self, *, ignored_classes: frozenset[str] = QT_OWNED_TOPLEVEL_CLASSES) -> tuple[tuple[str, str], ...]:
        return tuple(
            record for record in self.records if record[0] not in ignored_classes
        )


class MeshBuilderDriver:
    """A constructed Builder dialog plus the handles needed to drive it."""

    def __init__(
        self,
        *,
        modify_original_clone_mode: bool = False,
        dialog_title: str = "Mesh Builder driver",
    ) -> None:
        self.modify_original_clone_mode = bool(modify_original_clone_mode)
        self._temp = tempfile.TemporaryDirectory(prefix="cdmw-mesh-builder-driver-")
        self.root = Path(self._temp.name)
        self.settings = create_settings(settings_file_path=self.root / "builder.cfg")
        self.window = MainWindow(
            app_context=AppContext(
                settings=self.settings,
                services=ServiceContainer.create_default(settings=self.settings),
                event_bus=AppEventBus(),
            )
        )
        # The dialog derives complete_swap_profile_store_path from this. Left at
        # the default it resolves to the repository root and the test writes
        # into the working tree.
        self.window.settings_file_path = self.root / "builder.cfg"

        self.runtime_events: list[tuple[str, dict[str, object]]] = []
        self._original_record_runtime_event = getattr(
            self.window, "_record_runtime_event", None
        )
        self.window._record_runtime_event = self._capture_runtime_event

        self.parentless_show = ParentlessShow(self.window)
        APPLICATION.installEventFilter(self.parentless_show)

        configure_synthetic_archive_context(
            self.window, synthetic_archive_entry(self.root)
        )
        before = set(self.window._modeless_alignment_dialogs)
        try:
            prompt_archive_static_replacement_options(
                self.window,
                self.window.archive_entries[0],
                self.root / f"{dialog_title}.obj",
                dialog_title=dialog_title,
                _prepared_prompt_preflight=synthetic_builder_preflight(
                    modify_original_clone_mode=self.modify_original_clone_mode,
                ),
            )
            self.pump()
            opened = set(self.window._modeless_alignment_dialogs) - before
            if len(opened) != 1:
                raise AssertionError(
                    "expected exactly one Builder dialog, "
                    f"got {len(opened)}: {self.failure_detail()}"
                )
            self.dialog_key = next(iter(opened))
            self.dialog = self.window._modeless_alignment_dialogs[self.dialog_key]
            if not bool(getattr(self.dialog, "_cdmw_builder_construction_complete", False)):
                raise AssertionError(
                    f"Builder construction did not complete: {self.failure_detail()}"
                )
            self.context = getattr(self.dialog, "_cdmw_builder_construction_context", {})
        except BaseException:
            self.close(check_invariants=False)
            raise

    # -- observation ------------------------------------------------------

    def _capture_runtime_event(self, event: str, **fields: object) -> object:
        self.runtime_events.append((event, dict(fields)))
        if callable(self._original_record_runtime_event):
            return self._original_record_runtime_event(event, **fields)
        return {}

    def events_named(self, name: str) -> tuple[dict[str, object], ...]:
        return tuple(fields for event, fields in self.runtime_events if event == name)

    def failure_detail(self) -> str:
        failures = self.events_named("mesh_alignment_construction_failed")
        if not failures:
            return "no construction-failure diagnostic was recorded"
        latest = failures[-1]
        return f"stage={latest.get('stage')!s}, message={latest.get('message')!s}"

    # -- lookup -----------------------------------------------------------

    def control(self, key: str) -> object:
        """Fetch a control the dialog published on its construction context."""
        if key not in self.context:
            raise AssertionError(
                f"construction context has no {key!r}; "
                f"available keys include {sorted(self.context)[:12]}"
            )
        value = self.context[key]
        if value is None:
            raise AssertionError(f"construction context published {key!r} as None")
        return value

    def find(self, widget_type: type[_WidgetT], object_name: str) -> _WidgetT:
        """Fetch a real child widget by objectName, the way the app locates it."""
        widget = self.dialog.findChild(widget_type, object_name)
        if widget is None:
            raise AssertionError(
                f"{widget_type.__name__} named {object_name!r} is not in the dialog"
            )
        return widget

    def combo(self, object_name: str) -> QComboBox:
        return self.find(QComboBox, object_name)

    def checkbox(self, object_name: str) -> QCheckBox:
        return self.find(QCheckBox, object_name)

    def button(self, object_name: str) -> QPushButton:
        return self.find(QPushButton, object_name)

    # -- interaction ------------------------------------------------------

    def pump(self) -> None:
        APPLICATION.processEvents()

    def select_data(self, combo: QComboBox, value: object) -> None:
        """Select by item data and let the real signal chain run."""
        index = combo.findData(value)
        if index < 0:
            available = [combo.itemData(i) for i in range(combo.count())]
            raise AssertionError(
                f"{combo.objectName() or combo!r} has no item for {value!r}; "
                f"available: {available}"
            )
        combo.setCurrentIndex(index)
        self.pump()

    def set_checked(self, checkbox: QCheckBox, active: bool) -> None:
        checkbox.setChecked(bool(active))
        self.pump()

    def click(self, button: QAbstractButton) -> None:
        button.click()
        self.pump()

    def set_value(self, spin: QSpinBox | QDoubleSpinBox, value: float) -> None:
        spin.setValue(value)
        self.pump()

    def set_mesh_edit(self, active: bool) -> None:
        """Flip Edit Mesh without launching .NET, then refresh dependent state.

        The checkbox signal would start the renderer, which this driver forbids,
        so the state refresh is invoked directly the way the dialog does.
        """
        checkbox = self.checkbox("MeshEditModeCheckbox")
        checkbox.blockSignals(True)
        checkbox.setChecked(bool(active))
        checkbox.blockSignals(False)
        refresh = getattr(
            self.dialog, "_mesh_editor_refresh_preview_mode_controls", None
        )
        if callable(refresh):
            refresh()
        self.pump()

    # -- teardown ---------------------------------------------------------

    def close(self, *, check_invariants: bool = True) -> None:
        context = getattr(self, "context", {})
        active_timers: Sequence[str] = ()
        try:
            for dialog in tuple(self.window._modeless_alignment_dialogs.values()):
                dialog.reject()
            self.pump()
            active_timers = active_builder_timer_names(context)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.pump()
            self.window._finalize_close()
            self.pump()
        finally:
            APPLICATION.removeEventFilter(self.parentless_show)
            if callable(self._original_record_runtime_event):
                self.window._record_runtime_event = self._original_record_runtime_event
            self.window.deleteLater()
            self.pump()
            self._temp.cleanup()

        if not check_invariants:
            return
        remaining = set(self.window._modeless_alignment_dialogs)
        if remaining:
            raise AssertionError(f"Builder dialog did not close cleanly: {remaining}")
        if active_timers:
            raise AssertionError(
                f"Builder left active timers after close: {', '.join(active_timers)}"
            )
        started = self.events_named("mesh_dotnet_process_started")
        if started:
            raise AssertionError(
                f"Builder driver unexpectedly started the renderer: {started}"
            )


@contextmanager
def open_mesh_builder(
    *,
    modify_original_clone_mode: bool = False,
    dialog_title: str = "Mesh Builder driver",
) -> Iterator[MeshBuilderDriver]:
    """Construct the Builder offscreen, yield it, then assert clean teardown."""
    driver = MeshBuilderDriver(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=dialog_title,
    )
    try:
        yield driver
    finally:
        driver.close()


__all__ = [
    "APPLICATION",
    "MeshBuilderDriver",
    "ParentlessShow",
    "QT_OWNED_TOPLEVEL_CLASSES",
    "open_mesh_builder",
]
