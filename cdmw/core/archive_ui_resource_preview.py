"""Read-only Archive Browser previews for the game's UI fonts and animated cursors.

`ui/fonts/*.ttf` are ordinary TrueType files and `ui/cursor/*.ani` are Windows
animated cursors (a RIFF `ACON` list of `.cur`/`.ico` frames). Both are open
formats, so this module reads them exactly: font names, metrics and script
coverage from the sfnt tables, cursor timing and frames from the RIFF chunks.
Pillow renders a font specimen or a frame strip as the image preview.
"""

from __future__ import annotations

import hashlib
import io
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional

from cdmw.core.archive_model_references import _StructuredBinaryPreviewBundle
from cdmw.core.temp_cache import app_temp_cache_build, app_temp_cache_path, mark_app_temp_cache_recent

FONT_EXTENSIONS = frozenset({".ttf", ".otf", ".ttc"})
ANIMATED_CURSOR_EXTENSIONS = frozenset({".ani"})
UI_RESOURCE_EXTENSIONS = FONT_EXTENSIONS | ANIMATED_CURSOR_EXTENSIONS
# Shares the pruned archive preview cache; units are prefixed "ui-" to stay apart.
_PREVIEW_CACHE_DIRNAME = "archive_preview_cache"
_PREVIEW_VERSION = "1"

_NAME_IDS = (
    (1, "Family"),
    (2, "Style"),
    (4, "Full name"),
    (6, "PostScript name"),
    (5, "Version"),
    (8, "Manufacturer"),
    (9, "Designer"),
    (0, "Copyright"),
)
# Unicode blocks worth naming for a game font: the scripts the 14 interface
# languages need, plus symbol and private-use areas icon fonts occupy.
_SCRIPT_BLOCKS = (
    ("Basic Latin", 0x0020, 0x007E),
    ("Latin-1 Supplement", 0x00A0, 0x00FF),
    ("Latin Extended", 0x0100, 0x024F),
    ("Greek", 0x0370, 0x03FF),
    ("Cyrillic", 0x0400, 0x04FF),
    ("Arabic", 0x0600, 0x06FF),
    ("Thai", 0x0E00, 0x0E7F),
    ("Hangul Jamo", 0x1100, 0x11FF),
    ("General Punctuation", 0x2000, 0x206F),
    ("Arrows and symbols", 0x2190, 0x2BFF),
    ("CJK Symbols and Punctuation", 0x3000, 0x303F),
    ("Hiragana", 0x3040, 0x309F),
    ("Katakana", 0x30A0, 0x30FF),
    ("Bopomofo", 0x3100, 0x312F),
    ("Hangul Compatibility Jamo", 0x3130, 0x318F),
    ("CJK Unified Ideographs", 0x4E00, 0x9FFF),
    ("Hangul Syllables", 0xAC00, 0xD7AF),
    ("Private Use Area", 0xE000, 0xF8FF),
    ("Halfwidth and Fullwidth Forms", 0xFF00, 0xFFEF),
    ("Supplementary planes", 0x10000, 0x10FFFF),
)
_SPECIMEN_LINES = (
    "The quick brown fox jumps over the lazy dog. 0123456789",
    "ÀÉÎÕÜ àéîõü ß Ç ñ Ł ą ę ż ğ ş İ",
    "Съешь же ещё этих мягких французских булок",
    "다람쥐 헌 쳇바퀴에 타고파",
    "いろはにほへと ちりぬるを アイウエオ",
    "天地玄黄 宇宙洪荒 日月盈昃 辰宿列张",
    "ภาษาไทย สวัสดี",
)
_WEIGHT_NAMES = {
    100: "Thin", 200: "Extra Light", 300: "Light", 400: "Regular", 500: "Medium",
    600: "Semi Bold", 700: "Bold", 800: "Extra Bold", 900: "Black",
}


class UiResourceError(ValueError):
    """The bytes are not a font or animated cursor this module can read."""


@dataclass
class FontInfo:
    outline: str
    tables: tuple[str, ...]
    names: dict[str, str] = field(default_factory=dict)
    glyph_count: int = 0
    units_per_em: int = 0
    weight_class: int = 0
    vendor: str = ""
    embedding: str = ""
    code_points: frozenset[int] = frozenset()
    font_count: int = 1


