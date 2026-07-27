"""Plain-English names for prefab fields, types, and asset roles.

A decoded prefab is honest but unfriendly: it calls things
``_masterPoseSkinnedMeshComponent`` and ``ResourceReferencePath_SkinnedMesh``.
This module turns that vocabulary into something a modder can act on, and says
what each field is *for* rather than only what it is called.

Curated entries cover the fields that actually matter for modding. Anything
unknown falls back to de-camel-casing the declared name, so a field this table
has never seen still reads sensibly instead of disappearing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@dataclass(frozen=True, slots=True)
class FieldMeaning:
    """What a declared prefab field is called and what it controls."""

    label: str
    detail: str = ""


# Fields worth understanding, keyed by their declared name.
_FIELDS: dict[str, FieldMeaning] = {
    "_skinnedMeshFile": FieldMeaning("Mesh", "The model this object draws."),
    "_staticMeshInstanceFileName": FieldMeaning("Mesh instance", "Placed copy of a static model."),
    "_objectFilename": FieldMeaning("Object file", "The asset this object draws."),
    "_skinnedMeshFileName": FieldMeaning("Mesh name", "Name recorded alongside the mesh."),
    "_skeletonFileName": FieldMeaning("Skeleton", "Bone rig the mesh is bound to."),
    "_socketFileName": FieldMeaning("Socket data", "Attachment points other items hang from."),
    "_attachedSocketName": FieldMeaning("Attached to socket", "Where this object hangs on its parent."),
    "_pivotSocketName": FieldMeaning("Pivot socket", "Socket used as the rotation origin."),
    "_masterPoseSkinnedMeshComponent": FieldMeaning("Follows pose of", "Another mesh whose pose this copies."),
    "_worldTransform": FieldMeaning("World placement", "Position, rotation and scale in the world."),
    "_offsetTransform": FieldMeaning("Offset", "Extra placement applied on top of the socket."),
    "_tiledTransform": FieldMeaning("Tiled placement", "Placement within a world tile."),
    "_applyPosition": FieldMeaning("Use position", "Whether the socket's position is applied."),
    "_applyRotation": FieldMeaning("Use rotation", "Whether the socket's rotation is applied."),
    "_applyScale": FieldMeaning("Use scale", "Whether the socket's scale is applied."),
    "_isEnable": FieldMeaning("Enabled", "Whether this component is active."),
    "_opacity": FieldMeaning("Opacity", "How solid the mesh renders, 0 to 1."),
    "_shrinkTag": FieldMeaning("Shrink group", "Body region this hides so skin does not poke through."),
    "_shrinkMaskDistance": FieldMeaning("Shrink distance", "How far the shrink mask pushes the body in."),
    "_boneOffsetTag": FieldMeaning("Bone offset group", "Named bone offset profile to apply."),
    "_modelPropertyIndex": FieldMeaning("Material variant", "Which material set of the mesh to use."),
    "_modelBoneAnimationScriptKey": FieldMeaning("Bone script", "Named bone animation script."),
    "_collisionShapeType": FieldMeaning("Collision shape", "Shape used for physics collision."),
    "_components": FieldMeaning("Components", "What this object is made of."),
    "_childSceneObjects": FieldMeaning("Child objects", "Objects parented to this one."),
    "_customGameData": FieldMeaning("Game data", "Extra gameplay data attached to this object."),
    "_tag": FieldMeaning("Tag", "Identifier used by gameplay code."),
    "_sceneObjectUid": FieldMeaning("Object id", "Identifier for this object in the scene."),
    "_sceneObjectUuid": FieldMeaning("Object uuid", "Globally unique identifier for this object."),
    "_generateUUID": FieldMeaning("Generate uuid", "Whether the object gets a fresh uuid."),
    "_useCustomRenderPass": FieldMeaning("Custom render pass", "Draw with a non-default render pass."),
    "_customRenderValue": FieldMeaning("Render pass value", "Which custom render pass to use."),
    "_canSetOtherMasterPose": FieldMeaning("Can follow other poses", "Allows re-parenting the pose source."),
    "_isImportantGimmick": FieldMeaning("Important gimmick", "Marks the gimmick as gameplay-critical."),
    "_spawnReason": FieldMeaning("Spawn reason", "Why this object gets spawned."),
    "_initStateName": FieldMeaning("Initial state", "State the object starts in."),
    "_gimmickAliasName": FieldMeaning("Gimmick alias", "Name other systems refer to it by."),
    "_socketName": FieldMeaning("Socket name", "Name of this attachment point."),
    "_path": FieldMeaning("Path", "Location of the referenced file."),
}

# What an asset is, by file extension.
_ASSET_ROLES: dict[str, str] = {
    ".pac": "Model",
    ".pam": "Model",
    ".pamlod": "Model (LOD)",
    ".pab": "Skeleton",
    ".pabc": "Skeleton variation",
    ".papr": "Animation constraints",
    ".paa": "Animation",
    ".paac": "Animation chart",
    ".pae": "Animation",
    ".paem": "Animation",
    ".dds": "Texture",
    ".pami": "Material",
    ".pac_xml": "Material",
    ".pam_xml": "Material",
    ".hkx": "Physics",
    ".prefab": "Prefab",
}


def humanise_declared_name(name: str) -> str:
    """Turn ``_shrinkMaskDistance`` into ``Shrink mask distance``.

    Sentence case, not title case: acronyms such as ``UUID`` keep their shape,
    everything else reads as prose.
    """
    stripped = str(name or "").lstrip("_")
    if not stripped:
        return str(name or "")
    words = _CAMEL_BOUNDARY.sub(" ", stripped).split()
    if not words:
        return stripped
    rendered = [words[0][0].upper() + words[0][1:]]
    rendered.extend(word if word.isupper() else word.lower() for word in words[1:])
    return " ".join(rendered)


def describe_field(name: str) -> FieldMeaning:
    """Plain-English meaning of a declared field name."""
    known = _FIELDS.get(str(name or ""))
    if known is not None:
        return known
    return FieldMeaning(label=humanise_declared_name(name))


def describe_fields(names: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Readable labels for a run of declared field names, order preserved."""
    return tuple(describe_field(name).label for name in names)


