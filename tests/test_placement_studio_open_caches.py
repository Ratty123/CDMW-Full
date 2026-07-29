"""Gates for the two caches the Placement Studio opens against.

Opening the Studio used to walk all 33 package tables for the clip index and re-extract a
character's socket files and action charts, every time — about six seconds of UI-thread work
that the viewport dropped frames through. Both are stored now, keyed by a signature over the
package tables, and the risk moves from "slow" to "stale or subtly different": a cache that
reorders the index changes which clips a broad search lists, and one that outlives a game
patch hands back offsets into files that have moved.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.models import ArchiveEntry  # noqa: E402
from tools.placement_studio import armour, clips  # noqa: E402


def _entry(name: str, pamt: str, paz: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(
        path=name,
        pamt_path=Path(pamt),
        paz_file=Path(paz),
        offset=offset,
        comp_size=offset * 2,
        orig_size=offset * 3,
        flags=1,
        paz_index=offset % 4,
    )


def _sample_index() -> clips.ClipIndex:
    """One `.pamt` naming two `.paz` files, interleaved — the case that broke ordering.

    Grouping rows under the (table, archive) pair looks like the natural encoding and splits
    a package's rows apart, which silently reorders the index.
    """

    rows = []
    for position in range(10):
        paz = "a.paz" if position % 2 == 0 else "b.paz"
        rows.append(clips._entry(
            f"character/motion/1_pc/1_phm/cd_phm_{position:02d}_weapon_out.paa",
            _entry(f"clip{position}", "one.pamt", paz, position + 1),
        ))
    rows.append(clips._entry(
        "character/motion/1_pc/2_phw/cd_phw_idle_lod.paa",
        _entry("lod", "two.pamt", "c.paz", 99),
    ))
    return clips.ClipIndex(rows)


def _not_a_cache() -> bytes:
    """A well-formed zlib stream whose header decodes to the wrong JSON shape."""

    import json
    import zlib

    header = json.dumps([]).encode("utf-8")
    return zlib.compress(len(header).to_bytes(8, "little") + header + b"\x00" * 64, 1)


def _fingerprint(index: clips.ClipIndex):
    return [
        (
            entry.path, entry.rig, entry.category, entry.is_lod,
            str(entry.source.pamt_path), str(entry.source.paz_file),
            entry.source.offset, entry.source.comp_size, entry.source.orig_size,
            entry.source.flags, entry.source.paz_index,
        )
        for entry in index.entries
    ]


class _Sandbox(unittest.TestCase):
    """Points the work and game roots at throwaway directories."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        self._work = root / "work"
        self._game = root / "game"
        self._work.mkdir()
        self._game.mkdir()
        self._saved = {
            key: os.environ.get(key)
            for key in ("CDMW_PS_WORK_ROOT", "CDMW_PS_GAME_ROOT")
        }
        os.environ["CDMW_PS_WORK_ROOT"] = str(self._work)
        os.environ["CDMW_PS_GAME_ROOT"] = str(self._game)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temp.cleanup()


class ClipIndexCacheTests(_Sandbox):
    def test_a_cached_index_is_identical_to_the_one_that_was_scanned(self) -> None:
        original = _sample_index()
        clips._write_cache(self._game, original)
        parts = clips._read_cache(self._game)
        self.assertIsNotNone(parts, "a cache just written should be readable")

        rebuilt = None
        for _done, _total, result in clips._decode_cache(parts):
            if result is not None:
                rebuilt = result
        self.assertIsNotNone(rebuilt)
        self.assertEqual(_fingerprint(original), _fingerprint(rebuilt))

    def test_the_cache_keeps_scan_order_across_interleaved_archives(self) -> None:
        """`filter` returns in stored order and the browser draws the first 800 of them."""

        original = _sample_index()
        clips._write_cache(self._game, original)
        parts = clips._read_cache(self._game)
        rebuilt = [r for _d, _t, r in clips._decode_cache(parts) if r is not None][0]
        self.assertEqual(
            [entry.path for entry in original.entries],
            [entry.path for entry in rebuilt.entries],
        )

    def test_a_changed_install_is_refused_rather_than_misread(self) -> None:
        clips._write_cache(self._game, _sample_index())
        self.assertIsNotNone(clips._read_cache(self._game))
        # A game patch rewrites the package tables, so every stored offset is a guess.
        (self._game / "patched.pamt").write_bytes(b"x" * 16)
        self.assertIsNone(clips._read_cache(self._game))

    def test_a_renamed_category_is_refused_rather_than_shifting_every_label(self) -> None:
        clips._write_cache(self._game, _sample_index())
        saved = clips._CATEGORY_BY_ID
        try:
            clips._CATEGORY_BY_ID = ("brand_new", *saved)
            self.assertIsNone(clips._read_cache(self._game))
        finally:
            clips._CATEGORY_BY_ID = saved

    def test_a_corrupt_file_is_refused_rather_than_raising(self) -> None:
        clips._write_cache(self._game, _sample_index())
        clips._cache_file().write_bytes(b"not a zlib stream")
        self.assertIsNone(clips._read_cache(self._game))

    def test_a_valid_stream_that_is_not_a_cache_is_refused(self) -> None:
        """Valid zlib around a JSON list used to raise AttributeError through the generator,
        which the UI stepper caught as a scan failure and answered by dropping the browser to
        the pinned baseline — permanently, since the bad file was still there next launch."""

        clips._cache_file().parent.mkdir(parents=True, exist_ok=True)
        clips._cache_file().write_bytes(_not_a_cache())
        self.assertIsNone(clips._read_cache(self._game))

    def test_a_rewritten_paz_is_refused(self) -> None:
        archive = self._game / "0001.paz"
        archive.write_bytes(b"a" * 32)
        clips._write_cache(self._game, _sample_index())
        self.assertIsNotNone(clips._read_cache(self._game))
        archive.write_bytes(b"b" * 64)
        self.assertIsNone(clips._read_cache(self._game))

    def test_an_edited_classification_rule_is_refused(self) -> None:
        """Same labels, different regex: every stored row keeps the old classification."""

        clips._write_cache(self._game, _sample_index())
        self.assertIsNotNone(clips._read_cache(self._game))
        saved = clips._CATEGORIES
        try:
            clips._CATEGORIES = tuple(
                (label, pattern + "|_cleave") if label == "attack" else (label, pattern)
                for label, pattern in saved
            )
            self.assertIsNone(clips._read_cache(self._game))
        finally:
            clips._CATEGORIES = saved

    def test_reset_drops_the_file_and_is_safe_when_there_is_none(self) -> None:
        clips._write_cache(self._game, _sample_index())
        self.assertTrue(clips._cache_file().exists())
        clips.reset_cache()
        self.assertFalse(clips._cache_file().exists())
        clips.reset_cache()  # must not raise


