"""Material sidecar patching and wrapper-parameter helpers."""

from __future__ import annotations

import re
from typing import Optional, Sequence

from .material_profiles import (
    CDMaterialRuntimeProfile,
    _format_profile_color_hex,
    _profile_applies_source_pbr_scalars_with_preserved_layers,
    _profile_displacement_scale_max,
    _profile_displacement_scale_multiplier,
    _profile_neutral_color_rgb,
    _profile_preserves_target_layer_response,
    normalize_basic_control_percent,
    normalize_edge_relief_source,
)


def _normalize_texture_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


_SOURCE_MATERIAL_OVERRIDE_SLOT_ALIASES = {
    "basecolor": "base",
    "base_color": "base",
    "color": "base",
    "colour": "base",
    "diffuse": "base",
    "albedo": "base",
    "normalmap": "normal",
    "normal_map": "normal",
    "nrm": "normal",
    "heightmap": "height",
    "height_map": "height",
    "displacement": "height",
    "disp": "height",
    "materialmask": "material_mask",
    "material_mask": "material_mask",
    "mask_amg": "material_mask",
    "detailmask": "detail_mask",
    "detail_mask": "detail_mask",
    "detailmaterial": "detail_mask",
    "occlusion": "ao",
    "ambientocclusion": "ao",
    "ambient_occlusion": "ao",
    "specularglossiness": "material",
    "specular_glossiness": "material",
    "specular": "specular",
    "glossiness": "glossiness",
    "gloss": "glossiness",
    "smoothness": "glossiness",
    "metalness": "metalness",
    "metallic": "metallic",
    "roughness": "roughness",
    "opacity": "opacity",
    "alpha": "opacity",
    "specgloss": "material",
    "clearcoat": "material",
    "clear_coat": "material",
    "emission": "emissive",
    "emissive": "emissive",
    "glow": "emissive",
    "illum": "emissive",
    "illumination": "emissive",
}



def _material_tokens(value: str) -> set[str]:
    stop_words = {
        "cd",
        "phm",
        "pc",
        "texture",
        "material",
        "mesh",
        "obj",
        "dds",
        "png",
        "source",
        "target",
        "donor",
        "original",
        "replacement",
    }
    tokens: set[str] = set()
    for raw_token in re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split():
        token = re.sub(r"\d+$", "", raw_token.strip())
        if len(token) > 1 and token not in stop_words and not token.isdigit():
            tokens.add(token)
    return tokens


