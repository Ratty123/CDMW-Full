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


def _decode_with_vgmstream(source_path: Path, output_path: Path, *, subsong: int = 0) -> Path:
    from cdmw.core.archive_media_preview import _resolve_vgmstream_cli_path, _vgmstream_path_argument

    cli_path = _resolve_vgmstream_cli_path()
    if cli_path is None:
        raise ValueError("Bundled vgmstream decoder is not available in this build.")
    command = [str(cli_path), "-o", _vgmstream_path_argument(output_path)]
    if int(subsong) > 0:
        command += ["-s", str(int(subsong))]
    command.append(_vgmstream_path_argument(source_path))
    result = _run_hidden_process(command, timeout=180)
    if result.returncode != 0 or not output_path.is_file():
        raise ValueError(result.stderr.strip() or "vgmstream-cli could not decode this Wwise stream.")
    return output_path


def export_archive_audio_as_wav(entry: ArchiveEntry, output_path: Path, *, subsong: int = 0) -> Path:
    """Writes one sound as WAV.

    `subsong` selects a sound inside a container that holds several, which is what
    a Wwise sound bank is; zero exports the decoder's default sound.
    """

    from cdmw.core.archive_media_preview import ensure_archive_preview_source

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_path, _note = ensure_archive_preview_source(entry)
    extension = entry.extension.lower()
    if extension in {".wem", ".bnk"}:
        return _decode_with_vgmstream(source_path, output_path, subsong=subsong)
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


def _build_pcm_wem(wav_data: bytes, sample_rate: int, channels: int, *, channel_layout: int | None = None) -> bytes:
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
    if channel_layout is None:
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
    else:
        # Wwise's own 0x18-byte layout: the extensible tag, then the packed channel
        # configuration word its Vorbis streams carry at the same offset.
        fmt_chunk = struct.pack(
            "<4sIHHIIHHHHI",
            b"fmt ",
            0x18,
            0xFFFE,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            6,
            bits_per_sample,
            channel_layout,
        )
    data_chunk = b"data" + struct.pack("<I", len(pcm_data)) + pcm_data
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + fmt_chunk + data_chunk


def _wwise_channel_layout(media: bytes, channels: int) -> int | None:
    """The packed channel configuration a Wwise stream stores at `fmt ` + 0x14."""

    for chunk_id, chunk_size, chunk_offset in _iter_riff_chunks(media):
        if chunk_id == b"fmt " and chunk_size >= 0x18 and chunk_offset + 0x18 <= len(media):
            layout = struct.unpack_from("<I", media, chunk_offset + 0x14)[0]
            return layout if layout & 0xFF == channels else None
    return None


def build_wwise_replacement_media(original_media: bytes, replacement_audio_path: Path) -> bytes:
    """The bytes that replace one Wwise media file.

    A `.wem` the user made with their own Wwise authoring install is taken as it
    is, after checking it is a codec this game's banks play. Any other audio is
    converted to 16-bit PCM with the original's channel count, sample rate and
    speaker layout; CDMW has no Wwise Vorbis encoder.
    """

    from cdmw.core.archive_wwise_bank_edit import codec_plugin_for_media

    normalized_path = replacement_audio_path.expanduser().resolve()
    if not normalized_path.is_file():
        raise FileNotFoundError(f"Audio replacement file was not found: {normalized_path}")
    if normalized_path.suffix.lower() == ".wem":
        media = normalized_path.read_bytes()
        codec_plugin_for_media(media)
        return media
    sample_rate = 48000
    channels = 1
    original_wav_info = _read_wav_format_info_from_bytes(original_media)
    if original_wav_info is not None:
        channels = max(1, int(original_wav_info.channels))
        sample_rate = max(1, int(original_wav_info.sample_rate))
    normalized_wav = _normalize_audio_input(normalized_path, sample_rate=sample_rate, channels=channels)
    layout = _wwise_channel_layout(original_media, channels)
    return _build_pcm_wem(normalized_wav.read_bytes(), sample_rate, channels, channel_layout=layout)


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
    if wwise_media_source_id(entry) is None:
        return _named_wem_replacement(original_data, normalized_path)
    return build_wwise_replacement_media(original_data, normalized_path)


def _named_wem_replacement(original_media: bytes, replacement_path: Path) -> bytes:
    """A named voice line is handed to Wwise by the game, which also names its codec,
    so the replacement must be a Wwise .wem in the original's codec; PCM would be read as Vorbis."""

    from cdmw.core.archive_wwise_bank_edit import media_format_tag

    if replacement_path.suffix.lower() != ".wem":
        raise ValueError(
            "This voice line is chosen by name while the game runs, and the game tells Wwise which codec to decode "
            "it with (Wwise Vorbis), so converted audio would not play. Use a .wem made with your own Wwise install."
        )
    media = replacement_path.read_bytes()
    if media_format_tag(media) != media_format_tag(original_media):
        raise ValueError(
            "This voice line is chosen by name while the game runs and keeps the codec the game asks for; "
            "the replacement .wem uses a different codec. Encode it as Wwise Vorbis."
        )
    return media


