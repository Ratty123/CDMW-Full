"""Mesh faces to texture pixels and back: the rules behind Select From Mesh Selection.

A face covers the texture pixels whose centres lie on or inside its UV triangle. The
rules follow how the Mesh Editor's 3D view samples a texture, not how its UV page draws:

* U runs left to right and V top to bottom (V 0 is the top row), as the 3D view and
  the game sample a DDS. A material that flips V is flipped here too (``flip_v``).
* UVs outside 0-1 wrap: the 3D view repeats the texture, so a face at U 1.2 covers the
  pixels at U 0.2. The UV page draws only the 0-1 square and selects by the raw values.
* Mirrored and overlapping UVs cover the same pixels more than once. Nothing is lost:
  the mask is their union, and :func:`uv_faces_covering` names every face on a pixel.
* A face too small or too thin to hold a pixel centre still covers the pixel under its
  centre, so every face selects something.

One function (:func:`_coverage`) turns faces into pixels for the selection and for both
reads back, so a pixel is covered by a face exactly when that face is listed for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Mapping, Optional, Sequence

import numpy as np

#: How far outside an edge a pixel centre may lie and still count, in pixels.
EDGE_TOLERANCE = 1.0e-6
#: Faces whose pixel box is at most this many pixels on a side are tested in batches.
_BATCH_SIDE = 64
#: Test points per batch (memory stays near 100 MB at most).
_BATCH_POINTS = 1 << 21
#: A face spanning more repeats of the texture than this is left out and counted.
MAX_REPEATS = 64


@dataclass(frozen=True, slots=True)
class UvPart:
    """One part's primary UVs and triangles."""

    part: int
    uvs: Sequence[Sequence[float]]
    faces: Sequence[Sequence[int]]
    flip_v: bool = False


@dataclass(slots=True)
class UvMaskReport:
    """What a mask was made from, for the status line and the MCP answer."""

    faces: int = 0
    #: Faces with UVs outside 0-1, wrapped onto the texture.
    wrapped_faces: int = 0
    #: Faces holding no pixel centre, given the pixel under their centre.
    faces_under_a_pixel: int = 0
    #: Faces left out: an index past the UVs, a missing or non-finite UV.
    skipped_faces: int = 0
    #: Faces left out because they span more than MAX_REPEATS repeats.
    too_many_repeats: int = 0
    faces_by_part: dict[int, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"faces": self.faces, "wrapped_faces": self.wrapped_faces,
                "faces_under_a_pixel": self.faces_under_a_pixel, "skipped_faces": self.skipped_faces,
                "too_many_repeats": self.too_many_repeats,
                "faces_by_part": {str(part): count for part, count in sorted(self.faces_by_part.items())}}


def texel_position(u: float, v: float, width: int, height: int, *, flip_v: bool = False) -> tuple[float, float]:
    """Where a UV lands on the texture, in pixels (not wrapped): (0, 0) is the top-left corner."""

    return float(u) * width, (1.0 - float(v) if flip_v else float(v)) * height


def _texel_triangles(part: UvPart, width: int, height: int, face_ids: Optional[Sequence[int]],
                     report: UvMaskReport) -> tuple[np.ndarray, np.ndarray]:
    """(face numbers, their triangles in pixels as an (n, 3, 2) array) for one part."""

    faces = np.asarray(part.faces, dtype=np.int64).reshape(-1, 3) if len(part.faces) else np.zeros((0, 3), np.int64)
    ids = np.arange(len(faces), dtype=np.int64) if face_ids is None else np.unique(
        np.asarray(list(face_ids), dtype=np.int64))
    ids = ids[(ids >= 0) & (ids < len(faces))]
    uvs = np.asarray(part.uvs, dtype=np.float64).reshape(-1, 2) if len(part.uvs) else np.zeros((0, 2))
    corners = faces[ids]
    usable = np.all((corners >= 0) & (corners < len(uvs)), axis=1)
    if len(uvs):
        usable &= np.all(np.isfinite(uvs[np.clip(corners, 0, len(uvs) - 1)]), axis=(1, 2))
    report.skipped_faces += int(np.count_nonzero(~usable))
    ids, corners = ids[usable], corners[usable]
    if not len(ids):
        return ids, np.zeros((0, 3, 2))
    uv = uvs[corners]
    outside = np.any((uv < 0.0) | (uv > 1.0), axis=(1, 2))
    report.wrapped_faces += int(np.count_nonzero(outside))
    tri = np.empty_like(uv)
    tri[..., 0] = uv[..., 0] * width
    tri[..., 1] = ((1.0 - uv[..., 1]) if part.flip_v else uv[..., 1]) * height
    return ids, tri


