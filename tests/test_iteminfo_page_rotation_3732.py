"""Additional item behavior pages on 1.0.0.3732 rows (PageData._uiTextureRotationType).

The row layout reader learned the trailing page byte with the patch fix; the behavior
codec must read, keep and write it too, or every row with pages fails to read and a
page added to a new item breaks the row.
"""
import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.iteminfo_behavior import read_behavior_fields, set_behavior_fields
from cdmw.core.item_layout import read_item_layout
from cdmw.core.new_item_record import RecordError
from cdmw.domain.new_item.item_behavior import ItemBehaviorSettings, decode_behavior_settings
from cdmw.services.new_item_behavior import load_behavior_index
from cdmw.services.new_item_service import NewItemService
from tests.compact_item_fixtures import item
from tests.test_iteminfo_patch_3732 import ROTATION, _patched_files, old_row, patched, with_page
from tests.test_iteminfo_patch_layout import patched as patched_3527
from tests.test_new_item_service import _read, build_package

PAGE = {'left_texture': 'ui/left_page.dds', 'right_texture': 'ui/right_page.dds',
        'left_knowledge': 1990101, 'right_knowledge': 1990102}


def _rotation_bytes(raw):
    layout = read_item_layout(raw)
    return [raw[m.span.start:m.span.end] for m in layout.members if m.name == '_uiTextureRotationType']


def test_behavior_fields_read_a_3732_row_that_has_a_page():
    values = read_behavior_fields(patched(old_row()))
    assert values['fixed_pages'] == [{**PAGE, 'texture_rotation': ROTATION}]


def test_a_page_can_be_added_to_a_3732_row():
    raw = patched(patched_3527(item()))          # 3732 row without pages
    out = set_behavior_fields(raw, {'fixed_pages': [PAGE]})
    assert _rotation_bytes(out) == [b'\0']
    assert read_behavior_fields(out)['fixed_pages'] == [{**PAGE, 'texture_rotation': 0}]


def test_a_3732_page_keeps_its_rotation_through_an_edit():
    raw = patched(old_row())
    pages = read_behavior_fields(raw)['fixed_pages']
    pages[0]['left_knowledge'] = 1990999
    out = set_behavior_fields(raw, {'fixed_pages': pages})
    assert _rotation_bytes(out) == [bytes([ROTATION])]
    assert set_behavior_fields(raw, {'fixed_pages': read_behavior_fields(raw)['fixed_pages']}) == raw
    pages[0]['texture_rotation'] = 7
    assert read_behavior_fields(set_behavior_fields(raw, {'fixed_pages': pages}))['fixed_pages'][0]['texture_rotation'] == 7


def test_older_rows_have_no_rotation():
    raw = old_row()                               # 3527 row with a page
    assert read_behavior_fields(raw)['fixed_pages'] == [PAGE]
    assert set_behavior_fields(raw, {'fixed_pages': [{**PAGE, 'texture_rotation': 0}]}) == raw
    with pytest.raises(RecordError, match='no page texture rotation'):
        set_behavior_fields(raw, {'fixed_pages': [{**PAGE, 'texture_rotation': 1}]})


def test_rotation_is_a_closed_u8_member():
    decode_behavior_settings({'fields': {'dynamic_pages': [{**PAGE, 'texture_rotation': 255}]}})
    for bad in ({**PAGE, 'texture_rotation': 256}, {**PAGE, 'texture_rotation': True}, {**PAGE, 'rotation': 0}):
        with pytest.raises(ValueError):
            decode_behavior_settings({'fields': {'fixed_pages': [bad]}})
    assert ItemBehaviorSettings({'fixed_pages': [{**PAGE, 'texture_rotation': 3}]})


def test_behavior_index_reads_3732_rows_with_pages(tmp_path):
    source, rows = _patched_files(lambda raw: patched(with_page(patched_3527(raw))))
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / 'game', source)), read_entry=_read)
    index = load_behavior_index(snapshot)
    assert [{**PAGE, 'texture_rotation': ROTATION}] in index.observed['fixed_pages']


@pytest.mark.real_game
def test_installed_item_rows_read_every_behavior_field():
    """After the fix no shipped ItemInfo row (base or DLC) fails the behavior reader."""
    import os
    from pathlib import Path

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.structured_binary_editor import parse_pabgh_table
    from tools.placement_studio import corpus

    root = Path(os.environ.get('CDMW_GAME_ROOT') or corpus.game_root())
    if not root.is_dir():
        pytest.skip('needs the installed game')
    pairs = {}
    for _package, entry in corpus._iter_archive_entries(root):
        path = corpus.normalize_game_path(entry.path)
        name = path.rsplit('/', 1)[-1]
        if name.startswith('iteminfo.') and name.rsplit('.', 1)[-1] in ('staticinfobody', 'staticinfoheader'):
            stem, part = path.rsplit('.', 1)
            pairs.setdefault(stem, {}).setdefault(part, entry)
    read = lambda entry: bytes(read_archive_entry_data(entry)[0])  # noqa: E731
    failures, pages = [], 0
    for stem, pair in pairs.items():
        body, header = read(pair['staticinfobody']), read(pair['staticinfoheader'])
        for row, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body)):
            try:
                values = read_behavior_fields(body[start:end])
                pages += bool(values['fixed_pages'] or values['dynamic_pages'])
            except (RecordError, ValueError) as exc:
                failures.append((stem, row.row_id, str(exc)))
    assert not failures, failures[:10]
    assert pages > 1000
