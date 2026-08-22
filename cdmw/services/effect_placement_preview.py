"""Place an effect on an item in the .NET viewport: a small anchor mesh the gizmo moves.
The game draws a grafted effect at the weapon's origin, transformed by the
``_offsetTransform`` the studio writes (a uniform scale and an offset). This module
packages a small anchor (an octahedron a few centimetres across, at the effect's
origin) as the editable mesh for the resident .NET viewport, with the item's own
mesh as the reference: the viewport's placement gizmo moves and scales the anchor,
the particle layer draws the effect's approximate reading around it (see
:mod:`cdmw.services.effect_preview_model`), and every drag comes back as a delta
the studio adds to its offset and scale. What the effect *spans* (its reach, from
`EffectData._boundingBoxMin/Max`) travels along as numbers for the dialog's text;
it is not drawn, since a box the size of the reach hides the item.
The scene is the item's frame: the weapon's origin is the hand, +z toward the
pommel, the blade toward -z; a helm sits at head height. The anchor is authored at
scale 1.0 at the effect's own origin, so the placement transform the viewport
applies is exactly the ``_offsetTransform`` the game will.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Sequence, Tuple

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

if TYPE_CHECKING:
    from cdmw.services.effect_preview_model import EffectPreview

__all__ = [
    "EFFECT_ANCHOR_MATERIAL",
    "EFFECT_ANCHOR_RADIUS",
    "EFFECT_ANCHOR_SUBMESH",
    "EFFECT_AXIS_MATERIALS",
    "EFFECT_AXIS_TINTS",
    "EFFECT_REACH_MATERIAL",
    "EFFECT_REACH_SUBMESH",
    "anchor_axis_triad",
    "reach_cage_mesh",
    "EFFECT_PREVIEW_FILE",
    "EFFECT_TEXTURE_DIR",
    "EffectPlacementPreview",
    "anchor_mesh",
    "build_effect_placement_package",
    "framing_bounds_for",
    "mesh_names_textures",
    "next_scale",
    "write_effect_preview",
]

Vec3 = Tuple[float, float, float]
EFFECT_ANCHOR_SUBMESH = "effect_anchor"
EFFECT_ANCHOR_MATERIAL = "effect_anchor"
#: half the anchor's width, metres: a marker, small enough never to hide the item
EFFECT_ANCHOR_RADIUS = 0.015


EFFECT_REACH_SUBMESH = "effect_reach"
EFFECT_REACH_MATERIAL = "effect_reach"
#: a floor on the reach's extent, so an effect that reports none still shows a frame
_MIN_EXTENT = 0.05


def _bar(low: Vec3, high: Vec3, vertices: list, normals: list, uvs: list, faces: list) -> None:
    """One axis-aligned box between `low` and `high`, appended to the buffers."""

    x0, y0, z0 = low
    x1, y1, z1 = high
    corners = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    sides = (
        ((0, 1, 2, 3), (0.0, 0.0, -1.0)), ((5, 4, 7, 6), (0.0, 0.0, 1.0)),
        ((4, 0, 3, 7), (-1.0, 0.0, 0.0)), ((1, 5, 6, 2), (1.0, 0.0, 0.0)),
        ((4, 5, 1, 0), (0.0, -1.0, 0.0)), ((3, 2, 6, 7), (0.0, 1.0, 0.0)),
    )
    for quad, normal in sides:
        base = len(vertices)
        for corner in quad:
            vertices.append(corners[corner])
            normals.append(normal)
        uvs.extend([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        faces.append((base, base + 1, base + 2))
        faces.append((base, base + 2, base + 3))


def _strut(start: Vec3, end: Vec3, half: float, vertices: list, normals: list, uvs: list, faces: list) -> None:
    """One square bar from `start` to `end`, in any direction. `_bar` takes the corners of
    an axis-aligned box, so a limb drawn with it comes out as the slab that box would be;
    this one is built along its own axis and stays a limb."""

    import math

    direction = tuple(float(end[axis]) - float(start[axis]) for axis in range(3))
    length = math.sqrt(sum(value * value for value in direction))
    if length < 1e-9:
        return
    forward = tuple(value / length for value in direction)
    # any axis that is not the bar's own gives a usable pair of side directions
    aside = (0.0, 0.0, 1.0) if abs(forward[1]) > 0.9 else (0.0, 1.0, 0.0)
    right = (
        forward[1] * aside[2] - forward[2] * aside[1],
        forward[2] * aside[0] - forward[0] * aside[2],
        forward[0] * aside[1] - forward[1] * aside[0],
    )
    scale = math.sqrt(sum(value * value for value in right)) or 1.0
    right = tuple(value / scale for value in right)
    up = (
        right[1] * forward[2] - right[2] * forward[1],
        right[2] * forward[0] - right[0] * forward[2],
        right[0] * forward[1] - right[1] * forward[0],
    )
    corners = []
    for end_point in (start, end):
        for sign_right, sign_up in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corners.append(tuple(
                float(end_point[axis]) + sign_right * half * right[axis] + sign_up * half * up[axis]
                for axis in range(3)
            ))
    sides = (
        ((0, 1, 2, 3), tuple(-value for value in forward)),
        ((5, 4, 7, 6), forward),
        ((4, 0, 3, 7), tuple(-value for value in right)),
        ((1, 5, 6, 2), right),
        ((4, 5, 1, 0), tuple(-value for value in up)),
        ((3, 2, 6, 7), up),
    )
    for quad, normal in sides:
        base = len(vertices)
        for corner in quad:
            vertices.append(corners[corner])
            normals.append(normal)
        uvs.extend([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        faces.append((base, base + 1, base + 2))
        faces.append((base, base + 2, base + 3))


#: How much of each edge a corner bracket keeps. An eighth from each end leaves a quarter
#: of the box drawn and every corner stated twice over, once along each axis meeting there.
_REACH_CORNER_FRACTION = 0.125


def reach_cage_mesh(box_min: Vec3, box_max: Vec3, *, name: str = EFFECT_REACH_SUBMESH) -> ParsedMesh:
    """The effect's reach as twelve thin bars along the edges of its bounding box: an
    outline the reader can see through, drawn at scale 1.0 in the effect's own frame, so
    the placement transform moves and scales it with the anchor. A solid box would hide
    the item; a wire display mode would flatten everything else to wire."""

    low = [float(v) for v in box_min]
    high = [float(v) for v in box_max]
    for axis in range(3):
        if high[axis] - low[axis] < _MIN_EXTENT:
            centre = (high[axis] + low[axis]) / 2.0
            low[axis], high[axis] = centre - _MIN_EXTENT / 2.0, centre + _MIN_EXTENT / 2.0
    span = max(high[axis] - low[axis] for axis in range(3))
    thickness = max(0.003, span * 0.003)
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    uvs: list[Tuple[float, float]] = []
    faces: list[Tuple[int, int, int]] = []
    for axis in range(3):
        other = [index for index in range(3) if index != axis]
        length = high[axis] - low[axis]
        # Corner brackets, not whole edges. Twelve full bars around a boss effect's reach
        # is a cage the item sits inside and the reader looks through; the same box drawn
        # as eight corners says where it ends with a fraction of the ink, which is what
        # the frame is for. Short reaches keep more of each edge so the shape still reads.
        bracket = max(_MIN_EXTENT, length * _REACH_CORNER_FRACTION)
        for first in (low[other[0]], high[other[0]]):
            for second in (low[other[1]], high[other[1]]):
                for span_low, span_high in (
                    (low[axis], min(high[axis], low[axis] + bracket)),
                    (max(low[axis], high[axis] - bracket), high[axis]),
                ):
                    if span_high - span_low <= 0.0:
                        continue
                    bar_low = [0.0, 0.0, 0.0]
                    bar_high = [0.0, 0.0, 0.0]
                    bar_low[axis], bar_high[axis] = span_low, span_high
                    bar_low[other[0]], bar_high[other[0]] = first - thickness, first + thickness
                    bar_low[other[1]], bar_high[other[1]] = second - thickness, second + thickness
                    _bar(tuple(bar_low), tuple(bar_high), vertices, normals, uvs, faces)  # type: ignore[arg-type]
    submesh = SubMesh(
        name=name, material=EFFECT_REACH_MATERIAL, vertices=vertices, uvs=uvs, normals=normals, faces=faces,
        vertex_count=len(vertices), face_count=len(faces),
    )
    return ParsedMesh(path=f"{name}.reach", format="reach", submeshes=[submesh], bbox_min=tuple(low), bbox_max=tuple(high),  # type: ignore[arg-type]
                      total_vertices=len(vertices), total_faces=len(faces), has_uvs=True, has_bones=False)


#: What a submesh cut from the game's own character is named, so the material pass tints
#: it like the stand-in figure. Taken from the module that names them rather than spelled
#: again here: two copies of the string would let a rename draw the character black.
from cdmw.services.effect_character_reference import CHARACTER_SUBMESH_PREFIX as CHARACTER_MATERIAL_PREFIX  # noqa: E402

EFFECT_BODY_SUBMESH = "effect_body"
EFFECT_BODY_MATERIAL = "effect_body"

#: Where a weapon's own origin sits on the character holding it: the hand, about a metre
#: off the ground, with the body a little behind it and the character facing -z. The
#: numbers are the shipped characters' proportions to the nearest few centimetres, which is
#: all a scale reference needs to be -- the question it answers is whether an effect is the
#: size of a blade, an arm, or a house.
BODY_GROUND_Y = -1.05
BODY_HEAD_TOP_Y = 0.70
BODY_BEHIND_Z = 0.22


def character_reference_mesh(*, name: str = EFFECT_BODY_SUBMESH) -> ParsedMesh:
    """A person, at the size the game's characters are, as a cage of thin bars.

    An effect's reach in metres means very little on its own: everything looks either
    enormous or invisible next to a one-metre sword floating in the dark. Next to a body it
    reads immediately, and a cage of bars does it without hiding anything behind it.
    """

    ground, top = BODY_GROUND_Y, BODY_HEAD_TOP_Y
    hip = ground + 0.90
    shoulder = top - 0.30
    chin = top - 0.20
    z = BODY_BEHIND_Z
    vertices: list = []
    normals: list = []
    uvs: list = []
    faces: list = []

    def bar(start: Vec3, end: Vec3, half: float = 0.026) -> None:
        _strut(start, end, half, vertices, normals, uvs, faces)

    # the weapon arm reaches down and forward to the hand at the origin, which is where
    # the item -- and the effect on it -- is drawn
    bar((0.0, hip, z), (0.0, shoulder, z), 0.055)                      # torso
    bar((-0.20, shoulder, z), (0.20, shoulder, z), 0.032)              # shoulders
    bar((-0.15, hip, z), (0.15, hip, z), 0.038)                        # hips
    bar((-0.15, hip, z), (-0.11, ground, z))                           # left leg
    bar((0.15, hip, z), (0.11, ground, z))                             # right leg
    bar((0.20, shoulder, z), (0.27, shoulder - 0.28, z - 0.02), 0.024)  # upper arm, weapon side
    bar((0.27, shoulder - 0.28, z - 0.02), (0.04, 0.02, 0.06), 0.022)   # forearm, down to the hand
    bar((-0.20, shoulder, z), (-0.24, shoulder - 0.28, z), 0.024)       # other upper arm
    bar((-0.24, shoulder - 0.28, z), (-0.20, hip + 0.02, z), 0.022)     # other forearm
    bar((0.0, shoulder, z), (0.0, chin, z), 0.030)                      # neck
    bar((0.0, chin, z), (0.0, top, z), 0.085)                           # head
    for corner_x, corner_z in ((-0.32, -0.32), (0.32, -0.32), (0.32, 0.32), (-0.32, 0.32)):
        following = {(-0.32, -0.32): (0.32, -0.32), (0.32, -0.32): (0.32, 0.32),
                     (0.32, 0.32): (-0.32, 0.32), (-0.32, 0.32): (-0.32, -0.32)}[(corner_x, corner_z)]
        bar((corner_x, ground, z + corner_z), (following[0], ground, z + following[1]), 0.010)

    submesh = SubMesh(
        name=name, material=EFFECT_BODY_MATERIAL, vertices=vertices, uvs=uvs, normals=normals, faces=faces,
        vertex_count=len(vertices), face_count=len(faces),
    )
    return ParsedMesh(
        path=f"{name}.body", format="body", submeshes=[submesh],
        bbox_min=(-0.33, ground, z - 0.33), bbox_max=(0.33, top, z + 0.33),
        total_vertices=len(vertices), total_faces=len(faces), has_uvs=True, has_bones=False,
    )


def anchor_mesh(radius: float = EFFECT_ANCHOR_RADIUS, *, name: str = EFFECT_ANCHOR_SUBMESH) -> ParsedMesh:
    """A small octahedron at the origin (effect-local metres, scale 1.0): the editable
    mesh the gizmo hangs on, with flat faces so it reads as a solid marker."""

    r = max(0.001, float(radius))
    tips = [(r, 0.0, 0.0), (-r, 0.0, 0.0), (0.0, r, 0.0), (0.0, -r, 0.0), (0.0, 0.0, r), (0.0, 0.0, -r)]
    # each face its own three vertices: +x/-x with +y/-y with +z/-z corners, outward normals
    triangles = []
    for sx in (0, 1):
        for sy in (2, 3):
            for sz in (4, 5):
                a, b, c = tips[sx], tips[sy], tips[sz]
                # order so the normal points away from the origin
                normal = (
                    (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
                    (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
                    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]),
                )
                centre = tuple((a[i] + b[i] + c[i]) / 3.0 for i in range(3))
                if sum(normal[i] * centre[i] for i in range(3)) < 0:
                    b, c = c, b
                    normal = tuple(-v for v in normal)
                triangles.append(((a, b, c), normal))
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    uvs: list[Tuple[float, float]] = []
    faces: list[Tuple[int, int, int]] = []
    for (a, b, c), normal in triangles:
        length = sum(v * v for v in normal) ** 0.5 or 1.0
        unit = tuple(v / length for v in normal)
        base = len(vertices)
        vertices.extend([a, b, c])
        normals.extend([unit, unit, unit])
        uvs.extend([(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)])
        faces.append((base, base + 1, base + 2))
    submesh = SubMesh(
        name=name, material=EFFECT_ANCHOR_MATERIAL, vertices=vertices, uvs=uvs, normals=normals, faces=faces,
        vertex_count=len(vertices), face_count=len(faces),
    )
    return ParsedMesh(path=f"{name}.anchor", format="anchor", submeshes=[submesh], bbox_min=(-r, -r, -r), bbox_max=(r, r, r),
                      total_vertices=len(vertices), total_faces=len(faces), has_uvs=True, has_bones=False)


#: The anchor's axis bars, in the placement gizmo's own axis colours (x red, y green,
#: z blue; `GizmoAppearance.Default` as linear tints). An octahedron is the same shape
#: from every side, so without these a rotation is invisible on the anchor itself.
EFFECT_AXIS_MATERIALS: tuple = ("effect_anchor_axis_x", "effect_anchor_axis_y", "effect_anchor_axis_z")
EFFECT_AXIS_TINTS: tuple = ((0.84, 0.07, 0.07), (0.08, 0.72, 0.14), (0.07, 0.29, 1.0))


def anchor_axis_triad(radius: float = EFFECT_ANCHOR_RADIUS) -> Tuple[SubMesh, SubMesh, SubMesh]:
    """Three short bars from the anchor along the effect's own +x, +y and +z, one
    submesh each so the tint pass can colour them apart. They turn with the placement,
    which is what makes a rotation readable at a glance."""

    r = max(0.001, float(radius))
    length, half = r * 3.2, r * 0.16
    out = []
    for axis, material in enumerate(EFFECT_AXIS_MATERIALS):
        vertices: list[Vec3] = []
        normals: list[Vec3] = []
        uvs: list[Tuple[float, float]] = []
        faces: list[Tuple[int, int, int]] = []
        end = tuple(length if index == axis else 0.0 for index in range(3))
        _strut((0.0, 0.0, 0.0), end, half, vertices, normals, uvs, faces)  # type: ignore[arg-type]
        out.append(SubMesh(
            name=material, material=material, vertices=vertices, uvs=uvs, normals=normals, faces=faces,
            vertex_count=len(vertices), face_count=len(faces),
        ))
    return tuple(out)  # type: ignore[return-value]


def next_scale(current: float, delta: Sequence[float]) -> float:
    """The uniform effect scale after a gizmo scale drag reported as a per-axis delta:
    the mean of the three, clamped to the studio's range."""

    values = [float(v) for v in delta][:3] or [0.0]
    mean = sum(values) / len(values)
    return max(0.01, min(10.0, float(current) + mean))


