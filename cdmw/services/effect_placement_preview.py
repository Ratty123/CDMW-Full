"""Place an effect on an item in the .NET viewport: the effect's box as a mesh the gizmo moves.

The game draws a grafted effect at the weapon's origin, transformed by the
``_offsetTransform`` the studio writes (a uniform scale and an offset). What the
effect *spans* is known from its binary (`EffectData._boundingBoxMin/Max`, see
:mod:`cdmw.services.effect_catalogue`), so a box of that size, placed by the same
scale and offset, is where the effect will be. This module builds that box as a
:class:`ParsedMesh` and packages it for the resident .NET viewport with the item's
own mesh as the reference: the viewport's placement gizmo then moves and scales the
box, and every drag comes back as a delta the studio adds to its offset and scale.

The scene is the item's frame: the weapon's origin is the hand, +z toward the
pommel, the blade toward -z; a helm sits at head height. The box mesh is authored
at scale 1.0 around the effect's own origin, so the placement transform the
viewport applies is exactly the ``_offsetTransform`` the game will.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Sequence, Tuple

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

if TYPE_CHECKING:
    from cdmw.services.effect_preview_model import EffectPreview

__all__ = [
    "EFFECT_BOX_MATERIAL",
    "EFFECT_BOX_SUBMESH",
    "EFFECT_PREVIEW_FILE",
    "EFFECT_TEXTURE_DIR",
    "EffectPlacementPreview",
    "box_mesh",
    "build_effect_placement_package",
    "next_scale",
    "write_effect_preview",
]

Vec3 = Tuple[float, float, float]
EFFECT_BOX_SUBMESH = "effect_box"
EFFECT_BOX_MATERIAL = "effect_box"
_MIN_EXTENT = 0.05


def box_mesh(box_min: Vec3, box_max: Vec3, *, name: str = EFFECT_BOX_SUBMESH) -> ParsedMesh:
    """A closed box between `box_min` and `box_max` (effect-local metres, scale 1.0),
    with a floor of a few centimetres so an effect that reports no box still shows."""

    low = list(float(v) for v in box_min)
    high = list(float(v) for v in box_max)
    for axis in range(3):
        if high[axis] - low[axis] < _MIN_EXTENT:
            centre = (high[axis] + low[axis]) / 2.0
            low[axis], high[axis] = centre - _MIN_EXTENT / 2.0, centre + _MIN_EXTENT / 2.0
    x0, y0, z0 = low
    x1, y1, z1 = high
    corners = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    # each face its own four vertices, so the normals are flat and the box reads as a solid
    faces_by_side = (
        ((0, 1, 2, 3), (0.0, 0.0, -1.0)),
        ((5, 4, 7, 6), (0.0, 0.0, 1.0)),
        ((4, 0, 3, 7), (-1.0, 0.0, 0.0)),
        ((1, 5, 6, 2), (1.0, 0.0, 0.0)),
        ((4, 5, 1, 0), (0.0, -1.0, 0.0)),
        ((3, 2, 6, 7), (0.0, 1.0, 0.0)),
    )
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    uvs: list[Tuple[float, float]] = []
    faces: list[Tuple[int, int, int]] = []
    for quad, normal in faces_by_side:
        base = len(vertices)
        for corner in quad:
            vertices.append(corners[corner])
            normals.append(normal)
        uvs.extend([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        faces.append((base, base + 1, base + 2))
        faces.append((base, base + 2, base + 3))
    submesh = SubMesh(
        name=name, material=EFFECT_BOX_MATERIAL, vertices=vertices, uvs=uvs, normals=normals, faces=faces,
        vertex_count=len(vertices), face_count=len(faces),
    )
    return ParsedMesh(path=f"{name}.box", format="box", submeshes=[submesh], bbox_min=tuple(low), bbox_max=tuple(high),  # type: ignore[arg-type]
                      total_vertices=len(vertices), total_faces=len(faces), has_uvs=True, has_bones=False)


def next_scale(current: float, delta: Sequence[float]) -> float:
    """The uniform effect scale after a gizmo scale drag reported as a per-axis delta:
    the mean of the three, clamped to the studio's range."""

    values = [float(v) for v in delta][:3] or [0.0]
    mean = sum(values) / len(values)
    return max(0.01, min(10.0, float(current) + mean))


#: The box's look in the viewport: a translucent orange, so the item inside it stays visible.
BOX_TINT = (1.0, 0.45, 0.1)
BOX_OPACITY = 0.35


def _tint_box_material(materials_path: Path) -> None:
    """Make the box submesh translucent and orange in the package's .NET materials.

    The package builder gives every submesh an opaque neutral material; the box has
    to be seen through, or the item it surrounds is hidden. Best effort: a package
    whose materials file is missing or unreadable keeps the opaque box.
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
        if not isinstance(item, dict) or str(item.get("material", "")) != EFFECT_BOX_MATERIAL:
            continue
        item["alpha_mode"] = "blend"
        item["opacity_factor"] = BOX_OPACITY
        item["double_sided"] = True
        parameters = dict(item.get("parameters", {}) or {})
        parameters.update({"base_tint_color": list(BOX_TINT), "base_tint_strength": 1.0, "roughness": 0.9, "metalness": 0.0})
        item["parameters"] = parameters
        changed = True
    if changed:
        materials_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


@dataclass(frozen=True, slots=True)
class EffectPlacementPreview:
    """A built package: where it is, which submesh is the box, and the item's frame."""

    package_dir: Path
    box_submesh_index: int
    item_submesh_count: int
    box_min: Vec3
    box_max: Vec3
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
    """Package the item's mesh (reference, drawn as its wire) and the effect's box
    (the editable mesh the gizmo moves) for the resident .NET viewport; with
    `effect_preview`, the simulation description and its textures go in beside them
    (see :func:`write_effect_preview`)."""

    from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package

    box = box_mesh(box_min, box_max)
    package = build_mesh_dotnet_experiment_package(
        box,
        reference_mesh=item_mesh,
        comparison_mode="overlay",
        interaction_mode="placement",
        output_root=output_root,
        cancelled=cancelled,
        include_material_resources=False,
    )
    _tint_box_material(Path(package.package_dir) / "net_materials.json")
    preview_file: Optional[Path] = None
    missing: Tuple[str, ...] = ()
    if effect_preview is not None:
        preview_file, missing = write_effect_preview(Path(package.package_dir), effect_preview, texture_reader=texture_reader)
    return EffectPlacementPreview(
        package_dir=Path(package.package_dir),
        box_submesh_index=0,
        item_submesh_count=len(item_mesh.submeshes),
        box_min=tuple(box.bbox_min),  # type: ignore[arg-type]
        box_max=tuple(box.bbox_max),  # type: ignore[arg-type]
        preview_file=preview_file,
        missing_textures=missing,
    )
