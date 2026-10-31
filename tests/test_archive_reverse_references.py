from __future__ import annotations

import hashlib
import os
import struct
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject, QTimer, Signal, Qt, QSettings
from PySide6.QtWidgets import QApplication, QPushButton, QLabel, QTreeWidget, QWidget

from cdmw.core.archive_reverse_references import (
    incoming_reference, reference_evidence_group, reference_source_extension_groups, scan_reference_batch,
)
from cdmw.domain.archives.catalogue import ArchiveDurableIdentity, ArchiveEntryDto, ArchiveEntryRef, ArchiveEntryRole, ArchivePage, ArchiveQueryHandle
from cdmw.domain.archives.catalogue_operations import PrepareEntryResult, PrepareEntriesResult
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.services.archive_reference_search import ArchiveReferenceSearchController
from cdmw.ui.archive_browser.asset_family_dialog import ArchiveAssetFamilyDialogMixin
from cdmw.ui.archive_browser.asset_family_panel import ArchiveAssetFamilyPanelMixin
from cdmw.ui.archive_browser.asset_family_references import ArchiveAssetFamilyReferenceMixin
from cdmw.ui.archive_browser.asset_family_layout import ArchiveAssetFamilyLayoutMixin


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def entries_at(tmp_path, payloads):
    entries = []
    paz = tmp_path / "fixture.paz"
    with paz.open("wb") as stream:
        for path, payload in payloads:
            entries.append(ArchiveEntry(path, tmp_path / "0.pamt", paz, stream.tell(), len(payload), len(payload), 0, 0))
            stream.write(payload)
    return entries


def chunk(kind, payload):
    return kind + struct.pack("<I", len(payload)) + payload


def bank(media_id=42, *, version=150, plugin=0x00010001, didx=False):
    header = chunk(b"BKHD", struct.pack("<IIII", version, 2, 0, 0))
    if didx:
        return header + chunk(b"DIDX", struct.pack("<III", media_id, 0, 4)) + chunk(b"DATA", b"test")
    sound = struct.pack("<IIBI", 100, plugin, 2, media_id)
    sound += (struct.pack("<I", 8) if version > 150 else b"") + struct.pack("<IB", 0, 0x80)
    return header + chunk(b"HIRC", struct.pack("<IBI", 1, 2, len(sound)) + sound)


@pytest.mark.parametrize("payload, expected", [
    (b'<Texture path="textures/shared.dds"/>', "explicit_path"),
    (b'\x80\x81\x00TEXTURES\\SHARED.DDS\x00', "explicit_path"),
    ('<Texture path="textures/shared.dds"/>'.encode('utf-16'), "explicit_path"),
    (b'<Texture path="shared.dds"/>', "derived_same_stem"),
    (b'<Texture path="other/shared.dds"/>', None),
    (b'<Texture path="textures/shared.dds_backup"/>', None),
    (b'<Texture path="nottextures/shared.dds"/>', None),
    (b'<Texture path="textures/shared.dds.other"/>', None),
    (b'x' * 100000 + b' textures/shared.dds', "explicit_path"),
    (b'<Texture path="../textures/shared.dds"/>', "explicit_path"),
], ids=["path", "binary", "utf16", "basename", "other-folder", "suffix", "prefix", "compound-suffix", "long-run", "relative"])
def test_paths_and_guesses_are_distinct(tmp_path, payload, expected):
    target, source = entries_at(tmp_path, [("textures/shared.dds", b"DDS "), ("model/material.pac_xml", payload)])
    ref, supported = incoming_reference(target, source, payload)
    assert supported
    assert (ref.relation_confidence if ref else None) == expected
    if expected:
        assert ref.resolved_entry == source
        assert reference_evidence_group(expected) == ("Confirmed references" if expected == "explicit_path" else "Name-based guesses")


@pytest.mark.parametrize("payload, confidence", [(b'"shared.dds"', "derived_same_stem"),
                                               (b'"../shared.dds"', "explicit_path")])
def test_root_asset_still_requires_path_evidence(tmp_path, payload, confidence):
    target, source = entries_at(tmp_path, [("shared.dds", b"DDS "), ("model/material.xml", payload)])
    reference, _ = incoming_reference(target, source, payload)
    assert reference.relation_confidence == confidence


@pytest.mark.parametrize("language", ["english(us)", "chinese(prc)", "portuguese(br)"])
def test_sound_reference_preserves_language_folder_parentheses(tmp_path, language):
    path = f"sound/windows/{language}/dialogue.wem"
    data = f'<Sound path="{path}"/>'.encode()
    target, source = entries_at(tmp_path, [(path, b"RIFF"), ("sound/dialogue.xml", data)])
    ref, _ = incoming_reference(target, source, data)
    assert ref is not None
    assert ref.relation_confidence == "explicit_path"


def chart_string(text):
    """The `.paac` frame: `<strlen + 1><ASCII><NUL>`; 98 characters frame as `c`."""
    return bytes([len(text) + 1]) + text.encode("ascii") + b"\x00"


_LONG_CLIP = "1_pc/1_phm/" + "x" * 83 + ".paa"


