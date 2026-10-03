"""Current game metadata joins, using owned archives and the real readers."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.item_index import (
    _friendly_internal_item_name, build_archive_item_search_index,
    _collect_archive_item_index_sources, _try_build_archive_item_search_index_native,
)
from cdmw.core.item_sources import resolve_item_data_sources, STATIC_TABLE_ROOT
from cdmw.core.paloc_format import LocalizationEntry, encode_paloc
from cdmw.core.papgt_format import PapgtDirectory, serialize_papgt
from cdmw.domain.archives.item_names import compact_item_name
from cdmw.domain.new_item.spec import NewItemSpec
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_snapshot import build_snapshot
from cdmw.ui.new_item.controller import NewItemStudioController
from test_new_item_service import BIN, LOC, NAME_KEY, DESC_KEY, TEMPLATE, MC_ROW_0, MC_ROW_1, synthetic_files, build_package, _read
from tests.new_item_current_fixture_tables import current_recipe_tables
from test_new_item_service import STEM, PAC


def current_files():
    files = {}
    for path, payload in synthetic_files().items():
        if path.startswith(BIN + "/"):
            path = path.replace(BIN, STATIC_TABLE_ROOT).replace(".pabgb", ".staticinfobody").replace(".pabgh", ".staticinfoheader")
        elif "localizationstring_" in path:
            language = path.rsplit("_", 1)[1].removesuffix(".paloc")
            path = f"{LOC}/{language}/item.paloc"
        files[path] = payload
    # A non-item domain must never replace the item's name.
    files[f"{LOC}/eng/quest.paloc"] = encode_paloc([LocalizationEntry(7, NAME_KEY, "Wrong domain")])
    files[f"{LOC}/ara/item.paloc"] = encode_paloc([
        LocalizationEntry(7, NAME_KEY, "سيف الاختبار"), LocalizationEntry(7, DESC_KEY, "سيف"),
    ])
    files.update(current_recipe_tables(TEMPLATE, (MC_ROW_0, MC_ROW_1)))
    return files


@pytest.fixture
def current_entries(tmp_path):
    return parse_archive_pamt(build_package(tmp_path, current_files()))


def test_current_snapshot_and_template_search_share_all_languages(current_entries):
    snapshot = build_snapshot(current_entries, read_entry=_read)
    assert snapshot._template_search_catalogue is not None, "search preparation belongs to snapshot loading"
    assert snapshot.item_display_names()[TEMPLATE] == "Wolf's Fang"
    assert snapshot.languages == ("ara", "eng", "ger")
    controller = SimpleNamespace(snapshot=snapshot)
    for query in ("Wolf's Fang", "Wolfszahn", "سيف الاختبار", str(TEMPLATE)):
        rows = NewItemStudioController.template_options(controller, query, limit=None)
        assert [row[0] for row in rows] == [TEMPLATE]
        assert rows[0][2] == "Wolf's Fang"
