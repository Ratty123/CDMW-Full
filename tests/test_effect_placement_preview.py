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
        )
        try:
            self.assertIsNone(dialog.host)
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
