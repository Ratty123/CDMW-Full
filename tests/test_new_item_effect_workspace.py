from __future__ import annotations

import os
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QDeadlineTimer, QEventLoop, QObject, QThread, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QLabel,
    QPushButton,
    QTableView,
    QWidget,
)

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh  # noqa: E402
from cdmw.services.effect_catalogue import EffectCatalogue  # noqa: E402
from cdmw.ui.new_item.controller import NewItemStudioController  # noqa: E402
from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace  # noqa: E402
from cdmw.ui.new_item.effect_workspace import (  # noqa: E402
    EffectLibraryModel,
    EffectLibraryRow,
    GuidedEffectsWorkspace,
    _unique_effect_labels,
    effect_category,
    effect_display_label,
)
from cdmw.ui.new_item.state import EffectWorkspaceState, NewItemDraft  # noqa: E402


def _mesh() -> ParsedMesh:
    part = SubMesh(
        name="item",
        material="item",
        vertices=[(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.0, -1.0)],
        uvs=[(0.0, 0.0)] * 3,
        normals=[(0.0, 1.0, 0.0)] * 3,
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(
        path="item.pac",
        format="pac",
        submeshes=[part],
        bbox_min=(0.0, 0.0, -1.0),
        bbox_max=(0.1, 0.0, 0.0),
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )


class _Controller(QObject):
    effect_catalogue_progress = Signal(int, int, str)
    effect_catalogue_ready = Signal()
    effect_catalogue_failed = Signal(str)
    effect_changed = Signal(object)
    template_changed = Signal(object)
    model_import_changed = Signal(object)
    model_changed = Signal(object)
    model_placement_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.draft = NewItemDraft(template_key=1)
        self.stems = ("fx_fire_hit", "fx_fire_ring_loop", "fx_frost_loop")
        self.commit_count = 0

    def effect_stems(self, text="", *, limit=300):
        matches = [stem for stem in self.stems if not text or text.casefold() in stem.casefold()]
        return tuple(matches if limit is None else matches[:limit])

    def effect_facts(self, _stem):
        return None

    def effect_target_compatibility(self, stem):
        return SimpleNamespace(supported=True, message=f"Available for {stem} (2 prefabs).", errors=())

    def item_mesh_as_planned(self):
        return _mesh(), "template"

    def effect_box(self, _stem):
        return (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)

    def effect_preview_for_placement(self, _stem, _state=None):
        return None, None

    def character_holding_the_item(self):
        return None

    def commit_effect_workspace(self, state):
        if state == EffectWorkspaceState.from_draft(self.draft):
            return False
        state.write_to(self.draft)
        self.commit_count += 1
        self.effect_changed.emit(state)
        return True


class _Placement(QWidget):
    transform_changed = Signal()
    look_changed = Signal()
    apply_requested = Signal()

    def __init__(self, parent=None, **kwargs) -> None:
        super().__init__(parent)
        self.host = None
        self._host_error = "renderer missing"
        self._renderer_failed = True
        self.status = QLabel("")
        self.apply_button = QPushButton("Apply placement")
        self.offset = tuple(kwargs.get("offset", (0.0, 0.0, 0.0)))
        self.rotation = tuple(kwargs.get("rotation", (0.0, 0.0, 0.0)))
        self.scale = float(kwargs.get("scale", 1.0))
        self.color = kwargs.get("color")
        self.intensity = float(kwargs.get("intensity", 1.0))
        self.particle_size = float(kwargs.get("particle_size", 1.0))
        self.spawn_rate = float(kwargs.get("spawn_rate", 1.0))
        self.lifetime = float(kwargs.get("lifetime", 1.0))
        self.decoder_reason = ""
        self.content_calls = []

    def _set_numbers(self, offset, scale, rotation=None):
        self.offset = tuple(offset)
        self.scale = float(scale)
        if rotation is not None:
            self.rotation = tuple(rotation)

    def set_look(self, *, color, intensity, particle_size, spawn_rate, lifetime):
        self.color = color
        self.intensity = float(intensity)
        self.particle_size = float(particle_size)
        self.spawn_rate = float(spawn_rate)
        self.lifetime = float(lifetime)

    def set_decoder_reason(self, reason=""):
        self.decoder_reason = str(reason)

    def set_content(self, **kwargs):
        self.content_calls.append(kwargs)

    def iter_shutdown_workers(self):
        return ()

    def request_shutdown(self):
        pass


class EffectWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _workspace(self, controller=None, confirmations=None):
        controller = controller or _Controller()
        confirmations = confirmations if confirmations is not None else []

        def confirm(reason):
            confirmations.append(reason)
            return True

        workspace = GuidedEffectsWorkspace(
            controller,
            placement_factory=_Placement,
            confirm_unreviewed=confirm,
        )
        workspace.show()
        self.app.processEvents()
        self.addCleanup(workspace.request_shutdown)
        self.addCleanup(workspace.deleteLater)
        return workspace, controller, confirmations

    def _settle(self, predicate, timeout_ms=5000):
        deadline = QDeadlineTimer(timeout_ms)
        while not predicate() and not deadline.hasExpired():
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 25)
        self.assertTrue(predicate())

    def test_fixed_categories_and_neutral_mechanical_labels(self) -> None:
        self.assertEqual(effect_category("pafx_weapon_flame_loop"), "Fire")
        self.assertEqual(effect_category("fx_ice_fire"), "Fire", "fixed first-match precedence")
        self.assertEqual(effect_category("fx_emissive_ring"), "Glow")
        self.assertEqual(effect_category("fx_unclassified"), "Other")
        self.assertEqual(
            effect_display_label("fx_hit_common_fire_attach_a_loop"),
            "Hit Common Fire Attach A Loop",
        )
        self.assertEqual(
            effect_display_label("fx_action_boss_hit_01__metal_spark_k5", "A vague authoring name"),
            "Boss Hit 01 · Metal Spark K5",
        )
        self.assertEqual(effect_display_label("cdfx_flash_01a"), "Flash 01a")
        self.assertEqual(
            effect_display_label("fx_cc_firesweapon_a__fire1"),
            "CC Firesweapon A · Fire 1",
        )
        labels = _unique_effect_labels(("fx_action_hit__spark_a", "pafx_action_hit__spark_a"))
        self.assertEqual(len(set(labels.values())), 2)

    def test_no_effect_uses_the_pinned_row_without_repeating_empty_status(self) -> None:
        workspace, _controller, _confirmations = self._workspace()
        workspace.choose_effect("")
        self.app.processEvents()
        self.assertFalse(workspace.compatibility_label.isVisibleTo(workspace))
        self.assertFalse(workspace.selection_detail.isVisibleTo(workspace))

        workspace.choose_effect("fx_fire_hit")
        self.app.processEvents()
        self.assertTrue(workspace.compatibility_label.isVisibleTo(workspace))
        self.assertTrue(workspace.selection_detail.isVisibleTo(workspace))
        self.assertEqual(workspace.selection_detail.text(), "fx_fire_hit")

    def test_the_virtual_model_keeps_all_six_thousand_rows(self) -> None:
        model = EffectLibraryModel()
        rows = tuple(EffectLibraryRow.from_stem(f"fx_{index:04d}", None) for index in range(6000))
        model.replace_rows((EffectLibraryRow("", "No effect", "Other", "Off"), *rows))
        self.assertEqual(model.rowCount(), 6001)
        self.assertEqual(model.columnCount(), 4)
        self.assertEqual(
            [model.headerData(column, Qt.Orientation.Horizontal) for column in range(model.columnCount())],
            ["", "Effect", "Type", "Size"],
        )
        self.assertEqual(model.data(model.index(0, 0), EffectLibraryModel.StemRole), "")
        self.assertEqual(model.data(model.index(6000, 0), EffectLibraryModel.StemRole), "fx_5999")
        self.assertEqual(model.data(model.index(6000, 0), int(Qt.ItemDataRole.SizeHintRole)).height(), 24)

    def test_effect_table_uses_compact_regular_rows_and_metadata_columns(self) -> None:
        controller = _Controller()
        facts = SimpleNamespace(name="", loops=False, walk_note="", size=(2.5, 2.53, 2.64))
        controller.effect_facts = lambda stem: facts if stem == "fx_fire_hit" else None
        workspace, _controller, _confirmations = self._workspace(controller)
        view = workspace.library_view
        model = workspace.library_model
        index = model.index_for_stem("fx_fire_hit")

        self.assertIsInstance(view, QTableView)
        self.assertEqual(
            [model.data(model.index(index.row(), column)) for column in range(model.columnCount())],
            ["♨", "Fire Hit", "One-shot", "2.5×2.53×2.64"],
        )
        self.assertEqual(view.rowHeight(index.row()), 24)
        self.assertFalse(view.font().bold())
        self.assertFalse(view.horizontalHeader().font().bold())
        self.assertFalse(view.verticalHeader().isVisible())
        self.assertTrue(view.horizontalHeader().isVisible())
        self.assertTrue(view.hasMouseTracking())
        self.assertTrue(view.alternatingRowColors())
        self.assertFalse(view.showGrid())
        self.assertEqual(view.selectionBehavior(), QAbstractItemView.SelectionBehavior.SelectRows)

        view.setCurrentIndex(model.index(index.row(), 3))
        self.assertEqual(workspace.staged_state.stem, "fx_fire_hit", "every metadata cell selects its effect row")

    def test_selection_is_staged_and_apply_publishes_once(self) -> None:
        workspace, controller, confirmations = self._workspace()
        self.assertEqual((workspace.selection_timer.interval(), workspace.look_timer.interval()), (150, 250))
        workspace.choose_effect("fx_fire_hit")
        self.assertTrue(workspace.has_staged_changes())
        self.assertEqual(workspace.selection_detail.text(), "fx_fire_hit")
        self.assertEqual(controller.draft.effect_stem, "", "selection is not the draft")
        self.assertTrue(workspace.apply_staged())
        self.assertEqual(controller.draft.effect_stem, "fx_fire_hit")
        self.assertEqual(controller.commit_count, 1)
        self.assertEqual(confirmations, ["renderer missing"])
        self.assertTrue(workspace.apply_staged())
        self.assertEqual(controller.commit_count, 1, "a no-op apply does not invalidate again")

    def test_template_or_model_change_discards_staging_and_rebuilds_from_the_committed_draft(self) -> None:
        workspace, controller, _confirmations = self._workspace()
        workspace.choose_effect("fx_fire_hit")
        self.assertTrue(workspace.has_staged_changes())
        workspace._reset_view_next = False

        controller.template_changed.emit(2)

        self.assertEqual(workspace.staged_state, EffectWorkspaceState.from_draft(controller.draft))
        self.assertFalse(workspace.has_staged_changes())
        self.assertTrue(workspace._reset_view_next)
        self.assertTrue(workspace.selection_timer.isActive())

    def test_a_wearable_effect_defaults_to_the_applied_model_origin(self) -> None:
        controller = _Controller()
        helmet = _mesh()
        helmet._cdmw_effect_item_origin = (0.01, 1.76, -0.05)
        controller.item_mesh_as_planned = lambda: (helmet, "applied")
        workspace, _controller, _confirmations = self._workspace(controller)

        workspace.choose_effect("fx_fire_hit")
        workspace.selection_timer.stop()
        workspace._rebuild_preview()

        self.assertEqual(workspace.staged_state.offset, (0.01, 1.76, -0.05))
        self.assertEqual(workspace.placement.offset, (0.01, 1.76, -0.05))
        self.assertTrue(workspace.has_staged_changes(), "the head-height default is saved on Apply")

    def test_show_retries_a_transient_selected_template_preview(self) -> None:
        controller = _Controller()
        calls = 0

        def item_mesh_as_planned():
            nonlocal calls
            calls += 1
            return (None, "template") if calls == 1 else (_mesh(), "template")

        controller.item_mesh_as_planned = item_mesh_as_planned
        workspace, _controller, _confirmations = self._workspace(controller)
        self._settle(lambda: workspace.placement is not None)
        self.assertGreaterEqual(calls, 2)
        self.assertFalse(workspace.placeholder.isVisibleTo(workspace))

    def test_show_refreshes_an_existing_preview_after_model_step_changes(self) -> None:
        controller = _Controller()
        current = {"mesh": _mesh()}
        controller.item_mesh_as_planned = lambda: (current["mesh"], "placed")
        workspace, _controller, _confirmations = self._workspace(controller)
        self._settle(lambda: workspace.placement is not None)
        workspace.selection_timer.stop()
        workspace.look_timer.stop()
        workspace._initial_preview_timer.stop()
        workspace.placement.content_calls.clear()

        updated = _mesh()
        updated.path = "item-with-new-appearance.pac"
        current["mesh"] = updated
        workspace.hide()
        self.app.processEvents()
        workspace.show()
        self.app.processEvents()

        self.assertTrue(workspace.selection_timer.isActive(), "re-entering Effects refreshes the current Model & Placement appearance")
        self._settle(lambda: bool(workspace.placement.content_calls))
        self.assertIs(workspace.placement.content_calls[-1]["item_mesh"], updated)

    def test_reselecting_the_committed_effect_restores_its_values(self) -> None:
        controller = _Controller()
        committed = EffectWorkspaceState(
            stem="fx_fire_hit",
            scale=0.35,
            offset=(0.1, 0.2, 0.3),
            intensity=2.0,
        )
        committed.write_to(controller.draft)
        workspace, _controller, _confirmations = self._workspace(controller)
        workspace.choose_effect("fx_frost_loop")
        self.assertEqual(workspace.staged_state.scale, 1.0)
        workspace.choose_effect("fx_fire_hit")
        self.assertEqual(workspace.staged_state, committed)

    def test_no_effect_clears_stem_transform_colour_and_look_together(self) -> None:
        controller = _Controller()
        EffectWorkspaceState(
            stem="fx_fire_hit",
            scale=3.0,
            offset=(1.0, 2.0, 3.0),
            rotation=(10.0, 20.0, 30.0),
            color=(0.1, 0.2, 0.3),
            intensity=2.0,
            size=3.0,
            rate=4.0,
            lifetime=5.0,
        ).write_to(controller.draft)
        workspace, _controller, _confirmations = self._workspace(controller)
        workspace.choose_effect("")
        workspace._staged = EffectWorkspaceState(
            stem="",
            scale=7.0,
            offset=(1.0, 2.0, 3.0),
            color=(0.1, 0.2, 0.3),
            intensity=4.0,
        )
        self.assertTrue(workspace.apply_staged())
        self.assertEqual(EffectWorkspaceState.from_draft(controller.draft), EffectWorkspaceState.defaults())

    def test_an_external_commit_updates_a_clean_workspace_without_overwriting_dirty_staging(self) -> None:
        workspace, controller, _confirmations = self._workspace()
        committed = EffectWorkspaceState(stem="fx_fire_hit", scale=0.5)
        committed.write_to(controller.draft)
        controller.effect_changed.emit(committed)
        self.assertEqual(workspace.staged_state, committed)
        self.assertEqual(
            workspace.library_view.currentIndex().data(EffectLibraryModel.StemRole),
            committed.stem,
        )
        self.assertTrue(workspace.selection_timer.isActive())

        workspace.choose_effect("fx_frost_loop")
        newer = EffectWorkspaceState(stem="fx_fire_ring_loop", scale=0.25)
        newer.write_to(controller.draft)
        controller.effect_changed.emit(newer)
        self.assertEqual(workspace.staged_state.stem, "fx_frost_loop")

    def test_search_category_and_loop_filters_are_combined(self) -> None:
        workspace, _controller, _confirmations = self._workspace()
        workspace.category_buttons["Fire"].click()
        workspace.loop_only.click()
        stems = [workspace.library_model.row(row).stem for row in range(workspace.library_model.rowCount())]
        self.assertEqual(stems, ["", "fx_fire_ring_loop"])
        workspace.choose_effect("fx_frost_loop")
        stems = [workspace.library_model.row(row).stem for row in range(workspace.library_model.rowCount())]
        self.assertEqual(stems, ["", "fx_fire_ring_loop", "fx_frost_loop"], "the current selection stays visible")

    def test_category_chips_reflow_without_clipping_at_the_supported_narrow_width(self) -> None:
        workspace, _controller, _confirmations = self._workspace()
        workspace.resize(1280, 720)
        self.app.processEvents()
        self.assertLess(workspace._category_columns, len(workspace.category_buttons))
        for button in workspace.category_buttons.values():
            required_text = button.fontMetrics().horizontalAdvance(button.text()) + 18
            self.assertGreaterEqual(button.width(), required_text, button.text())

    def test_logarithmic_factor_mapping_has_one_in_the_centre(self) -> None:
        self.assertEqual(EffectPlacementWorkspace._factor_to_slider(0.05), -1000)
        self.assertEqual(EffectPlacementWorkspace._factor_to_slider(1.0), 0)
        self.assertEqual(EffectPlacementWorkspace._factor_to_slider(20.0), 1000)
        self.assertAlmostEqual(EffectPlacementWorkspace._slider_to_factor(0), 1.0)

    def test_incomplete_effect_metadata_forces_shipped_look_but_keeps_placement(self) -> None:
        workspace, controller, _confirmations = self._workspace()
        workspace._rebuild_preview()
        controller.effect_facts = lambda _stem: SimpleNamespace(walk_note="unexpected marker at byte 418")
        workspace._staged = EffectWorkspaceState(
            stem="fx_fire_hit",
            scale=2.0,
            offset=(0.1, 0.2, 0.3),
            color=(0.4, 0.5, 0.6),
            intensity=3.0,
            size=4.0,
            rate=5.0,
            lifetime=6.0,
        )

        workspace._sync_placement_from_state()

        self.assertEqual((workspace.staged_state.scale, workspace.staged_state.offset), (2.0, (0.1, 0.2, 0.3)))
        self.assertEqual(
            (
                workspace.staged_state.color,
                workspace.staged_state.intensity,
                workspace.staged_state.size,
                workspace.staged_state.rate,
                workspace.staged_state.lifetime,
            ),
            (None, 1.0, 1.0, 1.0, 1.0),
        )
        self.assertEqual(workspace.placement.decoder_reason, "unexpected marker at byte 418")

    def test_controller_commits_the_complete_staged_effect_exactly_once(self) -> None:
        controller = NewItemStudioController(synchronous=True)
        invalidated = []
        changed = []
        controller.plan_invalidated.connect(lambda: invalidated.append(True))
        controller.effect_changed.connect(changed.append)
        state = EffectWorkspaceState(
            stem="fx_fire_loop",
            scale=1.25,
            offset=(1.0, 2.0, 3.0),
            rotation=(10.0, 20.0, 30.0),
            color=(0.2, 0.4, 0.6),
            intensity=1.5,
            size=0.8,
            rate=1.2,
            lifetime=2.0,
        )

        self.assertTrue(controller.commit_effect_workspace(state))
        self.assertEqual(EffectWorkspaceState.from_draft(controller.draft), state)
        self.assertEqual(invalidated, [True])
        self.assertEqual(changed, [state])
        self.assertFalse(controller.commit_effect_workspace(state))
        self.assertEqual(invalidated, [True])
        self.assertEqual(changed, [state])

    def test_effect_index_runs_on_a_dedicated_lane_and_publishes_progress(self) -> None:
        from unittest.mock import patch

        snapshot = SimpleNamespace(effect_stems=frozenset({"fx_one"}), entries={})
        controller = NewItemStudioController(synchronous=False)
        controller.snapshot = snapshot
        progress = []
        ready = []
        controller.effect_catalogue_progress.connect(lambda done, total, stem: progress.append((done, total, stem)))
        controller.effect_catalogue_ready.connect(lambda: ready.append(True))

        def build(_snapshot, *, on_log, on_progress, stop_event):
            self.assertFalse(stop_event.is_set())
            on_progress(1, 1, "fx_one")
            on_log("indexed")
            return EffectCatalogue(signature="1:1:0")

        with patch("cdmw.workers.effect_catalogue_worker.build_effect_catalogue", side_effect=build):
            self.assertTrue(controller.start_effect_index())
            self.assertFalse(controller.busy, "catalogue work does not occupy the plan/import lane")
            self._settle(lambda: bool(ready) and not controller.iter_shutdown_workers())
        self.assertEqual(progress, [(1, 1, "fx_one")])
        self.assertIsNotNone(controller.effect_catalogue)
        controller.request_shutdown()

    def test_cache_load_build_and_atomic_save_all_stay_on_the_catalogue_worker(self) -> None:
        from unittest.mock import patch

        snapshot = SimpleNamespace(effect_stems=frozenset({"fx_one"}), entries={})
        controller = NewItemStudioController(synchronous=False)
        controller.snapshot = snapshot
        main_thread = QThread.currentThread()
        calls = []
        ready = []
        with tempfile.TemporaryDirectory() as folder:
            controller.effect_cache_path = Path(folder) / "effect_catalogue.json"

            def load(_path, *, signature):
                calls.append(("load", QThread.currentThread(), signature))
                return None

            def build(_snapshot, *, on_log, on_progress, stop_event):
                calls.append(("build", QThread.currentThread(), ""))
                return EffectCatalogue(signature="1:0:0")

            def save(_catalogue, _path):
                calls.append(("save", QThread.currentThread(), ""))

            controller.effect_catalogue_ready.connect(lambda: ready.append(True))
            with (
                patch("cdmw.workers.effect_catalogue_worker.load_effect_catalogue", side_effect=load),
                patch("cdmw.workers.effect_catalogue_worker.save_effect_catalogue", side_effect=save),
                patch("cdmw.workers.effect_catalogue_worker.build_effect_catalogue", side_effect=build),
            ):
                self.assertTrue(controller.start_effect_index())
                self._settle(lambda: bool(ready) and not controller.iter_shutdown_workers())

        self.assertEqual([name for name, _thread, _value in calls], ["load", "build", "save"])
        self.assertTrue(all(thread is not main_thread for _name, thread, _value in calls))
        controller.request_shutdown()

    def test_cancelled_and_stale_catalogue_results_are_never_published(self) -> None:
        from unittest.mock import patch

        first = SimpleNamespace(effect_stems=frozenset({"fx_one"}), entries={})
        second = SimpleNamespace(effect_stems=frozenset({"fx_two"}), entries={})
        started = threading.Event()
        release = threading.Event()
        controller = NewItemStudioController(synchronous=False)
        controller.snapshot = first
        ready = []
        controller.effect_catalogue_ready.connect(lambda: ready.append(True))

        def build(_snapshot, *, on_log, on_progress, stop_event):
            started.set()
            while not release.wait(0.01):
                if stop_event.is_set():
                    raise RuntimeError("Effect indexing cancelled.")
            return EffectCatalogue(signature="1:1:0")

        with patch("cdmw.workers.effect_catalogue_worker.build_effect_catalogue", side_effect=build):
            controller.start_effect_index()
            self._settle(started.is_set)
            controller.snapshot = second
            release.set()
            self._settle(lambda: not controller.iter_shutdown_workers())
        self.assertEqual(ready, [])
        self.assertIsNone(controller.effect_catalogue)

        stopped = threading.Event()

        def cancellable(_snapshot, *, on_log, on_progress, stop_event):
            started.set()
            while not stop_event.wait(0.01):
                pass
            stopped.set()
            raise RuntimeError("Effect indexing cancelled.")

        started.clear()
        controller = NewItemStudioController(synchronous=False)
        controller.snapshot = second
        with patch("cdmw.workers.effect_catalogue_worker.build_effect_catalogue", side_effect=cancellable):
            controller.start_effect_index()
            self._settle(started.is_set)
            controller.request_shutdown()
            self._settle(lambda: stopped.is_set() and not controller.iter_shutdown_workers())

    def test_restarting_the_same_catalogue_snapshot_is_a_no_op(self) -> None:
        from unittest.mock import patch

        snapshot = SimpleNamespace(effect_stems=frozenset({"fx_one"}), entries={})
        started = threading.Event()
        release = threading.Event()
        calls = []
        controller = NewItemStudioController(synchronous=False)
        controller.snapshot = snapshot

        def build(_snapshot, *, on_log, on_progress, stop_event):
            calls.append(stop_event)
            started.set()
            release.wait(2.0)
            return EffectCatalogue(signature="1:1:0")

        with patch("cdmw.workers.effect_catalogue_worker.build_effect_catalogue", side_effect=build):
            self.assertTrue(controller.start_effect_index())
            self._settle(started.is_set)
            self.assertTrue(controller.start_effect_index())
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0].is_set())
            release.set()
            self._settle(lambda: not controller.iter_shutdown_workers())
        controller.request_shutdown()


if __name__ == "__main__":
    unittest.main()