#: PCM larger than this many times the media it replaces is called out to the user.
_PCM_SIZE_WARNING_RATIO = 4.0


@dataclass(slots=True, frozen=True)
class WwiseMediaReplacement:
    """Every archive file one media replacement touches, with what changed in each."""

    source_id: int
    payloads: Tuple[Tuple[ArchiveEntry, bytes], ...]
    notes: Tuple[str, ...]


def wwise_media_source_id(entry: ArchiveEntry) -> Optional[int]:
    """The Wwise source id a loose `.wem` carries as its name, if it is numeric."""

    stem = Path(entry.basename).stem
    return int(stem) if entry.extension == ".wem" and stem.isdigit() else None


def build_wwise_media_replacement(
    source_id: int,
    media: bytes,
    *,
    original_media: bytes,
    wem_entries: Sequence[ArchiveEntry],
    bank_entries: Sequence[ArchiveEntry],
    read_entry=None,
    stop_event=None,
    on_log=None,
) -> WwiseMediaReplacement:
    """Replaces one media id everywhere the game reads it.

    The loose `.wem` copies get the new bytes, every bank that embeds the id
    gets its embedded copy (or stream prefix) replaced, and every bank whose
    sources play it gets the new size or prefix size and codec. Any refusal
    refuses the whole replacement, so no partial set of files is produced.
    """

    from cdmw.core.archive_wwise_bank_edit import (
        WwiseBankEditError,
        bank_media_references,
        bank_music_track_users,
        codec_plugin_for_media,
        media_duration_seconds,
        replace_embedded_media,
        retarget_loose_media,
    )
    from cdmw.domain.cancellation import raise_if_cancelled

    if read_entry is None:
        from cdmw.core.archive_extraction import read_archive_entry_data

        def read_entry(entry: ArchiveEntry) -> bytes:
            return read_archive_entry_data(entry)[0]

    log = on_log or (lambda _message: None)
    plugin = codec_plugin_for_media(media)
    payloads: List[Tuple[ArchiveEntry, bytes]] = [(entry, media) for entry in wem_entries]
    notes: List[str] = []
    music_tracks = 0
    needle = struct.pack("<I", int(source_id))
    for index, bank in enumerate(bank_entries):
        if index % 200 == 0:
            raise_if_cancelled(stop_event, "Audio replacement cancelled.")
        data = read_entry(bank)
        if needle not in data:
            continue
        embedded, sounds, undecoded = bank_media_references(data, source_id)
        if undecoded:
            raise WwiseBankEditError(
                f"{bank.path}: {undecoded} object(s) this reader does not decode hold media id {source_id}; "
                "refusing to change that media."
            )
        if not embedded and not sounds:
            continue
        music_tracks += bank_music_track_users(data, source_id)
        try:
            if embedded:
                result = replace_embedded_media(data, source_id, media, original_media=original_media)
            else:
                result = retarget_loose_media(data, source_id, media, original_media=original_media)
        except WwiseBankEditError as error:
            raise WwiseBankEditError(f"{bank.path}: {error}") from error
        payloads.append((bank, result.data))
        log(f"{bank.path}: " + "; ".join(result.changes))
    if len(payloads) == len(wem_entries):
        notes.append(
            f"No bank declares media {source_id}; the replacement is written, but nothing in the shipped banks plays it."
        )
    if music_tracks:
        before, after = media_duration_seconds(original_media), media_duration_seconds(media)
        if before and after and abs(after - before) > max(0.05, 0.01 * before):
            notes.append(
                f"{music_tracks} music track(s) play media {source_id}. Music keeps the original's clip timing "
                f"({before:,.2f} s), so the {after:,.2f} s replacement "
                + ("is cut off at that point." if after > before else "is followed by silence until then.")
            )
    if plugin == 0x00010001:
        ratio = len(media) / max(1, len(original_media))
        notes.append(
            "The replacement is uncompressed PCM, which no shipped bank declares; the banks that play it were switched "
            "to Wwise's built-in PCM codec, which the game plays."
        )
        if ratio >= _PCM_SIZE_WARNING_RATIO:
            notes.append(
                f"PCM is {ratio:,.1f} times the size of the Wwise Vorbis original "
                f"({len(media):,} bytes against {len(original_media):,}); sounds held in memory cost that much more."
            )
    return WwiseMediaReplacement(int(source_id), tuple(payloads), tuple(notes))


def read_sound_bank_editor_model(entry: ArchiveEntry):
    """What the sound bank editor can change in one bank archive entry."""

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_wwise_bank_plan import build_sound_bank_editor_model

    return build_sound_bank_editor_model(read_archive_entry_data(entry)[0])


