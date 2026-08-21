"""Gates for reading an FBX through Blender.

The studio reads glTF, GLB, OBJ and DAE itself and does not read FBX: the container is a
typed node tree and easy enough, but the transform stack, the layer-element mapping modes
and the axis and unit conversion are where an FBX arrives rotated, mirrored or a hundred
times too large. Blender reads those correctly, so FBX is supported through Blender -- and
only through a Blender the reader pointed at, so that a conversion is always something
they asked for and can account for when the result looks wrong.

Nothing here runs Blender: the run is a seam, so the gate says what the studio does with
what comes back rather than what Blender does.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.services.fbx_blender_conversion import (  # noqa: E402
    BlenderNotConfigured,
    convert_fbx_to_glb,
    is_blender_executable,
    likely_blender_executables,
)


@dataclass
class _Finished:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class ConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.folder = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)
        self.fbx = self.folder / "MagicSword.fbx"
        self.fbx.write_bytes(b"Kaydara FBX Binary  \x00")
        # what a Blender looks like to the checks, without being one
        self.blender = self.folder / "blender.exe"
        self.blender.write_bytes(b"")

    def _run(self, *, code: int = 0, stdout: str = "", stderr: str = "", write: bool = True):
        def run(command):
            self.commands.append(list(command))
            if write:
                (self.folder / "MagicSword.glb").write_bytes(b"glTF" + bytes(64))
            return _Finished(code, stdout, stderr)

        self.commands: list = []
        return run

    def test_no_blender_is_refused_by_name_rather_than_attempted(self) -> None:
        with self.assertRaises(BlenderNotConfigured) as caught:
            convert_fbx_to_glb(self.fbx, "", output_dir=self.folder, run=self._run())
        message = str(caught.exception)
        self.assertIn("needs Blender", message)
        self.assertIn("Choose blender.exe", message)
        self.assertIn("glTF, GLB, OBJ or DAE", message, "and what to do without one")

    def test_the_conversion_says_what_came_through(self) -> None:
        run = self._run(stdout='Blender 5.1.1\nCDMW_FBX_RESULT {"objects": 1, "vertices": 1458, "materials": ["Steel"], "images": ["Albedo"]}')
        result = convert_fbx_to_glb(self.fbx, self.blender, output_dir=self.folder, run=run)
        self.assertEqual(result.glb.name, "MagicSword.glb")
        self.assertEqual((result.objects, result.vertices), (1, 1458))
        self.assertEqual((result.materials, result.images), (("Steel",), ("Albedo",)))
        summary = result.summary(self.fbx)
        self.assertIn("1,458 vertices", summary)
        self.assertIn("Steel", summary)
        self.assertNotIn("references no textures", summary, "it brought an image of its own")

    def test_an_fbx_that_references_no_textures_says_so(self) -> None:
        """The Verdict axe and the magic sword are both like this: geometry and UVs, with
        the PNGs loose beside them and nothing in the file pointing at them. What saves
        those is the studio matching the images beside the file by name afterwards -- three
        of the magic sword's five -- so the line says which of the two happened."""

        run = self._run(stdout='CDMW_FBX_RESULT {"objects": 1, "vertices": 1458, "materials": [], "images": []}')
        result = convert_fbx_to_glb(self.fbx, self.blender, output_dir=self.folder, run=run)
        summary = result.summary(self.fbx)
        self.assertIn("references no textures of its own", summary)
        # and what happens then: the studio matches the images beside the file by name, so
        # this is not the same as the model arriving with nothing
        self.assertIn("matched by name", summary)

    def test_blender_is_run_headless_from_factory_settings(self) -> None:
        """A reader's own add-ons and preferences must not change what a conversion
        produces, and no window may open behind the studio."""

        run = self._run()
        convert_fbx_to_glb(self.fbx, self.blender, output_dir=self.folder, run=run)
        command = self.commands[0]
        self.assertEqual(command[0], str(self.blender))
        for flag in ("--background", "--factory-startup", "--python"):
            self.assertIn(flag, command)
        self.assertEqual(command[-2:], [str(self.fbx), str(self.folder / "MagicSword.glb")])

    def test_a_failed_conversion_carries_what_blender_said(self) -> None:
        """"The import failed" is not something a reader can act on."""

        run = self._run(code=31, stderr="Error: FBX version 6100 unsupported", write=False)
        with self.assertRaises(RuntimeError) as caught:
            convert_fbx_to_glb(self.fbx, self.blender, output_dir=self.folder, run=run)
        self.assertIn("FBX version 6100 unsupported", str(caught.exception))

    def test_blender_that_writes_nothing_is_a_failure_even_at_exit_zero(self) -> None:
        run = self._run(code=0, stdout="all good", write=False)
        with self.assertRaises(RuntimeError):
            convert_fbx_to_glb(self.fbx, self.blender, output_dir=self.folder, run=run)


class SuggestionTests(unittest.TestCase):
    def test_a_suggestion_is_not_a_choice(self) -> None:
        """Whatever this machine happens to have is a place for a file dialog to open, not
        the studio's Blender: a conversion nobody asked for is one nobody can account for."""

        for candidate in likely_blender_executables():
            self.assertTrue(is_blender_executable(candidate), candidate)

        from cdmw.ui.new_item.blender_setting import blender_for_fbx

        # nothing is used until it is stored, and only a real executable can be stored
        self.assertIn(blender_for_fbx(), ("", *(str(path) for path in likely_blender_executables())))

    def test_what_counts_as_a_blender(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "blender.exe").write_bytes(b"")
            (root / "notepad.exe").write_bytes(b"")
            self.assertTrue(is_blender_executable(root / "blender.exe"))
            self.assertFalse(is_blender_executable(root / "notepad.exe"))
            self.assertFalse(is_blender_executable(root / "blender.exe.missing"))
            self.assertFalse(is_blender_executable(""))


if __name__ == "__main__":
    unittest.main()