@pytest.mark.parametrize("target_path, source_path, payload, expected", [
    ("character/motion/1_pc/1_phm/idle.paa", "actionchart/bin__/upperaction/basic.paac",
     chart_string("1_pc/1_phm/idle.paa"), "explicit_path"),
    ("character/motion/" + _LONG_CLIP, "actionchart/bin__/upperaction/basic.paac",
     chart_string(_LONG_CLIP), "explicit_path"),
    ("character/motion/1_pc/1_phm/idle.paa", "character/binary/motionblending/phm/stance.motionblending",
     struct.pack("<I", 19) + b"1_pc/1_phm/idle.paa", "explicit_path"),
    ("actionchart/bin__/loweraction/2_mon/default_fist_lower.paac", "actionchart/bin__/loweraction/ai_lower.paac",
     chart_string("loweraction/2_mon/default_fist_lower"), "explicit_path"),
    ("character/bin__/prefab/6_object/tools/torch.prefab", "actionchart/bin__/loweraction/ride.paac",
     chart_string("/character/prefab/6_object/tools/torch.prefab"), "explicit_path"),
    ("sequencer/baseseq/fx/dark.paseq", "actionchart/bin__/loweraction/aux.paac",
     chart_string("baseseq/fx/dark"), "explicit_path"),
    ("character/motion/1_pc/1_phm/idle.paa", "actionchart/bin__/upperaction/basic.paac",
     chart_string("1_pc/2_phw/idle.paa"), None),
    ("actionchart/bin__/loweraction/2_mon/default_fist_lower.paac", "actionchart/bin__/loweraction/ai_lower.paac",
     chart_string("upperaction/2_mon/default_fist_lower"), None),
    ("actionchart/bin__/loweraction/2_mon/default_fist_lower.paac", "actionchart/bin__/loweraction/ai_lower.paac",
     chart_string("default_fist_lower_extra"), None),
], ids=["chart-clip", "leaked-length-byte", "blend-space", "sub-chart", "compiled-prefab", "sequence",
        "other-rig-folder", "other-chart-folder", "longer-name"])
def test_engine_resource_paths_are_explicit_references(tmp_path, target_path, source_path, payload, expected):
    target, source = entries_at(tmp_path, [(target_path, b"PAR "), (source_path, payload)])
    ref, supported = incoming_reference(target, source, payload)
    assert supported
    assert (ref.relation_confidence if ref else None) == expected


def test_animation_targets_read_charts_and_blend_spaces_first(tmp_path):
    (clip,) = entries_at(tmp_path, [("character/motion/1_pc/idle.paa", b"PAR ")])
    (texture,) = entries_at(tmp_path, [("textures/rock.dds", b"DDS ")])
    first = set(reference_source_extension_groups(clip)[0])
    assert {".paac", ".motionblending", ".paseq"} <= first and ".paa" not in first
    assert ".paac" not in reference_source_extension_groups(texture)[0]


def test_legacy_search_reads_only_banks_for_a_numeric_sound(app, tmp_path, monkeypatch):
    # No shipped file stores a .wem path (all 1,133,077 reference containers of
    # game 1.0.0.3446 were read); banks name sounds by media ID.
    from cdmw.workers import archive_reference_workers
    data = bank()
    files = entries_at(tmp_path, [
        ("audio/42.wem", b"RIFF"), ("character/body.pac", b"x" * 512),
        ("audio/bank.bnk", data), ("audio/info.xml", b'"audio/42.wem"'),
    ])
    scanned = []
    def record_scan(target, entries, stop):
        scanned.extend(entry.path for entry in entries)
        return scan_reference_batch(target, entries, stop)
    monkeypatch.setattr(archive_reference_workers, "scan_reference_batch", record_scan)
    controller = ArchiveReferenceSearchController()
    try:
        controller.start(files[0], files)
        wait_for(app, lambda: not controller.busy)
        assert {ref.resolved_entry.path for ref in controller.state.references} == {"audio/bank.bnk"}
        assert scanned == ["audio/bank.bnk"]
        assert not controller.state.limited
    finally:
        controller.cancel()
        wait_for(app, lambda: not controller.busy)


def test_unknown_evidence_is_context_not_confirmation_or_a_name_guess():
    assert reference_evidence_group("xml_reference") == "Unresolved / context"
    assert reference_evidence_group("explicit_path", "missing") == "Unresolved / context"


def test_existing_reference_resolution_does_not_promote_companions_or_basename_fallbacks(tmp_path):
    from cdmw.core.archive_references import build_archive_related_file_references, build_archive_relationship_references
    source, texture, sidecar = entries_at(tmp_path, [
        ("model/chair.pac", b"PAR "), ("textures/chair.dds", b"DDS "), ("metadata/chair.pac.xml", b"<Root/>"),
    ])
    paths = {entry.path: [entry] for entry in (source, texture, sidecar)}
    names = {entry.basename: [entry] for entry in (source, texture, sidecar)}
    for reference_name in ("chair.dds", "other/chair.dds"):
        refs = build_archive_related_file_references(source, explicit_reference_names=[reference_name],
                                                    archive_entries_by_normalized_path=paths, archive_entries_by_basename=names)
        assert len(refs) == 1
        assert reference_evidence_group(refs[0].relation_confidence) == "Name-based guesses"
    refs = build_archive_related_file_references(source, companion_entries=[texture], explicit_reference_names=[texture.path],
                                                archive_entries_by_normalized_path=paths, archive_entries_by_basename=names)
    assert len(refs) == 1 and reference_evidence_group(refs[0].relation_confidence) == "Confirmed references"
    refs = build_archive_relationship_references(source, archive_entries_by_normalized_path=paths, archive_entries_by_basename=names)
    companion = next(ref for ref in refs if ref.resolved_entry == sidecar)
    assert reference_evidence_group(companion.relation_confidence) == "Name-based guesses"
    refs = build_archive_related_file_references(texture, companion_entries=[sidecar])
    assert reference_evidence_group(refs[0].relation_confidence) == "Name-based guesses"


