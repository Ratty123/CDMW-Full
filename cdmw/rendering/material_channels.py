from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, Mapping, Optional, Sequence, Tuple


MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION = 2

MATERIAL_CHANNELS: Tuple[str, ...] = (
    "base_color",
    "normal",
    "metalness",
    "roughness",
    "glossiness",
    "specular",
    "specular_f0",
    "ao",
    "cavity",
    "emissive",
    "opacity",
)

_SLOT_TO_CHANNEL = {
    "base": "base_color",
    "albedo": "base_color",
    "base_color": "base_color",
    "basecolor": "base_color",
    "diffuse": "base_color",
    "normal": "normal",
    "normalmap": "normal",
    "metal": "metalness",
    "metallic": "metalness",
    "metalness": "metalness",
    "rough": "roughness",
    "roughness": "roughness",
    "gloss": "glossiness",
    "glossiness": "glossiness",
    "smoothness": "glossiness",
    "spec": "specular",
    "specular": "specular",
    "specularf0": "specular_f0",
    "specular_f0": "specular_f0",
    "ao": "ao",
    "occlusion": "ao",
    "ambient_occlusion": "ao",
    "cavity": "cavity",
    "emissive": "emissive",
    "emission": "emissive",
    "opacity": "opacity",
    "alpha": "opacity",
}

_CHANNEL_TO_SKETCHFAB = {
    "base_color": "AlbedoPBR",
    "normal": "NormalMap",
    "metalness": "MetalnessPBR",
    "roughness": "RoughnessPBR",
    "glossiness": "GlossinessPBR",
    "specular": "SpecularPBR",
    "specular_f0": "SpecularF0",
    "ao": "AOPBR",
    "cavity": "CavityPBR",
    "emissive": "EmitColor",
    "opacity": "Opacity",
}

_SRGB_CHANNELS = {"base_color", "emissive", "specular"}


@dataclass(frozen=True)
class MaterialChannelSource:
    channel: str
    source_slot: str
    preview_path: str = ""
    source_dds_path: str = ""
    source_channel: str = "rgb"
    color_space: str = "linear"
    confidence: str = "missing"
    source_kind: str = "missing"
    reason: str = ""
    sketchfab_channel: str = ""
    parameter_name: str = ""
    shader_family: str = ""
    disposition: str = "promoted"

    def to_diagnostic(self) -> Dict[str, object]:
        return {
            "channel": self.channel,
            "sketchfab_channel": self.sketchfab_channel or _CHANNEL_TO_SKETCHFAB.get(self.channel, self.channel),
            "source_slot": self.source_slot,
            "source_channel": self.source_channel,
            "color_space": self.color_space,
            "confidence": self.confidence,
            "source_kind": self.source_kind,
            "preview_path": self.preview_path,
            "source_dds_path": self.source_dds_path,
            "reason": self.reason,
            "parameter_name": self.parameter_name,
            "shader_family": self.shader_family,
            "disposition": self.disposition,
        }


@dataclass(frozen=True)
class MaterialChannelContract:
    schema_version: int = MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION
    material_name: str = ""
    workflow: str = "metallic_roughness"
    shader_family: str = "generic"
    channels: Mapping[str, MaterialChannelSource] = field(default_factory=dict)
    unresolved: Tuple[Dict[str, object], ...] = ()
    scalar_hints: Mapping[str, float] = field(default_factory=dict)

    def channel(self, name: str) -> Optional[MaterialChannelSource]:
        return self.channels.get(_normalize_channel(name))

    def diagnostics(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "material_name": self.material_name,
            "workflow": self.workflow,
            "shader_family": self.shader_family,
            "channels": [source.to_diagnostic() for source in self.channels.values()],
            "unresolved": list(self.unresolved),
            "scalar_hints": dict(self.scalar_hints),
        }


@dataclass(frozen=True)
class CrimsonMaterialParameterDefinition:
    name: str
    type: str = ""
    srgb: str = ""
    default_value: str = ""


