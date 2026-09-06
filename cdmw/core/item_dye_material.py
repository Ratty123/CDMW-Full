"""Exact material/submesh dye wiring, preserving shipped shader parameter blocks."""
import re
from cdmw.core.pac_xml_standard_material import find_material_wrappers

_PROPERTY = re.compile(r'<ModelProperty\b[^>]*\bIndex="(\d+)"[^>]*>(.*?)</ModelProperty>', re.S)
_TEXTURE = re.compile(r'(<ResourceReferencePath_ITexture\b[^>]*\b_path=")[^"]*(")')


def material_dye_bindings(raw):
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    result = {}
    for match in _PROPERTY.finditer(text):
        index = int(match.group(1))
        for wrapper in find_material_wrappers(match.group(2)):
            key = index, wrapper.submesh_name
            if key in result:
                raise ValueError("Duplicate material binding in a model property")
            result[key] = wrapper
    if not result:
        raise ValueError("The material's model-property boundaries are unsupported")
    return result


def has_dye_wiring(wrapper):
    return (any(parameter.name.startswith("_dyeing") for parameter in wrapper.parameters)
            and bool(wrapper.textures.get("_colorBlendingMaskTexture") or wrapper.textures.get("_maskTexture")))


def copy_dye_materials(target, source, assignments, mask_paths):
    """Copy only explicit donor materials at the same exact property indices.

Packed shader flags retain the donor's values. A supplied RGB mask changes the
proven color-mask texture parameter, never an inferred or fuzzy material binding.
"""
    source_text, target_text = source.decode("utf-8-sig"), target.decode("utf-8-sig")
    source_properties = {int(match.group(1)): match.group(2) for match in _PROPERTY.finditer(source_text)}
    selected = {entry.target_submesh:entry for entry in assignments}
    seen = set()
    edits = []
    for match in _PROPERTY.finditer(target_text):
        property_index = int(match.group(1))
        source_property = source_properties.get(property_index)
        donors = {w.submesh_name:w for w in find_material_wrappers(source_property or "")}
        for wrapper in find_material_wrappers(match.group(2)):
            entry = selected.get(wrapper.submesh_name)
            if entry is None:
                continue
            donor = donors.get(entry.source_submesh)
            if donor is None or not has_dye_wiring(donor):
                raise ValueError(f"No proven dye material for {entry.source_submesh}, property {property_index}")
            material = source_property[donor.start:donor.end]
            mask = mask_paths.get(entry.target_submesh)
            if mask:
                name = "_colorBlendingMaskTexture" if "_colorBlendingMaskTexture" in donor.textures else "_maskTexture"
                pattern = re.compile(r'(<MaterialParameterTexture\b[^>]*\bStringItemID="'+re.escape(name)+r'"[^>]*>)(.*?)(</MaterialParameterTexture>)',re.S)
                def replace_texture(m):
                    inner,count = _TEXTURE.subn(lambda value:value.group(1)+mask+value.group(2),m.group(2))
                    if count != 1:
                        raise ValueError("The dye mask parameter has an ambiguous resource binding")
                    return m.group(1)+inner+m.group(3)
                material,count = pattern.subn(replace_texture,material)
                if count != 1:
                    raise ValueError("The dye mask parameter is missing or repeated")
            edits.append((match.start(2)+wrapper.start,match.start(2)+wrapper.end,material))
            seen.add(entry.target_submesh)
    if seen != set(selected):
        raise ValueError("Every dye assignment must name an exact target material submesh")
    for start,end,text in sorted(edits,reverse=True):
        target_text = target_text[:start]+text+target_text[end:]
    result = target_text.encode("utf-8")
    material_dye_bindings(result)
    return result
