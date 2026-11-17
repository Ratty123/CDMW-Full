"""Source-preserving PAC_XML/PAMI edits for the decoded shader experiments."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from cdmw.core.pac_xml_emission import append_emission_parameter
from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.mesh.shader_controls import (VEIL_LAYER_FIELDS, VEIL_PRE_PATCH_FIELDS, VEIL_LAYERS_KEY, VEIL_LAYER_TRANSFORMS,
                                             VEIL_REPEAT, VEIL_OFFSET, VEIL_ROTATION, veil_layer_inputs, veil_transform_bytes, NEW_ITEM_FAMILIES, EYE_COVER, EYE_COVER_TEXTURE_FIELDS,
                                             BLENDED_SHADERS, ShaderControls, family_for, validate_choices)


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


def material_variant_blocks(text):
    """PAC model-property variants own separate wrappers with repeating part names."""
    return tuple(re.finditer(r'<ModelProperty\b[^>]*>.*?</ModelProperty>', text, re.S))


def edit_material_variants(text, edit):
    """Run ``edit(fragment) -> (fragment, result)`` once per variant, in file order.

    Part names repeat across variants, so name-keyed edits must never see two
    variants at once. Text without variant blocks is edited as one fragment.
    """
    variants = material_variant_blocks(text)
    if not variants:
        text, result = edit(text)
        return text, (result,)
    results = []
    for match in reversed(variants):
        block = match.group()
        start, end = block.find('>') + 1, len(block) - len('</ModelProperty>')
        fragment, result = edit(block[start:end])
        text = text[:match.start()] + block[:start] + fragment + block[end:] + text[match.end():]
        results.append(result)
    return text, tuple(reversed(results))


def control_material_variants(text, *, static=False):
    variants = () if static else material_variant_blocks(text)
    return tuple(control_material_sources(block.group()) for block in variants) if variants else (control_material_sources(text, static=static),)


def material_source_details(text):
    """Every PAC material wrapper as the file writes it, for the inspector's source view.

    One entry per wrapper in file order: its position among all wrappers
    (``slot``, what the preview's owner index counts), the model variant that
    holds it (``variant`` ordinal and that ModelProperty's ``Index`` text), the
    part name, shader and parameter rows. Nothing is interpreted or defaulted.
    """
    variants = material_variant_blocks(text)
    labels = []
    for ordinal, block in enumerate(variants):
        head = re.match(r'<ModelProperty\b[^>]*>', block.group())
        index = re.search(r'\bIndex="([^"]*)"', head.group()) if head else None
        labels.append(index.group(1) if index else str(ordinal))
    details = []
    for slot, wrapper in enumerate(find_material_wrappers(text)):
        variant = next((ordinal for ordinal, block in enumerate(variants) if block.start() <= wrapper.start < block.end()), 0)
        details.append({
            "slot": slot, "variant": variant, "variant_label": labels[variant] if labels else "",
            "name": wrapper.submesh_name, "shader": wrapper.shader,
            "rows": [{"kind": row.kind, "name": row.name, "item_id": row.item_id, "index": row.index,
                      "value": row.texture_path or row.value} for row in wrapper.parameters],
        })
    return details


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


def equipment_authored_values(text):
    """Parsed authored numbers per part for the editors: {part: {shader: {field: [numbers]}}}.

    Model variants can differ; the first variant that declares a part is shown.
    """
    from cdmw.domain.mesh.shader_controls import authored_values_payload
    result = {}
    for variant in control_material_variants(text):
        for name, (_shader, values, _textures) in variant.items():
            result.setdefault(name, authored_values_payload(values))
    return result


# Shaders a layered equipment material can be converted to once the appearance
# baker has flattened its layers into a plain base, normal and material map.
BAKED_CONVERSION_SHADERS = frozenset({"SkinnedMeshTranslucent", *BLENDED_SHADERS})


def equipment_glass_needs_bake(shader, parameters):
    """Only the decoded equipment layer families can use the appearance baker."""
    return shader in {"SkinnedMeshStandard_Ver2", "SkinnedMeshEmissive_Ver2"} and any(
        name.startswith(("_baseColorTexture", "_overlayColorTexture", "_detailDiffuseMask",
                         "_colorBlendingDiffuse", "_colorBlendingMaskTexture")) for name in parameters)


def validate_source(shader, controls, parameters, *, static=False, allow_bake=False):
    family = family_for(controls.shader)
    if static != (controls.shader in {"Dissolve", "Translucent"}):
        raise ValueError("World-object and equipment shaders use different vertex pipelines.")
    if (allow_bake and controls.shader in BAKED_CONVERSION_SHADERS
            and equipment_glass_needs_bake(shader, parameters)):
        return
    if shader != family.shader:
        plain_sources = {"Standard"} if static else {"SkinnedMeshStandard", "SkinnedMeshEmissive"}
        unsupported = ("_wrinkle", "_overlay", "_colorblending")
        if family.shader in {"Translucent", "SkinnedMeshTranslucent", *BLENDED_SHADERS}:
            unsupported += ("_layer",)
        if family == EYE_COVER or family.shader == "SkinnedMeshGlass":
            plain_sources.add("SkinnedMeshTranslucent")
        if (family.shader not in {"SkinnedMeshWing", EYE_COVER.shader, "Translucent", "SkinnedMeshTranslucent", *BLENDED_SHADERS}
                or shader not in plain_sources
                or "_baseColorTexture" not in parameters
                or any(name.lower().startswith(unsupported) for name in parameters)):
            raise ValueError(f"{family.label} requires {family.shader} or a compatible plain material with a base colour texture.")
    if "_hairDyeingProperty" in dict(controls.values):
        dye = parameters.get("_hairDyeingColor")
        raw = dye.get("_value", "") if dye is not None else ""
        if not re.fullmatch(r"#[0-9a-fA-F]{8}", raw) or int(raw[-2:], 16) == 0:
            raise ValueError("Dye roughness is inactive because the source hair dye alpha is zero. This edit will not enable dye or change its colour.")


def equipment_shader_options(text):
    """Source shader and compatible experiments, using the output writer's rules."""
    variants = material_variant_blocks(text)
    if variants:
        result = {}
        for block in variants:
            for name, (shader, supported) in equipment_shader_options(block.group()[block.group().find('>') + 1:-len('</ModelProperty>')]).items():
                if name in result:
                    before, allowed = result[name]
                    shader = before if before == shader else before + ", " + shader
                    supported = tuple(value for value in allowed if value in supported)
                result[name] = (shader, supported)
        return result
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
                    validate_source(wrapper.shader, ShaderControls(family.shader), parameters, allow_bake=True)
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


# ItemIDs as the game's own veil and crown wrappers carry them.
_VEIL_TRANSFORM_ITEM_IDS = {"_dyeingTransformProperty0": "2380709743296510", "_dyeingTransformProperty1": "2427310400602110",
                            "_dyeingTransformProperty3": "3193012944371710", "_dyeingPropertyBlend": "3323518988058622"}


def _write_veil_layer_transform(block, parameters, edits, *, layered):
    """Store an edited lace repeat, offset or rotation in the bytes of the detail channel in use.

    The other bytes of both rows belong to the other channels and are kept. A
    veil without detail layers does not read these rows, so nothing is added to it.
    """
    scale, offset, turn = veil_transform_bytes(edits.get(VEIL_REPEAT), edits.get(VEIL_OFFSET), edits.get(VEIL_ROTATION))
    if not layered or (scale is None and offset is None and turn is None):
        return block
    values = {name: row.get("_value", "") for name, row in parameters.items()}
    textures = {name: next((child.get("_path", "") for child in row), "") for name, row in parameters.items()}
    channel = veil_layer_inputs("SkinnedMeshTransparency", values, textures).get(VEIL_LAYERS_KEY, "r")

    def raw(name, default):
        try:
            return int(values.get(name, "") or default)
        except ValueError:
            return default

    if scale is not None or offset is not None:
        name = VEIL_LAYER_TRANSFORMS[channel]
        number = raw(name, 0x0000FFFF)  # Definition default: scale 1, offset 0.
        if scale is not None:
            number = (number & 0xFFFF0000) | scale[0] | scale[1] << 8
        if offset is not None:
            number = (number & 0x0000FFFF) | offset[0] << 16 | offset[1] << 24
        block = _write_parameter(block, name, "Byte4", str(number), _VEIL_TRANSFORM_ITEM_IDS[name], static=False)
    if turn is not None:
        shift = 8 * "rgb".index(channel)
        number = (raw("_dyeingPropertyBlend", 0x80808080) & ~(0xFF << shift) & 0xFFFFFFFF) | turn << shift
        block = _write_parameter(block, "_dyeingPropertyBlend", "Byte4", str(number),
                                 _VEIL_TRANSFORM_ITEM_IDS["_dyeingPropertyBlend"], static=False)
    return block


def _has_veil_layers(parameters):
    row = parameters.get("_colorBlendingFlag")
    try:
        flags = int(str(row.get("_value", "0") if row is not None else "0") or "0", 0)
    except ValueError:
        flags = 0
    return bool(flags & 0xFFF) or any(name.startswith("_detailHeightMask") for name in parameters)


def _rewrite_block(block, shader, controls, *, static, texture_paths=None):
    parameters = _parameter_rows(block)
    validate_source(shader, controls, parameters, static=static)
    family = family_for(controls.shader)
    if family == EYE_COVER and texture_paths is None:
        raise ValueError("EyeCover requires Create New Item texture preparation.")
    fields = {field.name: field for field in family.fields}
    # A net veil that draws Ver2 detail layers (November 2026 patch) no longer reads
    # _uvScale and _dyeingColor; one without them does not read the two displacement
    # scales. Neither pair is added where it is not read. A rebuild writes the older layout.
    unread = ()
    if controls.shader == "SkinnedMeshTransparency":
        layered = shader == controls.shader and not controls.rebuild and _has_veil_layers(parameters)
        unread = VEIL_PRE_PATCH_FIELDS if layered else VEIL_LAYER_FIELDS
    edits = controls.effective_values()
    if family.extras:
        block = _write_veil_layer_transform(block, parameters, edits,
                                            layered=bool(unread) and unread is VEIL_PRE_PATCH_FIELDS)
    for name, numbers in edits.items():
        if name not in fields:
            continue  # An extra control, written above.
        field = fields[name]
        if name in unread and name not in parameters:
            continue
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
        if "_eyeCoverDiffuseParameter" not in parameters and "_eyeCoverDiffuseParameter" not in controls.effective_values():
            block = _write_parameter(block, "_eyeCoverDiffuseParameter", "Byte4", "128",
                                     family.fields[0].item_id, static=False)
        for name in ("_alphaTexture", "_materialTexture"):
            if name in texture_paths:
                block = _write_parameter(block, name, "Texture", texture_paths[name], "0", static=False)
            elif name not in parameters:
                raise ValueError(f"EyeCover requires an explicit {name} binding; its game default uses a face texture.")
    if controls.cutout_mask is not None:
        if not texture_paths or not texture_paths.get("_wingFlowTex1"):
            raise ValueError("Painted cutouts require owned mask texture preparation.")
        block = _write_parameter(block, "_wingFlowTex1", "Texture", texture_paths["_wingFlowTex1"], "0", static=False)
    if shader != family.shader:
        pattern = r'(<Common\b[^>]*\bMaterialName=)"[^"]*"' if static else r'(\b_materialName=)"[^"]*"'
        block, count = re.subn(pattern, lambda match: match[1] + f'"{family.shader}"', block, count=1)
        if count != 1:
            raise ValueError("Cannot identify the material shader.")
        # Explicit defaults avoid inheriting Wing's partially hidden default pose.
        if family.shader == "SkinnedMeshWing" and "_wingFlowProgress" not in controls.effective_values():
            block = _write_parameter(block, "_wingFlowProgress", "Float", "2", "0", static=False)
    # Make inherited mask dependencies visible to the package/preview resolvers.
    if family.mask and family.default_mask and family.mask not in parameters and controls.cutout_mask is None:
        block = _write_parameter(block, family.mask, "Texture", family.default_mask, "0", static=static)
    if controls.rebuild:
        if static:
            raise ValueError("Rebuilding the parameter layout is supported on equipment models only.")
        block = rebuild_material_layout(block, family)
    return block


def rebuild_material_layout(block, family):
    """Rewrite one equipment material with the shader's own row set.

    Values come from the block as it stands, so call this after the changed
    fields are written. A row the layout does not list is dropped; a listed row
    takes the layout's ItemID and a fresh Index, in layout order. A field the
    block lacks is written with the shader definition's default, so nothing is
    left to an engine default that has not been observed.
    """
    from cdmw.domain.mesh.shader_controls import LAYOUT_PERMUTATIONS, SHADER_LAYOUTS
    layout = SHADER_LAYOUTS.get(family.shader)
    if layout is None:
        raise ValueError("This shader has no known parameter layout to rebuild from.")
    vector = re.search(r'<Vector Name="_parameters"\s*(?:/>|>(?P<body>.*?)</Vector>)', block, re.S)
    if vector is None or "<Vector" in (vector.group("body") or ""):
        raise ValueError("Cannot identify the material's parameter block.")
    existing = _parameter_rows(block)
    if "_baseColorTexture" not in existing:
        raise ValueError("Rebuilding needs a source material with a base colour texture.")
    fields = {field.name: field for field in family.fields}
    indent = re.search(r'\n[ \t]*(?=<MaterialParameter)', vector.group("body") or "")
    indent = indent.group() if indent else ""
    rows = []
    for kind, name, item_id, default in layout:
        old = existing.get(name)
        if kind == "Field":
            field = fields[name]
            kind, item_id = field.kind, field.item_id
            if old is not None:
                value = old.get("_value", "")
            elif kind == "Color":
                value = "#" + "".join(f"{round(v * 255):02X}" for v in field.default) + "FF"
            else:
                value = " ".join(f"{v:.9g}" for v in field.default)
        elif kind == "Texture":
            child = old.find("ResourceReferencePath_ITexture") if old is not None else None
            value = child.get("_path", "") if child is not None else default
        else:
            value = old.get("_value", "") if old is not None else default
        if value is None or (old is not None and old.tag != "MaterialParameter" + kind):
            if value is None:
                continue
            raise ValueError(f"{name}: source parameter type does not match the decoded shader.")
        value = escape(value, {'"': "&quot;"})
        head = f'<MaterialParameter{kind} StringItemID="{name}" ItemID="{item_id}" _name="{name}"'
        rows.append(head + (f' Index="{len(rows)}"><ResourceReferencePath_ITexture Name="_value" _path="{value}"/>'
                            f'</MaterialParameterTexture>' if kind == "Texture"
                            else f' _value="{value}" Index="{len(rows)}"/>'))
    # The vector's own closing tag sits one level out from its rows.
    body = "".join(indent + row for row in rows) + (indent[:-1] if indent.endswith("\t") else indent)
    block = block[:vector.start()] + '<Vector Name="_parameters">' + body + "</Vector>" + block[vector.end():]
    permutations = re.search(r'<Vector Name="_permutations"\s*(?:/>|>.*?</Vector>)', block, re.S)
    if permutations is None:
        raise ValueError("Cannot identify the material's permutation block.")
    listed = "".join(f'<MaterialParameter{kind} StringItemID="{name}" ItemID="{item_id}" _name="{name}" Index="{index}"/>'
                     for index, (kind, name, item_id) in enumerate(LAYOUT_PERMUTATIONS))
    return block[:permutations.start()] + '<Vector Name="_permutations">' + listed + "</Vector>" + block[permutations.end():]


def rewrite_texture_paths(text, paths):
    """Point named equipment materials' texture parameters at other archive paths.

    ``paths`` maps a casefolded submesh name to {parameter: archive path}. Every
    model variant is edited alike. An existing row keeps its ItemID and Index; a
    missing one is appended as the shader writer appends them. Returns the
    edited XML and the names found.
    """
    variants = material_variant_blocks(text)
    if variants:
        found = set()
        for match in reversed(variants):
            block = match.group()
            start, end = block.find('>') + 1, -len('</ModelProperty>')
            edited, matched = rewrite_texture_paths(block[start:end], paths)
            found.update(matched)
            text = text[:match.start()] + block[:start] + edited + block[end:] + text[match.end():]
        return text, found
    found, edits = set(), []
    for wrapper in find_material_wrappers(text):
        key = wrapper.submesh_name.casefold()
        if key not in paths:
            continue
        if key in found:
            raise ValueError(f"Ambiguous material binding: {wrapper.submesh_name}")
        found.add(key)
        block = text[wrapper.start:wrapper.end]
        for name, path in paths[key].items():
            try:
                block = _write_parameter(block, name, "Texture", path, "0", static=False)
            except (ValueError, ET.ParseError) as exc:
                raise ValueError(f"{wrapper.submesh_name}: {exc}") from exc
        edits.append((wrapper.start, wrapper.end, block))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text, found


def rewrite_shader_controls(text, choices, *, static=False, allow_missing=False, texture_paths=None):
    """Return edited XML and matched names. Callers must check cross-file misses."""
    if len(text) > 16 * 1024 * 1024:
        raise ValueError("Material sidecar exceeds the supported size limit.")
    validate_choices(choices)
    settings = {name.casefold(): controls for name, controls in choices}
    variants = () if static else material_variant_blocks(text)
    if variants:
        found = set()
        for match in reversed(variants):
            block = match.group()
            start, end = block.find('>') + 1, -len('</ModelProperty>')
            edited, matched = rewrite_shader_controls(block[start:end], choices, allow_missing=True, texture_paths=texture_paths)
            found.update(matched)
            text = text[:match.start()] + block[:start] + edited + block[end:] + text[match.end():]
        if not allow_missing and settings.keys() - found:
            raise ValueError("Shader material bindings were not found: " + ", ".join(sorted(settings.keys() - found)))
        return text, found
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
