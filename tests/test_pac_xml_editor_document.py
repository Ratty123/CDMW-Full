from __future__ import annotations

import codecs

import pytest

from cdmw.domain.pac_xml_editor import (
    PacXmlSourceFormat,
    parse_pac_xml_document,
    parse_pac_xml_payload,
)


ALL_TYPES_XML = """<?xml version="1.0" encoding="utf-8"?>
<!-- preserve this comment -->
<SkinnedMeshMaterialWrapper _subMeshName="body" ItemID="100" Index="0" IdBase="500">
  <Material _materialName="SkinnedMeshStandard_Ver2" ItemID="101">
    <MaterialParameterTexture _name="_baseColorTexture" ItemID="1" Index="0"><ResourceReferencePath_ITexture _path="character/texture/body.dds" /></MaterialParameterTexture>
    <MaterialParameterColor _name="_tint" ItemID="2" Index="1" _value="#112233ff" />
    <MaterialParameterFloat _name="_roughness" ItemID="3" Index="2" _value="0.5" />
    <MaterialParameterFloat2 _name="_uv" ItemID="4" Index="3" _value="1 2" />
    <MaterialParameterFloat3 _name="_direction" ItemID="5" Index="4" _value="1, 2, 3" />
    <MaterialParameterHalf2 _name="_half" ItemID="6" Index="5" _value="0.25 0.75" />
    <MaterialParameterBool _name="_enabled" ItemID="7" Index="6" _value="true" />
    <MaterialParameterInt _name="_signed" ItemID="8" Index="7" _value="-3" />
    <MaterialParameterUint _name="_unsigned" ItemID="9" Index="8" _value="12" />
    <MaterialParameterByte4 _name="_channels" ItemID="10" Index="9" _value="305419896" />
    <MaterialParameterBitFlag32 _name="_flags" ItemID="11" Index="10" _value="7" />
    <MaterialParameterClothCategory _name="_cloth" ItemID="12" Index="11" _value="Cape" />
    <MaterialParameterFloat _name="_absent" ItemID="13" Index="12" />
    <MaterialParameterMystery _name="_future" ItemID="14" Index="13" _value="opaque" />
  </Material>
</SkinnedMeshMaterialWrapper>
<SkinnedMeshMaterialWrapper _subMeshName="trim" ItemID="200" Index="1" IdBase="600">
  <Material _materialName="SkinnedMeshCloth_Ver2">
    <MaterialParameterFloat _name="_roughness" ItemID="15" Index="0" _value="0.9" />
  </Material>
</SkinnedMeshMaterialWrapper>
"""


def test_discovers_all_supported_types_in_source_order_and_unknown_read_only() -> None:
    document = parse_pac_xml_document(ALL_TYPES_XML)

    assert [field.kind for field in document.fields[:12]] == [
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
    ]
    assert [field.group_label for field in document.fields[-2:]] == ["body", "trim"]
    unknown = next(field for field in document.fields if field.kind == "mystery")
    assert not unknown.editable
    assert unknown.value == "opaque"


def test_duplicate_names_have_stable_distinct_row_ids_and_target_one_source_span() -> None:
    document = parse_pac_xml_document(ALL_TYPES_XML)
    duplicates = [field for field in document.fields if field.parameter_name == "_roughness"]

    assert len(duplicates) == 2
    assert duplicates[0].row_id != duplicates[1].row_id
    result = document.render({duplicates[1].row_id: "0.125"})

    assert '_value="0.5"' in result.text
    assert '_value="0.125"' in result.text
    assert result.changed_rows == (duplicates[1].row_id,)
    assert result.structural_signature == document.structural_signature


def test_absent_scalar_value_can_be_explicitly_set_without_reformatting_tag() -> None:
    document = parse_pac_xml_document(ALL_TYPES_XML)
    field = next(value for value in document.fields if value.parameter_name == "_absent")

    assert not field.explicit
    result = document.render({field.row_id: "1.25"})

    assert '<MaterialParameterFloat _name="_absent" ItemID="13" Index="12"  _value="1.25"/>' in result.text
    assert "<!-- preserve this comment -->" in result.text


@pytest.mark.parametrize(
    ("parameter", "value", "expected"),
    [
        ("_tint", "#abcdef", '#abcdefff'),
        ("_roughness", "1.75", '1.75'),
        ("_uv", "3, 4", '3 4'),
        ("_direction", "4 5 6", '4, 5, 6'),
        ("_half", "0.1 0.2", '0.1 0.2'),
        ("_enabled", "0", 'false'),
        ("_signed", "-20", '-20'),
        ("_unsigned", "0x20", '32'),
        ("_channels", "0xAABBCCDD", '2864434397'),
        ("_flags", "0x80000001", '2147483649'),
        ("_cloth", "Skirt", 'Skirt'),
    ],
)
def test_applies_each_guided_scalar_type(parameter: str, value: str, expected: str) -> None:
    document = parse_pac_xml_document(ALL_TYPES_XML)
    field = next(item for item in document.fields if item.parameter_name == parameter)

    result = document.render({field.row_id: value})

    reparsed = parse_pac_xml_document(result.text)
    reparsed_field = next(item for item in reparsed.fields if item.row_id == field.row_id)
    assert reparsed_field.value == expected


