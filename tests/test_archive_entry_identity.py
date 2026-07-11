from __future__ import annotations

from pathlib import Path

import pytest

from cdmw.core.archive_filtering import archive_entry_identity_key as compatibility_identity_key
from cdmw.domain.archives.filters import archive_entry_identity_key
from cdmw.models import ArchiveEntry, ArchiveEntryIdentity


def _entry(*, path: str, pamt: str, paz_index: int, offset: int) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path(pamt),
        paz_file=Path(pamt).with_name(f"{paz_index}.paz"),
        offset=offset,
        comp_size=8,
        orig_size=8,
        flags=0,
        paz_index=paz_index,
    )


def test_archive_entry_identity_is_normalized_immutable_and_tuple_compatible() -> None:
    entry = _entry(
        path=r"/Character\Model/Body.PAC",
        pamt=r"C:\Games\Crimson Desert\0009\0.PAMT",
        paz_index=33,
        offset=4096,
    )

    identity = archive_entry_identity_key(entry)

    assert identity == ArchiveEntryIdentity(
        "character/model/body.pac",
        "c:/games/crimson desert/0009/0.pamt",
        33,
        4096,
    )
    assert tuple(identity) == (
        "character/model/body.pac",
        "c:/games/crimson desert/0009/0.pamt",
        33,
        4096,
    )
    with pytest.raises(AttributeError):
        identity.entry_offset = 1  # type: ignore[misc]

    assert compatibility_identity_key is archive_entry_identity_key


def test_archive_entry_identity_distinguishes_paz_and_offset_collisions() -> None:
    base = _entry(path="character/model/body.pac", pamt="0009/0.pamt", paz_index=0, offset=10)
    other_paz = _entry(path="character/model/body.pac", pamt="0009/0.pamt", paz_index=1, offset=10)
    other_offset = _entry(path="character/model/body.pac", pamt="0009/0.pamt", paz_index=0, offset=11)

    assert base.identity != other_paz.identity
    assert base.identity != other_offset.identity
