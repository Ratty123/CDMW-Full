"""Small readers that the October 2026 DLC update's file layout changed."""
import pytest

from cdmw.core.mod_compatibility import decode_paver_build
from cdmw.core.table_catalog import recognized_table_for_path

# Installed 2.4.5 base `meta/0.paver`: version, one `dlc_01` record, four build bytes.
DLC_ERA_PAVER = bytes.fromhex("020004000500" "01000000" "06000000") + b"dlc_01" + bytes.fromhex("04000000" "e61bdda5")


def test_paver_reads_the_version_before_and_after_the_dlc_record_list():
    assert decode_paver_build(bytes.fromhex("02000400050011223344")) == "2.04.05"
    assert decode_paver_build(DLC_ERA_PAVER) == "2.04.05"
    assert decode_paver_build(DLC_ERA_PAVER[:-1]) == ""
    assert decode_paver_build(DLC_ERA_PAVER + b"\0") == ""


@pytest.mark.parametrize("path", [
    "gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody",
    "gamedata/binarystaticinfo__/bin/iteminfo.dlc_01.staticinfobody",
    "gamedata/binary__/client/bin/iteminfo.pabgb",
])
def test_current_and_dlc_table_bodies_are_recognized(path):
    assert recognized_table_for_path(path).source_table == "ItemInfo"


def test_package_group_names_the_dlc_copy_of_a_numbered_folder():
    from pathlib import Path

    from cdmw.domain.archives.filters import archive_entry_package_group
    from cdmw.models import ArchiveEntry

    def entry(folder):
        return ArchiveEntry(path="leveldata/a.pam", pamt_path=Path(f"C:/game/{folder}/0.pamt"),
                            paz_file=Path(f"C:/game/{folder}/0.paz"), offset=0, comp_size=1, orig_size=1,
                            flags=0, paz_index=0)

    assert archive_entry_package_group(entry("0015")) == "0015"
    assert archive_entry_package_group(entry("dlc/dlc_01/0015")) == "dlc_01/0015"


def test_game_root_of_a_dlc_entry_is_the_install_not_the_dlc_folder(tmp_path):
    from pathlib import Path

    from cdmw.domain.archives.filters import archive_entry_game_root
    from cdmw.models import ArchiveEntry

    def entry(folder):
        return ArchiveEntry(path="a.pam", pamt_path=tmp_path / folder / "0.pamt", paz_file=tmp_path / folder / "0.paz",
                            offset=0, comp_size=1, orig_size=1, flags=0, paz_index=0)

    assert archive_entry_game_root(entry("0015")) == tmp_path.resolve()
    assert archive_entry_game_root(entry("dlc/dlc_01/0040")) == tmp_path.resolve()


def test_mesh_editor_outputs_use_the_shared_dlc_aware_root_and_group():
    from pathlib import Path

    source = Path("cdmw/workers/mesh_editor_workers.py").read_text(encoding="utf-8")
    assert ".parent.parent" not in source
    assert "pamt_path).parent.name" not in source


def test_a_truncated_shop_drop_is_a_record_error_not_an_index_error():
    from cdmw.core.new_item_record import RecordError
    from cdmw.core.storeinfo_compact import drop_item

    assert drop_item(b"") == 0
    assert drop_item(bytes(8) + b"\x03" + bytes(54)) == 0  # a sell-only result names no item
    with pytest.raises(RecordError, match="truncated"):
        drop_item(b"\x01\x02\x03")


def test_a_dependency_refusal_names_the_missing_dlc_on_a_game_without_it(tmp_path):
    from types import SimpleNamespace

    from cdmw.services.independent_item_package import dependency_refusal

    def snapshot(root):
        entry = SimpleNamespace(pamt_path=root / "0008" / "0.pamt")
        return SimpleNamespace(iteminfo=SimpleNamespace(payload_entry=entry))

    without = dependency_refusal("Sword", "character/texture/a_d.dds", snapshot(tmp_path))
    assert "incompatible game dependency character/texture/a_d.dds" in without and "no DLC installed" in without
    (tmp_path / "dlc" / "dlc_01").mkdir(parents=True)
    with_dlc = dependency_refusal("Sword", "character/texture/a_d.dds", snapshot(tmp_path))
    assert "DLC" not in with_dlc