@pytest.mark.parametrize("version", [113, 128, 150, 151, 154])
def test_streamed_sound_source_id_without_didx(tmp_path, version):
    data = bank(version=version)
    target, source = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", data)])
    ref, supported = incoming_reference(target, source, data)
    assert supported and ref.relation_confidence == "wwise_media_id"


@pytest.mark.parametrize("data, match, supported", [
    (bank(didx=True), True, True),
    (bank(version=155), False, False),
    (bank(plugin=0x10002), False, True),
    (bank(plugin=0x80001), False, True),
    (bank(media_id=43) + chunk(b"DATA", struct.pack("<I", 42) + b"audio/42.wem"), False, True),
    (bank()[:-1], False, False),
    (bank() + b"broken", False, False),
])
def test_sound_ids_require_structured_evidence(tmp_path, data, match, supported):
    target, source = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", data)])
    ref, covered = incoming_reference(target, source, data)
    assert bool(ref) == match
    assert covered == supported


def test_sound_bank_forward_family_includes_streamed_sources(tmp_path):
    from cdmw.core.archive_asset_family import build_archive_entry_related_references
    data = bank()
    target, source = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", data)])
    refs = build_archive_entry_related_references(
        source, binary_data=data, archive_entries_by_basename={target.basename: [target]},
        archive_entries_by_normalized_path={target.path: [target]},
    )
    assert len(refs) == 1 and refs[0].resolved_entry == target
    assert refs[0].relation_confidence == "wwise_media_id"


def test_forward_sound_family_does_not_scan_media_payload_as_paths(tmp_path):
    from cdmw.core.archive_asset_family import build_archive_entry_related_references
    data = bank(media_id=43) + chunk(b"DATA", b"audio/42.wem\x00")
    target, source = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", data)])
    refs = build_archive_entry_related_references(source, binary_data=data,
        archive_entries_by_basename={target.basename: [target]}, archive_entries_by_normalized_path={target.path: [target]})
    assert all(ref.resolved_entry != target for ref in refs)


def test_read_only_scan_counts_failures_and_cancels(tmp_path):
    target, source, missing = entries_at(tmp_path, [
        ("textures/shared.dds", b"DDS "), ("ui/menu.xml", b'"textures/shared.dds"'), ("missing.xml", b""),
    ])
    missing = replace(missing, paz_file=tmp_path / "missing.paz")
    before = target.paz_file.read_bytes()
    result = scan_reference_batch(target, (source, missing), threading.Event())
    assert result.scanned == 1 and result.unreadable == 1 and len(result.references) == 1
    assert target.paz_file.read_bytes() == before
    stop = threading.Event(); stop.set()
    with pytest.raises(RunCancelled):
        scan_reference_batch(target, (source,), stop)


def wait_for(app, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)
    assert predicate()


def test_legacy_controller_runs_real_worker_and_keeps_partial_coverage(app, tmp_path):
    target, source = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", bank())])
    controller = ArchiveReferenceSearchController()
    try:
        assert controller.start(target, (target, source), generation=11)
        wait_for(app, lambda: not controller.busy)
        assert controller.state.finished and len(controller.state.references) == 1
        assert controller.state.generation == 11
    finally:
        controller.cancel()
        wait_for(app, lambda: not controller.busy)


class Catalogue(QObject):
    result_ready = Signal(str, str, object)
    batch_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self, entries):
        super().__init__()
        self.entries = entries
        self.counter = 0
        self.pages = []
        self.prepared = []
        self.cancelled = []
        self.queries = []
        self.batch_transform = lambda result: result

    def publish(self, payload):
        self.counter += 1
        request = str(self.counter)
        QTimer.singleShot(0, lambda: self.result_ready.emit(request, "test", payload))
        return request

    def create_query(self, query, **_kwargs):
        self.queries.append(query)
        self.query_indices = [i for i, entry in enumerate(self.entries) if entry.extension in query.extensions]
        return self.publish(ArchiveQueryHandle("session", "query", 0, len(self.query_indices)))

    def dto(self, index):
        entry = self.entries[index]
        identity = ArchiveDurableIdentity(entry.path, str(entry.pamt_path), 0, entry.offset)
        return ArchiveEntryDto("session", index, identity, entry.path, str(entry.pamt_path), str(entry.paz_file),
                               0, entry.offset, entry.comp_size, entry.orig_size, 0, entry.extension, "0", ArchiveEntryRole.TEXT, "Text", True)

    def fetch_page(self, request, **_kwargs):
        self.pages.append(request.page_start)
        rows = tuple(self.dto(i) for i in self.query_indices[request.page_start:request.page_start + request.page_size])
        return self.publish(ArchivePage("session", "query", 0, len(self.query_indices), request.page_start, rows))

    def prepare_entries(self, request, **_kwargs):
        self.prepared.extend(request.entry_ids)
        items = []
        for index in request.entry_ids:
            entry = self.entries[index]
            data = entry.paz_file.read_bytes()[entry.offset:entry.offset + entry.orig_size]
            path = entry.paz_file.parent / f"prepared-{index}.bin"
            path.write_bytes(data)
            dto = self.dto(index)
            items.append(PrepareEntryResult(ArchiveEntryRef("session", index, dto.identity, dto.path), str(path), len(data), hashlib.sha256(data).hexdigest()))
        self.counter += 1
        request_id = str(self.counter)
        result = PrepareEntriesResult("session", tuple(items), len(items), len(items), sum(item.size for item in items))
        def publish_prepared():
            # The production worker streams items, then sends an empty final list.
            for item in items:
                self.batch_ready.emit(request_id, "prepare_entry", self.batch_transform(replace(result, items=(item,))))
            self.result_ready.emit(request_id, "prepare_entry", replace(result, items=()))
        QTimer.singleShot(0, publish_prepared)
        return request_id

    def cancel(self, request):
        self.cancelled.append(request)


