"""The effect placement preview: the box mesh, the scale delta, the tinted package, the dialog's numbers."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.effect_placement_preview import (
    BOX_OPACITY,
    EFFECT_BOX_MATERIAL,
    _tint_box_material,
    box_mesh,
    build_effect_placement_package,
    next_scale,
)


def _blade() -> ParsedMesh:
    vertices = [(-0.02, 0.0, -0.9), (0.02, 0.0, -0.9), (0.02, 0.0, 0.2), (-0.02, 0.0, 0.2)]
    faces = [(0, 1, 2), (0, 2, 3)]
    submesh = SubMesh(name="blade", material="steel", vertices=vertices, uvs=[(0.0, 0.0)] * 4, normals=[(0.0, 1.0, 0.0)] * 4, faces=faces, vertex_count=4, face_count=2)
    return ParsedMesh(path="blade.pac", format="pac", submeshes=[submesh], bbox_min=(-0.02, 0.0, -0.9), bbox_max=(0.02, 0.0, 0.2), total_vertices=4, total_faces=2, has_uvs=True)


class BoxAndScaleTests(unittest.TestCase):
    def test_box_mesh_is_a_closed_box_of_the_given_span(self) -> None:
        mesh = box_mesh((-1.24, -1.24, -1.39), (1.26, 1.29, 1.25))
        self.assertEqual(len(mesh.submeshes), 1)
        box = mesh.submeshes[0]
        self.assertEqual(box.material, EFFECT_BOX_MATERIAL)
        self.assertEqual(len(box.vertices), 24)
        self.assertEqual(len(box.faces), 12)
        self.assertEqual(len(box.normals), 24)
        xs = sorted({round(v[0], 2) for v in box.vertices})
        self.assertEqual(xs, [-1.24, 1.26])
        self.assertEqual(mesh.bbox_min, (-1.24, -1.24, -1.39))
        self.assertEqual(mesh.bbox_max, (1.26, 1.29, 1.25))
        # every face index is a vertex, and every face is a real triangle
        for face in box.faces:
            self.assertTrue(all(0 <= index < 24 for index in face))
            self.assertEqual(len(set(face)), 3)

    def test_a_flat_or_empty_box_gets_a_floor_extent(self) -> None:
        mesh = box_mesh((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        low, high = mesh.bbox_min, mesh.bbox_max
        self.assertTrue(all(h - l > 0.04 for l, h in zip(low, high)))

    def test_next_scale_is_the_mean_delta_clamped(self) -> None:
        self.assertAlmostEqual(next_scale(0.5, (0.1, 0.1, 0.1)), 0.6)
        self.assertAlmostEqual(next_scale(0.5, (0.3, 0.0, 0.0)), 0.6)
        self.assertEqual(next_scale(0.5, (-2.0, -2.0, -2.0)), 0.01)
        self.assertEqual(next_scale(9.0, (5.0, 5.0, 5.0)), 10.0)
        self.assertEqual(next_scale(1.0, ()), 1.0)

    def test_the_box_material_becomes_translucent_orange(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "net_materials.json"
            path.write_text(json.dumps({"submeshes": [
                {"submesh_index": 0, "material": EFFECT_BOX_MATERIAL, "alpha_mode": "opaque", "opacity_factor": 1.0, "parameters": {"roughness": 0.5}},
                {"submesh_index": 1, "material": "steel", "alpha_mode": "opaque", "opacity_factor": 1.0, "parameters": {}},
            ]}), encoding="utf-8")
            _tint_box_material(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            box, steel = payload["submeshes"]
            self.assertEqual(box["alpha_mode"], "blend")
            self.assertEqual(box["opacity_factor"], BOX_OPACITY)
            self.assertTrue(box["double_sided"])
            self.assertEqual(box["parameters"]["base_tint_color"], [1.0, 0.45, 0.1])
            self.assertEqual(steel["alpha_mode"], "opaque")
            # a missing file is left alone
            _tint_box_material(Path(folder) / "missing.json")


class PackageTests(unittest.TestCase):
    def test_the_package_puts_the_box_first_and_the_item_as_reference(self) -> None:
        if os.environ.get("CDMW_SKIP_DOTNET_PACKAGE_TESTS") == "1":
            self.skipTest("dotnet package tests skipped by request")
        with tempfile.TemporaryDirectory() as folder:
            preview = build_effect_placement_package(_blade(), (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), output_root=Path(folder))
            self.assertEqual(preview.box_submesh_index, 0)
            self.assertEqual(preview.item_submesh_count, 1)
            scene = json.loads((preview.package_dir / "dotnet_scene.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(scene["comparison_mode"], "overlay")
            self.assertEqual(scene["interaction_mode"], "placement")
            self.assertEqual(scene["roles"]["replacement"], [0])
            self.assertEqual(scene["roles"]["original_reference"], [1])
            self.assertTrue(scene["gizmo"]["visible"])
            materials = json.loads((preview.package_dir / "net_materials.json").read_text(encoding="utf-8"))
            box = next(item for item in materials["submeshes"] if item["material"] == EFFECT_BOX_MATERIAL)
            self.assertEqual(box["alpha_mode"], "blend")


def _fire_preview():
    from cdmw.core.effect_binary import decode_effect_binary
    from cdmw.core.effect_edit import emitter_layout_of
    from cdmw.services.effect_preview_model import build_effect_preview

    fixtures = Path(__file__).parent / "fixtures" / "effects"
    trail_path = "effect/binary__/emitter/cdem_last_fire_circle_trail_001a.paem"
    trail = decode_effect_binary((fixtures / "cdem_last_fire_circle_trail_001a.paem").read_bytes())
    effect = decode_effect_binary((fixtures / "fx_hit_common_fire_attach_a_loop.pae").read_bytes())
    return build_effect_preview("fx_hit_common_fire_attach_a_loop", effect, emitter_documents={trail_path: trail}, layouts={trail_path: emitter_layout_of(trail)})


class EffectPreviewInPackageTests(unittest.TestCase):
    def test_the_description_and_its_textures_are_written_beside_the_mesh(self) -> None:
        from cdmw.services.effect_placement_preview import EFFECT_PREVIEW_FILE, EFFECT_TEXTURE_DIR, write_effect_preview

        preview = _fire_preview()
        with tempfile.TemporaryDirectory() as folder:
            target, missing = write_effect_preview(Path(folder), preview, texture_reader=lambda path: b"DDS fake" if path.endswith("pafx_fire_003a_kjd.dds") else None)
            self.assertEqual(target.name, EFFECT_PREVIEW_FILE)
            self.assertEqual(missing, ())
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], 1)
            self.assertEqual(payload["texture_files"], {"effect/texture/pafx_fire_003a_kjd.dds": f"{EFFECT_TEXTURE_DIR}/pafx_fire_003a_kjd.dds"})
            self.assertEqual((Path(folder) / EFFECT_TEXTURE_DIR / "pafx_fire_003a_kjd.dds").read_bytes(), b"DDS fake")
            self.assertEqual(len(payload["emitters"]), 2)
            # no reader: the JSON is still written, the texture is said to be missing
            target, missing = write_effect_preview(Path(folder), preview)
            self.assertEqual(missing, ("effect/texture/pafx_fire_003a_kjd.dds",))
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["texture_files"], {})

    def test_the_dialog_describes_the_emitters(self) -> None:
        from cdmw.ui.new_item.effect_placement_dialog import describe_effect_preview

        text = describe_effect_preview(_fire_preview())
        lines = text.split("\n")
        self.assertTrue(lines[0].startswith("cdem_last_fire_circle_trail_001a: billboard, "), lines[0])
        self.assertIn("loops", lines[0])
        self.assertIn("pafx_fire_003a_kjd.dds", lines[0])
        self.assertIn("#", lines[0])
        self.assertTrue(lines[1].startswith("cdem_material_firefly_alpha_uberstandard: billboard, "), lines[1])
        self.assertIn("once", lines[1])
        self.assertTrue(any("was not read" in line for line in lines[2:]), "the missing firefly file is a note")
        self.assertEqual(describe_effect_preview(None), "")


class ViewerParticleLayerContractTests(unittest.TestCase):
    """The resident .NET viewer's particle layer, as source: it reads what the package writes."""

    ROOT = Path(__file__).resolve().parents[1] / "tools" / "dotnet_mesh_editor_experiment"

    def test_the_viewer_reads_the_description_and_announces_the_capability(self) -> None:
        reader = (self.ROOT / "EffectParticlePreview.cs").read_text(encoding="utf-8")
        renderer = (self.ROOT / "D3D11MaterialViewport.EffectParticles.cs").read_text(encoding="utf-8")
        shaders = (self.ROOT / "D3D11MaterialShaders.hlsl").read_text(encoding="utf-8")
        provenance = (self.ROOT / "HelperBuildProvenance.cs").read_text(encoding="utf-8")
        package_protocol = (self.ROOT / "ExperimentForm.PackageProtocol.cs").read_text(encoding="utf-8")
        from cdmw.services.effect_placement_preview import EFFECT_PREVIEW_FILE

        self.assertIn(f'FileName = "{EFFECT_PREVIEW_FILE}"', reader)
        for key in ("bursts_per_second", "life", "spawn", "spread", "points", "force", "damping", "speed_limit", "scale", "rotation",
                    "scale_over_life", "alpha_over_life", "color_over_life", "emissive_color", "beam_width", "beam_length", "beam_axis",
                    "mass", "simulation_speed", "sequence", "velocity_stretch", "texture_files"):
            self.assertIn(f'"{key}"', reader, key)
        self.assertIn("class EffectEmitterSimulation", reader)
        self.assertIn("AppendBeamVertices", reader)
        self.assertIn("LoadEffectParticlePreview", renderer)
        self.assertIn("DrawEffectParticles", renderer)
        self.assertIn("VSParticle", shaders)
        self.assertIn("PSParticle", shaders)
        self.assertIn('"effect_particle_preview_v1"', provenance)
        self.assertIn("LoadEffectParticlePreview(prepared.PackagePath)", package_protocol)
        self.assertIn('["effect_preview"]', package_protocol)


