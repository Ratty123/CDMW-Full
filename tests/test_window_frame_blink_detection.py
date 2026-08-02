"""A blink is content that came back. Content that stayed is not a blink.

That distinction is the whole value of watching pixels: a panel that blanks and
repopulates from cache leaves a log identical to one that genuinely loaded
something. Getting it wrong in either direction makes the capture useless --
false positives bury the real ones, false negatives miss the thing being
reported -- so the rule is pinned here against synthetic frames rather than
against a running window.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "window_frame_capture.py"
_spec = importlib.util.spec_from_file_location("cdmw_window_frame_capture", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
capture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = capture
_spec.loader.exec_module(capture)


GRID = capture.DIFF_GRID


def _grid(value: float = 10.0) -> np.ndarray:
    """Built through the real reducer, so a shape mismatch cannot hide here."""

    side = GRID * capture.DIFF_DOWNSCALE
    frame = np.zeros((side, side, 4), dtype=np.uint8)
    frame[:, :, :3] = int(value)
    return capture.tile_means(frame)


def _with_patch(base: np.ndarray, value: float, rows: slice, cols: slice) -> np.ndarray:
    changed = base.copy()
    changed[rows, cols, :] = float(value)
    return changed


def _run(detector: capture.BlinkDetector, frames: list[np.ndarray]) -> list[capture.Blink]:
    found: list[capture.Blink] = []
    for index, frame in enumerate(frames, start=1):
        found.extend(detector.push(frame, at=float(index), frame_index=index))
    return found


class BlinkDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = capture.BlinkDetector()
        self.steady = _grid(10.0)
        self.blanked = _with_patch(self.steady, 200.0, slice(2, 6), slice(3, 9))

    def test_a_still_window_never_reports_a_blink(self) -> None:
        self.assertEqual(_run(self.detector, [self.steady] * 8), [])

    def test_content_that_changes_and_stays_is_not_a_blink(self) -> None:
        """The panel loaded something new. That is the interface working."""

        frames = [self.steady, self.steady, self.blanked, self.blanked, self.blanked, self.blanked]
        self.assertEqual(_run(self.detector, frames), [])

    def test_content_that_changes_and_comes_back_is_a_blink(self) -> None:
        frames = [self.steady, self.blanked, self.steady, self.steady]
        found = _run(self.detector, frames)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].frame_index, 2)
        self.assertEqual(found[0].returned_after, 1)

    def test_one_blink_is_reported_once(self) -> None:
        """A candidate re-judged on every new frame reports itself repeatedly."""

        frames = [self.steady, self.blanked, self.steady] + [self.steady] * 6
        self.assertEqual(len(_run(self.detector, frames)), 1)

    def test_a_slow_return_still_counts_within_the_window(self) -> None:
        frames = [self.steady, self.blanked, self.blanked, self.steady, self.steady]
        found = _run(self.detector, frames)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].returned_after, 2)

    def test_a_return_after_the_window_is_not_a_blink(self) -> None:
        """Coming back ten seconds later is navigation, not flicker."""

        frames = [self.steady] + [self.blanked] * 8 + [self.steady] * 3
        self.assertEqual(_run(self.detector, frames), [])

    def test_the_blink_names_the_region_that_blinked(self) -> None:
        frames = [self.steady, self.blanked, self.steady, self.steady]
        found = _run(self.detector, frames)
        left, top, right, bottom = found[0].tile_bounds
        self.assertEqual((left, top, right, bottom), (3, 2, 9, 6))

    def test_repeated_flicker_reports_each_blink(self) -> None:
        frames = [self.steady, self.blanked, self.steady, self.blanked, self.steady, self.steady]
        self.assertGreaterEqual(len(_run(self.detector, frames)), 2)

    def test_a_reset_forgets_everything(self) -> None:
        """A resized window has changed shape, not blinked."""

        self.detector.push(self.steady, at=1.0, frame_index=1)
        self.detector.push(self.blanked, at=2.0, frame_index=2)
        self.detector.reset()
        self.assertEqual(self.detector.push(self.steady, at=3.0, frame_index=3), [])

    def test_a_change_below_the_threshold_is_ignored(self) -> None:
        """Antialiasing and cursor blink must not fill the report."""

        barely = _with_patch(self.steady, 12.0, slice(2, 6), slice(3, 9))
        frames = [self.steady, barely, self.steady, self.steady]
        self.assertEqual(_run(self.detector, frames), [])


class TileReductionTests(unittest.TestCase):
    def test_tile_means_reduce_a_frame_to_the_grid(self) -> None:
        frame = np.zeros((GRID * capture.DIFF_DOWNSCALE, GRID * capture.DIFF_DOWNSCALE, 4), dtype=np.uint8)
        frame[:, :, :3] = 40
        tiles = capture.tile_means(frame)
        self.assertEqual(tiles.shape, (GRID, GRID, 3))
        self.assertTrue(np.allclose(tiles, 40.0))

    def test_a_bright_corner_shows_up_in_its_own_tile_only(self) -> None:
        side = GRID * capture.DIFF_DOWNSCALE
        frame = np.zeros((side, side, 4), dtype=np.uint8)
        frame[: capture.DIFF_DOWNSCALE, : capture.DIFF_DOWNSCALE, :3] = 255
        tiles = capture.tile_means(frame)
        self.assertGreater(tiles[0, 0].mean(), 0.0)
        self.assertEqual(tiles[1:, 1:].sum(), 0.0)


class RegionClassificationTests(unittest.TestCase):
    def test_a_blink_inside_the_viewport_is_named_as_one(self) -> None:
        """Chrome or viewport decides which half of the codebase owns it."""

        viewports = [(400, 100, 1200, 800)]
        self.assertEqual(capture._classify((500, 200, 700, 400), viewports), "viewport")

    def test_a_blink_outside_the_viewport_is_chrome(self) -> None:
        viewports = [(400, 100, 1200, 800)]
        self.assertEqual(capture._classify((0, 0, 100, 100), viewports), "chrome")

    def test_with_no_viewport_the_region_is_just_the_window(self) -> None:
        self.assertEqual(capture._classify((0, 0, 100, 100), []), "window")

    def test_tile_bounds_convert_to_pixels(self) -> None:
        pixels = capture._tile_bounds_to_pixels((0, 0, GRID, GRID), 1600, 800, GRID)
        self.assertEqual(pixels, (0, 0, 1600, 800))
        half = capture._tile_bounds_to_pixels((0, 0, GRID // 2, GRID // 2), 1600, 800, GRID)
        self.assertEqual(half, (0, 0, 800, 400))


if __name__ == "__main__":
    unittest.main()