def _oriented(tri: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The triangles wound one way (mirrored UVs turn the other way), and their doubled areas."""

    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    area = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    flipped = area < 0
    out = tri.copy()
    out[flipped, 1], out[flipped, 2] = tri[flipped, 2], tri[flipped, 1]
    return out, np.abs(area)


def _coverage(ids: np.ndarray, tri: np.ndarray, width: int, height: int,
              report: UvMaskReport) -> Iterator[tuple]:
    """Every pixel each face covers, wrapped onto the texture.

    Yields ``("points", faces, ys, xs)`` for small faces and ``("spans", face, rows, first,
    last)`` for large ones (each span inside one row, ``first <= last``)."""

    if not len(ids):
        return
    tri, area = _oriented(tri)
    low, high = tri.min(axis=1), tri.max(axis=1)
    x0 = np.ceil(low[:, 0] - 0.5 - EDGE_TOLERANCE).astype(np.int64)
    x1 = np.floor(high[:, 0] - 0.5 + EDGE_TOLERANCE).astype(np.int64)
    y0 = np.ceil(low[:, 1] - 0.5 - EDGE_TOLERANCE).astype(np.int64)
    y1 = np.floor(high[:, 1] - 0.5 + EDGE_TOLERANCE).astype(np.int64)
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    side = np.maximum(nx, ny)
    flat = area <= 1.0e-12
    centred = np.zeros(len(ids), dtype=bool)  # faces that hold at least one pixel centre
    small = (side <= _BATCH_SIDE) & ~flat & (nx > 0) & (ny > 0)
    large = (side > _BATCH_SIDE) & ~flat
    too_many = large & ((nx > MAX_REPEATS * width) | (ny > MAX_REPEATS * height))
    report.too_many_repeats += int(np.count_nonzero(too_many))
    large &= ~too_many

    # Small faces: every pixel centre of their box tested at once, in batches by box size.
    bucket = np.zeros(len(ids), dtype=np.int64)
    bucket[small] = np.ceil(np.log2(np.maximum(side[small], 1))).astype(np.int64)
    for power in np.unique(bucket[small]):
        size = 1 << int(power)
        members = np.flatnonzero(small & (bucket == power))
        step = max(1, _BATCH_POINTS // (size * size))
        offsets = np.arange(size, dtype=np.int64)
        for start in range(0, len(members), step):
            chosen = members[start:start + step]
            gx = x0[chosen, None, None] + offsets[None, None, :]
            gy = y0[chosen, None, None] + offsets[None, :, None]
            inside = (offsets[None, None, :] < nx[chosen, None, None]) & (offsets[None, :, None] < ny[chosen, None, None])
            cx, cy = gx + 0.5, gy + 0.5
            t = tri[chosen]
            for first, second in ((0, 1), (1, 2), (2, 0)):
                ax, ay = t[:, first, 0, None, None], t[:, first, 1, None, None]
                ex, ey = t[:, second, 0, None, None] - ax, t[:, second, 1, None, None] - ay
                length = np.maximum(np.hypot(ex, ey), 1.0e-300)
                inside &= (ex * (cy - ay) - ey * (cx - ax)) / length >= -EDGE_TOLERANCE
            owner, row, column = np.nonzero(inside)
            if not len(owner):
                continue
            centred[chosen[np.unique(owner)]] = True
            yield ("points", ids[chosen[owner]], np.mod(gy[owner, row, 0], height), np.mod(gx[owner, 0, column], width))

    # Large faces: one span per pixel row, from the three edges.
    for index in np.flatnonzero(large):
        rows = np.arange(y0[index], y1[index] + 1, dtype=np.int64)
        cy = rows + 0.5
        lo = np.full(len(rows), -np.inf)
        hi = np.full(len(rows), np.inf)
        keep = np.ones(len(rows), dtype=bool)
        t = tri[index]
        for first, second in ((0, 1), (1, 2), (2, 0)):
            ax, ay = t[first]
            ex, ey = t[second, 0] - ax, t[second, 1] - ay
            slack = EDGE_TOLERANCE * max(float(np.hypot(ex, ey)), 1.0e-300)
            # Inside: ex * (cy - ay) - ey * (x - ax) >= -slack.
            bound = ex * (cy - ay) + ey * ax + slack
            if ey > 0:
                hi = np.minimum(hi, bound / ey)
            elif ey < 0:
                lo = np.maximum(lo, bound / ey)
            else:
                keep &= ex * (cy - ay) >= -slack
        first_x = np.maximum(np.ceil(lo - 0.5), x0[index])
        last_x = np.minimum(np.floor(hi - 0.5), x1[index])
        keep &= last_x >= first_x
        if not np.any(keep):
            continue
        centred[index] = True
        rows, first_x, last_x = rows[keep], first_x[keep].astype(np.int64), last_x[keep].astype(np.int64)
        yield ("spans", int(ids[index]), *_folded_spans(rows, first_x, last_x, width, height))

    # Faces under a pixel: the pixel their centre falls on.
    lonely = np.flatnonzero(~centred & ~too_many)
    report.faces_under_a_pixel += len(lonely)
    if len(lonely):
        centre = tri[lonely].mean(axis=1)
        yield ("points", ids[lonely], np.mod(np.floor(centre[:, 1]).astype(np.int64), height),
               np.mod(np.floor(centre[:, 0]).astype(np.int64), width))


def _folded_spans(rows: np.ndarray, first: np.ndarray, last: np.ndarray, width: int,
                  height: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unwrapped row spans as spans on the texture: rows and columns wrap, a span crossing
    the right edge splits in two and a span at least as wide as the texture fills its row."""

    whole = last - first + 1 >= width
    start = np.where(whole, 0, np.mod(first, width))
    end = np.where(whole, width - 1, start + (last - first))
    split = end >= width
    rows = np.mod(rows, height)
    out_rows = np.concatenate([rows, rows[split]])
    out_first = np.concatenate([start, np.zeros(int(np.count_nonzero(split)), dtype=np.int64)])
    out_last = np.concatenate([np.where(split, width - 1, end), end[split] - width])
    return out_rows, out_first, out_last


def _faces_of(parts: Sequence[UvPart], width: int, height: int,
              faces_by_part: Mapping[int, Optional[Sequence[int]]] | None,
              report: UvMaskReport) -> Iterator[tuple[int, tuple]]:
    for part in parts:
        if faces_by_part is not None and part.part not in faces_by_part:
            continue
        chosen = None if faces_by_part is None else faces_by_part[part.part]
        ids, tri = _texel_triangles(part, int(width), int(height), chosen, report)
        report.faces += len(ids)
        if len(ids):
            report.faces_by_part[part.part] = report.faces_by_part.get(part.part, 0) + len(ids)
        for item in _coverage(ids, tri, int(width), int(height), report):
            yield part.part, item


def uv_faces_mask(width: int, height: int, parts: Sequence[UvPart],
                  faces_by_part: Mapping[int, Optional[Sequence[int]]] | None = None,
                  ) -> tuple[np.ndarray, UvMaskReport]:
    """A 0/255 mask of every pixel the chosen faces cover.

    ``faces_by_part`` maps a part to its face numbers, or to None for all of its faces;
    parts it leaves out are left out. Without it every face of every part counts."""

    width, height = int(width), int(height)
    report = UvMaskReport()
    mask = np.zeros((max(1, height), max(1, width)), dtype=np.uint8)
    if width <= 0 or height <= 0:
        return mask, report
    diff = None
    for _part, item in _faces_of(parts, width, height, faces_by_part, report):
        if item[0] == "points":
            mask[item[2], item[3]] = 255
            continue
        rows, first, last = item[2:]
        if diff is None:
            diff = np.zeros((height, width + 1), dtype=np.int32)
        np.add.at(diff, (rows, first), 1)
        np.add.at(diff, (rows, last + 1), -1)
    if diff is not None:
        mask[np.cumsum(diff, axis=1)[:, :width] > 0] = 255
    return mask, report


def uv_faces_covering(width: int, height: int, parts: Sequence[UvPart], *,
                      mask: Optional[np.ndarray] = None, pixel: Optional[tuple[int, int]] = None,
                      faces_by_part: Mapping[int, Optional[Sequence[int]]] | None = None,
                      ) -> dict[int, list[int]]:
    """The faces covering any pixel of ``mask`` (nonzero), or the one ``pixel`` (x, y), by part.

    Every face on a pixel is listed: mirrored and overlapping UVs list each of their faces."""

    width, height = int(width), int(height)
    if (mask is None) == (pixel is None):
        raise ValueError("Give a mask or a pixel.")
    found: dict[int, set[int]] = {}
    if width <= 0 or height <= 0:
        return {}
    if mask is not None:
        hits = np.asarray(mask)[:height, :width] > 0
        if hits.shape != (height, width):
            raise ValueError("The mask is not the texture's size.")
        prefix = np.zeros((height, width + 1), dtype=np.int64)
        np.cumsum(hits, axis=1, out=prefix[:, 1:])
    else:
        px, py = int(pixel[0]), int(pixel[1])
        if not (0 <= px < width and 0 <= py < height):
            raise ValueError(f"The pixel lies outside the texture ({width} x {height}).")
    report = UvMaskReport()
    for part, item in _faces_of(parts, width, height, faces_by_part, report):
        bucket = found.setdefault(part, set())
        if item[0] == "points":
            faces, ys, xs = item[1:]
            touched = hits[ys, xs] if mask is not None else (ys == py) & (xs == px)
            bucket.update(int(face) for face in np.unique(faces[touched]))
            continue
        face, rows, first, last = item[1:]
        if mask is not None:
            touched = np.any(prefix[rows, last + 1] - prefix[rows, first] > 0)
        else:
            touched = np.any((rows == py) & (first <= px) & (px <= last))
        if touched:
            bucket.add(int(face))
    return {part: sorted(faces) for part, faces in sorted(found.items()) if faces}


__all__ = ["EDGE_TOLERANCE", "MAX_REPEATS", "UvMaskReport", "UvPart", "texel_position",
           "uv_faces_covering", "uv_faces_mask"]