def _set_source_driven_wrapper_shader_name(wrapper_text: str, shader_name: str) -> str:
    shader = str(shader_name or "").strip()
    if not shader:
        return wrapper_text
    if re.search(r'(<Material\b[^>]*\b_materialName=")([^"]*)(")', wrapper_text, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(
            r'(<Material\b[^>]*\b_materialName=")([^"]*)(")',
            lambda match: f"{match.group(1)}{shader}{match.group(3)}",
            wrapper_text,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return re.sub(
        r"(<Material\b)",
        lambda match: f'{match.group(1)} _materialName="{_escape_xml_attr(shader)}"',
        wrapper_text,
        count=1,
        flags=re.IGNORECASE,
    )



def _source_driven_parameter_item_id(parameter_name: str) -> str:
    normalized = str(parameter_name or "").strip().lower()
    return {
        "_overlaycolortexture": "1",
        "_normaltexture": "6",
        "_heighttexture": "4",
        "_colorblendingmasktexture": "3936485985222654",
        "_detailmasktexture": "2838988925698046",
        "_emissivetexture": "271587251638718",
        "_emissiveintensitytexture": "1638159983050750",
        "_emissiveprogresstexture": "370587223877118",
        "_materialtexture": "3401228360876030",
        "_metallictexture": "488189023223806",
        "_roughnesstexture": "638052851515390",
        "_ambientocclusiontexture": "1028073018359806",
    }.get(normalized, "0")



def _inject_sidecar_texture_parameter(
    sidecar_text: str,
    injection: SidecarTextureParameterInjection,
    report: SidecarPatchReport,
) -> tuple[str, bool]:
    target_name = str(injection.target_material_name or "").strip()
    texture_path = str(injection.texture_path or "").strip()
    parameter_name = str(injection.parameter_name or "_overlayColorTexture").strip() or "_overlayColorTexture"
    if not target_name or not texture_path:
        return sidecar_text, False
    wrapper_match = _find_sidecar_material_wrapper(sidecar_text, target_name)
    if wrapper_match is None:
        wrapper_match = _find_sidecar_material_wrapper_by_texture_paths(
            sidecar_text,
            getattr(injection, "anchor_texture_paths", ()) or (),
        )
    if wrapper_match is None:
        report.warnings.append(f"Could not find sidecar material wrapper for injected texture target: {target_name}")
        return sidecar_text, False
    wrapper_text = wrapper_match.group(0)
    if re.search(
        rf'(?:_name|StringItemID|Name|name)="{re.escape(parameter_name)}"',
        wrapper_text,
        flags=re.IGNORECASE,
    ):
        report.unchanged_count += 1
        return sidecar_text, False
    template = _sidecar_texture_parameter_template(sidecar_text, parameter_name)
    parameter_vector_match = re.search(
        r'(<Vector\b[^>]*(?:Name|name|_name)="_parameters"[^>]*>)(.*?)(\s*</Vector>)',
        wrapper_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if parameter_vector_match is None:
        report.warnings.append(f"Could not find _parameters vector for injected texture target: {target_name}")
        return sidecar_text, False
    parameter_body = parameter_vector_match.group(2)
    insert_offset_in_body, insert_index = _sidecar_texture_injection_position(parameter_body, parameter_name)
    if insert_index is None:
        insert_index = _next_material_parameter_index(wrapper_text)
    parameter_text = _retarget_texture_parameter_template(template, parameter_name, texture_path, insert_index)
    if insert_offset_in_body is not None:
        parameter_body = _shift_sidecar_parameter_indexes(parameter_body, insert_index)
        new_parameter_body = (
            parameter_body[:insert_offset_in_body]
            + "\n\t\t\t\t\t\t\t"
            + parameter_text
            + parameter_body[insert_offset_in_body:]
        )
    else:
        new_parameter_body = parameter_body + "\n\t\t\t\t\t\t\t" + parameter_text
    new_wrapper_text = (
        wrapper_text[: parameter_vector_match.start(2)]
        + new_parameter_body
        + wrapper_text[parameter_vector_match.end(2) :]
    )
    return (
        sidecar_text[: wrapper_match.start()]
        + new_wrapper_text
        + sidecar_text[wrapper_match.end() :],
        True,
    )


def _find_sidecar_material_wrapper_by_texture_paths(
    sidecar_text: str,
    texture_paths: Sequence[str],
) -> Optional[re.Match[str]]:
    normalized_paths = {
        _normalize_texture_path(texture_path)
        for texture_path in texture_paths
        if _normalize_texture_path(texture_path)
    }
    if not normalized_paths:
        return None
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>.*?</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    best_match: Optional[re.Match[str]] = None
    best_score = 0
    for match in wrapper_pattern.finditer(sidecar_text):
        wrapper_paths = {
            _normalize_texture_path(path)
            for path in re.findall(r'\b_path="([^"]*)"', match.group(0), flags=re.IGNORECASE)
            if _normalize_texture_path(path)
        }
        score = len(normalized_paths & wrapper_paths)
        if score > best_score:
            best_match = match
            best_score = score
    return best_match if best_score > 0 else None


def _rename_sidecar_texture_parameter(
    sidecar_text: str,
    rename: SidecarTextureParameterRename,
    report: SidecarPatchReport,
) -> tuple[str, bool]:
    target_name = str(rename.target_material_name or "").strip()
    texture_path = str(rename.texture_path or "").replace("\\", "/").strip()
    old_parameter_name = str(rename.old_parameter_name or "").strip()
    new_parameter_name = str(rename.new_parameter_name or "").strip()
    if not target_name or not texture_path or not old_parameter_name or not new_parameter_name:
        return sidecar_text, False
    wrapper_match = _find_sidecar_material_wrapper(sidecar_text, target_name)
    if wrapper_match is None:
        return _rename_sidecar_texture_parameter_by_path(sidecar_text, rename, report)
    wrapper_text = wrapper_match.group(0)
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in texture_pattern.finditer(wrapper_text):
        block = match.group(0)
        block_path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
        block_path = str(block_path_match.group(1) if block_path_match else "").replace("\\", "/").strip()
        block_name = _sidecar_parameter_name(block)
        if block_path != texture_path:
            continue
        if block_name.lower() == new_parameter_name.lower():
            report.unchanged_count += 1
            return sidecar_text, False
        if block_name.lower() != old_parameter_name.lower():
            continue
        renamed_block = _rename_sidecar_parameter_name(block, new_parameter_name)
        new_wrapper_text = wrapper_text[: match.start()] + renamed_block + wrapper_text[match.end() :]
        return (
            sidecar_text[: wrapper_match.start()]
            + new_wrapper_text
            + sidecar_text[wrapper_match.end() :],
            True,
        )
    report.warnings.append(
        f"Could not find {old_parameter_name} texture parameter for {target_name}: {texture_path}"
    )
    return sidecar_text, False


def _rename_sidecar_texture_parameter_by_path(
    sidecar_text: str,
    rename: SidecarTextureParameterRename,
    report: SidecarPatchReport,
) -> tuple[str, bool]:
    texture_path = str(rename.texture_path or "").replace("\\", "/").strip()
    old_parameter_name = str(rename.old_parameter_name or "").strip()
    new_parameter_name = str(rename.new_parameter_name or "").strip()
    if not texture_path or not old_parameter_name or not new_parameter_name:
        return sidecar_text, False
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in texture_pattern.finditer(sidecar_text):
        block = match.group(0)
        block_path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
        block_path = str(block_path_match.group(1) if block_path_match else "").replace("\\", "/").strip()
        if block_path != texture_path:
            continue
        block_name = _sidecar_parameter_name(block)
        if block_name.lower() == new_parameter_name.lower():
            report.unchanged_count += 1
            return sidecar_text, False
        if block_name.lower() != old_parameter_name.lower():
            continue
        renamed_block = _rename_sidecar_parameter_name(block, new_parameter_name)
        return sidecar_text[: match.start()] + renamed_block + sidecar_text[match.end() :], True
    report.warnings.append(
        f"Could not find {old_parameter_name} texture parameter by path for {rename.target_material_name}: {texture_path}"
    )
    return sidecar_text, False


def _prune_unmapped_sidecar_texture_parameters(
    sidecar_text: str,
    keep_rules: Sequence[tuple[str, str]],
) -> tuple[str, int]:
    keep = {
        (str(parameter or "").strip().lower(), _normalize_texture_path(texture_path))
        for parameter, texture_path in keep_rules
        if str(parameter or "").strip() and _normalize_texture_path(texture_path)
    }
    texture_pattern = re.compile(
        r"\s*<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    removed_count = 0

    def replace_parameter(match: re.Match[str]) -> str:
        nonlocal removed_count
        block = match.group(0)
        parameter_name = _sidecar_parameter_name(block).lower()
        path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
        texture_path = _normalize_texture_path(path_match.group(1) if path_match else "")
        if (parameter_name, texture_path) in keep:
            return block
        removed_count += 1
        return ""

    patched = texture_pattern.sub(replace_parameter, sidecar_text)
    if removed_count:
        patched = _renumber_sidecar_parameter_indexes(patched)
    return patched, removed_count


def _prune_unmapped_sidecar_texture_parameters_for_materials(
    sidecar_text: str,
    *,
    material_names: Sequence[str],
    keep_rules: Sequence[tuple[str, str]],
) -> tuple[str, int]:
    target_keys = {
        _normalize_sidecar_material_name(str(name or ""))
        for name in tuple(material_names or ())
        if str(name or "").strip()
    }
    if not target_keys:
        return sidecar_text, 0
    keep = {
        (str(parameter or "").strip().lower(), _normalize_texture_path(texture_path))
        for parameter, texture_path in tuple(keep_rules or ())
        if str(parameter or "").strip() and _normalize_texture_path(texture_path)
    }
    wrapper_pattern = re.compile(
        r"(<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>)(?P<body>.*?)(</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    texture_pattern = re.compile(
        r"\s*<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    removed_count = 0

    def wrapper_selected(attrs: str, body: str) -> bool:
        name_match = re.search(
            r'(?:_subMeshName|subMeshName|SubMeshName|_submesh|submesh|MaterialName|materialName|Name|name)="([^"]+)"',
            attrs + " " + body[:400],
            flags=re.IGNORECASE,
        )
        wrapper_name = str(name_match.group(1) if name_match else "")
        wrapper_key = _normalize_sidecar_material_name(wrapper_name)
        if wrapper_key in target_keys:
            return True
        return any(_sidecar_material_names_match(wrapper_name, target_name) for target_name in target_keys)

    def prune_wrapper(match: re.Match[str]) -> str:
        nonlocal removed_count
        attrs = match.group("attrs")
        body = match.group("body")
        if not wrapper_selected(attrs, body):
            return match.group(0)

        def replace_parameter(texture_match: re.Match[str]) -> str:
            nonlocal removed_count
            block = texture_match.group(0)
            parameter_name = _sidecar_parameter_name(block).lower()
            path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
            texture_path = _normalize_texture_path(path_match.group(1) if path_match else "")
            if (parameter_name, texture_path) in keep:
                return block
            removed_count += 1
            return ""

        patched_body = texture_pattern.sub(replace_parameter, body)
        if patched_body != body:
            patched_body = _renumber_sidecar_parameter_indexes(patched_body)
        return f"{match.group(1)}{patched_body}{match.group(5)}"

    return wrapper_pattern.sub(prune_wrapper, sidecar_text), removed_count


def _material_wrapper_block_pattern() -> re.Pattern[str]:
    return re.compile(
        r"\s*<[A-Za-z0-9_:.-]*MaterialWrapper\b[^>]*/>"
        r"|\s*<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>.*?</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )


def _material_wrapper_name(wrapper_text: str) -> str:
    open_match = re.search(r"<[A-Za-z0-9_:.-]*MaterialWrapper\b(?P<attrs>[^>]*)>", str(wrapper_text or ""), flags=re.IGNORECASE | re.DOTALL)
    attrs = str(open_match.group("attrs") if open_match else "")
    name_match = re.search(
        r'(?:_subMeshName|subMeshName|SubMeshName|_submesh|submesh|MaterialName|materialName|Name|name)="([^"]+)"',
        attrs,
        flags=re.IGNORECASE,
    )
    return str(name_match.group(1) if name_match else "").strip()


def _prune_source_owned_sidecar_material_wrappers(
    sidecar_text: str,
    *,
    keep_material_names: Sequence[str],
) -> tuple[str, list[str]]:
    if "<ModelProperty" not in str(sidecar_text or "") or "<SkinnedMeshMaterialWrapper" not in str(sidecar_text or ""):
        return sidecar_text, []
    keep_keys = {
        _normalize_sidecar_material_name(str(name or ""))
        for name in tuple(keep_material_names or ())
        if str(name or "").strip()
    }
    if not keep_keys:
        return sidecar_text, []
    wrapper_pattern = _material_wrapper_block_pattern()
    removed_names: list[str] = []

    def prune_wrapper(match: re.Match[str]) -> str:
        wrapper_name = _material_wrapper_name(match.group(0))
        wrapper_key = _normalize_sidecar_material_name(wrapper_name)
        if wrapper_key in keep_keys:
            return match.group(0)
        removed_names.append(wrapper_name or "unnamed wrapper")
        return ""

    patched = wrapper_pattern.sub(prune_wrapper, str(sidecar_text or ""))
    return patched, removed_names


def _reorder_source_owned_sidecar_material_wrappers(
    sidecar_text: str,
    *,
    ordered_material_names: Sequence[str],
) -> tuple[str, int]:
    text = str(sidecar_text or "")
    ordered_keys: dict[str, int] = {}
    for index, name in enumerate(tuple(ordered_material_names or ())):
        key = _normalize_sidecar_material_name(str(name or ""))
        if key and key not in ordered_keys:
            ordered_keys[key] = index
    if not ordered_keys or "<SkinnedMeshMaterialWrapper" not in text:
        return text, 0

    wrapper_pattern = _material_wrapper_block_pattern()

    def wrapper_key(wrapper_text: str) -> str:
        return _normalize_sidecar_material_name(_material_wrapper_name(wrapper_text))

    def reorder_vector_body(body: str) -> tuple[str, bool]:
        matches = list(wrapper_pattern.finditer(body))
        if len(matches) <= 1:
            return body, False
        indexed = list(enumerate(matches))
        sorted_matches = sorted(
            indexed,
            key=lambda item: (
                ordered_keys.get(wrapper_key(item[1].group(0)), len(ordered_keys) + item[0]),
                item[0],
            ),
        )
        if [match.start() for _index, match in sorted_matches] == [match.start() for match in matches]:
            return body, False
        first_start = matches[0].start()
        last_end = matches[-1].end()
        reordered_blocks = "".join(match.group(0) for _index, match in sorted_matches)
        return body[:first_start] + reordered_blocks + body[last_end:], True

    tag_pattern = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_:.-]+)\b([^>]*)>", flags=re.IGNORECASE | re.DOTALL)
    stack: list[tuple[str, bool, int, int]] = []
    replacements: list[tuple[int, int, str]] = []
    for match in tag_pattern.finditer(text):
        is_close = bool(match.group(1))
        tag = match.group(2).split(":")[-1].lower()
        attrs = match.group(3) or ""
        if is_close:
            for index in range(len(stack) - 1, -1, -1):
                open_tag, is_target, _start, open_end = stack[index]
                if open_tag.lower() != tag:
                    continue
                del stack[index:]
                if is_target:
                    body = text[open_end:match.start()]
                    reordered, changed = reorder_vector_body(body)
                    if changed:
                        replacements.append((open_end, match.start(), reordered))
                break
            continue
        if attrs.rstrip().endswith("/"):
            continue
        is_target = (
            tag == "vector"
            and re.search(r'\b(?:Name|name|_name)="_subMeshResources"', attrs, flags=re.IGNORECASE) is not None
        )
        stack.append((tag, is_target, match.start(), match.end()))

    patched = text
    for start, end, replacement in reversed(replacements):
        patched = patched[:start] + replacement + patched[end:]
    return patched, len(replacements)


def _sync_submesh_resources_vector_idbase(sidecar_text: str) -> tuple[str, int]:
    text = str(sidecar_text or "")
    tag_pattern = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_:.-]+)\b([^>]*)>", flags=re.IGNORECASE | re.DOTALL)
    stack: list[tuple[str, bool, int, int]] = []
    replacements: list[tuple[int, int, str]] = []

    def sync_open_tag(open_tag: str, body: str) -> str:
        item_ids: list[int] = []
        for item_match in re.finditer(r"<SkinnedMeshMaterialWrapper\b[^>]*\bItemID=\"(\d+)\"", body, flags=re.IGNORECASE | re.DOTALL):
            try:
                item_ids.append(int(item_match.group(1)))
            except ValueError:
                continue
        if not item_ids:
            return open_tag
        required_idbase = max(item_ids)
        idbase_match = re.search(r'\bIdBase="(\d+)"', open_tag, flags=re.IGNORECASE)
        if idbase_match is not None:
            try:
                current_idbase = int(idbase_match.group(1))
            except ValueError:
                current_idbase = -1
            if current_idbase >= required_idbase:
                return open_tag
            return re.sub(
                r'\bIdBase="\d+"',
                f'IdBase="{required_idbase}"',
                open_tag,
                count=1,
                flags=re.IGNORECASE,
            )
        return open_tag[:-1] + f' IdBase="{required_idbase}">'

    for match in tag_pattern.finditer(text):
        is_close = bool(match.group(1))
        tag = match.group(2).split(":")[-1].lower()
        attrs = match.group(3) or ""
        if is_close:
            for index in range(len(stack) - 1, -1, -1):
                open_tag, is_target, start, open_end = stack[index]
                if open_tag.lower() != tag:
                    continue
                del stack[index:]
                if is_target:
                    old_open = text[start:open_end]
                    body = text[open_end:match.start()]
                    new_open = sync_open_tag(old_open, body)
                    if new_open != old_open:
                        replacements.append((start, open_end, new_open))
                break
            continue
        self_closing = attrs.rstrip().endswith("/")
        if self_closing:
            continue
        is_target = (
            tag == "vector"
            and re.search(r'\b(?:Name|name|_name)="_subMeshResources"', attrs, flags=re.IGNORECASE) is not None
        )
        stack.append((tag, is_target, match.start(), match.end()))

    patched = text
    for start, end, replacement in reversed(replacements):
        patched = patched[:start] + replacement + patched[end:]
    return patched, len(replacements)


def _apply_source_pbr_scalar_parameters(
    sidecar_text: str,
    *,
    material_names: Sequence[str],
    roughness_value: Optional[int] = None,
    metallic_value: Optional[int] = None,
    shine_value: Optional[float] = None,
    exact_only: bool = False,
) -> tuple[str, int]:
    target_keys = {
        _normalize_sidecar_material_name(str(name or ""))
        for name in tuple(material_names or ())
        if str(name or "").strip()
    }
    if not target_keys:
        return sidecar_text, 0
    wrapper_pattern = re.compile(
        r"(<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>)(?P<body>.*?)(</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    edited_wrappers = 0

    def wrapper_selected(attrs: str) -> bool:
        name_match = re.search(r'\b_subMeshName="([^"]*)"', attrs, flags=re.IGNORECASE)
        wrapper_name = str(name_match.group(1) if name_match else "")
        wrapper_key = _normalize_sidecar_material_name(wrapper_name)
        if wrapper_key in target_keys:
            return True
        if exact_only:
            return False
        return any(_sidecar_material_names_match(wrapper_name, target_name) for target_name in target_keys)

    def set_or_insert_byte4(body: str, parameter_name: str, item_id: str, value: int) -> tuple[str, bool]:
        parameter_pattern = re.compile(
            rf'(<MaterialParameterByte4\b[^>]*_name="{re.escape(parameter_name)}"[^>]*_value=")([^"]*)(")',
            flags=re.IGNORECASE | re.DOTALL,
        )
        replaced_body, replace_count = parameter_pattern.subn(rf"\g<1>{int(value)}\3", body)
        if replace_count:
            return replaced_body, True
        insertion = (
            f'\n\t\t\t\t\t\t\t<MaterialParameterByte4 StringItemID="{parameter_name}" '
            f'ItemID="{item_id}" _name="{parameter_name}" _value="{int(value)}" Index="0"/>'
        )
        vector_close = re.search(r"</Vector>", body, flags=re.IGNORECASE)
        if vector_close:
            insert_at = vector_close.start()
            return body[:insert_at] + insertion + body[insert_at:], True
        return body + insertion, True

    def set_or_insert_float(body: str, parameter_name: str, item_id: str, value: float) -> tuple[str, bool]:
        replacement_value = f"{max(0.0, min(1.0, float(value))):.6f}"
        parameter_pattern = re.compile(
            rf'(<MaterialParameterFloat\b[^>]*_name="{re.escape(parameter_name)}"[^>]*_value=")([^"]*)(")',
            flags=re.IGNORECASE | re.DOTALL,
        )
        replaced_body, replace_count = parameter_pattern.subn(rf"\g<1>{replacement_value}\3", body)
        if replace_count:
            return replaced_body, True
        insertion = (
            f'\n\t\t\t\t\t\t\t<MaterialParameterFloat StringItemID="{parameter_name}" '
            f'ItemID="{item_id}" _name="{parameter_name}" _value="{replacement_value}" Index="0"/>'
        )
        vector_close = re.search(r"</Vector>", body, flags=re.IGNORECASE)
        if vector_close:
            insert_at = vector_close.start()
            return body[:insert_at] + insertion + body[insert_at:], True
        return body + insertion, True

    def replace_existing_float(body: str, parameter_names: Sequence[str], value: float) -> tuple[str, bool]:
        replacement_value = f"{max(0.0, min(1.0, float(value))):.6f}"
        changed = False
        patched = body
        for parameter_name in tuple(parameter_names or ()):
            parameter_pattern = re.compile(
                rf'(<MaterialParameterFloat\b[^>]*_name="{re.escape(parameter_name)}"[^>]*_value=")([^"]*)(")',
                flags=re.IGNORECASE | re.DOTALL,
            )
            patched, replace_count = parameter_pattern.subn(rf"\g<1>{replacement_value}\3", patched)
            changed = changed or bool(replace_count)
        return patched, changed

    def byte4_to_unit(value: int) -> float:
        try:
            raw = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if raw > 255:
            raw = (raw >> 16) & 0xFF
        return max(0.0, min(1.0, float(raw) / 255.0))

    def patch_wrapper(match: re.Match[str]) -> str:
        nonlocal edited_wrappers
        attrs = match.group("attrs")
        if not wrapper_selected(attrs):
            return match.group(0)
        body = match.group("body")
        changed = False
        if roughness_value is not None:
            body, rough_changed = set_or_insert_byte4(body, "_scratchRoughness", "638052851515390", int(roughness_value))
            changed = changed or rough_changed
        if metallic_value is not None:
            body, metal_changed = set_or_insert_byte4(body, "_scratchMetallic", "488189023223806", int(metallic_value))
            changed = changed or metal_changed
        if shine_value is not None:
            body, shine_changed = set_or_insert_float(body, "_sheen", "403124275642366", float(shine_value))
            changed = changed or shine_changed
        if roughness_value is not None:
            body, rough_float_changed = replace_existing_float(
                body,
                ("_roughness", "_roughnessScale", "_roughnessValue", "_materialRoughness"),
                byte4_to_unit(int(roughness_value)),
            )
            changed = changed or rough_float_changed
        if metallic_value is not None:
            metal_float = byte4_to_unit(int(metallic_value))
            body, metal_float_changed = replace_existing_float(
                body,
                ("_metallic", "_metalness", "_metallicScale", "_specular", "_specularScale", "_reflection", "_reflectivity"),
                metal_float,
            )
            changed = changed or metal_float_changed
        if shine_value is not None:
            body, shine_float_changed = replace_existing_float(
                body,
                (
                    "_shine",
                    "_shininess",
                    "_gloss",
                    "_glossiness",
                    "_smoothness",
                    "_specularPower",
                    "_reflectionIntensity",
                ),
                float(shine_value),
            )
            changed = changed or shine_float_changed
        if changed:
            edited_wrappers += 1
            body = _renumber_sidecar_parameter_indexes(body)
        return f"{match.group(1)}{body}{match.group(5)}"

    return wrapper_pattern.sub(patch_wrapper, sidecar_text), edited_wrappers


def _apply_source_emissive_parameters(
    sidecar_text: str,
    target_settings: Mapping[str, tuple[str, float]],
    *,
    exact_only: bool = False,
    preserve_shader_material_names: Sequence[str] = (),
) -> tuple[str, int]:
    settings_by_key = {
        _normalize_sidecar_material_name(str(name or "")): (str(color or "#FFFFFFFF"), float(intensity or 0.0))
        for name, (color, intensity) in dict(target_settings or {}).items()
        if str(name or "").strip() and float(intensity or 0.0) > 0.0
    }
    if not settings_by_key:
        return sidecar_text, 0
    preserve_shader_keys = {
        _normalize_sidecar_material_name(str(name or ""))
        for name in tuple(preserve_shader_material_names or ())
        if str(name or "").strip()
    }
    wrapper_pattern = re.compile(
        r"(<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>)(?P<body>.*?)(</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    edited_wrappers = 0

    def selected_settings(attrs: str) -> Optional[tuple[str, float]]:
        name_match = re.search(r'\b_subMeshName="([^"]*)"', attrs, flags=re.IGNORECASE)
        wrapper_name = str(name_match.group(1) if name_match else "")
        wrapper_key = _normalize_sidecar_material_name(wrapper_name)
        if wrapper_key in settings_by_key:
            return settings_by_key[wrapper_key]
        if exact_only:
            return None
        for target_key, settings in settings_by_key.items():
            if _sidecar_material_names_match(wrapper_name, target_key):
                return settings
        return None

    def set_or_insert_color(body: str, parameter_name: str, item_id: str, value: str) -> tuple[str, bool]:
        cleaned = str(value or "#FFFFFFFF").strip()
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", cleaned):
            cleaned = "#FFFFFFFF"
        if len(cleaned) == 7:
            cleaned = cleaned + "FF"
        cleaned = cleaned.upper()
        parameter_pattern = re.compile(
            rf'(<MaterialParameterColor\b[^>]*(?:StringItemID|_name|Name|name)="{re.escape(parameter_name)}"[^>]*\b(?:_value|Value|value)=")([^"]*)(")',
            flags=re.IGNORECASE | re.DOTALL,
        )
        replaced_body, replace_count = parameter_pattern.subn(rf"\g<1>{cleaned}\3", body)
        if replace_count:
            return replaced_body, True
        insertion = (
            f'\n\t\t\t\t\t\t\t<MaterialParameterColor StringItemID="{parameter_name}" '
            f'ItemID="{item_id}" _name="{parameter_name}" _value="{cleaned}" Index="0"/>'
        )
        vector_close = re.search(r"</Vector>", body, flags=re.IGNORECASE)
        if vector_close:
            insert_at = vector_close.start()
            return body[:insert_at] + insertion + body[insert_at:], True
        return body + insertion, True

    def set_or_insert_float(body: str, parameter_name: str, item_id: str, value: float) -> tuple[str, bool]:
        replacement_value = f"{max(0.0, min(20.0, float(value))):.6f}"
        parameter_pattern = re.compile(
            rf'(<MaterialParameterFloat\b[^>]*(?:StringItemID|_name|Name|name)="{re.escape(parameter_name)}"[^>]*\b(?:_value|Value|value)=")([^"]*)(")',
            flags=re.IGNORECASE | re.DOTALL,
        )
        replaced_body, replace_count = parameter_pattern.subn(rf"\g<1>{replacement_value}\3", body)
        if replace_count:
            return replaced_body, True
        insertion = (
            f'\n\t\t\t\t\t\t\t<MaterialParameterFloat StringItemID="{parameter_name}" '
            f'ItemID="{item_id}" _name="{parameter_name}" _value="{replacement_value}" Index="0"/>'
        )
        vector_close = re.search(r"</Vector>", body, flags=re.IGNORECASE)
        if vector_close:
            insert_at = vector_close.start()
            return body[:insert_at] + insertion + body[insert_at:], True
        return body + insertion, True

    def patch_wrapper(match: re.Match[str]) -> str:
        nonlocal edited_wrappers
        settings = selected_settings(match.group("attrs"))
        if settings is None:
            return match.group(0)
        attrs = match.group("attrs")
        name_match = re.search(r'\b_subMeshName="([^"]*)"', attrs, flags=re.IGNORECASE)
        wrapper_key = _normalize_sidecar_material_name(str(name_match.group(1) if name_match else ""))
        color, intensity = settings
        body = match.group("body")
        body, color_changed = set_or_insert_color(body, "_emissiveColor", "2065176433000446", color)
        body, intensity_changed = set_or_insert_float(body, "_emissiveIntensity", "3419583792807934", intensity)
        if not (color_changed or intensity_changed):
            return match.group(0)
        edited_wrappers += 1
        body = _renumber_sidecar_parameter_indexes(body)
        patched_wrapper = f"{match.group(1)}{body}{match.group(5)}"
        if wrapper_key in preserve_shader_keys:
            return patched_wrapper
        return _set_source_driven_wrapper_shader_name(
            patched_wrapper,
            "SkinnedMeshEmissive_Ver2",
        )

    return wrapper_pattern.sub(patch_wrapper, sidecar_text), edited_wrappers


def _neutralize_inherited_material_layers(
    sidecar_text: str,
    *,
    material_names: Sequence[str] = (),
    keep_rules: Sequence[tuple[str, str]] = (),
    complete_external_reset: bool = False,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
    exact_only: bool = False,
    preserve_wrapper_layer_support: bool = False,
) -> tuple[str, int, int]:
    target_keys = {
        _normalize_sidecar_material_name(str(name or ""))
        for name in tuple(material_names or ())
        if str(name or "").strip()
    }
    keep = {
        (str(parameter or "").strip().lower(), _normalize_texture_path(texture_path))
        for parameter, texture_path in tuple(keep_rules or ())
        if str(parameter or "").strip() and _normalize_texture_path(texture_path)
    }
    keep_paths = {texture_path for _parameter, texture_path in keep if texture_path}
    wrapper_pattern = re.compile(
        r"(<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>)(?P<body>.*?)(</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    texture_pattern = re.compile(
        r"\s*<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    neutral_texture_tokens = (
        "colorblendingmasktexture",
        "detailmasktexture",
        "grime",
        "detail",
        "damage",
        "heighttexture",
        "materialtexture",
        "layer",
    )
    neutral_color_tokens = ("tintcolor", "dyeing", "scratchtint", "baseheighttint")
    neutral_byte_tokens = ("grime", "dyeing")
    neutral_flag_names = {"_colorblendingflag"}
    reset_remove_parameter_tokens = (
        "clothcategory",
        "clothmaskbit",
        "sheen",
        "scratchroughness",
        "scratchmetallic",
    )
    reset_zero_float_tokens = (
        "screenspacedisplacementscale",
        "detailscreenspacedisplacementscale",
    )
    reset_one_float_tokens = (
        "brightness",
    )
    neutral_rgb = _profile_neutral_color_rgb(material_profile)
    displacement_multiplier = _profile_displacement_scale_multiplier(material_profile)
    displacement_max = _profile_displacement_scale_max(material_profile)
    preserve_scratch_alpha = bool(getattr(material_profile, "preserve_scratch_alpha", False)) if material_profile is not None else False
    preserve_target_layer_response = _profile_preserves_target_layer_response(material_profile)
    preserve_wrapper_layer_support = bool(preserve_wrapper_layer_support)
    neutralize_preserved_layer_scalars = _profile_applies_source_pbr_scalars_with_preserved_layers(material_profile)
    preserve_layer_scalar_response = preserve_target_layer_response and not neutralize_preserved_layer_scalars
    reset_wrapper_contract = complete_external_reset and not preserve_target_layer_response and not preserve_wrapper_layer_support
    preserve_texture_layer_support = preserve_target_layer_response or preserve_wrapper_layer_support
    edge_relief_preserve_support = (
        normalize_basic_control_percent(getattr(material_profile, "edge_relief_strength", 0.0)) > 0.0
        and normalize_edge_relief_source(getattr(material_profile, "edge_relief_source", "hybrid"))
        in {"preserve_target", "hybrid"}
    )
    edited_wrappers = 0
    edited_parameters = 0

    def wrapper_selected(attrs: str) -> bool:
        if not target_keys:
            return True
        name_match = re.search(r'\b_subMeshName="([^"]*)"', attrs, flags=re.IGNORECASE)
        wrapper_name = str(name_match.group(1) if name_match else "")
        wrapper_key = _normalize_sidecar_material_name(wrapper_name)
        if wrapper_key in target_keys:
            return True
        if exact_only:
            return False
        return any(_sidecar_material_names_match(wrapper_name, target_name) for target_name in target_keys)

    def neutralize_wrapper(match: re.Match[str]) -> str:
        nonlocal edited_wrappers, edited_parameters
        attrs = match.group("attrs")
        body = match.group("body")
        if not wrapper_selected(attrs):
            return match.group(0)
        wrapper_edits = 0
        if reset_wrapper_contract:
            target_shader = (
                "SkinnedMeshEmissive_Ver2"
                if re.search(r"_emissive(?:Intensity|Progress)?Texture", body, flags=re.IGNORECASE)
                else "SkinnedMeshStandard_Ver2"
            )

            def replace_material_name(material_match: re.Match[str]) -> str:
                current = str(material_match.group(2) or "")
                if current == target_shader:
                    return material_match.group(0)
                return f"{material_match.group(1)}{target_shader}{material_match.group(3)}"

            patched_body, material_name_edits = re.subn(
                r'(<Material\b[^>]*\b_materialName=")([^"]*)(")',
                replace_material_name,
                body,
                flags=re.IGNORECASE | re.DOTALL,
            )
            wrapper_edits += material_name_edits
        else:
            patched_body = body

        def replace_texture(texture_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            block = texture_match.group(0)
            parameter_name = _sidecar_parameter_name(block).strip().lower()
            compact_parameter = re.sub(r"[^a-z0-9]+", "", parameter_name)
            path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
            texture_path = _normalize_texture_path(path_match.group(1) if path_match else "")
            if (parameter_name, texture_path) in keep or texture_path in keep_paths:
                return block
            if edge_relief_preserve_support:
                if (
                    any(
                        token in compact_parameter
                        for token in (
                            "heighttexture",
                            "detailmasktexture",
                            "detailnormal",
                            "detailheight",
                            "displacement",
                        )
                    )
                    and not any(token in compact_parameter for token in ("diffuse", "albedo", "basecolor", "color", "grime"))
                ):
                    return block
            if any(token in parameter_name for token in neutral_texture_tokens):
                if preserve_texture_layer_support:
                    return block
                wrapper_edits += 1
                return ""
            return block

        patched_body = texture_pattern.sub(replace_texture, patched_body)

        def replace_flag(flag_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            parameter_name = str(flag_match.group(2) or "").strip().lower()
            normalized_parameter = re.sub(r"[^a-z0-9]+", "", parameter_name)
            if complete_external_reset and parameter_name == "_rendersettingflag":
                if preserve_target_layer_response or preserve_wrapper_layer_support:
                    return flag_match.group(0)
                if str(flag_match.group(3) or "") == "4":
                    return flag_match.group(0)
                wrapper_edits += 1
                return f"{flag_match.group(1)}4{flag_match.group(4)}"
            if parameter_name not in neutral_flag_names:
                return flag_match.group(0)
            if preserve_layer_scalar_response:
                return flag_match.group(0)
            wrapper_edits += 1
            replacement_value = "15" if neutralize_preserved_layer_scalars else "0"
            return f"{flag_match.group(1)}{replacement_value}{flag_match.group(4)}"

        patched_body = re.sub(
            r'(<MaterialParameterBitFlag32\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            replace_flag,
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if reset_wrapper_contract and not re.search(
            r'<MaterialParameterBitFlag32\b[^>]*_name="_renderSettingFlag"',
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            render_flag = (
                '\n\t\t\t\t\t\t\t<MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" '
                'ItemID="8" _name="_renderSettingFlag" _value="4" Index="0"/>'
            )
            vector_match = re.search(r"</Vector>", patched_body, flags=re.IGNORECASE)
            if vector_match:
                patched_body = patched_body[: vector_match.start()] + render_flag + patched_body[vector_match.start() :]
            else:
                patched_body += render_flag
            wrapper_edits += 1

        def replace_float(float_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            parameter_name = str(float_match.group(2) or "").strip().lower()
            normalized_parameter = re.sub(r"[^a-z0-9]+", "", parameter_name)
            if not complete_external_reset:
                return float_match.group(0)
            if preserve_target_layer_response or preserve_wrapper_layer_support:
                return float_match.group(0)
            if any(token in normalized_parameter for token in reset_zero_float_tokens):
                if displacement_multiplier is not None:
                    try:
                        original_float = max(0.0, float(str(float_match.group(3) or "0") or 0.0))
                    except (TypeError, ValueError, OverflowError):
                        original_float = 0.0
                    replacement_float = original_float * displacement_multiplier
                    if displacement_max is not None:
                        replacement_float = min(replacement_float, displacement_max)
                    replacement_value = f"{max(0.0, replacement_float):.6f}"
                else:
                    replacement_value = "0.000000"
            elif any(token in normalized_parameter for token in reset_one_float_tokens):
                replacement_value = "1.000000"
            else:
                return float_match.group(0)
            if str(float_match.group(3) or "") == replacement_value:
                return float_match.group(0)
            wrapper_edits += 1
            return f"{float_match.group(1)}{replacement_value}{float_match.group(4)}"

        patched_body = re.sub(
            r'(<MaterialParameterFloat\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            replace_float,
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if reset_wrapper_contract:
            def remove_reset_parameter(parameter_match: re.Match[str]) -> str:
                nonlocal wrapper_edits
                block = parameter_match.group(0)
                parameter_name = _sidecar_parameter_name(block).strip().lower()
                normalized_parameter = re.sub(r"[^a-z0-9]+", "", parameter_name)
                if any(token in normalized_parameter for token in reset_remove_parameter_tokens):
                    wrapper_edits += 1
                    return ""
                return block

            patched_body = re.sub(
                r"\s*<MaterialParameter(?:Float|Byte4|BitFlag32|ClothCategory)\b[^>]*/>",
                remove_reset_parameter,
                patched_body,
                flags=re.IGNORECASE | re.DOTALL,
            )

        def replace_color(color_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            parameter_name = str(color_match.group(2) or "").strip().lower()
            if not any(token in parameter_name for token in neutral_color_tokens):
                return color_match.group(0)
            if preserve_layer_scalar_response:
                return color_match.group(0)
            original_value = str(color_match.group(3) or "").strip()
            if neutral_rgb is not None:
                if original_value.startswith("#"):
                    alpha = "ff"
                    hex_value = original_value[1:]
                    if preserve_scratch_alpha and "scratchtint" in parameter_name and len(hex_value) >= 8:
                        alpha = hex_value[6:8]
                    replacement_value = _format_profile_color_hex(neutral_rgb, alpha)
                else:
                    replacement_value = " ".join(f"{component / 255.0:.6f}" for component in neutral_rgb)
            else:
                replacement_value = (
                    "#ffffffff"
                    if complete_external_reset and original_value.startswith("#")
                    else "#ffffff00"
                    if original_value.startswith("#")
                    else "1.000000 1.000000 1.000000"
                )
            if original_value == replacement_value:
                return color_match.group(0)
            wrapper_edits += 1
            return f"{color_match.group(1)}{replacement_value}{color_match.group(4)}"

        patched_body = re.sub(
            r'(<MaterialParameterColor\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            replace_color,
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        )

        def replace_byte(byte_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            parameter_name = str(byte_match.group(2) or "").strip().lower()
            if not any(token in parameter_name for token in neutral_byte_tokens):
                return byte_match.group(0)
            if preserve_layer_scalar_response:
                return byte_match.group(0)
            wrapper_edits += 1
            return f"{byte_match.group(1)}0{byte_match.group(4)}"

        patched_body = re.sub(
            r'(<MaterialParameterByte4\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            replace_byte,
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        )

        def add_missing_neutral_byte_value(byte_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            block = byte_match.group(0)
            if re.search(r'\b(?:_value|Value)="', block, flags=re.IGNORECASE):
                return block
            parameter_name = _sidecar_parameter_name(block).strip().lower()
            if not any(token in parameter_name for token in neutral_byte_tokens):
                return block
            if preserve_layer_scalar_response:
                return block
            wrapper_edits += 1
            if block.endswith("/>"):
                return block[:-2].rstrip() + ' _value="0"/>'
            return re.sub(r">$", ' _value="0">', block, count=1)

        patched_body = re.sub(
            r"<MaterialParameterByte4\b[^>]*/?>",
            add_missing_neutral_byte_value,
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if wrapper_edits <= 0:
            return match.group(0)
        edited_wrappers += 1
        edited_parameters += wrapper_edits
        return match.group(1) + patched_body + match.group(5)

    patched = wrapper_pattern.sub(neutralize_wrapper, str(sidecar_text or ""))
    if edited_parameters <= 0 and complete_external_reset and not wrapper_pattern.search(str(sidecar_text or "")):
        patched, flat_wrappers, flat_parameters = _neutralize_flat_material_instance_parameters(
            patched,
            keep_rules=keep_rules,
            complete_external_reset=complete_external_reset,
        )
        edited_wrappers += flat_wrappers
        edited_parameters += flat_parameters
    if edited_parameters:
        patched = _renumber_sidecar_parameter_indexes(patched)
    return patched, edited_wrappers, edited_parameters


def _neutralize_flat_material_instance_parameters(
    sidecar_text: str,
    *,
    keep_rules: Sequence[tuple[str, str]] = (),
    complete_external_reset: bool = False,
) -> tuple[str, int, int]:
    """Neutralize PAMI/static-style flat material parameters for complete swaps."""

    keep = {
        (str(parameter or "").strip().lower(), _normalize_texture_path(texture_path))
        for parameter, texture_path in tuple(keep_rules or ())
        if str(parameter or "").strip() and _normalize_texture_path(texture_path)
    }
    keep_paths = {texture_path for _parameter, texture_path in keep if texture_path}
    if "<MaterialParameter" not in str(sidecar_text or ""):
        return sidecar_text, 0, 0

    edited = 0
    texture_pattern = re.compile(
        r"\s*<MaterialParameterTexture\b[^>]*/>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    remove_texture_tokens = (
        "colorblendingmasktexture",
        "detailmasktexture",
        "grime",
        "detail",
        "damage",
        "heighttexture",
        "materialtexture",
        "layer",
    )

    def flat_parameter_name(block: str) -> str:
        match = re.search(r'\b(?:_name|Name)="([^"]*)"', block, flags=re.IGNORECASE)
        return str(match.group(1) if match else "").strip()

    def flat_parameter_value(block: str) -> str:
        match = re.search(r'\b(?:_value|Value)="([^"]*)"', block, flags=re.IGNORECASE)
        return str(match.group(1) if match else "").strip()

    def replace_texture(match: re.Match[str]) -> str:
        nonlocal edited
        block = match.group(0)
        parameter_name = flat_parameter_name(block).lower()
        texture_path = _normalize_texture_path(flat_parameter_value(block))
        if (parameter_name, texture_path) in keep or texture_path in keep_paths:
            return block
        if any(token in parameter_name for token in remove_texture_tokens):
            edited += 1
            return ""
        return block

    patched = texture_pattern.sub(replace_texture, str(sidecar_text or ""))

    def replace_named_value(pattern: str, tokens: Sequence[str], replacement_for: Callable[[str], str]) -> None:
        nonlocal patched, edited

        def replace(match: re.Match[str]) -> str:
            nonlocal edited
            parameter_name = str(match.group(2) or "").strip().lower()
            normalized_parameter = re.sub(r"[^a-z0-9]+", "", parameter_name)
            if not any(token in normalized_parameter for token in tokens):
                return match.group(0)
            replacement_value = replacement_for(str(match.group(3) or ""))
            if str(match.group(3) or "") == replacement_value:
                return match.group(0)
            edited += 1
            return f"{match.group(1)}{replacement_value}{match.group(4)}"

        patched = re.sub(pattern, replace, patched, flags=re.IGNORECASE | re.DOTALL)

    if complete_external_reset:
        replace_named_value(
            r'(<MaterialParameterFloat\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            ("brightness",),
            lambda _value: "1.000000",
        )
        replace_named_value(
            r'(<MaterialParameterColor\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            ("tintcolor", "dyeing", "scratchtint", "baseheighttint"),
            lambda value: "#ffffffff" if str(value or "").strip().startswith("#") else "1.000000 1.000000 1.000000",
        )
        replace_named_value(
            r'(<MaterialParameterBitFlag32\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            ("colorblendingflag",),
            lambda _value: "0",
        )

    if edited:
        patched = _renumber_sidecar_parameter_indexes(patched)
    return patched, 1 if edited else 0, edited


def _renumber_sidecar_parameter_indexes(sidecar_text: str) -> str:
    vector_pattern = re.compile(
        r'(<Vector\b[^>]*(?:Name|name|_name)="_parameters"[^>]*>)(.*?)(\s*</Vector>)',
        flags=re.IGNORECASE | re.DOTALL,
    )
    parameter_index_pattern = re.compile(
        r'(<MaterialParameter[A-Za-z0-9_:.-]*\b[^>]*\bIndex=")(\d+)(")',
        flags=re.IGNORECASE | re.DOTALL,
    )

    def replace_vector(match: re.Match[str]) -> str:
        next_index = 0

        def replace_index(index_match: re.Match[str]) -> str:
            nonlocal next_index
            replacement = f"{index_match.group(1)}{next_index}{index_match.group(3)}"
            next_index += 1
            return replacement

        body = parameter_index_pattern.sub(replace_index, match.group(2))
        return f"{match.group(1)}{body}{match.group(3)}"

    return vector_pattern.sub(replace_vector, sidecar_text)


def _rename_sidecar_parameter_name(parameter_text: str, new_parameter_name: str) -> str:
    start_tag_match = re.match(r"(<MaterialParameterTexture\b[^>]*>)", parameter_text, flags=re.IGNORECASE | re.DOTALL)
    if start_tag_match is None:
        return parameter_text
    start_tag = start_tag_match.group(1)
    patched_start = start_tag
    for attr in ("StringItemID", "_name"):
        patched_start = re.sub(
            rf'\b{re.escape(attr)}="[^"]*"',
            f'{attr}="{_escape_xml_attr(new_parameter_name)}"',
            patched_start,
            count=1,
        )
    if patched_start == start_tag:
        patched_start = re.sub(
            r'\b(Name|name)="[^"]*"',
            lambda match: f'{match.group(1)}="{_escape_xml_attr(new_parameter_name)}"',
            patched_start,
            count=1,
        )
    return patched_start + parameter_text[start_tag_match.end() :]


def _sidecar_texture_injection_position(parameter_body: str, parameter_name: str) -> tuple[Optional[int], Optional[int]]:
    normalized_parameter = str(parameter_name or "").strip().lower()
    if normalized_parameter not in {"_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture"}:
        return None, None
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    fallback: Optional[tuple[int, int]] = None
    for match in texture_pattern.finditer(parameter_body):
        block = match.group(0)
        block_name = _sidecar_parameter_name(block).lower()
        block_index = _sidecar_parameter_index(block)
        if block_index is None:
            continue
        if block_name == "_normaltexture":
            return match.end(), block_index + 1
        if block_name == "_heighttexture" and fallback is None:
            fallback = (match.start(), block_index)
        elif block_name in {"_colorblendingmasktexture", "_detailmasktexture"} and fallback is None:
            fallback = (match.start(), block_index)
    if fallback is not None:
        return fallback
    return None, None


def _sidecar_parameter_name(parameter_text: str) -> str:
    name_match = re.search(
        r'(?:StringItemID|_name|Name|name)="([^"]+)"',
        parameter_text,
        flags=re.IGNORECASE,
    )
    return str(name_match.group(1) if name_match else "").strip()


def _sidecar_parameter_index(parameter_text: str) -> Optional[int]:
    index_match = re.search(r'\bIndex="(\d+)"', parameter_text)
    if index_match is None:
        return None
    try:
        return int(index_match.group(1))
    except ValueError:
        return None


def _shift_sidecar_parameter_indexes(parameter_body: str, start_index: int) -> str:
    def replace_index(match: re.Match[str]) -> str:
        try:
            value = int(match.group(1))
        except ValueError:
            return match.group(0)
        if value < start_index:
            return match.group(0)
        return f'Index="{value + 1}"'

    return re.sub(r'\bIndex="(\d+)"', replace_index, parameter_body)


def _find_sidecar_material_wrapper(sidecar_text: str, target_name: str) -> Optional[re.Match[str]]:
    normalized_target = _normalize_sidecar_material_name(target_name)
    fallback: Optional[tuple[float, re.Match[str]]] = None
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>.*?</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in wrapper_pattern.finditer(sidecar_text):
        name_match = re.search(
            r'(?:_subMeshName|subMeshName|SubMeshName|_submesh|submesh|MaterialName|materialName|Name|name)="([^"]+)"',
            match.group(0),
            flags=re.IGNORECASE,
        )
        if name_match and _normalize_sidecar_material_name(name_match.group(1)) == normalized_target:
            return match
        if name_match:
            score = _sidecar_material_match_score(target_name, name_match.group(1))
            if score > 0 and (fallback is None or score > fallback[0]):
                fallback = (score, match)
    if fallback is not None and fallback[0] >= 6.0:
        return fallback[1]
    return None


def _find_sidecar_material_wrapper_exact(sidecar_text: str, target_name: str) -> Optional[re.Match[str]]:
    normalized_target = _normalize_sidecar_material_name(target_name)
    if not normalized_target:
        return None
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>.*?</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in wrapper_pattern.finditer(sidecar_text):
        name_match = re.search(
            r'(?:_subMeshName|subMeshName|SubMeshName|_submesh|submesh|MaterialName|materialName|Name|name)="([^"]+)"',
            match.group(0),
            flags=re.IGNORECASE,
        )
        if name_match and _normalize_sidecar_material_name(name_match.group(1)) == normalized_target:
            return match
    return None


def _sidecar_material_names_match(left: str, right: str) -> bool:
    left_normalized = _normalize_sidecar_material_name(left)
    right_normalized = _normalize_sidecar_material_name(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    if len(left_normalized) >= 8 and left_normalized in right_normalized:
        return True
    if len(right_normalized) >= 8 and right_normalized in left_normalized:
        return True
    return _sidecar_material_match_score(left, right) >= 6.0


def _sidecar_material_match_score(left: str, right: str) -> float:
    left_tokens = _material_tokens(left)
    right_tokens = _material_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    score = float(len(overlap) * 4)
    for token in overlap:
        score += min(4.0, len(token) * 0.5)
        if token in {"acc", "accessory", "blade", "body", "guard", "handle", "hilt", "tail"}:
            score += 4.0
    if "blade" in left_tokens and "sword" in right_tokens:
        score += 6.0
    if "sword" in left_tokens and "blade" in right_tokens:
        score += 6.0
    return score


def _normalize_sidecar_material_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _sidecar_texture_parameter_template(sidecar_text: str, parameter_name: str) -> str:
    parameter_match = re.search(
        rf"<MaterialParameterTexture\b[^>]*(?:StringItemID|_name|Name|name)=\"{re.escape(parameter_name)}\"[^>]*>.*?</MaterialParameterTexture>",
        sidecar_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if parameter_match is not None:
        return parameter_match.group(0).strip()
    item_id = _source_driven_parameter_item_id(parameter_name)
    return (
        f'<MaterialParameterTexture StringItemID="{parameter_name}" ItemID="{item_id}" _name="{parameter_name}" Index="0">\n'
        f'\t\t\t\t\t\t\t\t<ResourceReferencePath_ITexture Name="_value" _path=""/>\n'
        f"\t\t\t\t\t\t\t</MaterialParameterTexture>"
    )


def _next_material_parameter_index(wrapper_text: str) -> int:
    indexes = []
    for raw_index in re.findall(r'\bIndex="(\d+)"', wrapper_text):
        try:
            indexes.append(int(raw_index))
        except ValueError:
            continue
    return max(indexes, default=-1) + 1


def _retarget_texture_parameter_template(
    template: str,
    parameter_name: str,
    texture_path: str,
    index: int,
) -> str:
    patched = template.strip()
    item_id = _source_driven_parameter_item_id(parameter_name)
    if item_id != "0":
        if re.search(r'\bItemID="[^"]*"', patched, flags=re.IGNORECASE):
            patched = re.sub(r'\bItemID="[^"]*"', f'ItemID="{item_id}"', patched, count=1, flags=re.IGNORECASE)
        else:
            patched = re.sub(r"(<MaterialParameterTexture\b)", rf'\1 ItemID="{item_id}"', patched, count=1, flags=re.IGNORECASE)
    if re.search(r'StringItemID="[^"]*"', patched, flags=re.IGNORECASE):
        patched = re.sub(r'StringItemID="[^"]*"', f'StringItemID="{parameter_name}"', patched, count=1, flags=re.IGNORECASE)
    if re.search(r'_name="[^"]*"', patched, flags=re.IGNORECASE):
        patched = re.sub(r'_name="[^"]*"', f'_name="{parameter_name}"', patched, count=1, flags=re.IGNORECASE)
    elif re.search(r'\bName="[^"]*"', patched, flags=re.IGNORECASE):
        patched = re.sub(r'\bName="[^"]*"', f'Name="{parameter_name}"', patched, count=1, flags=re.IGNORECASE)
    patched = re.sub(r'Index="\d+"', f'Index="{int(index)}"', patched, count=1)
    if re.search(r'\b(?:_path|path|Path|_value|Value|value)="[^"]*"', patched):
        patched = re.sub(
            r'\b(_path|path|Path|_value|Value|value)="[^"]*"',
            lambda match: f'{match.group(1)}="{_escape_xml_attr(texture_path)}"',
            patched,
            count=1,
        )
    else:
        patched = patched.replace(
            "</MaterialParameterTexture>",
            f'\n\t\t\t\t\t\t\t\t<ResourceReferencePath_ITexture Name="_value" _path="{_escape_xml_attr(texture_path)}"/>\n\t\t\t\t\t\t\t</MaterialParameterTexture>',
        )
    return patched


def _escape_xml_attr(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
