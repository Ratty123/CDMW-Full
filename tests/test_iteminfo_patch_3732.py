"""Owned records for the one-byte ItemInfo and PageData fields added by game 1.0.0.3732."""
import struct

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_row import (
    ItemInfoRowError, clone_iteminfo_row, parse_iteminfo_row, rebuild_stat_block, set_max_stack_count,
)
from cdmw.core.new_item_record import RecordError
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_snapshot import NewItemSnapshotError, build_snapshot
from tests.compact_item_fixtures import files, item, table, text
from tests.test_iteminfo_patch_layout import ROOT, SOUND, SOCKET, patched as patched_3527
from tests.test_new_item_provenance import spec
from tests.test_new_item_service import _read, build_package

DISCARD_SINGLE = 1
ROTATION = 2


def with_page(raw, *, rotation=None):
    """Give the row one fixed page; `rotation` adds the 3732 trailing byte."""
    layout = read_item_layout(raw)
    span = layout.fields['_fixedPageDataList']
    page = text('ui/left_page.dds') + text('ui/right_page.dds') + struct.pack('<II', 1990101, 1990102)
    if rotation is not None:
        page += bytes([rotation])
    return raw[:span.start] + b'\1' + struct.pack('<I', 1) + page + raw[span.end:]


def patched(raw, discard_single=DISCARD_SINGLE, rotation=ROTATION):
    """Build a 3732 row from a 3527 row, locating each insertion with the older reader."""
    layout = read_item_layout(raw)
    pages = [m.span.end for m in layout.members
             if m.owner == 'PageData' and m.name == '_rightPageRelatedKnowledgeInfo']
    cuts = sorted([(layout.fields['_discardable'].end, bytes([discard_single]))]
                  + [(end, bytes([rotation])) for end in pages], reverse=True)
    for at, value in cuts:
        raw = raw[:at] + value + raw[at:]
    return raw


def old_row():
    return with_page(patched_3527(item()))


def test_3732_rows_keep_new_fields_through_edits_and_clone():
    old = old_row()
    new = patched(old)
    assert len(new) == len(old) + 2
    assert '_discardSingleCount' not in read_item_layout(old).fields
    for raw in (old, new):
        row = parse_iteminfo_row(raw)
        assert rebuild_stat_block(row) == raw
        outputs = [raw, set_max_stack_count(row, 17), clone_iteminfo_row(
            row, key=1990001, string_key='PatchedClone', name_key='owned_name',
            desc_key='owned_description', replace_hashes={})]
        for output in outputs:
            layout = read_item_layout(output)
            assert layout.generation == 'compact'
            assert layout.data('_soundNameOnMaxCharged') == text(SOUND)
            rotation = [output[m.span.start:m.span.end] for m in layout.members if m.name == '_uiTextureRotationType']
            if raw is new:
                assert layout.data('_discardSingleCount') == bytes([DISCARD_SINGLE])
                assert rotation == [bytes([ROTATION])]
            else:
                assert '_discardSingleCount' not in layout.fields and rotation == []
        assert parse_iteminfo_row(outputs[1]).max_stack_count == 17
        assert parse_iteminfo_row(outputs[2]).key == 1990001


def test_a_3732_row_without_pages_still_needs_the_flag_byte():
    raw = patched(patched_3527(item()))
    assert read_item_layout(raw).data('_discardSingleCount') == bytes([DISCARD_SINGLE])
    # The flag without the page byte, or the page byte without the flag, is no known build.
    page_only = with_page(patched_3527(item()), rotation=ROTATION)
    full = patched(old_row())
    rot = next(m.span for m in read_item_layout(full).members if m.name == '_uiTextureRotationType')
    flag_only = full[:rot.start] + full[rot.end:]
    for raw in (page_only, flag_only):
        with pytest.raises(RecordError, match='compact ItemInfo layout'):
            read_item_layout(raw)


@pytest.mark.parametrize('damage', ['truncated', 'extra'])
def test_unknown_layouts_list_every_known_generation(damage):
    raw = patched(old_row())
    raw = raw[:-1] if damage == 'truncated' else raw + b'\0'
    with pytest.raises(ItemInfoRowError, match='Unsupported ItemInfo row layout') as error:
        parse_iteminfo_row(raw)
    for label in ('pre-3527:', '3527:', '3732:'):
        assert label in str(error.value)


def _patched_files(rewrite):
    source = files()
    body, head = source[ROOT + 'iteminfo.staticinfobody'], source[ROOT + 'iteminfo.staticinfoheader']
    rows = [(row.row_id, rewrite(body[start:end])) for row, start, end in
            parse_pabgh_table(head, payload=body).row_spans(len(body))]
    source[ROOT + 'iteminfo.staticinfobody'], source[ROOT + 'iteminfo.staticinfoheader'] = table(rows)
    return source, rows


