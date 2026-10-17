"""Exact model-property resource fields without collateral text replacements."""
import pytest

from cdmw.core.pac_xml_references import PacXmlReferenceError, parse_pac_xml_references


A = "character/texture/a.dds"
B = "character/texture/b.dds"
C = "character/texture/c.dds"


def test_texture_rewrite_is_simultaneous_and_preserves_unrelated_bytes():
    data = (b"\xef\xbb\xbf<SkinnedMeshPropertyCommon/>\r\n<ModelPropertyList>\r\n"
            + f"<!-- {A} --><![CDATA[{A}]]><Label text='{A}'>{A}</Label>\r\n".encode()
            + f"<ResourceReferencePath_ITexture Name='{A}' _path='{A}'/>\r\n".encode()
            + f'<ResourceReferencePath_ITexture _path="{B}" Name="_value"/>\r\n'.encode()
            + f'<ResourceReferencePath_ITexture Name="_value" _path="{A}.backup"/>\r\n'.encode()
            + f'<ResourceReferencePath_IModel Name="_value" _path="{A}"/>\r\n'.encode()
            + b"</ModelPropertyList>")
    document = parse_pac_xml_references(data)
    result = document.rewrite_textures({A: B, B: C})
    expected = data.replace(f"_path='{A}'".encode(), f"_path='{B}'".encode())
    expected = expected.replace(f'_path="{B}"'.encode(), f'_path="{C}"'.encode())
    assert result == expected
    assert document.data is data
    assert [row.path for row in document.references] == [A, B, A + ".backup", A]


def test_rewrite_uses_decoded_attributes_and_exact_lexical_spans():
    data = (b'<ModelPropertyList><ResourceReferencePath_ITexture\n'
            b' Name="_path=&quot;character/texture/a.dds&quot;"'
            b" _path='CHARACTER\\TEXTURE\\&#97;.DDS'/></ModelPropertyList>")
    document = parse_pac_xml_references(data)
    assert document.references[0].path == "CHARACTER\\TEXTURE\\a.DDS"
    result = document.rewrite_textures({A: "character/texture/b&c'd.dds"})
    assert result == data.replace(b"CHARACTER\\TEXTURE\\&#97;.DDS", b"character/texture/b&amp;c&apos;d.dds")
    assert parse_pac_xml_references(result).references[0].path == "character/texture/b&c'd.dds"


@pytest.mark.parametrize("data", [
    b"<OtherRoot/>", b"<ModelPropertyList>", b"<ModelPropertyList/>\x00",
    b'<!DOCTYPE test [<!ENTITY path "character/texture/a.dds">]><ModelPropertyList/>',
    b'<ModelPropertyList><ResourceReferencePath_ITexture _path="a" Other="b"/></ModelPropertyList>',
    b'<ModelPropertyList><ResourceReferencePath_ITexture _path="a" _path="b"/></ModelPropertyList>',
])
def test_unknown_or_malformed_reference_boundaries_refuse(data):
    with pytest.raises(PacXmlReferenceError):
        parse_pac_xml_references(data)


def test_cancellation_is_observed_during_parse_and_rewrite():
    data = (b"<ModelPropertyList>" + f'<ResourceReferencePath_ITexture _path="{A}"/>'.encode()
            + b"</ModelPropertyList>")
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        parse_pac_xml_references(data, check=cancel)
    document = parse_pac_xml_references(data)
    calls = 3
    with pytest.raises(RuntimeError, match="cancelled"):
        document.rewrite_textures({A: B}, check=cancel)


def test_normalized_duplicate_source_cannot_select_different_targets():
    document = parse_pac_xml_references(b"<ModelPropertyList/>")
    with pytest.raises(PacXmlReferenceError, match="Ambiguous"):
        document.rewrite_textures({A: B, A.upper(): C})
