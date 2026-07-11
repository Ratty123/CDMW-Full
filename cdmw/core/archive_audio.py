"""Archive audio export and patch payload helpers."""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.constants import APP_NAME
from cdmw.core.common import hidden_subprocess_kwargs
from cdmw.models import ArchiveEntry


def _ffmpeg_candidates() -> List[Path]:
    candidates: List[Path] = []
    env_path = shutil.which("ffmpeg")
    if env_path:
        candidates.append(Path(env_path))
    runtime_roots = [Path.cwd()]
    meipass = getattr(__import__("sys"), "_MEIPASS", "")
    if meipass:
        runtime_roots.append(Path(meipass))
    runtime_roots.append(Path(__file__).resolve().parents[2])
    for root in runtime_roots:
        for relative in ("ffmpeg/ffmpeg.exe", ".tools/ffmpeg/ffmpeg.exe", "ffmpeg.exe"):
            path = root / relative
            if path.is_file():
                candidates.append(path)
    seen: set[str] = set()
    unique: List[Path] = []
    for candidate in candidates:
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _run_hidden_process(command: Sequence[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    popen_kwargs: Dict[str, object] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
    }
    popen_kwargs.update(hidden_subprocess_kwargs())
    return subprocess.run(list(command), **popen_kwargs)


def _convert_audio_to_wav(source_path: Path, output_path: Path) -> Path:
    if source_path.suffix.lower() == ".wav":
        shutil.copy2(source_path, output_path)
        return output_path

    ffmpeg_path = next(iter(_ffmpeg_candidates()), None)
    if ffmpeg_path is None:
        raise ValueError("ffmpeg.exe is required to convert this audio stream to WAV.")
    result = _run_hidden_process(
        [str(ffmpeg_path), "-y", "-i", str(source_path), "-ar", "48000", "-ac", "1", "-sample_fmt", "s16", str(output_path)],
        timeout=180,
    )
    if result.returncode != 0 or not output_path.is_file():
        raise ValueError(result.stderr.strip() or "ffmpeg could not convert the selected audio stream.")
    return output_path


def _decode_with_vgmstream(source_path: Path, output_path: Path) -> Path:
    from cdmw.core.archive_media_preview import _resolve_vgmstream_cli_path

    cli_path = _resolve_vgmstream_cli_path()
    if cli_path is None:
        raise ValueError("Bundled vgmstream decoder is not available in this build.")
    result = _run_hidden_process([str(cli_path), "-o", str(output_path), str(source_path)], timeout=180)
    if result.returncode != 0 or not output_path.is_file():
        raise ValueError(result.stderr.strip() or "vgmstream-cli could not decode this Wwise stream.")
    return output_path


def export_archive_audio_as_wav(entry: ArchiveEntry, output_path: Path) -> Path:
    from cdmw.core.archive_media_preview import ensure_archive_preview_source

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_path, _note = ensure_archive_preview_source(entry)
    extension = entry.extension.lower()
    if extension in {".wem", ".bnk"}:
        return _decode_with_vgmstream(source_path, output_path)
    return _convert_audio_to_wav(source_path, output_path)


@dataclass(slots=True, frozen=True)
class _WavFormatInfo:
    audio_format: int
    channels: int
    sample_rate: int
    bits_per_sample: int


def _iter_riff_chunks(data: bytes, *, max_chunks: int = 64) -> List[Tuple[bytes, int, int]]:
    chunks: List[Tuple[bytes, int, int]] = []
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return chunks
    offset = 12
    while offset + 8 <= len(data) and len(chunks) < max_chunks:
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        data_offset = offset + 8
        if data_offset > len(data):
            break
        chunks.append((chunk_id, chunk_size, data_offset))
        next_offset = data_offset + chunk_size
        if next_offset <= offset:
            break
        offset = next_offset + (chunk_size % 2)
    return chunks


def _read_wav_format_info_from_bytes(data: bytes) -> Optional[_WavFormatInfo]:
    for chunk_id, chunk_size, chunk_offset in _iter_riff_chunks(data):
        if chunk_id != b"fmt " or chunk_size < 16 or chunk_offset + 16 > len(data):
            continue
        try:
            audio_format, channels, sample_rate, _byte_rate, _block_align, bits_per_sample = struct.unpack_from(
                "<HHIIHH",
                data,
                chunk_offset,
            )
        except struct.error:
            return None
        return _WavFormatInfo(
            audio_format=int(audio_format),
            channels=int(channels),
            sample_rate=int(sample_rate),
            bits_per_sample=int(bits_per_sample),
        )
    return None


def _read_wav_format_info(audio_path: Path, *, header_limit: int = 262_144) -> Optional[_WavFormatInfo]:
    try:
        with audio_path.open("rb") as handle:
            header = handle.read(max(64, int(header_limit)))
    except OSError:
        return None
    return _read_wav_format_info_from_bytes(header)


def _normalize_audio_input(audio_path: Path, *, sample_rate: int, channels: int) -> Path:
    if audio_path.suffix.lower() == ".wav":
        wav_info = _read_wav_format_info(audio_path)
        if (
            wav_info is not None
            and wav_info.audio_format == 1
            and wav_info.sample_rate == int(sample_rate)
            and wav_info.channels == int(channels)
            and wav_info.bits_per_sample == 16
        ):
            return audio_path
    temp_root = Path(tempfile.gettempdir()) / APP_NAME / "audio_patch"
    temp_root.mkdir(parents=True, exist_ok=True)
    output_path = temp_root / f"{audio_path.stem}_{sample_rate}hz_{channels}ch.wav"
    ffmpeg_path = next(iter(_ffmpeg_candidates()), None)
    if ffmpeg_path is None:
        raise ValueError("ffmpeg.exe is required to normalize replacement audio for patching.")
    result = _run_hidden_process(
        [str(ffmpeg_path), "-y", "-i", str(audio_path), "-ar", str(sample_rate), "-ac", str(channels), "-sample_fmt", "s16", str(output_path)],
        timeout=180,
    )
    if result.returncode != 0 or not output_path.is_file():
        raise ValueError(result.stderr.strip() or "ffmpeg could not normalize the selected replacement audio.")
    return output_path


def _build_pcm_wem(wav_data: bytes, sample_rate: int, channels: int) -> bytes:
    pcm_data = b""
    if wav_data[:4] == b"RIFF" and wav_data[8:12] == b"WAVE":
        cursor = 12
        while cursor + 8 <= len(wav_data):
            chunk_id = wav_data[cursor : cursor + 4]
            chunk_size = struct.unpack_from("<I", wav_data, cursor + 4)[0]
            if chunk_id == b"data":
                pcm_data = wav_data[cursor + 8 : cursor + 8 + chunk_size]
                break
            cursor += 8 + chunk_size
    else:
        pcm_data = wav_data

    if not pcm_data:
        return wav_data

    bits_per_sample = 16
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    fmt_chunk = struct.pack(
        "<4sIHHIIHH",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    )
    data_chunk = b"data" + struct.pack("<I", len(pcm_data)) + pcm_data
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + fmt_chunk + data_chunk


def build_archive_audio_patch_payload(entry: ArchiveEntry, replacement_audio_path: Path) -> bytes:
    from cdmw.core.archive_extraction import read_archive_entry_data

    normalized_path = replacement_audio_path.expanduser().resolve()
    if not normalized_path.is_file():
        raise FileNotFoundError(f"Audio replacement file was not found: {normalized_path}")

    if entry.extension == ".wav":
        return normalized_path.read_bytes()

    if entry.extension != ".wem":
        raise ValueError(f"Archive audio patching currently supports .wav and .wem targets only, not {entry.extension}.")

    original_data, _decompressed, _note = read_archive_entry_data(entry)
    sample_rate = 48000
    channels = 1
    original_wav_info = _read_wav_format_info_from_bytes(original_data)
    if original_wav_info is not None:
        channels = max(1, int(original_wav_info.channels))
        sample_rate = max(1, int(original_wav_info.sample_rate))
    normalized_wav = _normalize_audio_input(normalized_path, sample_rate=sample_rate, channels=channels)
    return _build_pcm_wem(normalized_wav.read_bytes(), sample_rate, channels)


__all__ = [
    "_WavFormatInfo",
    "_build_pcm_wem",
    "_convert_audio_to_wav",
    "_decode_with_vgmstream",
    "_ffmpeg_candidates",
    "_iter_riff_chunks",
    "_normalize_audio_input",
    "_read_wav_format_info",
    "_read_wav_format_info_from_bytes",
    "_run_hidden_process",
    "build_archive_audio_patch_payload",
    "export_archive_audio_as_wav",
]