class ExtractedContentCacheTests(_Sandbox):
    def test_payloads_round_trip_exactly(self) -> None:
        payloads = {
            "actionchart/a.paac": b"\x00\x01\x02binary",
            "actionchart/b.paac": b"",  # a zero-length entry must not shift the ones after it
            "character/c.sockets.xml": b"<sockets/>",
        }
        armour.store_content("1_phm", "charts", payloads, self._game)
        self.assertEqual(armour.cached_content("1_phm", "charts", self._game), payloads)

    def test_each_character_and_kind_is_kept_apart(self) -> None:
        armour.store_content("1_phm", "charts", {"a": b"kliff"}, self._game)
        armour.store_content("2_phw", "charts", {"a": b"damian"}, self._game)
        armour.store_content("1_phm", "sockets", {"a": b"socket"}, self._game)
        self.assertEqual(armour.cached_content("1_phm", "charts", self._game), {"a": b"kliff"})
        self.assertEqual(armour.cached_content("2_phw", "charts", self._game), {"a": b"damian"})
        self.assertEqual(armour.cached_content("1_phm", "sockets", self._game), {"a": b"socket"})

    def test_nothing_stored_reads_as_nothing_cached(self) -> None:
        self.assertIsNone(armour.cached_content("1_phm", "charts", self._game))

    def test_a_changed_install_is_refused(self) -> None:
        armour.store_content("1_phm", "charts", {"a": b"kliff"}, self._game)
        self.assertIsNotNone(armour.cached_content("1_phm", "charts", self._game))
        (self._game / "patched.pamt").write_bytes(b"x" * 16)
        self.assertIsNone(armour.cached_content("1_phm", "charts", self._game))

    def test_a_rewritten_paz_is_refused(self) -> None:
        """A row is an offset into a `.paz`; signing only the tables misses a payload swap."""

        archive = self._game / "0001.paz"
        archive.write_bytes(b"a" * 32)
        armour.store_content("1_phm", "charts", {"a": b"kliff"}, self._game)
        self.assertIsNotNone(armour.cached_content("1_phm", "charts", self._game))
        archive.write_bytes(b"b" * 64)
        self.assertIsNone(armour.cached_content("1_phm", "charts", self._game))

    def test_a_corrupt_file_is_refused_rather_than_raising(self) -> None:
        armour.store_content("1_phm", "charts", {"a": b"kliff"}, self._game)
        armour._content_file("1_phm", "charts").write_bytes(b"not a zlib stream")
        self.assertIsNone(armour.cached_content("1_phm", "charts", self._game))

    def test_a_valid_stream_that_is_not_a_cache_is_refused(self) -> None:
        """Valid zlib around a JSON list used to raise AttributeError out of this call."""

        armour._content_file("1_phm", "charts").write_bytes(_not_a_cache())
        self.assertIsNone(armour.cached_content("1_phm", "charts", self._game))


class SharedSignatureTests(_Sandbox):
    def test_both_caches_key_off_the_same_reading_of_the_tables(self) -> None:
        """Three copies of this would be three chances to disagree about staleness."""

        from tools.placement_studio.corpus import package_signature

        (self._game / "one.pamt").write_bytes(b"x" * 16)
        self.assertEqual(armour._cache_signature(self._game), package_signature(self._game))


if __name__ == "__main__":
    unittest.main()