#: the anchor's colour: orange, opaque, so it reads as a handle and not as part of the item
ANCHOR_TINT = (1.0, 0.45, 0.1)
#: the reach cage's colour: the same family, dimmer, so it reads as a frame around the effect
#: The reach frame is not the anchor and must not read as it: a dimmer shade of the same
#: orange left the reader asking which of the two orange things they were meant to drag,
#: and it competed with the particles, which are warm by nature. A cool blue is none of
#: those things.
REACH_TINT = (0.28, 0.52, 0.78)
#: the item's colour: a light neutral, because the package builder leaves its materials
#: without a texture or a base colour and the renderer draws that as a black body
ITEM_TINT = (0.62, 0.64, 0.67)
#: the body reference's colour: dim and cool, so it reads as background against the item
BODY_TINT = (0.20, 0.23, 0.28)


def _tint_anchor_material(materials_path: Path) -> None:
    """Colour the package's materials: the anchor orange, the reach cage a dimmer orange,
    and the item itself a light neutral grey.

    The item's own materials come out of the package builder with no texture and no base
    colour, which the renderer draws as a black body: on the viewport's dark background
    that is an invisible sword with a rim of specular. Best effort: a package whose
    materials file is missing or unreadable keeps what the builder wrote.
    """

    import json

    try:
        payload = json.loads(materials_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    changed = False
    for item in payload.get("submeshes", ()):
        if not isinstance(item, dict):
            continue
        material = str(item.get("material", ""))
        item["alpha_mode"] = "opaque"
        item["opacity_factor"] = 1.0
        parameters = dict(item.get("parameters", {}) or {})
        if material == EFFECT_BODY_MATERIAL or material.startswith(CHARACTER_MATERIAL_PREFIX):
            item["double_sided"] = True
            parameters.update({"base_tint_color": list(BODY_TINT), "base_tint_strength": 1.0, "roughness": 0.9, "metalness": 0.0})
        elif material == EFFECT_ANCHOR_MATERIAL:
            item["double_sided"] = True
            parameters.update({"base_tint_color": list(ANCHOR_TINT), "base_tint_strength": 1.0, "roughness": 0.6, "metalness": 0.0})
        elif material == EFFECT_REACH_MATERIAL:
            item["double_sided"] = True
            parameters.update({"base_tint_color": list(REACH_TINT), "base_tint_strength": 1.0, "roughness": 0.6, "metalness": 0.0})
        elif material in EFFECT_AXIS_MATERIALS:
            item["double_sided"] = True
            tint = EFFECT_AXIS_TINTS[EFFECT_AXIS_MATERIALS.index(material)]
            parameters.update({"base_tint_color": list(tint), "base_tint_strength": 1.0, "roughness": 0.6, "metalness": 0.0})
        elif str(item.get("texture", "") or "").strip():
            # it has textures of its own: tinting them would be painting over the thing the
            # reader came to look at
            parameters.update({"roughness": 0.55, "metalness": 0.0})
        else:
            parameters.update({"base_tint_color": list(ITEM_TINT), "base_tint_strength": 1.0, "roughness": 0.55, "metalness": 0.0})
        item["parameters"] = parameters
        changed = True
    if changed:
        materials_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _frame_scene_on_the_item(scene_path: Path, low: Vec3, high: Vec3) -> None:
    """Make the scene's framing bounds the item's, not the whole scene's.

    The builder frames on everything it was given, and what it was given includes the
    effect's reach cage. Effects made for bosses reach twenty metres, so the scene's
    extent became twenty metres, and the viewport took that as the size of the world:
    the camera opened on an empty box with the item a speck in the middle, the ground
    grid drew squares two metres wide, and the placement gizmo -- whose arms are a
    fifth of the scene -- reached four metres past the edges of the view, which left
    nothing to grab. The item is the subject here whatever the effect does around it.
    """

    import json

    try:
        payload = json.loads(scene_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    minimum = [float(low[axis]) for axis in range(3)]
    maximum = [float(high[axis]) for axis in range(3)]
    extent = max(0.01, max(maximum[axis] - minimum[axis] for axis in range(3)))
    bounds = {
        "min": minimum,
        "max": maximum,
        "center": [(minimum[axis] + maximum[axis]) * 0.5 for axis in range(3)],
    }
    payload["bounds"] = bounds
    payload["framing"] = {"bounds": bounds, "extent": extent}
    grid = payload.get("grid")
    if isinstance(grid, dict):
        grid["spacing"] = max(extent / 10.0, 0.01)
    scene_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def framing_bounds_for(
    item_mesh: ParsedMesh, *, include_body: bool = True, body_mesh: Optional[ParsedMesh] = None
) -> Tuple[Vec3, Vec3]:
    """What the view opens on: the item, the character standing behind it when one is
    drawn, and the item's origin -- the hand, where the effect starts -- so the anchor is
    in frame even on an item modelled away from it. Not the effect's reach: that is the
    thing being judged, and a view that had to hold twenty metres of it would show the
    item as a speck."""

    low = tuple(float(value) for value in (getattr(item_mesh, "bbox_min", None) or (-0.5, -0.5, -0.5)))
    high = tuple(float(value) for value in (getattr(item_mesh, "bbox_max", None) or (0.5, 0.5, 0.5)))
    if all(abs(high[axis] - low[axis]) < 1e-6 for axis in range(3)):
        low, high = (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)
    corners = [low, high, (0.0, 0.0, 0.0)]
    if include_body:
        body = body_mesh if body_mesh is not None else character_reference_mesh()
        corners.extend((body.bbox_min, body.bbox_max))
    return (
        tuple(min(float(corner[axis]) for corner in corners) for axis in range(3)),  # type: ignore[return-value]
        tuple(max(float(corner[axis]) for corner in corners) for axis in range(3)),  # type: ignore[return-value]
    )


@dataclass(frozen=True, slots=True)
class EffectPlacementPreview:
    """A built package: where it is, which submesh is the anchor, which is the reach cage,
    the item's frame, and the effect's reach (`box_min`/`box_max`, effect-local metres at
    scale 1.0)."""

    package_dir: Path
    box_submesh_index: int
    item_submesh_count: int
    box_min: Vec3
    box_max: Vec3
    #: the submesh the reach cage is (the editable role's second part)
    reach_submesh_index: int = 1
    #: first scene submesh of the body drawn for scale, or -1 when the package carries none
    body_submesh_index: int = -1
    #: how many submeshes the body is: one for the stand-in figure, several for the
    #: game's own character, which is worn armour in pieces
    body_submesh_count: int = 1
    #: `effect_preview.json` in the package when the caller gave an effect preview, else None
    preview_file: Optional[Path] = None
    #: archive texture paths the package could not carry (no reader, or the reader had none)
    missing_textures: Tuple[str, ...] = ()
    #: the 3x3 the item was turned by to join the character, or None when the scene is the
    #: item's own frame; an offset in the item's frame reaches the scene through it
    item_rotation: Optional[Tuple[float, ...]] = None

    @property
    def body_submesh_indices(self) -> Tuple[int, ...]:
        """Every scene submesh the body occupies, empty when the package carries none."""

        if self.body_submesh_index < 0:
            return ()
        return tuple(range(self.body_submesh_index, self.body_submesh_index + max(1, self.body_submesh_count)))


#: The simulation description the viewer's particle layer reads (schema 1), next to the mesh files.
EFFECT_PREVIEW_FILE = "effect_preview.json"
EFFECT_TEXTURE_DIR = "effect_textures"


def write_effect_preview(
    package_dir: Path,
    preview: "EffectPreview",
    *,
    texture_reader: Optional[Callable[[str], Optional[bytes]]] = None,
) -> Tuple[Path, Tuple[str, ...]]:
    """Write `preview` into `package_dir` as `effect_preview.json` and copy the sprite
    textures it names (DDS bytes from `texture_reader`, archive path -> bytes) into
    `effect_textures/`; the JSON's `texture_files` maps each archive path to the
    relative file the viewer loads. Returns the JSON path and the textures not carried."""

    import json

    from cdmw.services.effect_preview_model import effect_preview_json

    payload = json.loads(effect_preview_json(preview))
    files: dict = {}
    missing: list = []
    texture_dir = Path(package_dir) / EFFECT_TEXTURE_DIR
    for archive_path in preview.textures:
        data = texture_reader(archive_path) if texture_reader is not None else None
        if not data:
            missing.append(archive_path)
            continue
        texture_dir.mkdir(parents=True, exist_ok=True)
        name = archive_path.rsplit("/", 1)[-1]
        (texture_dir / name).write_bytes(bytes(data))
        files[archive_path] = f"{EFFECT_TEXTURE_DIR}/{name}"
    payload["texture_files"] = files
    target = Path(package_dir) / EFFECT_PREVIEW_FILE
    target.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return target, tuple(missing)


#: Where a submesh can name the texture it draws with. `texture` is the name a `.pac`
#: family carries; an imported model binds its own files through the preview attributes
#: instead, and a check that read only the first found none and drew the item flat grey.
_TEXTURE_ATTRIBUTES = ("texture", "preview_texture_path", "preview_texture_dds_path")


def mesh_names_textures(mesh: object) -> bool:
    """Whether any submesh of `mesh` names a texture to draw with."""

    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for attribute in _TEXTURE_ATTRIBUTES:
            if str(getattr(submesh, attribute, "") or "").strip():
                return True
    return False


def anchor_radius_for(item_mesh: ParsedMesh) -> float:
    """An anchor big enough to grab and small enough to leave the item visible: a
    twenty-fifth of the item's longest side, between one and a half and six centimetres.
    A fixed one-and-a-half-centimetre octahedron is a dot beside a two-handed axe, and a
    hand-sized one hides the hilt it is sitting on."""

    try:
        low = tuple(float(value) for value in item_mesh.bbox_min)
        high = tuple(float(value) for value in item_mesh.bbox_max)
        longest = max(high[axis] - low[axis] for axis in range(3))
    except Exception:  # noqa: BLE001 - a mesh with no bounds keeps the shipped size
        return EFFECT_ANCHOR_RADIUS
    return max(0.015, min(0.06, longest / 25.0)) if longest > 0 else EFFECT_ANCHOR_RADIUS


def build_effect_placement_package(
    item_mesh: ParsedMesh,
    box_min: Vec3,
    box_max: Vec3,
    *,
    output_root: Path,
    include_body: bool = True,
    character_mesh: Optional[ParsedMesh] = None,
    item_rotation: Optional[Sequence[float]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    #: Carry the item's own textures into the package and draw it with them, the way the
    #: Model step does. Off, the item is a flat neutral: the package builder resolves no
    #: textures and the renderer draws an untextured material as a black body, which on a
    #: dark backdrop is an invisible sword. Costs the material synthesis pass.
    include_item_textures: bool = False,
    effect_preview: Optional["EffectPreview"] = None,
    texture_reader: Optional[Callable[[str], Optional[bytes]]] = None,
) -> EffectPlacementPreview:
    """Package the item's mesh (reference, drawn as its wire) and the effect's anchor
    (the editable mesh the gizmo moves) for the resident .NET viewport; with
    `effect_preview`, the simulation description and its textures go in beside them
    (see :func:`write_effect_preview`). `box_min`/`box_max` is the effect's reach,
    carried as numbers.

    `character_mesh` is the body drawn for scale and pose: the game's own character from
    :func:`cdmw.services.effect_character_reference.build_character_reference` when the
    archives gave one, and the shipped stand-in otherwise. That character stands upright,
    so with it comes `item_rotation`, the 3x3 that turns the item into the hand the way
    the game holds it; the item and the anchor are baked into it and the dialog carries
    its offsets across the same rotation."""

    from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package

    from copy import replace as _dc_replace

    radius = anchor_radius_for(item_mesh)
    anchor = anchor_mesh(radius)
    # the reach cage stays the second submesh: `reach_submesh_index` promises index 1
    anchor.submeshes.extend(reach_cage_mesh(box_min, box_max).submeshes)
    anchor.submeshes.extend(anchor_axis_triad(radius))
    anchor.total_vertices = sum(len(submesh.vertices) for submesh in anchor.submeshes)
    anchor.total_faces = sum(len(submesh.faces) for submesh in anchor.submeshes)
    rotation = tuple(float(v) for v in item_rotation) if item_rotation is not None else None
    if rotation is not None:
        from cdmw.services.effect_character_reference import rotate_mesh

        # both the item and the editable role are measured in the item's frame, so both
        # turn together; the gizmo's uniform scale commutes with a rotation, which is why
        # baking it into the cage and rotating the offset is exact rather than nearly right
        item_mesh = rotate_mesh(item_mesh, rotation)
        anchor = rotate_mesh(anchor, rotation)
    reference = item_mesh
    body_index = -1
    body_count = 0
    if include_body:
        # the body belongs with the item, not with the anchor: the gizmo moves the editable
        # role, and a scale reference that slid about with the effect would be no reference
        body = character_mesh if character_mesh is not None else character_reference_mesh()
        submeshes = list(item_mesh.submeshes) + list(body.submeshes)
        reference = _dc_replace(
            item_mesh,
            submeshes=submeshes,
            total_vertices=sum(len(submesh.vertices) for submesh in submeshes),
            total_faces=sum(len(submesh.faces) for submesh in submeshes),
        )
        body_index = len(anchor.submeshes) + len(item_mesh.submeshes)
        body_count = len(body.submeshes)
    package = build_mesh_dotnet_experiment_package(
        anchor,
        reference_mesh=reference,
        comparison_mode="overlay",
        # the item is what the effect is placed on, not a before-and-after against the
        # anchor, so it is drawn as itself rather than as the overlay's wire ghost
        reference_draw="solid",
        interaction_mode="placement",
        output_root=output_root,
        cancelled=cancelled,
        include_material_resources=bool(include_item_textures),
    )
    _tint_anchor_material(Path(package.package_dir) / "net_materials.json")
    frame_low, frame_high = framing_bounds_for(
        item_mesh, include_body=include_body, body_mesh=character_mesh if include_body else None
    )
    _frame_scene_on_the_item(Path(package.package_dir) / "dotnet_scene.json", frame_low, frame_high)
    preview_file: Optional[Path] = None
    missing: Tuple[str, ...] = ()
    if effect_preview is not None:
        preview_file, missing = write_effect_preview(Path(package.package_dir), effect_preview, texture_reader=texture_reader)
    return EffectPlacementPreview(
        body_submesh_index=body_index,
        body_submesh_count=body_count,
        item_rotation=rotation,
        package_dir=Path(package.package_dir),
        box_submesh_index=0,
        item_submesh_count=len(item_mesh.submeshes),
        box_min=tuple(float(v) for v in box_min),  # type: ignore[arg-type]
        box_max=tuple(float(v) for v in box_max),  # type: ignore[arg-type]
        preview_file=preview_file,
        missing_textures=missing,
    )
