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
    "EFFECT_REACH_MATERIAL",
    "EFFECT_REACH_SUBMESH",
    "reach_cage_mesh",
    "EFFECT_PREVIEW_FILE",
    "EFFECT_TEXTURE_DIR",
    "EffectPlacementPreview",
    "anchor_mesh",
    "build_effect_placement_package",
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
    thickness = max(0.004, span * 0.004)
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    uvs: list[Tuple[float, float]] = []
    faces: list[Tuple[int, int, int]] = []
    for axis in range(3):
        other = [index for index in range(3) if index != axis]
        for first in (low[other[0]], high[other[0]]):
            for second in (low[other[1]], high[other[1]]):
                bar_low = [0.0, 0.0, 0.0]
                bar_high = [0.0, 0.0, 0.0]
                bar_low[axis], bar_high[axis] = low[axis], high[axis]
                bar_low[other[0]], bar_high[other[0]] = first - thickness, first + thickness
                bar_low[other[1]], bar_high[other[1]] = second - thickness, second + thickness
                _bar(tuple(bar_low), tuple(bar_high), vertices, normals, uvs, faces)  # type: ignore[arg-type]
    submesh = SubMesh(
        name=name, material=EFFECT_REACH_MATERIAL, vertices=vertices, uvs=uvs, normals=normals, faces=faces,
        vertex_count=len(vertices), face_count=len(faces),
    )
    return ParsedMesh(path=f"{name}.reach", format="reach", submeshes=[submesh], bbox_min=tuple(low), bbox_max=tuple(high),  # type: ignore[arg-type]
                      total_vertices=len(vertices), total_faces=len(faces), has_uvs=True, has_bones=False)


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


def next_scale(current: float, delta: Sequence[float]) -> float:
    """The uniform effect scale after a gizmo scale drag reported as a per-axis delta:
    the mean of the three, clamped to the studio's range."""

    values = [float(v) for v in delta][:3] or [0.0]
    mean = sum(values) / len(values)
    return max(0.01, min(10.0, float(current) + mean))


#: the anchor's colour: orange, opaque, so it reads as a handle and not as part of the item
ANCHOR_TINT = (1.0, 0.45, 0.1)
#: the reach cage's colour: the same family, dimmer, so it reads as a frame around the effect
REACH_TINT = (0.55, 0.3, 0.1)
#: the item's colour: a light neutral, because the package builder leaves its materials
#: without a texture or a base colour and the renderer draws that as a black body
ITEM_TINT = (0.62, 0.64, 0.67)


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
        if material == EFFECT_ANCHOR_MATERIAL:
            item["double_sided"] = True
            parameters.update({"base_tint_color": list(ANCHOR_TINT), "base_tint_strength": 1.0, "roughness": 0.6, "metalness": 0.0})
        elif material == EFFECT_REACH_MATERIAL:
            item["double_sided"] = True
            parameters.update({"base_tint_color": list(REACH_TINT), "base_tint_strength": 1.0, "roughness": 0.6, "metalness": 0.0})
        else:
            parameters.update({"base_tint_color": list(ITEM_TINT), "base_tint_strength": 1.0, "roughness": 0.55, "metalness": 0.0})
        item["parameters"] = parameters
        changed = True
    if changed:
        materials_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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
    #: `effect_preview.json` in the package when the caller gave an effect preview, else None
    preview_file: Optional[Path] = None
    #: archive texture paths the package could not carry (no reader, or the reader had none)
    missing_textures: Tuple[str, ...] = ()


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


def build_effect_placement_package(
    item_mesh: ParsedMesh,
    box_min: Vec3,
    box_max: Vec3,
    *,
    output_root: Path,
    cancelled: Optional[Callable[[], bool]] = None,
    effect_preview: Optional["EffectPreview"] = None,
    texture_reader: Optional[Callable[[str], Optional[bytes]]] = None,
) -> EffectPlacementPreview:
    """Package the item's mesh (reference, drawn as its wire) and the effect's anchor
    (the editable mesh the gizmo moves) for the resident .NET viewport; with
    `effect_preview`, the simulation description and its textures go in beside them
    (see :func:`write_effect_preview`). `box_min`/`box_max` is the effect's reach,
    carried as numbers."""

    from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package

    anchor = anchor_mesh()
    anchor.submeshes.extend(reach_cage_mesh(box_min, box_max).submeshes)
    anchor.total_vertices = sum(len(submesh.vertices) for submesh in anchor.submeshes)
    anchor.total_faces = sum(len(submesh.faces) for submesh in anchor.submeshes)
    package = build_mesh_dotnet_experiment_package(
        anchor,
        reference_mesh=item_mesh,
        comparison_mode="overlay",
        # the item is what the effect is placed on, not a before-and-after against the
        # anchor, so it is drawn as itself rather than as the overlay's wire ghost
        reference_draw="solid",
        interaction_mode="placement",
        output_root=output_root,
        cancelled=cancelled,
        include_material_resources=False,
    )
    _tint_anchor_material(Path(package.package_dir) / "net_materials.json")
    preview_file: Optional[Path] = None
    missing: Tuple[str, ...] = ()
    if effect_preview is not None:
        preview_file, missing = write_effect_preview(Path(package.package_dir), effect_preview, texture_reader=texture_reader)
    return EffectPlacementPreview(
        package_dir=Path(package.package_dir),
        box_submesh_index=0,
        item_submesh_count=len(item_mesh.submeshes),
        box_min=tuple(float(v) for v in box_min),  # type: ignore[arg-type]
        box_max=tuple(float(v) for v in box_max),  # type: ignore[arg-type]
        preview_file=preview_file,
        missing_textures=missing,
    )
