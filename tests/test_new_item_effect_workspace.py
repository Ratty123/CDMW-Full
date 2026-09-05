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

    def item_effect_preview_source(self):
        return lambda _stop: self.item_mesh_as_planned()

    def effect_box(self, _stem):
        return (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)

    def effect_preview_for_placement(self, _stem, _state=None):
        return None, None

    def character_holding_the_item(self, *, stop_event=None):
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
    item_mesh_ready = Signal(object, str)

    def __init__(self, parent=None, **kwargs) -> None:
        super().__init__(parent)
        self.host = None
        self._host_error = "renderer missing"
        self._renderer_failed = True
        self.status = QLabel("")
        self.apply_button = QPushButton("Apply placement")
        self.discard_button = QPushButton("Discard")
        self.staging_state = QLabel("")
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
        self.cancelled_content = 0
        self.character_fit_control = kwargs.get("character_fit_control")
        from PySide6.QtCore import QTimer

        self.item_timer = QTimer(self)
        self.item_timer.setSingleShot(True)
        self.item_timer.timeout.connect(self._finish_content)
        self._queue_content(kwargs, initial=True)

    def _queue_content(self, kwargs, *, initial=False):
        self._pending_content = (dict(kwargs), initial)
        self.item_timer.start(0)

    def cancel_pending_content(self):
        self.cancelled_content += 1
        self.item_timer.stop()

    def _finish_content(self):
        import threading

        kwargs, initial = self._pending_content
        builder = kwargs.get("item_mesh_builder")
        mesh, label = builder(threading.Event()) if callable(builder) else (kwargs.get("item_mesh"), "")
        kwargs["item_mesh"] = mesh
        if not initial:
            self.content_calls.append(kwargs)
        self.item_mesh_ready.emit(mesh, label)

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
        self._queue_content(kwargs)

    def iter_shutdown_workers(self):
        return ()

    def request_shutdown(self):
        self.item_timer.stop()


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
        self._settle(lambda: not workspace._library_timer.isActive())
        return workspace, controller, confirmations

    def _settle(self, predicate, timeout_ms=5000):
        deadline = QDeadlineTimer(timeout_ms)
        while not predicate() and not deadline.hasExpired():
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 25)
        self.assertTrue(predicate())

    def test_large_library_yields_before_labels_and_reuses_rows_for_filters(self) -> None:
        from unittest.mock import patch

        controller = _Controller()
        controller.stems = tuple(f"fx_fire_{index:05d}_loop" for index in range(20_000))
        with patch.object(controller, "effect_facts", wraps=controller.effect_facts) as facts:
            workspace = GuidedEffectsWorkspace(controller, placement_factory=_Placement)
            self.addCleanup(workspace.deleteLater)
            self.addCleanup(workspace.request_shutdown)
            self.assertEqual(facts.call_count, 0, "mounting the page must not format the entire library")
            self._settle(lambda: not workspace._library_timer.isActive())
            self.assertEqual(workspace.library_model.rowCount(), 20_001)
            prepared = facts.call_count
            workspace.search.setText("fire 001")
            workspace.loop_only.click()
            workspace.category_buttons["Fire"].click()
            self.assertEqual(facts.call_count, prepared, "filtering must reuse prepared facts and labels")
            self.assertGreater(workspace.library_model.rowCount(), 1)

    def test_replaced_library_build_cannot_publish_old_rows(self) -> None:
        controller = _Controller()
        controller.stems = tuple(f"fx_old_{index}" for index in range(20_000))
        workspace = GuidedEffectsWorkspace(controller, placement_factory=_Placement)
        self.addCleanup(workspace.deleteLater)
        self.addCleanup(workspace.request_shutdown)
        workspace._advance_library()
        controller.stems = ("fx_new_fire_loop",)
        controller.effect_catalogue_ready.emit()
        self._settle(lambda: not workspace._library_timer.isActive())
        self.assertEqual(workspace.library_model.rowCount(), 2)
        self.assertEqual(workspace.library_model.row(1).stem, "fx_new_fire_loop")

    def test_shutdown_cancels_pending_library_preparation(self) -> None:
        controller = _Controller()
        controller.stems = tuple(f"fx_fire_{index}" for index in range(20_000))
        workspace = GuidedEffectsWorkspace(controller, placement_factory=_Placement)
        self.addCleanup(workspace.deleteLater)
        workspace.request_shutdown()
        controller.effect_catalogue_ready.emit()
        self.app.processEvents()
        self.assertFalse(workspace._library_timer.isActive())
        self.assertIsNone(workspace._library_build)
        self.assertEqual(workspace.library_model.rowCount(), 1)

    def test_hidden_effects_page_does_not_decode_the_item(self) -> None:
        from unittest.mock import patch

        controller = _Controller()
        with patch.object(controller, "item_mesh_as_planned", wraps=controller.item_mesh_as_planned) as decode:
            workspace = GuidedEffectsWorkspace(controller, placement_factory=_Placement)
            self.addCleanup(workspace.deleteLater)
            self.addCleanup(workspace.request_shutdown)
            controller.model_changed.emit(None)
            workspace._rebuild_preview()
            self.app.processEvents()
            self.assertEqual(decode.call_count, 0)
            workspace.show()
            self._settle(lambda: workspace.placement is not None)
            self.assertEqual(decode.call_count, 1)
            self.assertFalse(workspace.selection_timer.isActive(), "showing must queue only one initial preview")
            workspace.hide()
            controller.model_changed.emit(None)
            workspace._rebuild_preview()
            self.assertEqual(decode.call_count, 1)

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

    def test_compatibility_target_count_uses_complete_plural_messages(self) -> None:
        workspace, controller, _confirmations = self._workspace()
        controller.effect_target_compatibility = lambda _stem: SimpleNamespace(
            supported=True,
            target_prefabs=("one",),
            errors=(),
        )
        workspace.choose_effect("fx_fire_hit")
        self.app.processEvents()
        self.assertEqual(workspace.compatibility_label.text(), "Compatible  ·  1 target")

        controller.effect_target_compatibility = lambda _stem: SimpleNamespace(
            supported=True,
            target_prefabs=("one", "two"),
            errors=(),
        )
        workspace._refresh_compatibility()
        self.assertEqual(workspace.compatibility_label.text(), "Compatible  ·  2 targets")

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

    def test_unchanged_library_rows_preserve_the_selected_model_index(self) -> None:
        from dataclasses import replace
        from PySide6.QtCore import QPersistentModelIndex

        model = EffectLibraryModel()
        rows = (EffectLibraryRow.from_stem("fx_fire_hit", None),)
        model.replace_rows(rows)
        selected = QPersistentModelIndex(model.index(0, 1))
        resets = []
        model.modelReset.connect(lambda: resets.append(True))

        model.replace_rows(tuple(replace(row) for row in rows))
        self.assertTrue(selected.isValid(), "an unchanged library must retain selection and layout")
        self.assertEqual(resets, [])

        model.replace_rows((replace(rows[0], label="Updated fire"),))
        self.assertEqual(resets, [True])
        self.assertEqual(model.data(model.index(0, 1)), "Updated fire")

    def test_hidden_library_column_sizing_samples_a_bounded_number_of_rows(self) -> None:
        from unittest.mock import patch
        from PySide6.QtWidgets import QHeaderView

        workspace, _controller, _confirmations = self._workspace()
        workspace.hide()
        rows = tuple(EffectLibraryRow.from_stem(f"fx_{index:04d}", None) for index in range(6000))
        workspace.library_model.replace_rows(rows)
        inspected = set()
        original = EffectLibraryModel.data

        def data(model, index, role=int(Qt.ItemDataRole.DisplayRole)):
            inspected.add(index.row())
            return original(model, index, role)

        with patch.object(EffectLibraryModel, "data", data):
            workspace.library_view.horizontalHeader().resizeSections(QHeaderView.ResizeMode.ResizeToContents)
        self.assertLess(len(inspected), 128, "hidden metadata columns must not measure the whole catalogue")

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

        self._settle(lambda: workspace.staged_state.offset == (0.01, 1.76, -0.05))
        self.assertEqual(workspace.staged_state.offset, (0.01, 1.76, -0.05))
        self.assertEqual(workspace.placement.offset, (0.01, 1.76, -0.05))
        self.assertTrue(workspace.has_staged_changes(), "the head-height default is saved on Apply")

    def test_leaving_effects_during_item_preparation_does_not_stage_a_late_origin(self) -> None:
        controller = _Controller()
        helmet = _mesh()
        helmet._cdmw_effect_item_origin = (0.01, 1.76, -0.05)
        controller.item_mesh_as_planned = lambda: (helmet, "applied")
        workspace, _controller, _confirmations = self._workspace(controller)
        workspace.choose_effect("fx_fire_hit")
        workspace.selection_timer.stop()
        workspace._rebuild_preview()
        workspace.hide()
        self.app.processEvents()
        self.assertEqual(workspace.staged_state.offset, (0.0, 0.0, 0.0))
        workspace.show()
        self._settle(lambda: workspace.staged_state.offset == (0.01, 1.76, -0.05))

    def test_show_retries_a_transient_selected_template_preview(self) -> None:
        controller = _Controller()
        calls = 0

        def item_mesh_as_planned():
            nonlocal calls
            calls += 1
            return (None, "template") if calls == 1 else (_mesh(), "template")

        controller.item_mesh_as_planned = item_mesh_as_planned
        workspace, _controller, _confirmations = self._workspace(controller)
        self._settle(lambda: calls >= 2)
        self.assertGreaterEqual(calls, 2)
        self.assertFalse(workspace.placeholder.isVisibleTo(workspace))

    def test_show_reuses_an_unchanged_resident_preview(self) -> None:
        workspace, _controller, _confirmations = self._workspace()
        self._settle(lambda: workspace.placement is not None)
        workspace.selection_timer.stop()
        workspace.look_timer.stop()
        workspace._initial_preview_timer.stop()
        workspace.placement.content_calls.clear()
        workspace.placement._renderer_failed = False

        workspace.hide()
        self.app.processEvents()
        workspace.show()
        self.app.processEvents()
        self._settle(lambda: not workspace.placement.item_timer.isActive())

        self.assertFalse(workspace._initial_preview_timer.isActive())
        self.assertEqual(workspace.placement.content_calls, [], "returning to Effects must keep its resident scene")

        workspace.placement._content_failed = True
        workspace.hide()
        self.app.processEvents()
        workspace.show()
        self.app.processEvents()
        self._settle(lambda: not workspace.placement.item_timer.isActive())
        self.assertEqual(len(workspace.placement.content_calls), 1, "a failed content update must still retry")

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
        workspace.placement._renderer_failed = False

        updated = _mesh()
        updated.path = "item-with-new-appearance.pac"
        current["mesh"] = updated
        workspace.hide()
        controller.model_changed.emit(updated)
        self.app.processEvents()
        workspace.show()
        self.app.processEvents()

        self.assertFalse(workspace.selection_timer.isActive(), "re-entering Effects must not schedule a duplicate preview")
        self._settle(lambda: bool(workspace.placement.content_calls))
        self.assertEqual(len(workspace.placement.content_calls), 1)
        self.assertIs(workspace.placement.content_calls[-1]["item_mesh"], updated)

    def test_source_change_invalidates_content_before_the_debounce_fires(self) -> None:
        workspace, controller, _confirmations = self._workspace()
        self._settle(lambda: workspace.placement is not None)
        placement = workspace.placement
        before = placement.cancelled_content
        controller.draft.template_key = 2
        controller.template_changed.emit(2)
        self.assertGreater(placement.cancelled_content, before)
        self.assertTrue(workspace.selection_timer.isActive())

    def test_character_fit_selector_rebuilds_only_the_preview_for_the_requested_rig(self) -> None:
        controller = _Controller()
        requested: list[str] = []

        def character_holding_the_item(*, rig_model: str = "", stop_event=None):
            requested.append(rig_model)
            return None

        controller.character_holding_the_item = character_holding_the_item  # type: ignore[method-assign]
        workspace, _controller, _confirmations = self._workspace(controller)
        self._settle(lambda: workspace.placement is not None)
        workspace.selection_timer.stop()
        workspace.placement.content_calls.clear()
        original_draft = EffectWorkspaceState.from_draft(controller.draft)

        self.assertEqual(
            [
                workspace.character_fit_choice.itemText(index)
                for index in range(workspace.character_fit_choice.count())
            ],
            ["Auto", "Kliff", "Damian"],
        )
        workspace.character_fit_choice.setCurrentIndex(workspace.character_fit_choice.findData(2))
        self.assertTrue(workspace.selection_timer.isActive())
        workspace.selection_timer.stop()
        workspace._rebuild_preview()

        self._settle(lambda: bool(workspace.placement.content_calls))
        selected = workspace.placement.content_calls[-1]
        selected["character_builder"]()
        self.assertEqual(requested, ["2_phw"])
        self.assertFalse(selected["reset_view"], "switching the reference body preserves the camera")
        self.assertEqual(EffectWorkspaceState.from_draft(controller.draft), original_draft)

        workspace.character_fit_choice.setCurrentIndex(workspace.character_fit_choice.findData(0))
        workspace.selection_timer.stop()
        workspace._rebuild_preview()
        self._settle(lambda: len(workspace.placement.content_calls) == 2)
        workspace.placement.content_calls[-1]["character_builder"]()
        self.assertEqual(requested, ["2_phw", ""], "Auto keeps the template-owned callback")

        self.assertTrue(workspace.character_fit_choice.toolTip())
        self.assertIs(workspace.placement.character_fit_control, workspace.character_fit_row)
        self.assertEqual(
            workspace.placement_layout.indexOf(workspace.character_fit_row),
            -1,
            "Character shares an existing inspector row instead of reserving a full-width band",
        )
        self.assertEqual(
            workspace.placement.geometry().top(),
            0,
            "the placement preview starts at the top of its column",
        )
        controller.draft.template_key = None
        controller.template_changed.emit(None)
        self.assertFalse(
            workspace.character_fit_choice.isEnabled(),
            "there is no body-fit choice without a template",
        )

    def test_controller_caches_auto_and_explicit_character_fit_separately(self) -> None:
        from unittest.mock import patch

        controller = NewItemStudioController(synchronous=True)
        self.addCleanup(controller.deleteLater)

        class Snapshot:
            @staticmethod
            def family(_key):
                return SimpleNamespace(
                    model_folder="character/model/1_pc/1_phm/weapon/1_onehandweapon",
                    parts=(),
                )

        controller.snapshot = Snapshot()
        controller.draft.template_key = 7
        reference_requests: list[str] = []
        held_requests: list[str] = []

        def character_reference(_folder: str = "", *, rig_model: str = "", stop_event=None):
            reference_requests.append(rig_model)
            return f"reference:{rig_model or 'auto'}"

        def hold(_snapshot, reference, **_kwargs):
            held_requests.append(reference)
            return object(), ""

        controller.character_reference = character_reference  # type: ignore[method-assign]
        with patch("cdmw.services.effect_character_reference.held_character_from_snapshot", side_effect=hold):
            automatic = controller.character_holding_the_item()
            self.assertIs(controller.character_holding_the_item(), automatic)
            damian = controller.character_holding_the_item(rig_model="2_phw")
            self.assertIs(controller.character_holding_the_item(rig_model="2_phw"), damian)

        self.assertIsNot(automatic, damian)
        self.assertEqual(reference_requests, ["", "2_phw"])
        self.assertEqual(held_requests, ["reference:auto", "reference:2_phw"])

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

    def test_readable_search_reset_and_discard_preserve_the_committed_effect(self) -> None:
        workspace, controller, _ = self._workspace()
        workspace.choose_effect("fx_fire_hit")
        workspace._rebuild_preview()
        self.assertTrue(workspace.apply_staged())
        workspace.choose_effect("fx_frost_loop")
        workspace.search.setText("fire ring")
        stems = [workspace.library_model.row(row).stem for row in range(workspace.library_model.rowCount())]
        self.assertEqual(stems, ["", "fx_fire_ring_loop", "fx_frost_loop"])
        workspace.search.setText("no such effect")
        self.assertTrue(workspace.empty_results.isVisibleTo(workspace))
        self.assertEqual(workspace.staged_state.stem, "fx_frost_loop")
        workspace.reset_filters.click()
        self.assertEqual(workspace.search.text(), "")
        self.assertFalse(workspace.empty_results.isVisibleTo(workspace))
        self.assertEqual(workspace.library_model.rowCount(), 4)
        workspace.placement.discard_button.click()
        self.assertEqual(workspace.staged_state.stem, "fx_fire_hit")
        self.assertFalse(workspace.has_staged_changes())
        self.assertFalse(workspace.placement.discard_button.isEnabled())
        self.assertEqual(controller.commit_count, 1)

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
