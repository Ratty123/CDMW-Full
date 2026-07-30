"""Builds the preview for a Wwise sound bank, including playing what it embeds.

A bank is one archive entry that holds many sounds, so its preview is not the
single-stream shape the other audio formats use: the reader picks a sound and
that one is decoded. Keeping it here rather than inline in the preview result
builder keeps the branch readable and the builder from growing another screen.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from cdmw.core.archive_wwise_bank import read_embedded_media
from cdmw.core.common import RunCancelled
from cdmw.models import ArchiveEntry, ArchivePreviewTrack


def build_sound_bank_tracks(data: bytes) -> Tuple[ArchivePreviewTrack, ...]:
    """The sounds a bank embeds, as preview rows labelled by Wwise source id."""

    return tuple(
        ArchivePreviewTrack(index=media.ordinal, name=str(media.source_id), size=media.size)
        for media in read_embedded_media(data)
    )


def select_sound_bank_track(tracks: Sequence[ArchivePreviewTrack], requested_index: int) -> int:
    """Clamps a requested sound to one the bank actually has.

    A request can outlive the entry it was made for, so an index this bank does
    not have falls back to the first sound rather than failing the preview.
    """

    try:
        requested = int(requested_index)
    except (TypeError, ValueError):
        return 1
    return requested if 1 <= requested <= len(tracks) else 1


def decode_sound_bank_track(
    entry: ArchiveEntry,
    selected_index: int,
    *,
    ensure_preview_source: Callable[..., Tuple[Path, str]],
    ensure_media_source: Callable[..., Tuple[Path, str]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Optional[str], str]:
    """Decodes one embedded sound to a playable WAV.

    Returns the WAV path and a note, or `None` and the reason it could not be
    decoded. A codec the decoder cannot read is a property of the one sound, so
    the caller keeps the bank's list and the reader can move to another sound
    instead of losing the whole preview.
    """

    try:
        source_path, _source_note = ensure_preview_source(entry, stop_event=stop_event)
        media_source, playback_note = ensure_media_source(
            source_path,
            ".bnk",
            subsong=selected_index,
            stop_event=stop_event,
        )
    except RunCancelled:
        raise
    except Exception as error:  # noqa: BLE001 - surfaced to the reader as a note
        return None, f"Sound {selected_index:,} could not be decoded: {error}"
    if media_source is None or Path(media_source).suffix.lower() != ".wav":
        return None, playback_note or f"Sound {selected_index:,} produced no playable audio."
    return str(media_source), playback_note


def sound_bank_metadata_summary(
    metadata_summary: str,
    tracks: Sequence[ArchivePreviewTrack],
    selected_index: int,
) -> str:
    selected = tracks[selected_index - 1]
    return (
        f"{metadata_summary} | Wwise SoundBank | "
        f"Sound {selected_index:,} of {len(tracks):,} (source id {selected.name})"
    )


def sound_bank_detail_parts(note_flags: Sequence[str], bank_detail_text: str) -> List[str]:
    flags = set(note_flags or ())
    return [
        (
            "Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes."
            if "PartialRaw" in flags
            else ""
        ),
        ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in flags else ""),
        bank_detail_text,
    ]


__all__ = [
    "build_sound_bank_tracks",
    "decode_sound_bank_track",
    "select_sound_bank_track",
    "sound_bank_detail_parts",
    "sound_bank_metadata_summary",
]