def _be(fmt: str, data: bytes, offset: int) -> tuple:
    try:
        return struct.unpack_from(">" + fmt, data, offset)
    except struct.error as exc:
        raise UiResourceError(f"font table runs past the file at 0x{offset:x}") from exc


def _font_tables(data: bytes, base: int) -> dict[str, tuple[int, int]]:
    version = data[base : base + 4]
    if version not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise UiResourceError("not a TrueType or OpenType font")
    (count,) = _be("H", data, base + 4)
    tables = {}
    for index in range(count):
        tag, _checksum, offset, length = _be("4sIII", data, base + 12 + 16 * index)
        if offset + length > len(data):
            raise UiResourceError(f"table {tag!r} runs past the file")
        tables[tag.decode("latin-1")] = (offset, length)
    return tables


def _decode_name(platform: int, raw: bytes) -> str:
    if platform in (0, 3):
        return raw.decode("utf-16-be", errors="replace")
    return raw.decode("mac_roman", errors="replace")


def _read_names(data: bytes, offset: int) -> dict[str, str]:
    _format, count, strings = _be("HHH", data, offset)
    candidates: dict[int, tuple[int, str]] = {}
    for index in range(count):
        platform, encoding, language, name_id, length, start = _be("6H", data, offset + 6 + 12 * index)
        raw = data[offset + strings + start : offset + strings + start + length]
        # Prefer Windows/Unicode US English, then any Windows/Unicode name, then Mac.
        if platform == 3 and encoding in (1, 10) and language == 0x409:
            rank = 0
        elif platform in (0, 3):
            rank = 1
        elif platform == 1 and encoding == 0:
            rank = 2
        else:
            continue
        text = _decode_name(platform, raw).strip()
        if text and (name_id not in candidates or rank < candidates[name_id][0]):
            candidates[name_id] = (rank, text)
    return {label: candidates[name_id][1] for name_id, label in _NAME_IDS if name_id in candidates}


def _cmap_code_points(data: bytes, offset: int) -> frozenset[int]:
    _version, count = _be("HH", data, offset)
    best: Optional[tuple[int, int]] = None
    for index in range(count):
        platform, encoding, sub_offset = _be("HHI", data, offset + 4 + 8 * index)
        (fmt,) = _be("H", data, offset + sub_offset)
        if fmt == 12 and platform in (0, 3):
            best = (12, offset + sub_offset)
            break
        if fmt == 4 and platform in (0, 3) and best is None:
            best = (4, offset + sub_offset)
    if best is None:
        return frozenset()
    fmt, table = best
    points: set[int] = set()
    if fmt == 12:
        (groups,) = _be("I", data, table + 12)
        for index in range(min(groups, 200_000)):
            start, end, _glyph = _be("III", data, table + 16 + 12 * index)
            if end - start > 0x110000:
                raise UiResourceError("implausible cmap group")
            points.update(range(start, min(end, 0x10FFFF) + 1))
        return frozenset(points)
    (seg_x2,) = _be("H", data, table + 6)
    segments = seg_x2 // 2
    ends = table + 14
    starts = ends + seg_x2 + 2
    deltas = starts + seg_x2
    ranges = deltas + seg_x2
    for index in range(segments):
        (end,) = _be("H", data, ends + 2 * index)
        (start,) = _be("H", data, starts + 2 * index)
        (delta,) = _be("h", data, deltas + 2 * index)
        (range_offset,) = _be("H", data, ranges + 2 * index)
        for code in range(start, end + 1):
            if code == 0xFFFF:
                continue
            if range_offset == 0:
                glyph = (code + delta) & 0xFFFF
            else:
                address = ranges + 2 * index + range_offset + 2 * (code - start)
                (glyph,) = _be("H", data, address)
                glyph = (glyph + delta) & 0xFFFF if glyph else 0
            if glyph:
                points.add(code)
    return frozenset(points)