class HostPlacementMatrixTests(unittest.TestCase):
    """The host's placement numbers reach the helper as the editable role's model matrix."""

    def test_the_placement_composes_the_editable_model_matrix_and_bounds(self) -> None:
        from cdmw.ui.preview.dotnet_host import _apply_placement_to_editable_role, _placement_matrix

        matrix = _placement_matrix((1.0, 2.0, 3.0), (0.0, 0.0, 0.0), (0.2, 0.2, 0.2))
        self.assertEqual([round(v, 6) for v in matrix], [0.2, 0, 0, 0, 0, 0.2, 0, 0, 0, 0, 0.2, 0, 1.0, 2.0, 3.0, 1.0])
        scene = {"roles": {"editable": {"model_matrix": [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0], "world_bounds": {"min": [-1, -1, -1], "max": [1, 1, 1]}}}}
        _apply_placement_to_editable_role(scene, {"translation": (0.0, 0.0, 0.5), "rotation_degrees": (0.0, 0.0, 0.0), "scale": (0.5, 0.5, 0.5)})
        editable = scene["roles"]["editable"]
        self.assertEqual([round(v, 6) for v in editable["model_matrix"]][12:15], [0.0, 0.0, 0.5])
        self.assertEqual([round(v, 6) for v in editable["world_bounds"]["min"]], [-0.5, -0.5, 0.0])
        self.assertEqual([round(v, 6) for v in editable["world_bounds"]["max"]], [0.5, 0.5, 1.0])
        # a second placement starts from the remembered local bounds, not the moved ones
        _apply_placement_to_editable_role(scene, {"translation": (0.0, 0.0, 0.0), "rotation_degrees": (0.0, 0.0, 0.0), "scale": (1.0, 1.0, 1.0)})
        self.assertEqual([round(v, 6) for v in scene["roles"]["editable"]["world_bounds"]["max"]], [1.0, 1.0, 1.0])
        # a scene without the role is left alone
        _apply_placement_to_editable_role({}, {"translation": (0, 0, 0), "rotation_degrees": (0, 0, 0), "scale": (1, 1, 1)})


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_without_a_viewport_the_numbers_and_deltas_still_work(self) -> None:
        from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementDialog

        dialog = EffectPlacementDialog(
            None, item_mesh=_blade(), box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
            offset=(0.0, 0.0, 0.1), scale=0.5, effect_label="fx_test", host_factory=lambda parent: None,
            effect_preview=_fire_preview(),
        )
        try:
            self.assertIsNone(dialog.host)
            self.assertTrue(dialog.emitters_label.isVisibleTo(dialog))
            self.assertIn("cdem_last_fire_circle_trail_001a: billboard", dialog.emitters_label.text())
            self.assertIn("2.00 x 2.00 x 2.00 m; at scale 0.50: 1.00 x 1.00 x 1.00 m", dialog.size_label.text())
            dialog.apply_deltas((0.0, 0.0, 0.2))
            self.assertEqual(dialog.offset, (0.0, 0.0, 0.3))
            dialog.apply_deltas((0.0, 0.0, 0.0), (0.1, 0.1, 0.1))
            self.assertAlmostEqual(dialog.scale, 0.6)
            self.assertIn("at scale 0.60: 1.20 x 1.20 x 1.20 m", dialog.size_label.text())
            dialog.scale_spin.setValue(0.25)
            dialog.offset_spins[1].setValue(-0.05)
            self.assertEqual(dialog.scale, 0.25)
            self.assertEqual(dialog.offset, (0.0, -0.05, 0.3))
        finally:
            dialog.done(0)


if __name__ == "__main__":
    unittest.main()
