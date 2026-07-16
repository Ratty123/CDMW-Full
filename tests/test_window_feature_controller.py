from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QEventLoop, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.ui.shell.window_feature_controller import (
    LazyFeatureProvider,
    WindowFeatureController,
    install_window_feature_controller,
)
import cdmw.ui.shell.window_feature_controller as feature_controller


REPO_ROOT = Path(__file__).resolve().parents[1]


class _ShellProvider:
    shell_constant = "shell"

    def shell_method(self, suffix: str) -> str:
        return f"{self.name}:{suffix}"


class _InheritedProvider:
    def inherited_method(self) -> str:
        return self.name.upper()


class _ArchiveProvider(_InheritedProvider):
    @property
    def label(self) -> str:
        return self._label

    @label.setter
    def label(self, value: str) -> None:
        self._label = value


class _Window:
    def __init__(self) -> None:
        self.name = "workbench"
        self._label = "initial"
        self._shell_controller = WindowFeatureController(self, (_ShellProvider,))
        self._archive_controller = WindowFeatureController(self, (_ArchiveProvider,))


install_window_feature_controller(
    _Window,
    controller_attribute="_shell_controller",
    providers=(_ShellProvider,),
)
install_window_feature_controller(
    _Window,
    controller_attribute="_archive_controller",
    providers=(_ArchiveProvider,),
)


def test_composed_controller_preserves_method_property_and_inherited_behavior() -> None:
    window = _Window()

    assert window.shell_method("ok") == "workbench:ok"
    assert window.inherited_method() == "WORKBENCH"
    assert window.shell_constant == "shell"
    assert window.label == "initial"

    window.label = "changed"
    assert window.label == "changed"
    assert window._label == "changed"


def test_composed_controller_keeps_class_level_method_introspection() -> None:
    window = _Window()

    assert callable(_Window.shell_method)
    assert _Window.shell_method(window, "class") == "workbench:class"
    assert _Window.__cdmw_composed_members__["shell_method"] == "_shell_controller"

    window.shell_method = lambda suffix: f"override:{suffix}"
    assert window.shell_method("instance") == "override:instance"


def test_composed_controller_rejects_ambiguous_ownership() -> None:
    class DuplicateProvider:
        def shell_method(self) -> str:
            return "duplicate"

    with pytest.raises(TypeError, match="already owned"):
        install_window_feature_controller(
            _Window,
            controller_attribute="_archive_controller",
            providers=(DuplicateProvider,),
        )


def test_composed_controller_keeps_explicit_qt_virtual_bridge() -> None:
    class Provider:
        def closeEvent(self, event: object) -> None:
            self.virtual_events.append("close")
            event.accept()
            self.loop.quit()

        def resizeEvent(self, _event: object) -> None:
            self.virtual_events.append("resize")

        def changeEvent(self, _event: object) -> None:
            self.virtual_events.append("change")

    class Window(QMainWindow):
        def __init__(self, loop: QEventLoop) -> None:
            super().__init__()
            self.loop = loop
            self.virtual_events: list[str] = []
            self._controller = WindowFeatureController(self, (Provider,))

        def closeEvent(self, event: object) -> None:  # type: ignore[override]
            self._controller.resolve("closeEvent")(event)

        def resizeEvent(self, event: object) -> None:  # type: ignore[override]
            self._controller.resolve("resizeEvent")(event)

        def changeEvent(self, event: object) -> None:  # type: ignore[override]
            self._controller.resolve("changeEvent")(event)

    install_window_feature_controller(
        Window,
        controller_attribute="_controller",
        providers=(Provider,),
        bridged_members=("changeEvent", "closeEvent", "resizeEvent"),
    )
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop()
    window = Window(loop)
    window.resize(320, 200)
    window.show()
    app.processEvents()
    QApplication.sendEvent(window, QEvent(QEvent.Type.LanguageChange))
    QTimer.singleShot(0, window.close)
    QTimer.singleShot(2000, loop.quit)

    loop.exec()

    assert {"change", "close", "resize"}.issubset(window.virtual_events)
    assert Window.__dict__["closeEvent"].__name__ == "closeEvent"
    assert Window.__cdmw_composed_members__["closeEvent"] == "_controller"


def test_composed_controller_rejects_unlisted_existing_member() -> None:
    class Provider:
        def callback(self) -> None:
            pass

    class Window:
        def callback(self) -> None:
            pass

    with pytest.raises(TypeError, match="already defines composed member"):
        install_window_feature_controller(
            Window,
            controller_attribute="_controller",
            providers=(Provider,),
        )


