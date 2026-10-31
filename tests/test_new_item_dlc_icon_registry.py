"""New item icons shaped after a DLC icon, which the DLC registers in its own pathc."""

from cdmw.core.pathc_format import encode_pathc
from tests.test_new_item_compact_dlc import setup
from tests.test_pathc_format import ICON_BLOCKS, build_table, dds_header

DLC_ICON = "ui/texture/icon/itemicon_prefab_cd_phm_00_ring_0012_l.dds"


def test_snapshot_reads_each_installed_dlc_texture_registry(tmp_path):
    registry = build_table(headers=[dds_header(width=256, height=256, tag=15)], entries=[(DLC_ICON, 0, ICON_BLOCKS)])
    meta = tmp_path / "game" / "dlc" / "dlc_01" / "meta"
    meta.mkdir(parents=True)
    (meta / "0.pathc").write_bytes(encode_pathc(registry))
    _service, snapshot = setup(tmp_path, dlc=True)
    assert [table.find(DLC_ICON) is not None for table in snapshot.dlc_pathcs] == [True]
    assert snapshot.pathc is None or snapshot.pathc.find(DLC_ICON) is None


def test_snapshot_without_a_dlc_registry_has_none(tmp_path):
    _service, snapshot = setup(tmp_path, dlc=True)
    assert snapshot.dlc_pathcs == ()
