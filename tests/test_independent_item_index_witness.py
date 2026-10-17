"""PAMT fingerprints must attest the index that supplied the selected entries."""
import hashlib
import os
import struct
from dataclasses import replace

import pytest

from cdmw.core.archive_format import calculate_pa_checksum, parse_archive_pamt
from cdmw.core.iteminfo_row import set_max_stack_count
from cdmw.domain.archives.iteminfo_composition import replace_rows, rows_of
from cdmw.services.independent_item_package import stock_snapshot
from cdmw.services.new_item_provenance import StaleNewItemSource
from cdmw.services.new_item_service import NewItemService
from tests.test_new_item_provenance import current_files
from tests.test_new_item_service import build_package, TEMPLATE


BODY = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
HEADER = BODY.replace('body', 'header')
ALTERNATE = 'character/fixture/alternate-iteminfo.bin'


def index_fixture(tmp_path):
    from cdmw.core.iteminfo_row import parse_iteminfo_row
    files = current_files()
    row = parse_iteminfo_row(rows_of(files[BODY], files[HEADER])[TEMPLATE])
    files[ALTERNATE] = replace_rows(files[BODY], files[HEADER], {TEMPLATE: set_max_stack_count(row, 9)})
    pamt = build_package(tmp_path / 'game', files)
    entries = parse_archive_pamt(pamt)
    original = pamt.read_bytes()
    changed = bytearray(original)
    table = len(changed) - len(entries) * struct.calcsize('<IIIIHH')
    indexes = {entry.path: index for index, entry in enumerate(entries)}
    first, second = indexes[BODY], indexes[ALTERNATE]
    assert entries[first].orig_size == entries[second].orig_size
    for index, offset in ((first, entries[second].offset), (second, entries[first].offset)):
        struct.pack_into('<I', changed, table + index * 20 + 4, offset)
    struct.pack_into('<I', changed, 0, calculate_pa_checksum(changed[12:]))
    assert len(changed) == len(original)
    return pamt, original, bytes(changed)


def replace_index(path, data, same_stamp):
    stamp = path.stat()
    path.write_bytes(data)
    if same_stamp:
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))


@pytest.mark.parametrize('same_stamp', [False, True])
def test_stock_snapshot_refuses_valid_mapping_replacement_before_first_payload_pin(tmp_path, same_stamp):
    pamt, original, changed = index_fixture(tmp_path)
    payloads = {path: path.read_bytes() for path in pamt.parent.glob('*.paz')}
    consumed = []

    class ReplacedIndexService(NewItemService):
        def build_snapshot(self, entries, **kwargs):
            replace_index(pamt, changed, same_stamp)
            result = super().build_snapshot(entries, **kwargs)
            consumed.append(result.rows[TEMPLATE].max_stack_count)
            return result

    with pytest.raises(StaleNewItemSource, match='[Ii]ndex'):
        stock_snapshot(tmp_path / 'game', service=ReplacedIndexService(), overlay_changes=())
    assert consumed == []  # The catalogue witness now refuses before decoding stale ItemInfo.
    assert stock_snapshot(tmp_path / 'game', overlay_changes=()).rows[TEMPLATE].max_stack_count == 9
    assert all(path.read_bytes() == data for path, data in payloads.items())
    assert hashlib.sha256(pamt.read_bytes()).digest() != hashlib.sha256(original).digest()


def test_captured_byte_parser_never_reopens_the_changed_index(tmp_path):
    from cdmw.core.archive_format import parse_archive_pamt_bytes
    pamt, original, changed = index_fixture(tmp_path)
    expected = parse_archive_pamt(pamt)
    pamt.write_bytes(changed)
    assert parse_archive_pamt_bytes(original, pamt) == expected
    assert parse_archive_pamt(pamt) != expected


@pytest.mark.parametrize('change', ['offset', 'flags'])
def test_index_replacement_during_parsing_retains_original_byte_witness(tmp_path, monkeypatch, change):
    import cdmw.core.archive_format as archive_format
    pamt, original, changed = index_fixture(tmp_path)
    if change == 'flags':
        entries = parse_archive_pamt(pamt)
        changed = bytearray(original)
        index = next(i for i, entry in enumerate(entries) if entry.path == BODY)
        struct.pack_into('<H', changed, len(changed) - len(entries) * 20 + index * 20 + 18, 16)
        struct.pack_into('<I', changed, 0, calculate_pa_checksum(changed[12:]))
        changed = bytes(changed)
    parse = archive_format._parse_archive_pamt_bytes

    def replace_during_parse(data, path, **kwargs):
        replace_index(pamt, changed, True)
        return parse(data, path, **kwargs)

    monkeypatch.setattr(archive_format, '_parse_archive_pamt_bytes', replace_during_parse)
    with pytest.raises(StaleNewItemSource, match='index changed since parsing'):
        stock_snapshot(tmp_path / 'game', overlay_changes=())


