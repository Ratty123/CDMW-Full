"""Lifecycle, refresh, template-search, and report cases for the New Item Studio tab."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.archive_format import parse_archive_pamt  # noqa: E402
from cdmw.domain.new_item.spec import UNLIMITED_STOCK, MaterialRoute, ModelSource, PlacementKind, SheathedModel  # noqa: E402
from cdmw.services.new_item_service import NewItemService  # noqa: E402
from cdmw.ui.new_item.state import (  # noqa: E402
    NewItemDraft,
    flat_grid_values,
    scaled_grid_values,
    spec_from_draft,
    stat_edits_from_grid,
    stat_grid_for,
    with_template,
)
from cdmw.ui.new_item.workflow_header import WorkflowStepState  # noqa: E402
from test_iteminfo_row import COPPER, DDD, build_row  # noqa: E402
from test_new_item_service import OTHER, TEMPLATE, _read, build_package, synthetic_files  # noqa: E402


class _TabLifecycleMixin:
    def test_an_install_reads_the_archives_again(self) -> None:
        """The installed item is only in the snapshot after a re-read, so the studio does
        one itself; without it the next item would be allocated the same key."""

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        reread = []
        with patch.object(tab.controller, "start_snapshot", side_effect=lambda entries, **kwargs: reread.append((tuple(entries), kwargs)) or True):
            tab._reread_after_install()
        self.assertEqual(len(reread), 1)
        self.assertTrue(reread[0][0], "the mounted studio refreshes even though a snapshot is already ready")
        self.assertIn("own key and stem", tab.output_panel.log.toPlainText())
        tab.close()
        tab.deleteLater()

    def test_post_install_snapshot_completion_preserves_group_picker_items(self) -> None:
        """A reread updates archive data without rebuilding the unchanged group picker."""

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        group_list = tab.placement_panel.group_list
        original_snapshot = tab.controller.snapshot
        original_groups = tuple((group.key, group.name) for group in original_snapshot.item_groups)
        original_items = tuple(group_list.item(row) for row in range(group_list.count()))
        self.assertTrue(original_items)

        tab._reread_after_install()

        self.assertIsNot(tab.controller.snapshot, original_snapshot, "the real snapshot task completed")
        self.assertEqual(
            tuple((group.key, group.name) for group in tab.controller.snapshot.item_groups),
            original_groups,
            "installing an item changes group membership, not the group catalogue",
        )
        self.assertEqual(group_list.count(), len(original_items))
        for row, item in enumerate(original_items):
            self.assertIs(
                group_list.item(row),
                item,
                "the post-install reread must not release and recreate unchanged Qt item wrappers",
            )
        tab.close()
        tab.deleteLater()

    def test_every_plan_input_clears_a_ready_plan(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        controller = tab.controller

        def remember_dummy_plan() -> None:
            controller.plan = object()
            controller._plan_revision = controller._draft_revision

        remember_dummy_plan()
        tab.identity_panel.internal_name.setText("Changed_identity")
        self.assertIsNone(controller.plan)

        remember_dummy_plan()
        tab.model_panel.icon_source.setText(str(self.root / "icons"))
        self.assertIsNone(controller.plan)

        remember_dummy_plan()
        tab.stats_panel.scale.setValue(1.25)
        tab.stats_panel._apply_scale()
        self.assertIsNone(controller.plan)
        tab.close()
        tab.deleteLater()

    def test_a_plan_finishing_after_an_edit_is_discarded(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.controller import NewItemStudioController

        service = NewItemService()
        snapshot = service.build_snapshot(self.entries, read_entry=_read)
        controller = NewItemStudioController(service=service, read_entry=_read)
        controller.snapshot = snapshot
        controller.set_template(TEMPLATE)
        controller.draft.internal_name = "First_Name"
        controller.draft.display_names = {"eng": "First"}
        ready_plan = service.plan(controller.current_spec(), snapshot)
        release = threading.Event()

        def delayed_task(_log, _stop):
            release.wait(1.0)
            return ready_plan

        with patch("cdmw.ui.new_item.controller.plan_task", return_value=delayed_task):
            self.assertTrue(controller.start_plan())
            controller.draft.internal_name = "Changed_After_Plan"
            controller.invalidate_plan()
            release.set()
            deadline = time.monotonic() + 2.0
            while controller._thread is not None and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertIsNone(controller.plan)
        self.assertNotIn(ready_plan.spec.item_key, controller.issued_keys)
        controller.shutdown()

    def test_controller_shutdown_does_not_wait_for_a_running_task(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.controller import NewItemStudioController

        controller = NewItemStudioController()

        def slow_task(_log, _stop):
            time.sleep(0.2)
            return None

        self.assertTrue(controller._run("slow", slow_task, lambda _result: None, lambda _message: None))
        deadline = time.monotonic() + 1.0
        while (controller._thread is None or not controller._thread.isRunning()) and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        started = time.monotonic()
        controller.shutdown()
        self.assertLess(time.monotonic() - started, 0.08)
        self.assertTrue(controller.iter_shutdown_workers())
        while controller._thread is not None and time.monotonic() < deadline + 1.0:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertEqual(controller.iter_shutdown_workers(), ())

    def test_model_operation_progress_and_cancel_are_correlated(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.controller import NewItemStudioController

        controller = NewItemStudioController()
        progress = []
        errors = []
        completed = []
        statuses = []
        controller.operation_progress.connect(lambda *values: progress.append(values))
        controller.status_message.connect(lambda *values: statuses.append(values))

        def task(_log, report, stop_event):
            report(1, 3, "Transforming mesh")
            while not stop_event.wait(0.005):
                pass
            report(2, 3, "Late progress must not replace Cancelling")
            return object()

        self.assertTrue(
            controller._run(
                "model_apply",
                task,
                completed.append,
                errors.append,
                task_accepts_progress=True,
            )
        )
        deadline = time.monotonic() + 2.0
        while not progress and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertTrue(controller.cancel_operation("model_apply"))
        while controller._thread is not None and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertIn(("model_apply", 1, 3, "Transforming mesh"), progress)
        self.assertTrue(any(values[-1] == "Cancelling…" for values in progress))
        self.assertFalse(any(values[-1].startswith("Late progress") for values in progress))
        self.assertEqual(completed, [])
        self.assertEqual(errors, [])
        self.assertIn(("Operation cancelled.", False), statuses)
        self.assertEqual(controller.iter_shutdown_workers(), ())

    def test_a_builder_result_handed_in_directly_and_the_material_route(self) -> None:
        """`receive_imported_model` takes a ready Builder result (code can hand one in);
        the material route and the sheath are an imported model's questions."""

        from types import SimpleNamespace

        from cdmw.services.new_item_planning import ModelFiles

        tab = self._tab(window=SimpleNamespace())
        tab.prefill_template(TEMPLATE)
        with patch("cdmw.ui.new_item.panels_model.QFileDialog.getOpenFileName", return_value=("", "")):
            tab.model_panel.import_button.click()
        self.assertIsNone(tab.controller.model_import, "cancelling the file dialog imports nothing")
        entry = tab.controller.template_entries()[0]
        self.assertFalse(tab.model_panel.plain_pbr.isEnabled(), "the material route is an imported model's question")
        tab.receive_imported_model(entry, ModelFiles(pac_data=b"PAC imported"), scene=None)
        self.assertTrue(tab.model_panel.import_model.isChecked())
        self.assertEqual(tab.controller.draft.model_source, ModelSource.IMPORTED)
        self.assertTrue(tab.model_panel.plain_pbr.isEnabled())
        self.assertTrue(tab.model_panel.plain_pbr.isChecked(), "the plain PBR shaders by default")
        self.assertEqual(tab.controller.draft.material_route, MaterialRoute.PLAIN_PBR)
        self.assertEqual(tab.controller.current_spec().material_route, MaterialRoute.PLAIN_PBR)
        tab.model_panel.plain_pbr.setChecked(False)
        self.assertEqual(tab.controller.draft.material_route, MaterialRoute.BUILDER)
        tab.model_panel.plain_pbr.setChecked(True)
        self.assertTrue(tab.model_panel.own_sheath.isChecked() and tab.model_panel.own_sheath.isEnabled())
        self.assertEqual(tab.controller.current_spec().sheathed_model, SheathedModel.OWN_MODEL)
        tab.model_panel.own_sheath.setChecked(False)
        self.assertEqual(tab.controller.draft.sheathed_model, SheathedModel.TEMPLATE)
        tab.model_panel.own_sheath.setChecked(True)
        tab.identity_panel.internal_name.setText("Ziane_Clone_OneHandSword")
        tab.identity_panel.display_name.setText("X")
        tab.output_panel.build_button.click()
        plan = tab.controller.plan
        self.assertIsNotNone(plan, tab.output_panel.summary.toPlainText())
        self.assertTrue(any(path.endswith("cd_phm_01_sword_9109.pac") for path in plan.new_paths))
        tab.model_panel.clear_button.click()
        self.assertEqual(tab.controller.draft.model_source, ModelSource.TEMPLATE)
        tab.close()
        tab.deleteLater()


    def test_a_busy_operation_after_the_panels_are_built_does_not_touch_the_bootstrap(self) -> None:
        """The bootstrap's progress bar is deleted when the panels replace it, and
        `busy_changed` goes on firing for every operation after that -- importing a model
        is one. A lambda was still calling setVisible on the deleted C++ object, which took
        the app down with `libshiboken: Internal C++ object already deleted`. A lambda also
        has no receiver for Qt to disconnect when the widget dies, which is why it survived
        to be called at all."""

        import inspect

        from PySide6.QtCore import QEvent

        import shiboken6

        from cdmw.ui.new_item.tab import NewItemStudioTab

        source = inspect.getsource(NewItemStudioTab.__init__)
        self.assertIn("busy_changed.connect(self._bootstrap_busy_changed)", source, "a slot Qt can disconnect")
        self.assertNotIn("lambda busy:", source, "not a lambda that outlives the widget it touches")

        tab = self._tab(window=None)
        progress = tab._progress
        tab.prefill_template(TEMPLATE)
        self.assertTrue(tab._panels_built, "the panels replaced the bootstrap")
        # deleteLater only runs when the loop processes deferred deletions, and the C++
        # object has to be gone for this to be the failure the reader hit
        self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(shiboken6.isValid(progress), "the bootstrap's progress bar is gone")

        # what an import does. Neither the slot nor the signal may touch what is gone.
        tab._bootstrap_busy_changed(True)
        tab._bootstrap_busy_changed(False)
        tab.controller.busy_changed.emit(True)
        tab.controller.busy_changed.emit(False)
        self.app.processEvents()
        tab.close()
        tab.deleteLater()

    def test_effect_character_uses_the_template_rig_and_keeps_armour_in_bind_space(self) -> None:
        """The escaped helmet bug: armour bypasses the hand and keeps its upright axes."""

        from types import SimpleNamespace

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.services.effect_character_reference import CharacterReference
        from cdmw.ui.new_item.controller import NewItemStudioController

        def body(model: str) -> ParsedMesh:
            vertices = [(0.0, 0.0, 0.0), (0.2, 1.75, 0.0), (-0.2, 1.75, 0.0)]
            return ParsedMesh(
                path=f"{model}_body.pac",
                format="pac",
                submeshes=[SubMesh(name=model, vertices=vertices, faces=[(0, 1, 2)])],
                bbox_min=(-0.2, 0.0, 0.0),
                bbox_max=(0.2, 1.75, 0.0),
            )

        folders = {
            7: "character/model/1_pc/2_phw/armor/13_hel",
            8: "character/model/1_pc/2_phw/armor/20_mask",
            9: "character/model/1_pc/1_phm/armor/13_hel",
        }

        class Snapshot:
            entries = {}

            @staticmethod
            def family(key):
                return SimpleNamespace(model_folder=folders[key], parts=())

        requested: list[str] = []

        def reference_for(_snapshot, *, model_folder="", **_options):
            requested.append(model_folder)
            model = "2_phw" if "/2_phw/" in model_folder else "1_phm"
            return CharacterReference(
                body=body(model),
                body_matrix=(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                             0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0),
                socket="RHand_Socket",
                rig=f"{model}.pab",
                sources=(f"character/model/1_pc/{model}/nude/{model}_lod_0001.pac",),
            ), ""

        controller = NewItemStudioController(synchronous=True)
        controller.snapshot = Snapshot()
        with patch(
            "cdmw.services.effect_character_reference.character_reference_from_snapshot",
            side_effect=reference_for,
        ):
            controller.draft.template_key = 7
            helmet = controller.character_holding_the_item()
            controller.draft.template_key = 8
            mask = controller.character_holding_the_item()
            controller.draft.template_key = 9
            other_rig = controller.character_holding_the_item()

        self.assertEqual(requested, [folders[7], folders[9]], "one archive body read per rig")
        self.assertIs(helmet.mesh, mask.mesh, "helmet and mask share the cached PHW body")
        self.assertIsNone(helmet.item_rotation)
        self.assertEqual(helmet.held_from, "wearable")
        self.assertEqual(helmet.mesh.bbox_min[1], 0.0, "armour stays at the body's origin")
        self.assertNotEqual(other_rig.mesh.path, helmet.mesh.path)

    def test_an_imported_model_is_textured_and_listed_before_and_after_apply(self) -> None:
        """The live import owns preview materials and part names throughout the workflow;
        the Builder result owns output, not the source PBR appearance."""

        from types import SimpleNamespace

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

        def mesh(texture: str) -> ParsedMesh:
            part = SubMesh(
                name="blade", material="steel", texture=texture,
                vertices=[(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0)],
                uvs=[(0.0, 0.0)] * 3, normals=[(0.0, 1.0, 0.0)] * 3, faces=[(0, 1, 2)],
                vertex_count=3, face_count=1,
            )
            part.preview_material_texture_inputs = (texture,)
            part.preview_material_parameters = (texture,)
            return ParsedMesh(
                path="import.pac", format="pac", submeshes=[part], bbox_min=(0.0, 0.0, 0.0),
                bbox_max=(0.1, 0.1, 0.0), total_vertices=3, total_faces=1, has_uvs=True,
            )

        tab = self._tab(window=None)
        tab.prefill_template(TEMPLATE)
        controller = tab.controller
        self.assertIsNone(controller.model_result, "nothing applied yet")

        controller.model_import = SimpleNamespace(
            baked_preview_mesh=lambda: mesh("frostmourne_basecolor.png"),
            baked_scene_mesh=lambda: mesh(""),
            baked_bounds=lambda: ((0.0, 0.0, 0.0), (0.1, 0.1, 0.0)),
            # the materials the file itself declares, which is what a glow is chosen by
            scene=SimpleNamespace(material_bindings=(
                SimpleNamespace(material_name="lambert1"),
                SimpleNamespace(material_name="Inside"),
                SimpleNamespace(material_name="Inside"),
                SimpleNamespace(material_name="Outside"),
            )),
        )
        planned, kind = controller.item_mesh_as_planned()
        self.assertEqual(kind, "placed")
        self.assertEqual(
            planned.submeshes[0].texture, "frostmourne_basecolor.png",
            "the effect viewport gets the textured decode, not the bare geometry",
        )

        controller.model_result = SimpleNamespace(preview_model=object())
        with patch.object(
            controller,
            "_textured_preview_mesh",
            return_value=mesh("template_synthesized.png"),
        ) as rebuilt_material_fallback:
            planned, kind = controller.item_mesh_as_planned()
        self.assertEqual(kind, "applied")
        self.assertEqual(
            planned.submeshes[0].texture,
            "frostmourne_basecolor.png",
            "Apply must not replace Model & Placement's source materials with the rebuilt template material row",
        )
        self.assertEqual(planned.submeshes[0].preview_material_texture_inputs, ("frostmourne_basecolor.png",))
        self.assertEqual(planned.submeshes[0].preview_material_parameters, ("frostmourne_basecolor.png",))
        rebuilt_material_fallback.assert_not_called()
        controller.model_result = None

        # the parts are the model's own materials, in the order the file declares them and
        # each one once. The template's parts are never among them: `cd_phm_02_hammer_sub_0002`
        # is not a thing the reader can act on, and it is not theirs to light either.
        self.assertEqual(
            controller.material_parts(),
            (("lambert1", "lambert1"), ("Inside", "Inside"), ("Outside", "Outside")),
        )

        # and the step fills its list when the file is read, not when Apply runs: the
        # Builder result only exists after Apply, and listening for that alone left it empty
        panel = tab.model_panel
        panel.glow_parts.clear()
        controller.model_import_changed.emit(controller.model_import)
        self.assertEqual(
            [panel.glow_parts.item(row).text() for row in range(panel.glow_parts.count())],
            ["lambert1", "Inside", "Outside"],
            "importing a model fills the parts list",
        )
        tab.close()
        tab.deleteLater()

    def test_an_fbx_with_no_blender_never_starts_a_read(self) -> None:
        """It did, and that was the fault: the refusal lived at the bottom of the worker,
        so a zip was extracted whole, the reason arrived in the window's status line, and
        the step was left saying "Reading the model file..." over a read that could never
        finish. The rule is answered from the listing, before the worker exists."""

        import zipfile

        tab = self._tab(window=None)
        tab.prefill_template(TEMPLATE)
        controller = tab.controller
        panel = tab.model_panel

        holder = tempfile.TemporaryDirectory(prefix="cdmw_fbx_gate_")
        self.addCleanup(holder.cleanup)
        folder = Path(holder.name)
        archive = folder / "magic-sword.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("source/MagicSword.fbx", b"not really an fbx")

        said: list = []
        controller.status_message.connect(lambda text, bad: said.append((text, bad)))
        with patch("cdmw.ui.new_item.controller.blender_for_fbx", return_value=""):
            started = controller.start_model_import(archive)

        self.assertFalse(started, "no read is started at all")
        self.assertFalse(controller.busy, "and nothing goes busy over it")
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["magic-sword.zip"], "nothing extracted")
        self.assertTrue(said and said[-1][1], "the refusal is said as a problem")
        self.assertIn("MagicSword.fbx", said[-1][0])
        self.assertIn("Blender", said[-1][0])
        # and it lands where the reader is looking, not only in the window's status line
        self.assertIn("MagicSword.fbx", panel.model_status.text())

        # the row that answers it is directly on Model: a refusal
        # naming a button nobody can see is the same as no answer. It shows with the rest
        # of the import controls, which is the moment the question can be asked at all.
        panel.import_model.setChecked(True)
        self.assertTrue(panel.blender_holder.isVisibleTo(panel), "the Blender row shows with the import controls")
        # and it says which of the two states the studio is in (the machine running this
        # may have a Blender stored, so both are asked for rather than read off it)
        with patch("cdmw.ui.new_item.blender_setting.blender_for_fbx", return_value=""):
            panel._refresh_blender_label()
        self.assertIn("Blender is required", panel.blender_label.text())
        self.assertFalse(panel.blender_forget.isVisibleTo(panel), "nothing to forget")
        with patch("cdmw.ui.new_item.blender_setting.blender_for_fbx", return_value="C:/blender/blender.exe"):
            panel._refresh_blender_label()
        self.assertIn("C:/blender/blender.exe", panel.blender_label.text(), "which Blender, not just that there is one")
        tab.close()
        tab.deleteLater()

    def test_clicking_a_template_applies_before_navigation_settles(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        tab = self._tab(window=None)
        tab.resize(1280, 720)
        tab.show()
        tab.prefill_template(TEMPLATE)
        panel = tab.template_panel
        panel.filter_edit.clear()
        self.app.processEvents()
        target = next(
            panel.matches.topLevelItem(row)
            for row in range(panel.matches.topLevelItemCount())
            if panel.matches.topLevelItem(row).data(0, Qt.UserRole) == OTHER
        )
        panel.matches.scrollToItem(target)

        taken: list = []
        tab.controller.set_template = lambda key: taken.append(key)  # type: ignore[method-assign]
        QTest.mouseClick(
            panel.matches.viewport(),
            Qt.MouseButton.LeftButton,
            pos=panel.matches.visualItemRect(target).center(),
        )

        self.assertEqual(taken, [OTHER], "a deliberate click does not wait for the navigation timer")
        self.assertFalse(panel._pick_timer.isActive())
        self.assertIsNone(panel._pending_key)
        tab.close()
        tab.deleteLater()

    def test_template_search_normalizes_terms_and_includes_localized_item_names(self) -> None:
        from dataclasses import replace

        tab = self._tab(window=None)
        tab.prefill_template(TEMPLATE)
        panel = tab.template_panel

        panel.filter_edit.setText("fang ziane")
        self.app.processEvents()

        self.assertEqual(panel.matches.topLevelItemCount(), 1)
        self.assertEqual(
            [panel.matches.topLevelItem(0).text(column) for column in range(panel.matches.columnCount())],
            ["Ziane_OneHandSword", "Wolf's Fang", "1001295", "OneHandSword"],
        )
        self.assertEqual(
            [key for key, _internal, _item_name, _equip in tab.controller.template_options('"wolf\'s fang" OR cigar')],
            [OTHER, TEMPLATE],
        )
        self.assertEqual(
            [key for key, _internal, _item_name, _equip in tab.controller.template_options("sword -cigar")],
            [TEMPLATE],
        )
        helmet_key = 1000036
        tab.controller.snapshot.rows = {
            **tab.controller.snapshot.rows,
            helmet_key: replace(
                tab.controller.snapshot.rows[TEMPLATE],
                key=helmet_key,
                string_key="Redrin_Fabric_Helm",
                name_key="",
            ),
        }
        self.assertEqual(
            [key for key, _internal, _item_name, _equip in tab.controller.template_options("helmet red")],
            [helmet_key],
            "Archive Browser's helmet-to-helm alias and token prefixes are preserved",
        )
        self.assertEqual(
            tab.controller.template_options(limit=1)[0][0],
            OTHER,
            "the display limit is applied after the complete match set is sorted",
        )
        tab.close()
        tab.deleteLater()

    def test_template_results_load_more_on_scroll_and_sort_the_complete_match_set(self) -> None:
        from PySide6.QtCore import Qt

        tab = self._tab(window=None)
        tab.resize(1280, 720)
        tab.show()
        tab.prefill_template(TEMPLATE)
        panel = tab.template_panel
        options = [
            (10_000 + index, f"Internal_{124 - index:03}", f"Item {index:03}", "Helm")
            for index in range(125)
        ]

        def template_options(_text="", *, limit=60):
            return options if limit is None else options[:limit]

        tab.controller.template_options = template_options  # type: ignore[method-assign]

        panel.filter_edit.clear()
        panel._refresh_matches()
        self.app.processEvents()
        self.assertEqual(panel.matches.topLevelItemCount(), 60)

        scroll_bar = panel.matches.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        self.app.processEvents()
        self.assertEqual(panel.matches.topLevelItemCount(), 120)
        scroll_bar.setValue(scroll_bar.maximum())
        self.app.processEvents()
        self.assertEqual(panel.matches.topLevelItemCount(), 125)

        panel.matches.header().sectionClicked.emit(2)
        self.assertEqual(panel.matches.topLevelItem(0).data(0, Qt.UserRole), 10_000)
        panel.matches.header().sectionClicked.emit(2)
        self.assertEqual(panel.matches.topLevelItem(0).data(0, Qt.UserRole), 10_124)
        self.assertEqual(panel.matches.topLevelItemCount(), 125, "sorting retains every loaded row")
        tab.close()
        tab.deleteLater()

    def test_walking_the_template_list_rebuilds_once_the_reader_stops(self) -> None:
        """Choosing a template rebuilds five steps: 65 ms against the real archives, and
        1,926 ms before the corpus measure moved to the snapshot worker. The list asked
        for that once per row the arrow keys passed through, so holding the key down
        queued one per row and the window stopped answering."""

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem

        tab = self._tab(window=None)
        tab.prefill_template(TEMPLATE)
        panel = tab.template_panel

        taken: list = []
        tab.controller.set_template = lambda key: taken.append(key)  # type: ignore[method-assign]

        panel._syncing = True
        panel.matches.clear()
        for key in (4001, 4002, 4003):
            item = QTreeWidgetItem([f"row {key}", "", str(key), "Helm"])
            item.setData(0, Qt.UserRole, key)
            panel.matches.addTopLevelItem(item)
        panel._syncing = False

        for row in range(panel.matches.topLevelItemCount()):
            panel.matches.setCurrentItem(panel.matches.topLevelItem(row))
        self.assertEqual(taken, [], "walking the list takes nothing on the way past")
        self.assertTrue(panel._pick_timer.isActive(), "the row waits for the reader to settle")

        # and the row they stopped on is taken, once
        panel._pick_timer.stop()
        panel._apply_pick()
        self.assertEqual(taken, [4003])

        # leaving the step is settling on a row too: a pending pick is never dropped
        taken.clear()
        panel.matches.setCurrentItem(panel.matches.topLevelItem(0))
        tab._show_step(1)
        self.assertEqual(taken, [4001], "moving on takes the row the reader left on")
        self.assertFalse(panel._pick_timer.isActive())
        tab.close()
        tab.deleteLater()

    def test_the_parts_that_glow_are_chosen_on_the_step(self) -> None:
        """A template's own emissive is not inherited -- its mask is cut for the template's
        mesh, and what the importer generates in its place is flat, so inheriting it lit a
        whole imported sword. A glow is asked for, part by part."""

        from PySide6.QtCore import Qt

        tab = self._tab(window=None)
        tab.prefill_template(TEMPLATE)
        panel = tab.model_panel
        self.assertFalse(panel.glow_box.isChecked(), "nothing glows unless it is asked for")
        self.assertTrue(all(widget.isHidden() for widget in panel._glow_detail_widgets))
        self.assertEqual(tab.controller.current_spec().glow, None)

        # nothing to glow until a model is imported: the route that writes a glow runs
        # only for one, so the group stays shut
        self.assertFalse(panel.glow_box.isEnabled())
        self.assertIn("Import a model", panel.glow_box.toolTip())

        # the parts are the imported model's own materials, keyed by the wrapper name the
        # file uses and labelled by the name the reader gave them
        parts = (("cd_phm_01_sword_0109", "blade"), ("cd_phm_01_sword_handle_0109", "grip"))
        tab.controller.material_parts = lambda: parts  # type: ignore[method-assign]
        panel.refresh_glow_parts()
        self.assertEqual([panel.glow_parts.item(row).text() for row in range(panel.glow_parts.count())], ["blade", "grip"])
        self.assertTrue(panel.glow_box.isEnabled())
        self.assertTrue(all(widget.isHidden() for widget in panel._glow_detail_widgets))

        panel.glow_box.setChecked(True)
        self.assertTrue(all(not widget.isHidden() for widget in panel._glow_detail_widgets))
        panel.glow_parts.item(0).setCheckState(Qt.CheckState.Checked)
        panel.glow_intensity.setValue(6.5)
        tab.controller.draft.glow_color = (0.0, 0.5, 1.0)
        glow = tab.controller.current_spec().glow
        self.assertEqual(glow.parts, (parts[0][0],), "the plan is given the wrapper name, not the label")
        self.assertEqual(glow.intensity, 6.5)
        self.assertEqual(glow.hex_color(), "#0080FFFF")

        panel.glow_box.setChecked(False)
        self.assertTrue(all(widget.isHidden() for widget in panel._glow_detail_widgets))
        self.assertIsNone(tab.controller.current_spec().glow, "turned off, nothing glows again")
        tab.close()
        tab.deleteLater()

class InstallReportTests(unittest.TestCase):
    """Step 7's four buttons all report through one signal, and they hand back four
    different kinds of result. Before this, three of them said "Installed 0 archive
    entr(ies)", which reads like a failure after a button that did its work."""

    def test_each_route_says_what_it_did(self) -> None:
        from cdmw.services.archive_overlay_install import OverlayInstallResult
        from cdmw.services.archive_overlay_migration import MigrationPlan, MigrationResult, RemovalResult
        from cdmw.ui.new_item.panels_output import install_result_report

        title, message = install_result_report(
            OverlayInstallResult(Path("g/0036"), 1, 27, 113_457_995, 4, Path("b/1"), ())
        )
        self.assertEqual(title, "Install as an overlay")
        self.assertIn("0036", message)
        self.assertIn("27 file(s)", message)
        self.assertIn("4 of them carried forward", message)
        self.assertIn("were not written to", message)

        title, message = install_result_report(MigrationResult(Path("g/0036"), 12, (Path("a"), Path("b")), Path("b/2"), 5_000))
        self.assertEqual(title, "Move installed items into the overlay")
        self.assertIn("Moved 12 file(s)", message)
        self.assertIn("2 archive file(s)", message)

        title, message = install_result_report(MigrationPlan((), (), ()))
        self.assertEqual(title, "Move installed items into the overlay")
        self.assertIn("Nothing to move", message)

        title, message = install_result_report(RemovalResult(Path("g/0036"), True, 2, Path("b/3")))
        self.assertEqual(title, "Remove the overlay")
        self.assertIn("Removed the overlay 0036", message)
        self.assertIn("gone from the game", message)

        # the texture registry is a loose file the overlay rewrote in place, so a removal
        # that put it back has to say so
        title, message = install_result_report(RemovalResult(Path("g/0036"), True, 2, Path("b/3"), ("meta/0.pathc",)))
        self.assertIn("meta/0.pathc", message)
        self.assertIn("back to what the game shipped", message)

        title, message = install_result_report(RemovalResult(None, False, 0, None))
        self.assertIn("no overlay to remove", message)

        class _Patched:
            changed_paths = ("a", "b", "c")
            backup_dir = Path("b/4")

        title, message = install_result_report(_Patched())
        self.assertEqual(title, "Install into the game archives")
        self.assertIn("Installed 3 archive entr(ies)", message)
