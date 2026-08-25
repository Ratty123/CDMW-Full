"""New Item Studio: the Glow choice shown live in the step's viewport.

The export writes a ticked part as a solid map times a colour times a number; the
resident renderer draws the same three values sent as parameter overrides, so the
preview shows what the shipped item will do. These tests cover the three seams:
the groups a draft's glow becomes, the host call that sends groups with explicit
nulls intact, and the panel sync that connects them.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _parameter(name: str, *, numeric: float | None = None, value: str = "") -> SimpleNamespace:
    return SimpleNamespace(parameter_name=name, numeric_value=numeric, value=value)


def _submesh(material: str, name: str, parameters: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(material=material, name=name, preview_material_parameters=list(parameters))


def _mesh() -> SimpleNamespace:
    return SimpleNamespace(submeshes=[
        _submesh("Blade", "part_0"),
        _submesh("Gem", "part_1", (
            _parameter("_emissiveIntensity", numeric=2.0),
            _parameter("_emissiveColor", value="#00FF00"),
        )),
        _submesh("Grip", "part_2"),
    ])


def _group_for(groups, index):
    for group in groups:
        if index in group["source_submesh_indices"]:
            return group
    raise AssertionError(f"no group carries submesh {index}: {groups!r}")


class GlowPreviewGroupTests(unittest.TestCase):
    def test_a_ticked_part_takes_the_readers_colour_and_strength(self) -> None:
        from cdmw.domain.new_item.spec import GlowChoice
        from cdmw.services.new_item_materials import glow_preview_parameter_groups

        groups = glow_preview_parameter_groups(
            _mesh(), GlowChoice(parts=("blade",), color=(1.0, 0.25, 0.0), intensity=6.0)
        )
        blade = _group_for(groups, 0)
        self.assertEqual(blade["editor_role"], "replacement_preview")
        self.assertEqual(blade["emissive_intensity"], 6.0)
        self.assertEqual(blade["emissive_color"], [1.0, 0.25, 0.0])
        self.assertTrue(blade["emissive_color_authoritative"])
        # the ticked name matches the export's rule: the submesh's material, casefolded
        self.assertEqual(blade["source_submesh_indices"], [0])

    def test_an_unticked_part_goes_back_to_the_imports_own_emissive_or_nothing(self) -> None:
        from cdmw.domain.new_item.spec import GlowChoice
        from cdmw.services.new_item_materials import glow_preview_parameter_groups

        groups = glow_preview_parameter_groups(
            _mesh(), GlowChoice(parts=("blade",), color=(1.0, 1.0, 1.0), intensity=4.0)
        )
        gem = _group_for(groups, 1)
        self.assertEqual(gem["emissive_intensity"], 2.0, "the import's own declared strength")
        self.assertEqual(gem["emissive_color"], [0.0, 1.0, 0.0], "the import's own declared colour")
        grip = _group_for(groups, 2)
        self.assertIsNone(grip["emissive_intensity"], "an explicit null clears the override")
        self.assertIsNone(grip["emissive_color"])
        self.assertIsNone(grip["emissive_color_authoritative"])

    def test_no_glow_is_a_complete_restore_statement(self) -> None:
        from cdmw.services.new_item_materials import glow_preview_parameter_groups

        groups = glow_preview_parameter_groups(_mesh(), None)
        # Blade and Grip share the null group; Gem restores its own emissive
        self.assertEqual(_group_for(groups, 0), _group_for(groups, 2))
        self.assertEqual(sorted(_group_for(groups, 0)["source_submesh_indices"]), [0, 2])
        self.assertEqual(_group_for(groups, 1)["emissive_intensity"], 2.0)

    def test_the_submesh_name_matches_too_and_the_strength_clamps_at_the_games_cap(self) -> None:
        from cdmw.domain.new_item.spec import GlowChoice
        from cdmw.services.new_item_materials import glow_preview_parameter_groups

        groups = glow_preview_parameter_groups(
            _mesh(), GlowChoice(parts=("part_2",), color=(0.5, 0.5, 1.0), intensity=25.0)
        )
        grip = _group_for(groups, 2)
        self.assertEqual(grip["emissive_intensity"], 20.0)
        self.assertEqual(grip["emissive_color"], [0.5, 0.5, 1.0])

    def test_an_empty_mesh_builds_no_groups(self) -> None:
        from cdmw.services.new_item_materials import glow_preview_parameter_groups

        self.assertEqual(glow_preview_parameter_groups(SimpleNamespace(submeshes=[]), None), ())


class GlowChoiceHelperTests(unittest.TestCase):
    def test_the_draft_glow_becomes_the_domain_choice_only_when_a_part_is_ticked(self) -> None:
        from cdmw.ui.new_item.state import NewItemDraft, glow_choice

        self.assertIsNone(glow_choice(NewItemDraft()))
        choice = glow_choice(NewItemDraft(glow_parts=("blade",), glow_color=(0.2, 0.4, 0.6), glow_intensity=7.5))
        self.assertEqual(choice.parts, ("blade",))
        self.assertEqual(choice.color, (0.2, 0.4, 0.6))
        self.assertEqual(choice.intensity, 7.5)


class EffectPreviewMeshRoutingTests(unittest.TestCase):
    def test_effect_preview_reuses_model_and_placement_s_fitted_pivot(self) -> None:
        from types import SimpleNamespace

        from PySide6.QtWidgets import QApplication

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.controller import NewItemStudioController
        from cdmw.ui.new_item.model_import import ModelPlacement

        app = QApplication.instance() or QApplication([])
        part = SubMesh(
            name="helmet",
            material="steel",
            vertices=[(0.0, 1.5, 0.0), (0.0, 2.0, 0.0), (0.2, 1.75, 0.0)],
            uvs=[(0.0, 0.0)] * 3,
            normals=[(0.0, 1.0, 0.0)] * 3,
            faces=[(0, 1, 2)],
        )
        imported = ParsedMesh(
            path="helmet.gltf",
            format="gltf",
            submeshes=[part],
            bbox_min=(0.0, 1.5, 0.0),
            bbox_max=(0.2, 2.0, 0.0),
        )
        controller = NewItemStudioController(synchronous=True)
        controller.draft.template_key = 1
        controller.snapshot = SimpleNamespace(
            family=lambda _key: SimpleNamespace(
                model_folder="character/model/1_pc/1_phm/armor/13_hel"
            )
        )
        controller.model_import = SimpleNamespace(
            baked_preview_mesh=lambda: imported,
            baked_scene_mesh=lambda: imported,
            baked_origin=lambda: (0.0, 1.75, 0.0),
        )
        controller.model_placement = ModelPlacement(rotation=(90.0, 0.0, 0.0))

        planned, kind = controller.item_mesh_as_planned()

        self.assertEqual(kind, "placed")
        self.assertGreater(planned.bbox_min[1], 1.7, "Effects did not rotate the helmet around the feet")
        self.assertLess(planned.bbox_max[2] - planned.bbox_min[2], 0.6)
        self.assertEqual(planned._cdmw_effect_item_origin, (0.0, 1.75, 0.0))
        controller.request_shutdown()
        self.assertIsNotNone(app)

    def test_the_effect_preview_mesh_carries_the_current_glow_without_mutating_the_import(self) -> None:
        from PySide6.QtWidgets import QApplication

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.controller import NewItemStudioController

        app = QApplication.instance() or QApplication([])
        part = SubMesh(
            name="blade", material="steel",
            vertices=[(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0)],
            uvs=[(0.0, 0.0)] * 3, normals=[(0.0, 1.0, 0.0)] * 3, faces=[(0, 1, 2)],
            vertex_count=3, face_count=1,
        )
        part.preview_native_material_overrides = {"roughness": 0.7}
        imported = ParsedMesh(
            path="import.pac", format="pac", submeshes=[part], bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(0.1, 0.1, 0.0), total_vertices=3, total_faces=1, has_uvs=True,
        )
        controller = NewItemStudioController(synchronous=True)
        controller.draft.template_key = 1
        controller.model_import = SimpleNamespace(
            label="import.pac",
            baked_preview_mesh=lambda: imported,
            baked_scene_mesh=lambda: imported,
            baked_bounds=lambda: (imported.bbox_min, imported.bbox_max),
        )
        controller.draft.glow_parts = ("steel",)
        controller.draft.glow_color = (0.1, 0.8, 0.2)
        controller.draft.glow_intensity = 9.0

        planned, kind = controller.item_mesh_as_planned()

        self.assertEqual(kind, "placed")
        overrides = planned.submeshes[0].preview_native_material_overrides
        self.assertEqual(overrides["roughness"], 0.7, "the import's other appearance authority remains")
        self.assertEqual(overrides["emissive_color"], [0.1, 0.8, 0.2])
        self.assertTrue(overrides["emissive_color_authoritative"])
        self.assertEqual(overrides["emissive_intensity"], 9.0)
        self.assertEqual(part.preview_native_material_overrides, {"roughness": 0.7}, "the live import remains reusable")
        controller.request_shutdown()
        self.assertIsNotNone(app)


class _RememberingController:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[tuple[str, str, dict]] = []

    def remember_state(self, key: str, event: str, payload: dict) -> bool:
        self.calls.append((key, event, payload))
        return self.result


class ApplyMaterialParameterGroupTests(unittest.TestCase):
    def _host(self) -> SimpleNamespace:
        return SimpleNamespace(_material_parameter_generation=0, controller=_RememberingController())

    def test_groups_go_through_with_explicit_nulls_and_a_rising_generation(self) -> None:
        from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame

        host = self._host()
        sent = DotNetPreviewHostFrame.apply_material_parameter_groups(host, (
            {"source_submesh_indices": [0], "editor_role": "replacement_preview", "emissive_intensity": 6.0},
            {"source_submesh_indices": [1, 2], "emissive_intensity": None, "emissive_color": None},
        ))
        self.assertTrue(sent)
        key, event, payload = host.controller.calls[-1]
        self.assertEqual((key, event), ("material_parameters", "material_parameter_update"))
        self.assertEqual(payload["schema"], "cdmw_mesh_material_parameters_v1")
        self.assertEqual(payload["parameter_generation"], 1)
        self.assertEqual(payload["affected_submeshes"], [0, 1, 2])
        self.assertIsNone(payload["groups"][1]["emissive_intensity"], "None survives to become JSON null")
        self.assertEqual(payload["groups"][1]["editor_role"], "replacement_preview", "injected when absent")
        DotNetPreviewHostFrame.apply_material_parameter_groups(host, (
            {"source_submesh_indices": [0], "emissive_intensity": 1.0},
        ))
        self.assertEqual(host.controller.calls[-1][2]["parameter_generation"], 2)

    def test_a_group_without_indices_is_dropped_and_nothing_sends_for_none_at_all(self) -> None:
        from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame

        host = self._host()
        sent = DotNetPreviewHostFrame.apply_material_parameter_groups(host, (
            {"source_submesh_indices": [], "emissive_intensity": None},
        ))
        self.assertFalse(sent, "an empty index list means every submesh to the renderer; refuse it")
        self.assertEqual(host.controller.calls, [])
        self.assertEqual(host._material_parameter_generation, 0, "a refused send burns no generation")


class PanelGlowSyncTests(unittest.TestCase):
    def _panel(self, *, glow_parts=(), touched=False, showing=True, model_import=...):
        from cdmw.ui.new_item.state import NewItemDraft

        mesh = _mesh()
        if model_import is ...:
            model_import = SimpleNamespace(baked_preview_mesh=lambda: mesh)
        sent: list[tuple] = []
        host = SimpleNamespace(apply_material_parameter_groups=lambda groups: sent.append(groups) or True)
        panel = SimpleNamespace(
            preview=SimpleNamespace(host=host, showing_placement=showing),
            _controller=SimpleNamespace(
                draft=NewItemDraft(glow_parts=tuple(glow_parts), glow_color=(1.0, 0.5, 0.0), glow_intensity=5.0),
                model_import=model_import,
            ),
            _glow_preview_touched=touched,
        )
        return panel, sent

    def _sync(self, panel) -> None:
        from cdmw.ui.new_item.panels_model import ModelPanel

        ModelPanel._sync_glow_preview(panel)

    def test_a_ticked_glow_reaches_the_viewport_and_marks_the_panel_touched(self) -> None:
        panel, sent = self._panel(glow_parts=("blade",))
        self._sync(panel)
        self.assertEqual(len(sent), 1)
        blade = _group_for(sent[0], 0)
        self.assertEqual(blade["emissive_intensity"], 5.0)
        self.assertEqual(blade["emissive_color"], [1.0, 0.5, 0.0])
        self.assertTrue(panel._glow_preview_touched)

    def test_a_draft_that_never_glowed_sends_nothing(self) -> None:
        panel, sent = self._panel(glow_parts=(), touched=False)
        self._sync(panel)
        self.assertEqual(sent, [])
        self.assertFalse(panel._glow_preview_touched)

    def test_unticking_everything_still_restores_once_touched(self) -> None:
        panel, sent = self._panel(glow_parts=(), touched=True)
        self._sync(panel)
        self.assertEqual(len(sent), 1, "the restore statement for every part")
        self.assertIsNone(_group_for(sent[0], 0)["emissive_intensity"])

    def test_the_sync_stays_quiet_off_the_placement_scene_or_without_an_import(self) -> None:
        panel, sent = self._panel(glow_parts=("blade",), showing=False)
        self._sync(panel)
        self.assertEqual(sent, [])
        panel, sent = self._panel(glow_parts=("blade",), model_import=None)
        self._sync(panel)
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
