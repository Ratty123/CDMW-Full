"""Gates for the first placement an imported weapon lands at (`fitted_placement`).

The fit is a guess the reader corrects, so the only thing that matters about it is which
guess costs the least correction. For a weapon that is one long axis and a heavy end, the
answer is the grip: matching the two bounding boxes' middles instead leaves the handle
half a weapon from the hand, which is a big drag on every import whose mass sits at one
end -- an axe, a hammer, a halberd.
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

    def test_the_scale_still_matches_the_template_s_length(self) -> None:
        axe = bounds((-0.4, -0.1, -2.0), (0.4, 0.1, 0.0))
        placement, (low, high) = self.placed(axe, source_centroid=(0.0, 0.0, -1.5))
        self.assertAlmostEqual(placement.scale[0], 0.5, places=4, msg="two metres into one")
        self.assertAlmostEqual(high - low, 1.0, places=3)

    def test_nothing_to_fit_is_no_placement(self) -> None:
        self.assertEqual(fitted_placement(None, self.TEMPLATE).offset, (0.0, 0.0, 0.0))
        self.assertEqual(fitted_placement(self.TEMPLATE, None).scale, (1.0, 1.0, 1.0))


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
