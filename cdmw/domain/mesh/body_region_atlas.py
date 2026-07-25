"""Pure presentation model for the body-region atlas.

Everything a region browser needs to draw itself and nothing about how it is
drawn: grouped rows, stable per-region colours, a readable summary, and the
diagnostics worth surfacing. Keeping this Qt-free means the parts that actually
carry logic — grouping, ordering, colour assignment, what counts as a warning —
are testable without a widget.

Colours are assigned here rather than by the view so a region keeps the same
colour in a list, a 3D overlay, and an exported OBJ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .body_regions import BODY_REGION_GROUPS, BodyRegionMap


Rgb = tuple[int, int, int]

# Distinct hues rather than a ramp: neighbouring regions must not read as the
# same colour. Assigned by sorted region id so a body always looks the same.
BODY_REGION_ATLAS_COLOURS: tuple[Rgb, ...] = (
    (229, 64, 64),
    (64, 153, 229),
    (89, 204, 89),
    (242, 179, 51),
    (179, 102, 229),
    (51, 204, 204),
    (242, 115, 191),
    (153, 140, 77),
    (115, 115, 242),
    (217, 140, 89),
    (102, 191, 153),
    (204, 204, 102),
)
UNCLAIMED_COLOUR: Rgb = (89, 89, 89)
HIGH_UNCLAIMED_WEIGHT = 0.05
"""Above this share of unclaimed skin the rule table needs attention."""


@dataclass(frozen=True, slots=True)
class BodyRegionAtlasRow:
    """One selectable region."""

    region_id: str
    label: str
    group: str
    side: str
    colour: Rgb
    vertex_count: int
    dominant_vertex_count: int
    bone_count: int
    axis_length: float
    axis_source: str

    @property
    def detail(self) -> str:
        millimetres = self.axis_length * 1000.0
        return f"{self.vertex_count:,} verts · {self.bone_count} bones · axis {millimetres:.0f} mm"

    @property
    def has_usable_axis(self) -> bool:
        """Axis-driven sliders need a real direction, not the fallback."""

        return self.axis_length > 0.0 and self.axis_source not in ("default", "degenerate")


@dataclass(frozen=True, slots=True)
class BodyRegionAtlasGroup:
    """Regions under one heading, in display order."""

    name: str
    rows: tuple[BodyRegionAtlasRow, ...] = ()

    @property
    def vertex_count(self) -> int:
        return sum(row.vertex_count for row in self.rows)


@dataclass(frozen=True, slots=True)
class BodyRegionAtlas:
    """Everything the atlas view renders."""

    groups: tuple[BodyRegionAtlasGroup, ...] = ()
    summary: str = ""
    warnings: tuple[str, ...] = ()
    unmapped_bone_names: tuple[str, ...] = ()

    @property
    def rows(self) -> tuple[BodyRegionAtlasRow, ...]:
        return tuple(row for group in self.groups for row in group.rows)

    @property
    def empty(self) -> bool:
        return not self.rows

    def row(self, region_id: object) -> BodyRegionAtlasRow | None:
        wanted = str(region_id or "").strip().lower()
        return next((row for row in self.rows if row.region_id == wanted), None)

    def colour_for(self, region_id: object) -> Rgb:
        row = self.row(region_id)
        return row.colour if row is not None else UNCLAIMED_COLOUR


def build_body_region_atlas(region_map: BodyRegionMap) -> BodyRegionAtlas:
    """Turn a region map into grouped, coloured, selectable rows."""

    populated = region_map.populated_regions
    colours = _colours_by_region(populated)
    groups: list[BodyRegionAtlasGroup] = []
    for name in BODY_REGION_GROUPS:
        rows = tuple(
            BodyRegionAtlasRow(
                region_id=region.region_id,
                label=region.label,
                group=region.group,
                side=region.side,
                colour=colours[region.region_id],
                vertex_count=region.vertex_count,
                dominant_vertex_count=region.dominant_vertex_count,
                bone_count=len(region.bone_indices),
                axis_length=region.axis.length,
                axis_source=region.axis.source,
            )
            for region in populated
            if region.group == name
        )
        if rows:
            groups.append(BodyRegionAtlasGroup(name=name, rows=rows))
    return BodyRegionAtlas(
        groups=tuple(groups),
        summary=_summary(region_map, sum(len(group.rows) for group in groups)),
        warnings=_warnings(region_map, groups),
        unmapped_bone_names=region_map.unmapped_bone_names,
    )


def _colours_by_region(regions: Sequence[object]) -> dict[str, Rgb]:
    # Sorted, not map order, so adding a region does not recolour the others.
    identifiers = sorted(str(getattr(region, "region_id", "")) for region in regions)
    return {
        region_id: BODY_REGION_ATLAS_COLOURS[index % len(BODY_REGION_ATLAS_COLOURS)]
        for index, region_id in enumerate(identifiers)
    }


def _summary(region_map: BodyRegionMap, region_count: int) -> str:
    if not region_count:
        return "No body regions were resolved."
    claimed = (1.0 - region_map.unmapped_weight_fraction) * 100.0
    return (
        f"{region_count} regions · {region_map.skinned_vertex_count:,} skinned vertices · "
        f"{claimed:.1f}% of skin weight claimed"
    )


def _warnings(region_map: BodyRegionMap, groups: Sequence[BodyRegionAtlasGroup]) -> tuple[str, ...]:
    warnings: list[str] = []
    if not groups:
        warnings.append(
            "No regions resolved. The body needs its matching skeleton, and a PAC also "
            "needs its bone palette resolved before slots can be named."
        )
    if region_map.unskinned_vertex_count:
        warnings.append(
            f"{region_map.unskinned_vertex_count:,} vertices carry no skin weights and "
            "belong to no region."
        )
    if region_map.unmapped_weight_fraction > HIGH_UNCLAIMED_WEIGHT:
        warnings.append(
            f"{region_map.unmapped_weight_fraction * 100.0:.1f}% of skin weight sits on bones "
            "no region rule claims; sliders will not reach that surface."
        )
    for row in (row for group in groups for row in group.rows):
        if not row.has_usable_axis:
            warnings.append(
                f"{row.label} has no usable bone axis, so only volume sliders can be built for it."
            )
    return tuple(warnings)
