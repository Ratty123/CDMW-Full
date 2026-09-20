"""Reference preparation of cloth anchors, position blends and rotation neighbors.

This implements the traced mode-1 CPU preparation, not a time-stepping solver.
Runtime switches must be supplied explicitly. Python pow is not bit-exact powf.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from ._pbd_numeric import FLOAT32_MAX, f32, round_pbd_half
from .pac_cloth_guides import PacClothGuides, inspect_guide_attachment_candidates, inspect_guide_particle_initialization


def prepare_guide_cloth_attachments(
    guides: PacClothGuides, *, separate_components: bool,
    use_vertex_alpha_position_blending: bool, auto_weighting_enabled: bool,
    auto_weighting_exponential_base: float = 0.4,
    auto_weighting_input_ratio_shift: float = 0.0,
    particle_positions: Sequence[Sequence[float]] | None = None,
) -> dict:
    """Prepare initialized guide particles using explicitly selected settings.

    0x143CCD480 normalizes each component; 0x143CCDE90 uses the whole mesh.
    Distances are averaged before half upload. Degenerate distance ranges use
    one minus the initialized position blend and skip automatic weighting.
    A non-degenerate range can apply base**(10*(ratio+shift)) to dynamic blends.

    Neighbor selection compares *packed* ratios, preserving triangle order on
    ties. A vertex not referenced by a triangle has None, since no write was
    observed there. Unknown initial/runtime memory is not fabricated.
    """
    if any(type(value) is not bool for value in (
        separate_components, use_vertex_alpha_position_blending, auto_weighting_enabled,
    )):
        raise ValueError("Cloth preparation requires explicit boolean runtime switches.")
    base = f32(auto_weighting_exponential_base)
    shift = f32(auto_weighting_input_ratio_shift)
    candidates = inspect_guide_attachment_candidates(guides, particle_positions=particle_positions)
    scope = "by_connected_component" if separate_components else "whole_mesh"
    rows = candidates[scope]
    group_ids = candidates["component_ids"] if separate_components else [0] * len(rows)
    group_count = candidates["component_count"] if separate_components else 1
    minimums = [FLOAT32_MAX if separate_components else 100000.0] * group_count
    maximums = [0.0] * group_count
    means = []
    rest_lengths = []
    for row, group in zip(rows, group_ids, strict=True):
        lengths = row["rest_lengths_before_half_upload"]
        rest_lengths.append([round_pbd_half(value) for value in lengths])
        total = 0.0
        for length in lengths:
            total = f32(total + length)
        mean = f32(total / len(lengths)) if lengths else None
        means.append(mean)
        if mean is not None:
            minimums[group] = min(minimums[group], mean)
            maximums[group] = max(maximums[group], mean)

    initial = inspect_guide_particle_initialization(guides)
    key = "position_blend_with_vertex_alpha" if use_vertex_alpha_position_blending else "position_blend_without_vertex_alpha"
    blends = list(initial[key])
    ratios, auto_applied = [], []
    for index, group in enumerate(group_ids):
        low, high = minimums[group], maximums[group]
        if high <= low:
            ratios.append(round_pbd_half(f32(1.0 - blends[index])))
            continue
        mean = means[index] if means[index] is not None else high
        ratio = max(0.0, min(1.0, f32(f32(mean - low) / f32(high - low))))
        ratios.append(round_pbd_half(ratio))
        if not auto_weighting_enabled or guides.channel_b[index] == 255:
            continue
        exponent = f32(f32(ratio + shift) * 10.0)
        try:
            if base == 0 and exponent < 0:
                factor = -math.inf if math.copysign(1.0, base) < 0 and exponent % 2 == 1 else math.inf
            else:
                factor = math.pow(base, exponent)
        except ValueError as exc:
            raise ValueError("Automatic weighting has an unsupported non-real power result.") from exc
        except OverflowError:
            # Overflow is saturated immediately after powf in the CPU path.
            factor = -math.inf if base < 0 and exponent % 2 else math.inf
        factor = max(0.0, min(1.0, factor))
        factor = f32(factor)
        value = f32(blends[index] * factor) if use_vertex_alpha_position_blending else factor
        blends[index] = round_pbd_half(value)
        auto_applied.append(index)

    neighbors = [None] * len(rows)
    scores = [2.0] * len(rows)
    for a, b, c in guides.triangles:
        for vertex, first, second in ((a, b, c), (b, c, a), (c, a, b)):
            if scores[vertex] > ratios[first]:
                scores[vertex] = ratios[first]
                neighbors[vertex] = (first, second)
    return {
        "position_basis": candidates["position_basis"],
        "candidate_scope": scope,
        "use_vertex_alpha_position_blending": use_vertex_alpha_position_blending,
        "auto_weighting_enabled": auto_weighting_enabled,
        "auto_weighting_exponential_base": base,
        "auto_weighting_input_ratio_shift": shift,
        "anchor_indices": [row["guide_indices"] for row in rows],
        "anchor_rest_lengths": rest_lengths,
        "mean_anchor_distances": means,
        "long_range_ratios": ratios,
        "position_blends": blends,
        "auto_weighted_vertex_indices": auto_applied,
        "orientation_neighbor_indices": neighbors,
        "limitations": "Explicit mode-1 preparation scenario, not proof of active game settings. Positions precede skinning unless supplied. Float32/half operations are modeled; powf parity, runtime activation, collisions and solver motion are not established. Unreferenced orientation neighbors remain unknown.",
    }
