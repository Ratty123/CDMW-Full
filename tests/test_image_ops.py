"""cdmw.core.image_ops against what OpenCV 4.13 returned for the Texture Editor's calls.

``tests/fixtures/image_ops/cv2_reference.npz`` holds OpenCV's outputs, made by
``tests/fixtures/image_ops/make_cv2_reference.py`` from the inputs in
``tests/helpers/image_ops_inputs.py``. These pins keep working once OpenCV is
gone. Where OpenCV is still installed, the live tests below also compare on
random sizes.

Tolerances, where a function is not exact, and why each is invisible:
- Gaussian blur of float32 images: 1e-3 (summation order). The brush rounds
  the blurred value to 8 bits afterwards.
- Gaussian blur of 8-bit images: 1 level (OpenCV's 8-bit path is fixed point).
  It feeds the selection feather and the edge snap.
- addWeighted: 1e-4 (float32 against double intermediate).
- cubic resize: 1 level on under 1 % of values (OpenCV's fixed point), used
  when a floating selection is scaled up.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import numpy as np
import pytest

from cdmw.core import image_ops
from tests.helpers import image_ops_inputs as inputs

REFERENCE = np.load(Path(__file__).parent / "fixtures" / "image_ops" / "cv2_reference.npz")
SHIPPED = (Path("cdmw_app.py"), Path("cdmw"), Path("tools/placement_studio"), Path("tools/translation_studio"))


def _digest(array: np.ndarray) -> np.ndarray:
    data = np.ascontiguousarray(array)
    text = f"{data.dtype.str}{data.shape}".encode() + data.tobytes()
    return np.frombuffer(hashlib.sha256(text).digest(), dtype=np.uint8)


def _exact(name: str, actual: np.ndarray) -> None:
    expected = REFERENCE[name]
    assert actual.shape == expected.shape, name
    assert actual.dtype == expected.dtype, name
    assert np.array_equal(actual, expected), (name, int(np.count_nonzero(actual != expected)))


def _within(name: str, actual: np.ndarray, tolerance: float) -> None:
    expected = REFERENCE[name]
    assert actual.shape == expected.shape, name
    worst = float(np.max(np.abs(actual.astype(np.float64) - expected.astype(np.float64)))) if actual.size else 0.0
    assert worst <= tolerance, (name, worst)


RGBA = inputs.rgba_image()
RGB = np.ascontiguousarray(RGBA[..., :3])
GRAY = inputs.gray_image()
RGB_F = inputs.float_rgb()
MASKS = {"binary": inputs.binary_mask(), "soft": inputs.soft_mask()}


@pytest.fixture(params=("numpy", "opencv"))
def backend(request, monkeypatch):
    """Run an OpenCV-first function on its numpy version, and on OpenCV when installed."""

    if request.param == "numpy":
        monkeypatch.setattr(image_ops, "_opencv_or_none", lambda: None)
    elif not image_ops.opencv_available():
        pytest.skip("OpenCV is not installed")
    return request.param


def test_reference_was_made_by_the_opencv_the_release_shipped():
    assert str(REFERENCE["opencv_version"]) == "4.13.0"


# ---- exact -------------------------------------------------------------------------------


@pytest.mark.parametrize("pad", (1, 4))
def test_pad_constant(pad):
    _exact(f"pad_{pad}", image_ops.pad_constant(RGBA, pad, (0, 0, 0, 0)))


def test_channel_swaps():
    _exact("rgb2bgr", image_ops.swap_red_blue(RGB))
    _exact("rgba2bgra", image_ops.swap_red_blue(RGBA))
    _exact("bgra2rgba", image_ops.swap_red_blue(RGBA))


def test_gray_for_every_colour(backend):
    _exact("rgba2gray", image_ops.rgba_to_gray(RGBA))
    every = inputs.all_rgb_colours()
    assert np.array_equal(_digest(image_ops.rgba_to_gray(every)), REFERENCE["rgba2gray_all_digest"])


def test_hsv_both_ways_for_every_8_bit_value(backend):
    _exact("rgb2hsv", image_ops.rgb_to_hsv(RGB))
    _exact("hsv2rgb", image_ops.hsv_to_rgb(REFERENCE["rgb2hsv"]))
    assert np.array_equal(_digest(image_ops.rgb_to_hsv(inputs.all_rgb_colours())), REFERENCE["rgb2hsv_all_digest"])
    assert np.array_equal(_digest(image_ops.hsv_to_rgb(inputs.all_hsv_colours())), REFERENCE["hsv2rgb_all_digest"])


def test_lookup_table(backend):
    _exact("lut", image_ops.apply_lut(RGB, REFERENCE["lut_table"]))


def test_png_blobs_written_by_opencv_decode_to_the_same_pixels():
    # History snapshots and saved selections written before the switch.
    assert np.array_equal(image_ops.decode_png_rgba(bytes(REFERENCE["png_rgba_blob"])), RGBA)
    assert np.array_equal(image_ops.decode_png_mask(bytes(REFERENCE["png_mask_blob"])), MASKS["soft"])
    # A three-channel file: OpenCV's [..., -1] of BGR was red.
    assert np.array_equal(image_ops.decode_png_mask(bytes(REFERENCE["png_bgr_blob"])), RGB[..., 2])
    rgba_from_bgr = image_ops.decode_png_rgba(bytes(REFERENCE["png_bgr_blob"]))
    assert np.array_equal(rgba_from_bgr[..., :3], RGB[..., ::-1]) and np.all(rgba_from_bgr[..., 3] == 255)


def test_png_round_trip_and_unreadable_blobs():
    assert np.array_equal(image_ops.decode_png_rgba(image_ops.encode_png(RGBA)), RGBA)
    assert np.array_equal(image_ops.decode_png_mask(image_ops.encode_png(MASKS["soft"])), MASKS["soft"])
    gray_rgba = image_ops.decode_png_rgba(image_ops.encode_png(GRAY))
    assert np.array_equal(gray_rgba[..., 0], GRAY) and np.all(gray_rgba[..., 3] == 255)
    assert image_ops.decode_png_rgba(b"") is None
    assert image_ops.decode_png_rgba(b"not a png") is None
    assert image_ops.decode_png_mask(b"\x89PNG broken") is None


@pytest.mark.parametrize("size", range(1, 62, 2))
def test_ellipse_kernel(size):
    _exact(f"ellipse_{size}", image_ops.ellipse_kernel(size))


@pytest.mark.parametrize("name", sorted(MASKS))
@pytest.mark.parametrize("size", (3, 7, 21))
def test_dilate_and_erode(name, size):
    _exact(f"dilate_{name}_{size}", image_ops.dilate_ellipse(MASKS[name], size))
    _exact(f"erode_{name}_{size}", image_ops.erode_ellipse(MASKS[name], size))


@pytest.mark.parametrize("angle", (0.5, 17.0, 45.0, 90.0, -133.25))
def test_rotation_matrix(angle):
    height, width = RGBA.shape[:2]
    _exact(f"rotation_matrix_{angle}", image_ops.rotation_matrix((width / 2.0, height / 2.0), angle, 1.0))


SIZES = ((53, 37), (20, 15), (106, 74), (71, 50), (13, 61), (1, 1))


@pytest.mark.parametrize(("width", "height"), SIZES)
def test_resize_nearest_linear_area_exact_cubic_within_one(backend, width, height):
    _exact(f"resize_nearest_{width}x{height}", image_ops.resize(RGBA, width, height, "nearest"))
    _exact(f"resize_linear_{width}x{height}", image_ops.resize(RGBA, width, height, "linear"))
    _exact(f"resize_area_{width}x{height}", image_ops.resize(RGBA, width, height, "area"))
    _within(f"resize_cubic_{width}x{height}", image_ops.resize(RGBA, width, height, "cubic"), 1)


def test_area_resize_of_the_4x_supersampled_selection(backend):
    mask = MASKS["binary"]
    supersampled = image_ops.resize(mask, mask.shape[1] * 4, mask.shape[0] * 4, "nearest")
    _exact("resize_area_quarter", image_ops.resize(supersampled, mask.shape[1], mask.shape[0], "area"))


# ---- within a tolerance ------------------------------------------------------------------


@pytest.mark.parametrize("sigma", (0.8, 1.3, 2.9, 6.4))
def test_gaussian_blur_float32(backend, sigma):
    _within(f"gauss_f32_{sigma}", image_ops.gaussian_blur(RGB_F, sigma), 1e-3)


def test_gaussian_blur_8_bit(backend):
    _within("gauss_gray_1.2", image_ops.gaussian_blur(GRAY, 1.2), 1)
    for feather in (1, 3, 8):
        size = max(3, feather * 2 + 1)
        _within(f"gauss_mask_{feather}", image_ops.gaussian_blur(MASKS["soft"], max(0.8, feather / 2.0), size), 1)


@pytest.mark.parametrize("amount", (0.05, 0.47))
def test_add_weighted(backend, amount):
    blurred = REFERENCE["gauss_f32_1.3"]
    _within(f"add_weighted_{amount}", image_ops.add_weighted(RGB_F, 1.0 + amount, blurred, -amount, 0.0), 1e-4)


# ---- written since, or still OpenCV only: one pin per function -----------------------------


def _only_on_opencv(backend: str, name: str) -> None:
    if backend == "numpy" and name in image_ops.opencv_only:
        pytest.skip(f"{name} has no numpy version yet")


def test_flood_fills(backend):
    _only_on_opencv(backend, "flood_fill_mask_only")
    for tolerance in (0, 24, 90):
        for index, seed in enumerate(((5, 5), (40, 20), (0, 36))):
            _exact(f"flood_bucket_{tolerance}_{index}", image_ops.flood_fill_mask_only(RGB, seed, tolerance))
            for connectivity in (4, 8):
                _exact(f"flood_select_{tolerance}_{index}_{connectivity}",
                       image_ops.flood_fill_value(MASKS["soft"], seed, 255, tolerance, connectivity))


def test_fill_polygon_antialiased(backend):
    _only_on_opencv(backend, "fill_polygon_antialiased")
    for index, polygon in enumerate(inputs.polygons()):
        canvas = np.zeros((160, 200), np.uint8)
        _exact(f"fillpoly_aa_{index}", image_ops.fill_polygon_antialiased(canvas, polygon))


def test_find_contours(backend):
    _only_on_opencv(backend, "find_outer_contours_ccomp")
    for name, mask in MASKS.items():
        contours, hierarchy = image_ops.find_outer_contours_ccomp(np.asarray(mask > 0, dtype=np.uint8))
        assert len(contours) == int(REFERENCE[f"contours_{name}_count"])
        _exact(f"contours_{name}_hierarchy", np.asarray(hierarchy).reshape(-1, 4))
        for index, contour in enumerate(contours):
            _exact(f"contours_{name}_{index}", contour.reshape(-1, 2))


def test_contour_length_and_simplification():
    # Inputs are OpenCV's own contours, kept in the reference file.
    for name in MASKS:
        for index in range(int(REFERENCE[f"contours_{name}_count"])):
            contour = REFERENCE[f"contours_{name}_{index}"].reshape(-1, 1, 2)
            length = image_ops.contour_arc_length(contour, True)
            assert length == float(REFERENCE[f"arclength_{name}_{index}"])
            _exact(f"approx_closed_{name}_{index}",
                   image_ops.approx_polygon(contour, max(0.35, length * 0.002), True).reshape(-1, 2))
    for index, path in enumerate(inputs.lasso_paths()):
        assert np.array_equal(REFERENCE[f"lasso_{index}"], path)
        _exact(f"approx_open_{index}", image_ops.approx_polygon(path.reshape(-1, 1, 2), 0.35, False).reshape(-1, 2))


def test_canny(backend):
    _only_on_opencv(backend, "canny_edges")
    for low, high in ((10, 23), (44, 98), (94, 210)):
        _exact(f"canny_{low}_{high}", image_ops.canny_edges(REFERENCE["gauss_gray_1.2"], low, high))


def test_median_and_bilateral(backend):
    _only_on_opencv(backend, "median_blur")
    for size in (3, 5, 9):
        _exact(f"median_{size}", image_ops.median_blur(RGB, size))
    _only_on_opencv(backend, "bilateral_filter")
    for diameter, colour, space in ((3, 12.0, 6.0), (7, 30.0, 16.0), (15, 48.0, 26.0)):
        _exact(f"bilateral_{diameter}", image_ops.bilateral_filter(RGB, diameter, colour, space))


def test_warp_affine(backend):
    _only_on_opencv(backend, "warp_affine_linear")
    for angle in (0.5, 17.0, 45.0, 90.0, -133.25):
        height, width = RGBA.shape[:2]
        center = (width / 2.0, height / 2.0)
        matrix = image_ops.rotation_matrix(center, angle, 1.0)
        cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
        bound_w = max(1, int((height * sin) + (width * cos)))
        bound_h = max(1, int((height * cos) + (width * sin)))
        matrix[0, 2] += (bound_w / 2.0) - center[0]
        matrix[1, 2] += (bound_h / 2.0) - center[1]
        _exact(f"warp_{angle}", image_ops.warp_affine_linear(RGBA, matrix, bound_w, bound_h))


# ---- live, against OpenCV while it is installed ------------------------------------------


def test_resize_matches_opencv_on_random_sizes():
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(3)
    flags = {"nearest": cv2.INTER_NEAREST, "linear": cv2.INTER_LINEAR, "area": cv2.INTER_AREA, "cubic": cv2.INTER_CUBIC}
    for trial in range(60):
        height, width = (int(value) for value in rng.integers(1, 70, 2))
        channels = (None, 3, 4)[trial % 3]
        image = rng.integers(0, 256, (height, width) if channels is None else (height, width, channels)).astype(np.uint8)
        target_h, target_w = (int(value) for value in rng.integers(1, 140, 2))
        for name, flag in flags.items():
            expected = cv2.resize(image, (target_w, target_h), interpolation=flag)
            actual = image_ops._resize_numpy(image, target_w, target_h, name)
            difference = np.abs(expected.astype(np.int16) - actual.astype(np.int16))
            assert int(difference.max()) <= (1 if name == "cubic" else 0), (name, image.shape, target_w, target_h)


def test_colour_conversions_match_opencv_on_random_widths():
    # OpenCV rounds the scalar tail of each row differently from its vector blocks.
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(12)
    for width in (1, 2, 5, 16, 31, 32, 33, 47, 64, 70, 97, 130):
        rgb = rng.integers(0, 256, (9, width, 3)).astype(np.uint8)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        assert np.array_equal(image_ops._rgb_to_hsv_numpy(rgb), hsv), width
        assert np.array_equal(image_ops._hsv_to_rgb_numpy(hsv), cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)), width
        rgba = rng.integers(0, 256, (9, width, 4)).astype(np.uint8)
        assert np.array_equal(image_ops._rgba_to_gray_numpy(rgba), cv2.cvtColor(rgba, cv2.COLOR_RGBA2GRAY)), width
        lut = rng.integers(0, 256, 256).astype(np.uint8)
        assert np.array_equal(image_ops._apply_lut_numpy(rgb, lut), cv2.LUT(rgb, lut)), width


def test_contour_length_and_simplification_match_opencv_on_random_contours():
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(4)
    for trial in range(60):
        height, width = (int(value) for value in rng.integers(3, 90, 2))
        mask = (rng.random((height, width)) > rng.uniform(0.2, 0.9)).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            for closed in (True, False):
                length = cv2.arcLength(contour, closed)
                assert image_ops.contour_arc_length(contour, closed) == length
                epsilon = max(0.35, length * 0.002) if trial % 2 else float(rng.uniform(0.1, 6.0))
                assert np.array_equal(image_ops.approx_polygon(contour, epsilon, closed),
                                      cv2.approxPolyDP(contour, epsilon, closed))
        path = np.cumsum(rng.normal(0.0, 1.5, (int(rng.integers(2, 300)), 2)), axis=0).astype(np.float32)
        path = path.reshape(-1, 1, 2)
        for closed in (False, True):
            assert image_ops.contour_arc_length(path, closed) == cv2.arcLength(path, closed)
            assert np.array_equal(image_ops.approx_polygon(path, 0.35, closed), cv2.approxPolyDP(path, 0.35, closed))


def test_warp_affine_matches_opencv_on_random_rotations():
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(6)
    for trial in range(40):
        height, width = (int(value) for value in rng.integers(1, 70, 2))
        channels = (None, 3, 4)[trial % 3]
        image = rng.integers(0, 256, (height, width) if channels is None else (height, width, channels)).astype(np.uint8)
        matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), float(rng.uniform(-360, 360)),
                                         float(rng.choice([1.0, rng.uniform(0.3, 2.5)])))
        matrix[:, 2] += rng.uniform(-10, 10, 2)
        out_w, out_h = (int(value) for value in rng.integers(1, 110, 2))
        expected = cv2.warpAffine(image, matrix, (out_w, out_h), flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        assert np.array_equal(image_ops._warp_affine_linear_numpy(image, matrix, out_w, out_h), expected)


def test_morphology_matches_opencv_on_random_masks():
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(8)
    for _ in range(12):
        height, width = (int(value) for value in rng.integers(1, 90, 2))
        mask = (rng.random((height, width)) > 0.7).astype(np.uint8) * 255
        if rng.random() > 0.5:
            mask = rng.integers(0, 256, (height, width)).astype(np.uint8)
        size = int(rng.integers(0, 15)) * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        assert np.array_equal(image_ops.dilate_ellipse(mask, size), cv2.dilate(mask, kernel))
        assert np.array_equal(image_ops.erode_ellipse(mask, size), cv2.erode(mask, kernel))


# ---- one place for OpenCV ----------------------------------------------------------------


def test_only_image_ops_imports_opencv():
    offenders = []
    for root in SHIPPED:
        for path in [root] if root.suffix == ".py" else sorted(root.rglob("*.py")):
            if path.as_posix() == "cdmw/core/image_ops.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                if any(name.split(".", 1)[0] == "cv2" for name in names):
                    offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_without_opencv_the_replaced_functions_answer_and_the_rest_say_what_is_missing(monkeypatch):
    monkeypatch.setattr(image_ops, "_opencv_or_none", lambda: None)
    assert not image_ops.opencv_available()
    assert image_ops.resize(RGBA, 20, 15, "area").shape == (15, 20, 4)
    assert image_ops.gaussian_blur(RGB_F, 1.3).dtype == np.float32
    with pytest.raises(ImportError, match="still needs OpenCV"):
        image_ops.canny_edges(GRAY, 10, 20)


def test_the_list_of_functions_still_on_opencv_is_complete():
    tree = ast.parse(Path("cdmw/core/image_ops.py").read_text(encoding="utf-8"))
    calling = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            if any(isinstance(inner, ast.Call) and getattr(inner.func, "id", "") in {"_cv2", "_opencv_or_none"}
                   for inner in ast.walk(node)):
                calling.add(node.name)
    assert calling - {"opencv_available"} == set(image_ops.uses_opencv)
    assert set(image_ops.opencv_only) <= set(image_ops.uses_opencv)