def apply_sound_bank_edits(
    entry: ArchiveEntry,
    plan,
    archive_entries: Sequence[ArchiveEntry],
    *,
    stop_event=None,
    on_log=None,
) -> Tuple[bytes, Tuple[str, ...]]:
    """Applies a sound bank editor plan to one bank and returns its new bytes and changes.

    Added variations get ids no bank or loose media uses, so every bank in the
    listing is read when the plan adds one.
    """

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_wwise_bank_plan import apply_sound_bank_edit_plan
    from cdmw.core.archive_wwise_bank_variations import bank_ids
    from cdmw.domain.cancellation import raise_if_cancelled

    log = on_log or (lambda _message: None)
    data = read_archive_entry_data(entry)[0]
    taken: set[int] = set()
    loose_by_id: Dict[int, ArchiveEntry] = {}
    for item in archive_entries:
        source_id = wwise_media_source_id(item)
        if source_id is not None:
            taken.add(source_id)
            loose_by_id.setdefault(source_id, item)
    if plan.added_variations:
        banks = active_archive_entries([item for item in archive_entries if item.extension == ".bnk"])
        log(f"Collecting the ids {len(banks):,} banks use, so added sounds get unused ones...")
        for index, bank in enumerate(banks):
            if index % 200 == 0:
                raise_if_cancelled(stop_event, "Sound bank edit cancelled.")
            taken |= bank_ids(read_archive_entry_data(bank)[0])

    def template_media(source_id: int) -> bytes:
        loose = loose_by_id.get(source_id)
        if loose is None:
            raise ValueError(f"No loose {source_id}.wem is in the archive listing.")
        return read_archive_entry_data(loose)[0]

    return apply_sound_bank_edit_plan(
        data,
        plan,
        build_media=build_wwise_replacement_media,
        template_media=template_media,
        taken_ids=sorted(taken),
        on_log=log,
    )


def active_archive_entries(entries: Sequence[ArchiveEntry]) -> List[ArchiveEntry]:
    """One entry per virtual path: the one the game loads when a package or DLC shadows another."""

    from cdmw.domain.archives.filters import active_archive_entry_for_virtual_path

    grouped: Dict[str, List[ArchiveEntry]] = {}
    for item in entries:
        grouped.setdefault(item.path.replace("\\", "/").lower(), []).append(item)
    return [group[0] if len(group) == 1 else active_archive_entry_for_virtual_path(group) for group in grouped.values()]


def list_bank_embedded_media(entry: ArchiveEntry):
    """The sounds a bank archive entry embeds, in preview-track order."""

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_wwise_bank import read_embedded_media

    return read_embedded_media(read_archive_entry_data(entry)[0])


def plan_wwise_media_replacement(
    entry: ArchiveEntry,
    replacement_audio_path: Path,
    source_id: int,
    archive_entries: Sequence[ArchiveEntry],
    *,
    stop_event=None,
    on_log=None,
) -> WwiseMediaReplacement:
    """Plans one media replacement started from a loose `.wem` or from a bank's embedded sound.

    `archive_entries` is the scanned archive listing; the loose copies named
    `<source id>.wem` and every `.bnk` are taken from it.
    """

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_wwise_bank import read_bank_embedded_bytes, read_embedded_media

    wem_name = f"{int(source_id)}.wem"
    wem_entries = active_archive_entries([item for item in archive_entries if item.basename.lower() == wem_name])
    bank_entries = active_archive_entries([item for item in archive_entries if item.extension == ".bnk"])
    if entry.extension == ".bnk" and not any(item.path.lower() == entry.path.lower() for item in bank_entries):
        bank_entries.append(entry)
    data = read_archive_entry_data(entry)[0]
    if entry.extension == ".bnk":
        embedded = next((item for item in read_embedded_media(data) if item.source_id == int(source_id)), None)
        if embedded is None:
            raise ValueError(f"{entry.path} does not embed media {source_id}.")
        # A bank may embed only a stream prefix; the loose file, when there is
        # one, is the complete original that prefixes are measured against.
        original = read_archive_entry_data(wem_entries[0])[0] if wem_entries else read_bank_embedded_bytes(data, embedded)
    else:
        original = data
    media = build_wwise_replacement_media(original, replacement_audio_path)
    if on_log is not None:
        on_log(f"Looking for the banks that play media {source_id} among {len(bank_entries):,} banks...")
    return build_wwise_media_replacement(
        int(source_id),
        media,
        original_media=original,
        wem_entries=wem_entries,
        bank_entries=bank_entries,
        stop_event=stop_event,
        on_log=on_log,
    )


__all__ = [
    "WwiseMediaReplacement",
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
    "active_archive_entries",
    "apply_sound_bank_edits",
    "build_archive_audio_patch_payload",
    "build_wwise_media_replacement",
    "build_wwise_replacement_media",
    "export_archive_audio_as_wav",
    "list_bank_embedded_media",
    "plan_wwise_media_replacement",
    "read_sound_bank_editor_model",
    "wwise_media_source_id",
]
