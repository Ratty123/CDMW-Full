"""Turn an imported model's painted cloth into template-guide bindings in its built PAC.

The imported parts are merged into the template's draw slots during the build, so
the built parts do not line up with the imported ones. The paint therefore travels
by position: every imported vertex, painted or not, becomes a sample at its placed
position, and each built vertex takes the value of the sample it was built from.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
from cdmw.modding.pac_cloth_paint import ClothPaintSamples, apply_pac_cloth_paint

#: Largest gap between a built vertex and its painted source, as a share of the
#: model's size. PAC positions are quantized to 1/32767 of each part's bounds.
SAMPLE_TOLERANCE = 1e-3


def part_cloth_paint(part) -> list[float]:
    """The part's cloth paint, or [] when it has none that fits its vertices."""
    paint = list(getattr(part, "cloth_paint", ()) or ())
    if len(paint) != len(getattr(part, "vertices", ()) or ()):
        return []
    return [min(1.0, max(0.0, float(value))) if math.isfinite(float(value)) else 0.0 for value in paint]


def mesh_has_cloth_paint(mesh) -> bool:
    # The model panel asks on every refresh: stop at the first painted vertex and build no lists.
    for part in getattr(mesh, "submeshes", ()) or ():
        paint = getattr(part, "cloth_paint", ()) or ()
        if len(paint) == len(getattr(part, "vertices", ()) or ()) and any(
                0 < float(value) < math.inf for value in paint):
            return True
    return False


def _apply_row_matrix(point, matrix: Sequence[float]):
    x, y, z = (float(v) for v in point)
    return (x * matrix[0] + y * matrix[4] + z * matrix[8] + matrix[12],
            x * matrix[1] + y * matrix[5] + z * matrix[9] + matrix[13],
            x * matrix[2] + y * matrix[6] + z * matrix[10] + matrix[14])


def import_cloth_paint_samples(mesh, matrix: Sequence[float]) -> ClothPaintSamples:
    """Every imported vertex at its placed position, unpainted vertices at 0."""
    positions, values = [], []
    for part in getattr(mesh, "submeshes", ()) or ():
        vertices = list(getattr(part, "vertices", ()) or ())
        paint = part_cloth_paint(part) or [0.0] * len(vertices)
        positions.extend(_apply_row_matrix(vertex, matrix) for vertex in vertices)
        values.extend(paint)
    return ClothPaintSamples(tuple(positions), tuple(values))


def apply_import_cloth_paint(result, mesh, matrix: Sequence[float]) -> bool:
    """Rewrite ``result.rebuilt_data`` from the import's paint; False when nothing is painted."""
    if not mesh_has_cloth_paint(mesh):
        return False
    if not (guides := decode_pac_cloth_guides(result.rebuilt_data)) or not guides.vertices:
        raise ValueError("The template has no cloth guides for the painted cloth to follow. Set Painted cloth to "
                         "\"Gets cloth guides of its own\", or choose a template with cloth.")
    samples = import_cloth_paint_samples(mesh, matrix)
    lows = [min(p[i] for p in samples.positions) for i in range(3)]
    highs = [max(p[i] for p in samples.positions) for i in range(3)]
    size = math.dist(lows, highs)
    data, report = apply_pac_cloth_paint(
        result.rebuilt_data, {}, default=samples,
        max_sample_distance=max(1e-5, size * SAMPLE_TOLERANCE))
    result.rebuilt_data = data
    result.cloth_paint_report = report
    result.summary_lines.append(
        f"Cloth paint: {report.cloth_vertices:,} vertices follow the template's {report.guide_count:,} cloth guides, "
        f"{report.rigid_vertices:,} follow bones only"
        + (f"; {report.reduced_vertices:,} reduced to four bones" if report.reduced_vertices else "")
        + (f"; {report.kept_template_parts} template part(s) not replaced by the import keep their own cloth"
           if report.kept_template_parts else "")
        + (f". Cloth parts: {', '.join(report.cloth_parts)}; cloth moves only where the template's material "
           "sidecar gives that part a cloth profile" if report.cloth_parts else "")
        + ". Not shown in the preview; test in game.")
    return True
