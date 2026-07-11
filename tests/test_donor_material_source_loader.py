from __future__ import annotations

import threading
from pathlib import Path

import pytest

from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.ui.archive_browser import static_replacement_donor_material_loader as loader
from tests.static_replacement_source_support import (
    static_replacement_callback_family_source,
)


ROOT = Path(__file__).resolve().parents[1]


def _entry(path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(path, Path("index.pamt"), Path("0.paz"), offset, 4, 4, 0, 0)


def test_donor_material_source_loader_reads_sidecars_and_uses_profile_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    donor = _entry("character/model/donor.pac", 1)
    sidecar = _entry("character/model/donor.pac_xml", 2)
    stop_event = threading.Event()
    seen_stop_events: list[threading.Event | None] = []

    monkeypatch.setattr(
        loader,
        "_extract_archive_model_sidecar_texture_references",
        lambda *_args, **_kwargs: ((), (), {}, {}),
    )

    def fake_read(_entry: ArchiveEntry, *, stop_event: threading.Event | None = None):
        seen_stop_events.append(stop_event)
        return b"<material />", False, ""

    monkeypatch.setattr(loader, "read_archive_entry_data", fake_read)
    monkeypatch.setattr(loader, "donor_bindings_from_sidecar_profiles", lambda _texts: ("binding",))

    result = loader.load_donor_material_source(
        donor,
        (sidecar,),
        {sidecar.basename.lower(): (sidecar,)},
        stop_event=stop_event,
    )

    assert result.bindings == ("binding",)
    assert result.bindings_from_profile is True
    assert dict(result.sidecar_texts) == {sidecar.path: "<material />"}
    assert seen_stop_events == [stop_event]


def test_donor_material_source_loader_honours_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    donor = _entry("character/model/donor.pac", 1)
    sidecar = _entry("character/model/donor.pac_xml", 2)
    stop_event = threading.Event()
    stop_event.set()
    monkeypatch.setattr(
        loader,
        "_extract_archive_model_sidecar_texture_references",
        lambda *_args, **_kwargs: ((), (), {}, {}),
    )

    with pytest.raises(RunCancelled):
        loader.load_donor_material_source(
            donor,
            (sidecar,),
            {sidecar.basename.lower(): (sidecar,)},
            stop_event=stop_event,
        )


def test_donor_picker_dispatches_archive_reads_to_cancellable_worker() -> None:
    source = static_replacement_callback_family_source(ROOT, "texture")
    start = source.index("def _open_original_material_source_picker")
    body = source[start : source.index("def _handle_donor_material_source_error", start)]

    assert "_run_utility_task(" in body
    assert "task_accepts_cancel=True" in body
    assert "read_archive_entry_data(" not in body
    assert "QApplication.processEvents()" not in body
    assert "QProgressDialog(" not in body
