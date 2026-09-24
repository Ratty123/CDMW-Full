"""Source-preserving PAC_XML/PAMI edits for the decoded shader experiments."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from cdmw.core.pac_xml_emission import append_emission_parameter
from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.mesh.shader_controls import (NEW_ITEM_FAMILIES, EYE_COVER, EYE_COVER_TEXTURE_FIELDS,
                                             ShaderControls, family_for, validate_choices)


def _parameter_rows(block):
    root = ET.fromstring(block)
    result = {}
    for element in root.iter():
        if not element.tag.startswith("MaterialParameter"):
            continue
        name = element.get("_name", element.get("StringItemID", element.get("Name", "")))
        if name in result:
            raise ValueError(f"Ambiguous duplicate material parameter: {name}")
        result[name] = element
    return result


def control_material_sources(text, *, static=False):
    """Read material identity and authored inputs without rewriting the document."""
    if static:
        blocks = []
        for match in re.finditer(r'<Material\b[^>]*\bPrimitiveName="[^"]*"[^>]*>.*?</Material>', text, re.S):
            root = ET.fromstring(match.group())
            common = root.find("Common")
            blocks.append((root.get("PrimitiveName", ""), common.get("MaterialName", "") if common is not None else "", match.group()))
    else:
        blocks = [(w.submesh_name, w.shader, text[w.start:w.end]) for w in find_material_wrappers(text)]
    result = {}
    for name, shader, block in blocks:
        values, textures = {}, {}
        for key, element in _parameter_rows(block).items():
            value = element.get("_value", element.get("Value", ""))
            if element.tag == "MaterialParameterTexture":
                child = element.find("ResourceReferencePath_ITexture")
                textures[key] = child.get("_path", "") if child is not None else value
            else:
                values[key] = value
        if name.casefold() in result:
            raise ValueError(f"Ambiguous material binding: {name}")
        result[name.casefold()] = (shader, values, textures)
    return result


def validate_source(shader, controls, parameters, *, static=False):
    family = family_for(controls.shader)
    if static != (controls.shader == "Dissolve"):
        raise ValueError("Object dissolve and equipment shaders use different vertex pipelines.")
    if shader != family.shader:
        plain_sources = {"SkinnedMeshStandard", "SkinnedMeshEmissive"}
        if family == EYE_COVER:
            plain_sources.add("SkinnedMeshTranslucent")
        if (family.shader not in {"SkinnedMeshWing", EYE_COVER.shader} or shader not in plain_sources
                or "_baseColorTexture" not in parameters
                or any(name.lower().startswith(("_wrinkle", "_overlay", "_colorblending")) for name in parameters)):
            raise ValueError(f"{family.label} requires {family.shader} or a compatible plain equipment material with a base colour texture.")
    if "_hairDyeingProperty" in dict(controls.values):
        dye = parameters.get("_hairDyeingColor")
        raw = dye.get("_value", "") if dye is not None else ""
        if not re.fullmatch(r"#[0-9a-fA-F]{8}", raw) or int(raw[-2:], 16) == 0:
            raise ValueError("Dye roughness is inactive because the source hair dye alpha is zero. This edit will not enable dye or change its colour.")


def equipment_shader_options(text):
    """Source shader and compatible experiments, using the output writer's rules."""
    result = {}
    for wrapper in find_material_wrappers(text):
        key = wrapper.submesh_name.casefold()
        supported = []
        try:
            parameters = _parameter_rows(text[wrapper.start:wrapper.end])
        except (ValueError, ET.ParseError):
            parameters = None
        if key not in result and parameters is not None:
            for family in NEW_ITEM_FAMILIES:
                try:
                    validate_source(wrapper.shader, ShaderControls(family.shader), parameters)
                except ValueError:
                    continue
                supported.append(family.shader)
        # Ambiguous or malformed wrappers cannot safely accept an experiment.
        result[key] = (wrapper.shader, tuple(supported))
    return result


def _write_parameter(block, name, kind, value, item_id, *, static):
    pattern = re.compile(r'<MaterialParameter(?P<kind>\w+)\b(?=[^>]*\b(?:StringItemID|_name|Name)="' + re.escape(name)
                         + r'")[^>]*?(?:\s*/>|>.*?</MaterialParameter(?P=kind)>)', re.S)
    matches = list(pattern.finditer(block))
    if len(matches) > 1:
        raise ValueError(f"Ambiguous duplicate material parameter: {name}")
    old = ET.fromstring(matches[0].group()) if matches else None
    if old is not None and old.tag != "MaterialParameter" + kind:
        raise ValueError(f"{name}: source parameter type does not match the decoded shader.")
    if old is not None:
        # Retain all source metadata, including the real ItemID, Index and flags.
        if kind != "Texture" and old.get("Value" if static else "_value") == value:
            return block
        if kind == "Texture":
            if static:
                old.set("Value", value)
            else:
                child = old.find("ResourceReferencePath_ITexture")
                if child is None:
                    raise ValueError(f"{name}: the source texture binding is incomplete.")
                child.set("_path", value)
        else:
            old.set("Value" if static else "_value", value)
        return block[:matches[0].start()] + ET.tostring(old, encoding="unicode") + block[matches[0].end():]
    value = escape(value, {'"': "&quot;"})
    if static:
        row = f'<MaterialParameter{kind} Name="{name}" Value="{value}"/>'
        vector = re.search(r'<Parameters\s*(/?)>', block)
        if vector is None:
            raise ValueError("The static material has no parameter block.")
        if vector.group(1):
            return block[:vector.start()] + "<Parameters>" + row + "</Parameters>" + block[vector.end():]
        return block[:vector.end()] + row + block[vector.end():]
    index = max((int(v) for v in re.findall(r'\bIndex="(\d+)"', block)), default=-1) + 1
    # StringItemID/_name carry the parameter identity. Preserve donor IDs where
    # known; zero follows the existing source-driven writer for new named fields.
    row = f'<MaterialParameter{kind} StringItemID="{name}" ItemID="{item_id}" _name="{name}"'
    row += (f' Index="{index}"><ResourceReferencePath_ITexture Name="_value" _path="{value}"/></MaterialParameterTexture>'
            if kind == "Texture" else f' _value="{value}" Index="{index}"/>')
    return append_emission_parameter(block, row)


