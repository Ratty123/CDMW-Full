"""Image operations for the Texture Editor, in numpy and Pillow.

Every Texture Editor call that used OpenCV goes through this module (P16
stage 2). Each function here reproduces what OpenCV 4.13 returned for the
same call, pinned by ``tests/test_image_ops.py`` against OpenCV's own output
(``tests/fixtures/image_ops/cv2_reference.npz``):

- exact: the same bytes as OpenCV;
- within a stated tolerance where OpenCV computes in fixed point or with
  vector rounding that numpy does not reproduce; each such function says how
  far it may differ and why that is invisible to the caller.

OpenCV is imported here and nowhere else. Three groups:

- replaced: numpy or Pillow only (borders, the ellipse kernel, dilate and
  erode, the rotation matrix, PNG);
- written and pinned, but OpenCV first: the numpy version is many times slower
  on a 4096 x 4096 layer, and these run per stroke or per composite, so they
  call OpenCV while it is installed and fall back to numpy without it (gray,
  HSV, the lookup table, addWeighted, Gaussian blur, resize);
- OpenCV only, not written yet (flood fill, antialiased polygon fill,
  contours, polygon simplification, Canny, bilateral and median filters,
  affine warp).

``uses_opencv`` lists the last two groups; a test keeps it complete.
"""

from __future__ import annotations

import io
import math
from functools import lru_cache
from typing import Optional, Sequence, Tuple

import numpy as np

# ---- OpenCV, only for what is not replaced yet ---------------------------------------------

_cv2_module = None
_cv2_missing = False


def _opencv_or_none():
    """OpenCV when it is installed, else None (the numpy versions then answer)."""

    global _cv2_module, _cv2_missing
    if _cv2_module is None and not _cv2_missing:
        try:
            import cv2  # noqa: PLC0415 - the one place the app imports OpenCV
        except ImportError:
            _cv2_missing = True
        else:
            _cv2_module = cv2
    return _cv2_module


def _cv2():
    """OpenCV for functions that have no replacement yet."""

    module = _opencv_or_none()
    if module is None:
        raise ImportError("This Texture Editor operation still needs OpenCV (opencv-python-headless).")
    return module


def opencv_available() -> bool:
    return _opencv_or_none() is not None


# Functions that call OpenCV (first or only). A test keeps this list complete.
uses_opencv: Tuple[str, ...] = (
    "rgba_to_gray",
    "apply_lut",
    "add_weighted",
    "rgb_to_hsv",
    "hsv_to_rgb",
    "gaussian_blur",
    "resize",
    "flood_fill_mask_only",
    "flood_fill_value",
    "fill_polygon_antialiased",
    "find_outer_contours_ccomp",
    "contour_arc_length",
    "approx_polygon",
    "canny_edges",
    "bilateral_filter",
    "median_blur",
    "warp_affine_linear",
)


# ---- borders and channels (exact) -----------------------------------------------------------


def pad_constant(image: np.ndarray, pad: int, value: Sequence[int] | int = 0) -> np.ndarray:
    """``cv2.copyMakeBorder(image, pad, pad, pad, pad, BORDER_CONSTANT, value=value)``."""

    source = np.asarray(image)
    amount = max(0, int(pad))
    shape = (source.shape[0] + 2 * amount, source.shape[1] + 2 * amount) + source.shape[2:]
    out = np.empty(shape, dtype=source.dtype)
    fill = np.asarray(value, dtype=np.float64)
    if source.ndim == 3 and fill.ndim == 1:
        fill = fill[: source.shape[2]]
    out[...] = fill.astype(source.dtype)
    out[amount : amount + source.shape[0], amount : amount + source.shape[1]] = source
    return out


def swap_red_blue(image: np.ndarray) -> np.ndarray:
    """RGB <-> BGR and RGBA <-> BGRA (``COLOR_RGB2BGR``, ``COLOR_RGBA2BGRA``, ``COLOR_BGRA2RGBA``)."""

    source = np.asarray(image)
    order = [2, 1, 0] + ([3] if source.shape[2] == 4 else [])
    return np.ascontiguousarray(source[..., order])


