from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin


def _entry() -> ArchiveEntry:
    return ArchiveEntry(
        path="character/model/weapon/test_sword.pac",
        pamt_path=Path("C:/game/0009/0.pamt"),
        paz_file=Path("C:/game/0009/0.paz"),
        offset=12,
        comp_size=34,
        orig_size=56,
        flags=0,
        paz_index=0,
    )


class _ContextLaunchHarness(ArchiveBrowserActionMixin):
    def __init__(self) -> None:
        self._shutting_down = False
        self.launched: list[ArchiveEntry] = []

    def _launch_archive_mesh_editor_for_entry(self, entry: ArchiveEntry) -> None:
        self.launched.append(entry)


def test_mesh_editor_context_launch_is_queued_with_an_immutable_entry_snapshot() -> None:
    harness = _ContextLaunchHarness()
    source = _entry()
    callbacks: list[object] = []

    with patch(
        "cdmw.ui.archive_browser.actions.QTimer.singleShot",
        side_effect=lambda _delay, callback: callbacks.append(callback),
    ):
        harness._queue_archive_mesh_editor_context_launch(source)

    assert harness.launched == []
    assert len(callbacks) == 1
    callback = callbacks.pop()
    assert callable(callback)
    callback()
    assert len(harness.launched) == 1
    assert harness.launched[0] == source
    assert harness.launched[0] is not source


def test_queued_mesh_editor_context_launch_is_dropped_during_shutdown() -> None:
    harness = _ContextLaunchHarness()
    callbacks: list[object] = []

    with patch(
        "cdmw.ui.archive_browser.actions.QTimer.singleShot",
        side_effect=lambda _delay, callback: callbacks.append(callback),
    ):
        harness._queue_archive_mesh_editor_context_launch(_entry())

    harness._shutting_down = True
    callback = callbacks.pop()
    assert callable(callback)
    callback()
    assert harness.launched == []