def test_remote_search_pages_beyond_preview_dependencies_and_reads_prepared_files(app, tmp_path):
    files = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), *[(f"audio/{i}.bnk", bank(media_id=42 if i == 19 else 43)) for i in range(21)]])
    catalogue = Catalogue(files[1:])
    controller = ArchiveReferenceSearchController(catalogue)
    try:
        controller.start(files[0], session_id="session", generation=5)
        wait_for(app, lambda: not controller.busy)
        assert not controller.state.error
        assert catalogue.pages == [0, 16]
        assert catalogue.prepared == list(range(21))
        assert controller.state.scanned == controller.state.total == 21
        assert [ref.resolved_archive_path for ref in controller.state.references] == ["audio/19.bnk"]
        assert ".bnk" in catalogue.queries[0].extensions
    finally:
        controller.cancel()
        wait_for(app, lambda: not controller.busy)


def test_cancel_before_catalogue_reply_rejects_stale_result(app, tmp_path):
    files = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", bank())])
    catalogue = Catalogue(files[1:])
    controller = ArchiveReferenceSearchController(catalogue)
    controller.start(files[0], session_id="session", generation=5)
    controller.cancel()
    app.processEvents()
    assert controller.state.cancelled and not controller.busy
    assert not catalogue.pages and catalogue.cancelled


def test_shutdown_retains_running_worker_until_exit_and_discards_late_batch(app, tmp_path, monkeypatch):
    from cdmw.workers import archive_reference_workers
    from cdmw.core.archive_reverse_references import ReferenceScanBatch
    target, source = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", bank())])
    entered, release = threading.Event(), threading.Event()
    def blocked_scan(*_args):
        entered.set()
        release.wait(3)
        return ReferenceScanBatch((incoming_reference(target, source, bank())[0],), scanned=1)
    monkeypatch.setattr(archive_reference_workers, "scan_reference_batch", blocked_scan)
    controller = ArchiveReferenceSearchController()
    try:
        controller.start(target, (source,), generation=1)
        wait_for(app, entered.is_set)
        controller.request_shutdown()
        assert controller.busy and len(tuple(controller.iter_shutdown_workers())) == 1
        release.set()
        wait_for(app, lambda: not controller.busy)
        assert controller.state.cancelled and not controller.state.references
        assert not tuple(controller.iter_shutdown_workers())
    finally:
        release.set()
        controller.cancel()
        wait_for(app, lambda: not controller.busy)


def test_per_file_limit_reports_skips(app, tmp_path, monkeypatch):
    import cdmw.services.archive_reference_search as search
    target, source = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", bank())])
    monkeypatch.setattr(search, "MAX_REFERENCE_FILE_BYTES", 1)
    controller = ArchiveReferenceSearchController()
    controller.start(target, (source,))
    wait_for(app, lambda: not controller.busy)
    assert controller.state.finished
    assert controller.state.skipped == 1 and not controller.state.references


def test_search_continues_past_two_gib_in_bounded_batches(app, tmp_path, monkeypatch):
    from cdmw.workers import archive_reference_workers
    from cdmw.core.archive_reverse_references import ReferenceScanBatch
    files = entries_at(tmp_path, [("audio/42.wem", b"RIFF"),
                                  *[(f"audio/{i}.bnk", bank()) for i in range(65)]])
    files[1:] = [replace(entry, orig_size=32 * 1024 * 1024) for entry in files[1:]]
    batches = []
    def scan(target, entries, stop):
        batches.append(len(entries))
        refs = tuple(incoming_reference(target, entry, bank())[0] for entry in entries)
        return ReferenceScanBatch(refs, scanned=len(entries), bytes_read=sum(entry.orig_size for entry in entries))
    monkeypatch.setattr(archive_reference_workers, "scan_reference_batch", scan)
    catalogue = Catalogue(files[1:])
    controller = ArchiveReferenceSearchController(catalogue)
    try:
        controller.start(files[0], session_id="session")
        wait_for(app, lambda: not controller.busy)
        assert not controller.state.error and not controller.state.limited
        assert controller.state.scanned == controller.state.total == 65
        assert controller.state.bytes_read > 2 * 1024 * 1024 * 1024
        assert len(controller.state.references) == 65
        assert max(batches) <= 16
    finally:
        controller.cancel()
        wait_for(app, lambda: not controller.busy)


