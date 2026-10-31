"""Wwise `.wem` stream header facts, read without decoding the audio.

The RIFF `fmt ` chunk gives the codec, channels and rate. Wwise packs the
channel count, configuration type and speaker mask into the extensible layout
word, and its Vorbis header (the 0x42-byte `fmt `) stores the total sample
count right after that word. `smpl` holds loop points and `cue `/`LIST adtl`
hold markers. Field offsets follow vgmstream's `meta/wwise.c`; on the shipped
build every sampled stream was Vorbis, and sample count, rate, channels, mask
and loops matched `vgmstream-cli -m` on each sample checked.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

_CODECS = {
    0x0001: "PCM",
    0xFFFE: "PCM",
    0x0002: "IMA ADPCM",
    0x0069: "IMA ADPCM",
    0x3039: "Opus",
    0x3040: "Opus",
    0x3041: "Opus",
    0x8311: "PTADPCM",
    0xFFFF: "Vorbis",
    0xFFFC: "Vorbis",
}
_SPEAKERS = (
    "FL", "FR", "FC", "LFE", "BL", "BR", "FLC", "FRC", "BC", "SL", "SR",
    "TC", "TFL", "TFC", "TFR", "TBL", "TBC", "TBR",
)
_MAX_CHUNKS = 64
_MAX_MARKERS = 16


@dataclass(frozen=True)
class WemMarker:
    position: int
    label: str = ""


@dataclass(frozen=True)
class WemStreamInfo:
    codec: str
    codec_tag: int
    channels: int
    sample_rate: int
    bits_per_sample: int = 0
    speaker_mask: int = 0
    sample_count: int | None = None
    loop: tuple[int, int] | None = None
    markers: tuple[WemMarker, ...] = field(default_factory=tuple)

    @property
    def duration_seconds(self) -> float | None:
        if self.sample_count is None or self.sample_rate <= 0:
            return None
        return self.sample_count / self.sample_rate

    @property
    def speaker_layout(self) -> str:
        return " ".join(name for bit, name in enumerate(_SPEAKERS) if self.speaker_mask & (1 << bit))


def _riff_chunks(data: bytes) -> list[tuple[bytes, int, int]]:
    chunks: list[tuple[bytes, int, int]] = []
    offset = 12
    while offset + 8 <= len(data) and len(chunks) < _MAX_CHUNKS:
        identifier = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        chunks.append((identifier, offset + 8, size))
        offset += 8 + size + (size & 1)
    return chunks


def _markers(data: bytes, chunks: list[tuple[bytes, int, int]]) -> tuple[WemMarker, ...]:
    positions: dict[int, int] = {}
    labels: dict[int, str] = {}
    for identifier, offset, size in chunks:
        end = min(len(data), offset + size)
        if identifier == b"cue " and offset + 4 <= end:
            count = struct.unpack_from("<I", data, offset)[0]
            for index in range(min(count, _MAX_MARKERS, (end - offset - 4) // 24)):
                cue_id, position = struct.unpack_from("<II", data, offset + 4 + index * 24)
                positions[cue_id] = position
        elif identifier == b"LIST" and data[offset:offset + 4] == b"adtl":
            cursor = offset + 4
            while cursor + 12 <= end:
                kind = data[cursor:cursor + 4]
                length = struct.unpack_from("<I", data, cursor + 4)[0]
                if kind == b"labl" and length >= 4 and cursor + 8 + length <= end:
                    cue_id = struct.unpack_from("<I", data, cursor + 8)[0]
                    text = data[cursor + 12:cursor + 8 + length].split(b"\x00", 1)[0]
                    labels[cue_id] = text.decode("utf-8", errors="replace")
                cursor += 8 + length + (length & 1)
    return tuple(WemMarker(position, labels.get(cue_id, "")) for cue_id, position in sorted(positions.items(), key=lambda item: item[1]))


def read_wem_stream_info(data: bytes) -> WemStreamInfo | None:
    """Header facts for a little-endian RIFF Wwise stream, or None."""

    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    chunks = _riff_chunks(data)
    found = {identifier: (offset, size) for identifier, offset, size in reversed(chunks)}
    if b"fmt " not in found:
        return None
    fmt_offset, fmt_size = found[b"fmt "]
    if fmt_size < 16 or fmt_offset + 16 > len(data):
        return None
    tag, channels, rate, _byte_rate, _align, bits = struct.unpack_from("<HHIIHH", data, fmt_offset)
    mask = 0
    if fmt_size >= 0x18 and fmt_offset + 0x18 <= len(data):
        layout = struct.unpack_from("<I", data, fmt_offset + 0x14)[0]
        mask = layout >> 12 if layout & 0xFF == channels else layout
    samples: int | None = None
    if tag in {0xFFFF, 0xFFFC} and fmt_size == 0x42 and fmt_offset + 0x1C <= len(data):
        samples = struct.unpack_from("<I", data, fmt_offset + 0x18)[0]
    elif tag in {0x0001, 0xFFFE} and bits and channels and b"data" in found:
        samples = found[b"data"][1] // (channels * (bits // 8))
    loop: tuple[int, int] | None = None
    if b"smpl" in found:
        smpl_offset, smpl_size = found[b"smpl"]
        if smpl_size >= 0x34 and smpl_offset + 0x34 <= len(data) and struct.unpack_from("<I", data, smpl_offset + 0x1C)[0]:
            start, end = struct.unpack_from("<II", data, smpl_offset + 0x2C)
            loop = (start, end + 1)
    return WemStreamInfo(
        codec=_CODECS.get(tag, f"0x{tag:04X}"),
        codec_tag=tag,
        channels=channels,
        sample_rate=rate,
        bits_per_sample=bits if tag in {0x0001, 0xFFFE} else 0,
        speaker_mask=mask,
        sample_count=samples,
        loop=loop,
        markers=_markers(data, chunks),
    )


def _seconds(samples: int, rate: int) -> str:
    return f"{samples / rate:,.3f} s" if rate > 0 else f"{samples:,} samples"


def wem_stream_summary(info: WemStreamInfo) -> str:
    parts = [f"{info.channels} ch", f"{info.sample_rate:,} Hz", f"Wwise {info.codec}"]
    if info.bits_per_sample:
        parts.append(f"{info.bits_per_sample}-bit")
    if info.duration_seconds is not None:
        parts.append(f"{info.duration_seconds:,.2f} s")
    return " | ".join(parts)


def wem_stream_detail_lines(info: WemStreamInfo) -> list[str]:
    lines = [f"Codec: Wwise {info.codec} (format tag 0x{info.codec_tag:04X})"]
    layout = info.speaker_layout
    lines.append(f"Channels: {info.channels}" + (f" ({layout})" if layout else ""))
    lines.append(f"Sample rate: {info.sample_rate:,} Hz")
    if info.sample_count is not None:
        lines.append(f"Length: {_seconds(info.sample_count, info.sample_rate)} ({info.sample_count:,} samples)")
    if info.loop is not None:
        lines.append(f"Loop: {_seconds(info.loop[0], info.sample_rate)} to {_seconds(info.loop[1], info.sample_rate)}")
    for marker in info.markers:
        lines.append(f"Marker at {_seconds(marker.position, info.sample_rate)}" + (f": {marker.label}" if marker.label else ""))
    if info.codec != "PCM":
        lines.append(
            "Patch Audio To Game writes uncompressed PCM with this stream's channel count and sample rate; "
            f"it does not re-encode Wwise {info.codec}."
        )
    return lines


__all__ = ["WemMarker", "WemStreamInfo", "read_wem_stream_info", "wem_stream_detail_lines", "wem_stream_summary"]
