"""Deterministic inputs for the image operation pins (tests/test_image_ops.py).

Small on purpose: odd sizes so no stride is a power of two, flat areas, hard
edges, gradients, a hole and single-pixel details, so borders, ties and
rounding all occur.
"""

from __future__ import annotations

import numpy as np


def rgba_image(height: int = 37, width: int = 53) -> np.ndarray:
    rng = np.random.default_rng(1234)
    image = rng.integers(0, 256, (height, width, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:height, 0:width]
    image[: height // 3, :, 0] = (xx[: height // 3] * 255 // max(1, width - 1)).astype(np.uint8)
    image[: height // 3, :, 1] = (yy[: height // 3] * 255 // max(1, height - 1)).astype(np.uint8)
    image[height // 3 : height // 2, : width // 2] = (200, 40, 40, 255)
    image[height // 3 : height // 2, width // 2 :] = (40, 200, 40, 128)
    image[-3:, -3:] = (0, 0, 0, 0)
    image[5, 7] = (255, 255, 255, 255)
    return image


def float_rgb() -> np.ndarray:
    return rgba_image()[..., :3].astype(np.float32) * np.float32(0.97) + np.float32(1.25)


def gray_image(height: int = 41, width: int = 47) -> np.ndarray:
    rng = np.random.default_rng(77)
    yy, xx = np.mgrid[0:height, 0:width]
    image = ((xx * 5 + yy * 3) % 256).astype(np.uint8)
    image[10:30, 12:35] = 220
    image[18:22, 20:27] = 15
    noise = rng.integers(-12, 13, (height, width))
    return np.clip(image.astype(np.int32) + noise, 0, 255).astype(np.uint8)


def binary_mask(height: int = 64, width: int = 80) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width]
    mask = np.zeros((height, width), np.uint8)
    mask[((xx - 22) ** 2 + (yy - 24) ** 2) <= 14 ** 2] = 255
    mask[8:40, 44:72] = 255
    mask[16:30, 52:62] = 0  # a hole
    mask[50:52, 10:70] = 255  # a thin bar
    mask[58, 5] = 255  # a single pixel
    mask[0:4, 0:6] = 255  # touching the border
    return mask


def soft_mask() -> np.ndarray:
    mask = binary_mask().astype(np.float32)
    # A box blur in numpy keeps this input independent of the code under test.
    padded = np.pad(mask, 2, mode="edge")
    total = np.zeros_like(mask)
    for dy in range(5):
        for dx in range(5):
            total += padded[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
    return np.clip(np.round(total / 25.0), 0, 255).astype(np.uint8)


def all_rgb_colours() -> np.ndarray:
    values = np.arange(1 << 24, dtype=np.uint32)
    rgb = np.stack(((values >> 16) & 255, (values >> 8) & 255, values & 255), axis=-1).astype(np.uint8)
    return rgb.reshape(4096, 4096, 3)


def all_hsv_colours() -> np.ndarray:
    h, s, v = np.meshgrid(np.arange(180), np.arange(256), np.arange(256), indexing="ij")
    return np.stack((h, s, v), axis=-1).astype(np.uint8).reshape(180 * 256, 256, 3)


def polygons() -> list[np.ndarray]:
    """Integer polygons on a 200 x 160 canvas, as the 4x supersampled selection uses."""

    star = []
    for index in range(10):
        angle = np.pi * 2.0 * index / 10.0
        radius = 70.0 if index % 2 == 0 else 28.0
        star.append((100 + radius * np.cos(angle), 80 + radius * np.sin(angle)))
    return [
        np.array([(10, 10), (190, 14), (120, 150), (12, 120)], np.int32),
        np.round(np.array(star)).astype(np.int32),
        np.array([(20, 20), (180, 20), (20, 140), (180, 140)], np.int32),  # self-intersecting
        np.array([(5, 5), (6, 5), (6, 155), (5, 155)], np.int32),  # a sliver
        np.array([(0, 0), (199, 0), (199, 159), (0, 159)], np.int32),  # the whole canvas
    ]


def lasso_paths() -> list[np.ndarray]:
    rng = np.random.default_rng(99)
    paths = []
    for count in (3, 12, 200):
        steps = rng.normal(0.0, 1.0, (count, 2)).astype(np.float32)
        paths.append(np.cumsum(steps, axis=0).astype(np.float32) + np.float32(50.0))
    t = np.linspace(0.0, 2.0 * np.pi, 400, dtype=np.float32)
    paths.append(np.stack((40 + 30 * np.cos(t), 40 + 20 * np.sin(t)), axis=-1).astype(np.float32))
    paths.append(np.array([(0, 0), (1, 0.2), (2, 0), (3, 0.4), (4, 0)], np.float32))
    return paths