def read_font_info(data: bytes) -> FontInfo:
    base, font_count = 0, 1
    if data[:4] == b"ttcf":
        font_count, first = _be("I", data, 8)[0], _be("I", data, 12)[0]
        base = first
    tables = _font_tables(data, base)
    outline = "CFF (OpenType)" if "CFF " in tables or "CFF2" in tables else "TrueType outlines"
    info = FontInfo(outline=outline, tables=tuple(sorted(tables)), font_count=font_count)
    if "name" in tables:
        info.names = _read_names(data, tables["name"][0])
    if "maxp" in tables:
        (info.glyph_count,) = _be("H", data, tables["maxp"][0] + 4)
    if "head" in tables:
        (info.units_per_em,) = _be("H", data, tables["head"][0] + 18)
    if "OS/2" in tables and tables["OS/2"][1] >= 62:
        os2 = tables["OS/2"][0]
        info.weight_class, _width, fs_type = _be("HHH", data, os2 + 4)
        info.vendor = data[os2 + 58 : os2 + 62].decode("latin-1", errors="replace").strip()
        info.embedding = (
            "installable" if fs_type & 0xF == 0 else
            "restricted" if fs_type & 0x2 else
            "preview and print" if fs_type & 0x4 else
            "editable" if fs_type & 0x8 else f"0x{fs_type:04x}"
        )
    if "cmap" in tables:
        info.code_points = _cmap_code_points(data, tables["cmap"][0])
    return info


def describe_font(info: FontInfo) -> list[str]:
    lines = ["Summary:"]
    for label, text in info.names.items():
        if label == "Copyright" and len(text) > 160:
            text = text[:157] + "..."
        lines.append(f"- {label}: {text}")
    lines.append(f"- Outlines: {info.outline}")
    if info.font_count > 1:
        lines.append(f"- Collection: {info.font_count} fonts (the first is described)")
    if info.glyph_count:
        lines.append(f"- Glyphs: {info.glyph_count:,}")
    if info.code_points:
        lines.append(f"- Mapped characters: {len(info.code_points):,}")
    if info.units_per_em:
        lines.append(f"- Units per em: {info.units_per_em:,}")
    if info.weight_class:
        weight = _WEIGHT_NAMES.get(info.weight_class, "")
        lines.append(f"- Weight class: {info.weight_class}{f' ({weight})' if weight else ''}")
    if info.vendor:
        lines.append(f"- Vendor ID: {info.vendor}")
    if info.embedding:
        lines.append(f"- Embedding permission: {info.embedding}")
    lines.append(f"- Tables: {', '.join(info.tables)}")
    if info.code_points:
        lines.extend(["", "Character coverage:"])
        for label, start, end in _SCRIPT_BLOCKS:
            count = sum(1 for point in info.code_points if start <= point <= end)
            if count:
                lines.append(f"  {label} (U+{start:04X}-U+{end:04X}): {count:,}")
    return lines


def _cache_png_path(kind: str, data: bytes, virtual_path: str) -> Path:
    digest = hashlib.sha256(data).hexdigest()[:32]
    stem = PurePosixPath(str(virtual_path or "").replace("\\", "/")).stem or kind
    safe_stem = "".join(char if char.isalnum() or char in "-_." else "_" for char in stem)[:80]
    return app_temp_cache_path(_PREVIEW_CACHE_DIRNAME, f"ui-{kind}-v{_PREVIEW_VERSION}-{digest}") / f"{safe_stem}.png"


def _render_cached(target: Path, render) -> Path:
    """Build `target` once under the cache unit's lease, so pruning cannot race the write."""

    with app_temp_cache_build(target.parent):
        if not (target.is_file() and target.stat().st_size > 0):
            render(target)
    mark_app_temp_cache_recent(target.parent)
    return target


