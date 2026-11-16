"""A painting frame's canvas, and a user's picture fitted to it.

A frame is a static mesh (`.pam`) whose canvas is one small flat submesh; its material
in the painting's `.pami` takes the picture as `_baseColorTexture`. Read from game
1.0.0.3663 (`.work/research/2026-11-16-paintings-build/frames.txt` of the branch that
built this): on 23 of the 24 frames exactly one submesh has a planar UV map with u
growing along +x and v growing down -y, and it is the material whose picture differs
between the paintings sharing the frame. The shipped pictures are stored upright, art
inside that UV rectangle (`cd_artist_paint_h_01.dds` fills v 0 to 0.695, the animal
atlases one cell each). The 24th frame, `cd_gimmick_picture_01.pam`, maps its canvas
turned round, so it is not offered.

The picture's physical shape comes from the canvas in metres, not from the texture:
texels are not square on most frames (`cd_in_dpw_picture_01.pam` maps 0.775 x 0.639 m
onto 397 x 253 texels of a 512 x 256 texture). The new texture keeps the source
picture's size, BC1 with a full mip chain, as every shipped painting texture is.
"""

from __future__ import annotations

import io
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

__all__ = [
    "FIT_FILL",
    "FIT_WHOLE",
    "CanvasMapping",
    "PaintingPictureError",
    "PicturePlan",
    "compose_picture",
    "dds_size",
    "find_canvas",
    "full_mip_count",
    "load_picture",
    "plan_picture_texture",
    "shape_picture",
]

#: Fill the canvas, cropping the picture's longer side.
FIT_FILL = "fill"
#: Show the whole picture, with bands of its average colour where the shapes differ.
FIT_WHOLE = "whole"
PICTURE_FORMAT = "BC1_UNORM"
_PLANAR_TOLERANCE = 1e-3
_AXIS_TOLERANCE = 0.9
_MAX_CANVAS_VERTICES = 8


class PaintingPictureError(ValueError):
    """A frame without a usable canvas, or a picture that cannot be used."""


@dataclass(frozen=True, slots=True)
class CanvasMapping:
    """The canvas submesh of a frame: its material, UV rectangle and size in metres."""

    material: str
    uv_rect: Tuple[float, float, float, float]
    size_m: Tuple[float, float]
    vertex_count: int

    @property
    def aspect(self) -> float:
        return self.size_m[0] / self.size_m[1]


@dataclass(frozen=True, slots=True)
class PicturePlan:
    """The new picture texture: size, mips, format, and the texel rectangle the canvas shows."""

    width: int
    height: int
    mip_count: int
    dds_format: str
    rect: Tuple[int, int, int, int]
    aspect: float


def full_mip_count(width: int, height: int) -> int:
    """Mip levels down to 1 x 1: 9 for 256, 10 for 512, 11 for 1024."""

    return int(math.floor(math.log2(max(1, int(width), int(height))))) + 1


def dds_size(data: bytes) -> Tuple[int, int]:
    """(width, height) from a DDS header."""

    if len(data) < 20 or data[:4] != b"DDS ":
        raise PaintingPictureError("The frame's picture texture is not a DDS file.")
    height, width = struct.unpack_from("<II", data, 12)
    if not width or not height:
        raise PaintingPictureError("The frame's picture texture has no size.")
    return int(width), int(height)


def _solve(rows: Sequence[Sequence[float]], values: Sequence[float]) -> Tuple[Tuple[float, ...], float]:
    """Least squares with numpy; returns the coefficients and the worst residual."""

    import numpy as np

    a = np.asarray(rows, dtype=float)
    b = np.asarray(values, dtype=float)
    solution, *_ = np.linalg.lstsq(a, b, rcond=None)
    return tuple(float(v) for v in solution), float(np.abs(a @ solution - b).max()) if len(b) else 0.0


def _canvas_of(submesh) -> Optional[CanvasMapping]:
    vertices, uvs = list(submesh.vertices or ()), list(submesh.uvs or ())
    if not 3 <= len(vertices) <= _MAX_CANVAS_VERTICES or len(uvs) != len(vertices):
        return None
    # Position as an affine function of (u, v): one column per axis.
    rows = [(u, v, 1.0) for u, v in uvs]
    columns, worst = [], 0.0
    for axis in range(3):
        coefficients, residual = _solve(rows, [p[axis] for p in vertices])
        columns.append(coefficients)
        worst = max(worst, residual)
    if worst > _PLANAR_TOLERANCE:
        return None
    along_u = [c[0] for c in columns]
    along_v = [c[1] for c in columns]
    length_u, length_v = math.hypot(*along_u), math.hypot(*along_v)
    if length_u <= 0 or length_v <= 0:
        return None
    # u must run to the right (+x) and v downwards (-y), as on every offered frame.
    if along_u[0] < _AXIS_TOLERANCE * length_u or -along_v[1] < _AXIS_TOLERANCE * length_v:
        return None
    us, vs = [u for u, _ in uvs], [v for _, v in uvs]
    rect = tuple(min(1.0, max(0.0, value)) for value in (min(us), min(vs), max(us), max(vs)))
    size = (length_u * (max(us) - min(us)), length_v * (max(vs) - min(vs)))
    if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0 or size[0] <= 0 or size[1] <= 0:
        return None
    return CanvasMapping(material=str(submesh.material).strip(), uv_rect=rect, size_m=size, vertex_count=len(vertices))


