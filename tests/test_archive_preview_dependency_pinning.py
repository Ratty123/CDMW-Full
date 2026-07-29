"""An armed in-game swap target must survive the browsing that picks its source.

Prepared dependency snapshots live in a four-slot LRU. Choosing a swap source means
previewing other files, so the target was routinely evicted between arming and firing
and the swap stopped with a message that rendered on a different tab.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_preview_dependencies import (
    MAX_ARCHIVE_PREVIEW_SNAPSHOTS,
    ArchivePreviewDependencySet,
    ArchiveRemotePreviewDependencyProvider,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Service:
    """The provider only connects to these four signals in __init__."""

    class _Sig:
        def connect(self, _slot) -> None:
            return None

    batch_ready = _Sig()
    result_ready = _Sig()
    request_failed = _Sig()
    request_cancelled = _Sig()


def _entry(path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0.pamt"), Path("0.paz"), offset, 8, 8, 0, 0)


def _snapshot(entry: ArchiveEntry) -> ArchivePreviewDependencySet:
    # selected_entry is a property over entries[0], not a field.
    return ArchivePreviewDependencySet(
        session_id="test-session",
        entry_id=entry.offset,
        entries=(entry,),
        entries_by_normalized_path={entry.path.casefold(): (entry,)},
        entries_by_basename={entry.basename.casefold(): (entry,)},
        total_candidates=1,
        truncated=False,
    )


def _provider() -> ArchiveRemotePreviewDependencyProvider:
    return ArchiveRemotePreviewDependencyProvider(_Service())


_WEAPONS = "character/model/1_pc/1_phm/weapon/1_onehandweapon"


def test_unpinned_target_is_evicted_by_browsing() -> None:
    """The pre-fix behaviour, kept as the contrast the pin exists to change."""

    _app()
    provider = _provider()
    target = _entry(f"{_WEAPONS}/cd_phm_01_sword_0070.pac", 70)
    provider._remember_snapshot(_snapshot(target))
    for index in range(MAX_ARCHIVE_PREVIEW_SNAPSHOTS):
        provider._remember_snapshot(_snapshot(_entry(f"{_WEAPONS}/other_{index}.pac", 900 + index)))

    assert provider.snapshot_for_entry(target) is None


def test_pinned_target_survives_the_browsing_that_picks_a_source() -> None:
    """Reproduces the reported sequence: arm 0070, browse 0072/0073/0074, then fire."""

    _app()
    provider = _provider()
    target = _entry(f"{_WEAPONS}/cd_phm_01_sword_0070.pac", 70)
    provider._remember_snapshot(_snapshot(target))
    provider.pin_entry(target)

    for path, offset in (
        (f"{_WEAPONS}/cd_phm_01_sword_0072.pac", 72),
        (f"{_WEAPONS}/cd_phm_01_sword_0073_00_01_in.pac", 73),
        (f"{_WEAPONS}/cd_phm_01_sword_0074.pac", 74),
        (f"{_WEAPONS}/cd_phm_01_sword_0075.pac", 75),
        (f"{_WEAPONS}/cd_phm_01_sword_0076.pac", 76),
    ):
        provider._remember_snapshot(_snapshot(_entry(path, offset)))

    held = provider.snapshot_for_entry(target)
    assert held is not None, "the armed swap target was evicted while its source was chosen"
    assert held.selected_entry.identity == target.identity
    assert len(provider._snapshots_by_identity) <= MAX_ARCHIVE_PREVIEW_SNAPSHOTS


def test_releasing_the_pin_restores_normal_eviction() -> None:
    _app()
    provider = _provider()
    target = _entry(f"{_WEAPONS}/cd_phm_01_sword_0070.pac", 70)
    provider._remember_snapshot(_snapshot(target))
    provider.pin_entry(target)
    provider.pin_entry(None)

    for index in range(MAX_ARCHIVE_PREVIEW_SNAPSHOTS):
        provider._remember_snapshot(_snapshot(_entry(f"{_WEAPONS}/other_{index}.pac", 900 + index)))

    assert provider.snapshot_for_entry(target) is None


def test_pinning_a_target_whose_snapshot_has_not_landed_yet_still_protects_it() -> None:
    """Arming can beat the async preparation, so the pin has to apply retroactively."""

    _app()
    provider = _provider()
    target = _entry(f"{_WEAPONS}/cd_phm_01_sword_0070.pac", 70)

    assert provider.pin_entry(target) is False, "nothing is prepared yet"

    # The target's own preparation lands after arming, then browsing continues.
    provider._remember_snapshot(_snapshot(target))
    for index in range(MAX_ARCHIVE_PREVIEW_SNAPSHOTS + 2):
        provider._remember_snapshot(_snapshot(_entry(f"{_WEAPONS}/other_{index}.pac", 900 + index)))

    assert provider.snapshot_for_entry(target) is not None


def test_a_scope_change_keeps_the_pinned_target() -> None:
    """apply_entry_id_scope cancels with clear_snapshot=True while a swap is armed."""

    _app()
    provider = _provider()
    target = _entry(f"{_WEAPONS}/cd_phm_01_sword_0070.pac", 70)
    provider._remember_snapshot(_snapshot(target))
    provider._remember_snapshot(_snapshot(_entry(f"{_WEAPONS}/other.pac", 999)))
    provider.pin_entry(target)

    provider.cancel(clear_snapshot=True)

    assert provider.snapshot_for_entry(target) is not None
    assert len(provider._snapshots_by_identity) == 1
