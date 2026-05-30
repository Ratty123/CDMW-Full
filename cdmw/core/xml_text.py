from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from typing import Iterable, Optional


_XML_DECL_ENCODING_RE = re.compile(br"<\?xml\s+[^>]*encoding\s*=\s*(['\"])(?P<encoding>[^'\"]+)\1", re.IGNORECASE)
_TEXT_XML_DECL_ENCODING_RE = re.compile(r"(<\?xml\s+[^>]*encoding\s*=\s*)(['\"])([^'\"]+)(\2)", re.IGNORECASE)
_CP1252_SPECIAL_TO_BYTE = {
    "\u20ac": 0x80,
    "\u201a": 0x82,
    "\u0192": 0x83,
    "\u201e": 0x84,
    "\u2026": 0x85,
    "\u2020": 0x86,
    "\u2021": 0x87,
    "\u02c6": 0x88,
    "\u2030": 0x89,
    "\u0160": 0x8A,
    "\u2039": 0x8B,
    "\u0152": 0x8C,
    "\u017d": 0x8E,
    "\u2018": 0x91,
    "\u2019": 0x92,
    "\u201c": 0x93,
    "\u201d": 0x94,
    "\u2022": 0x95,
    "\u2013": 0x96,
    "\u2014": 0x97,
    "\u02dc": 0x98,
    "\u2122": 0x99,
    "\u0161": 0x9A,
    "\u203a": 0x9B,
    "\u0153": 0x9C,
    "\u017e": 0x9E,
    "\u0178": 0x9F,
}


@dataclass(frozen=True, slots=True)
class DecodedXmlText:
    text: str
    encoding: str = "utf-8"
    bom: bytes = b""
    repaired_mojibake: bool = False


def _encoding_name(value: object) -> str:
    raw = str(value or "").strip().strip("'\"")
    if not raw:
        return ""
    try:
        name = codecs.lookup(raw).name
    except LookupError:
        return raw
    if name == "utf-8-sig":
        return "utf-8"
    return name


def _declared_encoding_ascii(data: bytes) -> str:
    match = _XML_DECL_ENCODING_RE.search(bytes(data[:512]))
    if not match:
        return ""
    try:
        return _encoding_name(match.group("encoding").decode("ascii", errors="ignore"))
    except Exception:
        return ""


def _declared_encoding_utf16(data: bytes, encoding: str) -> str:
    try:
        prefix = bytes(data[:1024]).decode(encoding, errors="strict")
    except UnicodeError:
        return ""
    match = _TEXT_XML_DECL_ENCODING_RE.search(prefix)
    return _encoding_name(match.group(3)) if match else ""


