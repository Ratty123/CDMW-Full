from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import (
    ArchiveAssociationResult,
    ArchiveDurableIdentity,
    ArchiveEntryRef,
    ArchiveEntryDto,
    ArchiveEntryRole,
)
from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult, PrepareEntryResult
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_preview_dependencies import (
    ArchivePreviewDependencySet,
    ArchiveRemotePreviewDependencyProvider,
    MAX_ARCHIVE_PREVIEW_DEPENDENCIES,
)
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin


class _CatalogueService(QObject):
    batch_ready = Signal(str, str, object)
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[object, int]] = []
        self.cancelled: list[str] = []

    def find_association_candidates(self, request: object, *, ui_generation: int) -> str:
        self.requests.append((request, ui_generation))
        return f"association-{len(self.requests)}"

    def prepare_entries(self, request: object, *, ui_generation: int) -> str:
        self.requests.append((request, ui_generation))
        return f"prepare-{len(self.requests)}"

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True


def _dto(entry_id: int, path: str) -> ArchiveEntryDto:
    extension = Path(path).suffix.casefold()
    return ArchiveEntryDto(
        "session-a",
        entry_id,
        ArchiveDurableIdentity(path.casefold(), "c:/game/0009/0.pamt", 0, entry_id * 100),
        path,
        "C:/Game/0009/0.pamt",
        "C:/Game/0009/0.paz",
        0,
        entry_id * 100,
        20,
        40,
        0,
        extension,
        "0009/0.pamt",
        ArchiveEntryRole.MODEL if extension != ".dds" else ArchiveEntryRole.IMAGE,
        "model" if extension != ".dds" else "texture",
        True,
    )


def _prepared(dto: ArchiveEntryDto) -> PrepareEntryResult:
    return PrepareEntryResult(
        ArchiveEntryRef(dto.session_id, dto.entry_id, dto.identity, dto.path),
        f"C:/cache/{dto.entry_id}{dto.extension}",
        dto.original_size,
        f"sha-{dto.entry_id}",
        "prepared test source",
    )


def test_remote_preview_provider_streams_one_bounded_candidate_snapshot() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    ready: list[tuple[int, ArchivePreviewDependencySet]] = []
    provider.ready.connect(lambda request_id, payload: ready.append((request_id, payload)))
    selected = _dto(7, "character/sword.pac")

    assert provider.request(selected, ui_request_id=41)
    request, generation = service.requests[0]
    assert request.session_id == "session-a"
    assert request.entry_id == 7
    assert request.limit == MAX_ARCHIVE_PREVIEW_DEPENDENCIES
    assert request.purpose.value == "preview"
    assert generation == 41

    first = _dto(8, "character/sword.pac_xml")
    second = _dto(9, "texture/sword_d.dds")
    service.batch_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (first,), 2, False),
    )
    service.batch_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (first, second), 2, False),
    )
    service.result_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (), 2, False),
    )
    assert service.requests[1][0].entry_ids == (7, 8, 9)
    service.batch_ready.emit(
        "prepare-2",
        "prepare_entry",
        PrepareEntriesResult("session-a", (_prepared(selected), _prepared(first)), 3, 3, 120),
    )
    service.batch_ready.emit(
        "prepare-2",
        "prepare_entry",
        PrepareEntriesResult("session-a", (_prepared(second),), 3, 3, 120),
    )
    service.result_ready.emit(
        "prepare-2",
        "prepare_entry",
        PrepareEntriesResult("session-a", (), 3, 3, 120),
    )

    assert len(ready) == 1
    request_id, snapshot = ready[0]
    assert request_id == 41
    assert [entry.path for entry in snapshot.entries] == [
        "character/sword.pac",
        "character/sword.pac_xml",
        "texture/sword_d.dds",
    ]
    assert snapshot.entries_by_normalized_path["character/sword.pac_xml"][0].offset == 800
    assert snapshot.entries_by_basename["sword_d.dds"][0].offset == 900
    assert snapshot.entries[0].prepared_path == Path("C:/cache/7.pac")
    assert snapshot.entries[0].prepared_sha256 == "sha-7"
    assert all(entry.prepared_path is not None for entry in snapshot.entries)
    assert not snapshot.truncated
    assert provider.snapshot_for(41, 7) is snapshot
    assert provider.snapshot_for(42, 7) is None


def test_remote_preview_provider_cancels_and_ignores_obsolete_requests() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    ready: list[int] = []
    provider.ready.connect(lambda request_id, _payload: ready.append(request_id))

    assert provider.request(_dto(7, "character/old.pac"), ui_request_id=1)
    assert provider.request(_dto(8, "character/new.pac"), ui_request_id=2)
    assert service.cancelled == ["association-1"]

    service.result_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (), 0, False),
    )
    service.result_ready.emit(
        "association-2",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 8, (), 0, False),
    )
    service.batch_ready.emit(
        "prepare-3",
        "prepare_entry",
        PrepareEntriesResult(
            "session-a",
            (_prepared(_dto(8, "character/new.pac")),),
            1,
            1,
            40,
        ),
    )
    service.result_ready.emit(
        "prepare-3",
        "prepare_entry",
        PrepareEntriesResult("session-a", (), 1, 1, 40),
    )

    assert ready == [2]
    assert provider.snapshot_for(2, 8) is not None


