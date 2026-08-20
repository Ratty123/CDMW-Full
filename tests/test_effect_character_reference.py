"""Gates for the character the effect dialog draws: which body it takes, which frame the
scene is in, and that an offset survives the trip into that frame and back.

The dialog's numbers are the item's own -- the effect rides on the weapon's prefab and
moves with it -- while the picture has to be of a person standing upright, because a
camera has an up and a body lying at sixty degrees reads as a bug. The two are the same
scene through one rotation, and everything here is about that rotation being exact.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh  # noqa: E402
from cdmw.services.effect_character_reference import (  # noqa: E402
    CHARACTER_SUBMESH_PREFIX,
    _body_mesh_paths,
    build_character_reference,
    rotate_mesh,
    rotate_point,
    unrotate_point,
)
from cdmw.services.effect_placement_preview import build_effect_placement_package  # noqa: E402

#: a quarter turn about x: y goes to z, z goes to -y. Row-major, row vectors.
QUARTER_TURN = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0)


def _blade() -> ParsedMesh:
    vertices = [(-0.02, 0.0, -0.9), (0.02, 0.0, -0.9), (0.02, 0.0, 0.2), (-0.02, 0.0, 0.2)]
    submesh = SubMesh(
        name="blade", material="steel", vertices=vertices, uvs=[(0.0, 0.0)] * 4,
        normals=[(0.0, 1.0, 0.0)] * 4, faces=[(0, 1, 2), (0, 2, 3)], vertex_count=4, face_count=2,
    )
    return ParsedMesh(
        path="blade.pac", format="pac", submeshes=[submesh],
        bbox_min=(-0.02, 0.0, -0.9), bbox_max=(0.02, 0.0, 0.2),
        total_vertices=4, total_faces=2, has_uvs=True,
    )


def _body(submeshes: int = 2) -> ParsedMesh:
    parts = []
    for index in range(submeshes):
        base = float(index)
        vertices = [(0.0, base, 0.0), (0.1, base, 0.0), (0.0, base + 0.5, 0.0)]
        parts.append(SubMesh(
            name=f"{CHARACTER_SUBMESH_PREFIX}{index}", material=f"{CHARACTER_SUBMESH_PREFIX}body",
            vertices=vertices, uvs=[(0.0, 0.0)] * 3, normals=[(0.0, 0.0, 1.0)] * 3,
            faces=[(0, 1, 2)], vertex_count=3, face_count=1,
        ))
    every = [vertex for part in parts for vertex in part.vertices]
    return ParsedMesh(
        path="body.pac", format="pac", submeshes=parts,
        bbox_min=tuple(min(v[a] for v in every) for a in range(3)),
        bbox_max=tuple(max(v[a] for v in every) for a in range(3)),
        total_vertices=len(every), total_faces=submeshes, has_uvs=True,
    )


class RotationTests(unittest.TestCase):
    def test_a_point_goes_into_the_scene_and_comes_back(self) -> None:
        for point in ((0.0, 0.0, 0.0), (0.0, 0.0, 0.9), (0.3, -0.2, 0.1)):
            scene = rotate_point(point, QUARTER_TURN)
            back = unrotate_point(scene, QUARTER_TURN)
            for axis in range(3):
                self.assertAlmostEqual(back[axis], point[axis], places=9, msg=f"{point} axis {axis}")

    def test_the_quarter_turn_is_the_turn_it_says(self) -> None:
        self.assertEqual(
            tuple(round(v, 9) for v in rotate_point((0.0, 0.0, 1.0), QUARTER_TURN)), (0.0, -1.0, 0.0)
        )

    def test_a_mesh_turns_with_its_normals_and_its_bounds(self) -> None:
        turned = rotate_mesh(_blade(), QUARTER_TURN)
        self.assertEqual(tuple(round(v, 6) for v in turned.submeshes[0].normals[0]), (0.0, 0.0, 1.0))
        # the blade ran from z -0.9 to 0.2; a quarter turn about x makes that y 0.9 to -0.2
        self.assertAlmostEqual(turned.bbox_min[1], -0.2, places=6)
        self.assertAlmostEqual(turned.bbox_max[1], 0.9, places=6)
        self.assertEqual(turned.total_vertices, 4, "turning a mesh does not change what it is")

    def test_a_rotation_is_nine_numbers(self) -> None:
        with self.assertRaises(ValueError):
            rotate_mesh(_blade(), (1.0, 0.0, 0.0))


class BodyChoiceTests(unittest.TestCase):
    """Which mesh stands in for the player. The whole low-detail figure has a head, hands
    and feet in one file of under a thousand vertices; armour is the fallback, and picking
    it badly lands on an accessory the size of an elbow pad."""

    LOD = "character/model/1_pc/1_phm/nude/cd_phm_00_lod_0001.pac"
    UPPER = "character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_02_ub_0010_01.pac"
    LOWER = "character/model/1_pc/1_phm/armor/10_lowerbody/cd_phm_00_lb_00_0339.pac"

    def test_the_whole_figure_wins_over_armour(self) -> None:
        chosen = _body_mesh_paths([self.UPPER, self.LOWER, self.LOD], {})
        self.assertEqual(chosen, [self.LOD])

    def test_without_it_one_piece_per_half(self) -> None:
        chosen = _body_mesh_paths([self.UPPER, self.LOWER], {self.UPPER: 400_000, self.LOWER: 300_000})
        self.assertEqual(chosen, [self.UPPER, self.LOWER])

    def test_an_install_with_neither_gives_nothing(self) -> None:
        self.assertEqual(_body_mesh_paths(["gamedata/binary__/client/bin/iteminfo.pabgb"], {}), [])


class NoCharacterTests(unittest.TestCase):
    def test_archives_without_a_rig_give_none_rather_than_an_error(self) -> None:
        def read(_path: str) -> bytes:
            raise AssertionError("nothing should be read when there is no rig to read")

        self.assertIsNone(build_character_reference(["gamedata/binary__/client/bin/iteminfo.pabgb"], read))


class SnapshotSeamTests(unittest.TestCase):
    """The studio's controller reads no archives itself; it asks for a character and gets
    one line back to log either way."""

    class _Entry:
        orig_size = 1024

    class _Snapshot:
        def __init__(self, paths) -> None:
            self.entries = {path: SnapshotSeamTests._Entry() for path in paths}

        def payload(self, path: str) -> bytes:
            raise AssertionError(f"nothing should be read here: {path}")

    def test_a_snapshot_with_no_rig_says_so_and_draws_the_stand_in(self) -> None:
        from cdmw.services.effect_character_reference import character_reference_from_snapshot

        reference, said = character_reference_from_snapshot(
            self._Snapshot(["gamedata/binary__/client/bin/iteminfo.pabgb"])
        )
        self.assertIsNone(reference)
        self.assertIn("stand-in", said)

    def test_a_snapshot_that_will_not_read_is_reported_rather_than_raised(self) -> None:
        from cdmw.services.effect_character_reference import character_reference_from_snapshot

        class _Broken:
            entries = property(lambda self: (_ for _ in ()).throw(RuntimeError("the archives moved")))

        reference, said = character_reference_from_snapshot(_Broken())
        self.assertIsNone(reference)
        self.assertIn("the archives moved", said)


class PackageFrameTests(unittest.TestCase):
    """What the viewport is handed when a character came: the body in the scene, the item
    turned into it, and the rotation written down so the dialog can carry its numbers."""

    def _package(self, **overrides):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        preview = build_effect_placement_package(
            _blade(), (-0.3, -0.3, -0.3), (0.3, 0.3, 0.3), output_root=Path(folder.name), **overrides
        )
        return preview

    def test_the_body_is_every_one_of_its_submeshes(self) -> None:
        """The stand-in figure is one submesh and the game's character is several; the
        checkbox that hides it has to hide all of them or half a person stays on screen."""

        preview = self._package(character_mesh=_body(3), item_rotation=QUARTER_TURN)
        self.assertEqual(preview.body_submesh_count, 3)
        self.assertEqual(
            preview.body_submesh_indices,
            (preview.body_submesh_index, preview.body_submesh_index + 1, preview.body_submesh_index + 2),
        )

    def test_the_item_is_turned_and_the_rotation_comes_back(self) -> None:
        preview = self._package(character_mesh=_body(1), item_rotation=QUARTER_TURN)
        self.assertEqual(preview.item_rotation, QUARTER_TURN)
        scene = json.loads((Path(preview.package_dir) / "dotnet_scene.json").read_text(encoding="utf-8"))
        bounds = scene.get("bounds") or {}
        low = tuple(float(v) for v in (bounds.get("min") or bounds.get("low") or (0, 0, 0)))
        high = tuple(float(v) for v in (bounds.get("max") or bounds.get("high") or (0, 0, 0)))
        # the blade lay along z and the body stands along y; turned into the body's frame
        # the blade stands too, so the scene is taller than the blade is long
        self.assertGreater(high[1] - low[1], 0.9)

    def test_without_a_character_the_scene_is_the_item_s_own_frame(self) -> None:
        preview = self._package()
        self.assertIsNone(preview.item_rotation, "no character, no turn, and the numbers are the picture")
        self.assertEqual(preview.body_submesh_count, 1, "the stand-in figure is one piece")


if __name__ == "__main__":
    unittest.main()