def test_paged_search_also_skips_named_voice_lines(app, tmp_path):
    path = "sound/windows/english(us)/dialogue.wem"
    files = entries_at(tmp_path, [(path, b"RIFF"), ("character/body.pac", path.encode()),
                                  ("audio/bank.bnk", bank()), ("sound/dialogue.xml", path.encode())])
    catalogue = Catalogue(files[1:])
    controller = ArchiveReferenceSearchController(catalogue)
    try:
        controller.start(files[0], session_id="session")
        wait_for(app, lambda: not controller.busy)
        assert not controller.state.error and controller.state.note == "runtime_named_sound"
        assert not catalogue.queries and not catalogue.prepared and not controller.state.references
    finally:
        controller.cancel()
        wait_for(app, lambda: not controller.busy)


def test_cancel_during_preparation_discards_later_streamed_items(app, tmp_path):
    files = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", bank())])
    catalogue = Catalogue(files[1:])
    controller = ArchiveReferenceSearchController(catalogue)
    catalogue.batch_ready.connect(lambda *_: controller.cancel())
    controller.start(files[0], session_id="session")
    wait_for(app, lambda: not controller.busy)
    assert controller.state.cancelled and not controller.state.references
    assert not controller._prepared
    assert len(catalogue.queries) == 1


def test_mismatched_preparation_batch_stops_search_and_discards_final_reply(app, tmp_path):
    files = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/ambient.bnk", bank())])
    catalogue = Catalogue(files[1:])
    catalogue.batch_transform = lambda result: replace(result, session_id="another-session")
    controller = ArchiveReferenceSearchController(catalogue)
    controller.start(files[0], session_id="session")
    wait_for(app, lambda: not controller.busy)
    assert controller.state.error == "Reference search preparation omitted a requested file."
    assert not controller.state.references and not controller._prepared
    assert len(catalogue.cancelled) == 1 and len(catalogue.queries) == 1


@pytest.mark.parametrize("basename", ["42.wem", "dialogue.wem"])
def test_real_worker_search_consumes_streamed_preparation(app, tmp_path, basename):
    import shiboken6
    from cdmw.domain.archives.catalogue import ArchiveQuery
    from cdmw.domain.archives.catalogue_operations import FetchPageRequest, OpenArchiveRequest
    from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
    from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient
    from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter

    worker = Path(__file__).resolve().parents[1] / (
        "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/bin/Release/"
        "net10.0-windows/win-x64/cdmw-full-archive-worker.exe"
    )
    if not worker.is_file():
        pytest.skip("built archive worker is required for the real protocol check")
    root = tmp_path / "owned"
    package = root / "0000"
    package.mkdir(parents=True)
    target_path = f"sound/windows/english(us)/{basename}"
    payloads = [(target_path, b"RIFF"),
                *[(f"sound/bank{i:02}.bnk", bank(media_id=42 if i == 20 else 43)) for i in range(21)],
                ("sound/scene.xml", f'<Sound path="{target_path}"/>'.encode()),
                ("character/body.pac", target_path.encode())]
    names, contents, records = bytearray(), bytearray(), bytearray()
    for path, data in payloads:
        encoded = path.encode()
        records += struct.pack("<IIIIHH", len(names), len(contents), len(data), len(data), 0, 0)
        names += struct.pack("<I", 0xFFFFFFFF) + bytes([len(encoded)]) + encoded
        contents += data
    (package / "0.paz").write_bytes(contents)
    (package / "0.pamt").write_bytes(struct.pack("<7I", 0, 1, 0, 0, 0, 0, 0)
        + struct.pack("<I", len(names)) + names + struct.pack("<II", 0, len(payloads)) + records)
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in package.iterdir()}
    client = ArchiveBackendClient(cache_root=tmp_path / "cache", worker_executable=worker)
    service = ArchiveCatalogueService(client)
    awaiter = _Awaiter(service)
    controller = ArchiveReferenceSearchController(service)
    try:
        session = awaiter.wait(service.open_archive(OpenArchiveRequest(str(root)), ui_generation=5))
        query = awaiter.wait(service.create_query(ArchiveQuery(session.session_id, extensions=(".wem",)), ui_generation=5))
        page = awaiter.wait(service.fetch_page(FetchPageRequest(query.query_id, 0, 16), ui_generation=5))
        target = service.compatibility_entry(page.rows[0])
        controller.start(target, session_id=session.session_id, generation=5)
        assert _Awaiter._wait_until(lambda: not controller.busy, timeout_ms=15000)
        assert not controller.state.error, controller.state.error
        if basename == "42.wem":
            # The worker byte-searches the 21 banks for the media ID; Python reads the one hit.
            assert {ref.resolved_archive_path for ref in controller.state.references} == {"sound/bank20.bnk"}
            assert controller.state.scanned == controller.state.total == 21
            assert controller.state.candidates == (1 if service.byte_search_available else 0)
        else:
            assert not controller.state.references and controller.state.note == "runtime_named_sound"
            assert controller.state.scanned == controller.state.total == 0
        assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in package.iterdir()}
    finally:
        controller.cancel()
        assert _Awaiter._wait_until(lambda: not controller.busy, timeout_ms=5000)
        client.shutdown()
        assert _Awaiter._wait_until(lambda: client.process_id == 0, timeout_ms=5000)
        shiboken6.delete(controller)
        shiboken6.delete(service)
        shiboken6.delete(client)


