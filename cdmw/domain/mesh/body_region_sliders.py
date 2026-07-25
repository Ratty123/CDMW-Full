"""Generate morph sliders from segmented body regions.

The point of segmenting a body is to skip vertex painting: pick "left thigh"
and get sliders that already move the right surface, about the right pivot,
along the right axis. This turns a :class:`BodyRegionMap` into ready-to-use
:class:`MeshMorphDefinition` objects.

Every slider takes its weighted vertices, pivot, and local basis from the
region itself, so the falloff a slider applies is the feathered region weight
and the axis it works along is the region's own bone chain. Nothing here has to
know what a thigh is.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .body_regions import (
    BodyRegion,
    BodyRegionMap,
    body_region_local_basis,
    body_region_morph_selection,
)
from .morph import (
    MESH_MORPH_AXES,
    MESH_MORPH_RULES,
    MeshMorphDefinition,
    MeshMorphProfile,
    MeshMorphRule,
    mesh_morph_driver_topology_fingerprint,
)


BODY_REGION_SLIDER_PROFILE_PREFIX = "body_regions"


@dataclass(frozen=True, slots=True)
class BodyRegionSliderTemplate:
    """One slider to instantiate against every region."""

    slider_id: str
    label: str
    rule: str
    axis: str = "y"
    amount: float = 0.25
    minimum_percent: float = -100.0
    maximum_percent: float = 100.0

    def __post_init__(self) -> None:
        slider_id = str(self.slider_id or "").strip().lower()
        if not slider_id:
            raise ValueError("Body region slider template requires a slider_id.")
        if self.rule not in MESH_MORPH_RULES:
            raise ValueError(f"Unsupported morph rule for a region slider: {self.rule!r}")
        if self.axis not in MESH_MORPH_AXES:
            raise ValueError(f"Unsupported morph axis for a region slider: {self.axis!r}")
        if self.minimum_percent >= self.maximum_percent:
            raise ValueError("Body region slider range must be non-empty.")
        object.__setattr__(self, "slider_id", slider_id)
        object.__setattr__(self, "label", str(self.label or slider_id).strip() or slider_id)


# Y is the region's bone axis (see body_region_local_basis), so "scale" runs
# along the limb and "radius" across it. Amounts are the displacement at 100%,
# tuned so a slider at full travel is a strong but usable change.
DEFAULT_BODY_REGION_SLIDER_TEMPLATES: tuple[BodyRegionSliderTemplate, ...] = (
    BodyRegionSliderTemplate("size", "Size", "radius", "y", 0.30),
    BodyRegionSliderTemplate("length", "Length", "scale", "y", 0.25),
    BodyRegionSliderTemplate("taper", "Taper", "taper", "y", 0.30),
    BodyRegionSliderTemplate("flatten", "Flatten", "flatten", "y", 0.20),
    BodyRegionSliderTemplate("shift", "Shift", "move", "y", 0.02),
)


def build_region_slider_definitions(
    region: BodyRegion,
    templates: tuple[BodyRegionSliderTemplate, ...] = DEFAULT_BODY_REGION_SLIDER_TEMPLATES,
) -> tuple[MeshMorphDefinition, ...]:
    """Instantiate every template against one region.

    Returns nothing for a region with no vertices, and skips axis-driven
    sliders when the region has no usable axis — a rule that needs a direction
    would otherwise push the whole region along an arbitrary one.
    """

    if region.empty:
        return ()
    vertices = body_region_morph_selection(region)
    if not vertices:
        return ()
    basis = body_region_local_basis(region)
    axis_is_real = region.axis.length > 0.0 and region.axis.source != "default"
    definitions: list[MeshMorphDefinition] = []
    for template in templates:
        if not axis_is_real and template.rule != "volume":
            continue
        definitions.append(
            MeshMorphDefinition(
                definition_id=f"{region.region_id}_{template.slider_id}",
                label=f"{region.label} {template.label}",
                category=region.group,
                vertices=vertices,
                pivot=region.axis.origin,
                local_basis=basis,
                rule=MeshMorphRule(kind=template.rule, axis=template.axis, amount=template.amount),
                min_percent=template.minimum_percent,
                max_percent=template.maximum_percent,
            )
        )
    return tuple(definitions)


def build_region_slider_profile(
    mesh: object,
    region_map: BodyRegionMap,
    *,
    profile_id: str = "",
    name: str = "",
    templates: tuple[BodyRegionSliderTemplate, ...] = DEFAULT_BODY_REGION_SLIDER_TEMPLATES,
    region_ids: tuple[str, ...] = (),
) -> MeshMorphProfile:
    """Build one profile covering the map's regions, or just ``region_ids``.

    The fingerprint covers exactly the submeshes the definitions touch, because
    that is what the service compares against when activating. Using the whole
    map's fingerprint would make any region-scoped profile fail to activate:
    the map spans every submesh, a thigh profile only one.
    """

    wanted = {str(value).strip().lower() for value in region_ids}
    definitions: list[MeshMorphDefinition] = []
    for region in region_map.populated_regions:
        if wanted and region.region_id not in wanted:
            continue
        definitions.extend(build_region_slider_definitions(region, templates))
    identifier = _safe_identifier(profile_id) or _default_profile_id(region_map, wanted)
    fingerprint = (
        mesh_morph_driver_topology_fingerprint(mesh, definitions)
        if definitions
        else region_map.topology_fingerprint
    )
    return MeshMorphProfile(
        profile_id=identifier,
        name=str(name or "").strip() or "Body Region Sliders",
        topology_fingerprint=fingerprint,
        definitions=tuple(definitions),
    )


def _default_profile_id(region_map: BodyRegionMap, wanted: set[str]) -> str:
    """Fingerprint-suffixed, so profiles for different bodies never collide."""

    suffix = region_map.topology_fingerprint[:12] or "unknown"
    scope = "_".join(sorted(wanted))[:48] if wanted else ""
    parts = [BODY_REGION_SLIDER_PROFILE_PREFIX, scope, suffix]
    return "_".join(part for part in parts if part)


def _safe_identifier(value: object) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
