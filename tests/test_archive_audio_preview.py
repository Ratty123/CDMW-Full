"""Playback and export must pass usable cache paths to the bundled decoder."""
from __future__ import annotations

import io
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