class Family(QWidget, ArchiveAssetFamilyPanelMixin, ArchiveAssetFamilyDialogMixin, ArchiveAssetFamilyReferenceMixin):
    def __init__(self, target, entries):
        super().__init__()
        self.archive = self
        self.entry = target
        self.archive_entries = entries
        self.archive_preview_request_id = 7
        self.archive_reference_search_button = QPushButton("Find references", self)
        self.archive_reference_cancel_button = QPushButton("Cancel", self)
        self.archive_reference_search_status = QLabel(self)
        self.archive_asset_map_tree = QTreeWidget(self)
        self.archive_asset_map_tree.setColumnCount(5)
        self.archive_asset_used_by_tree = QTreeWidget(self)
        self.archive_asset_used_by_tree.setColumnCount(5)
        self.current_archive_model_texture_references = []
        self.current_archive_used_by_references = []
        self.current_archive_family_member_rows = []
        self.current_archive_asset_family_graph = None
        self.shell = SimpleNamespace()
        self.archive_reference_search_button.clicked.connect(self._start_archive_reference_search)
        self.archive_reference_cancel_button.clicked.connect(self._cancel_archive_reference_search)

    def _current_archive_entry(self): return self.entry
    def _archive_known_used_by_references(self, entry): return []
    def _archive_entry_role_label(self, entry): return entry.extension
    def _archive_texture_reference_status_text(self, ref): return ref.resolution_status
    def _style_archive_role_columns(self, *_args): pass
    def _ui_style_status_columns(self, *_args): pass

    def _populate_archive_texture_reference_list(self, *_args, **_kwargs):
        self.current_archive_used_by_references = self._archive_incoming_references(self.entry)
        self._populate_archive_relation_tree(self.archive_asset_used_by_tree, self.current_archive_used_by_references,
                                            source_name=self.entry.basename, reference_source="used_by")
        self.archive_asset_map_tree.clear()
        self._partition_archive_asset_map([], [])


def test_button_search_displays_confirmed_and_guesses_separately(app, tmp_path):
    files = entries_at(tmp_path, [("textures/a.dds", b"DDS "), ("ui/one.xml", b'"textures/a.dds"'), ("ui/two.xml", b'"a.dds"')])
    owner = Family(files[0], files)
    try:
        assert owner._archive_has_asset_family_workspace()
        owner.archive_reference_search_button.click()
        wait_for(app, lambda: not owner.archive_reference_search_controller.busy)
        for tree in (owner.archive_asset_map_tree, owner.archive_asset_used_by_tree):
            labels = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
            assert any(label.startswith("Confirmed references") for label in labels)
            assert any(label.startswith("Name-based guesses") for label in labels)
            assert tree.topLevelItem(0).child(0).data(0, Qt.UserRole)[0] == "used_by"
        # Incoming sources never become outgoing export dependencies.
        assert owner.current_archive_model_texture_references == []
        old_state = owner.archive_reference_search_state
        owner.entry = files[1]
        owner.archive_preview_request_id += 1
        owner._archive_reference_search_updated(old_state)
        assert owner.archive_reference_search_state is old_state
    finally:
        owner._cancel_archive_reference_search()
        wait_for(app, lambda: not owner.archive_reference_search_controller.busy)
        owner.deleteLater()


@pytest.mark.parametrize("target_path, source_path, found", [
    ("ui/icon.png", "tree/bush_icon.pat", True),
    # No shipped file names an .ogg, so the search says so instead of reading.
    ("audio/voice.ogg", "ui/scene.xml", False),
])
def test_other_registered_images_and_sounds_expose_search(app, tmp_path, target_path, source_path, found):
    files = entries_at(tmp_path, [(target_path, b""), (source_path, target_path.encode())])
    owner = Family(files[0], files)
    try:
        assert owner._archive_has_asset_family_workspace()
        owner.archive_reference_search_button.click()
        wait_for(app, lambda: not owner.archive_reference_search_controller.busy)
        if found:
            assert owner.current_archive_used_by_references[0].resolved_entry == files[1]
        else:
            assert not owner.current_archive_used_by_references
            assert owner.archive_reference_search_status.text().startswith("Not searched")
    finally:
        owner._cancel_archive_reference_search()
        wait_for(app, lambda: not owner.archive_reference_search_controller.busy)
        owner.deleteLater()


