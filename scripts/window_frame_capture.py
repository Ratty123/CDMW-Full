"""Capture the application window and find the moments it blinked.

A reader reporting "the interface flickers" is describing something no log in
this repository can see. This watches the pixels instead, and it distinguishes
the two things that look alike in a log:

    content updating   old -> new, and it stays new
    a blink            old -> something else -> old again, inside a few frames

Only the second is flicker, and only the second is reported. That difference is
the whole reason this exists: a preview panel that blanks itself and repopulates
from cache 60ms later leaves a trail identical to one that legitimately loaded
something, unless you look at the screen.

Capture is `PrintWindow` with `PW_RENDERFULLCONTENT`, which was measured against
the real Mesh Editor viewport: it returns the D3D11 swap-chain content, it works
while the window is behind other windows, and it captures nothing but the target
window -- so a session recording does not sweep up whatever else is on screen.

Standalone:

    .venv\\Scripts\\python.exe scripts\\window_frame_capture.py --seconds 60

Writes `blinks.jsonl` and PNG triples for each blink into an output directory.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
import time
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

DEFAULT_TITLE = "Crimson Desert Mod Workbench"
DEFAULT_FPS = 12.0
# Flicker is a large-area event, so the diff runs on a heavily reduced image.
# Reduction is stride slicing, which costs nothing.
DIFF_DOWNSCALE = 8
DIFF_GRID = 16
# Mean channel value, out of 255, over one tile.
CHANGED_THRESHOLD = 6.0
RETURNED_THRESHOLD = 2.5
# How many frames a region may take to come back and still count as a blink.
MAX_BLINK_FRAMES = 3
# How long to wait for the app window to exist. A cold start behind a splash and
# an archive scan is easily half a minute.
WINDOW_WAIT_SECONDS = 180.0

SRCCOPY = 0x00CC0020
PW_RENDERFULLCONTENT = 0x00000002

user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True) if sys.platform == "win32" else None


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _declare() -> None:
    """Without explicit signatures ctypes truncates 64-bit handles to int."""

    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsHungAppWindow.argtypes = [wintypes.HWND]
    user32.IsHungAppWindow.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
    ]


def set_dpi_aware() -> str:
    """Otherwise every rectangle is virtual pixels and nothing lines up."""

    for attempt, call in (
        ("per-monitor-v2", lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))),
        ("per-monitor", lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2)),
        ("system", lambda: ctypes.windll.user32.SetProcessDPIAware()),
    ):
        try:
            call()
            return attempt
        except Exception:
            continue
    return "none"


def _window_text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def owning_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def child_windows(hwnd: int) -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _each(child, _lparam):
        found.append(child)
        return True

    user32.EnumChildWindows(hwnd, _each, 0)
    return found


def find_app_window(title_fragment: str = DEFAULT_TITLE) -> Optional[int]:
    """The app window, told apart from the Build tool that shares its name.

    The one we want is the only one hosting a child from another process, which
    is the .NET viewport. Failing that -- the Mesh Editor may simply not be open
    yet -- the largest match wins.
    """

    matches: list[int] = []
    fragment = title_fragment.lower()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _each(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and fragment in _window_text(hwnd).lower():
            matches.append(hwnd)
        return True

    user32.EnumWindows(_each, 0)
    if not matches:
        return None

    def _area(hwnd: int) -> int:
        left, top, right, bottom = window_rect(hwnd)
        return (right - left) * (bottom - top)

    hosting = [
        hwnd
        for hwnd in matches
        if any(owning_pid(child) != owning_pid(hwnd) for child in child_windows(hwnd))
    ]
    return max(hosting or matches, key=_area)


def _await_app_window(
    title: str,
    *,
    should_stop: Optional[Callable[[], bool]] = None,
    timeout_seconds: float = WINDOW_WAIT_SECONDS,
) -> Optional[int]:
    """Wait for the app window, because the capture usually starts first.

    A cold start behind a splash and an archive scan takes tens of seconds; the
    capture is launched in the same breath as the app.
    """

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        hwnd = find_app_window(title)
        if hwnd is not None:
            return hwnd
        if should_stop is not None and should_stop():
            return None
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def viewport_rects(hwnd: int) -> list[tuple[int, int, int, int]]:
    """Cross-process children, in window-relative coordinates.

    A blink inside one of these is the 3D view; a blink outside is chrome. The
    distinction decides which half of the codebase to look at.
    """

    host_pid = owning_pid(hwnd)
    left, top, _right, _bottom = window_rect(hwnd)
    rects: list[tuple[int, int, int, int]] = []
    for child in child_windows(hwnd):
        if owning_pid(child) == host_pid:
            continue
        c_left, c_top, c_right, c_bottom = window_rect(child)
        rects.append((c_left - left, c_top - top, c_right - left, c_bottom - top))
    return rects


def window_is_hung(hwnd: int) -> bool:
    """Whether Windows considers this window's thread stuck.

    `PrintWindow` is a synchronous `SendMessage` into the target's UI thread and
    has no timeout variant, so calling it on a wedged window blocks this thread
    for as long as the wedge lasts. That happened: an app froze, the capture
    blocked in `PrintWindow` indefinitely, and the session it was recording
    never produced a report at all. Asking first costs nothing and turns a
    permanent block into an observation worth having.
    """

    try:
        return bool(user32.IsHungAppWindow(wintypes.HWND(hwnd)))
    except Exception:
        return False


def capture_window(hwnd: int, width: int, height: int) -> Optional[np.ndarray]:
    """One BGRA frame of the window, including its D3D11 child."""

    window_dc = user32.GetDC(hwnd)
    if not window_dc:
        return None
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT):
            return None
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # top-down
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        if gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0) == 0:
            return None
        return np.frombuffer(buffer, dtype=np.uint8).reshape((height, width, 4)).copy()
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def tile_means(frame: np.ndarray, grid: int = DIFF_GRID, downscale: int = DIFF_DOWNSCALE) -> np.ndarray:
    """Reduce a frame to a grid of average colours.

    Flicker is whole panels changing, so per-tile averages carry it and cost a
    fraction of a full-resolution comparison. Stride slicing does the downscale
    without touching most of the pixels at all.
    """

    small = frame[::downscale, ::downscale, :3].astype(np.float32)
    height, width = small.shape[:2]
    tile_h, tile_w = max(1, height // grid), max(1, width // grid)
    usable = small[: tile_h * grid, : tile_w * grid]
    # Colour channels are kept, not averaged away: the detector compares on
    # axis 2, and a panel can change hue without changing brightness.
    return usable.reshape(grid, tile_h, grid, tile_w, 3).mean(axis=(1, 3))


@dataclass
class Blink:
    at: float
    frame_index: int
    returned_after: int
    tiles: list[tuple[int, int]]
    magnitude: float
    tile_bounds: tuple[int, int, int, int]
    region: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)

    def as_row(self) -> dict:
        return {
            "t": round(self.at, 4),
            "event": "blink",
            "frame": self.frame_index,
            "returned_after_frames": self.returned_after,
            "tiles": len(self.tiles),
            "magnitude": round(self.magnitude, 2),
            "region": self.region,
            "bounds": list(self.bounds),
        }


@dataclass
class BlinkDetector:
    """Finds regions that changed and then changed back.

    Holds a short history of tile grids. For each candidate frame it asks
    whether some tiles differ from the frame before it, and whether those same
    tiles have returned to their earlier value within a few frames. Content that
    legitimately updated never returns, so it never fires.
    """

    grid: int = DIFF_GRID
    changed_threshold: float = CHANGED_THRESHOLD
    returned_threshold: float = RETURNED_THRESHOLD
    max_blink_frames: int = MAX_BLINK_FRAMES
    history: deque = field(default_factory=deque)

    def reset(self) -> None:
        self.history.clear()

    def push(self, tiles: np.ndarray, at: float, frame_index: int) -> list[Blink]:
        """Give every frame exactly one verdict, then slide past it.

        The window advances by `popleft` rather than by a bounded deque, because
        a candidate that is re-examined on each new frame reports the same blink
        once per frame until it falls out of history.
        """

        self.history.append((frame_index, at, tiles))
        found: list[Blink] = []
        while len(self.history) >= 3:
            _before_index, _before_at, before = self.history[0]
            candidate_index, candidate_at, candidate = self.history[1]
            changed = np.abs(candidate - before).mean(axis=2)
            changed_mask = changed > self.changed_threshold
            if not changed_mask.any():
                self.history.popleft()
                continue
            blink = self._settle(before, changed, changed_mask, candidate_index, candidate_at)
            if blink is not None:
                found.append(blink)
                self.history.popleft()
                continue
            # Nothing has come back yet. Once we have looked the full distance
            # ahead, this was content changing for good rather than a blink.
            if len(self.history) - 1 > self.max_blink_frames:
                self.history.popleft()
                continue
            break
        return found

    def _settle(
        self,
        before: np.ndarray,
        changed: np.ndarray,
        changed_mask: np.ndarray,
        candidate_index: int,
        candidate_at: float,
    ) -> Optional[Blink]:
        for offset in range(2, len(self.history)):
            later_index, _later_at, later = self.history[offset]
            returned = np.abs(later - before).mean(axis=2)
            blinked = changed_mask & (returned < self.returned_threshold)
            if not blinked.any():
                continue
            rows, cols = np.nonzero(blinked)
            return Blink(
                at=candidate_at,
                frame_index=candidate_index,
                returned_after=later_index - candidate_index,
                tiles=list(zip(rows.tolist(), cols.tolist())),
                magnitude=float(changed[blinked].mean()),
                tile_bounds=(int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1),
            )
        return None


def _tile_bounds_to_pixels(bounds: tuple[int, int, int, int], width: int, height: int, grid: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = bounds
    return (
        int(left * width / grid),
        int(top * height / grid),
        int(right * width / grid),
        int(bottom * height / grid),
    )


def _classify(pixel_bounds: tuple[int, int, int, int], viewports: list[tuple[int, int, int, int]]) -> str:
    """Chrome or viewport: which half of the codebase owns this blink."""

    left, top, right, bottom = pixel_bounds
    centre_x, centre_y = (left + right) // 2, (top + bottom) // 2
    for v_left, v_top, v_right, v_bottom in viewports:
        if v_left <= centre_x < v_right and v_top <= centre_y < v_bottom:
            return "viewport"
    return "chrome" if viewports else "window"


# PrintWindow is not free and it is not free for the *target*: it drives the
# window to render synchronously, on the application's own UI thread. A capture
# that keeps the app busy a quarter of the time is measuring something it
# created. The loop therefore holds itself to this share of wall clock, whatever
# the window costs, and reports the rate it actually achieved.
DEFAULT_DUTY_BUDGET = 0.25


@dataclass
class CaptureResult:
    frames: int = 0
    blinks: list[dict] = field(default_factory=list)
    dropped: int = 0
    stopped_reason: str = ""
    median_capture_ms: float = 0.0
    effective_fps: float = 0.0
    # Wall-clock stamps where the window stopped responding.
    hangs: list = field(default_factory=list)


def run_capture(
    output_dir: Path,
    *,
    title: str = DEFAULT_TITLE,
    fps: float = DEFAULT_FPS,
    seconds: float = 0.0,
    should_stop: Optional[Callable[[], bool]] = None,
    save_evidence: bool = True,
    duty_budget: float = DEFAULT_DUTY_BUDGET,
    on_blink: Optional[Callable[[dict], None]] = None,
) -> CaptureResult:
    """Capture until told to stop, reporting every blink seen."""

    if sys.platform != "win32":
        return CaptureResult(stopped_reason="not_windows")
    _declare()
    set_dpi_aware()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = output_dir / "blink-frames"
    result = CaptureResult()
    detector = BlinkDetector()
    recent: deque = deque(maxlen=MAX_BLINK_FRAMES + 2)
    blink_log = output_dir / "blinks.jsonl"
    blink_log.write_text("", encoding="utf-8")

    # The monitor starts this at the same moment it launches the app, so the
    # window does not exist yet. Looking once and giving up meant a whole
    # session recorded zero frames and reported "window_not_found" as if the app
    # had never opened.
    hwnd = _await_app_window(title, should_stop=should_stop, timeout_seconds=WINDOW_WAIT_SECONDS)
    if hwnd is None:
        return CaptureResult(stopped_reason="window_not_found")
    viewports = viewport_rects(hwnd)
    requested_interval = 1.0 / max(1.0, float(fps))
    interval = requested_interval
    budget = min(1.0, max(0.01, float(duty_budget)))
    capture_costs: list[float] = []
    started = time.monotonic()
    last_size: tuple[int, int] = (0, 0)
    frame_index = 0
    hang_reported = False

    while True:
        if should_stop is not None and should_stop():
            result.stopped_reason = "asked_to_stop"
            break
        if seconds and (time.monotonic() - started) >= seconds:
            result.stopped_reason = "duration_reached"
            break
        cycle_started = time.monotonic()
        if not user32.IsWindow(wintypes.HWND(hwnd)):
            result.stopped_reason = "window_closed"
            break
        left, top, right, bottom = window_rect(hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            time.sleep(interval)
            continue
        if (width, height) != last_size:
            # A resize invalidates every stored comparison; a window that just
            # changed shape has not blinked, it has been resized.
            detector.reset()
            recent.clear()
            viewports = viewport_rects(hwnd)
            last_size = (width, height)
        if window_is_hung(hwnd):
            # Never call PrintWindow into a wedged window: it would block this
            # thread until the wedge cleared, and the session would end with no
            # report. Say so instead, once per stall, on the shared clock.
            if not hang_reported:
                hang_reported = True
                result.hangs.append(round(time.time(), 4))
                row = {
                    "t": round(time.time(), 4),
                    "event": "app_window_hung",
                    "frame": frame_index,
                    "note": "capture skipped; the window stopped responding",
                }
                with open(blink_log, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row) + "\n")
                if on_blink is not None:
                    on_blink(row)
            result.dropped += 1
            time.sleep(max(interval, 0.5))
            continue
        hang_reported = False
        capture_started = time.monotonic()
        frame = capture_window(hwnd, width, height)
        capture_cost = time.monotonic() - capture_started
        if frame is None:
            result.dropped += 1
            time.sleep(interval)
            continue
        capture_costs.append(capture_cost)
        # Back off to keep the app's share of the cost inside the budget. A big
        # window simply gets sampled less often rather than being slowed down.
        interval = max(requested_interval, capture_cost / budget)
        captured_at = time.time()
        result.frames += 1
        frame_index += 1
        recent.append((frame_index, frame))
        for blink in detector.push(tile_means(frame, detector.grid), captured_at, frame_index):
            pixel_bounds = _tile_bounds_to_pixels(blink.tile_bounds, width, height, detector.grid)
            blink.bounds = pixel_bounds
            blink.region = _classify(pixel_bounds, viewports)
            row = blink.as_row()
            if save_evidence:
                row["frames"] = _save_evidence(frames_dir, recent, blink)
            result.blinks.append(row)
            with open(blink_log, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            if on_blink is not None:
                on_blink(row)
        elapsed = time.monotonic() - cycle_started
        if elapsed < interval:
            time.sleep(interval - elapsed)
    if capture_costs:
        ordered = sorted(capture_costs)
        result.median_capture_ms = round(ordered[len(ordered) // 2] * 1000.0, 2)
    total_seconds = max(1e-6, time.monotonic() - started)
    result.effective_fps = round(result.frames / total_seconds, 2)
    return result


def _save_evidence(frames_dir: Path, recent: deque, blink: Blink) -> list[str]:
    """Write the before, during and after of one blink, and nothing else.

    Saving every frame of a session is gigabytes nobody reads. Three frames per
    blink is what makes the report answer "show me".
    """

    try:
        from PIL import Image
    except ImportError:
        return []
    frames_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    wanted = {blink.frame_index - 1, blink.frame_index, blink.frame_index + blink.returned_after}
    for index, frame in recent:
        if index not in wanted:
            continue
        path = frames_dir / f"blink-{blink.frame_index:06d}-f{index:06d}.png"
        try:
            Image.fromarray(frame[:, :, :3][:, :, ::-1]).save(path)
            written.append(path.name)
        except Exception:
            continue
    return written


class CaptureThread:
    """Runs the capture beside a monitor that owns the rest of the session."""

    def __init__(self, output_dir: Path, **options: object) -> None:
        self._output_dir = Path(output_dir)
        self._options = options
        self._stop = threading.Event()
        self.result: Optional[CaptureResult] = None
        self._thread = threading.Thread(target=self._run, name="cdmw-frame-capture", daemon=True)

    def _run(self) -> None:
        try:
            self.result = run_capture(self._output_dir, should_stop=self._stop.is_set, **self._options)
        except Exception as exc:  # noqa: BLE001 - reported, never raised into the monitor
            self.result = CaptureResult(stopped_reason=f"failed: {exc}")

    def start(self) -> "CaptureThread":
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> Optional[CaptureResult]:
        self._stop.set()
        self._thread.join(timeout=timeout)
        return self.result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--out", default="")
    parser.add_argument("--no-evidence", action="store_true", help="detect blinks without saving PNGs")
    parser.add_argument(
        "--duty",
        type=float,
        default=DEFAULT_DUTY_BUDGET,
        help="Share of wall clock the capture may spend. The default 0.25 keeps "
        "the app responsive but caps sampling near 5 fps, which is too slow to "
        "see a blink that lasts two frames of a 60 Hz interface. Raise it to "
        "0.5 or 0.7 for a flicker hunt and accept that the app slows down.",
    )
    args = parser.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path(__file__).resolve().parents[1] / "workspace" / "evidence" / f"frame-capture-{stamp}"
    print(f"Capturing {args.title!r} at {args.fps:g} fps for {args.seconds:g}s")
    print(f"Output: {out}")

    def _announce(row: dict) -> None:
        print(f"  blink at {row['t']:.2f}  {row['region']:<8} {row['tiles']} tiles  magnitude {row['magnitude']}")

    result = run_capture(
        out,
        title=args.title,
        fps=args.fps,
        seconds=args.seconds,
        save_evidence=not args.no_evidence,
        duty_budget=args.duty,
        on_blink=_announce,
    )
    print()
    print(f"frames captured: {result.frames}, dropped: {result.dropped}")
    print(f"capture cost: {result.median_capture_ms:g} ms median, effective {result.effective_fps:g} fps")
    if result.effective_fps and result.effective_fps < args.fps - 0.5:
        print(f"  (held below the requested {args.fps:g} fps to keep the app's share under the duty budget)")
    print(f"blinks: {len(result.blinks)} ({result.stopped_reason})")
    if result.stopped_reason == "window_not_found":
        print(f"No visible window matched {args.title!r}. Is the app running?")
        return 1
    for row in result.blinks[:20]:
        print(f"  {row['t']:.2f}  {row['region']:<8} bounds={row['bounds']} magnitude={row['magnitude']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
