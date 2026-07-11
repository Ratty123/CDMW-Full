from __future__ import annotations

from cdmw.core.archive_binary_preview_compat import bind_binary_preview_globals


@bind_binary_preview_globals(
)
def _group_prefab_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("cloth", "pbd", "shrink", "masterpose", "syncmeshcomponent", "anchormeshnode", "meshnode", "dynamicmotion", "sdf")):
        return "Mesh / Cloth"
    if any(token in normalized for token in ("socket", "skeleton", "bone")):
        return "Skeleton / Sockets"
    if any(token in normalized for token in ("path", "file", "filename", "mesh", "model", "lod", "material", "texture", "resource", "asset")):
        return "Resources"
    if any(token in normalized for token in ("component", "childsceneobjects", "masterpose", "customgamedata")):
        return "Scene / Object"
    if any(token in normalized for token in ("prefab", "scene", "object", "node", "actor", "entity", "spawn", "enable", "uuid", "uid", "tag", "generateuuid")):
        return "Scene / Object"
    if any(token in normalized for token in ("position", "rotation", "scale", "transform", "matrix", "bound", "bbox")):
        return "Transform / Bounds"
    if any(token in normalized for token in ("collision", "physics", "pbd", "shape", "constraint", "rigid", "mass")):
        return "Physics / Collision"
    if any(token in normalized for token in ("script", "event", "trigger", "condition", "gimmick", "logic")):
        return "Logic / Events"
    if any(token in normalized for token in ("render", "opacity", "priority", "sound", "audio", "effect", "emitter", "particle", "light")):
        return "Presentation"
    return "Misc"


@bind_binary_preview_globals(
    '_group_animation_field_name',
    '_group_character_customization_field_name',
    '_group_meshinfo_field_name',
    '_group_model_property_header_field_name',
    '_group_prefab_field_name',
    '_group_rig_variant_field_name',
    '_group_seqmt_field_name',
    '_group_world_field_name',
)
def _binary_sidecar_group_func_for_extension(extension: str) -> Callable[[str], str]:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == ".meshinfo":
        return _group_meshinfo_field_name
    if normalized_extension in {".prefab", ".pappt"}:
        return _group_prefab_field_name
    if normalized_extension == ".pamhc":
        return _group_model_property_header_field_name
    if normalized_extension == ".paccd":
        return _group_character_customization_field_name
    if normalized_extension == ".seqmt":
        return _group_seqmt_field_name
    if normalized_extension in {".levelinfo", ".palevel", ".roadsector", ".road", ".nav"}:
        return _group_world_field_name
    if normalized_extension in {".pabc", ".pabv", ".pabgb", ".pabgh"}:
        return _group_rig_variant_field_name
    return _group_animation_field_name


@bind_binary_preview_globals(
)
def _group_model_property_header_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("material", "shader", "texture", "submesh", "parameter", "skin", "cloth")):
        return "Material / Texture"
    if any(token in normalized for token in ("mesh", "model", "lod", "resource", "path", "file", "filename", "asset")):
        return "Model Resources"
    if any(token in normalized for token in ("socket", "skeleton", "bone", "rig")):
        return "Skeleton / Rig"
    if any(token in normalized for token in ("physics", "collision", "hkx", "shape", "cloth", "pbd")):
        return "Physics / Collision"
    if any(token in normalized for token in ("bounds", "bbox", "position", "rotation", "scale", "transform")):
        return "Transform / Bounds"
    if any(token in normalized for token in ("variant", "part", "body", "gender", "race")):
        return "Variant / Part"
    return "Misc"


@bind_binary_preview_globals(
)
def _group_character_customization_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("custom", "slot", "slider", "morph", "blend", "palette", "preset")):
        return "Customization Slots"
    if any(token in normalized for token in ("color", "tint", "rgb", "skin", "hair", "dye")):
        return "Palette / Color"
    if any(token in normalized for token in ("face", "head", "body", "eye", "nose", "mouth", "brow")):
        return "Body / Face"
    if any(token in normalized for token in ("material", "texture", "shader", "mask")):
        return "Material / Texture"
    if any(token in normalized for token in ("part", "variant", "gender", "race", "class")):
        return "Variant / Part"
    return "Misc"