def test_snapshot_plan_and_export_keep_3732_fields(tmp_path):
    source, rows = _patched_files(lambda raw: patched(patched_3527(raw)))
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / 'game', source)), read_entry=_read)
    assert set(snapshot.rows) == {key for key, _raw in rows}
    plan = service.plan(spec('PatchedOwned3732'), snapshot, capture_independent=True)
    body, head = plan.loose_files[ROOT + 'iteminfo.staticinfobody'], plan.loose_files[ROOT + 'iteminfo.staticinfoheader']
    by_key = {row.row_id: body[start:end] for row, start, end in parse_pabgh_table(head, payload=body).row_spans(len(body))}
    for key, raw in rows:
        assert by_key[key] == raw  # untouched rows are copied byte for byte
    layout = read_item_layout(by_key[plan.spec.item_key])
    assert layout.data('_discardSingleCount') == bytes([DISCARD_SINGLE])
    assert layout.data('_soundSocketNameOnMaxCharged') == text(SOCKET)
    assert parse_iteminfo_row(by_key[plan.spec.item_key]).string_key == 'PatchedOwned3732'


def test_snapshot_says_when_no_row_decodes(tmp_path):
    # A build that adds a byte this app does not know breaks every row at once.
    source, _rows = _patched_files(lambda raw: patched(patched_3527(raw)) + b'\0')
    entries = parse_archive_pamt(build_package(tmp_path / 'game', source))
    with pytest.raises(NewItemSnapshotError) as error:
        build_snapshot(entries, read_entry=_read)
    message = str(error.value)
    assert 'did not decode' in message and '3732:' in message
    assert 'newer than this version supports' in message


def test_snapshot_counts_a_single_bad_row(tmp_path):
    damaged = []

    def rewrite(raw):
        raw = patched(patched_3527(raw))
        if not damaged:
            damaged.append(True)
            return raw + b'\0'
        return raw

    source, rows = _patched_files(rewrite)
    with pytest.raises(NewItemSnapshotError) as error:
        build_snapshot(parse_archive_pamt(build_package(tmp_path / 'game', source)), read_entry=_read)
    message = str(error.value)
    assert f'ItemInfo row {rows[0][0]} did not decode' in message
    assert f'1 of the first {len(rows)} rows did not decode' in message
    assert 'newer than this version' not in message


def test_probe_finds_both_3732_changes_when_the_generation_is_unknown(monkeypatch):
    from cdmw.core import compact_static
    from tools import probe_iteminfo_layout as probe

    rows = [patched(old_row()), patched(patched_3527(item()))]
    monkeypatch.setattr(compact_static, 'ITEMINFO_GENERATIONS', compact_static.ITEMINFO_GENERATIONS[:2])
    known, steps, sampled = probe.probe(rows, sample=10)
    assert known == {'pre-3527': 0, '3527': 0} and sampled == 2
    assert steps and steps[-1][1] == 2
    found = [tie for _change, _score, ties in steps for tie in ties]
    assert any(t.reader is None and t.after == '_discardable' and t.op == ('raw', 1) for t in found)
    assert any(t.reader is not None and t.after == '_rightPageRelatedKnowledgeInfo' and t.op == ('raw', 1)
               for t in found)


@pytest.mark.real_game
def test_installed_item_tables_decode_under_exactly_one_generation():
    """Guard for patch register P-34: every shipped ItemInfo and ItemUseInfo row, base and DLC."""
    import os
    from pathlib import Path

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.compact_static import ITEMINFO_GENERATIONS, _read_compact_layout
    from cdmw.core.item_layout import read_item_use_layout
    from tools.placement_studio import corpus

    root = Path(os.environ.get('CDMW_GAME_ROOT') or corpus.game_root())
    if not root.is_dir():
        pytest.skip('needs the installed game')
    pairs = {}
    for _package, entry in corpus._iter_archive_entries(root):
        path = corpus.normalize_game_path(entry.path)
        if path.startswith(ROOT) and path.rsplit('/', 1)[1].startswith(('iteminfo.', 'itemuseinfo.')):
            stem, part = path.rsplit('.', 1)
            pairs.setdefault(stem, {}).setdefault(part, entry)
    read = lambda entry: bytes(read_archive_entry_data(entry)[0])  # noqa: E731
    stems = {stem.rsplit('/', 1)[1] for stem in pairs}
    assert {'iteminfo', 'iteminfo.dlc_01', 'itemuseinfo', 'itemuseinfo.dlc_01'} <= stems, stems
    newest = ITEMINFO_GENERATIONS[-1][0]
    for stem, pair in pairs.items():
        body, header = read(pair['staticinfobody']), read(pair['staticinfoheader'])
        spans = parse_pabgh_table(header, payload=body).row_spans(len(body))
        assert len(spans) > 1000, stem
        failures = []
        for row, start, end in spans:
            raw = body[start:end]
            try:
                if '/itemuseinfo' in stem:
                    read_item_use_layout(raw)
                    continue
                parsed = parse_iteminfo_row(raw)
                assert parsed.key == row.row_id and rebuild_stat_block(parsed) == raw
                matched = []
                for label, program in ITEMINFO_GENERATIONS:
                    try:
                        _read_compact_layout(raw, 'iteminfo', program)
                        matched.append(label)
                    except (RecordError, UnicodeError):
                        pass
                assert matched == [newest], matched
            except RecordError as exc:
                if 'Blocked item-use definition' not in str(exc):
                    failures.append((row.row_id, str(exc)[:120]))
            except AssertionError as exc:
                failures.append((row.row_id, str(exc)[:120]))
        assert not failures, (stem, len(failures), failures[:3])