def _publish_png(image, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    image.save(staging, format="PNG")
    os.replace(staging, target)
    return target


def render_font_specimen(data: bytes, info: FontInfo, target: Path) -> Path:
    """A specimen PNG: the family name, the sample lines the font covers, and a size ramp."""

    if target.is_file() and target.stat().st_size > 0:
        return target
    from PIL import Image, ImageDraw, ImageFont

    def font(size: int):
        return ImageFont.truetype(io.BytesIO(data), size=size)

    width, margin = 1100, 28
    rows: list[tuple[str, int]] = []
    title = info.names.get("Full name") or info.names.get("Family") or "Font"
    rows.append((title, 40))
    for line in _SPECIMEN_LINES:
        if all(char == " " or ord(char) in info.code_points for char in line):
            rows.append((line, 30))
    private = sorted(point for point in info.code_points if 0xE000 <= point <= 0xF8FF)
    if private:
        rows.append((" ".join(chr(point) for point in private[:28]), 30))
    ramp_sizes = (12, 16, 24, 32, 48)
    height = margin * 2 + sum(int(size * 1.6) for _text, size in rows) + 80
    image = Image.new("RGB", (width, height), (250, 250, 248))
    draw = ImageDraw.Draw(image)
    y = margin
    for text, size in rows:
        draw.text((margin, y), text, font=font(size), fill=(24, 24, 28))
        y += int(size * 1.6)
    x = margin
    label_font = font(12)
    sample = "Aa" if {ord("A"), ord("a")} <= set(info.code_points) else (chr(next(iter(sorted(info.code_points)))) if info.code_points else "Aa")
    for size in ramp_sizes:
        draw.text((x, y + 4), sample, font=font(size), fill=(24, 24, 28))
        draw.text((x, y + 60), f"{size}px", font=label_font, fill=(120, 120, 126))
        x += max(60, int(size * 2.4))
    return _publish_png(image, target)


@dataclass
class AnimatedCursor:
    frame_count: int = 0
    step_count: int = 0
    width: int = 0
    height: int = 0
    default_rate: int = 0
    rates: tuple[int, ...] = ()
    sequence: tuple[int, ...] = ()
    frames: list[bytes] = field(default_factory=list)
    title: str = ""
    artist: str = ""


def read_animated_cursor(data: bytes) -> AnimatedCursor:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"ACON":
        raise UiResourceError("not a RIFF ACON animated cursor")
    cursor = AnimatedCursor()
    end = min(len(data), 8 + struct.unpack_from("<I", data, 4)[0])

    def walk(start: int, stop: int) -> None:
        position = start
        while position + 8 <= stop:
            tag = data[position : position + 4]
            (size,) = struct.unpack_from("<I", data, position + 4)
            body = data[position + 8 : position + 8 + size]
            if position + 8 + size > stop:
                raise UiResourceError(f"chunk {tag!r} runs past its list")
            if tag == b"anih" and size >= 36:
                (_, cursor.frame_count, cursor.step_count, cursor.width, cursor.height,
                 _bits, _planes, cursor.default_rate, _flags) = struct.unpack_from("<9I", body, 0)
            elif tag == b"rate":
                cursor.rates = struct.unpack_from(f"<{size // 4}I", body, 0)
            elif tag == b"seq ":
                cursor.sequence = struct.unpack_from(f"<{size // 4}I", body, 0)
            elif tag == b"LIST" and size >= 4:
                walk(position + 12, position + 8 + size)
            elif tag == b"icon":
                cursor.frames.append(bytes(body))
            elif tag == b"INAM":
                cursor.title = body.split(b"\0", 1)[0].decode("latin-1", errors="replace")
            elif tag == b"IART":
                cursor.artist = body.split(b"\0", 1)[0].decode("latin-1", errors="replace")
            position += 8 + size + (size & 1)

    walk(12, end)
    if not cursor.frames:
        raise UiResourceError("animated cursor has no frames")
    return cursor


def _cursor_frame_image(frame: bytes):
    from PIL import Image

    # Pillow reads .ico; a .cur differs only in the type word and hotspot fields.
    data = frame
    if len(frame) >= 4 and frame[2:4] == b"\x02\x00":
        data = frame[:2] + b"\x01\x00" + frame[4:]
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGBA")


def _cursor_hotspot(frame: bytes) -> Optional[tuple[int, int]]:
    if len(frame) >= 22 and frame[2:4] == b"\x02\x00":
        return struct.unpack_from("<HH", frame, 10)
    return None


def render_cursor_strip(cursor: AnimatedCursor, target: Path, *, scale: int = 3) -> Path:
    if target.is_file() and target.stat().st_size > 0:
        return target
    from PIL import Image

    frames = [_cursor_frame_image(frame) for frame in cursor.frames[:32]]
    cell = max(max(frame.width, frame.height) for frame in frames) * scale + 16
    columns = min(8, len(frames))
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * cell, rows * cell), (0, 0, 0, 0))
    checker = Image.new("RGBA", (cell, cell), (205, 205, 205, 255))
    for y in range(0, cell, 8):
        for x in range(0, cell, 8):
            if (x // 8 + y // 8) % 2:
                checker.paste((240, 240, 240, 255), (x, y, x + 8, y + 8))
    for index, frame in enumerate(frames):
        enlarged = frame.resize((frame.width * scale, frame.height * scale), Image.NEAREST)
        left, top = (index % columns) * cell, (index // columns) * cell
        sheet.paste(checker, (left, top))
        sheet.alpha_composite(enlarged, (left + (cell - enlarged.width) // 2, top + (cell - enlarged.height) // 2))
    return _publish_png(sheet, target)


def describe_animated_cursor(cursor: AnimatedCursor) -> list[str]:
    jiffy_ms = 1000 / 60
    lines = ["Summary:", f"- Frames: {len(cursor.frames)}"]
    if cursor.step_count:
        lines.append(f"- Animation steps: {cursor.step_count}")
    if cursor.width and cursor.height:
        lines.append(f"- Declared size: {cursor.width} x {cursor.height}")
    if cursor.default_rate:
        lines.append(f"- Default frame time: {cursor.default_rate} jiffies ({cursor.default_rate * jiffy_ms:.0f} ms)")
    if cursor.rates:
        lines.append(f"- Per-step times (jiffies): {', '.join(str(rate) for rate in cursor.rates[:32])}")
    if cursor.sequence:
        lines.append(f"- Step order: {', '.join(str(step) for step in cursor.sequence[:32])}")
    if cursor.title:
        lines.append(f"- Title: {cursor.title}")
    if cursor.artist:
        lines.append(f"- Author: {cursor.artist}")
    lines.extend(["", "Frames:"])
    for index, frame in enumerate(cursor.frames[:32]):
        kind = "cursor" if frame[2:4] == b"\x02\x00" else "icon"
        hotspot = _cursor_hotspot(frame)
        size = ""
        if len(frame) >= 8:
            frame_width, frame_height = frame[6] or 256, frame[7] or 256
            size = f"{frame_width} x {frame_height}, "
        hotspot_text = f", hotspot {hotspot[0]},{hotspot[1]}" if hotspot else ""
        lines.append(f"  [{index}] {kind}, {size}{len(frame):,} bytes{hotspot_text}")
    return lines


@dataclass(frozen=True)
class UiResourcePreview:
    bundle: _StructuredBinaryPreviewBundle
    image_path: str = ""


def build_ui_resource_preview(
    data: bytes,
    virtual_path: str,
    *,
    extension: str,
    render_image: bool = True,
) -> UiResourcePreview:
    """Describe a font or animated cursor, with a rendered PNG when Pillow can draw it.

    Raises `UiResourceError` when the bytes are not a readable font or cursor.
    A rendering failure keeps the text description and says so.
    """

    normalized = str(extension or "").lower()
    detail: list[str] = []
    image_path = ""
    if normalized in FONT_EXTENSIONS:
        info = read_font_info(data)
        lines = [f"Font preview for {virtual_path}", ""]
        lines.extend(describe_font(info))
        label = "Font"
        if render_image:
            try:
                target = _cache_png_path("font", data, virtual_path)
                image_path = str(_render_cached(target, lambda path: render_font_specimen(data, info, path)))
                detail.append("The specimen shows only sample lines whose characters the font maps.")
            except Exception as exc:  # noqa: BLE001 - the text description stands on its own
                detail.append(f"The font specimen could not be rendered: {exc}")
    elif normalized in ANIMATED_CURSOR_EXTENSIONS:
        cursor = read_animated_cursor(data)
        lines = [f"Animated cursor preview for {virtual_path}", ""]
        lines.extend(describe_animated_cursor(cursor))
        label = "Animated Cursor"
        if render_image:
            try:
                target = _cache_png_path("cursor", data, virtual_path)
                image_path = str(_render_cached(target, lambda path: render_cursor_strip(cursor, path)))
                detail.append("Frames are shown enlarged three times on a checkerboard, in file order.")
            except Exception as exc:  # noqa: BLE001
                detail.append(f"The cursor frames could not be rendered: {exc}")
    else:
        raise UiResourceError(f"{normalized or 'this file'} is not a font or animated cursor")
    detail.append("This preview is read-only.")
    return UiResourcePreview(
        bundle=_StructuredBinaryPreviewBundle(
            preview_text="\n".join(lines),
            detail_lines=tuple(detail),
            metadata_label=label,
        ),
        image_path=image_path,
    )


__all__ = [
    "ANIMATED_CURSOR_EXTENSIONS",
    "FONT_EXTENSIONS",
    "UI_RESOURCE_EXTENSIONS",
    "UiResourceError",
    "UiResourcePreview",
    "build_ui_resource_preview",
    "read_animated_cursor",
    "read_font_info",
]