def test_texture_edit_escapes_xml_and_round_trips_exact_value() -> None:
    document = parse_pac_xml_document(ALL_TYPES_XML)
    field = next(item for item in document.fields if item.kind == "texture")
    edited_path = 'character/texture/a&b"c.dds'

    result = document.render({field.row_id: edited_path})

    assert "a&amp;b&quot;c.dds" in result.text
    assert parse_pac_xml_document(result.text).field_by_id()[field.row_id].value == edited_path


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("_roughness", "not-a-number"),
        ("_uv", "1 2 3"),
        ("_enabled", "maybe"),
        ("_unsigned", "-1"),
        ("_channels", "0x100000000"),
    ],
)
def test_rejects_invalid_typed_values(parameter: str, value: str) -> None:
    document = parse_pac_xml_document(ALL_TYPES_XML)
    field = next(item for item in document.fields if item.parameter_name == parameter)

    with pytest.raises(ValueError):
        document.render({field.row_id: value})


def test_unknown_parameter_cannot_be_edited() -> None:
    document = parse_pac_xml_document(ALL_TYPES_XML)
    field = next(item for item in document.fields if item.kind == "mystery")

    with pytest.raises(ValueError, match="read-only"):
        document.render({field.row_id: "changed"})


def test_equivalent_integer_notation_is_a_byte_level_noop() -> None:
    document = parse_pac_xml_document(ALL_TYPES_XML)
    field = next(item for item in document.fields if item.parameter_name == "_unsigned")

    result = document.render({field.row_id: "0xC"})

    assert result.changed_rows == ()
    assert result.payload == document.original_payload


@pytest.mark.parametrize(
    "payload",
    [
        ALL_TYPES_XML.replace("\n", "\r\n").encode("utf-8"),
        codecs.BOM_UTF8 + ALL_TYPES_XML.encode("utf-8"),
        codecs.BOM_UTF16_LE
        + ALL_TYPES_XML.replace('encoding="utf-8"', 'encoding="utf-16"').encode("utf-16-le"),
        codecs.BOM_UTF16_BE
        + ALL_TYPES_XML.replace('encoding="utf-8"', 'encoding="utf-16"').encode("utf-16-be"),
        ALL_TYPES_XML.replace('encoding="utf-8"', 'encoding="utf-16"').encode("utf-16-le"),
        ALL_TYPES_XML.replace('encoding="utf-8"', 'encoding="utf-16"').encode("utf-16-be"),
    ],
)
def test_noop_and_single_edit_preserve_encoding_bom_newlines_and_untouched_bytes(payload: bytes) -> None:
    document = parse_pac_xml_payload(payload)
    assert document.render({}).payload == payload
    field = next(item for item in document.fields if item.parameter_name == "_signed")

    result = document.render({field.row_id: "-4"})

    assert result.payload.startswith(document.source_format.bom)
    decoded = result.payload[len(document.source_format.bom) :].decode(document.source_format.encoding)
    assert decoded.count(document.source_format.newline) == document.text.count(document.source_format.newline)
    assert "<!-- preserve this comment -->" in decoded
    assert 'ItemID="8" Index="7"' in decoded


def test_payload_larger_than_legacy_preview_limit_is_complete_and_byte_stable() -> None:
    comment = "x" * 260_000
    text = f"<!--{comment}-->\n<MaterialParameterFloat _name=\"_value\" _value=\"1\" />"
    payload = text.encode("utf-8")

    document = parse_pac_xml_payload(payload)

    assert len(document.text) > 240_000
    assert document.render({}).payload == payload
    result = document.render({document.fields[0].row_id: "2"})
    assert comment.encode("ascii") in result.payload
    assert result.payload.endswith(b'_value="2" />')


def test_invalid_or_malformed_fragment_is_rejected() -> None:
    with pytest.raises(ValueError, match="Could not parse"):
        parse_pac_xml_document("<MaterialParameterFloat>")


def test_source_format_metadata_is_honored_for_text_documents() -> None:
    source_format = PacXmlSourceFormat(encoding="utf-8", bom=codecs.BOM_UTF8, newline="\r\n")
    text = '<MaterialParameterFloat _name="_value" _value="1" />\r\n'
    document = parse_pac_xml_document(text, source_format=source_format)

    assert document.original_payload == codecs.BOM_UTF8 + text.encode("utf-8")
