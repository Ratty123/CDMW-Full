"""A fresh export must not silently inherit another installed custom item."""

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.domain.new_item.spec import NewItemSpec
from cdmw.services.new_item_mod_base import (
    build_mod_base_snapshot, mod_folder_payloads, read_entry_over_mod_folder,
)
from cdmw.services.new_item_service import NewItemService
from tests.test_new_item_service import TEMPLATE, _read, build_package, synthetic_files
from tests.test_new_item_provenance import current_files


@pytest.mark.parametrize("manager", ["DMM", "CDUMM", "JMM"])
@pytest.mark.parametrize("current", [False, True], ids=["legacy", "current"])
def test_fresh_export_names_and_refuses_inherited_custom_items(tmp_path, manager, current):
    service = NewItemService()
    files = current_files() if current else synthetic_files()
    entries = tuple(parse_archive_pamt(build_package(tmp_path / "game", files)))
    clean = service.build_snapshot(entries, read_entry=_read)
    first = service.plan(NewItemSpec(template_key=TEMPLATE, internal_name="Old_Item",
                                    display_names={"eng": "sfed"}), clean)
    prior_folder = tmp_path / "prior"
    service.export_loose(first, prior_folder, manager=manager, replace_existing=False)
    loaded = service.build_snapshot(entries, read_entry=read_entry_over_mod_folder(
        _read, mod_folder_payloads(prior_folder)))
    second_spec = NewItemSpec(template_key=TEMPLATE, internal_name="New_Item",
                              display_names={"eng": "heahea"})
    inherited = service.plan(second_spec, loaded)
    assert inherited.unselected_source_items == (f"sfed (item {first.spec.item_key})",)
    assert any("sfed" in warning and "Source:" in warning for warning in inherited.warnings)
    destination = tmp_path / "separate"
    with pytest.raises(ValueError, match="sfed.*read the archives again"):
        service.export_loose(inherited, destination, manager=manager, replace_existing=False,
                             create_zip=True)
    assert not destination.exists()
    assert not destination.with_suffix(".zip").exists()

    # Choosing the existing mod explicitly keeps its item and full dependencies.
    selected = build_mod_base_snapshot(service, clean, prior_folder, read_entry=_read)
    combined = service.plan(second_spec, selected)
    assert not combined.unselected_source_items
    service.export_loose(combined, destination, manager=manager, replace_existing=False)
    payloads = mod_folder_payloads(destination)
    assert {path: payload.read_bytes() for path, payload in payloads.items()
            if not path.startswith("meta/")} == dict(combined.loose_files)


def test_clean_separate_plan_contains_only_the_requested_new_item(tmp_path):
    service = NewItemService()
    entries = tuple(parse_archive_pamt(build_package(tmp_path / "game", synthetic_files())))
    clean = service.build_snapshot(entries, read_entry=_read)
    plan = service.plan(NewItemSpec(template_key=TEMPLATE, internal_name="Only_Item",
                                   display_names={"eng": "heahea"}), clean)
    assert not plan.unselected_source_items
    assert not any("source item table already contains" in warning for warning in plan.warnings)