def asset_role(path: str) -> str:
    """What kind of asset a path points at, e.g. ``Model`` or ``Socket data``."""
    text = str(path or "").replace("\\", "/").strip()
    if not text:
        return "File"
    lowered = text.lower()
    if lowered.endswith(".sockets.xml"):
        return "Socket data"
    if lowered.endswith(".prefabdata_xml"):
        return "Prefab data"
    suffix = PurePosixPath(lowered).suffix
    return _ASSET_ROLES.get(suffix, "File")


def is_asset_path(value: str) -> bool:
    """Whether a decoded string addresses another file.

    Some paths are stored inline rather than behind a pointer, so this follows
    the value's shape rather than which record kind it came from.
    """
    text = str(value or "").strip()
    return "/" in text and "." in text.rsplit("/", 1)[-1]


def describe_component(type_name: str) -> str:
    """What a component type does, in one line."""
    known = {
        "SkinnedMeshComponent": "Draws a rigged mesh that follows a skeleton.",
        "MeshComponent": "Draws a static mesh.",
        "EditorMeshComponent": "Editor-only mesh, not shown in game.",
        "TreeComponent": "Draws speed-tree style foliage.",
        "SocketComponent": "Provides attachment points for other objects.",
        "GimmickSpawnDataComponent": "Controls how a gimmick spawns.",
        "SpawnComponent": "Spawns another object.",
        "TransformSocket": "A named attachment point with its own offset.",
    }
    return known.get(str(type_name or ""), "")


def value_kind_hint(type_name: str, kind_label: str) -> str:
    """A plain description of what a field holds, given its declared type."""
    fixed = {
        "reference": "points at another file",
        "text": "text",
        "list": "child objects",
        "enum": "fixed choice",
    }
    if kind_label in fixed:
        return fixed[kind_label]
    lowered = str(type_name or "").lower()
    if lowered == "bool":
        return "on/off"
    if "transform" in lowered:
        return "position / rotation / scale"
    if "uuid" in lowered or "uid" in lowered:
        return "identifier"
    return "number"


__all__ = [
    "FieldMeaning",
    "asset_role",
    "describe_component",
    "describe_field",
    "describe_fields",
    "humanise_declared_name",
    "is_asset_path",
    "value_kind_hint",
]
