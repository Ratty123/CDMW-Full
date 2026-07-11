"""Compatibility exports for domain-owned XML text rules."""

from cdmw.domain.xml_text import (
    DecodedXmlText,
    decode_xml_text_payload,
    encode_xml_text_like_source,
    repair_utf8_mojibake,
)


__all__ = [
    "DecodedXmlText",
    "decode_xml_text_payload",
    "encode_xml_text_like_source",
    "repair_utf8_mojibake",
]
