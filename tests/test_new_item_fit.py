"""Gates for the first placement an imported model lands at (`fitted_placement`).

The fit is a guess the reader corrects. Weapons use their long axis and heavy end to meet
at the grip; armour and accessories match the same axes but stay centred, because neither
end of a helmet or boot is a handle.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.ui.new_item.model_import import fitted_placement  # noqa: E402


def bounds(low, high):
    return (tuple(float(v) for v in low), tuple(float(v) for v in high))


class FitTests(unittest.TestCase):
    #: a template sword a metre long down z, its blade (the heavy end) at -z, grip at +z
    TEMPLATE = bounds((-0.05, -0.02, -0.90), (0.05, 0.02, 0.10))
    TEMPLATE_CENTROID = (0.0, 0.0, -0.55)

    def placed(self, source, source_centroid):
        placement = fitted_placement(
            source, self.TEMPLATE, source_centroid=source_centroid, template_centroid=self.TEMPLATE_CENTROID
        )
        low = placement.apply(source[0])
        high = placement.apply(source[1])
        return placement, (min(low[2], high[2]), max(low[2], high[2]))

    def test_the_grips_meet_rather_than_the_middles(self) -> None:
        """An axe: a metre long, and the head is most of it. Its grip has to land on the
        template's grip, not its centre on the template's centre."""

        axe = bounds((-0.2, -0.05, -1.0), (0.2, 0.05, 0.0))
        _placement, (low, high) = self.placed(axe, source_centroid=(0.0, 0.0, -0.75))
        self.assertAlmostEqual(high, 0.10, places=3, msg="the grip end sits where the template's grip is")
        self.assertAlmostEqual(low, -0.90, places=3, msg="and the head reaches the template's far end")

    def test_a_heavy_end_the_other_way_round_is_matched_the_other_way(self) -> None:
        axe = bounds((-0.2, -0.05, 0.0), (0.2, 0.05, 1.0))
        _placement, (low, high) = self.placed(axe, source_centroid=(0.0, 0.0, 0.75))
        self.assertAlmostEqual(low, -0.90, places=3)
        self.assertAlmostEqual(high, 0.10, places=3)

    def test_without_centroids_the_middles_meet_as_before(self) -> None:
        """Nothing says which end is which, so nothing is claimed: the boxes are centred,
        which is what the fit did for everything before."""

        axe = bounds((-0.2, -0.05, -1.0), (0.2, 0.05, 0.0))
        placement = fitted_placement(axe, self.TEMPLATE)
        low = placement.apply(axe[0])
        high = placement.apply(axe[1])
        middle = (min(low[2], high[2]) + max(low[2], high[2])) / 2.0
        self.assertAlmostEqual(middle, -0.40, places=3, msg="the template's own middle")

    def test_a_nonweapon_fit_does_not_turn_a_helmet_to_match_heavy_ends(self) -> None:
        helmet = bounds((-0.05, -0.02, -0.10), (0.05, 0.02, 0.90))
        helmet_centroid = (0.0, 0.0, 0.55)

        weapon_fit = fitted_placement(
            helmet,
            self.TEMPLATE,
            source_centroid=helmet_centroid,
            template_centroid=self.TEMPLATE_CENTROID,
        )
        armour_fit = fitted_placement(
            helmet,
            self.TEMPLATE,
            source_centroid=helmet_centroid,
            template_centroid=self.TEMPLATE_CENTROID,
            match_grip=False,
        )

        self.assertNotEqual(weapon_fit.rotation, (0.0, 0.0, 0.0), "a weapon turns its heavy end to match")
        self.assertEqual(armour_fit.rotation, (0.0, 0.0, 0.0), "armour keeps the cheapest centred orientation")

    def test_the_scale_still_matches_the_template_s_length(self) -> None:
        axe = bounds((-0.4, -0.1, -2.0), (0.4, 0.1, 0.0))
        placement, (low, high) = self.placed(axe, source_centroid=(0.0, 0.0, -1.5))
        self.assertAlmostEqual(placement.scale[0], 0.5, places=4, msg="two metres into one")
        self.assertAlmostEqual(high - low, 1.0, places=3)

    def test_nothing_to_fit_is_no_placement(self) -> None:
        self.assertEqual(fitted_placement(None, self.TEMPLATE).offset, (0.0, 0.0, 0.0))
        self.assertEqual(fitted_placement(self.TEMPLATE, None).scale, (1.0, 1.0, 1.0))

    def test_a_diagonal_authored_weapon_is_straightened_to_the_template_axis(self) -> None:
        """The supplied gravestone sword is authored diagonally inside its AABB. A
        quarter-turn-only box fit leaves it visibly diagonal over a straight template."""

        import math

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.model_import import mesh_bounds, mesh_principal_frame

        angle = math.radians(39.0)
        long_axis = (math.cos(angle), math.sin(angle), 0.0)
        side_axis = (-math.sin(angle), math.cos(angle), 0.0)

        def prism(axis, side, half_length, half_width):
            return [
                (
                    axis[0] * along + side[0] * across,
                    axis[1] * along + side[1] * across,
                    z,
                )
                for along in (-half_length, half_length)
                for across in (-half_width, half_width)
                for z in (-0.01, 0.01)
            ]

        source_mesh = ParsedMesh(
            path="diagonal.gltf",
            format="gltf",
            submeshes=[SubMesh(name="sword", vertices=prism(long_axis, side_axis, 2.0, 0.2), faces=[])],
        )
        template_mesh = ParsedMesh(
            path="template.pac",
            format="pac",
            submeshes=[SubMesh(name="template", vertices=prism((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), 1.0, 0.1), faces=[])],
        )
        source_frame = mesh_principal_frame(source_mesh)
        template_frame = mesh_principal_frame(template_mesh)
        self.assertIsNotNone(source_frame)
        self.assertIsNotNone(template_frame)

        placement = fitted_placement(
            mesh_bounds(source_mesh),
            mesh_bounds(template_mesh),
            match_grip=False,
            source_frame=source_frame,
            template_frame=template_frame,
        )
        matrix = placement.matrix()
        mapped_long = (
            source_frame.axes[0][0] * matrix[0] + source_frame.axes[0][1] * matrix[4] + source_frame.axes[0][2] * matrix[8],
            source_frame.axes[0][0] * matrix[1] + source_frame.axes[0][1] * matrix[5] + source_frame.axes[0][2] * matrix[9],
            source_frame.axes[0][0] * matrix[2] + source_frame.axes[0][1] * matrix[6] + source_frame.axes[0][2] * matrix[10],
        )
        alignment = abs(sum(mapped_long[index] * template_frame.axes[0][index] for index in range(3)))
        self.assertAlmostEqual(alignment / placement.scale[0], 1.0, places=5)
        self.assertAlmostEqual(
            source_frame.extents[0] * placement.scale[0],
            template_frame.extents[0],
            places=6,
        )
        for actual, expected in zip(placement.apply(source_frame.center), template_frame.center):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertFalse(
            all(abs(value / 90.0 - round(value / 90.0)) < 1e-5 for value in placement.rotation),
            "the fit must correct the authored diagonal, not choose another quarter turn",
        )

    def test_named_grips_and_tips_drive_alignment_without_a_reflection(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.model_import import analyze_mesh_geometry

        def anchor_triangle(name, center):
            x, y, z = center
            return SubMesh(
                name=name,
                vertices=[
                    (x, y - 0.10, z - 0.05),
                    (x, y + 0.10, z - 0.05),
                    (x, y, z + 0.05),
                ],
                faces=[(0, 1, 2)],
            )

        source = ParsedMesh(
            path="named-source.gltf",
            format="gltf",
            submeshes=[
                anchor_triangle("weapon_handle", (-2.0, 0.0, 0.0)),
                anchor_triangle("blade_tip", (2.0, 0.0, 0.0)),
            ],
        )
        template = ParsedMesh(
            path="named-template.pac",
            format="pac",
            submeshes=[
                anchor_triangle("hilt", (0.0, -1.0, 0.0)),
                anchor_triangle("point", (0.0, 1.0, 0.0)),
            ],
        )
        source_analysis = analyze_mesh_geometry(source)
        template_analysis = analyze_mesh_geometry(template)
        self.assertIsNotNone(source_analysis.principal_frame)
        self.assertIsNotNone(template_analysis.principal_frame)
        source_frame = source_analysis.principal_frame
        template_frame = template_analysis.principal_frame
        self.assertIsNotNone(source_frame.grip)
        self.assertIsNotNone(source_frame.tip)
        self.assertIsNotNone(source_frame.direction_hint)

        placement = fitted_placement(
            source_analysis.bounds,
            template_analysis.bounds,
            source_centroid=source_analysis.centroid,
            template_centroid=template_analysis.centroid,
            source_frame=source_frame,
            template_frame=template_frame,
            match_grip=True,
        )

        for actual, expected in zip(placement.apply(source_frame.grip), template_frame.grip):
            self.assertAlmostEqual(actual, expected, places=5)
        matrix = placement.matrix()
        determinant = (
            matrix[0] * (matrix[5] * matrix[10] - matrix[6] * matrix[9])
            - matrix[1] * (matrix[4] * matrix[10] - matrix[6] * matrix[8])
            + matrix[2] * (matrix[4] * matrix[9] - matrix[5] * matrix[8])
        )
        self.assertGreater(determinant, 0.0, "automatic fitting must preserve handedness")

    def test_tilted_imports_lie_flat_on_each_template_grid_plane(self) -> None:
        from dataclasses import replace

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.item_preview_materials import flat_preview_normal_axis
        from cdmw.ui.new_item.model_import import ModelPlacement, analyze_mesh_geometry

        def prism(half_extents, rotation, axis_order):
            transform = ModelPlacement(rotation=rotation, offset=(0.3, -0.2, 0.1))

            def point(value):
                turned = transform.apply(value)
                return tuple(turned[index] for index in axis_order)

            length, width, thickness = half_extents
            mesh = ParsedMesh(path="prism", format="gltf", submeshes=[
                SubMesh(
                    name=name,
                    vertices=[point((x, y, z)) for y in (-width, width) for z in (-thickness, thickness)],
                    faces=[(0, 1, 2), (1, 3, 2)],
                )
                for name, x in (("handle", -length), ("blade_tip", length))
            ])
            return mesh, point

        for broad_shape in (False, True):
            source_width = 2.0 if broad_shape else 0.4
            source, source_point = prism((2.0, source_width, 0.04), (31.0, 17.0, -39.0), (0, 1, 2))
            source_analysis = analyze_mesh_geometry(source)
            for axis_order, expected_normal in (((0, 1, 2), "z"), ((1, 2, 0), "y"), ((2, 0, 1), "x")):
                template, template_point = prism(
                    (1.0, source_width / 2.0, 0.02), (14.0, -9.0, 25.0), axis_order,
                )
                template_analysis = analyze_mesh_geometry(template)
                normal = "xyz".index(flat_preview_normal_axis(template_analysis.bounds))
                self.assertEqual("xyz"[normal], expected_normal)
                anchor_modes = ("centre", "named") if broad_shape else ("centre", "named", "inferred")
                for anchor_mode in anchor_modes:
                    with self.subTest(broad_shape=broad_shape, normal=expected_normal, anchor=anchor_mode):
                        source_frame = source_analysis.principal_frame
                        template_frame = template_analysis.principal_frame
                        if anchor_mode == "inferred":
                            source_frame = replace(source_frame, grip=None, tip=None)
                            template_frame = replace(template_frame, grip=None, tip=None)
                        match_grip = anchor_mode != "centre"
                        placement = fitted_placement(
                            source_analysis.bounds,
                            template_analysis.bounds,
                            source_centroid=source_analysis.centroid,
                            template_centroid=template_analysis.centroid,
                            source_frame=source_frame,
                            template_frame=template_frame,
                            match_grip=match_grip,
                        )
                        # Measure the actual transformed geometry, not the Euler angles:
                        # an imported model can already be tilted inside its own mesh.
                        placed = [placement.apply(vertex) for part in source.submeshes for vertex in part.vertices]
                        thickness = max(point[normal] for point in placed) - min(point[normal] for point in placed)
                        self.assertAlmostEqual(thickness, 0.08 * placement.scale[0], places=6)
                        if not broad_shape:
                            self.assertAlmostEqual(placement.scale[0], 0.5, places=6)
                            source_start = placement.apply(source_point((-2.0, 0.0, 0.0)))
                            source_end = placement.apply(source_point((2.0, 0.0, 0.0)))
                            target_start = template_point((-1.0, 0.0, 0.0))
                            target_end = template_point((1.0, 0.0, 0.0))
                            ours = [source_end[index] - source_start[index] for index in range(3)]
                            theirs = [target_end[index] - target_start[index] for index in range(3)]
                            theirs[normal] = 0.0
                            alignment = sum(a * b for a, b in zip(ours, theirs))
                            lengths = sum(v * v for v in ours) * sum(v * v for v in theirs)
                            self.assertAlmostEqual(alignment * alignment / lengths, 1.0, places=6)
                        source_anchor = source_analysis.principal_frame.grip if match_grip else source_analysis.principal_frame.center
                        target_anchor = template_analysis.principal_frame.grip if match_grip else template_analysis.principal_frame.center
                        for actual, expected in zip(placement.apply(source_anchor), target_anchor):
                            self.assertAlmostEqual(actual, expected, places=6)

    def test_a_symmetric_template_still_levels_an_import_with_a_clear_plane(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.model_import import ModelPlacement, analyze_mesh_geometry

        def box(half_extents, rotation):
            transform = ModelPlacement(rotation=rotation)
            return ParsedMesh(path="box", format="gltf", submeshes=[SubMesh(
                name="box",
                vertices=[
                    transform.apply((x, y, z))
                    for x in (-half_extents[0], half_extents[0])
                    for y in (-half_extents[1], half_extents[1])
                    for z in (-half_extents[2], half_extents[2])
                ],
                faces=[],
            )])

        source = box((2.0, 0.2, 0.02), (23.0, 17.0, 39.0))
        source_analysis = analyze_mesh_geometry(source)
        template_analysis = analyze_mesh_geometry(box((1.0, 1.0, 1.0), (0.0, 0.0, 0.0)))
        placement = fitted_placement(
            source_analysis.bounds, template_analysis.bounds,
            source_frame=source_analysis.principal_frame,
            template_frame=template_analysis.principal_frame,
            match_grip=False,
        )
        heights = [placement.apply(vertex)[2] for vertex in source.submeshes[0].vertices]
        self.assertAlmostEqual(max(heights) - min(heights), 0.04 * placement.scale[0], places=6)

    def test_bake_uses_the_native_affine_path_and_preserves_direction_channels(self) -> None:
        from unittest.mock import patch

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.model_import import ModelPlacement, bake_mesh

        mesh = ParsedMesh(
            path="source",
            format="gltf",
            submeshes=[SubMesh(
                name="part",
                vertices=[(1.0, 0.0, 0.0)],
                normals=[(1.0, 0.0, 0.0)],
                tangents=[(1.0, 0.0, 0.0, -1.0)],
                faces=[],
            )],
        )
        seen = {}

        def native(submeshes, *, position_matrices_by_index, **_kwargs):
            seen.update(position_matrices_by_index)
            matrix = position_matrices_by_index[0]
            x, y, z = submeshes[0].vertices[0]
            submeshes[0].vertices = [(
                matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
                matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
                matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
            )]
            return {0}

        placement = ModelPlacement(offset=(2.0, 3.0, 4.0), rotation=(0.0, 0.0, 90.0))
        with patch("cdmw.services.mesh_workflow_service.apply_native_mesh_affine_transform_submeshes", native):
            baked = bake_mesh(mesh, placement)

        self.assertEqual(set(seen), {0})
        self.assertAlmostEqual(baked.submeshes[0].vertices[0][0], 2.0, places=6)
        self.assertAlmostEqual(baked.submeshes[0].vertices[0][1], 4.0, places=6)
        self.assertEqual(baked.submeshes[0].tangents[0][3], -1.0)
        self.assertAlmostEqual(baked.submeshes[0].normals[0][1], 1.0, places=6)

    def test_bake_uses_the_same_fitted_origin_as_model_and_placement(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.modding.static_mesh_scene_frame import (
            build_static_transform_frame,
            matrix_transform_point,
        )
        from cdmw.ui.new_item.model_import import ModelPlacement, bake_mesh

        mesh = ParsedMesh(
            path="helmet.gltf",
            format="gltf",
            submeshes=[SubMesh(
                name="helmet",
                vertices=[(0.0, 1.5, 0.0), (0.0, 2.0, 0.0), (0.2, 1.75, 0.0)],
                normals=[(0.0, 1.0, 0.0)] * 3,
                faces=[(0, 1, 2)],
            )],
            bbox_min=(0.0, 1.5, 0.0),
            bbox_max=(0.2, 2.0, 0.0),
        )
        origin = (0.0, 1.75, 0.0)
        placement = ModelPlacement(
            offset=(0.0, 0.05, 0.02),
            rotation=(90.0, 0.0, 0.0),
        )

        baked = bake_mesh(mesh, placement, origin=origin)
        frame = build_static_transform_frame(
            mesh,
            mesh,
            placement.build_transform(origin=origin),
            include_grid_floor=False,
        )

        # The fitted source origin stays on the head and receives only the manual offset.
        self.assertEqual(
            tuple(round(value, 6) for value in placement.matrix(origin=origin)[12:15]),
            (0.0, 1.8, -1.73),
        )
        middle = baked.submeshes[0].vertices[2]
        self.assertEqual(tuple(round(value, 6) for value in middle), (0.2, 1.8, 0.02))
        for source, preview in zip(mesh.submeshes[0].vertices, baked.submeshes[0].vertices):
            built = matrix_transform_point(frame.effective_model_matrix, source)
            self.assertEqual(
                tuple(round(value, 6) for value in preview),
                tuple(round(value, 6) for value in built),
                "Effects and Model & Placement use the same anchored transform",
            )
        self.assertGreater(baked.bbox_min[1], 1.5, "the helmet was not swung around world zero")


class UnimportableModelTests(unittest.TestCase):
    """What the studio says when a file holds nothing it can read. Half the models on the
    asset sites arrive as `source/<name>.fbx` with the textures beside it, and a list of
    extensions reads like the file is broken rather than like it is the wrong kind."""

    def setUp(self) -> None:
        import tempfile

        self._temp = tempfile.TemporaryDirectory()
        self.folder = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def test_a_zip_holding_an_fbx_says_so_and_says_what_to_do(self) -> None:
        import zipfile

        from cdmw.ui.new_item.model_import import _nothing_to_import

        archive = self.folder / "magic-sword.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("source/MagicSword.fbx", b"not really an fbx")
            zipped.writestr("textures/MagicSword_Albedo.png", b"not really a png")
        message = _nothing_to_import(archive, self.folder / "nothing")
        self.assertIn("MagicSword.fbx", message, "the file it found, not just a list of extensions")
        # FBX is read by converting it, and only with a Blender the reader pointed at: the
        # message has to say that is what is missing, not that the file is the wrong kind
        self.assertIn("converting it with Blender", message)
        self.assertIn("Choose blender.exe", message)
        self.assertIn("glTF, GLB, OBJ or DAE", message, "and the way round it")

    def test_a_file_of_no_known_kind_falls_back_to_what_can_be_read(self) -> None:
        from cdmw.ui.new_item.model_import import _nothing_to_import

        empty = self.folder / "sword.rar"
        empty.write_bytes(b"")
        message = _nothing_to_import(empty, self.folder / "nothing")
        self.assertIn("sword.rar", message)
        for readable in ("GLTF", "GLB", "OBJ", "DAE"):
            self.assertIn(readable, message)


class NeedsBlenderBeforeReadingTests(unittest.TestCase):
    """Whether a source needs Blender is answered from its name and, for a zip, its
    listing: the studio has to know *before* it starts, because the alternative is what
    shipped first -- a zip extracted whole, a worker started, and a refusal at the far end
    of it while the step still said "Reading the model file...".
    """

    def setUp(self) -> None:
        import tempfile

        self._temp = tempfile.TemporaryDirectory()
        self.folder = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def zip_of(self, *names) -> Path:
        import zipfile

        archive = self.folder / "source.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for name in names:
                zipped.writestr(name, b"x")
        return archive

    def test_a_loose_fbx_needs_one(self) -> None:
        from cdmw.ui.new_item.model_import import fbx_needing_blender

        self.assertEqual(fbx_needing_blender(self.folder / "MagicSword.fbx"), "MagicSword.fbx")

    def test_a_zip_holding_only_an_fbx_needs_one(self) -> None:
        from cdmw.ui.new_item.model_import import fbx_needing_blender

        archive = self.zip_of("source/MagicSword.fbx", "textures/Albedo.png")
        self.assertEqual(fbx_needing_blender(archive), "MagicSword.fbx")

    def test_a_zip_that_also_holds_a_readable_model_needs_none(self) -> None:
        """Publishers ship both often enough that refusing the zip for the FBX in it would
        refuse a model the studio reads perfectly well."""

        from cdmw.ui.new_item.model_import import fbx_needing_blender

        archive = self.zip_of("source/MagicSword.fbx", "MagicSword.glb")
        self.assertEqual(fbx_needing_blender(archive), "")

    def test_the_formats_the_studio_reads_itself_need_none(self) -> None:
        from cdmw.ui.new_item.model_import import fbx_needing_blender

        for name in ("sword.glb", "sword.gltf", "sword.obj", "sword.dae", "sword.rar", ""):
            self.assertEqual(fbx_needing_blender(self.folder / name if name else ""), "", name)

    def test_nothing_is_extracted_to_answer_it(self) -> None:
        """The point of the question: a 300 MB zip is not unpacked to find out that the
        conversion it needs cannot run."""

        from cdmw.ui.new_item.model_import import fbx_needing_blender

        archive = self.zip_of("source/MagicSword.fbx")
        before = sorted(path.name for path in self.folder.iterdir())
        fbx_needing_blender(archive)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