@pytest.mark.parametrize("target_path, stored", [
    ("character/motion/1_pc/1_phm/idle.paa", "1_pc/1_phm/idle.paa"),
    ("character/binary/motionblending/phm/walk.motionblending", "character/binary/motionblending/phm/walk.motionblending"),
    ("actionchart/bin__/loweraction/2_mon/default_fist_lower.paac", "loweraction/2_mon/default_fist_lower"),
], ids=["clip", "blend-space", "sub-chart"])
def test_animation_targets_find_the_charts_that_name_them(app, tmp_path, target_path, stored):
    files = entries_at(tmp_path, [
        (target_path, b"PAR "), ("actionchart/bin__/upperaction/basic_upper.paac", chart_string(stored)),
    ])
    owner = Family(files[0], files)
    try:
        assert owner._archive_has_asset_family_workspace()
        owner.archive_reference_search_button.click()
        wait_for(app, lambda: not owner.archive_reference_search_controller.busy)
        (reference,) = owner.current_archive_used_by_references
        assert reference.resolved_entry == files[1]
        assert reference_evidence_group(reference.relation_confidence) == "Confirmed references"
    finally:
        owner._cancel_archive_reference_search()
        wait_for(app, lambda: not owner.archive_reference_search_controller.busy)
        owner.deleteLater()


class FullPanel(Family, ArchiveAssetFamilyLayoutMixin):
    _populate_archive_texture_reference_list = ArchiveAssetFamilyPanelMixin._populate_archive_texture_reference_list

    def _refresh_archive_asset_family_panel_layout(self, **_kwargs): pass
    def _schedule_archive_asset_family_panel_layout(self, **_kwargs): pass
    def _update_archive_texture_reference_action_controls(self): pass


@pytest.mark.parametrize("texture", [False, True], ids=["sound", "texture"])
def test_real_layout_and_full_panel_preserve_incoming_results(app, tmp_path, texture):
    files = entries_at(tmp_path, [("textures/a.dds", b"DDS "), ("ui/scene.xml", b'"textures/a.dds"')]
                       if texture else [("audio/42.wem", b"RIFF"), ("audio/bank.bnk", bank())])
    owner = FullPanel(files[0], files)
    owner.shell.settings = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    owner.shell.schedule_settings_save = lambda: None
    owner.shell._tree_horizontal_wheel_guards = []
    owner.archive_asset_family_button = QPushButton("Asset Family", owner)
    owner.archive_asset_family_panel_requested = True
    owner._build_archive_texture_references_panel()
    owner.archive_texture_refs_group.setParent(owner)
    try:
        owner.archive_reference_search_button.click()
        wait_for(app, lambda: not owner.archive_reference_search_controller.busy)
        assert len(owner.current_archive_used_by_references) == 1
        assert owner.archive_asset_used_by_tree.topLevelItem(0).text(0).startswith("Confirmed references")
        assert owner.archive_asset_map_tree.topLevelItem(0).child(0).data(0, Qt.UserRole) == ("used_by", 0)
        assert not owner.archive_texture_refs_group.isHidden()
        owner._populate_archive_texture_reference_list((), None, enrich=False)
        assert len(owner.current_archive_used_by_references) == 1
        owner._populate_archive_texture_reference_list((), None, enrich=True)
        assert len(owner.current_archive_used_by_references) == 1
        assert not owner.current_archive_model_texture_references
        assert all(row.resolved_entry != files[1] for row in owner.current_archive_asset_family_graph.member_rows)
    finally:
        owner._cancel_archive_reference_search()
        wait_for(app, lambda: not owner.archive_reference_search_controller.busy)
        owner.archive_texture_refs_group.deleteLater()
        owner.deleteLater()


# -- measured source formats and the worker's byte search ----------------------


class ByteSearchCatalogue(Catalogue):
    """A catalogue whose worker offers byte search, as text_search_bytes_v1 workers do."""

    progress = Signal(str, object)
    byte_search_available = True

    def __init__(self, entries):
        super().__init__(entries)
        self.searches = []
        self.resolved = []

    def text_search(self, request, **_kwargs):
        from cdmw.domain.archives.catalogue_operations import ArchiveTextMatch, ArchiveTextSearchBatch
        self.searches.append(request)
        needles = [request.query]
        if request.query.isascii() and request.query.isprintable():
            needles += ["".join(f"{c}\0" for c in request.query), "".join(f"\0{c}" for c in request.query)]
        matches, scanned = [], 0
        for index, entry in enumerate(self.entries):
            if entry.extension not in request.extensions:
                continue
            scanned += 1
            text = entry.paz_file.read_bytes()[entry.offset:entry.offset + entry.orig_size].decode("latin-1")
            haystack = text if request.case_sensitive else text.lower()
            if any((needle if request.case_sensitive else needle.lower()) in haystack for needle in needles):
                matches.append(ArchiveTextMatch(index, entry.path, 1, 1, len(request.query), "", "0"))
        self.counter += 1
        request_id = str(self.counter)
        def publish():
            self.batch_ready.emit(request_id, "text_search", ArchiveTextSearchBatch(
                "session", scanned, len(matches), 0, tuple(matches), False, False, ()))
            self.result_ready.emit(request_id, "text_search", ArchiveTextSearchBatch(
                "session", scanned, len(matches), 0, (), True, False, ()))
        QTimer.singleShot(0, publish)
        return request_id

    def resolve_entries(self, request, **_kwargs):
        from cdmw.domain.archives.catalogue import ArchiveLookupResult
        self.resolved.extend(request.entry_ids)
        rows = tuple(self.dto(index) for index in request.entry_ids)
        self.counter += 1
        request_id = str(self.counter)
        def publish():
            self.batch_ready.emit(request_id, "resolve_entries", ArchiveLookupResult("session", rows, len(rows), False))
            self.result_ready.emit(request_id, "resolve_entries", ArchiveLookupResult("session", (), len(rows), False))
        QTimer.singleShot(0, publish)
        return request_id


