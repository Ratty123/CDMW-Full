"""Preserving edits to the material-local equipment emission parameters."""
from __future__ import annotations

import re
from xml.sax.saxutils import escape

from cdmw.core.pac_xml_standard_material import PacXmlMaterialError, find_material_wrappers

# IDs and types retained from decoded shipped PAC_XML donors.
ANIMATION_PARAMETERS = (
    ("_emissiveFlowSpeedU", "1140313039044606"),
    ("_emissiveFlowSpeedV", "892034994929662"),
    ("_emissiveFlickeringFreq", "2437966152597502"),
    ("_emissiveFlickeringIntensityMin", "1771470289108990"),
)


def append_emission_parameter(block, row):
    """Insert into the actual parameter vector, including an empty vector."""
    header = re.search(r'<Vector\b[^>]*\bName="_parameters"[^>]*>', block)
    if header is None:
        raise PacXmlMaterialError("The material has no editable parameter vector.")
    newline = "\r\n" if "\r\n" in block else "\n"
    if header.group().endswith("/>"):
        return block[:header.start()] + header.group()[:-2] + ">" + newline + row + newline + "</Vector>" + block[header.end():]
    depth = 1
    for tag in re.finditer(r'<(/?)Vector\b[^>]*>', block[header.end():]):
        if tag.group(1):
            depth -= 1
        elif not tag.group().endswith("/>"):
            depth += 1
        if depth == 0:
            end = header.end() + tag.start()
            return block[:end] + row + newline + block[end:]
    raise PacXmlMaterialError("The material parameter vector is incomplete.")


def validate_emission_shader(wrapper, *, animated=False):
    allowed = {"SkinnedMeshStandard", "SkinnedMeshStandard_Ver2",
               "SkinnedMeshEmissive", "SkinnedMeshEmissive_Ver2"}
    if not animated:
        allowed.add("SkinnedMeshTranslucent")
    if wrapper.shader not in allowed:
        raise PacXmlMaterialError(
            f"{wrapper.submesh_name}: {wrapper.shader} does not support this glow edit. "
            "Animated glow requires an equipment Emissive material and cannot share a part with translucency.")
    if wrapper.shader.startswith("SkinnedMeshStandard") and any(
            p.name.lower().startswith("_wrinkle") for p in wrapper.parameters):
        raise PacXmlMaterialError(
            f"{wrapper.submesh_name}: switching to animated/emissive material would lose wrinkle controls. "
            "Use a Plain PBR material or another part.")


def rewrite_emission_animation(text, settings):
    """Write explicit zeros too, so choosing static cancels a donor's animation."""
    if len(text) > 16 * 1024 * 1024:
        raise PacXmlMaterialError("Glow material sidecar exceeds the supported size limit.")
    settings = {name.casefold(): value for name, value in settings.items()}
    found, edits = set(), []
    for wrapper in find_material_wrappers(text):
        name = wrapper.submesh_name.casefold()
        if name not in settings:
            continue
        animation = settings[name]
        animation.validate()
        validate_emission_shader(wrapper, animated=animation.active)
        found.add(name)
        if wrapper.shader == "SkinnedMeshTranslucent":
            continue
        block = text[wrapper.start:wrapper.end]
        for (parameter, item_id), value in zip(ANIMATION_PARAMETERS, animation.factors()):
            pattern = r'<MaterialParameterFloat\b[^>]*\bStringItemID="' + parameter + r'"[^>]*/>'
            block = re.sub(pattern, "", block)
            index = max((int(v) for v in re.findall(r'\bIndex="(\d+)"', block)), default=-1) + 1
            row = (f'<MaterialParameterFloat StringItemID="{parameter}" ItemID="{item_id}" '
                   f'_name="{parameter}" _value="{value:.6f}" Index="{index}"/>')
            block = append_emission_parameter(block, row)
        edits.append((wrapper.start, wrapper.end, block))
    if settings.keys() - found:
        raise PacXmlMaterialError("Glow material bindings were not found: " + ", ".join(sorted(settings.keys() - found)))
    for start, end, block in reversed(edits):
        text = text[:start] + block + text[end:]
    return text


def rewrite_rgb_emission(text, settings):
    """Use the existing glow texture for RGB and its red channel for reveal.

    Keep the intensity texture binding so restored monochrome glow and dependency
    discovery refer to the same resource. The zero base intensity prevents double glow.
    """
    settings = {name.casefold(): value for name, value in settings.items()}
    edits, found = [], set()
    for wrapper in find_material_wrappers(text):
        name = wrapper.submesh_name.casefold()
        if name not in settings:
            continue
        rgb, color = settings[name]
        if rgb is not None:
            rgb.validate()
        validate_emission_shader(wrapper, animated=rgb is not None)
        if wrapper.shader == "SkinnedMeshTranslucent" and rgb is None:
            found.add(name)
            continue
        texture = wrapper.textures.get("_emissiveIntensityTexture", "")
        if not texture and rgb is not None:
            raise PacXmlMaterialError(f"{wrapper.submesh_name}: RGB glow needs a source glow texture.")
        found.add(name)
        entries = (("Float", "_emissiveProgressGauge", "3757690423607294", "0.000000"),) if rgb is None else (
            ("Texture", "_emissiveProgressTexture", "3954849808908286", texture),
            ("Texture", "_emissiveProgressMaskTexture", "3376939046797310", texture),
            ("Color", "_emissiveProgressColor", "1897722707705854", color),
            ("Float", "_emissiveIntensity", "3419583792807934", "0.000000"),
            ("Float", "_emissiveProgressIntensity", "2869121302659070", f"{rgb.intensity:.6f}"),
            ("Float", "_emissiveProgressGauge", "3757690423607294", f"{rgb.reveal:.6f}"),
            ("Float", "_emissiveMaskHardness", "1782260911046654", f"{rgb.softness:.6f}"),
            ("Int", "_emissiveMaskInverse", "3150543907192830", str(int(rgb.inverse))),
        )
        block = text[wrapper.start:wrapper.end]
        for kind, parameter, item_id, value in entries:
            pattern = (r'<MaterialParameter' + kind + r'\b[^>]*\bStringItemID="' + parameter + r'"[^>]*'
                       + (r'>.*?</MaterialParameterTexture>' if kind == "Texture" else r'/>'))
            block = re.sub(pattern, "", block, flags=re.S)
            index = max((int(v) for v in re.findall(r'\bIndex="(\d+)"', block)), default=-1) + 1
            row = f'<MaterialParameter{kind} StringItemID="{parameter}" ItemID="{item_id}" _name="{parameter}"'
            value = escape(value, {'"': "&quot;"})
            row += (f' Index="{index}"><ResourceReferencePath_ITexture Name="_value" _path="{value}"/></MaterialParameterTexture>'
                    if kind == "Texture" else f' _value="{value}" Index="{index}"/>')
            block = append_emission_parameter(block, row)
        edits.append((wrapper.start, wrapper.end, block))
    if settings.keys() - found:
        raise PacXmlMaterialError("RGB glow material bindings were not found: " + ", ".join(sorted(settings.keys() - found)))
    for start, end, block in reversed(edits):
        text = text[:start] + block + text[end:]
    return text
