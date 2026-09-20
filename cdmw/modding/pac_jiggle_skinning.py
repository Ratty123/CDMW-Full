"""Read-only bone-to-render reference for game build 1.0.0.2944.

The caller resolves runtime buffers, rig maps and animation. This covers the
ordinary inverse-bind path and current-frame jiggle/wind blending, not special
LOD remapping, sample generation, stream-out packing or GPU-exact arithmetic.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence


def _matrix(value):
    if len(value) != 4 or any(len(row) != 4 for row in value):
        raise ValueError("Jiggle skinning requires a 4 by 4 row-major matrix.")
    rows = tuple(tuple(float(x) for x in row) for row in value)
    if any(not math.isfinite(x) for row in rows for x in row):
        raise ValueError("Jiggle skinning matrices must be finite.")
    return rows


def _entry(buffer, index):
    if type(index) is not int or not 0 <= index < len(buffer):
        raise ValueError("Jiggle skinning index refers outside its supplied runtime buffer.")
    return buffer[index]


def prepare_jiggle_bone_skinning(
    *, inverse_bind_matrix: Sequence[Sequence[float]],
    animation_matrix: Sequence[Sequence[float]],
    jiggle_matrix: Sequence[Sequence[float]] | None,
    character_space_scale: Sequence[float],
) -> dict:
    """Prepare one bone's ordinary and simulated matrices (ComputeSkinningMatrix2).

    This is the ordinary inverse-bind branch, including LOD0. The caller must
    resolve matching bones; the special cross-LOD inverse-variant correction
    is not implemented. Pass step_jiggle_bone's matrix when runtime jiggle is
    active, or None when disabled. Character scale multiplies the three basis
    rows before inverse-bind composition, leaving translation unchanged.

    Solver row0.w/row1.w are blend metadata. They move to the *ordinary* matrix
    after composition and must not contaminate either pose's homogeneous column.
    The result has skeletal_matrix and jiggle_matrix (None when disabled).
    """
    inverse = _matrix(inverse_bind_matrix)
    animation = _matrix(animation_matrix)
    jiggle = None if jiggle_matrix is None else _matrix(jiggle_matrix)
    if len(character_space_scale) != 3 or any(not math.isfinite(x) for x in character_space_scale):
        raise ValueError("Character-space bone scale must contain three finite values.")

    def compose(pose):
        scaled = tuple(tuple(pose[i][j] * character_space_scale[i] for j in range(3)) + (0.,)
                       for i in range(3)) + (pose[3],)
        return tuple(tuple(sum(inverse[i][k] * scaled[k][j] for k in range(4))
                           for j in range(4)) for i in range(4))

    skeletal = compose(animation)
    marker = float(jiggle is not None and jiggle[0][3] > 0)
    weight = 0. if jiggle is None else jiggle[1][3]
    skeletal = (skeletal[0][:3] + (marker,), skeletal[1][:3] + (weight,), *skeletal[2:])
    return {"skeletal_matrix": skeletal, "jiggle_matrix": None if jiggle is None else compose(jiggle)}


def _weighted_matrices(buffer, indices, weights):
    # The shader fetches every selected slot, including zero-weight slots.
    matrices = [_matrix(_entry(buffer, index)) for index in indices]
    # Byte weights are divided by 255, then normalized by their total. Only an
    # all-zero total reaches the shader's 1e-5 divisor clamp, yielding zeros.
    total = sum(weights) or 1
    return tuple(tuple(sum(matrix[i][j] * weight for matrix, weight in zip(matrices, weights)) / total
                       for j in range(4)) for i in range(4))


def blend_render_jiggle_matrix(
    data: bytes, offset: int, *, render_flags: int,
    bone_palette: Sequence[int], skinning_index_map: Sequence[int],
    skeletal_matrices: Sequence[Sequence[Sequence[float]]],
    jiggle_matrices: Sequence[Sequence[Sequence[float]]] | None,
    wind_weight: float = 0.,
    wind_samples: Sequence[Sequence[Sequence[float]]] | None = None,
) -> tuple[tuple[float, ...], ...]:
    """Blend one retained 40-byte PAC record before guide-cloth processing.

    Inputs are resolved buffer slices: PAC slot -> bone_palette -> original bone
    -> skinning_index_map -> ordinary/simulated matrix. None for jiggle_matrices
    represents a zero runtime jiggle-buffer offset; a PAC alone cannot establish
    activation. render_flags is the main-render-parameter flag, not PAC metadata.

    Ordinary mode uses six skeletal slots, reduced to four for guide-bound
    vertices or nonzero render_flags & 0xE00. Only the latter modes bypass jiggle.
    Blend overrides are weighted with the bone matrices before byte-38 selection;
    positive values above one extrapolate. Nonpositive values bypass jiggle.

    Positive wind_weight additionally requires the global sample buffer. Samples
    use 1024 | (original_bone & 255), before the skinning-index remap. Their basis
    premultiplies the blended jiggle basis; translation is added separately.
    Runtime wind/sample generation is not inferred or simulated here.

    The shader consumes four XYZ rows. The returned fourth column is canonical
    (0, 0, 0, 1), allowing direct use by blend_render_cloth_matrix. Blend metadata
    is already consumed. This function does not transform normals or pack output.
    """
    if type(offset) is not int or offset < 0 or offset + 40 > len(data):
        raise ValueError("Jiggle skinning requires a complete retained 40-byte PAC record.")
    if type(render_flags) is not int or not 0 <= render_flags <= 0xFFFFFFFF:
        raise ValueError("Render flags must be an unsigned 32-bit integer.")
    if not math.isfinite(wind_weight):
        raise ValueError("Jiggle wind weight must be finite.")
    ordinary_mode = (render_flags & 0xE00) == 0
    count = 6 if ordinary_mode and (data[offset + 39] & 63) == 63 else 4
    groups = struct.unpack_from('<2I', data, offset + 20)
    slots = tuple((group >> shift) & 1023 for group in groups for shift in (0, 10, 20))[:count]
    weights = tuple(data[offset + 28:offset + 28 + count])
    bones = tuple(_entry(bone_palette, slot) for slot in slots)
    indices = tuple(_entry(skinning_index_map, bone) for bone in bones)
    skeletal = _weighted_matrices(skeletal_matrices, indices, weights)
    vertex_blend = (1. - (data[offset + 38] & 15) / 15 if render_flags & 128
                    else 1. - data[offset + 38] / 255)
    blend = skeletal[1][3] if skeletal[0][3] > 0 else vertex_blend
    result = skeletal
    if ordinary_mode and jiggle_matrices is not None and blend > 0:
        jiggle = _weighted_matrices(jiggle_matrices, indices, weights)
        if wind_weight > 0:
            if wind_samples is None:
                raise ValueError("Active jiggle wind blending requires the runtime sample buffer.")
            sample = _weighted_matrices(wind_samples, tuple(1024 | (bone & 255) for bone in bones), weights)
            translation = tuple(jiggle[3][j] + sample[3][j] for j in range(3))
            basis = tuple(tuple(sum(sample[i][k] * jiggle[k][j] for k in range(3))
                                + sample[i][3] * translation[j] for j in range(3)) for i in range(3))
            wind = (*basis, translation)
            jiggle = tuple(tuple(jiggle[i][j] + wind_weight * (wind[i][j] - jiggle[i][j])
                                 for j in range(3)) for i in range(4))
        result = tuple(tuple(skeletal[i][j] + blend * (jiggle[i][j] - skeletal[i][j])
                             for j in range(3)) for i in range(4))
    return tuple((*row[:3], float(i == 3)) for i, row in enumerate(result))
