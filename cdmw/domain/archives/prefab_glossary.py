"""Plain-English names for prefab fields, types, and asset roles.

A decoded prefab is honest but unfriendly: it calls things
``_masterPoseSkinnedMeshComponent`` and ``ResourceReferencePath_SkinnedMesh``.
This module turns that vocabulary into something a modder can act on, and says
what each field is *for* rather than only what it is called.

Curated entries cover the fields that actually matter for modding, chosen by
how often they are *set* across the shipped prefabs rather than how often they
are declared -- a prefab declares far more than it uses.

Descriptions are inferred from each field's name and declared type, not from
engine documentation. Where a name does not support a confident reading the
entry carries a label only, so the field still reads as prose without the
inspector asserting something it cannot back up. Anything absent falls back to
de-camel-casing the declared name.
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
    "_staticMeshInstanceFileName": FieldMeaning(
        "Mesh instance", "Names the model and the materials drawn on it."
    ),
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
    # Identity and editor presentation.
    "_displayName": FieldMeaning("Display name", "Name shown for this object in the editor."),
    "_key": FieldMeaning("Key", "Named lookup key for this entry."),
    "_value": FieldMeaning("Value", "The value this entry carries."),
    # Appearance and rendering.
    "_diffuseTexture": FieldMeaning("Base texture", "Base colour texture."),
    "_decalInfo": FieldMeaning("Decal", "Decal projected onto nearby surfaces."),
    "_triplanarMode": FieldMeaning("Triplanar mapping", "Project the texture from three axes instead of using UVs."),
    "_useTextureBuffer": FieldMeaning("Use texture buffer", "Read texture data from a buffer instead of a bound texture."),
    "_thickness": FieldMeaning("Thickness", "How thick the generated geometry is."),
    "_fade": FieldMeaning("Fade", "How this object fades in and out of view."),
    "_fadeInTime": FieldMeaning("Fade-in time", "Seconds taken to fade in."),
    "_fadeOutTime": FieldMeaning("Fade-out time", "Seconds taken to fade out."),
    "_priority": FieldMeaning("Priority", "Ordering against other objects competing for the same slot."),
    "_customRenderMaxPriority": FieldMeaning("Custom pass wins ties", "Give this object's custom render pass top priority."),
    "_useInstanceOptimization": FieldMeaning("Instance optimisation", "Allow the engine to batch repeated copies."),
    "_aggregation": FieldMeaning("Aggregate", "Merge this object with others for drawing."),
    # Placement and repetition.
    "_multiPosition": FieldMeaning("Repeat placement", "Placement used when this object is repeated."),
    "_multiPositionLargeMode": FieldMeaning("Repeat over a large area"),
    "_transforms": FieldMeaning("Placements", "Placement for each repeated copy."),
    "_offsetRadius": FieldMeaning("Offset radius", "How far copies are scattered from the origin."),
    "_position": FieldMeaning("Position", "Position in space."),
    "_applyLevelOverrideTransform": FieldMeaning(
        "Use level placement", "Take placement from the level rather than from this prefab."
    ),
    # Physics and collision.
    "_ignoreCollisionMasks": FieldMeaning("Ignored collision layers", "Collision layers this object does not interact with."),
    "_disableBreaking": FieldMeaning("Cannot break", "Stops this object from being broken."),
    "_overrideToDynamicMotion": FieldMeaning("Force dynamic motion", "Make this object physics-driven rather than static."),
    "_shapeId": FieldMeaning("Shape id"),
    # Cloth and meshes.
    "_attachingClothToMesh": FieldMeaning("Attached cloth", "Cloth simulation bound to this mesh."),
    "_siblingMesh": FieldMeaning("Paired mesh", "Another mesh component this one is paired with."),
    "_isSyncMeshComponent": FieldMeaning("Sync with mesh", "Keep this component in step with its mesh."),
    "_instanceAnchorMeshNodeContainer": FieldMeaning("Instance anchors", "Mesh nodes that placed copies anchor to."),
    "_externalLoadingInfo": FieldMeaning("Streaming info", "How this asset is streamed in."),
    # Splines.
    "_splineName": FieldMeaning("Spline", "Name of the spline this follows."),
    "_splineObject": FieldMeaning("Spline object", "The spline this object is bound to."),
    "_splineObjectUid": FieldMeaning("Spline id", "Identifier of the spline this belongs to."),
    "_isClosed": FieldMeaning("Closed loop", "Whether the spline joins back to its start."),
    "_rotationMode": FieldMeaning("Rotation mode", "How rotation follows the spline."),
    "_pointList": FieldMeaning("Points", "Points making up this shape."),
    "_smootingDistance": FieldMeaning("Smoothing distance", "How far smoothing reaches along the shape."),
    # Gimmicks and linkage.
    "_enableList": FieldMeaning("Enables", "Objects this switches on."),
    "_disableList": FieldMeaning("Disables", "Objects this switches off."),
    "_enableTargetList": FieldMeaning("Enable targets", "Objects targeted when switching on."),
    "_disableTargetList": FieldMeaning("Disable targets", "Objects targeted when switching off."),
    "_linkdataGroupList": FieldMeaning("Linked groups", "Groups of objects linked to this one."),
    "_gimmickTriggerCheckTargetDataList": FieldMeaning("Trigger checks", "Objects checked when this gimmick triggers."),
    "_switchOn": FieldMeaning("Starts on", "Whether this begins in the on state."),
    "_isSavePresetTarget": FieldMeaning("Saved in presets", "Include this object when a preset is saved."),
    "_socketList": FieldMeaning("Sockets", "Attachment points this object provides."),
    "_autoUpdateCustomKey": FieldMeaning("Auto-update key", "Refresh the custom key automatically."),
    "_customkey": FieldMeaning("Custom key", "Free-form value read by gameplay code."),
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
    # A .pami is an XML <StaticMeshInstance>: it names the mesh and carries the
    # material data for it. Checked on 300 sampled files -- all 300 have that
    # root element and a <StaticMesh Path=...>, 299 a <MaterialData>. Calling
    # it "Material" sends a modder looking for a texture file.
    ".pami": "Mesh instance",
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
