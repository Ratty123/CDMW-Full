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
  erode, the rotation matrix, PNG, contour length, polygon simplification);
- written and pinned, but OpenCV first: the numpy version is many times slower
  on a 4096 x 4096 layer, and these run per stroke or per composite, so they
  call OpenCV while it is installed and fall back to numpy without it (gray,
  HSV, the lookup table, addWeighted, Gaussian blur, resize, affine warp,
  both flood fills, Canny, the median and bilateral filters, contours);
- OpenCV only, not written yet (antialiased polygon fill).

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
    "canny_edges",
    "bilateral_filter",
    "median_blur",
    "warp_affine_linear",
)
# Of those, the ones with no numpy version yet: they need OpenCV to run at all.
opencv_only: Tuple[str, ...] = (
    "fill_polygon_antialiased",
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
    """The paint bucket's contiguous fill on an RGB image: a (h + 2, w + 2) mask, 255 where filled.

    ``cv2.floodFill(bgr, mask, seed, 0, tol, tol, 4 | 255 << 8 | FLOODFILL_MASK_ONLY)``;
    the mask's one-pixel frame is 1, as OpenCV leaves it.
    """

    cv2 = _opencv_or_none()
    if cv2 is None:
        return _flood_fill_mask_only_numpy(rgb, seed, tolerance)
    source = cv2.cvtColor(np.asarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2BGR).copy()
    mask = np.zeros((source.shape[0] + 2, source.shape[1] + 2), dtype=np.uint8)
    diff = (int(tolerance),) * 3
    cv2.floodFill(source, mask, (int(seed[0]), int(seed[1])), (0, 0, 0), loDiff=diff, upDiff=diff,
                  flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY)
    return mask


def flood_fill_value(mask: np.ndarray, seed: Tuple[int, int], value: int, tolerance: int, connectivity: int) -> np.ndarray:
    """The selection fill: ``cv2.floodFill(mask, None, seed, value, tolerance, tolerance, connectivity)``."""

    cv2 = _opencv_or_none()
    if cv2 is None:
        return _flood_fill_value_numpy(mask, seed, value, tolerance, connectivity)
    working = np.ascontiguousarray(mask, dtype=np.uint8).copy()
    cv2.floodFill(working, None, (int(seed[0]), int(seed[1])), int(value), loDiff=int(tolerance),
                  upDiff=int(tolerance), flags=int(connectivity))
    return working


def _segment_close(row: np.ndarray, links: np.ndarray) -> np.ndarray:
    """Spread ``row`` along each run of linked pixels (``links[x]`` joins x and x + 1)."""

    starts = np.empty(row.size, dtype=bool)
    starts[0] = True
    starts[1:] = ~links
    segment = np.cumsum(starts) - 1
    hit = np.bincount(segment, weights=row.astype(np.float64), minlength=int(segment[-1]) + 1) > 0
    return hit[segment]


def _reach(seeds: np.ndarray, h_links: np.ndarray, v_links: Optional[np.ndarray],
           enter: Optional[np.ndarray], diagonal: bool,
           d_links: Optional[Tuple[np.ndarray, np.ndarray]] = None) -> np.ndarray:
    """Every pixel reachable from ``seeds``.

    Within a row, pixels x and x + 1 are joined where ``h_links`` says so.
    Between rows either links join neighbours both ways (``v_links[y]`` joins
    (y, x) and (y + 1, x); ``d_links`` = (a, b) with ``a[y, x]`` joining (y, x)
    and (y + 1, x + 1) and ``b[y, x]`` joining (y, x + 1) and (y + 1, x)), or a
    pixel can be entered from a reached pixel in the next row up or down (also
    diagonally when ``diagonal``) where ``enter`` allows it. The rows are swept
    down and up until a sweep reaches nothing new.
    """

    height = seeds.shape[0]
    reached = np.zeros_like(seeds, dtype=bool)
    for y in range(height):
        if seeds[y].any():
            reached[y] = _segment_close(seeds[y], h_links[y])
    changed = True
    while changed:
        changed = False
        for rows, step in ((range(1, height), -1), (range(height - 2, -1, -1), 1)):
            for y in rows:
                source = reached[y + step]
                if not source.any():
                    continue
                if v_links is not None:
                    link_row = min(y, y + step)
                    incoming = source & v_links[link_row]
                    if d_links is not None:
                        a, b = d_links[0][link_row], d_links[1][link_row]
                        incoming = incoming.copy()
                        if step == -1:  # from row y - 1
                            incoming[1:] |= source[:-1] & a  # (y - 1, x - 1) to (y, x)
                            incoming[:-1] |= source[1:] & b  # (y - 1, x + 1) to (y, x)
                        else:  # from row y + 1
                            incoming[1:] |= source[:-1] & b  # (y + 1, x - 1) to (y, x)
                            incoming[:-1] |= source[1:] & a  # (y + 1, x + 1) to (y, x)
                else:
                    if diagonal:
                        source = source.copy()
                        source[1:] |= reached[y + step][:-1]
                        source[:-1] |= reached[y + step][1:]
                    incoming = source & enter[y]
                if (incoming & ~reached[y]).any():
                    reached[y] = _segment_close(reached[y] | incoming, h_links[y])
                    changed = True
    return reached


def _flood_fill_mask_only_numpy(rgb: np.ndarray, seed: Tuple[int, int], tolerance: int) -> np.ndarray:
    """OpenCV's floating-range fill, mask only, 4-connected (exact).

    Without painting, each step compares a pixel with the neighbour it is
    reached from, so the result is the seed's component of the graph whose
    neighbours differ by at most the tolerance in every channel.
    """

    source = np.asarray(rgb, dtype=np.uint8).astype(np.int16)
    tol = int(tolerance)
    height, width = source.shape[:2]
    h_links = np.all(np.abs(source[:, 1:] - source[:, :-1]) <= tol, axis=-1)
    v_links = np.all(np.abs(source[1:] - source[:-1]) <= tol, axis=-1)
    seeds = np.zeros((height, width), dtype=bool)
    seeds[int(seed[1]), int(seed[0])] = True
    reached = _reach(seeds, h_links, v_links, None, False)
    mask = np.ones((height + 2, width + 2), dtype=np.uint8)
    mask[1:-1, 1:-1] = np.where(reached, 255, 0)
    return mask


def _flood_fill_value_numpy(mask: np.ndarray, seed: Tuple[int, int], value: int, tolerance: int,
                            connectivity: int) -> np.ndarray:
    """OpenCV's floating-range fill that paints ``value`` into an 8-bit image (exact).

    Each step compares a pixel with the unpainted neighbour it is reached
    from (OpenCV paints a segment after scanning beside it), so the filled area
    is the seed's component of the graph whose 4- or 8-neighbours differ by at
    most the tolerance; a tolerance of 0 fills the seed's equal-valued area.
    """

    working = np.ascontiguousarray(mask, dtype=np.uint8).copy()
    source = working.astype(np.int16)
    tol = int(tolerance)
    x, y = int(seed[0]), int(seed[1])
    seeds = np.zeros(source.shape, dtype=bool)
    seeds[y, x] = True
    h_links = np.abs(source[:, 1:] - source[:, :-1]) <= tol
    v_links = np.abs(source[1:] - source[:-1]) <= tol
    d_links = None
    if int(connectivity) == 8:
        d_links = (np.abs(source[1:, 1:] - source[:-1, :-1]) <= tol, np.abs(source[1:, :-1] - source[:-1, 1:]) <= tol)
    reached = _reach(seeds, h_links, v_links, None, False, d_links)
    working[reached] = np.uint8(int(value) & 255)
    return working


def fill_polygon_antialiased(canvas: np.ndarray, polygon: np.ndarray, value: int = 255) -> np.ndarray:
    """``cv2.fillPoly(canvas, [polygon], value, lineType=LINE_AA)``, in place; returns the canvas."""

    cv2 = _cv2()
    cv2.fillPoly(canvas, [np.asarray(polygon, dtype=np.int32).reshape(-1, 1, 2)], int(value), lineType=cv2.LINE_AA)
    return canvas


def find_outer_contours_ccomp(binary: np.ndarray):
    """``cv2.findContours(binary, RETR_CCOMP, CHAIN_APPROX_SIMPLE)``: (contours, hierarchy)."""

    cv2 = _opencv_or_none()
    if cv2 is None:
        return _find_contours_ccomp_numpy(binary)
    return cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)