@dataclass(frozen=True)
class CrimsonMaterialDefinition:
    name: str
    technique: str = ""
    source_path: str = ""
    parameters: Mapping[str, CrimsonMaterialParameterDefinition] = field(default_factory=dict)
    permutations: Mapping[str, str] = field(default_factory=dict)
    parameter_groups: Tuple[str, ...] = ()


def _normalize_channel(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    compact = text.replace("_", "")
    return _SLOT_TO_CHANNEL.get(text) or _SLOT_TO_CHANNEL.get(compact) or text


def _normalize_key(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _normalized_shader_family(value: object) -> str:
    text = str(value or "").strip().lower()
    compact = _normalize_key(text)
    if not compact:
        return ""
    if "skin" in compact and "skinnedmesh" not in compact:
        return "skin"
    if "hair" in compact:
        return "hair"
    if "cloth" in compact:
        return "cloth_v2" if "v2" in compact or "ver2" in compact else "cloth"
    if "emissive" in compact:
        return "emissive_v2" if "v2" in compact or "ver2" in compact else "emissive"
    if "static" in compact and ("multi" in compact or "rgbtexture" in compact):
        return "static_multitextured"
    if "static" in compact:
        return "static_standard"
    if "standard" in compact:
        return "standard_v2" if "v2" in compact or "ver2" in compact else "standard"
    return text.replace(" ", "_")


def parse_crimson_material_definition_text(text: str, *, source_path: str = "") -> CrimsonMaterialDefinition:
    """Parse a Crimson ``.material`` definition into parameter metadata."""
    wrapped = "<Root>" + str(text or "") + "</Root>"
    root = ET.fromstring(wrapped)
    technique = ""
    parameters: Dict[str, CrimsonMaterialParameterDefinition] = {}
    permutations: Dict[str, str] = {}
    groups: list[str] = []
    for element in root:
        tag = str(element.tag or "")
        if tag == "Technique":
            technique = str(element.attrib.get("Name", "") or "").strip()
        elif tag == "Parameter":
            name = str(element.attrib.get("Name", "") or "").strip()
            if name:
                parameters[name] = CrimsonMaterialParameterDefinition(
                    name=name,
                    type=str(element.attrib.get("Type", "") or ""),
                    srgb=str(element.attrib.get("sRGB", element.attrib.get("SRGB", "")) or ""),
                    default_value=str(element.attrib.get("DefaultValue", "") or ""),
                )
        elif tag == "Permutation":
            name = str(element.attrib.get("Name", "") or "").strip()
            if name:
                permutations[name] = str(element.attrib.get("Value", "") or "")
        elif tag == "ParameterGroup":
            name = str(element.attrib.get("Name", "") or "").strip()
            if name:
                groups.append(name)
    inferred_name = Path(source_path).stem if source_path else technique
    return CrimsonMaterialDefinition(
        name=inferred_name,
        technique=technique,
        source_path=str(source_path or ""),
        parameters=parameters,
        permutations=permutations,
        parameter_groups=tuple(groups),
    )


def index_crimson_material_definitions(root: Path) -> Dict[str, CrimsonMaterialDefinition]:
    """Index Crimson ``.material`` files by normalized file stem and technique."""
    root = Path(root).expanduser()
    definitions: Dict[str, CrimsonMaterialDefinition] = {}
    if not root.exists():
        return definitions
    for path in root.rglob("*.material"):
        try:
            definition = parse_crimson_material_definition_text(path.read_text(encoding="utf-8-sig"), source_path=str(path))
        except Exception:
            continue
        for key in (path.stem, definition.name, definition.technique):
            normalized = _normalized_shader_family(key) or _normalize_key(key)
            if normalized:
                definitions.setdefault(normalized, definition)
    return definitions


def _slot_state_from_contract(batch: Mapping[str, object], slot_name: str) -> Mapping[str, object]:
    contract = batch.get("material_contract")
    if not isinstance(contract, Mapping):
        slots = {}
    else:
        slots = contract.get("texture_slots") or contract.get("resolved_texture_slots")
    if isinstance(slots, Mapping):
        slot = slots.get(slot_name)
        if isinstance(slot, Mapping):
            return slot
    dds_textures = batch.get("dds_textures")
    if isinstance(dds_textures, Mapping):
        slot = dds_textures.get(slot_name)
        if isinstance(slot, Mapping):
            return slot
    return {}


def _material_input_entries(batch: Mapping[str, object]) -> Tuple[Mapping[str, object], ...]:
    entries: list[Mapping[str, object]] = []
    for source in (batch.get("material_inputs"), (batch.get("dds_textures") or {}).get("material_inputs") if isinstance(batch.get("dds_textures"), Mapping) else None):
        if not isinstance(source, Sequence) or isinstance(source, (str, bytes, bytearray)):
            continue
        for item in source:
            if isinstance(item, Mapping):
                entries.append(item)
    return tuple(entries)


def _normalize_srgb_mode(value: object) -> str:
    if isinstance(value, bool):
        return "srgb" if value else "linear"
    text = str(value or "").strip().lower()
    if text in {"srgb", "s_rgb", "true", "1", "yes"}:
        return "srgb"
    if text in {"linear", "false", "0", "no"}:
        return "linear"
    return ""


def _slot_srgb_mode(batch: Mapping[str, object], slot_name: str) -> str:
    slot_state = _slot_state_from_contract(batch, slot_name)
    for key in ("srgb_mode", "sRGB", "srgb"):
        mode = _normalize_srgb_mode(slot_state.get(key, ""))
        if mode:
            return mode
    slot_name_key = str(slot_name or "").strip().lower()
    for entry in _material_input_entries(batch):
        entry_slot = str(entry.get("slot", "") or entry.get("slot_kind", "") or "").strip().lower()
        if entry_slot != slot_name_key:
            continue
        for key in ("srgb_mode", "sRGB", "srgb"):
            mode = _normalize_srgb_mode(entry.get(key, ""))
            if mode:
                return mode
    return ""


def _channel_color_space(batch: Mapping[str, object], slot_name: str, channel: str) -> str:
    mode = _slot_srgb_mode(batch, slot_name)
    if mode in {"srgb", "linear"}:
        return mode
    return "srgb" if channel in _SRGB_CHANNELS else "linear"


def _entry_path_name(entry: Mapping[str, object]) -> str:
    text = str(entry.get("source_dds_path", "") or entry.get("source_path", "") or entry.get("archive_path", "") or entry.get("preview_path", "") or "")
    if not text:
        return ""
    try:
        return Path(text).name.lower()
    except (OSError, ValueError):
        return text.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _slot_parameter_name(batch: Mapping[str, object], slot_name: str) -> str:
    slot_state = _slot_state_from_contract(batch, slot_name)
    parameter = str(slot_state.get("parameter_name", "") or "").strip()
    if parameter:
        return parameter
    slot_name = str(slot_name or "").strip().lower()
    for entry in _material_input_entries(batch):
        if str(entry.get("slot", "") or "").strip().lower() == slot_name:
            parameter = str(entry.get("parameter_name", "") or "").strip()
            if parameter:
                return parameter
    return ""


def _slot_shader_family(batch: Mapping[str, object], slot_name: str) -> str:
    candidates = [
        _slot_state_from_contract(batch, slot_name).get("shader_family", ""),
        (batch.get("material_contract") or {}).get("shader_family", "") if isinstance(batch.get("material_contract"), Mapping) else "",
        batch.get("material_shader_family", ""),
        (batch.get("native_material_hints") or {}).get("shader_family", "") if isinstance(batch.get("native_material_hints"), Mapping) else "",
    ]
    for entry in _material_input_entries(batch):
        if str(entry.get("slot", "") or "").strip().lower() == str(slot_name or "").strip().lower():
            candidates.append(entry.get("shader_family", ""))
    for value in candidates:
        normalized = _normalized_shader_family(value)
        if normalized:
            return normalized
    return "generic"


def _slot_packed_channels(batch: Mapping[str, object], slot_name: str) -> Tuple[str, ...]:
    contract = batch.get("material_contract")
    if isinstance(contract, Mapping):
        raw = contract.get("packed_channels", ())
        if isinstance(raw, str):
            return tuple(part.strip().lower() for part in raw.split(",") if part.strip())
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            values = tuple(str(value or "").strip().lower() for value in raw if str(value or "").strip())
            if values:
                return values
    slot_state = _slot_state_from_contract(batch, slot_name)
    raw = slot_state.get("packed_channels", "")
    if isinstance(raw, str) and raw.strip():
        return tuple(part.strip().lower() for part in raw.replace(";", ",").split(",") if part.strip())
    return ()


def _supported_crimson_material_mask_family(shader_family: str) -> bool:
    family = _normalized_shader_family(shader_family)
    return family in {"standard", "standard_v2", "static_standard", "static_multitextured", "emissive", "emissive_v2"}


def _crimson_material_mask_layout(batch: Mapping[str, object]) -> Optional[Dict[str, str]]:
    if not _is_crimson_ma_material_map(batch):
        return None
    parameter_key = _normalize_key(_slot_parameter_name(batch, "material"))
    shader_family = _slot_shader_family(batch, "material")
    if parameter_key == "colorblendingmasktexture" and _supported_crimson_material_mask_family(shader_family):
        return {"ao": "r", "roughness": "g", "metalness": "b"}
    return None


def _crimson_unresolved_material_entries(batch: Mapping[str, object]) -> Tuple[Dict[str, object], ...]:
    unresolved: list[Dict[str, object]] = []
    entries: list[Mapping[str, object]] = []
    material_slot = _slot_state_from_contract(batch, "material")
    if material_slot:
        entries.append(material_slot)
    entries.extend(_material_input_entries(batch))
    seen: set[Tuple[str, str, str]] = set()
    for entry in entries:
        name = _entry_path_name(entry)
        if not name and entry is material_slot:
            name = _slot_source_name(batch, "material")
        parameter = str(entry.get("parameter_name", "") or "").strip()
        parameter_key = _normalize_key(parameter)
        shader_family = _normalized_shader_family(entry.get("shader_family", "")) or _slot_shader_family(batch, "material")
        if name.endswith("_ma.dds") or Path(name).stem.endswith("_ma"):
            if parameter_key == "colorblendingmasktexture" and _supported_crimson_material_mask_family(shader_family):
                continue
            disposition = "diagnostic_only"
            reason = "Crimson _ma mask is not promoted without supported shader family and _colorBlendingMaskTexture parameter"
            slot = "material"
        elif name.endswith("_mg.dds") or Path(name).stem.endswith("_mg") or parameter_key == "detailmasktexture":
            disposition = "layer_only"
            reason = "Crimson _mg detail/grime/dye mask is layer-only; not a whole-material PBR map"
            slot = "detail"
        elif name.endswith("_sp.dds") or Path(name).stem.endswith("_sp"):
            disposition = "layer_material_response" if any(token in parameter_key for token in ("grimematerialtexture", "detailmaterialmask", "materialtexture")) else "diagnostic_only"
            reason = "Crimson _sp material response is parameter/layer dependent; not exported as whole-material roughness/metalness"
            slot = "material"
        elif parameter_key == "flowtexture" or name.endswith("_flow.dds") or Path(name).stem.endswith("_flow"):
            disposition = "layer_flow"
            reason = "Crimson flow texture is layer/vector control data; not promoted without an exact shader decoder"
            slot = "layer"
        elif parameter_key == "ssdmhairdirectiontexture" or "hairdirection" in parameter_key:
            disposition = "layer_direction"
            reason = "Crimson hair direction texture is anisotropic/layer control data; not a whole-material normal map"
            slot = "layer"
        elif (
            any(token in parameter_key for token in ("eyetexture", "iris", "pupil", "cornea"))
            or any(token in Path(name).stem.lower() for token in ("_eye", "_iris", "_pupil", "_cornea"))
        ):
            disposition = "diagnostic_only"
            reason = "Crimson eye/iris/pupil texture is anatomy-layer data; not promoted without an exact eye shader rule"
            slot = "layer"
        else:
            continue
        key = (slot, name, parameter)
        if key in seen:
            continue
        seen.add(key)
        unresolved.append(
            {
                "slot": slot,
                "parameter_name": parameter,
                "shader_family": shader_family or "generic",
                "source_dds_path": str(entry.get("source_dds_path", "") or entry.get("source_path", "") or _slot_source_paths(batch, "material")[1]),
                "preview_path": str(entry.get("preview_path", "") or _slot_source_paths(batch, "material")[0]),
                "disposition": disposition,
                "reason": reason,
                "confidence": str(entry.get("confidence", "") or entry.get("evidence_grade", "") or "shader_parameter_rule"),
                "layer_role": str(entry.get("layer_role", "") or ""),
                "layer_channel": str(entry.get("layer_channel", "") or ""),
                "blend_flags": list(tuple(entry.get("blend_flags", ()) or ())) if isinstance(entry.get("blend_flags", ()), Sequence) and not isinstance(entry.get("blend_flags", ()), (str, bytes, bytearray)) else (),
            }
        )
    return tuple(unresolved)


def _texture_slot_present(batch: Mapping[str, object], slot_name: str) -> bool:
    textures = batch.get("textures")
    if isinstance(textures, Mapping) and str(textures.get(slot_name, "") or "").strip():
        return True
    dds_textures = batch.get("dds_textures")
    if isinstance(dds_textures, Mapping):
        entry = dds_textures.get(slot_name)
        if isinstance(entry, Mapping) and str(entry.get("source_path", "") or "").strip():
            return True
    slot_state = _slot_state_from_contract(batch, slot_name)
    return bool(
        str(slot_state.get("preview_path", "") or "").strip()
        or str(slot_state.get("source_dds_path", "") or "").strip()
    )


def _source_for_slot(batch: Mapping[str, object], slot_name: str, channel: str) -> MaterialChannelSource:
    slot_state = _slot_state_from_contract(batch, slot_name)
    confidence = str(slot_state.get("confidence", "") or "").strip().lower()
    if not confidence or confidence == "missing":
        confidence = "exact" if channel in {"base_color", "normal"} else "inferred"
    source_kind = str(slot_state.get("source_kind", "") or "").strip().lower()
    if not source_kind or source_kind == "missing":
        source_kind = "texture"
    source_channel = "rgb" if channel in {"base_color", "normal", "emissive", "specular"} else "r"
    return MaterialChannelSource(
        channel=channel,
        source_slot=slot_name,
        preview_path=str(slot_state.get("preview_path", "") or ""),
        source_dds_path=str(slot_state.get("source_dds_path", "") or ""),
        source_channel=source_channel,
        color_space=_channel_color_space(batch, slot_name, channel),
        confidence=confidence,
        source_kind=source_kind,
        reason=str(slot_state.get("diagnostic", "") or slot_state.get("reason", "") or f"{slot_name} slot resolved"),
        sketchfab_channel=_CHANNEL_TO_SKETCHFAB.get(channel, channel),
        parameter_name=str(slot_state.get("parameter_name", "") or _slot_parameter_name(batch, slot_name)),
        shader_family=str(slot_state.get("shader_family", "") or _slot_shader_family(batch, slot_name)),
        disposition=str(slot_state.get("disposition", "") or "promoted"),
    )


def _slot_source_paths(batch: Mapping[str, object], slot_name: str) -> Tuple[str, str]:
    slot_state = _slot_state_from_contract(batch, slot_name)
    preview_path = str(slot_state.get("preview_path", "") or "")
    source_dds_path = str(slot_state.get("source_dds_path", "") or "")
    textures = batch.get("textures")
    if not preview_path and isinstance(textures, Mapping):
        preview_path = str(textures.get(slot_name, "") or "")
    dds_textures = batch.get("dds_textures")
    if not source_dds_path and isinstance(dds_textures, Mapping):
        entry = dds_textures.get(slot_name)
        if isinstance(entry, Mapping):
            source_dds_path = str(entry.get("source_path", "") or "")
    return preview_path, source_dds_path


def _slot_source_name(batch: Mapping[str, object], slot_name: str) -> str:
    preview_path, source_dds_path = _slot_source_paths(batch, slot_name)
    text = source_dds_path or preview_path
    if not text:
        return ""
    try:
        return Path(text).name.lower()
    except (OSError, ValueError):
        return text.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _is_crimson_ma_material_map(batch: Mapping[str, object]) -> bool:
    name = _slot_source_name(batch, "material")
    if not name:
        return False
    stem = Path(name).stem.lower()
    return stem.endswith("_ma")


def _packed_material_channels(batch: Mapping[str, object]) -> Dict[str, MaterialChannelSource]:
    if not _texture_slot_present(batch, "material"):
        return {}
    packed = _slot_packed_channels(batch, "material")
    confidence = "exact"
    source_kind = "packed_material"
    reason = "explicit packed material channel layout"
    joined_packed = ",".join(packed)
    if packed[:3] in {("ao", "roughness", "metallic"), ("occlusion", "roughness", "metallic")}:
        layout = {"ao": "r", "roughness": "g", "metalness": "b"}
    elif packed[:2] == ("roughness", "metallic"):
        layout = {"roughness": "g", "metalness": "b"}
    elif (
        ("r=ao" in joined_packed or "r=occlusion" in joined_packed)
        and "g=roughness" in joined_packed
        and ("b=metallic" in joined_packed or "b=metalness" in joined_packed)
    ):
        layout = {"ao": "r", "roughness": "g", "metalness": "b"}
    elif (layout := _crimson_material_mask_layout(batch)):
        confidence = "shader_parameter_rule"
        source_kind = "crimson_color_blending_mask"
        reason = "Crimson _ma _colorBlendingMaskTexture: R=AO, G=roughness, B=metalness"
    else:
        return {}
    preview_path, source_dds_path = _slot_source_paths(batch, "material")
    parameter_name = _slot_parameter_name(batch, "material")
    shader_family = _slot_shader_family(batch, "material")
    return {
        channel: MaterialChannelSource(
            channel=channel,
            source_slot="material",
            preview_path=preview_path,
            source_dds_path=source_dds_path,
            source_channel=source_channel,
            color_space="linear",
            confidence=confidence,
            source_kind=source_kind,
            reason=reason,
            sketchfab_channel=_CHANNEL_TO_SKETCHFAB.get(channel, channel),
            parameter_name=parameter_name,
            shader_family=shader_family,
            disposition="promoted",
        )
        for channel, source_channel in layout.items()
    }


def resolve_preview_batch_material_channels(
    batch: Mapping[str, object],
    *,
    package_dir: Optional[Path] = None,
) -> MaterialChannelContract:
    """Build the Sketchfab-style material channel view for a preview-package batch.

    This resolver is intentionally conservative. It promotes explicit slots
    such as base, normal, roughness, and metalness, exact glTF packed material
    maps, and the known Crimson ``*_ma`` material convention into channels.
    Other packed Crimson masks remain unresolved until a shader-family decoder
    can prove their channel layout.
    """
    del package_dir  # Reserved for later validation of copied paths.
    material_contract = batch.get("material_contract")
    contract_mapping = material_contract if isinstance(material_contract, Mapping) else {}
    shader_family = str(contract_mapping.get("shader_family", "") or _slot_shader_family(batch, "material") or "generic")
    scalar_hints_raw = contract_mapping.get("pbr_scalar_hints")
    scalar_hints = {
        str(key): float(value)
        for key, value in dict(scalar_hints_raw if isinstance(scalar_hints_raw, Mapping) else {}).items()
        if isinstance(value, (int, float))
    }
    channels: Dict[str, MaterialChannelSource] = {}
    for slot_name, channel in (
        ("base", "base_color"),
        ("albedo", "base_color"),
        ("base_color", "base_color"),
        ("normal", "normal"),
        ("roughness", "roughness"),
        ("metalness", "metalness"),
        ("metallic", "metalness"),
        ("glossiness", "glossiness"),
        ("specular", "specular"),
        ("specular_f0", "specular_f0"),
        ("occlusion", "ao"),
        ("ao", "ao"),
        ("cavity", "cavity"),
        ("emissive", "emissive"),
        ("opacity", "opacity"),
    ):
        normalized = _normalize_channel(channel)
        if normalized in channels:
            continue
        if _texture_slot_present(batch, slot_name):
            channels[normalized] = _source_for_slot(batch, slot_name, normalized)
    channels.update({name: source for name, source in _packed_material_channels(batch).items() if name not in channels})

    unresolved: list[Dict[str, object]] = list(_crimson_unresolved_material_entries(batch))
    seen_unresolved = {
        (
            str(item.get("slot", "") or ""),
            str(item.get("preview_path", "") or ""),
            str(item.get("source_dds_path", "") or ""),
            str(item.get("parameter_name", "") or ""),
        )
        for item in unresolved
    }
    material_promoted = any(source.source_slot == "material" for source in channels.values())
    for slot_name in ("material", "height", "detail", "mask"):
        if _texture_slot_present(batch, slot_name):
            if slot_name == "material" and material_promoted:
                continue
            slot_state = _slot_state_from_contract(batch, slot_name)
            entry = {
                "slot": slot_name,
                "reason": "custom or packed material data; not promoted without an exact channel layout",
                "confidence": str(slot_state.get("confidence", "") or "unresolved"),
                "preview_path": str(slot_state.get("preview_path", "") or ""),
                "source_dds_path": str(slot_state.get("source_dds_path", "") or ""),
                "parameter_name": str(slot_state.get("parameter_name", "") or _slot_parameter_name(batch, slot_name)),
                "shader_family": str(slot_state.get("shader_family", "") or _slot_shader_family(batch, slot_name)),
                "disposition": "diagnostic_only",
            }
            key = (
                str(entry.get("slot", "") or ""),
                str(entry.get("preview_path", "") or ""),
                str(entry.get("source_dds_path", "") or ""),
                str(entry.get("parameter_name", "") or ""),
            )
            if key not in seen_unresolved:
                unresolved.append(entry)
                seen_unresolved.add(key)
    packed_channels = _slot_packed_channels(batch, "material")
    if packed_channels and _texture_slot_present(batch, "material") and not material_promoted:
        unresolved.append(
            {
                "slot": "material",
                "packed_channels": list(str(value) for value in packed_channels),
                "reason": "packed channels recorded for diagnostics; shader-family decoder not yet authoritative",
            }
        )

    workflow = "specular_glossiness" if "specular" in channels and "glossiness" in channels else "metallic_roughness"
    return MaterialChannelContract(
        material_name=str(batch.get("material_name") or batch.get("texture_name") or ""),
        workflow=workflow,
        shader_family=shader_family,
        channels=channels,
        unresolved=tuple(unresolved),
        scalar_hints=scalar_hints,
    )


__all__ = [
    "MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION",
    "MATERIAL_CHANNELS",
    "MaterialChannelContract",
    "MaterialChannelSource",
    "CrimsonMaterialDefinition",
    "CrimsonMaterialParameterDefinition",
    "index_crimson_material_definitions",
    "parse_crimson_material_definition_text",
    "resolve_preview_batch_material_channels",
]
