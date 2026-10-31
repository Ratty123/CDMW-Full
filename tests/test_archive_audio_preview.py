"""Playback and export must pass usable cache paths to the bundled decoder."""
from __future__ import annotations

import io
import struct
import os
from pathlib import Path
import wave

import pytest

from cdmw.core import archive_media_preview
from cdmw.core.archive_audio import export_archive_audio_as_wav
from cdmw.core.archive_preview_result_builder import build_archive_preview_result
from cdmw.models import ArchiveEntry


@pytest.fixture
def pcm_entry(tmp_path, monkeypatch):
    if archive_media_preview._resolve_vgmstream_cli_path() is None:
        pytest.skip("bundled vgmstream-cli is required")
    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x01" * 480)
    payload = data.getvalue()
    paz = tmp_path / "owned.paz"
    paz.write_bytes(payload)
    return ArchiveEntry("sound/windows/english(us)/dialogue.wem", tmp_path / "owned.pamt",
                        paz, 0, len(payload), len(payload), 0, 0)


@pytest.mark.skipif(os.name != "nt", reason="Windows extended cache path regression")
def test_archive_wem_preview_decodes_prefixed_cache_and_reuses_pcm(pcm_entry):
    result = build_archive_preview_result(pcm_entry)
    assert result.preview_media_kind == "audio", result.detail_text
    path = Path(result.preview_media_path)
    assert path.name == "dialogue.vgmstream.wav", result.detail_text
    with wave.open(str(path), "rb") as audio:
        assert audio.getnframes() == 480
        assert audio.getsampwidth() == 2
    stamp = path.stat().st_mtime_ns
    again = build_archive_preview_result(pcm_entry)
    assert again.preview_media_path == result.preview_media_path
    assert path.stat().st_mtime_ns == stamp


@pytest.mark.skipif(os.name != "nt", reason="Windows extended cache path regression")
def test_archive_wem_wav_export_decodes_prefixed_source(pcm_entry, tmp_path):
    output = export_archive_audio_as_wav(pcm_entry, tmp_path / "export.wav")
    with wave.open(str(output), "rb") as audio:
        assert audio.getnframes() == 480


def riff_chunk(identifier: bytes, payload: bytes) -> bytes:
    return identifier + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) % 2 else b"")


def wwise_vorbis_header(*, channels=2, rate=48000, samples=96000, loop=None, label=b""):
    # 0x42-byte Wwise Vorbis fmt: tag, channels, rate, avg bytes, align/bits zero,
    # extra size, then the packed layout word and the total sample count.
    layout = (0x3 << 12) | (1 << 8) | channels
    fmt = struct.pack("<HHIIHHHHII", 0xFFFF, channels, rate, 16000, 0, 0, 0x30, 0, layout, samples)
    fmt += b"\x00" * (0x42 - len(fmt))
    body = riff_chunk(b"fmt ", fmt) + riff_chunk(b"hash", b"\x00" * 16)
    if loop is not None:
        smpl = struct.pack("<9I", 0, 0, 0, 60, 0, 0, 0, 1, 0) + struct.pack("<6I", 0, 0, loop[0], loop[1] - 1, 0, 0)
        body += riff_chunk(b"smpl", smpl)
    if label:
        body += riff_chunk(b"cue ", struct.pack("<I", 1) + struct.pack("<II4sIII", 1, 0, b"data", 0, 0, 0))
        body += riff_chunk(b"LIST", b"adtl" + riff_chunk(b"labl", struct.pack("<I", 1) + label + b"\x00"))
    body += riff_chunk(b"data", b"\x00" * 32)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


def test_wwise_vorbis_header_reports_codec_length_layout_loop_and_markers():
    from cdmw.core.archive_wwise_stream import read_wem_stream_info, wem_stream_detail_lines, wem_stream_summary

    info = read_wem_stream_info(wwise_vorbis_header(loop=(4800, 96000), label=b"line_0001.wav"))
    assert (info.codec, info.channels, info.sample_rate, info.sample_count) == ("Vorbis", 2, 48000, 96000)
    assert info.speaker_layout == "FL FR" and info.loop == (4800, 96000) and info.bits_per_sample == 0
    assert [(marker.position, marker.label) for marker in info.markers] == [(0, "line_0001.wav")]
    lines = wem_stream_detail_lines(info)
    assert "Length: 2.000 s (96,000 samples)" in lines
    assert "Loop: 0.100 s to 2.000 s" in lines
    assert "Marker at 0.000 s: line_0001.wav" in lines
    assert any("does not re-encode Wwise Vorbis" in line for line in lines)
    assert wem_stream_summary(info) == "2 ch | 48,000 Hz | Wwise Vorbis | 2.00 s"


def test_pcm_wem_length_comes_from_its_data_chunk():
    from cdmw.core.archive_wwise_stream import read_wem_stream_info, wem_stream_detail_lines

    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x01" * 480)
    info = read_wem_stream_info(data.getvalue())
    assert (info.codec, info.bits_per_sample, info.sample_count) == ("PCM", 16, 480)
    assert not any("re-encode" in line for line in wem_stream_detail_lines(info))


@pytest.mark.parametrize("data", [b"", b"RIFX" + b"\x00" * 40, b"RIFF\x10\x00\x00\x00WAVEjunk\x00\x00\x00\x00"])
def test_wem_header_reader_rejects_other_containers(data):
    from cdmw.core.archive_wwise_stream import read_wem_stream_info

    assert read_wem_stream_info(data) is None


def test_wem_details_drop_the_zero_bit_label_for_compressed_streams(tmp_path):
    source = tmp_path / "line_0001.wem"
    data = wwise_vorbis_header(channels=1, rate=44100, samples=44100)
    source.write_bytes(data)
    summary, details = archive_media_preview._build_wem_media_preview_detail_text(source, data, loose=True)
    assert summary.endswith("1 ch | 44,100 Hz | Wwise Vorbis | 1.00 s")
    assert "0-bit" not in summary
    assert "Codec: Wwise Vorbis (format tag 0xFFFF)" in details