def _detect_utf16_no_bom(data: bytes) -> str:
    sample = bytes(data[:256])
    if len(sample) < 4:
        return ""
    even_nuls = sample[0::2].count(0)
    odd_nuls = sample[1::2].count(0)
    if odd_nuls > max(2, len(sample) // 6) and even_nuls <= max(1, odd_nuls // 8):
        return "utf-16-le"
    if even_nuls > max(2, len(sample) // 6) and odd_nuls <= max(1, even_nuls // 8):
        return "utf-16-be"
    if sample.startswith(b"<\x00?\x00x\x00m\x00l\x00"):
        return "utf-16-le"
    if sample.startswith(b"\x00<\x00?\x00x\x00m\x00l"):
        return "utf-16-be"
    return ""


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _encoding_name(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def _hangul_count(text: str) -> int:
    return sum(1 for char in str(text or "") if "\uac00" <= char <= "\ud7af")


def _mojibake_score(text: str) -> int:
    value = str(text or "")
    markers = ("Ã", "Â", "â", "€", "™", "œ", "ì", "í", "ë", "\ufffd")
    return sum(value.count(marker) for marker in markers)


def _encode_windows_mojibake_bytes(text: str) -> bytes:
    result = bytearray()
    for char in str(text or ""):
        codepoint = ord(char)
        if codepoint <= 0xFF:
            result.append(codepoint)
            continue
        mapped = _CP1252_SPECIAL_TO_BYTE.get(char)
        if mapped is None:
            raise UnicodeEncodeError("windows-mojibake", char, 0, 1, "character cannot map to original byte")
        result.append(mapped)
    return bytes(result)


def repair_utf8_mojibake(text: str) -> str:
    value = str(text or "")
    original_score = _mojibake_score(value)
    if original_score < 4:
        return value
    original_hangul = _hangul_count(value)
    best = value
    best_score = original_score
    best_hangul = original_hangul
    candidates: list[str] = []
    try:
        candidates.append(_encode_windows_mojibake_bytes(value).decode("utf-8"))
    except UnicodeError:
        pass
    for wrong_encoding in ("cp1252", "latin-1"):
        try:
            candidates.append(value.encode(wrong_encoding).decode("utf-8"))
        except UnicodeError:
            continue
    for candidate in candidates:
        candidate_hangul = _hangul_count(candidate)
        candidate_score = _mojibake_score(candidate)
        if candidate_hangul > best_hangul and candidate_score < best_score:
            best = candidate
            best_score = candidate_score
            best_hangul = candidate_hangul
    return best


def decode_xml_text_payload(data: bytes, *, repair_mojibake: bool = True) -> DecodedXmlText:
    payload = bytes(data or b"")
    if not payload:
        return DecodedXmlText("")

    bom = b""
    bom_encoding = ""
    if payload.startswith(b"\xef\xbb\xbf"):
        bom = b"\xef\xbb\xbf"
        bom_encoding = "utf-8"
    elif payload.startswith(b"\xff\xfe"):
        bom = b"\xff\xfe"
        bom_encoding = "utf-16-le"
    elif payload.startswith(b"\xfe\xff"):
        bom = b"\xfe\xff"
        bom_encoding = "utf-16-be"

    body = payload[len(bom) :] if bom else payload
    utf16_guess = _detect_utf16_no_bom(body)
    declared = _declared_encoding_utf16(body, utf16_guess) if utf16_guess else _declared_encoding_ascii(body)
    candidates = _dedupe(
        (
            bom_encoding,
            declared,
            utf16_guess,
            "utf-8",
            "cp949",
            "euc-kr",
            "cp1252",
        )
    )
    last_error: Optional[UnicodeError] = None
    for encoding in candidates:
        try:
            text = body.decode(encoding, errors="strict").lstrip("\ufeff")
        except UnicodeError as exc:
            last_error = exc
            continue
        repaired = repair_utf8_mojibake(text) if repair_mojibake else text
        return DecodedXmlText(
            text=repaired,
            encoding=encoding,
            bom=bom,
            repaired_mojibake=repaired != text,
        )
    fallback = body.decode("utf-8", errors="replace").lstrip("\ufeff")
    repaired = repair_utf8_mojibake(fallback) if repair_mojibake else fallback
    return DecodedXmlText(
        text=repaired,
        encoding="utf-8",
        bom=bom,
        repaired_mojibake=repaired != fallback or last_error is not None,
    )


def _replace_declared_encoding(text: str, encoding: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}{encoding}{match.group(4)}"

    return _TEXT_XML_DECL_ENCODING_RE.sub(replace, str(text or ""), count=1)


def _text_declared_encoding(text: str) -> str:
    match = _TEXT_XML_DECL_ENCODING_RE.search(str(text or ""))
    return _encoding_name(match.group(3)) if match else ""


def _xml_declaration_encoding_label(encoding: str, bom: bytes) -> str:
    normalized = _encoding_name(encoding)
    if normalized == "utf-16-le" and bom:
        return "utf-16"
    if normalized == "utf-16-be" and bom:
        return "utf-16"
    if normalized == "euc_kr":
        return "euc-kr"
    return normalized or "utf-8"


def encode_xml_text_like_source(text: str, source: bytes | DecodedXmlText | None = None) -> bytes:
    if isinstance(source, DecodedXmlText):
        decoded = source
    else:
        decoded = decode_xml_text_payload(bytes(source or b""), repair_mojibake=False)
    payload_text = str(text or "").lstrip("\ufeff")
    encoding = _encoding_name(decoded.encoding) or "utf-8"
    declared_encoding = _text_declared_encoding(payload_text)
    if declared_encoding and declared_encoding != encoding:
        payload_text = _replace_declared_encoding(
            payload_text,
            _xml_declaration_encoding_label(encoding, decoded.bom),
        )
    try:
        return bytes(decoded.bom or b"") + payload_text.encode(encoding, errors="strict")
    except UnicodeError:
        payload_text = _replace_declared_encoding(payload_text, "utf-8")
        return payload_text.encode("utf-8", errors="strict")