def run_search(app, controller, target):
    try:
        controller.start(target, session_id="session", generation=3)
        wait_for(app, lambda: not controller.busy)
        return controller.state
    finally:
        controller.cancel()
        wait_for(app, lambda: not controller.busy)


def test_named_voice_lines_are_not_searched(app, tmp_path):
    path = "sound/windows/chinese(prc)/unique_kliff_aidialogstringinfo_affinity_quest_51013.wem"
    files = entries_at(tmp_path, [(path, b"RIFF"), ("sound/dialogue.xml", path.encode()), ("audio/a.bnk", bank())])
    catalogue = ByteSearchCatalogue(files[1:])

    state = run_search(app, ArchiveReferenceSearchController(catalogue), files[0])

    assert state.finished and not state.error and not state.references
    assert state.note == "runtime_named_sound"
    assert not catalogue.queries and not catalogue.searches and not catalogue.prepared


def test_byte_search_reads_only_measured_formats_and_candidate_files(app, tmp_path):
    texture = "character/texture/rock_d.dds"
    files = entries_at(tmp_path, [
        (texture, b"DDS "),
        ("object/rock.pami", f'<Texture path="{texture}"/>'.encode()),
        ("object/other.pami", b'<Texture path="character/texture/sand_d.dds"/>'),
        ("object/rock.pam", b"PAR \x00\x00" + texture.upper().encode("utf-16-le") + b"\x00\x00"),
        ("character/model/rock.pac", texture.encode()),
    ])
    catalogue = ByteSearchCatalogue(files[1:])

    state = run_search(app, ArchiveReferenceSearchController(catalogue), files[0])

    assert not state.error and not state.limited
    assert {ref.resolved_entry.path for ref in state.references} == {"object/rock.pami", "object/rock.pam"}
    assert all(search.match_bytes and not search.case_sensitive for search in catalogue.searches)
    assert all(".pac" not in search.extensions for search in catalogue.searches)
    assert sorted(catalogue.resolved) == sorted(catalogue.prepared) == [0, 2]
    assert state.candidates == 2 and state.scanned == state.total == 3
    assert not catalogue.pages


def test_numeric_sounds_search_banks_for_their_media_id_bytes(app, tmp_path):
    from cdmw.core.archive_reverse_references import bank_media_id_query
    files = entries_at(tmp_path, [("audio/42.wem", b"RIFF"), ("audio/a.bnk", bank(media_id=43)), ("audio/b.bnk", bank()),
                                  ("audio/info.xml", b'"audio/42.wem"')])
    catalogue = ByteSearchCatalogue(files[1:])

    state = run_search(app, ArchiveReferenceSearchController(catalogue), files[0])

    assert [ref.resolved_archive_path for ref in state.references] == ["audio/b.bnk"]
    (search,) = catalogue.searches
    assert search.query == bank_media_id_query(42) and search.case_sensitive and search.extensions == (".bnk",)
    assert catalogue.prepared == [1]


def test_older_workers_fall_back_to_reading_the_measured_formats(app, tmp_path):
    texture = "character/texture/rock_d.dds"
    files = entries_at(tmp_path, [(texture, b"DDS "), ("object/rock.pami", f'"{texture}"'.encode()),
                                  ("character/model/rock.pac", texture.encode())])
    catalogue = Catalogue(files[1:])

    state = run_search(app, ArchiveReferenceSearchController(catalogue), files[0])

    assert [ref.resolved_entry.path for ref in state.references] == ["object/rock.pami"]
    assert catalogue.prepared == [0] and all(".pac" not in query.extensions for query in catalogue.queries)


def test_files_without_the_name_are_rejected_before_any_decoding():
    from cdmw.core.archive_reverse_references import may_name_target
    assert may_name_target(b"..ROCK_D.DDS..", ("rock_d.dds",))
    assert may_name_target("x rock_d.dds".encode("utf-16-le"), ("rock_d.dds",))
    assert may_name_target("x rock_d.dds".encode("utf-16-be"), ("rock_d.dds",))
    assert not may_name_target(b"rock_n.dds sand_d.dds", ("rock_d.dds",))


def test_length_prefixed_paths_count_whatever_byte_follows_them(tmp_path):
    path = "effect/texture/pafx_grass_001a_1bit.dds"
    stored = struct.pack("<I", len(path)) + path.encode() + b"/\x00\x00\x00Y"
    target, preset = entries_at(tmp_path, [(path, b"DDS "), ("effect/binary__/renderpreset/grass.parg", b"\x00" * 8 + stored)])
    ref, _supported = incoming_reference(target, preset, b"\x00" * 8 + stored)
    assert ref is not None and ref.relation_confidence == "explicit_path" and ref.relation_reason == path
    longer = struct.pack("<I", len(path) + 4) + b"old/" + path.encode() + b"/"
    assert incoming_reference(target, preset, longer)[0] is None