# Chain code directions (x, y): 0 right, then counter-clockwise in image space.
_CHAIN_DELTAS = ((1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1))
_MARK = 2
_MARK_RIGHT = 130  # OpenCV's (schar)(2 | -128), stored unsigned


def _trace_border(image: bytearray, stride: int, start: int, is_hole: bool) -> list:
    """OpenCV's icvFetchContour with CHAIN_APPROX_SIMPLE on a 0/1 image framed by 0.

    Marks the border it follows (2, or 130 where the pixel to its right is 0)
    and returns the flat positions where the chain changes direction, and the
    positions it marked.
    """

    deltas = [1, -stride + 1, -stride, -stride - 1, -1, stride - 1, stride, stride + 1]
    deltas = deltas + deltas
    points = []
    i0 = start
    s_end = s = 0 if is_hole else 4
    while True:
        s = (s - 1) & 7
        i1 = i0 + deltas[s]
        if image[i1] != 0 or s == s_end:
            break
    if s == s_end:
        image[i0] = _MARK_RIGHT
        points.append(i0)
        return points, [i0]
    i3 = i0
    prev_s = s ^ 4
    position = i0
    marked = []
    while True:
        s_end = s
        i4 = i3
        while s < 15:
            s += 1
            i4 = i3 + deltas[s]
            if image[i4] != 0:
                break
        s &= 7
        if ((s - 1) & 0xFFFFFFFF) < s_end:
            image[i3] = _MARK_RIGHT
            marked.append(i3)
        elif image[i3] == 1:
            image[i3] = _MARK
            marked.append(i3)
        if s != prev_s:
            points.append(position)
            prev_s = s
        position += deltas[s]
        if i4 == i0 and i3 == i1:
            break
        i3 = i4
        s = (s + 4) & 7
    return points, marked