class _PreviewBridge:
    displays_v2 = True

    def __init__(self, snapshot: ArchivePreviewDependencySet | None) -> None:
        self.snapshot = snapshot
        self.requested: list[tuple[int, ArchiveEntry]] = []

    def preview_dependencies_for(
        self,
        _request_id: int,
        _entry: ArchiveEntry,
    ) -> ArchivePreviewDependencySet | None:
        return self.snapshot

    def preview_dependencies_pending_for(self, _request_id: int) -> bool:
        return False

    def request_preview_dependencies(self, request_id: int, entry: ArchiveEntry) -> bool:
        self.requested.append((request_id, entry))
        return True


class _PreviewHarness(ArchivePreviewWorkerMixin):
    def __init__(self, snapshot: ArchivePreviewDependencySet | None) -> None:
        self.archive_remote_bridge = _PreviewBridge(snapshot)
        selected = _entry("character/sword.pac", 700)
        self.scheduled_archive_preview_request = (5, selected, False, False)
        self.archive_preview_request_id = 5
        self.archive_preview_thread = None
        self.archive_preview_worker = None
        self.pending_archive_preview_request = None
        self.archive_sidecar_generation = 0
        self.archive_preview_cache_keys: dict[int, str] = {}
        self.archive_preview_cache: dict[str, object] = {}
        self.started: dict[str, object] | None = None
        self.detail = ""
        self.status = ""

    @property
    def archive_entries_by_normalized_path(self) -> object:
        raise AssertionError("v2 preview read the global path index")

    @property
    def archive_entries_by_basename(self) -> object:
        raise AssertionError("v2 preview read the global basename index")

    @property
    def archive_sidecar_entries_by_texture_path(self) -> object:
        raise AssertionError("v2 preview read the global sidecar path index")

    @property
    def archive_sidecar_entries_by_texture_basename(self) -> object:
        raise AssertionError("v2 preview read the global sidecar basename index")

    def _mesh_replacement_builder_active(self) -> bool:
        return False

    def _archive_basic_index_missing_for_lookup(self) -> bool:
        return False

    def _collect_archive_preview_loose_roots(self) -> list[Path]:
        return []

    def _archive_preview_cache_key(self, *_args: object, quality_tier: str, **_kwargs: object) -> str:
        return f"quality:{quality_tier}"

    def _find_archive_preview_companion_entry(self, _entry: object, **_kwargs: object) -> None:
        return None

    def _current_archive_performance_settings(self) -> object:
        return SimpleNamespace(quick_then_full_preview=False)

    def _show_archive_preview_loading_state(self, _entry: object) -> None:
        return None

    def _set_archive_preview_base_detail_text(self, text: str, **_kwargs: object) -> None:
        self.detail = text

    def set_status_message(self, text: str, **_kwargs: object) -> None:
        self.status = text

    def _start_archive_preview_worker(self, *_args: object, **kwargs: object) -> None:
        self.started = kwargs


def _entry(path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0.pamt"), Path("0.paz"), offset, 20, 40, 0, 0)


def test_v2_preview_flush_uses_only_remote_dependency_maps() -> None:
    snapshot = ArchivePreviewDependencySet.from_dtos(
        _dto(7, "character/sword.pac"),
        (_dto(8, "character/sword.pac_xml"),),
        total_candidates=1,
        truncated=False,
        prepared={
            7: _prepared(_dto(7, "character/sword.pac")),
            8: _prepared(_dto(8, "character/sword.pac_xml")),
        },
    )
    harness = _PreviewHarness(snapshot)

    harness._flush_scheduled_archive_preview_request()

    assert harness.started is not None
    assert harness.started["texture_entries_by_normalized_path"] is snapshot.entries_by_normalized_path
    assert harness.started["texture_entries_by_basename"] is snapshot.entries_by_basename
    assert harness.started["sidecar_entries_by_texture_path"] == {}
    assert harness.started["sidecar_entries_by_texture_basename"] == {}


def test_v2_preview_flush_waits_for_remote_dependencies_without_starting_worker() -> None:
    harness = _PreviewHarness(None)

    harness._flush_scheduled_archive_preview_request()

    assert harness.started is None
    assert len(harness.archive_remote_bridge.requested) == 1
    assert harness.archive_remote_bridge.requested[0][0] == 5
    assert harness.detail == "Resolving bounded archive preview dependencies..."
