"""Exercise the native worker lifetimes behind the Model -> Effects crash."""
import os
import threading
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop, Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from cdmw.ui.localization import UiLocalizer
from cdmw.ui.new_item.item_preview import ItemPreviewFrame
from cdmw.ui.new_item.translucency_editor import TranslucencyEditor
from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
from tests.test_effect_placement_dialog import _blade, _Host
from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace


def test_appearance_to_effects_deletes_workers_on_their_native_threads(tmp_path):
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    layout = QVBoxLayout(root)
    translucency, shaders = TranslucencyEditor(), ShaderControlsEditor()
    layout.addWidget(translucency)
    layout.addWidget(shaders)
    model = ItemPreviewFrame(root, output_root=tmp_path / "model")
    effects = EffectPlacementWorkspace(item_mesh=_blade(), box_min=(-1., -1., -1.), box_max=(1., 1., 1.),
                                       host_factory=lambda parent: _Host(parent), output_root=tmp_path / "effects")
    effects.setParent(root)
    localizer = UiLocalizer(language_dir=tmp_path / "language", language_code="en")
    localizer.activate_runtime_tracking(root, application=app)
    gui_thread = threading.get_ident()
    release = threading.Event()

    def settle(done):
        from PySide6.QtCore import QDeadlineTimer
        deadline = QDeadlineTimer(5000)
        while not done() and not deadline.hasExpired():
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert done(), "preview worker did not retire"

    try:
        for _ in range(8):
            translucency.refresh((("Blade", "Blade"), ("Grip", "Grip")), None)
            translucency.setChecked(True)
            translucency.select_all.click()
            translucency.clear_selection.click()
            shaders.refresh((("Blade", "Blade"),), ())
            shaders.family.setCurrentIndex(1)
            shaders.family.setCurrentIndex(0)
            for owner in (model, effects):
                release.clear()
                ran, destroyed = [], []

                def work(*_args, **_kwargs):
                    ran.append(threading.get_ident())
                    assert release.wait(5), "worker release timed out"
                    return None

                with patch("cdmw.ui.new_item.effect_placement_dialog.build_effect_placement_package", work):
                    if owner is model:
                        model._launch_package_worker(work, None)
                    else:
                        effects._start_package()
                    owner._worker.destroyed.connect(lambda: destroyed.append(threading.get_ident()), Qt.DirectConnection)
                    release.set()
                    settle(lambda: owner._thread is None and bool(destroyed))
                assert ran == destroyed
                assert ran[0] != gui_thread, "worker teardown must not migrate into the GUI event filters"
        assert not model.iter_shutdown_workers() and not effects.iter_shutdown_workers()
    finally:
        release.set()
        model.request_shutdown()
        effects.request_shutdown()
        settle(lambda: model._thread is None and effects._thread is None)
        localizer.shutdown()
        root.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