def _rewrite_block(block, shader, controls, *, static, texture_paths=None):
    parameters = _parameter_rows(block)
    validate_source(shader, controls, parameters, static=static)
    family = family_for(controls.shader)
    if family == EYE_COVER and texture_paths is None:
        raise ValueError("EyeCover requires Create New Item texture preparation.")
    fields = {field.name: field for field in family.fields}
    for name, numbers in controls.values:
        field = fields[name]
        if field.kind == "ExportToggle":
            # These options belong to the New Item plan, never to PAC parameters.
            continue
        if field.kind == "TextureChannel":
            if EYE_COVER_TEXTURE_FIELDS[name][0] not in texture_paths:
                raise ValueError(f"{field.label}: the owned texture override was not prepared.")
            continue
        if field.kind == "Color" and not static:
            existing = parameters.get(name)
            raw = existing.get("_value", "") if existing is not None else ""
            alpha = raw[-2:] if re.fullmatch(r"#[0-9a-fA-F]{8}", raw) else "FF"
            value = "#" + "".join(f"{round(v * 255):02X}" for v in numbers) + alpha
        elif field.kind in {"Byte4", "NormalizedByte4"}:
            existing = parameters.get(name)
            raw = int(existing.get("_value", "128")) if existing is not None else 128
            byte = round(numbers[0] * 255) if field.kind == "NormalizedByte4" else int(numbers[0])
            value = str((raw & 0xFFFFFF00) | byte)
        elif field.kind == "BitFlag32":
            existing = parameters.get(name)
            raw = int(existing.get("Value" if static else "_value", "0")) if existing is not None else 0
            value = str((raw & 0xFFFFFFFE) | int(numbers[0]))
        elif field.kind == "Int":
            value = str(int(numbers[0]))
        else:
            value = " ".join(f"{v:.9g}" for v in numbers)
        kind = "Byte4" if field.kind == "NormalizedByte4" else field.kind
        block = _write_parameter(block, name, kind, value, field.item_id, static=static)
    if family == EYE_COVER:
        if "_eyeCoverDiffuseParameter" not in parameters and "_eyeCoverDiffuseParameter" not in dict(controls.values):
            block = _write_parameter(block, "_eyeCoverDiffuseParameter", "Byte4", "128",
                                     family.fields[0].item_id, static=False)
        for name in ("_alphaTexture", "_materialTexture"):
            if name in texture_paths:
                block = _write_parameter(block, name, "Texture", texture_paths[name], "0", static=False)
            elif name not in parameters:
                raise ValueError(f"EyeCover requires an explicit {name} binding; its game default uses a face texture.")
    if shader != family.shader:
        block, count = re.subn(r'\b_materialName="[^"]*"', f'_materialName="{family.shader}"', block, count=1)
        if count != 1:
            raise ValueError("Cannot identify the equipment material shader.")
        # Explicit defaults avoid inheriting Wing's partially hidden default pose.
        if family.shader == "SkinnedMeshWing" and "_wingFlowProgress" not in dict(controls.values):
            block = _write_parameter(block, "_wingFlowProgress", "Float", "2", "0", static=False)
    # Make inherited mask dependencies visible to the package/preview resolvers.
    if family.mask and family.default_mask and family.mask not in parameters:
        block = _write_parameter(block, family.mask, "Texture", family.default_mask, "0", static=static)
    return block


def rewrite_shader_controls(text, choices, *, static=False, allow_missing=False, texture_paths=None):
    """Return edited XML and matched names. Callers must check cross-file misses."""
    if len(text) > 16 * 1024 * 1024:
        raise ValueError("Material sidecar exceeds the supported size limit.")
    validate_choices(choices)
    settings = {name.casefold(): controls for name, controls in choices}
    blocks = []
    if static:
        for match in re.finditer(r'<Material\b[^>]*\bPrimitiveName="[^"]*"[^>]*>.*?</Material>', text, re.S):
            element = ET.fromstring(match.group())
            common = element.find("Common")
            blocks.append((match.start(), match.end(), element.get("PrimitiveName", ""),
                           common.get("MaterialName", "") if common is not None else ""))
    else:
        blocks = [(w.start, w.end, w.submesh_name, w.shader) for w in find_material_wrappers(text)]
    found, edits = set(), []
    for start, end, name, shader in blocks:
        key = name.casefold()
        if key not in settings:
            continue
        if key in found:
            raise ValueError(f"Ambiguous material binding: {name}")
        found.add(key)
        try:
            replacement = _rewrite_block(text[start:end], shader, settings[key], static=static,
                texture_paths=texture_paths.get(key, {}) if texture_paths is not None else None)
        except (ValueError, ET.ParseError) as exc:
            raise ValueError(f"{name}: {exc}") from exc
        edits.append((start, end, replacement))
    if not allow_missing and settings.keys() - found:
        raise ValueError("Shader material bindings were not found: " + ", ".join(sorted(settings.keys() - found)))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text, found
