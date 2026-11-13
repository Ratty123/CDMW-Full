"""Record what OpenCV returns today for every cv2 call the Texture Editor makes.

Run once, with opencv-python-headless 4.13.0.92 installed, from the repository
root:

    python tests/fixtures/image_ops/make_cv2_reference.py

It writes ``cv2_reference.npz`` beside this file. ``tests/test_image_ops.py``
compares ``cdmw.core.image_ops`` against it, so the pins keep working after
OpenCV leaves the package. The inputs are made here from fixed seeds, so the
file holds only OpenCV's outputs plus the inputs that cannot be regenerated
cheaply. Exhaustive inputs (every 8-bit colour) are pinned by SHA-256 digest.
"""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from tests.helpers.image_ops_inputs import (  # noqa: E402
    all_rgb_colours,
    all_hsv_colours,
    binary_mask,
    float_rgb,
    gray_image,
    lasso_paths,
    polygons,
    rgba_image,
    soft_mask,
)


def digest(array: np.ndarray) -> np.ndarray:
    data = np.ascontiguousarray(array)
    text = f"{data.dtype.str}{data.shape}".encode() + data.tobytes()
    return np.frombuffer(hashlib.sha256(text).digest(), dtype=np.uint8)


def main() -> None:
    out: dict[str, np.ndarray] = {"opencv_version": np.array(cv2.__version__)}
    rgba = rgba_image()
    rgb = np.ascontiguousarray(rgba[..., :3])
    gray = gray_image()
    rgb_f = float_rgb()
    masks = {"binary": binary_mask(), "soft": soft_mask()}

    # copyMakeBorder, BORDER_CONSTANT
    for pad in (1, 4):
        out[f"pad_{pad}"] = cv2.copyMakeBorder(rgba, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))

    # cvtColor
    out["rgb2bgr"] = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    out["rgba2bgra"] = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    out["bgra2rgba"] = cv2.cvtColor(rgba, cv2.COLOR_BGRA2RGBA)
    out["gray2bgra"] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGRA)
    out["bgr2bgra"] = cv2.cvtColor(rgb, cv2.COLOR_BGR2BGRA)
    out["rgba2gray"] = cv2.cvtColor(rgba, cv2.COLOR_RGBA2GRAY)
    every_rgb = all_rgb_colours()
    every_rgba = np.concatenate([every_rgb, np.full(every_rgb.shape[:2] + (1,), 255, np.uint8)], axis=2)
    out["rgba2gray_all_digest"] = digest(cv2.cvtColor(every_rgba, cv2.COLOR_RGBA2GRAY))
    out["rgb2hsv_all_digest"] = digest(cv2.cvtColor(every_rgb, cv2.COLOR_RGB2HSV))
    out["rgb2hsv"] = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    every_hsv = all_hsv_colours()
    out["hsv2rgb_all_digest"] = digest(cv2.cvtColor(every_hsv, cv2.COLOR_HSV2RGB))
    out["hsv2rgb"] = cv2.cvtColor(np.ascontiguousarray(out["rgb2hsv"]), cv2.COLOR_HSV2RGB)

    # LUT
    lut = np.random.default_rng(5).integers(0, 256, 256).astype(np.uint8)
    out["lut_table"] = lut
    out["lut"] = cv2.LUT(rgb, lut)

    # imencode / imdecode
    out["png_rgba_blob"] = np.frombuffer(bytes(cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))[1]), np.uint8)
    out["png_mask_blob"] = np.frombuffer(bytes(cv2.imencode(".png", masks["soft"])[1]), np.uint8)
    out["png_bgr_blob"] = np.frombuffer(bytes(cv2.imencode(".png", rgb)[1]), np.uint8)

    # getStructuringElement + dilate / erode
    for size in range(1, 62, 2):
        out[f"ellipse_{size}"] = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    for name, mask in masks.items():
        for size in (3, 7, 21):
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
            out[f"dilate_{name}_{size}"] = cv2.dilate(mask, kernel, iterations=1)
            out[f"erode_{name}_{size}"] = cv2.erode(mask, kernel, iterations=1)

    # GaussianBlur
    for sigma in (0.8, 1.3, 2.9, 6.4):
        out[f"gauss_f32_{sigma}"] = cv2.GaussianBlur(rgb_f, (0, 0), sigmaX=sigma, sigmaY=sigma)
    out["gauss_gray_1.2"] = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.2, sigmaY=1.2)
    for feather in (1, 3, 8):
        kernel = max(3, feather * 2 + 1)
        out[f"gauss_mask_{feather}"] = cv2.GaussianBlur(masks["soft"], (kernel, kernel), sigmaX=max(0.8, feather / 2.0))

    # addWeighted
    blurred = out["gauss_f32_1.3"]
    for amount in (0.05, 0.47):
        out[f"add_weighted_{amount}"] = cv2.addWeighted(rgb_f, 1.0 + amount, blurred, -amount, 0.0)

    # medianBlur, bilateralFilter
    for size in (3, 5, 9):
        out[f"median_{size}"] = cv2.medianBlur(rgb, size)
    for diameter, colour, space in ((3, 12.0, 6.0), (7, 30.0, 16.0), (15, 48.0, 26.0)):
        out[f"bilateral_{diameter}"] = cv2.bilateralFilter(rgb, diameter, colour, space)

    # resize
    sizes = ((53, 37), (20, 15), (106, 74), (71, 50), (13, 61), (1, 1))
    for width, height in sizes:
        for label, flag in (("nearest", cv2.INTER_NEAREST), ("linear", cv2.INTER_LINEAR),
                            ("area", cv2.INTER_AREA), ("cubic", cv2.INTER_CUBIC)):
            out[f"resize_{label}_{width}x{height}"] = cv2.resize(rgba, (width, height), interpolation=flag)
    supersampled = cv2.resize(masks["binary"], (masks["binary"].shape[1] * 4, masks["binary"].shape[0] * 4),
                              interpolation=cv2.INTER_NEAREST)
    out["resize_area_quarter"] = cv2.resize(supersampled, (masks["binary"].shape[1], masks["binary"].shape[0]),
                                            interpolation=cv2.INTER_AREA)

    # floodFill: the paint bucket (mask only, floating range) and the selection fill
    for tolerance in (0, 24, 90):
        for index, seed in enumerate(((5, 5), (40, 20), (0, 36))):
            source = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR).copy()
            flood_mask = np.zeros((rgb.shape[0] + 2, rgb.shape[1] + 2), np.uint8)
            cv2.floodFill(source, flood_mask, seed, (0, 0, 0), loDiff=(tolerance,) * 3, upDiff=(tolerance,) * 3,
                          flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY)
            out[f"flood_bucket_{tolerance}_{index}"] = flood_mask
            for connectivity in (4, 8):
                working = masks["soft"].copy()
                cv2.floodFill(working, None, seed, 255, loDiff=tolerance, upDiff=tolerance, flags=connectivity)
                out[f"flood_select_{tolerance}_{index}_{connectivity}"] = working

    # fillPoly LINE_AA on a 4x supersampled patch, then INTER_AREA down (selection masks)
    for index, polygon in enumerate(polygons()):
        canvas = np.zeros((160, 200), np.uint8)
        cv2.fillPoly(canvas, [polygon.reshape(-1, 1, 2)], 255, lineType=cv2.LINE_AA)
        out[f"fillpoly_aa_{index}"] = canvas
        out[f"fillpoly_aa_down_{index}"] = cv2.resize(canvas, (50, 40), interpolation=cv2.INTER_AREA)

    # findContours + arcLength + approxPolyDP (closed), as _selection_mask_to_polygons uses them
    for name, mask in masks.items():
        binary = np.asarray(mask > 0, dtype=np.uint8)
        contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        out[f"contours_{name}_count"] = np.array(len(contours))
        out[f"contours_{name}_hierarchy"] = np.asarray(hierarchy).reshape(-1, 4) if hierarchy is not None else np.zeros((0, 4), np.int32)
        for index, contour in enumerate(contours):
            out[f"contours_{name}_{index}"] = contour.reshape(-1, 2)
            length = cv2.arcLength(contour, True)
            out[f"arclength_{name}_{index}"] = np.array(length)
            epsilon = max(0.35, length * 0.002)
            out[f"approx_closed_{name}_{index}"] = cv2.approxPolyDP(contour, epsilon, closed=True).reshape(-1, 2)
    # approxPolyDP (open, float32): the lasso simplification
    for index, path in enumerate(lasso_paths()):
        out[f"lasso_{index}"] = path
        out[f"approx_open_{index}"] = cv2.approxPolyDP(path.reshape(-1, 1, 2), 0.35, closed=False).reshape(-1, 2)

    # Canny on the blurred gray image (edge snapping)
    blurred_gray = out["gauss_gray_1.2"]
    for low, high in ((10, 23), (44, 98), (94, 210)):
        out[f"canny_{low}_{high}"] = cv2.Canny(blurred_gray, low, high)

    # getRotationMatrix2D + warpAffine, as the floating selection rotates
    for angle in (0.5, 17.0, 45.0, 90.0, -133.25):
        height, width = rgba.shape[:2]
        center = (width / 2.0, height / 2.0)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        out[f"rotation_matrix_{angle}"] = matrix
        cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
        bound_w = max(1, int((height * sin) + (width * cos)))
        bound_h = max(1, int((height * cos) + (width * sin)))
        shifted = matrix.copy()
        shifted[0, 2] += (bound_w / 2.0) - center[0]
        shifted[1, 2] += (bound_h / 2.0) - center[1]
        out[f"warp_{angle}"] = cv2.warpAffine(rgba, shifted, (bound_w, bound_h), flags=cv2.INTER_LINEAR,
                                              borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))

    np.savez_compressed(HERE / "cv2_reference.npz", **out)
    print(f"{len(out)} arrays, OpenCV {cv2.__version__}, {math.ceil((HERE / 'cv2_reference.npz').stat().st_size / 1024)} KiB")


if __name__ == "__main__":
    main()
