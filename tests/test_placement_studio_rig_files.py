"""Gates for the shared archive read behind Driven bones and Rig behaviour.

Finding anything in the archives means walking the package tables, which takes about four
seconds. Both rig panels need files from there, and both re-target whenever the Studio's
character changes, so the cost has to be paid once and only once.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.placement_studio import rig_files  # noqa: E402
from tools.placement_studio.rig_files import (  # noqa: E402
    POSE_MODIFIER_PATH,
    RigFiles,
    read_rig_files,
    reset_cache,
)


class _Entry:
    def __init__(self, path: str) -> None:
        self.path = path


class OnePassTests(unittest.TestCase):
    """One walk collects both panels' inputs, and is not walked again."""

    def setUp(self) -> None:
        reset_cache()
        self.addCleanup(reset_cache)
        self.walks = 0

    def _install(self, *paths: str):
        """Stand in for the archive tables, counting how often they are walked."""

        def iter_entries(_root):
            self.walks += 1
            for path in paths:
                yield ("pkg", _Entry(path))

        original_iter = rig_files.corpus._iter_archive_entries
        original_root = rig_files.corpus.game_root
        rig_files.corpus._iter_archive_entries = iter_entries
        rig_files.corpus.game_root = lambda: Path("nowhere")

        import cdmw.core.archive_extraction as extraction

        original_read = extraction.read_archive_entry_data
        extraction.read_archive_entry_data = lambda entry: (
            f"payload:{entry.path}".encode(), False, ""
        )

        def restore():
            rig_files.corpus._iter_archive_entries = original_iter
            rig_files.corpus.game_root = original_root
            extraction.read_archive_entry_data = original_read

        self.addCleanup(restore)

    def test_one_walk_returns_both_panels_inputs(self) -> None:
        self._install("a/b/rig.papr", POSE_MODIFIER_PATH, "a/b/model.pac")

        files = read_rig_files()

        self.assertEqual(self.walks, 1)
        self.assertEqual(files.constraint_paths, ("a/b/rig.papr",))
        self.assertEqual(files.constraints["a/b/rig.papr"], b"payload:a/b/rig.papr")
        self.assertTrue(files.pose_modifier)

    def test_the_walk_is_not_repeated(self) -> None:
        """Four seconds once is fine; four seconds per character switch is not."""

        self._install("a/b/rig.papr", POSE_MODIFIER_PATH)

        read_rig_files()
        read_rig_files()
        read_rig_files()

        self.assertEqual(self.walks, 1)

    def test_an_unreadable_entry_costs_one_panel_not_the_pass(self) -> None:
        self._install("a/b/rig.papr", POSE_MODIFIER_PATH)
        import cdmw.core.archive_extraction as extraction

        def explode(entry):
            if entry.path.endswith(".papr"):
                raise OSError("bad block")
            return (b"<PoseModifierData/>", False, "")

        extraction.read_archive_entry_data = explode

        files = read_rig_files()

        self.assertEqual(files.constraints["a/b/rig.papr"], b"")
        self.assertEqual(files.pose_modifier, b"<PoseModifierData/>")

    def test_an_install_without_the_descriptor_reports_empty_not_missing_key(self) -> None:
        self._install("a/b/rig.papr")

        files = read_rig_files()

        self.assertEqual(files.pose_modifier, b"")
        self.assertTrue(files.available)

    def test_an_empty_archive_set_is_reported_as_unavailable(self) -> None:
        self._install()

        self.assertFalse(read_rig_files().available)


class DefaultsTests(unittest.TestCase):
    def test_an_empty_bundle_needs_no_arguments(self) -> None:
        """The panels take a `RigFiles` unconditionally, including before any read."""

        files = RigFiles()
        self.assertEqual(files.constraint_paths, ())
        self.assertEqual(files.constraints, {})
        self.assertEqual(files.pose_modifier, b"")
        self.assertFalse(files.available)



class SlicedScanTests(OnePassTests):
    """The scan yields progress so the UI can paint between slices."""

    def test_the_scan_yields_a_result_only_on_its_last_step(self) -> None:
        from tools.placement_studio.rig_files import scan_rig_files

        self._install("a/b/rig.papr", POSE_MODIFIER_PATH)

        steps = list(scan_rig_files())

        self.assertTrue(steps)
        self.assertIsNone(steps[0][2] if len(steps) > 1 else None)
        self.assertIsNotNone(steps[-1][2])
        self.assertEqual(steps[-1][2].constraint_paths, ("a/b/rig.papr",))

    def test_a_warm_process_cache_still_yields_a_result(self) -> None:
        """The UI drives the generator either way; it must not come back empty-handed."""

        from tools.placement_studio.rig_files import read_rig_files, scan_rig_files

        self._install("a/b/rig.papr")
        read_rig_files()

        steps = list(scan_rig_files())

        self.assertEqual(len(steps), 1)
        self.assertIsNotNone(steps[0][2])


class DiskCacheTests(unittest.TestCase):
    """The scan is written out, so only the first session of all pays for it."""

    def setUp(self) -> None:
        from tools.placement_studio.rig_files import reset_cache

        reset_cache()
        self.addCleanup(reset_cache)

    def test_a_round_trip_through_the_cache_preserves_the_payloads(self) -> None:
        import tempfile
        from pathlib import Path

        from tools.placement_studio import rig_files

        files = rig_files.RigFiles(
            constraint_paths=("a/b/rig.papr",),
            constraints={"a/b/rig.papr": b"PAR payload"},
            pose_modifier=b"<PoseModifierData/>",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_work = rig_files.corpus.work_root
            original_stamp = rig_files._stamp
            rig_files.corpus.work_root = lambda: root / "work"
            rig_files._stamp = lambda _root: {"version": 1, "packages": []}
            try:
                rig_files._save_to_disk(root, files)
                loaded = rig_files._load_from_disk(root)
            finally:
                rig_files.corpus.work_root = original_work
                rig_files._stamp = original_stamp

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.constraints, files.constraints)
        self.assertEqual(loaded.pose_modifier, files.pose_modifier)

    def test_a_changed_archive_stamp_invalidates_the_cache(self) -> None:
        """A game update must not leave the panels showing the previous install."""

        import tempfile
        from pathlib import Path

        from tools.placement_studio import rig_files

        files = rig_files.RigFiles(constraint_paths=(), constraints={}, pose_modifier=b"x")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_work = rig_files.corpus.work_root
            original_stamp = rig_files._stamp
            rig_files.corpus.work_root = lambda: root / "work"
            rig_files._stamp = lambda _root: {"version": 1, "packages": [["a", 1, 1]]}
            try:
                rig_files._save_to_disk(root, files)
                rig_files._stamp = lambda _root: {"version": 1, "packages": [["a", 2, 9]]}
                loaded = rig_files._load_from_disk(root)
            finally:
                rig_files.corpus.work_root = original_work
                rig_files._stamp = original_stamp

        self.assertIsNone(loaded)

    def test_an_absent_cache_is_a_miss_not_an_error(self) -> None:
        import tempfile
        from pathlib import Path

        from tools.placement_studio import rig_files

        with tempfile.TemporaryDirectory() as tmp:
            original = rig_files.corpus.work_root
            rig_files.corpus.work_root = lambda: Path(tmp) / "nothing-here"
            try:
                self.assertIsNone(rig_files._load_from_disk(Path(tmp)))
            finally:
                rig_files.corpus.work_root = original

if __name__ == "__main__":
    unittest.main()