def test_index_change_during_payload_validation_is_not_hidden_by_same_stamps(tmp_path):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.services.new_item_provenance import SourceTracker
    pamt, _, changed = index_fixture(tmp_path)
    tracker = SourceTracker(lambda entry: read_archive_entry_data(entry)[0])
    entries = tracker.parse_index(pamt)
    tracker.read(next(entry for entry in entries if entry.path == BODY))
    revision = tracker.capture()

    def replace_during_read(entry):
        data = read_archive_entry_data(entry)[0]
        replace_index(pamt, changed, True)
        return data

    with pytest.raises(StaleNewItemSource, match='index changed since parsing'):
        replace(revision, reader=replace_during_read).validate()


@pytest.mark.parametrize('virtual', [False, True])
def test_final_fingerprinting_cannot_adopt_a_replacement_index(tmp_path, monkeypatch, virtual):
    from cdmw.services import archive_overlay_manager as overlays, virtual_loader_composition as composition
    from cdmw.domain.virtual_loader import VirtualProfile
    from cdmw.services.independent_item_install import prepare_install
    from cdmw.services.independent_item_package import package_bytes
    from tests.test_independent_item_fields import field_package
    pamt, _, changed = index_fixture(tmp_path)
    root = tmp_path / 'game'
    package = package_bytes(field_package(stock_snapshot(root, overlay_changes=())))
    source = tmp_path / 'item.cditem'
    source.write_bytes(package)
    owner, name = (composition, 'hash_file') if virtual else (overlays, '_read_source_checksum')
    checksum = getattr(owner, name)

    def replace_before_hash(path, stop_event=None, **kwargs):
        if path == pamt:
            replace_index(pamt, changed, True)
        return checksum(path, stop_event, **kwargs)

    monkeypatch.setattr(owner, name, replace_before_hash)
    with pytest.raises(ValueError, match='index changed since parsing'):
        if virtual:
            composition.prepare_profile(VirtualProfile((source,)), root)
        else:
            prepare_install([package], root)
    assert not (root / '.cdmw').exists()


def test_discovery_fork_keeps_index_witness_without_inheriting_payload_reads(tmp_path):
    pamt, original, changed = index_fixture(tmp_path)
    snapshot = stock_snapshot(tmp_path / 'game', overlay_changes=())
    before = snapshot.provenance.capture()
    child = snapshot.discovery_view()
    assert child.provenance.capture().indexes == before.indexes == ((pamt, hashlib.sha256(original).hexdigest()),)
    assert not child.provenance.capture().payloads
    child.payload(ALTERNATE)
    assert snapshot.provenance.capture().payloads == before.payloads
    replace_index(pamt, changed, True)
    with pytest.raises(StaleNewItemSource, match='index changed since parsing'):
        child.provenance.capture().validate()


@pytest.mark.parametrize('mounted', [False, True])
def test_external_index_replacement_during_collection_refuses(tmp_path, monkeypatch, mounted):
    import cdmw.core.archive_format as archive_format
    from cdmw.core.papgt_format import papgt_with_directory
    from cdmw.services.independent_item_compatibility import external_mods
    root = tmp_path / 'game'
    index_fixture(tmp_path)
    source, original, changed = index_fixture(tmp_path / 'foreign')
    if mounted:
        folder = root / 'foreign'
        folder.mkdir()
        for path in source.parent.iterdir():
            (folder / path.name).write_bytes(path.read_bytes())
        source = folder / source.name
        mount = root / 'meta/0.papgt'
        mount.write_bytes(papgt_with_directory(mount.read_bytes(), folder.name, int.from_bytes(original[:4], 'little'), first=True))
        folders = ()
    else:
        folders = (source.parent,)
    parse = archive_format._parse_archive_pamt_bytes

    def replace_during_parse(data, path, **kwargs):
        if path == source:
            replace_index(source, changed, True)
        return parse(data, path, **kwargs)

    monkeypatch.setattr(archive_format, '_parse_archive_pamt_bytes', replace_during_parse)
    with pytest.raises(StaleNewItemSource, match='index changed since parsing'):
        external_mods(root, {'directory': '0036'}, folders=folders)
