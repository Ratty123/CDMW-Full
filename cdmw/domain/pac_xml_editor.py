"""Pure PAC XML document parsing and source-preserving value edits."""

from __future__ import annotations

import codecs
import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence
from xml.sax.saxutils import escape, unescape


_XML_DECLARATION_RE = re.compile(r"^\s*<\?xml\b[^>]*\?>", re.IGNORECASE)
_XML_DECLARATION_ENCODING_RE = re.compile(
    rb"<\?xml\b[^>]*\bencoding\s*=\s*['\"]\s*([A-Za-z0-9._:-]+)\s*['\"]",
    re.IGNORECASE,
)
_ATTRIBUTE_RE = re.compile(
    r"(?P<name>[A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_PARAMETER_PREFIX = "MaterialParameter"
_VALUE_ATTRS = ("_value", "Value", "value")
_TEXTURE_ATTRS = ("_path", "path", "Path", "_value", "Value", "value", "File", "file", "Texture", "texture")
_NAME_ATTRS = ("_name", "StringItemID", "ParameterName", "parameterName", "_parameterName", "Name", "name", "ID", "id")
_RGB_ATTR_GROUPS = (("x", "y", "z"), ("r", "g", "b"), ("_x", "_y", "_z"), ("_r", "_g", "_b"))
_KNOWN_KINDS = frozenset(
    {
        "texture",
        "color",
        "float",
        "float2",
        "float3",
        "half2",
        "bool",
        "int",
        "uint",
        "byte4",
        "bitflag32",
        "clothcategory",
    }
)
_VECTOR_COMPONENT_COUNTS = {"float2": 2, "half2": 2, "float3": 3}
_UNESCAPE_ENTITIES = {"&quot;": '"', "&apos;": "'"}


@dataclass(frozen=True, slots=True)
class PacXmlSourceFormat:
    encoding: str = "utf-8"
    bom: bytes = b""
    newline: str = "\n"


@dataclass(frozen=True, slots=True)
class PacXmlValueSpan:
    start: int
    end: int
    attribute_name: str
    quote: str = '"'


@dataclass(frozen=True, slots=True)
class PacXmlField:
    row_id: str
    kind: str
    parameter_type: str
    group_label: str
    shader_name: str
    parameter_name: str
    value: str
    detail: str
    item_id: str = ""
    index: str = ""
    source_order: int = 0
    source_line: int = 0
    explicit: bool = True
    editable: bool = True
    value_mode: str = "attribute"
    spans: tuple[PacXmlValueSpan, ...] = ()
    insertion_offset: int = -1
    insertion_attribute: str = "_value"
    risk: str = ""


@dataclass(frozen=True, slots=True)
class PacXmlEditResult:
    text: str
    payload: bytes
    changed_rows: tuple[str, ...]
    structural_signature: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class PacXmlDocument:
    text: str
    fields: tuple[PacXmlField, ...]
    source_format: PacXmlSourceFormat = PacXmlSourceFormat()
    original_payload: bytes = b""
    source_sha256: str = ""
    structural_signature: tuple[tuple[str, ...], ...] = ()

    def field_by_id(self) -> dict[str, PacXmlField]:
        return {field.row_id: field for field in self.fields}

    def render(self, edited_values: Mapping[str, object]) -> PacXmlEditResult:
        return apply_pac_xml_edits(self, edited_values)


@dataclass(frozen=True, slots=True)
class _AttributeToken:
    name: str
    value: str
    raw_value: str
    value_start: int
    value_end: int
    quote: str


@dataclass(frozen=True, slots=True)
class _XmlToken:
    kind: str
    name: str
    local_name: str
    start: int
    end: int
    close_offset: int
    self_closing: bool
    attributes: tuple[_AttributeToken, ...] = ()


def decode_pac_xml_payload(payload: bytes) -> tuple[str, PacXmlSourceFormat]:
    """Decode a complete XML payload strictly while retaining its byte format."""

    data = bytes(payload)
    if not data:
        raise ValueError("PAC XML payload is empty.")
    bom = b""
    encoding = "utf-8"
    body = data
    if data.startswith(codecs.BOM_UTF8):
        bom, encoding, body = codecs.BOM_UTF8, "utf-8", data[len(codecs.BOM_UTF8) :]
    elif data.startswith(codecs.BOM_UTF16_LE):
        bom, encoding, body = codecs.BOM_UTF16_LE, "utf-16-le", data[len(codecs.BOM_UTF16_LE) :]
    elif data.startswith(codecs.BOM_UTF16_BE):
        bom, encoding, body = codecs.BOM_UTF16_BE, "utf-16-be", data[len(codecs.BOM_UTF16_BE) :]
    elif data.startswith((b"<\x00?\x00", b"<\x00")):
        encoding = "utf-16-le"
    elif data.startswith((b"\x00<\x00?", b"\x00<")):
        encoding = "utf-16-be"
    else:
        declaration = _XML_DECLARATION_ENCODING_RE.search(data[:512])
        if declaration:
            declared = declaration.group(1).decode("ascii", errors="strict")
            try:
                codec = codecs.lookup(declared)
            except LookupError as exc:
                raise ValueError(f"Unsupported PAC XML encoding: {declared}") from exc
            encoding = codec.name
            if encoding == "utf-8-sig":
                encoding = "utf-8"
    try:
        text = body.decode(encoding, errors="strict")
    except UnicodeError as exc:
        raise ValueError(f"PAC XML is not valid {encoding} text: {exc}") from exc
    newline = "\r\n" if "\r\n" in text else "\r" if "\r" in text and "\n" not in text else "\n"
    return text, PacXmlSourceFormat(encoding=encoding, bom=bom, newline=newline)


def encode_pac_xml_text(text: str, source_format: PacXmlSourceFormat) -> bytes:
    try:
        return source_format.bom + str(text).encode(source_format.encoding, errors="strict")
    except UnicodeError as exc:
        raise ValueError(f"Edited PAC XML cannot be encoded as {source_format.encoding}: {exc}") from exc


def parse_pac_xml_payload(payload: bytes) -> PacXmlDocument:
    text, source_format = decode_pac_xml_payload(payload)
    return parse_pac_xml_document(text, source_format=source_format, original_payload=bytes(payload))


def parse_pac_xml_document(
    text: str,
    *,
    source_format: PacXmlSourceFormat | None = None,
    original_payload: bytes = b"",
) -> PacXmlDocument:
    source_text = str(text)
    _validate_xml_fragment(source_text)
    tokens = tuple(_iter_xml_tokens(source_text))
    fields = _build_fields(source_text, tokens)
    signature = _structural_signature(tokens)
    payload = bytes(original_payload) if original_payload else encode_pac_xml_text(source_text, source_format or PacXmlSourceFormat())
    return PacXmlDocument(
        text=source_text,
        fields=fields,
        source_format=source_format or PacXmlSourceFormat(newline="\r\n" if "\r\n" in source_text else "\n"),
        original_payload=payload,
        source_sha256=hashlib.sha256(payload).hexdigest(),
        structural_signature=signature,
    )


def apply_pac_xml_edits(document: PacXmlDocument, edited_values: Mapping[str, object]) -> PacXmlEditResult:
    if not edited_values:
        payload = document.original_payload or encode_pac_xml_text(document.text, document.source_format)
        return PacXmlEditResult(document.text, payload, (), document.structural_signature)
    fields = document.field_by_id()
    replacements: list[tuple[int, int, str]] = []
    changed_rows: list[str] = []
    for row_id, raw_value in edited_values.items():
        field = fields.get(str(row_id))
        if field is None:
            raise ValueError(f"Unknown PAC XML editor row: {row_id}")
        if not field.editable:
            raise ValueError(f"{field.parameter_name} is read-only because its value format is not safely recognized.")
        value = _validate_field_value(field, raw_value)
        if field.explicit and value == field.value:
            continue
        field_replacements: list[tuple[int, int, str]] = []
        if field.value_mode == "rgb_attributes":
            components = _parse_color_components(value, field.value)
            if len(field.spans) != 3:
                raise ValueError(f"Could not locate RGB attributes for {field.parameter_name}.")
            for span, component in zip(field.spans, components):
                field_replacements.append((span.start, span.end, _escaped_attribute_value(_format_float(component), span.quote)))
        elif field.spans:
            span = field.spans[0]
            replacement = _normalized_replacement_value(field, value)
            field_replacements.append((span.start, span.end, _escaped_attribute_value(replacement, span.quote)))
        elif field.insertion_offset >= 0 and field.kind != "texture":
            replacement = _normalized_replacement_value(field, value)
            insertion = f" {field.insertion_attribute}=\"{_escaped_attribute_value(replacement, chr(34))}\""
            field_replacements.append((field.insertion_offset, field.insertion_offset, insertion))
        else:
            raise ValueError(f"Could not locate a safe editable value for {field.parameter_name}.")
        field_replacements = [
            replacement
            for replacement in field_replacements
            if replacement[0] == replacement[1] or document.text[replacement[0] : replacement[1]] != replacement[2]
        ]
        if not field_replacements:
            continue
        replacements.extend(field_replacements)
        changed_rows.append(field.row_id)
    if not replacements:
        payload = document.original_payload or encode_pac_xml_text(document.text, document.source_format)
        return PacXmlEditResult(document.text, payload, (), document.structural_signature)
    _validate_non_overlapping_replacements(replacements)
    patched = document.text
    for start, end, replacement in sorted(replacements, key=lambda item: (item[0], item[1]), reverse=True):
        patched = patched[:start] + replacement + patched[end:]
    _validate_xml_fragment(patched)
    signature = _structural_signature(tuple(_iter_xml_tokens(patched)))
    if signature != document.structural_signature:
        raise ValueError("PAC XML structural validation failed: wrappers, shaders, IDs, indexes, or parameter order changed.")
    return PacXmlEditResult(
        text=patched,
        payload=encode_pac_xml_text(patched, document.source_format),
        changed_rows=tuple(changed_rows),
        structural_signature=signature,
    )


def _iter_xml_tokens(text: str) -> Iterable[_XmlToken]:
    index = 0
    length = len(text)
    while index < length:
        start = text.find("<", index)
        if start < 0:
            return
        if text.startswith("<!--", start):
            end = text.find("-->", start + 4)
            index = length if end < 0 else end + 3
            continue
        if text.startswith("<![CDATA[", start):
            end = text.find("]]>", start + 9)
            index = length if end < 0 else end + 3
            continue
        if text.startswith("<?", start):
            end = text.find("?>", start + 2)
            index = length if end < 0 else end + 2
            continue
        quote = ""
        end = start + 1
        while end < length:
            char = text[end]
            if quote:
                if char == quote:
                    quote = ""
            elif char in {'"', "'"}:
                quote = char
            elif char == ">":
                break
            end += 1
        if end >= length:
            raise ValueError(f"Unterminated XML tag at character {start}.")
        body = text[start + 1 : end]
        stripped = body.lstrip()
        is_end = stripped.startswith("/")
        is_declaration = stripped.startswith("!")
        name_text = stripped[1:].lstrip() if is_end else stripped
        name_match = re.match(r"([A-Za-z_:][A-Za-z0-9_.:-]*)", name_text)
        if name_match and not is_declaration:
            name = name_match.group(1)
            local_name = _local_name(name)
            if is_end:
                yield _XmlToken("end", name, local_name, start, end + 1, end, False)
            else:
                self_closing = body.rstrip().endswith("/")
                close_offset = end - 1 if self_closing and text[end - 1] == "/" else end
                attributes = tuple(_attributes_for_tag(text, start, end + 1))
                yield _XmlToken("start", name, local_name, start, end + 1, close_offset, self_closing, attributes)
        index = end + 1


def _attributes_for_tag(text: str, start: int, end: int) -> Iterable[_AttributeToken]:
    tag_text = text[start:end]
    for match in _ATTRIBUTE_RE.finditer(tag_text):
        raw_value = match.group("value")
        yield _AttributeToken(
            name=match.group("name"),
            value=unescape(raw_value, _UNESCAPE_ENTITIES),
            raw_value=raw_value,
            value_start=start + match.start("value"),
            value_end=start + match.end("value"),
            quote=match.group("quote"),
        )


def _build_fields(text: str, tokens: Sequence[_XmlToken]) -> tuple[PacXmlField, ...]:
    fields: list[PacXmlField] = []
    open_stack: list[tuple[str, str, str, dict[str, object] | None]] = []
    group_label = "Global"
    shader_name = ""
    active_parameter: dict[str, object] | None = None
    element_index = 0
    for token in tokens:
        if token.kind == "end":
            while open_stack:
                tag, previous_group, previous_shader, previous_parameter = open_stack.pop()
                group_label, shader_name, active_parameter = previous_group, previous_shader, previous_parameter
                if _local_name(tag).casefold() == token.local_name.casefold():
                    break
            continue
        element_index += 1
        previous_group, previous_shader, previous_parameter = group_label, shader_name, active_parameter
        attrs = _attribute_map(token.attributes)
        local = token.local_name
        if local.casefold().endswith("materialwrapper"):
            group_label = _first_attribute_value(attrs, ("_subMeshName", "subMeshName", "SubMeshName", "PrimitiveName", "primitiveName", "Name", "name")) or group_label
        if local.casefold() == "material":
            shader_name = _first_attribute_value(attrs, ("_materialName", "MaterialName", "materialName")) or shader_name
            if group_label == "Global":
                group_label = _first_attribute_value(attrs, ("PrimitiveName", "primitiveName", "SubMeshName", "subMeshName")) or group_label
        if local.startswith(_PARAMETER_PREFIX) or local == "RepresentColor":
            field = _field_from_parameter(text, token, attrs, group_label, shader_name, element_index, len(fields))
            fields.append(field)
            active_parameter = {"field_index": len(fields) - 1, "kind": field.kind}
        elif active_parameter is not None and str(active_parameter.get("kind")) == "texture" and _looks_like_texture_resource_tag(local):
            field_index = int(active_parameter.get("field_index", -1))
            if 0 <= field_index < len(fields) and not fields[field_index].spans:
                target = _first_existing_attribute(attrs, _TEXTURE_ATTRS, require_texture=True)
                if target is not None:
                    fields[field_index] = _replace_field_texture_target(fields[field_index], target)
        if not token.self_closing:
            open_stack.append((token.name, previous_group, previous_shader, previous_parameter))
        else:
            group_label, shader_name, active_parameter = previous_group, previous_shader, previous_parameter
    return tuple(fields)


def _field_from_parameter(
    text: str,
    token: _XmlToken,
    attrs: Mapping[str, _AttributeToken],
    group_label: str,
    shader_name: str,
    element_index: int,
    source_order: int,
) -> PacXmlField:
    parameter_type = "Color" if token.local_name == "RepresentColor" else token.local_name[len(_PARAMETER_PREFIX) :] or "Unknown"
    kind = parameter_type.casefold()
    parameter_name = token.local_name if token.local_name == "RepresentColor" else _first_attribute_value(attrs, _NAME_ATTRS) or token.local_name
    item_id = _first_attribute_value(attrs, ("ItemID", "_itemID", "itemID", "itemId", "id"))
    index = _first_attribute_value(attrs, ("Index", "_index", "index"))
    spans: tuple[PacXmlValueSpan, ...] = ()
    value = ""
    value_mode = "attribute"
    target_attr = ""
    if kind == "color":
        rgb = _rgb_attribute_tokens(attrs)
        if rgb:
            spans = tuple(_span(attribute) for attribute in rgb)
            value = ", ".join(attribute.value for attribute in rgb)
            value_mode = "rgb_attributes"
            target_attr = ",".join(attribute.name for attribute in rgb)
        else:
            target = _first_existing_attribute(attrs, _VALUE_ATTRS)
            if target is not None:
                spans, value, target_attr = (_span(target),), target.value.strip(), target.name
    elif kind == "texture":
        target = _first_existing_attribute(attrs, _TEXTURE_ATTRS, require_texture=True)
        if target is not None:
            spans, value, target_attr = (_span(target),), target.value.strip(), target.name
    else:
        target = _first_existing_attribute(attrs, _VALUE_ATTRS)
        if target is not None:
            spans, value, target_attr = (_span(target),), target.value.strip(), target.name
    insertion_attribute = _insertion_attribute(attrs)
    row_kind = kind if kind else "unknown"
    row_id = _row_id(row_kind, element_index, parameter_name, target_attr or insertion_attribute)
    explicit = bool(spans)
    editable = kind in _KNOWN_KINDS and (kind != "texture" or explicit)
    risk = _field_risk(parameter_name, kind)
    detail = _field_detail(parameter_type, shader_name, explicit, risk)
    return PacXmlField(
        row_id=row_id,
        kind=row_kind,
        parameter_type=parameter_type,
        group_label=group_label or "Global",
        shader_name=shader_name,
        parameter_name=parameter_name,
        value=value,
        detail=detail,
        item_id=item_id,
        index=index,
        source_order=source_order,
        source_line=text.count("\n", 0, token.start) + 1,
        explicit=explicit,
        editable=editable,
        value_mode=value_mode,
        spans=spans,
        insertion_offset=token.close_offset,
        insertion_attribute=insertion_attribute,
        risk=risk,
    )


def _replace_field_texture_target(field: PacXmlField, target: _AttributeToken) -> PacXmlField:
    return PacXmlField(
        row_id=_row_id(field.kind, _row_element_index(field.row_id), field.parameter_name, target.name),
        kind=field.kind,
        parameter_type=field.parameter_type,
        group_label=field.group_label,
        shader_name=field.shader_name,
        parameter_name=field.parameter_name,
        value=target.value.strip(),
        detail=_field_detail(field.parameter_type, field.shader_name, True, field.risk),
        item_id=field.item_id,
        index=field.index,
        source_order=field.source_order,
        source_line=field.source_line,
        explicit=True,
        editable=True,
        value_mode="attribute",
        spans=(_span(target),),
        insertion_offset=field.insertion_offset,
        insertion_attribute=field.insertion_attribute,
        risk=field.risk,
    )


def _validate_field_value(field: PacXmlField, raw_value: object) -> str:
    value = str(raw_value if raw_value is not None else "").strip()
    if field.kind == "texture":
        value = value.replace("\\", "/")
        if not value or not re.search(r"\.[A-Za-z0-9]{2,8}$", value):
            raise ValueError(f"{field.parameter_name} requires a non-empty asset path with a file extension.")
    elif field.kind == "color":
        _parse_color_components(value, field.value)
    elif field.kind in {"float", *tuple(_VECTOR_COMPONENT_COUNTS)}:
        expected = _VECTOR_COMPONENT_COUNTS.get(field.kind, 1)
        values = _numeric_tokens(value)
        if len(values) != expected:
            raise ValueError(f"{field.parameter_name} requires {expected} numeric value(s).")
    elif field.kind == "bool":
        if value.casefold() not in {"0", "1", "false", "true"}:
            raise ValueError(f"{field.parameter_name} requires 0/1 or false/true.")
    elif field.kind == "int":
        _bounded_integer(value, -(2**31), 2**31 - 1, field.parameter_name)
    elif field.kind in {"uint", "byte4", "bitflag32"}:
        _bounded_integer(value, 0, 0xFFFFFFFF, field.parameter_name)
    elif field.kind == "clothcategory" and not value:
        raise ValueError(f"{field.parameter_name} requires a category value.")
    return value


def _normalized_replacement_value(field: PacXmlField, value: str) -> str:
    if field.kind == "color" and field.value.startswith("#"):
        parsed = _parse_color_components(value, field.value)
        alpha = field.value.lstrip("#")[6:8] if len(field.value.lstrip("#")) == 8 else ""
        return _format_hex_color(parsed, alpha)
    if field.kind == "bool":
        normalized = value.casefold()
        if field.value.casefold() in {"true", "false"}:
            return "true" if normalized in {"1", "true"} else "false"
        return "1" if normalized in {"1", "true"} else "0"
    if field.kind in {"float", *tuple(_VECTOR_COMPONENT_COUNTS)}:
        separator = ", " if "," in field.value else " "
        return separator.join(_format_float(number) for number in _numeric_tokens(value))
    if field.kind in {"int", "uint", "byte4", "bitflag32"}:
        return str(int(value, 0))
    return value.replace("\\", "/") if field.kind == "texture" else value


def _validate_xml_fragment(text: str) -> None:
    normalized = str(text).lstrip("\ufeff")
    normalized = _XML_DECLARATION_RE.sub("", normalized, count=1)
    try:
        ET.fromstring(f"<PacXmlEditorRoot>{normalized}</PacXmlEditorRoot>")
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse material sidecar XML: {exc}") from exc


def _structural_signature(tokens: Sequence[_XmlToken]) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for token in tokens:
        if token.kind != "start":
            continue
        local = token.local_name
        attrs = _attribute_map(token.attributes)
        if local.casefold().endswith("materialwrapper"):
            rows.append(
                (
                    "wrapper",
                    local,
                    _first_attribute_value(attrs, ("_subMeshName", "SubMeshName", "Name", "name")),
                    *_locked_identity_values(attrs),
                )
            )
        elif local.casefold() == "material":
            rows.append(
                (
                    "material",
                    local,
                    _first_attribute_value(attrs, ("_materialName", "MaterialName", "materialName")),
                    *_locked_identity_values(attrs),
                )
            )
        elif local.startswith(_PARAMETER_PREFIX):
            rows.append(
                (
                    "parameter",
                    local,
                    _first_attribute_value(attrs, _NAME_ATTRS),
                    *_locked_identity_values(attrs),
                )
            )
    return tuple(rows)


def _locked_identity_values(attrs: Mapping[str, _AttributeToken]) -> tuple[str, str, str]:
    return (
        _first_attribute_value(attrs, ("ItemID", "_itemID", "itemID", "id")),
        _first_attribute_value(attrs, ("Index", "_index", "index")),
        _first_attribute_value(attrs, ("IdBase", "IDBase", "_idBase", "idBase")),
    )


def _attribute_map(attributes: Sequence[_AttributeToken]) -> dict[str, _AttributeToken]:
    return {attribute.name.casefold(): attribute for attribute in attributes}


def _first_attribute_value(attrs: Mapping[str, _AttributeToken], names: Sequence[str]) -> str:
    target = _first_existing_attribute(attrs, names)
    return target.value.strip() if target is not None else ""


def _first_existing_attribute(
    attrs: Mapping[str, _AttributeToken],
    names: Sequence[str],
    *,
    require_texture: bool = False,
) -> _AttributeToken | None:
    for name in names:
        attribute = attrs.get(name.casefold())
        if attribute is None:
            continue
        if require_texture and not _looks_like_texture_reference(attribute.value):
            continue
        return attribute
    return None


def _rgb_attribute_tokens(attrs: Mapping[str, _AttributeToken]) -> tuple[_AttributeToken, ...]:
    for names in _RGB_ATTR_GROUPS:
        values = tuple(attrs.get(name.casefold()) for name in names)
        if all(value is not None and _is_float(value.value) for value in values):
            return tuple(value for value in values if value is not None)
    return ()


def _insertion_attribute(attrs: Mapping[str, _AttributeToken]) -> str:
    return "_value" if any(name.casefold() in attrs for name in ("_name", "StringItemID", "ItemID", "Index")) else "Value"


def _field_risk(parameter_name: str, kind: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", parameter_name.casefold())
    if kind == "bitflag32" or normalized in {"rendersettingflag", "clothmaskbit", "colorblendingflag"}:
        return "Runtime flag; review in game after export."
    if kind not in _KNOWN_KINDS:
        return "Unknown value type; editing is disabled."
    return ""


def _field_detail(parameter_type: str, shader_name: str, explicit: bool, risk: str) -> str:
    parts = [f"Material {parameter_type} parameter"]
    if shader_name:
        parts.append(f"Shader: {shader_name}")
    if not explicit:
        parts.append("Inherited/default; no explicit value attribute")
    if risk:
        parts.append(risk)
    return " | ".join(parts)


def _looks_like_texture_reference(value: str) -> bool:
    return bool(re.search(r"\.(dds|png|jpg|jpeg|tga|bmp|tif|tiff)\b", str(value), re.IGNORECASE))


def _looks_like_texture_resource_tag(local_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", local_name.casefold())
    return local_name == "ResourceReferencePath_ITexture" or "textureref" in normalized or ("texture" in normalized and any(token in normalized for token in ("resource", "reference", "path", "file")))


def _span(attribute: _AttributeToken) -> PacXmlValueSpan:
    return PacXmlValueSpan(attribute.value_start, attribute.value_end, attribute.name, attribute.quote)


def _row_id(kind: str, element_index: int, parameter_name: str, target_attr: str = "") -> str:
    normalized_parameter = re.sub(r"[^a-z0-9_]+", "_", str(parameter_name).strip().casefold()).strip("_")
    normalized_attr = re.sub(r"[^a-z0-9_]+", "_", str(target_attr).strip().casefold()).strip("_")
    return ":".join(part for part in (kind, str(element_index), normalized_parameter, normalized_attr) if part)


def _row_element_index(row_id: str) -> int:
    try:
        return int(str(row_id).split(":", 2)[1])
    except (IndexError, TypeError, ValueError):
        return 0


def _local_name(name: str) -> str:
    return str(name).rsplit(":", 1)[-1].rsplit("}", 1)[-1]


def _numeric_tokens(value: str) -> tuple[float, ...]:
    tokens = [token for token in re.split(r"[\s,;]+", str(value).strip()) if token]
    try:
        return tuple(float(token) for token in tokens)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value: {value}") from exc


def _parse_color_components(value: str, original: str = "") -> tuple[float, float, float]:
    normalized = str(value).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", normalized):
        return tuple(int(normalized[index : index + 2], 16) / 255.0 for index in (0, 2, 4))  # type: ignore[return-value]
    values = _numeric_tokens(value)
    if len(values) < 3:
        raise ValueError(f"Invalid color value: {value or original}")
    return values[0], values[1], values[2]


def _format_hex_color(values: Sequence[float], alpha: str = "") -> str:
    channels = [f"{max(0, min(255, round(float(value) * 255))):02x}" for value in tuple(values)[:3]]
    if re.fullmatch(r"[0-9a-fA-F]{2}", alpha):
        channels.append(alpha.casefold())
    return "#" + "".join(channels)


def _format_float(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".") or "0"


def _is_float(value: str) -> bool:
    try:
        float(str(value).strip())
    except ValueError:
        return False
    return True


def _bounded_integer(value: str, minimum: int, maximum: int, label: str) -> int:
    try:
        parsed = int(str(value).strip(), 0)
    except ValueError as exc:
        raise ValueError(f"{label} requires an integer value.") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return parsed


def _escaped_attribute_value(value: str, quote: str) -> str:
    entities = {'"': "&quot;"} if quote == '"' else {"'": "&apos;"}
    return escape(str(value), entities)


def _validate_non_overlapping_replacements(replacements: Sequence[tuple[int, int, str]]) -> None:
    previous_end = -1
    for start, end, _replacement in sorted(replacements, key=lambda item: (item[0], item[1])):
        if start < previous_end:
            raise ValueError("PAC XML edits overlap and cannot be applied safely.")
        previous_end = max(previous_end, end)


__all__ = [
    "PacXmlDocument",
    "PacXmlEditResult",
    "PacXmlField",
    "PacXmlSourceFormat",
    "PacXmlValueSpan",
    "apply_pac_xml_edits",
    "decode_pac_xml_payload",
    "encode_pac_xml_text",
    "parse_pac_xml_document",
    "parse_pac_xml_payload",
]