@bind_binary_preview_globals(
)
def _group_seqmt_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("material", "shader", "texture", "parameter", "color", "tint", "mask", "blend", "uv")):
        return "Material / Texture"
    if any(token in normalized for token in ("sequence", "sequencer", "timeline", "track", "key", "frame", "curve", "duration", "time")):
        return "Sequence / Timeline"
    if any(token in normalized for token in ("path", "file", "filename", "resource", "asset", "model", "mesh", "prefab")):
        return "Resources"
    if any(token in normalized for token in ("effect", "emitter", "particle", "light", "visibility", "opacity", "render", "presentation")):
        return "Effect / Presentation"
    if any(token in normalized for token in ("position", "rotation", "scale", "transform", "matrix", "bound", "bbox")):
        return "Transform / Bounds"
    return "Misc"


@bind_binary_preview_globals(
)
def _group_world_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("level", "world", "zone", "sector", "region", "cell", "tile", "block")):
        return "World / Region"
    if any(token in normalized for token in ("road", "spline", "lane", "path", "waypoint", "route")):
        return "Road / Path"
    if any(token in normalized for token in ("nav", "navigation", "navmesh", "obstacle", "agent")):
        return "Navigation"
    if any(token in normalized for token in ("prefab", "object", "entity", "spawn", "gimmick", "prop")):
        return "Scene Objects"
    if any(token in normalized for token in ("terrain", "height", "water", "foliage", "grass", "vegetation")):
        return "Terrain"
    if any(token in normalized for token in ("bound", "bbox", "extent", "position", "rotation", "scale")):
        return "Bounds / Transform"
    return "Misc"


@bind_binary_preview_globals(
)
def _group_rig_variant_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("skeleton", "bone", "joint", "rig", "socket")):
        return "Skeleton / Rig"
    if any(token in normalized for token in ("physics", "ragdoll", "constraint", "collision", "shape")):
        return "Physics"
    if any(token in normalized for token in ("animation", "motion", "blend", "pose", "clip")):
        return "Animation"
    if any(token in normalized for token in ("variant", "gender", "race", "body", "part", "custom")):
        return "Variant / Body"
    if any(token in normalized for token in ("gameplay", "state", "behavior", "ai", "event")):
        return "Gameplay"
    return "Misc"


@bind_binary_preview_globals(
    '_structured_field_type_hint',
    'defaultdict',
)
def _build_grouped_structured_section_lines(
    field_names: Sequence[str],
    *,
    group_func: Callable[[str], str],
    section_order: Sequence[str],
    per_section_limit: int = 24,
) -> List[str]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for name in sorted({str(item or "").strip() for item in field_names if str(item or "").strip()}, key=str.casefold):
        grouped[group_func(name)].append(name)

    lines: List[str] = []
    for section_name in section_order:
        section_fields = grouped.get(section_name, [])
        if not section_fields:
            continue
        lines.extend(["", f"{section_name} ({len(section_fields)})"])
        for field_name in section_fields[:per_section_limit]:
            lines.append(f"  [{_structured_field_type_hint(field_name)}] {field_name}")
        if len(section_fields) > per_section_limit:
            lines.append(f"  ... {len(section_fields) - per_section_limit} more")

    remaining_sections = [
        section_name
        for section_name, section_fields in grouped.items()
        if section_name not in section_order and section_fields
    ]
    for section_name in sorted(remaining_sections, key=str.casefold):
        section_fields = grouped.get(section_name, [])
        if not section_fields:
            continue
        lines.extend(["", f"{section_name} ({len(section_fields)})"])
        for field_name in section_fields[:per_section_limit]:
            lines.append(f"  [{_structured_field_type_hint(field_name)}] {field_name}")
        if len(section_fields) > per_section_limit:
            lines.append(f"  ... {len(section_fields) - per_section_limit} more")

    return lines
