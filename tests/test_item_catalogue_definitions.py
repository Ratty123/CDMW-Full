"""The same owned category witnesses exercise the Python and Full catalogue paths."""
import json
from pathlib import Path

import pytest

from cdmw.core.item_index import ArchiveItemRecord, _classify_archive_asset_catalog_category_group

CASES = json.loads((Path(__file__).resolve().parents[1] / "tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/ItemCatalogueDefinitions.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,slot,category,group", CASES)
def test_definition_beats_translated_and_related_asset_words(name, slot, category, group):
    item = ArchiveItemRecord(1, name, "Bow Helmet Crate", equip_type=slot,
                             localized_names=("boots necklace sword",),
                             model_stems=["horse_armor"], pac_files=["necklace.pac"])
    assert _classify_archive_asset_catalog_category_group(item) == (category, group)


NAMING_CASES = json.loads((Path(__file__).resolve().parents[1] / "tools/dotnet_archive_backend/tests/Cdmw.FullArchive.Tests/ItemCatalogueNamingCases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", NAMING_CASES, ids=[case["name"] for case in NAMING_CASES])
def test_naming_fallback_ignores_translations_and_model_subpart_words(case):
    item = ArchiveItemRecord(1, case["name"], case["display"], localized_names=tuple(case["localized"]),
                             model_stems=list(case["models"]), pac_files=[stem + ".pac" for stem in case["models"]])
    assert _classify_archive_asset_catalog_category_group(item) == (case["category"], case["group"])
