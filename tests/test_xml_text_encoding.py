import ast
import unittest
from pathlib import Path

from cdmw.core import xml_text as core_xml_text
from cdmw.core.xml_text import decode_xml_text_payload, encode_xml_text_like_source
from cdmw.domain import xml_text as domain_xml_text


KOREAN_LABEL = "\ub514\uc2a4\ud06c\ub9bd\uc158 / \ud074\ub9ac\ud504"
CP1252_BYTES_TO_TEXT = {
    0x80: "\u20ac",
    0x82: "\u201a",
    0x83: "\u0192",
    0x84: "\u201e",
    0x85: "\u2026",
    0x86: "\u2020",
    0x87: "\u2021",
    0x88: "\u02c6",
    0x89: "\u2030",
    0x8A: "\u0160",
    0x8B: "\u2039",
    0x8C: "\u0152",
    0x8E: "\u017d",
    0x91: "\u2018",
    0x92: "\u2019",
    0x93: "\u201c",
    0x94: "\u201d",
    0x95: "\u2022",
    0x96: "\u2013",
    0x97: "\u2014",
    0x98: "\u02dc",
    0x99: "\u2122",
    0x9A: "\u0161",
    0x9B: "\u203a",
    0x9C: "\u0153",
    0x9E: "\u017e",
    0x9F: "\u0178",
}


def _windows_1252ish_mojibake(data: bytes) -> str:
    return "".join(CP1252_BYTES_TO_TEXT.get(value, chr(value)) for value in data)


class XmlTextEncodingTests(unittest.TestCase):
    def test_core_exports_domain_owned_objects_and_ui_uses_domain_owner(self) -> None:
        self.assertIs(core_xml_text.DecodedXmlText, domain_xml_text.DecodedXmlText)
        self.assertIs(core_xml_text.decode_xml_text_payload, domain_xml_text.decode_xml_text_payload)
        self.assertIs(core_xml_text.encode_xml_text_like_source, domain_xml_text.encode_xml_text_like_source)
        offenders: list[str] = []
        for path in Path("cdmw/ui").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "cdmw.core.xml_text":
                    offenders.append(path.as_posix())
                elif isinstance(node, ast.Import) and any(
                    alias.name == "cdmw.core.xml_text" for alias in node.names
                ):
                    offenders.append(path.as_posix())
        self.assertEqual([], offenders)

    def test_utf8_korean_xml_round_trips_without_mojibake(self) -> None:
        source_text = f"<!-- {KOREAN_LABEL} --><Root />"
        decoded = decode_xml_text_payload(source_text.encode("utf-8"))

        patched_text = decoded.text.replace("<Root />", '<Root Socket="Pelvis_L_Socket" />')
        encoded = encode_xml_text_like_source(patched_text, decoded)

        self.assertIn(KOREAN_LABEL, decoded.text)
        self.assertEqual(encoded, patched_text.encode("utf-8"))
        self.assertNotIn("ë", encoded.decode("utf-8"))

    def test_utf8_korean_mojibake_is_repaired_before_write(self) -> None:
        source_text = f"<!-- {KOREAN_LABEL} --><Root />"
        mojibake_text = _windows_1252ish_mojibake(source_text.encode("utf-8"))

        decoded = decode_xml_text_payload(mojibake_text.encode("utf-8"))
        encoded = encode_xml_text_like_source(decoded.text, decoded)

        self.assertIn(KOREAN_LABEL, decoded.text)
        self.assertTrue(decoded.repaired_mojibake)
        self.assertIn(KOREAN_LABEL, encoded.decode("utf-8"))

    def test_utf16le_bom_xml_keeps_source_encoding_on_write(self) -> None:
        source_text = f'<?xml version="1.0" encoding="utf-16"?><Root Name="{KOREAN_LABEL}" />'
        source_data = b"\xff\xfe" + source_text.encode("utf-16-le")

        decoded = decode_xml_text_payload(source_data)
        patched_text = decoded.text.replace("/>", ' Socket="Spine2_B_SubWeapon_Socket" />')
        encoded = encode_xml_text_like_source(patched_text, decoded)

        self.assertTrue(encoded.startswith(b"\xff\xfe"))
        self.assertIn(KOREAN_LABEL, encoded[2:].decode("utf-16-le"))
        self.assertIn("Spine2_B_SubWeapon_Socket", encoded[2:].decode("utf-16-le"))

    def test_inserted_declaration_is_synced_to_source_encoding(self) -> None:
        source_text = f"<Root Name=\"{KOREAN_LABEL}\" />"
        source_data = b"\xff\xfe" + source_text.encode("utf-16-le")
        decoded = decode_xml_text_payload(source_data)

        patched_text = '<?xml version="1.0" encoding="utf-8"?>\n' + decoded.text
        encoded = encode_xml_text_like_source(patched_text, decoded)
        rewritten = encoded[2:].decode("utf-16-le")

        self.assertIn('encoding="utf-16"', rewritten)
        self.assertNotIn('encoding="utf-8"', rewritten)

    def test_declared_cp949_xml_keeps_korean_text_on_write(self) -> None:
        source_text = f'<?xml version="1.0" encoding="cp949"?><Root Name="{KOREAN_LABEL}" />'
        source_data = source_text.encode("cp949")

        decoded = decode_xml_text_payload(source_data)
        patched_text = decoded.text.replace("/>", ' Socket="Pelvis_L_Socket" />')
        encoded = encode_xml_text_like_source(patched_text, decoded)

        self.assertEqual(decoded.encoding, "cp949")
        self.assertIn(KOREAN_LABEL, encoded.decode("cp949"))
        self.assertIn("Pelvis_L_Socket", encoded.decode("cp949"))


if __name__ == "__main__":
    unittest.main()
