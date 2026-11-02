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
