from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
import math
import struct
import zlib

def _write_checker_png(path: Path, *, width: int = 16, height: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def chunk(name: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + name
            + payload
            + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
        )

    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            if ((x // 4) + (y // 4)) % 2:
                rows.extend((48, 176, 224))
            else:
                rows.extend((232, 72, 56))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk("IHDR".encode("ascii"), struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk("IDAT".encode("ascii"), zlib.compress(bytes(rows), 9))
        + chunk("IEND".encode("ascii"), b"")
    )
    path.write_bytes(png)

def _png_capture_summary(path: Path) -> dict[str, object]:
    try:
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return {"ok": False, "error": "not a PNG"}
        width = 0
        height = 0
        bit_depth = 0
        color_type = -1
        idat_chunks: list[bytes] = []
        offset = 8
        while offset + 12 <= len(data):
            chunk_len = struct.unpack(">I", data[offset : offset + 4])[0]
            chunk_type = data[offset + 4 : offset + 8]
            payload_start = offset + 8
            payload_end = payload_start + chunk_len
            if payload_end + 4 > len(data):
                return {"ok": False, "error": "truncated PNG chunk"}
            payload = data[payload_start:payload_end]
            offset = payload_end + 4
            if chunk_type == b"IHDR":
                width, height, bit_depth, color_type = struct.unpack(">IIBB", payload[:10])
            elif chunk_type == b"IDAT":
                idat_chunks.append(payload)
            elif chunk_type == b"IEND":
                break

        channels_by_type = {0: 1, 2: 3, 6: 4}
        channels = channels_by_type.get(color_type)
        if width <= 0 or height <= 0 or not idat_chunks:
            return {"ok": False, "error": "missing PNG image data", "width": width, "height": height}
        if bit_depth != 8 or channels is None:
            return {
                "ok": False,
                "error": f"unsupported PNG format bit_depth={bit_depth} color_type={color_type}",
                "width": width,
                "height": height,
            }

        raw = zlib.decompress(b"".join(idat_chunks))
        row_bytes = width * channels
        if len(raw) < (row_bytes + 1) * height:
            return {"ok": False, "error": "truncated PNG scanlines", "width": width, "height": height}

        unique_rgb: set[tuple[int, int, int]] = set()
        bright_samples = 0
        sampled_pixels = 0
        sample_stride = max(1, (width * height) // 20000)
        previous = bytearray(row_bytes)
        cursor = 0
        for y in range(height):
            filter_type = raw[cursor]
            cursor += 1
            scanline = bytearray(raw[cursor : cursor + row_bytes])
            cursor += row_bytes
            _png_unfilter_scanline(scanline, previous, channels, filter_type)
            for x in range(width):
                if ((y * width) + x) % sample_stride:
                    continue
                pixel_offset = x * channels
                if channels == 1:
                    rgb = (scanline[pixel_offset], scanline[pixel_offset], scanline[pixel_offset])
                else:
                    rgb = (scanline[pixel_offset], scanline[pixel_offset + 1], scanline[pixel_offset + 2])
                unique_rgb.add(rgb)
                bright_samples += int(sum(rgb) >= 96)
                sampled_pixels += 1
            previous = scanline

        ok = width >= 64 and height >= 64 and len(unique_rgb) >= 2 and bright_samples > 0
        return {
            "ok": ok,
            "width": width,
            "height": height,
            "unique_rgb_count": len(unique_rgb),
            "bright_sample_count": bright_samples,
            "sampled_pixel_count": sampled_pixels,
        }
    except (OSError, ValueError, zlib.error, struct.error) as exc:
        return {"ok": False, "error": str(exc)}

def _write_real_archive_visual_edit_proof(
    before_path: Path,
    after_path: Path,
    output_path: Path,
    *,
    before_center: Sequence[object] | None,
    after_center: Sequence[object] | None,
) -> dict[str, object]:
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageEnhance
    except Exception as exc:
        return {"ok": False, "error": f"Pillow unavailable: {exc}"}
    try:
        with Image.open(before_path) as before_raw, Image.open(after_path) as after_raw:
            before_image = before_raw.convert("RGB")
            after_image = after_raw.convert("RGB")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if before_image.size != after_image.size:
        return {
            "ok": False,
            "error": "capture sizes differ",
            "before_size": list(before_image.size),
            "after_size": list(after_image.size),
        }

    width, height = before_image.size

    def _point(value: Sequence[object] | None, fallback: tuple[float, float]) -> tuple[float, float]:
        try:
            if value is None:
                return fallback
            return (float(value[0]), float(value[1]))  # type: ignore[index]
        except (TypeError, ValueError, OverflowError, IndexError):
            return fallback

    before_point = _point(before_center, (width * 0.5, height * 0.5))
    after_point = _point(after_center, before_point)
    min_x = max(0, int(math.floor(min(before_point[0], after_point[0]) - 180)))
    max_x = min(width, int(math.ceil(max(before_point[0], after_point[0]) + 180)))
    min_y = max(0, int(math.floor(min(before_point[1], after_point[1]) - 140)))
    max_y = min(height, int(math.ceil(max(before_point[1], after_point[1]) + 140)))
    if max_x - min_x < 80 or max_y - min_y < 80:
        min_x, min_y, max_x, max_y = 0, 0, width, height
    crop_box = (min_x, min_y, max_x, max_y)
    before_crop = before_image.crop(crop_box)
    after_crop = after_image.crop(crop_box)
    diff = ImageChops.difference(before_crop, after_crop)
    diff_mask = diff.convert("L").point(lambda value: 255 if value > 24 else 0)
    diff_bbox = diff_mask.getbbox()
    changed_pixels = 0
    if diff_bbox is not None:
        changed_pixels = diff_mask.histogram()[255]

    panel_size = (360, 260)
    before_panel = before_crop.resize(panel_size)
    after_panel = after_crop.resize(panel_size)
    diff_panel = ImageEnhance.Brightness(diff).enhance(5.0).resize(panel_size)
    sheet = Image.new("RGB", (panel_size[0] * 3, panel_size[1] + 28), (15, 18, 22))
    sheet.paste(before_panel, (0, 28))
    sheet.paste(after_panel, (panel_size[0], 28))
    sheet.paste(diff_panel, (panel_size[0] * 2, 28))
    draw = ImageDraw.Draw(sheet)
    labels = ("selected before drag", "after drag", "difference")
    for index, label in enumerate(labels):
        draw.text((index * panel_size[0] + 10, 8), label, fill=(235, 235, 235))
    crop_width = max(1, max_x - min_x)
    crop_height = max(1, max_y - min_y)

    def _mark(point: tuple[float, float], panel_index: int, color: tuple[int, int, int]) -> None:
        x = panel_index * panel_size[0] + int(round(((point[0] - min_x) / crop_width) * panel_size[0]))
        y = 28 + int(round(((point[1] - min_y) / crop_height) * panel_size[1]))
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline=color, width=3)

    _mark(before_point, 0, (0, 220, 255))
    _mark(after_point, 1, (255, 180, 0))
    _mark(before_point, 2, (0, 220, 255))
    _mark(after_point, 2, (255, 180, 0))
    try:
        sheet.save(output_path)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": output_path.is_file() and changed_pixels > 0,
        "path": str(output_path),
        "changed_pixel_count": changed_pixels,
        "diff_bbox": list(diff_bbox) if diff_bbox is not None else None,
        "crop_box": list(crop_box),
        "before_center": [before_point[0], before_point[1]],
        "after_center": [after_point[0], after_point[1]],
    }

def _png_unfilter_scanline(scanline: bytearray, previous: bytearray, channels: int, filter_type: int) -> None:
    for index, value in enumerate(scanline):
        left = scanline[index - channels] if index >= channels else 0
        up = previous[index]
        up_left = previous[index - channels] if index >= channels else 0
        if filter_type == 0:
            continue
        if filter_type == 1:
            scanline[index] = (value + left) & 0xFF
        elif filter_type == 2:
            scanline[index] = (value + up) & 0xFF
        elif filter_type == 3:
            scanline[index] = (value + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            scanline[index] = (value + _png_paeth(left, up, up_left)) & 0xFF
        else:
            raise ValueError(f"unsupported PNG filter: {filter_type}")

def _png_paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    up_left_distance = abs(estimate - up_left)
    if left_distance <= up_distance and left_distance <= up_left_distance:
        return left
    if up_distance <= up_left_distance:
        return up
    return up_left
