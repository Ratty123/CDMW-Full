"""Read-only reference for the traced guide-to-render skinning handoff.

The caller supplies animation frames and the ordinary skeletal/jiggle matrix.
This implements their composition, not the solver that produces those inputs.
Calculations use Python floats, not bit-exact GPU float/half arithmetic.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from .pac_cloth_guides import PacClothGuides


def _matrix4(value: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    if len(value) != 4 or any(len(row) != 4 for row in value):
        raise ValueError("Cloth skinning requires a 4 by 4 row-major matrix.")
    rows = tuple(tuple(float(component) for component in row) for row in value)
    if any(not math.isfinite(component) for row in rows for component in row):
        raise ValueError("Cloth skinning matrices must be finite.")
    return rows


def prepare_guide_skinning_matrices(
    guides: PacClothGuides, animation_frames: Sequence[Sequence[Sequence[float]]],
) -> tuple[tuple[tuple[float, ...], ...], ...]:
    """Convert one animated frame per guide using ComputeGuideMeshPrepareSkinning.

    Frames and guide positions share PAC model coordinates. Row 3 contains the
    animated guide position. The original guide position is subtracted through
    the frame, so points rotate about their guide rather than the model origin.
    Use shader-decoded guide positions, not the separate CPU initialization view.
    The fourth column contains metadata and must be preserved, not treated as
    conventional homogeneous coordinates. In particular, row 0.w scales the
    render vertex's skeletal blend in the subsequent stream-out shader.
    """
    if len(animation_frames) != len(guides.vertices):
        raise ValueError("Cloth skinning requires one animation frame per guide.")
    result = []
    for rest, frame in zip(guides.vertices, animation_frames, strict=True):
        if len(rest) != 3 or any(not math.isfinite(value) for value in rest):
            raise ValueError("Cloth guide positions must be finite three-component points.")
        matrix = _matrix4(frame)
        translation = tuple(matrix[3][j] - sum(rest[i] * matrix[i][j] for i in range(3))
                            for j in range(4))
        result.append((*matrix[:3], translation))
    return tuple(result)


def blend_render_cloth_matrix(
    data: bytes, offset: int, *, skeletal_matrix: Sequence[Sequence[float]],
    guide_matrices: Sequence[Sequence[Sequence[float]]],
) -> tuple[tuple[float, float, float], ...]:
    """Return the four XYZ rows used to deform a retained PAC render vertex.

    The ordinary matrix already includes skeletal/jiggle processing. Guide
    matrices must be prepared and local to this PAC. A byte-39 low-six value of
    63 bypasses guide access. Otherwise an active guide buffer and a valid
    retained binding are required, including all four indices at zero weight.
    Missing runtime buffers are not emulated. Zero guide totals produce a zero
    matrix on the active guide path, whose singular normal basis is unusable.

    For a model point p, result = p.x*row0 + p.y*row1 + p.z*row2 + row3.
    Normals require the inverse transpose of the resulting 3 by 3 basis; this
    function does not interpolate normals or emulate stream-out packing.
    """
    skeletal = _matrix4(skeletal_matrix)
    binding = decode_pac_cloth_binding(data, offset)
    if binding is None:
        return tuple(row[:3] for row in skeletal)
    blend, indices, weights = binding
    if any(index >= len(guide_matrices) for index in indices):
        raise ValueError("A render cloth binding refers outside this PAC's guide matrices.")
    matrices = [_matrix4(guide_matrices[index]) for index in indices]
    # The shader clamps its divisor above zero. With byte weights, only an
    # all-zero total reaches that clamp; every numerator is then zero too.
    total = sum(weights) or 1
    # Guide-bone weights use /255 without normalization. These *render-to-guide*
    # weights are normalized by their total in both traced stream-out variants.
    runtime_blend = sum(matrix[0][3] * weight for matrix, weight in zip(matrices, weights)) / total
    skeletal_blend = blend / 63 * runtime_blend
    result = []
    for i in range(4):
        guide = [sum(matrix[i][j] * weight for matrix, weight in zip(matrices, weights)) / total
                 for j in range(3)]
        result.append(tuple(guide[j] + skeletal_blend * (skeletal[i][j] - guide[j]) for j in range(3)))
    return tuple(result)


def inspect_render_cloth_bindings(data: bytes, guides: PacClothGuides) -> dict:
    """Report actual stored-LOD bindings without assuming runtime activation.

    Invalid rows remain visible as counts and bounded source-offset samples;
    they do not invalidate independently decoded guide geometry. Zero totals
    are reported separately; they remain excluded by the editing guards.
    """
    try:
        levels = pac_cloth_lods(data)
    except ValueError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    lods = []
    invalid_total = 0
    for lod, mesh in enumerate(levels):
        parts = []
        for part_index, part in enumerate(mesh.submeshes):
            bound = bypass = invalid = zero_guide = zero_skeletal = 0
            fetched, weighted, weight_sums, blend_values = set(), set(), set(), set()
            errors = []
            for vertex, offset in enumerate(part.source_vertex_offsets):
                try:
                    binding = decode_pac_cloth_binding(data, offset)
                    if binding is None:
                        bypass += 1
                        continue
                    blend, indices, weights = binding
                    if any(index >= len(guides.vertices) for index in indices):
                        raise ValueError("Cloth-guide index exceeds this PAC's guide count, including zero-weight slots.")
                except ValueError as exc:
                    invalid += 1
                    if len(errors) < 8:
                        errors.append({"vertex": vertex, "source_offset": offset, "reason": str(exc)})
                    continue
                bound += 1
                zero_guide += not sum(weights)
                zero_skeletal += not sum(data[offset + 28:offset + 32])
                fetched.update(indices)
                weighted.update(index for index, weight in zip(indices, weights) if weight)
                weight_sums.add(sum(weights))
                blend_values.add(blend)
            invalid_total += invalid
            parts.append({"part": part_index, "name": part.name, "vertex_count": len(part.vertices),
                          "bound_vertex_count": bound, "bypass_vertex_count": bypass,
                          "invalid_vertex_count": invalid, "invalid_examples": errors,
                          "zero_guide_weight_vertex_count": zero_guide,
                          "zero_skeletal_weight_vertex_count": zero_skeletal,
                          "fetched_guide_indices": sorted(fetched), "weighted_guide_indices": sorted(weighted),
                          "guide_weight_sums": sorted(weight_sums), "skeletal_blend_values": sorted(blend_values)})
        lods.append({"lod": lod, "parts": parts})
    return {"status": "invalid_bindings" if invalid_total else "decoded", "lods": lods,
            "invalid_vertex_count": invalid_total,
            "limitations": "Bindings require an active runtime guide buffer. Byte 39's low six bits are multiplied by a weighted guide-matrix runtime factor; stored values alone do not establish final cloth influence."}