def test_composed_controller_honors_normal_provider_override() -> None:
    class BaseProvider:
        def value(self) -> str:
            return "base"

    class DerivedProvider(BaseProvider):
        def value(self) -> str:
            return "derived"

    class Window:
        def __init__(self) -> None:
            self._controller = WindowFeatureController(self, (DerivedProvider,))

    install_window_feature_controller(
        Window,
        controller_attribute="_controller",
        providers=(DerivedProvider,),
    )

    assert Window().value() == "derived"


def test_lazy_provider_imports_only_when_forwarded_member_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        def callback(self, value: str) -> str:
            return f"{self.name}:{value}"

        @property
        def label(self) -> str:
            return self.name.upper()

    imports: list[str] = []
    module = SimpleNamespace(Provider=Provider)
    loaded: dict[str, object] = {}

    def import_once(name: str) -> object:
        if name not in loaded:
            imports.append(name)
            loaded[name] = module
        return loaded[name]

    monkeypatch.setattr(
        feature_controller,
        "import_module",
        import_once,
    )
    feature_controller._load_lazy_descriptor.cache_clear()
    provider = LazyFeatureProvider("test_lazy_provider", "Provider", ("callback", "label"), {"callback": 1})

    class Window:
        def __init__(self) -> None:
            self.name = "workbench"
            self._controller = WindowFeatureController(self, (provider,))

    install_window_feature_controller(Window, controller_attribute="_controller", providers=(provider,))
    window = Window()

    callback = window.callback
    assert imports == []
    assert callback("ok", "ignored Qt signal payload") == "workbench:ok"
    assert imports == ["test_lazy_provider"]
    assert window.callback is callback
    assert window.label == "WORKBENCH"
    assert imports == ["test_lazy_provider"]
    feature_controller._load_lazy_descriptor.cache_clear()


def test_lazy_provider_worker_callback_runs_on_owning_qt_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        def handle_completed(self, _result: object) -> None:
            self.completed_thread = QThread.currentThread()
            self.loop.quit()

    class Worker(QObject):
        completed = Signal(object)
        finished = Signal()

        @Slot()
        def run(self) -> None:
            self.completed.emit({})
            self.finished.emit()

    monkeypatch.setattr(feature_controller, "import_module", lambda _name: SimpleNamespace(Provider=Provider))
    feature_controller._load_lazy_descriptor.cache_clear()
    provider = LazyFeatureProvider(
        "test_worker_provider",
        "Provider",
        ("handle_completed",),
        {"handle_completed": 1},
    )

    class Window(QObject):
        def __init__(self, loop: QEventLoop) -> None:
            super().__init__()
            self.loop = loop
            self.completed_thread: QThread | None = None
            self._controller = WindowFeatureController(self, (provider,))

    install_window_feature_controller(Window, controller_attribute="_controller", providers=(provider,))
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop()
    window = Window(loop)
    thread = QThread()
    worker = Worker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.completed.connect(window.handle_completed)
    worker.finished.connect(thread.quit)
    QTimer.singleShot(2000, loop.quit)

    thread.start()
    loop.exec()
    thread.quit()
    assert thread.wait(2000)

    assert window.completed_thread is app.thread()
    feature_controller._load_lazy_descriptor.cache_clear()


def test_lazy_provider_ignores_callbacks_after_qt_owner_is_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        def cached_callback(self, _value: object) -> None:
            raise AssertionError("Deleted Qt owners must not receive cached callbacks.")

        def uncached_callback(self, _value: object) -> None:
            raise AssertionError("Deleted Qt owners must not receive newly resolved callbacks.")

    imports: list[str] = []

    def import_provider(name: str) -> object:
        imports.append(name)
        return SimpleNamespace(Provider=Provider)

    monkeypatch.setattr(feature_controller, "import_module", import_provider)
    feature_controller._load_lazy_descriptor.cache_clear()
    provider = LazyFeatureProvider(
        "test_deleted_owner_provider",
        "Provider",
        ("cached_callback", "uncached_callback"),
        {"cached_callback": 1, "uncached_callback": 1},
    )

    class Window(QObject):
        def __init__(self) -> None:
            super().__init__()
            self._controller = WindowFeatureController(self, (provider,))

    install_window_feature_controller(Window, controller_attribute="_controller", providers=(provider,))
    app = QApplication.instance() or QApplication([])
    window = Window()
    cached_callback = window.cached_callback

    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

    assert cached_callback("late") is None
    assert window.uncached_callback("late") is None
    assert imports == []
    feature_controller._load_lazy_descriptor.cache_clear()


def test_generated_window_provider_metadata_is_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_window_feature_provider_members.py", "--check"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