def _rgba_to_gray_numpy(image: np.ndarray) -> np.ndarray:
    """``COLOR_RGBA2GRAY`` / ``COLOR_RGB2GRAY`` for 8-bit images, OpenCV's 15-bit fixed point."""

    source = np.asarray(image, dtype=np.uint8)
    r = source[..., 0].astype(np.uint32)
    g = source[..., 1].astype(np.uint32)
    b = source[..., 2].astype(np.uint32)
    return ((r * 9798 + g * 19235 + b * 3735 + (1 << 14)) >> 15).astype(np.uint8)


def _apply_lut_numpy(image: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """``cv2.LUT`` with a single 256-entry table applied to every channel."""

    table = np.asarray(lut).reshape(-1)
    if table.size != 256:
        raise ValueError("A lookup table needs 256 entries.")
    return np.take(table, np.asarray(image, dtype=np.uint8))


def _add_weighted_numpy(first: np.ndarray, alpha: float, second: np.ndarray, beta: float, gamma: float) -> np.ndarray:
    """``cv2.addWeighted`` for float32 images (within 1e-4; see the tests)."""

    a = np.asarray(first, dtype=np.float32)
    b = np.asarray(second, dtype=np.float32)
    return (a.astype(np.float64) * alpha + b.astype(np.float64) * beta + gamma).astype(np.float32)


# ---- PNG (exact pixels) ---------------------------------------------------------------------


def encode_png(image: np.ndarray) -> bytes:
    """PNG bytes for an 8-bit gray, RGB or RGBA array, in that channel order.

    OpenCV wrote BGR(A) arrays as RGB(A) files; callers that used to swap to
    BGRA before ``cv2.imencode`` pass RGBA here and the file is the same image.
    """

    from PIL import Image

    array = np.ascontiguousarray(np.asarray(image, dtype=np.uint8))
    if array.ndim == 2:
        mode = "L"
    elif array.ndim == 3 and array.shape[2] in (3, 4):
        mode = "RGB" if array.shape[2] == 3 else "RGBA"
    else:
        raise ValueError(f"Cannot write a PNG from an array shaped {array.shape}.")
    stream = io.BytesIO()
    # Level 1 keeps history snapshots fast, as OpenCV's default did.
    Image.fromarray(array, mode=mode).save(stream, format="PNG", compress_level=1)
    return stream.getvalue()


def _decode_png_array(blob: bytes) -> Optional[np.ndarray]:
    """The stored image: 2D gray, or RGB / RGBA in file order; None when unreadable."""

    from PIL import Image

    if not blob:
        return None
    try:
        with Image.open(io.BytesIO(bytes(blob))) as image:
            image.load()
            mode = image.mode
            if mode == "P":
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            elif mode == "LA":
                gray, alpha = (np.asarray(band, dtype=np.uint8) for band in image.split())
                return np.stack((gray, gray, gray, alpha), axis=-1)
            elif mode in ("I;16", "I;16B", "I;16L", "I"):
                return np.asarray(image).astype(np.uint8)
            elif mode not in ("L", "RGB", "RGBA"):
                image = image.convert("RGBA")
            return np.array(image, dtype=np.uint8)
    except Exception:  # noqa: BLE001 - OpenCV returned None for any unreadable blob
        return None


def decode_png_rgba(blob: bytes) -> Optional[np.ndarray]:
    """What ``imdecode(UNCHANGED)`` then GRAY/BGR to BGRA then BGRA to RGBA gave: an RGBA array."""

    decoded = _decode_png_array(blob)
    if decoded is None:
        return None
    if decoded.ndim == 2:
        return np.stack((decoded, decoded, decoded, np.full_like(decoded, 255)), axis=-1)
    if decoded.shape[2] == 3:
        alpha = np.full(decoded.shape[:2] + (1,), 255, dtype=np.uint8)
        return np.ascontiguousarray(np.concatenate((decoded, alpha), axis=2))
    return np.ascontiguousarray(decoded)


def decode_png_mask(blob: bytes) -> Optional[np.ndarray]:
    """What ``imdecode(UNCHANGED)`` then ``[..., -1]`` for colour gave: one 8-bit channel.

    For a colour file that last channel was alpha (BGRA) or red (BGR).
    """

    decoded = _decode_png_array(blob)
    if decoded is None:
        return None
    if decoded.ndim == 2:
        return decoded
    if decoded.shape[2] == 3:
        return np.ascontiguousarray(decoded[..., 0])
    return np.ascontiguousarray(decoded[..., 3])


# ---- colour (HSV) ---------------------------------------------------------------------------

_HSV_SHIFT = 12


@lru_cache(maxsize=1)
def _hsv_tables() -> Tuple[np.ndarray, np.ndarray]:
    index = np.arange(256, dtype=np.float64)
    with np.errstate(divide="ignore"):
        sdiv = np.where(index > 0, np.rint((255 << _HSV_SHIFT) / index), 0).astype(np.int64)
        hdiv = np.where(index > 0, np.rint((180 << _HSV_SHIFT) / (6.0 * index)), 0).astype(np.int64)
    return sdiv, hdiv


def _rgb_to_hsv_numpy(image: np.ndarray) -> np.ndarray:
    """``COLOR_RGB2HSV`` for 8-bit RGB: H in [0, 180), OpenCV's integer arithmetic."""

    source = np.asarray(image, dtype=np.uint8)
    r = source[..., 0].astype(np.int64)
    g = source[..., 1].astype(np.int64)
    b = source[..., 2].astype(np.int64)
    v = np.maximum(np.maximum(r, g), b)
    vmin = np.minimum(np.minimum(r, g), b)
    diff = v - vmin
    sdiv, hdiv = _hsv_tables()
    half = 1 << (_HSV_SHIFT - 1)
    s = (diff * sdiv[v] + half) >> _HSV_SHIFT
    vr = v == r
    vg = v == g
    h = np.where(vr, g - b, np.where(vg, b - r + 2 * diff, r - g + 4 * diff))
    h = (h * hdiv[diff] + half) >> _HSV_SHIFT
    h = np.where(h < 0, h + 180, h)
    return np.stack((h, s, v), axis=-1).astype(np.uint8)


_HSV_VECTOR_PIXELS = 32
_HSV_SECTORS = np.array(((1, 3, 0), (1, 0, 2), (3, 0, 1), (0, 2, 1), (0, 1, 3), (2, 1, 0)), dtype=np.intp)


def _hsv_to_rgb_numpy(image: np.ndarray) -> np.ndarray:
    """``COLOR_HSV2RGB`` for 8-bit HSV (H in [0, 180)), OpenCV's float32 steps, exact."""

    source = np.asarray(image, dtype=np.uint8)
    h = source[..., 0].astype(np.float32) * np.float32(6.0 / 180.0)
    s = source[..., 1].astype(np.float32) * np.float32(1.0 / 255.0)
    v = source[..., 2].astype(np.float32) * np.float32(1.0 / 255.0)
    h = np.where(h >= np.float32(6.0), h - np.float32(6.0), h).astype(np.float32)
    sector = np.floor(h).astype(np.intp)
    h = (h - sector.astype(np.float32)).astype(np.float32)
    bad = (sector < 0) | (sector >= 6)
    sector = np.where(bad, 0, sector)
    h = np.where(bad, np.float32(0.0), h).astype(np.float32)
    one = np.float32(1.0)
    tab = np.stack(
        (
            v,
            v * (one - s),
            v * (one - s * h),
            v * (one - s * (one - h)),
        ),
        axis=-1,
    ).astype(np.float32)
    picks = _HSV_SECTORS[sector]  # (..., 3): b, g, r indices
    bgr = np.take_along_axis(tab, picks, axis=-1)
    rgb = (bgr[..., ::-1] * np.float32(255.0)).astype(np.float32)
    # OpenCV 4.13 converts each row in blocks of 32 pixels with vector code that
    # truncates, and the rest of the row with scalar code that rounds (measured
    # with its AVX2 build; a CPU with narrower vectors splits rows differently).
    out = np.trunc(rgb)
    if out.ndim == 3 and out.shape[1] % _HSV_VECTOR_PIXELS:
        tail = out.shape[1] - out.shape[1] % _HSV_VECTOR_PIXELS
        out[:, tail:] = np.rint(rgb[:, tail:])
    return np.clip(out, 0, 255).astype(np.uint8)


# ---- Gaussian blur ----------------------------------------------------------------------------


def gaussian_kernel(size: int, sigma: float) -> np.ndarray:
    """``cv2.getGaussianKernel(size, sigma)`` in float64."""

    n = int(size)
    sigma_x = sigma if sigma > 0 else ((n - 1) * 0.5 - 1) * 0.3 + 0.8
    scale = -0.5 / (sigma_x * sigma_x)
    x = np.arange(n, dtype=np.float64) - (n - 1) * 0.5
    weights = np.exp(scale * x * x)
    return weights / weights.sum()


def _gaussian_size(sigma: float, eight_bit: bool) -> int:
    return int(np.rint(sigma * (3 if eight_bit else 4) * 2 + 1)) | 1


def _convolve_axis(image: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    radius = kernel.size // 2
    pad = [(0, 0)] * image.ndim
    pad[axis] = (radius, radius)
    padded = np.pad(image, pad, mode="reflect")  # OpenCV's BORDER_REFLECT_101
    out = np.zeros_like(image, dtype=np.float32)
    length = image.shape[axis]
    for tap, weight in enumerate(kernel.astype(np.float32)):
        window = padded[tap : tap + length] if axis == 0 else padded[:, tap : tap + length]
        out += weight * window
    return out


def _gaussian_blur_numpy(image: np.ndarray, sigma: float, size: int = 0) -> np.ndarray:
    """``cv2.GaussianBlur(image, (size, size), sigma)``; ``size`` 0 derives it from sigma.

    float32 images: within 1e-3 of OpenCV (summation order). 8-bit images:
    within 1 level, because OpenCV's 8-bit path is fixed point; the callers
    feed an edge detector and a selection feather, where one level is below
    what either can show.
    """

    source = np.asarray(image)
    eight_bit = source.dtype == np.uint8
    n = int(size) if int(size) > 0 else _gaussian_size(float(sigma), eight_bit)
    kernel = gaussian_kernel(n, float(sigma))
    working = source.astype(np.float32)
    if min(working.shape[0], working.shape[1]) > 0:
        working = _convolve_axis(working, kernel, 1)
        working = _convolve_axis(working, kernel, 0)
    if eight_bit:
        return np.clip(np.rint(working), 0, 255).astype(np.uint8)
    return working.astype(source.dtype, copy=False)


# ---- morphology -------------------------------------------------------------------------------


def ellipse_kernel(size: int) -> np.ndarray:
    """``cv2.getStructuringElement(MORPH_ELLIPSE, (size, size))``."""

    width = height = max(1, int(size))
    kernel = np.zeros((height, width), dtype=np.uint8)
    r = height // 2
    c = width // 2
    inv_r2 = 1.0 / (r * r) if r else 0.0
    for row in range(height):
        dy = row - r
        if abs(dy) > r:
            continue
        dx = int(np.rint(c * math.sqrt((r * r - dy * dy) * inv_r2))) if r else 0
        kernel[row, max(c - dx, 0) : min(c + dx + 1, width)] = 1
    return kernel


def _ellipse_morph(mask: np.ndarray, size: int, dilate: bool) -> np.ndarray:
    source = np.asarray(mask, dtype=np.uint8)
    kernel = ellipse_kernel(size)
    radius = kernel.shape[0] // 2
    if radius == 0:
        return source.copy()
    combine = np.maximum if dilate else np.minimum
    border = 0 if dilate else 255
    height, width = source.shape
    padded = np.full((height + 2 * radius, width + 2 * radius), border, dtype=np.uint8)
    padded[radius : radius + height, radius : radius + width] = source
    # Each kernel row is one run, centred: half widths per row offset.
    half_widths = {}
    for row in range(kernel.shape[0]):
        columns = np.flatnonzero(kernel[row])
        if columns.size:
            half_widths[row - radius] = int(columns[-1]) - radius
    result = np.full((height, width), border, dtype=np.uint8)
    # horizontal[:, x] = combine of padded[:, x - d .. x + d], grown one step per d:
    # the window of d is the union of the windows of d - 1 at x - 1 and x + 1.
    horizontal = padded
    current = 0
    for d in sorted(set(half_widths.values())):
        while current < d:
            current += 1
            grown = np.empty_like(padded)
            grown[:, 0] = border
            grown[:, -1] = border
            if current == 1:
                combine(horizontal[:, :-2], horizontal[:, 1:-1], out=grown[:, 1:-1])
                combine(grown[:, 1:-1], horizontal[:, 2:], out=grown[:, 1:-1])
            else:
                combine(horizontal[:, :-2], horizontal[:, 2:], out=grown[:, 1:-1])
            horizontal = grown
        for dy, half in half_widths.items():
            if half == d:
                combine(result, horizontal[radius + dy : radius + dy + height, radius : radius + width], out=result)
    return result


def dilate_ellipse(mask: np.ndarray, size: int) -> np.ndarray:
    """``cv2.dilate(mask, getStructuringElement(MORPH_ELLIPSE, (size, size)))`` for 8-bit masks."""

    return _ellipse_morph(mask, size, True)


def erode_ellipse(mask: np.ndarray, size: int) -> np.ndarray:
    """``cv2.erode(mask, getStructuringElement(MORPH_ELLIPSE, (size, size)))`` for 8-bit masks."""

    return _ellipse_morph(mask, size, False)


# ---- resize ---------------------------------------------------------------------------------


def _nearest_indices(source: int, target: int) -> np.ndarray:
    scale = 1.0 / (target / source)  # as OpenCV forms it; source / target differs in the last bit
    return np.minimum(np.floor(np.arange(target) * scale).astype(np.int64), source - 1)


_RESIZE_COEF_SCALE = 2048  # OpenCV's INTER_RESIZE_COEF_SCALE for 8-bit linear


def _linear_taps(source: int, target: int, area_mode: bool, clamp: bool) -> Tuple[np.ndarray, np.ndarray]:
    """OpenCV's 8-bit linear taps: indices and 11-bit integer weights.

    Positions are float32 as OpenCV computes them. Columns clamp the position
    at the edges; rows do not, they only clamp the row index, so an edge row
    splits its weight over the same source row (``clamp`` False).
    """

    inv_scale = target / source
    scale = 1.0 / inv_scale
    index = np.zeros((target, 2), dtype=np.int64)
    weight = np.zeros((target, 2), dtype=np.int64)
    one = np.float32(1.0)
    for dx in range(target):
        if area_mode:
            sx = math.floor(dx * scale)
            fx = np.float32((dx + 1) - (sx + 1) * inv_scale)
            fx = np.float32(0.0) if fx <= 0 else np.float32(fx - math.floor(fx))
        else:
            fx = np.float32((dx + 0.5) * scale - 0.5)
            sx = math.floor(fx)
            fx = np.float32(fx - sx)
        if clamp:
            if sx < 0:
                fx, sx = np.float32(0.0), 0
            if sx >= source - 1:
                fx, sx = np.float32(0.0), source - 1
        index[dx] = (min(max(sx, 0), source - 1), min(max(sx + 1, 0), source - 1))
        weight[dx] = (
            int(np.rint(np.float32((one - fx) * np.float32(_RESIZE_COEF_SCALE)))),
            int(np.rint(np.float32(fx * np.float32(_RESIZE_COEF_SCALE)))),
        )
    return index, weight


def _resize_linear_8bit(source: np.ndarray, width: int, height: int, area_mode: bool) -> np.ndarray:
    src_h, src_w = source.shape[:2]
    col_index, col_weight = _linear_taps(src_w, width, area_mode, clamp=True)
    row_index, row_weight = _linear_taps(src_h, height, area_mode, clamp=False)
    s = source.astype(np.int64)
    extra = (1,) * (source.ndim - 2)
    c0 = col_weight[:, 0].reshape((1, width) + extra)
    c1 = col_weight[:, 1].reshape((1, width) + extra)
    horizontal = s[:, col_index[:, 0]] * c0 + s[:, col_index[:, 1]] * c1
    b0 = row_weight[:, 0].reshape((height, 1) + extra)
    b1 = row_weight[:, 1].reshape((height, 1) + extra)
    # OpenCV's vector path: 16-bit high multiplies, then a 2-bit rounding shift.
    first = (b0 * (horizontal[row_index[:, 0]] >> 4)) >> 16
    second = (b1 * (horizontal[row_index[:, 1]] >> 4)) >> 16
    return np.clip((first + second + 2) >> 2, 0, 255).astype(np.uint8)


def _cubic_taps(source: int, target: int) -> Tuple[np.ndarray, np.ndarray]:
    scale = source / target
    a = -0.75
    index = np.zeros((target, 4), dtype=np.int64)
    weight = np.zeros((target, 4), dtype=np.float64)
    for dx in range(target):
        fx = (dx + 0.5) * scale - 0.5
        sx = math.floor(fx)
        fx -= sx
        w0 = ((a * (fx + 1) - 5 * a) * (fx + 1) + 8 * a) * (fx + 1) - 4 * a
        w1 = ((a + 2) * fx - (a + 3)) * fx * fx + 1
        w2 = ((a + 2) * (1 - fx) - (a + 3)) * (1 - fx) * (1 - fx) + 1
        w3 = 1.0 - w0 - w1 - w2
        for tap in range(4):
            index[dx, tap] = min(max(sx - 1 + tap, 0), source - 1)
        weight[dx] = (w0, w1, w2, w3)
    return index, weight


def _area_taps(source: int, target: int) -> Tuple[np.ndarray, np.ndarray]:
    scale = source / target
    taps = int(math.ceil(scale)) + 1
    index = np.zeros((target, taps), dtype=np.int64)
    weight = np.zeros((target, taps), dtype=np.float64)
    for dx in range(target):
        fsx1 = dx * scale
        fsx2 = fsx1 + scale
        sx1 = math.ceil(fsx1)
        sx2 = math.floor(fsx2)
        sx2 = min(sx2, source - 1)
        sx1 = min(sx1, sx2)
        cell = min(scale, source - fsx1)
        entries = []
        if sx1 - fsx1 > 1e-3:
            entries.append((sx1 - 1, (sx1 - fsx1) / cell))
        for sx in range(sx1, sx2):
            entries.append((sx, 1.0 / cell))
        if fsx2 - sx2 > 1e-3:
            entries.append((sx2, min(min(fsx2 - sx2, 1.0), cell) / cell))
        for tap, (sx, w) in enumerate(entries[:taps]):
            index[dx, tap] = sx
            weight[dx, tap] = w
    return index, weight


def _apply_taps(image: np.ndarray, index: np.ndarray, weight: np.ndarray, axis: int) -> np.ndarray:
    out = None
    for tap in range(index.shape[1]):
        gathered = np.take(image, index[:, tap], axis=axis)
        shape = [1] * image.ndim
        shape[axis] = index.shape[0]
        term = gathered * weight[:, tap].astype(np.float32).reshape(shape)
        out = term if out is None else out + term
    return out


def _resize_numpy(image: np.ndarray, width: int, height: int, interpolation: str) -> np.ndarray:
    """``cv2.resize(image, (width, height), interpolation=...)`` for 8-bit images.

    ``nearest`` is exact. ``linear``, ``area`` and ``cubic`` follow OpenCV's
    sample positions and weights in floating point; OpenCV's 8-bit paths are
    fixed point, so a pixel may differ by 1 level (2 for cubic, whose
    overshoot is clipped at a slightly different place). Exact integer
    shrink factors with ``area`` (the 4x supersampled selection) are exact.
    """

    source = np.asarray(image, dtype=np.uint8)
    target_w = max(1, int(width))
    target_h = max(1, int(height))
    src_h, src_w = source.shape[:2]
    if interpolation == "nearest":
        rows = _nearest_indices(src_h, target_h)
        cols = _nearest_indices(src_w, target_w)
        return np.ascontiguousarray(source[rows][:, cols])
    if interpolation == "area" and src_w % target_w == 0 and src_h % target_h == 0 and (src_w > target_w or src_h > target_h):
        fx, fy = src_w // target_w, src_h // target_h
        blocks = source.reshape((target_h, fy, target_w, fx) + source.shape[2:]).astype(np.int64)
        total = blocks.sum(axis=(1, 3))
        return np.clip(np.rint(total.astype(np.float32) * np.float32(1.0 / (fx * fy))), 0, 255).astype(np.uint8)
    working = source.astype(np.float32)
    if interpolation == "area" and target_w <= src_w and target_h <= src_h:
        col_taps = _area_taps(src_w, target_w)
        row_taps = _area_taps(src_h, target_h)
    elif interpolation in ("linear", "area"):
        # OpenCV's INTER_AREA turns into linear "area mode" unless both sides shrink.
        return _resize_linear_8bit(source, target_w, target_h, interpolation == "area")
    elif interpolation == "cubic":
        col_taps = _cubic_taps(src_w, target_w)
        row_taps = _cubic_taps(src_h, target_h)
    else:
        raise ValueError(f"Unknown interpolation {interpolation!r}.")
    working = _apply_taps(working, *col_taps, axis=1)
    working = _apply_taps(working, *row_taps, axis=0)
    return np.clip(np.rint(working), 0, 255).astype(np.uint8)



# ---- OpenCV first, numpy without it ------------------------------------------------------------
# 4096 x 4096, best of three, plain timer (P16 stage 2 report): the numpy versions
# above take 12 to 258 times as long as OpenCV, and these run on a whole layer per
# stroke or per composite.

_RESIZE_FLAGS = {"nearest": "INTER_NEAREST", "linear": "INTER_LINEAR", "area": "INTER_AREA", "cubic": "INTER_CUBIC"}


def rgba_to_gray(image: np.ndarray) -> np.ndarray:
    """``cv2.cvtColor(image, COLOR_RGBA2GRAY)`` (RGB input too)."""

    cv2 = _opencv_or_none()
    if cv2 is None:
        return _rgba_to_gray_numpy(image)
    source = np.asarray(image, dtype=np.uint8)
    return cv2.cvtColor(source, cv2.COLOR_RGBA2GRAY if source.shape[-1] == 4 else cv2.COLOR_RGB2GRAY)


def apply_lut(image: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """``cv2.LUT(image, lut)`` with one 256-entry table."""

    cv2 = _opencv_or_none()
    return _apply_lut_numpy(image, lut) if cv2 is None else cv2.LUT(image, lut)


def add_weighted(first: np.ndarray, alpha: float, second: np.ndarray, beta: float, gamma: float) -> np.ndarray:
    """``cv2.addWeighted(first, alpha, second, beta, gamma)``."""

    cv2 = _opencv_or_none()
    if cv2 is None:
        return _add_weighted_numpy(first, alpha, second, beta, gamma)
    return cv2.addWeighted(first, alpha, second, beta, gamma)


def rgb_to_hsv(image: np.ndarray) -> np.ndarray:
    """``cv2.cvtColor(image, COLOR_RGB2HSV)``."""

    cv2 = _opencv_or_none()
    return _rgb_to_hsv_numpy(image) if cv2 is None else cv2.cvtColor(image, cv2.COLOR_RGB2HSV)


def hsv_to_rgb(image: np.ndarray) -> np.ndarray:
    """``cv2.cvtColor(image, COLOR_HSV2RGB)``."""

    cv2 = _opencv_or_none()
    return _hsv_to_rgb_numpy(image) if cv2 is None else cv2.cvtColor(image, cv2.COLOR_HSV2RGB)


def gaussian_blur(image: np.ndarray, sigma: float, size: int = 0) -> np.ndarray:
    """``cv2.GaussianBlur(image, (size, size), sigma)``; ``size`` 0 derives it from sigma."""

    cv2 = _opencv_or_none()
    if cv2 is None:
        return _gaussian_blur_numpy(image, sigma, size)
    n = int(size)
    return cv2.GaussianBlur(image, (n, n) if n > 0 else (0, 0), sigmaX=float(sigma), sigmaY=float(sigma))


def resize(image: np.ndarray, width: int, height: int, interpolation: str) -> np.ndarray:
    """``cv2.resize(image, (width, height), interpolation=...)``: nearest, linear, area or cubic."""

    if interpolation not in _RESIZE_FLAGS:
        raise ValueError(f"Unknown interpolation {interpolation!r}.")
    cv2 = _opencv_or_none()
    if cv2 is None:
        return _resize_numpy(image, width, height, interpolation)
    flag = getattr(cv2, _RESIZE_FLAGS[interpolation])
    return cv2.resize(image, (max(1, int(width)), max(1, int(height))), interpolation=flag)

# ---- still OpenCV -----------------------------------------------------------------------------


def flood_fill_mask_only(rgb: np.ndarray, seed: Tuple[int, int], tolerance: int) -> np.ndarray:
    """The paint bucket's contiguous fill on an RGB image: a (h + 2, w + 2) mask, 255 where filled."""

    cv2 = _cv2()
    source = cv2.cvtColor(np.asarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2BGR).copy()
    mask = np.zeros((source.shape[0] + 2, source.shape[1] + 2), dtype=np.uint8)
    diff = (int(tolerance),) * 3
    cv2.floodFill(source, mask, (int(seed[0]), int(seed[1])), (0, 0, 0), loDiff=diff, upDiff=diff,
                  flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY)
    return mask


def flood_fill_value(mask: np.ndarray, seed: Tuple[int, int], value: int, tolerance: int, connectivity: int) -> np.ndarray:
    """The selection fill: ``cv2.floodFill(mask, None, seed, value, tolerance, tolerance, connectivity)``."""

    working = np.ascontiguousarray(mask, dtype=np.uint8).copy()
    _cv2().floodFill(working, None, (int(seed[0]), int(seed[1])), int(value), loDiff=int(tolerance),
                     upDiff=int(tolerance), flags=int(connectivity))
    return working


def fill_polygon_antialiased(canvas: np.ndarray, polygon: np.ndarray, value: int = 255) -> np.ndarray:
    """``cv2.fillPoly(canvas, [polygon], value, lineType=LINE_AA)``, in place; returns the canvas."""

    cv2 = _cv2()
    cv2.fillPoly(canvas, [np.asarray(polygon, dtype=np.int32).reshape(-1, 1, 2)], int(value), lineType=cv2.LINE_AA)
    return canvas


def find_outer_contours_ccomp(binary: np.ndarray):
    """``cv2.findContours(binary, RETR_CCOMP, CHAIN_APPROX_SIMPLE)``: (contours, hierarchy)."""

    cv2 = _cv2()
    return cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)


def contour_arc_length(contour: np.ndarray, closed: bool) -> float:
    return float(_cv2().arcLength(contour, closed))


def approx_polygon(contour: np.ndarray, epsilon: float, closed: bool) -> np.ndarray:
    return _cv2().approxPolyDP(contour, epsilon, closed=closed)


def canny_edges(gray: np.ndarray, low: float, high: float) -> np.ndarray:
    return _cv2().Canny(gray, low, high)


def bilateral_filter(rgb: np.ndarray, diameter: int, sigma_colour: float, sigma_space: float) -> np.ndarray:
    return _cv2().bilateralFilter(rgb, diameter, sigma_colour, sigma_space)


def median_blur(rgb: np.ndarray, size: int) -> np.ndarray:
    return _cv2().medianBlur(rgb, int(size))


def rotation_matrix(center: Tuple[float, float], angle: float, scale: float) -> np.ndarray:
    """``cv2.getRotationMatrix2D(center, angle, scale)`` (exact)."""

    radians = angle * (math.pi / 180.0)
    alpha = math.cos(radians) * scale
    beta = math.sin(radians) * scale
    cx, cy = float(center[0]), float(center[1])
    return np.array(
        ((alpha, beta, (1.0 - alpha) * cx - beta * cy), (-beta, alpha, beta * cx + (1.0 - alpha) * cy)),
        dtype=np.float64,
    )


def warp_affine_linear(image: np.ndarray, matrix: np.ndarray, width: int, height: int) -> np.ndarray:
    """``cv2.warpAffine(image, matrix, (width, height), INTER_LINEAR, BORDER_CONSTANT, 0)``."""

    cv2 = _cv2()
    return cv2.warpAffine(image, matrix, (int(width), int(height)), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