def _find_contours_ccomp_numpy(binary: np.ndarray):
    """OpenCV's findContours, RETR_CCOMP and CHAIN_APPROX_SIMPLE, for an 8-bit image (exact).

    Suzuki and Abe's border following as OpenCV implements it, on the image
    framed by one row and column of 0, scanned in raster order. In the
    two-level hierarchy a hole's parent is the outer border of the 8-connected
    component it is cut out of. That component is found from the leftmost pixel
    of the run the hole starts in: it lies on a border already followed, and
    the contour that marked it belongs to the same component. Siblings come
    newest first, each outer border followed by its holes, as OpenCV lists them.
    """

    source = np.asarray(binary)
    height, width = source.shape[:2]
    padded = np.zeros((height + 2, width + 2), dtype=np.uint8)
    padded[1:-1, 1:-1] = source != 0
    stride = width + 2
    image = bytearray(padded.tobytes())
    foreground = padded.astype(bool)
    owner = np.full(padded.size, -1, dtype=np.int64)  # outer contour (component) that marked a pixel
    # Columns where a row changes between 0 and not 0: the only places a border can start.
    changes = np.flatnonzero((foreground[:, 1:] != foreground[:, :-1]).reshape(-1))
    outers: list = []
    holes: list = []  # (points, parent outer index)
    run_start = -1
    for flat in changes:
        y, x0 = divmod(int(flat), stride - 1)
        x = x0 + 1
        position = y * stride + x
        if image[position] != 0 and image[position - 1] == 0:
            run_start = position
        if x >= stride - 1:  # OpenCV scans columns 1 .. width - 2 of the framed image
            continue
        prev, current = image[position - 1], image[position]
        if prev == 0 and current == 1:
            points, marked = _trace_border(image, stride, position, False)
            owner[marked] = len(outers)
            outers.append(points)
        elif current == 0 and prev in (1, _MARK):
            parent = int(owner[run_start])
            points, marked = _trace_border(image, stride, position - 1, True)
            owner[marked] = parent
            holes.append((points, parent))
    if not outers:
        return (), None
    children: dict = {}
    for hole_index in range(len(holes) - 1, -1, -1):
        children.setdefault(holes[hole_index][1], []).append(hole_index)
    order = []
    for index in range(len(outers) - 1, -1, -1):
        order.append((outers[index], -1))
        order.extend((holes[h][0], index) for h in children.get(index, ()))
    position_of_outer = {}
    cursor = 0
    for index in range(len(outers) - 1, -1, -1):
        position_of_outer[index] = cursor
        cursor += 1 + len(children.get(index, ()))
    hierarchy = np.full((len(order), 4), -1, dtype=np.int32)
    top = [position_of_outer[index] for index in range(len(outers) - 1, -1, -1)]
    for rank, at in enumerate(top):
        hierarchy[at, 0] = top[rank + 1] if rank + 1 < len(top) else -1
        hierarchy[at, 1] = top[rank - 1] if rank > 0 else -1
    for index, at in position_of_outer.items():
        kids = list(range(at + 1, at + 1 + len(children.get(index, ()))))
        if kids:
            hierarchy[at, 2] = kids[0]
        for rank, kid in enumerate(kids):
            hierarchy[kid, 0] = kids[rank + 1] if rank + 1 < len(kids) else -1
            hierarchy[kid, 1] = kids[rank - 1] if rank > 0 else -1
            hierarchy[kid, 3] = at
    contours = tuple(
        np.array([(q % stride - 1, q // stride - 1) for q in points], dtype=np.int32).reshape(-1, 1, 2)
        for points, _parent in order
    )
    return contours, hierarchy.reshape(1, -1, 4)


def contour_arc_length(contour: np.ndarray, closed: bool) -> float:
    """``cv2.arcLength(contour, closed)`` (exact).

    OpenCV takes float32 square roots of float32 squared steps, sums each block
    of 16 backwards, and adds the blocks in double; this does the same.
    """

    points = np.asarray(contour).reshape(-1, 2).astype(np.float32)
    count = points.shape[0]
    if count <= 1:
        return 0.0
    previous = np.concatenate((points[-1:] if closed else points[:1], points[:-1]), axis=0)
    step = (points - previous).astype(np.float32)
    lengths = np.sqrt((step[:, 0] * step[:, 0] + step[:, 1] * step[:, 1]).astype(np.float32)).astype(np.float32)
    perimeter = 0.0
    for start in range(0, count, 16):
        for value in lengths[start : start + 16][::-1]:
            perimeter += float(value)
    return perimeter


def approx_polygon(contour: np.ndarray, epsilon: float, closed: bool) -> np.ndarray:
    """``cv2.approxPolyDP(contour, epsilon, closed)``: OpenCV's Douglas-Peucker, step for step.

    Integer contours (from findContours) and float32 paths (the lasso) keep
    their type; the result has OpenCV's (n, 1, 2) shape.
    """

    source = np.asarray(contour)
    is_float = source.dtype == np.float32
    if not is_float and source.dtype != np.int32:
        raise ValueError("approx_polygon takes int32 or float32 points, as OpenCV does.")
    points = source.reshape(-1, 2)
    count = points.shape[0]
    if count == 0:
        return points.reshape(0, 1, 2).copy()
    if is_float:
        xs = [np.float32(value) for value in points[:, 0]]
        ys = [np.float32(value) for value in points[:, 1]]

        def sub(a, b):
            return float(np.float32(a - b))

        def sq(ax, ay, bx, by):
            # float * float + float * float stays float32 in OpenCV's C++.
            return float(np.float32(np.float32(ax - bx) * np.float32(ax - bx) + np.float32(ay - by) * np.float32(ay - by)))

        def dot(ax, ay, bx, by, cx, cy):
            return float(np.float32(np.float32(ax - bx) * np.float32(cx - ax) + np.float32(ay - by) * np.float32(cy - ay)))
    else:
        xs = [int(value) for value in points[:, 0]]
        ys = [int(value) for value in points[:, 1]]

        def sub(a, b):
            return float(a - b)

        def sq(ax, ay, bx, by):
            return float((ax - bx) * (ax - bx) + (ay - by) * (ay - by))

        def dot(ax, ay, bx, by, cx, cy):
            return float((ax - bx) * (cx - ax) + (ay - by) * (cy - ay))

    eps = float(epsilon) * float(epsilon)
    stack: list[tuple[int, int]] = []
    out: list[int] = []
    init_iters = 3
    slice_start = slice_end = 0
    right_start = right_end = 0
    is_closed = bool(closed)
    if not is_closed:
        right_start = count
        if xs[count - 1] != xs[0] or ys[count - 1] != ys[0]:
            stack.append((0, count - 1))
        else:
            is_closed = True
            init_iters = 1
    start_index = 0
    if is_closed:
        right_start = 0
        pos = 0
        le_eps = False
        for _ in range(init_iters):
            pos = (pos + right_start) % count
            start_index = pos
            pos = (pos + 1) % count
            max_dist = 0.0
            for j in range(1, count):
                index = pos
                pos = (pos + 1) % count
                dx = sub(xs[index], xs[start_index])
                dy = sub(ys[index], ys[start_index])
                dist = dx * dx + dy * dy
                if dist > max_dist:
                    max_dist = dist
                    right_start = j
            le_eps = max_dist <= eps
        if not le_eps:
            right_end = slice_start = pos % count
            slice_end = right_start = (right_start + slice_start) % count
            stack.append((right_start, right_end))
            stack.append((slice_start, slice_end))
        else:
            out.append(start_index)
    while stack:
        slice_start, slice_end = stack.pop()
        end_index = slice_end
        pos = slice_start
        start_index = pos
        pos = (pos + 1) % count
        if pos != slice_end:
            dx = sub(xs[end_index], xs[start_index])
            dy = sub(ys[end_index], ys[start_index])
            segment_len_2 = dx * dx + dy * dy
            max_dist = 0.0  # squared distance to the segment, times segment_len_2
            while pos != slice_end:
                index = pos
                pos = (pos + 1) % count
                px = sub(xs[index], xs[start_index])
                py = sub(ys[index], ys[start_index])
                projection = px * dx + py * dy
                if projection < 0:
                    dist = sq(xs[index], ys[index], xs[start_index], ys[start_index]) * segment_len_2
                elif projection > segment_len_2:
                    dist = sq(xs[index], ys[index], xs[end_index], ys[end_index]) * segment_len_2
                else:
                    cross = py * dx - px * dy
                    dist = cross * cross
                if dist > max_dist:
                    max_dist = dist
                    right_start = (pos + count - 1) % count
            le_eps = max_dist <= eps * segment_len_2
        else:
            le_eps = True
            start_index = slice_start
        if le_eps:
            out.append(start_index)
        else:
            stack.append((right_start, slice_end))
            stack.append((slice_start, right_start))
    if not is_closed:
        out.append(count - 1)

    # Final clean-up: drop points on nearly straight runs, as OpenCV does.
    dst = [(xs[index], ys[index]) for index in out]
    is_closed = bool(closed)
    total = new_count = len(dst)
    pos = total - 1 if is_closed else 0

    def read(position):
        point = dst[position]
        position += 1
        return point, (0 if position >= total else position)

    start, pos = read(pos)
    write = pos
    point, pos = read(pos)
    i = 0 if is_closed else 1
    limit = total - (0 if is_closed else 1)
    while i < limit and new_count > 2:
        end, pos = read(pos)
        dx = sub(end[0], start[0])
        dy = sub(end[1], start[1])
        dist = abs(sub(point[0], start[0]) * dy - sub(point[1], start[1]) * dx)
        inner = dot(point[0], point[1], start[0], start[1], end[0], end[1])
        if dist * dist <= 0.5 * eps * (dx * dx + dy * dy) and dx != 0 and dy != 0 and inner >= 0:
            new_count -= 1
            dst[write] = start = end
            write = write + 1 if write + 1 < total else 0
            point, pos = read(pos)
            i += 2
            continue
        dst[write] = start = point
        write = write + 1 if write + 1 < total else 0
        point = end
        i += 1
    if not is_closed:
        dst[write] = point
    result = np.array(dst[:new_count], dtype=np.float32 if is_float else np.int32).reshape(-1, 1, 2)
    return result


def canny_edges(gray: np.ndarray, low: float, high: float) -> np.ndarray:
    """``cv2.Canny(gray, low, high)``: aperture 3, L1 gradient."""

    cv2 = _opencv_or_none()
    return _canny_numpy(gray, low, high) if cv2 is None else cv2.Canny(gray, low, high)


_CANNY_TG22 = 13573  # tan(22.5 degrees) in OpenCV's 15-bit fixed point


def _canny_numpy(gray: np.ndarray, low: float, high: float) -> np.ndarray:
    """OpenCV 4.13's Canny on an 8-bit image (exact).

    Sobel 3 x 3 with a replicated border, |dx| + |dy|, OpenCV's fixed-point
    direction test for non-maximum suppression, then hysteresis: weak edge
    pixels 8-connected to a strong one are kept.
    """

    low, high = sorted((float(low), float(high)))
    low_i, high_i = math.floor(low), math.floor(high)
    source = np.asarray(gray, dtype=np.uint8).astype(np.int32)
    padded = np.pad(source, 1, mode="edge")
    dx = (padded[:-2, 2:] + 2 * padded[1:-1, 2:] + padded[2:, 2:]) - (padded[:-2, :-2] + 2 * padded[1:-1, :-2] + padded[2:, :-2])
    dy = (padded[2:, :-2] + 2 * padded[2:, 1:-1] + padded[2:, 2:]) - (padded[:-2, :-2] + 2 * padded[:-2, 1:-1] + padded[:-2, 2:])
    magnitude = np.abs(dx) + np.abs(dy)
    height, width = magnitude.shape
    m = np.zeros((height + 2, width + 2), dtype=np.int64)
    m[1:-1, 1:-1] = magnitude
    centre = m[1:-1, 1:-1]
    left, right = m[1:-1, :-2], m[1:-1, 2:]
    up, down = m[:-2, 1:-1], m[2:, 1:-1]
    up_left, up_right = m[:-2, :-2], m[:-2, 2:]
    down_left, down_right = m[2:, :-2], m[2:, 2:]
    ax = np.abs(dx).astype(np.int64)
    ay = np.abs(dy).astype(np.int64) << 15
    tg22x = ax * _CANNY_TG22
    tg67x = tg22x + (ax << 16)
    horizontal = ay < tg22x
    vertical = ~horizontal & (ay > tg67x)
    diagonal = ~horizontal & ~vertical
    negative = (dx ^ dy) < 0  # s = -1: compare up-right and down-left
    peak = np.where(
        horizontal,
        (centre > left) & (centre >= right),
        np.where(
            vertical,
            (centre > up) & (centre >= down),
            np.where(negative, (centre > up_right) & (centre > down_left), (centre > up_left) & (centre > down_right)),
        ),
    )
    candidate = (centre > low_i) & peak
    strong = candidate & (centre > high_i)
    edges = _reach(strong, candidate[:, 1:] & candidate[:, :-1], None, candidate, True)
    return np.where(edges, 255, 0).astype(np.uint8)


def bilateral_filter(rgb: np.ndarray, diameter: int, sigma_colour: float, sigma_space: float) -> np.ndarray:
    """``cv2.bilateralFilter(rgb, diameter, sigma_colour, sigma_space)`` for 8-bit images."""

    cv2 = _opencv_or_none()
    if cv2 is None:
        return _bilateral_filter_numpy(rgb, diameter, sigma_colour, sigma_space)
    return cv2.bilateralFilter(rgb, diameter, sigma_colour, sigma_space)


def median_blur(rgb: np.ndarray, size: int) -> np.ndarray:
    """``cv2.medianBlur(rgb, size)`` for 8-bit images."""

    cv2 = _opencv_or_none()
    return _median_blur_numpy(rgb, size) if cv2 is None else cv2.medianBlur(rgb, int(size))


_MEDIAN_CHUNK_BYTES = 64 << 20


def _median_blur_numpy(image: np.ndarray, size: int) -> np.ndarray:
    """The exact median of each size x size window, border replicated, as OpenCV."""

    source = np.asarray(image, dtype=np.uint8)
    k = int(size)
    if k < 3 or k % 2 == 0:
        raise ValueError("The median filter size must be odd and at least 3.")
    radius = k // 2
    planar = source.ndim == 2
    work = source[..., None] if planar else source
    height, width, channels = work.shape
    padded = np.pad(work, ((radius, radius), (radius, radius), (0, 0)), mode="edge")
    out = np.empty_like(work)
    rows = max(1, _MEDIAN_CHUNK_BYTES // max(1, width * channels * k * k))
    middle = (k * k) // 2
    for top in range(0, height, rows):
        bottom = min(height, top + rows)
        block = padded[top : bottom + 2 * radius]
        windows = np.lib.stride_tricks.sliding_window_view(block, (k, k), axis=(0, 1))
        flat = windows.reshape(windows.shape[:3] + (k * k,))
        out[top:bottom] = np.partition(flat, middle, axis=-1)[..., middle]
    return out[..., 0] if planar else out


def _bilateral_filter_numpy(image: np.ndarray, diameter: int, sigma_colour: float, sigma_space: float) -> np.ndarray:
    """OpenCV 4.13's 8-bit bilateral filter.

    The same float32 colour and space weight tables over a circular window, a
    reflect-101 border, float32 sums taken offset by offset, and the rounded
    ratio at the end. For three channels (the brush's only use) it matches
    OpenCV except about one value in 100,000, by 1 level (OpenCV's vector
    sums). For one channel with a diameter of 3 or 5 OpenCV takes another
    routine and about 4 % of values are 1 level higher here.
    """

    source = np.asarray(image, dtype=np.uint8)
    planar = source.ndim == 2
    work = source[..., None] if planar else source
    channels = work.shape[2]
    sigma_colour = float(sigma_colour) if sigma_colour > 0 else 1.0
    sigma_space = float(sigma_space) if sigma_space > 0 else 1.0
    colour_coeff = -0.5 / (sigma_colour * sigma_colour)
    space_coeff = -0.5 / (sigma_space * sigma_space)
    radius = int(np.rint(sigma_space * 1.5)) if int(diameter) <= 0 else int(diameter) // 2
    radius = max(radius, 1)
    index = np.arange(256 * channels, dtype=np.float64)
    colour_weight = np.exp(index * index * colour_coeff).astype(np.float32)
    padded = np.pad(work, ((radius, radius), (radius, radius), (0, 0)), mode="reflect").astype(np.int32)
    height, width = work.shape[:2]
    centre = work.astype(np.int32)
    weight_sum = np.zeros((height, width), dtype=np.float32)
    sums = np.zeros((height, width, channels), dtype=np.float32)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            r = math.sqrt(float(dy * dy) + float(dx * dx))
            if r > radius:
                continue
            space_weight = np.float32(math.exp(r * r * space_coeff))
            shifted = padded[radius + dy : radius + dy + height, radius + dx : radius + dx + width]
            distance = np.abs(shifted - centre).sum(axis=-1)
            w = (space_weight * colour_weight[distance]).astype(np.float32)
            weight_sum += w
            sums += (shifted.astype(np.float32) * w[..., None]).astype(np.float32)
    result = np.rint(sums * (np.float32(1.0) / weight_sum)[..., None])
    out = np.clip(result, 0, 255).astype(np.uint8)
    return out[..., 0] if planar else out


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

    cv2 = _opencv_or_none()
    if cv2 is None:
        return _warp_affine_linear_numpy(image, matrix, width, height)
    return cv2.warpAffine(image, matrix, (int(width), int(height)), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


_AB_BITS = 10
_INTER_BITS = 5
_INTER_TAB = 1 << _INTER_BITS


def _warp_affine_linear_numpy(image: np.ndarray, matrix: np.ndarray, width: int, height: int) -> np.ndarray:
    """OpenCV 4.13's 8-bit warpAffine, linear, constant 0 border (exact).

    The matrix is inverted as ``invertAffineTransform`` does; source positions
    are stepped in 10-bit fixed point, cut to 1/32 pixel, and blended with
    OpenCV's 15-bit weights. Taps outside the source read 0.
    """

    source = np.asarray(image, dtype=np.uint8)
    out_w, out_h = max(1, int(width)), max(1, int(height))
    m = np.asarray(matrix, dtype=np.float64).reshape(-1)
    det = m[0] * m[4] - m[1] * m[3]
    det = 1.0 / det if det != 0 else 0.0
    a11, a22 = m[4] * det, m[0] * det
    a12, a21 = -m[1] * det, -m[3] * det
    b1 = -a11 * m[2] - a12 * m[5]
    b2 = -a21 * m[2] - a22 * m[5]
    scale = float(1 << _AB_BITS)
    round_delta = (1 << _AB_BITS) // _INTER_TAB // 2
    xs = np.arange(out_w, dtype=np.float64)
    ys = np.arange(out_h, dtype=np.float64)
    adelta = np.rint(a11 * xs * scale).astype(np.int64)
    bdelta = np.rint(a21 * xs * scale).astype(np.int64)
    x0 = np.rint((a12 * ys + b1) * scale).astype(np.int64) + round_delta
    y0 = np.rint((a22 * ys + b2) * scale).astype(np.int64) + round_delta
    shift = _AB_BITS - _INTER_BITS
    fixed_x = (x0[:, None] + adelta[None, :]) >> shift
    fixed_y = (y0[:, None] + bdelta[None, :]) >> shift
    sx = fixed_x >> _INTER_BITS
    sy = fixed_y >> _INTER_BITS
    fx = fixed_x & (_INTER_TAB - 1)
    fy = fixed_y & (_INTER_TAB - 1)
    src_h, src_w = source.shape[:2]
    channels = source.shape[2:]
    total = np.zeros((out_h, out_w) + channels, dtype=np.int64)
    taps = (
        (0, 0, (_INTER_TAB - fy) * (_INTER_TAB - fx)),
        (0, 1, (_INTER_TAB - fy) * fx),
        (1, 0, fy * (_INTER_TAB - fx)),
        (1, 1, fy * fx),
    )
    weight_scale = (1 << 15) // (_INTER_TAB * _INTER_TAB)  # OpenCV's table is these products times 32
    for dy, dx, weight in taps:
        tx = sx + dx
        ty = sy + dy
        inside = (tx >= 0) & (tx < src_w) & (ty >= 0) & (ty < src_h)
        values = source[np.clip(ty, 0, src_h - 1), np.clip(tx, 0, src_w - 1)].astype(np.int64)
        w = np.where(inside, weight * weight_scale, 0)
        total += values * (w[..., None] if channels else w)
    return np.clip((total + (1 << 14)) >> 15, 0, 255).astype(np.uint8)