def find_canvas(mesh, picture_materials: Sequence[str]) -> CanvasMapping:
    """The one canvas of `mesh` among the materials the `.pami` gives a base colour texture."""

    wanted = {str(name).strip() for name in picture_materials}
    found = [canvas for canvas in (_canvas_of(sub) for sub in getattr(mesh, "submeshes", ()))
             if canvas is not None and canvas.material in wanted]
    if len(found) != 1:
        raise PaintingPictureError(
            f"The frame {Path(str(getattr(mesh, 'path', '') or 'mesh')).name} has {len(found)} canvas surfaces CDMW can map, not one.")
    return found[0]


def plan_picture_texture(texture_size: Tuple[int, int], canvas: CanvasMapping) -> PicturePlan:
    """The new texture at the source picture's size, and the texels the canvas samples."""

    width, height = (int(value) for value in texture_size)
    if width <= 0 or height <= 0 or width % 4 or height % 4:
        raise PaintingPictureError(f"The frame's picture texture is {width} x {height}; BC1 needs sides that are multiples of 4.")
    u0, v0, u1, v1 = canvas.uv_rect
    rect = (int(math.floor(u0 * width + 1e-6)), int(math.floor(v0 * height + 1e-6)),
            int(math.ceil(u1 * width - 1e-6)), int(math.ceil(v1 * height - 1e-6)))
    rect = (max(0, rect[0]), max(0, rect[1]), min(width, rect[2]), min(height, rect[3]))
    if rect[2] - rect[0] < 4 or rect[3] - rect[1] < 4:
        raise PaintingPictureError("The frame's canvas covers too few texels to hold a picture.")
    return PicturePlan(width=width, height=height, mip_count=full_mip_count(width, height),
                       dds_format=PICTURE_FORMAT, rect=rect, aspect=canvas.aspect)


def load_picture(path) -> "object":
    """The picture as an RGB Pillow image; refuses a missing or unreadable file."""

    from PIL import Image, UnidentifiedImageError

    if path is None or not str(path).strip():
        raise PaintingPictureError("Choose a picture for the painting.")
    source = Path(path)
    if not source.is_file():
        raise PaintingPictureError(f"The picture {source.name} does not exist.")
    try:
        with Image.open(io.BytesIO(source.read_bytes())) as image:
            image.load()
            picture = image.convert("RGB")
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as exc:
        raise PaintingPictureError(f"{source.name} could not be read as a picture: {exc}") from exc
    if picture.width < 1 or picture.height < 1:
        raise PaintingPictureError(f"{source.name} has no pixels.")
    return picture


def shape_picture(picture, aspect: float, fit: str):
    """The picture cropped (fill) or padded (whole) to the canvas's physical shape."""

    from PIL import Image, ImageStat

    width, height = picture.size
    if fit == FIT_FILL:
        if width / height > aspect:
            keep = max(1, round(height * aspect))
            left = (width - keep) // 2
            return picture.crop((left, 0, left + keep, height))
        keep = max(1, round(width / aspect))
        top = (height - keep) // 2
        return picture.crop((0, top, width, top + keep))
    if fit != FIT_WHOLE:
        raise PaintingPictureError(f"Unknown picture fit {fit!r}.")
    if width / height > aspect:
        box = (width, max(1, round(width / aspect)))
    else:
        box = (max(1, round(height * aspect)), height)
    colour = tuple(int(round(value)) for value in ImageStat.Stat(picture).mean[:3])
    canvas = Image.new("RGB", box, colour)
    canvas.paste(picture, ((box[0] - width) // 2, (box[1] - height) // 2))
    return canvas


def compose_picture(picture, plan: PicturePlan, *, fit: str = FIT_FILL):
    """The full texture image: the picture in the canvas rectangle, its edges carried outward.

    Texels outside the rectangle repeat the nearest edge, so filtering and the slightly
    overhanging UVs of some frames sample the picture's own border, not a seam.
    """

    import numpy as np
    from PIL import Image

    x0, y0, x1, y1 = plan.rect
    shaped = shape_picture(picture.convert("RGB"), plan.aspect, fit).resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    pixels = np.asarray(shaped, dtype=np.uint8)
    full = np.pad(pixels, ((y0, plan.height - y1), (x0, plan.width - x1), (0, 0)), mode="edge")
    alpha = np.full(full.shape[:2] + (1,), 255, dtype=np.uint8)
    return Image.fromarray(np.concatenate((full, alpha), axis=2), "RGBA")
