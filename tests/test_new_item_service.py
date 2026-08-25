"""Gates for the New Item service: snapshot, context, plan, export and install.

The synthetic package below carries one template sword with everything the planner
touches (ItemInfo, StringInfo, the part-prefab table, StoreInfo, ItemGroupInfo,
StatusInfo, EquipTypeInfo, two language tables, the model family files and the
icon), laid out the way the archive writer expects, so a plan can be applied
through the real mutation path and read back.
"""

from __future__ import annotations

import json
from dataclasses import replace
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.archive_extraction import read_archive_entry_data  # noqa: E402
from cdmw.core.archive_format import calculate_pa_checksum, parse_archive_pamt  # noqa: E402
from cdmw.core.item_icon_addition import NewItemIcon  # noqa: E402
from cdmw.core.itemgroupinfo_table import parse_item_group_table  # noqa: E402
from cdmw.core.iteminfo_row import equip_type_key, parse_iteminfo_row  # noqa: E402
from cdmw.core.paloc_format import LocalizationEntry, encode_paloc, parse_paloc  # noqa: E402
from cdmw.core.pappt_format import PartPrefabPart, PartPrefabRecord, PartPrefabTable, encode_pappt, parse_pappt  # noqa: E402
from cdmw.core.prefab_binary import decode_prefab_binary  # noqa: E402
from cdmw.core.storeinfo_table import parse_store_table  # noqa: E402
from cdmw.core.stringinfo_table import build_stringinfo_row, parse_stringinfo, stringinfo_index, stringinfo_key  # noqa: E402
from cdmw.core.structured_binary_editor import parse_pabgh_table  # noqa: E402
from cdmw.domain.archives.mutation import ArchiveAddRequest  # noqa: E402
from cdmw.domain.cancellation import RunCancelled  # noqa: E402
from cdmw.domain.new_item.allocation import localization_keys  # noqa: E402
from cdmw.domain.new_item.spec import (  # noqa: E402
    BuyPriceEdit,
    IconSource,
    ItemGroupsChoice,
    ModelSource,
    NewItemSpec,
    Placement,
    PlacementKind,
    PriceEdit,
    SheathedModel,
    StatEdit,
    UNLIMITED_STOCK,
)
from cdmw.services.archive_mutation_service import ArchiveMutationService  # noqa: E402
from cdmw.services.new_item_planning import ModelFiles, NewItemPlanError  # noqa: E402
from cdmw.services.new_item_service import NewItemInstallRefused, NewItemService  # noqa: E402
from cdmw.services.new_item_snapshot import EFFECT_DONOR_PATH, EFFECT_DONOR_PREFAB, build_context  # noqa: E402
from cdmw.workers.new_item_workers import export_task, install_task, plan_task, snapshot_task  # noqa: E402
from test_iteminfo_row import COPPER, DDD, build_row  # noqa: E402
from test_prefab_binary_edit import _build as build_prefab  # noqa: E402
from test_prefab_component_graft import build_prefab as build_component_prefab  # noqa: E402
from test_storeinfo_table import _entry as stock_entry, _row as store_row  # noqa: E402

TEMPLATE = 1001295
OTHER = 240018
FOLDER = "1_pc/01_phm/weapon/01_onehandweapon"
MODEL_FOLDER = "1_pc/1_phm/weapon/1_onehandweapon"
STEM = "cd_phm_01_sword_0109"
PAC = f"character/model/{MODEL_FOLDER}/{STEM}.pac"
PAC_XML = f"character/modelproperty/{MODEL_FOLDER}/{STEM}.pac_xml"
HKX = f"character/bin__/meshphysics/{MODEL_FOLDER}/{STEM}.hkx"
ICON = f"ui/texture/icon/itemicon_prefab_{STEM}.dds"
ICON_STRING = "ItemIcon_Prefab_CD_PHM_01_Sword_0109"
BIN = "gamedata/binary__/client/bin"
LOC = "gamedata/stringtable/binary__"
NAME_KEY, DESC_KEY = "4300529278648432", "4300529278648433"
MC_ROW_0, MC_ROW_1 = 1013129, 1013130


def _multichange_row(key: int, name: str, item: int) -> bytes:
    """`u32 key, u32 len, name, NUL, 24 bytes, u32 item, tail`: the shape the enhancement rows share."""

    raw = name.encode("ascii")
    return struct.pack("<II", key, len(raw)) + raw + b"\x00" + bytes(24) + struct.pack("<I", item) + bytes(40) + b"\x01"


def _table4(rows: list[tuple[int, bytes]]) -> tuple[bytes, bytes]:
    payload = bytearray()
    header = bytearray(struct.pack("<H", len(rows)))
    for key, raw in rows:
        header += struct.pack("<II", key, len(payload))
        payload += raw
    return bytes(payload), bytes(header)


def _table2(rows: list[bytes]) -> tuple[bytes, bytes]:
    payload = bytearray()
    header = bytearray(struct.pack("<H", len(rows)))
    for raw in rows:
        header += raw[:2] + struct.pack("<I", len(payload))
        payload += raw
    return bytes(payload), bytes(header)


def _named_row(key: int, name: str) -> bytes:
    raw = name.encode("ascii") + b"\x00"
    return struct.pack("<II", key, len(raw)) + raw


def _group_row(key: int, name: str, members: tuple[int, ...]) -> bytes:
    raw = name.encode("ascii")
    digits = b"7284264533"
    out = struct.pack("<H", key) + struct.pack("<I", len(raw)) + raw + b"\x00" + bytes([8, 0x80, 0, 0, 0])
    out += struct.pack("<II", key, len(digits)) + digits
    out += struct.pack("<I", 0)
    out += struct.pack("<I", len(members)) + b"".join(struct.pack("<I", m) for m in members)
    out += struct.pack("<I", 0) + b"\xff\xff" + b"\x02" + struct.pack("<I", 0xEAC5E173) + struct.pack("<I", 0)
    return out


def _fake_dds(width: int = 256, height: int = 256) -> bytes:
    data = bytearray(128)
    data[0:4] = b"DDS "
    struct.pack_into("<I", data, 4, 124)
    struct.pack_into("<I", data, 12, height)
    struct.pack_into("<I", data, 16, width)
    struct.pack_into("<I", data, 28, 1)
    struct.pack_into("<I", data, 76, 32)
    struct.pack_into("<I", data, 80, 0x4)
    data[84:88] = b"DXT5"
    return bytes(data)


def _record(stem: str, part: str) -> PartPrefabRecord:
    return PartPrefabRecord(stem=stem, folder=FOLDER, sockets_path="x.sockets.xml", parts=(PartPrefabPart(part, 1),))


def synthetic_files() -> dict[str, bytes]:
    """Every archive file the planner touches, keyed by game path."""

    template = build_row(
        key=TEMPLATE, string_key="Ziane_OneHandSword", name_key=NAME_KEY, desc_key=DESC_KEY,
        stems=(f"{STEM}_r", "cd_phm_01_sword_0168_r_in_index01", f"{STEM}_l", ICON_STRING),
    )
    # the template's `_multiChangeInfoList`: a u32 count and its two enhancement rows, spliced in
    # right before the three flag bytes that precede the stat block
    parsed = parse_iteminfo_row(template)
    at = parsed.stat_block_offset - 3
    template = template[:at] + struct.pack("<III", 2, MC_ROW_0, MC_ROW_1) + template[at:]
    other = build_row(
        key=OTHER, string_key="Cigar_OneHandSword", name_key="1030869460451440", desc_key="1030869460451441",
        stems=("cd_phm_01_sword_0016_r", "cd_phm_01_sword_0016_l"),
    )
    money = [
        (key, build_row(key=key, string_key=name, equip="", stems=(), levels=[], prices=(), socket_items=(), adds=()))
        for key, name in ((COPPER, "Money_Copper"), (11, "Money_Silver"), (15, "Camp_Weapon_Token"))
    ] + [
        (key, build_row(key=key, string_key=name, equip="", item_type=2501, stems=(), levels=[], prices=(), socket_items=(), adds=()))
        for key, name in ((1002791, "Socket_Gem"), (1002793, "Socket_Gem_III"), (1002812, "Socket_Swift_III"))
    ]
    iteminfo = _table4([(TEMPLATE, template), (OTHER, other)] + money)
    texts = [f"{STEM}_r", f"{STEM}_l", "cd_phm_01_sword_0168_r_in_index01", "cd_phm_01_sword_0016_r", "cd_phm_01_sword_0016_l", ICON_STRING, "rootlevel"]
    stringinfo = _table4([(stringinfo_key(t), build_stringinfo_row(t)) for t in texts])
    pappt = encode_pappt(PartPrefabTable(records=(
        _record("cd_phm_01_sword_0016_r", "CD_MainWeapon_Sword_R"), _record("cd_phm_01_sword_0016_l", "CD_MainWeapon_Sword_L"),
        _record(f"{STEM}_r", "CD_MainWeapon_Sword_R"), _record(f"{STEM}_l", "CD_MainWeapon_Sword_L"),
        _record("cd_phm_01_sword_0168_r_in_index01", "CD_MainWeapon_Sword_IN_R"),
    )))
    stores = _table2([
        # Cigar's line wants the knowledge of item 15 (a collection prop stand-in) before it sells, like 1,856 shipped lines
        store_row((stock_entry(OTHER, 0, option=struct.pack("<IBQ", 15, 1, 0x7A601F54819F3FB4)), stock_entry(50001, 1)), name="Store_Camp_Equipment", key=6600),
        store_row((stock_entry(TEMPLATE, 0),), name="Store_Pai_BlackMarket", key=2003),
    ])
    groups = _table2([
        _group_row(17010, "ItemGroup_Equip_Weapon_OneHandSword", (OTHER, TEMPLATE, 13800)),
        _group_row(17011, "ItemGroup_Equip", (TEMPLATE,)),
        _group_row(17012, "ItemGroup_Junk", (OTHER,)),
    ])
    multichange = _table4([
        (MC_ROW_0, _multichange_row(MC_ROW_0, "Ziane_OneHandSword_0", TEMPLATE)),
        (MC_ROW_1, _multichange_row(MC_ROW_1, "Ziane_OneHandSword_1", TEMPLATE)),
        (1013200, _multichange_row(1013200, "Cigar_OneHandSword_0", OTHER)),
    ])
    statusinfo = _table4([(DDD, _named_row(DDD, "DDD")), (1000003, _named_row(1000003, "DPV")), (1000007, _named_row(1000007, "CriticalRate"))])
    equiptypes = _table4([(equip_type_key("OneHandSword"), _named_row(equip_type_key("OneHandSword"), "OneHandSword"))])
    eng = encode_paloc([
        LocalizationEntry(7, "1030869460451440", "Cigar"), LocalizationEntry(9, "other_key", "Other."),
        LocalizationEntry(7, NAME_KEY, "Wolf's Fang"), LocalizationEntry(8, DESC_KEY, "Ziane's own sword."),
    ])
    ger = encode_paloc([
        LocalizationEntry(7, "1030869460451440", "Zigarre"),
        LocalizationEntry(7, NAME_KEY, "Wolfszahn"), LocalizationEntry(8, DESC_KEY, "Zianes eigenes Schwert."),
    ])
    sheath_pac = f"character/model/{MODEL_FOLDER}/cd_phm_01_sword_0168_in.pac"
    other_pac = f"character/model/{MODEL_FOLDER}/cd_phm_01_sword_0016.pac"
    return {
        f"{BIN}/iteminfo.pabgb": iteminfo[0], f"{BIN}/iteminfo.pabgh": iteminfo[1],
        f"{BIN}/stringinfo.pabgb": stringinfo[0], f"{BIN}/stringinfo.pabgh": stringinfo[1],
        f"{BIN}/storeinfo.pabgb": stores[0], f"{BIN}/storeinfo.pabgh": stores[1],
        f"{BIN}/itemgroupinfo.pabgb": groups[0], f"{BIN}/itemgroupinfo.pabgh": groups[1],
        f"{BIN}/statusinfo.pabgb": statusinfo[0], f"{BIN}/statusinfo.pabgh": statusinfo[1],
        f"{BIN}/multichangeinfo.pabgb": multichange[0], f"{BIN}/multichangeinfo.pabgh": multichange[1],
        f"{BIN}/equiptypeinfo.pabgb": equiptypes[0], f"{BIN}/equiptypeinfo.pabgh": equiptypes[1],
        f"{LOC}/localizationstring_eng.paloc": eng, f"{LOC}/localizationstring_ger.paloc": ger,
        "character/bin__/partprefabtable.pappt": pappt,
        # the family's own prefabs are shaped like the shipped ones (a SkinnedMeshComponent in
        # `_components`), so an effect can be grafted into them; the others keep the older shape
        f"character/bin__/prefab/{FOLDER}/{STEM}_r.prefab": build_component_prefab(component="SkinnedMeshComponent", member_kind="pointer", value=PAC, pointee_type="ResourceReferencePath_SkinnedMesh"),
        f"character/bin__/prefab/{FOLDER}/{STEM}_l.prefab": build_component_prefab(component="SkinnedMeshComponent", member_kind="pointer", value=PAC, pointee_type="ResourceReferencePath_SkinnedMesh"),
        EFFECT_DONOR_PREFAB: build_component_prefab(component="EffectComponent", member_kind="object", value=EFFECT_DONOR_PATH, with_transform=True, pointee_type="EffectDataReferencePath"),
        "effect/binary__/releasebin/fx_test_fire.pae": b"PAE fire",
        "effect/binary__/releasebin/fx_test_ice.pae": b"PAE ice",
        "ui/xml/texture/cd_item_icon.xml": (b"\xef\xbb\xbf" + b'<Texture Name="itemicon_empty"\tFilename="UI/texture/icon/ItemIcon_Heavy_Silver_Pack.dds" Type="Image" GetRect="0,0,256,256"/>\r\n'
                                            + b'<Texture Name="ItemIcon_Prefab_cd_phm_01_sword_0109"\tFilename="UI/texture/icon/ItemIcon_Prefab_cd_phm_01_sword_0109.dds" Type="Image" GetRect="0,0,256,256"/>\r\n\r\n'),
        f"character/bin__/prefab/{FOLDER}/cd_phm_01_sword_0168_r_in_index01.prefab": build_component_prefab(
            component="SkinnedMeshComponent",
            member_kind="pointer",
            value=sheath_pac,
            pointee_type="ResourceReferencePath_SkinnedMesh",
        ),
        f"character/bin__/prefab/{FOLDER}/cd_phm_01_sword_0016_r.prefab": build_prefab(other_pac),
        f"character/bin__/prefab/{FOLDER}/cd_phm_01_sword_0016_l.prefab": build_prefab(other_pac),
        PAC: b"PAC template mesh", sheath_pac: b"PAC sheath", other_pac: b"PAC other",
        PAC_XML: b"<pac_xml><texture>cd_phm_01_sword_0109_d.dds</texture><texture>shared_metal_n.dds</texture></pac_xml>",
        HKX: b"HKX physics",
        f"character/texture/1_pc/{STEM}_d.dds": _fake_dds(4, 4),
        ICON: _fake_dds(),
        "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_0016.dds": _fake_dds(),
    }


def _flat_name(name: str) -> bytes:
    raw = name.encode("utf-8")
    return struct.pack("<IB", 0xFFFFFFFF, len(raw)) + raw


def build_package(root: Path, files: dict[str, bytes]) -> Path:
    """Write meta/0.papgt and 0009/{0.pamt,0.paz,1.paz} holding `files`; return the pamt path."""

    group = root / "0009"
    meta = root / "meta"
    group.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)
    by_folder: dict[str, list[str]] = {}
    for path in files:
        folder, _, name = path.rpartition("/")
        by_folder.setdefault(folder, []).append(name)
    folders = sorted(by_folder)
    paz0 = bytearray()
    paz1 = b"\0" * 16
    dir_block = bytearray()
    dir_offsets = {}
    for folder in folders:
        dir_offsets[folder] = len(dir_block)
        dir_block += _flat_name(folder)
    name_block = bytearray()
    file_records: list[bytes] = []
    folder_records: list[bytes] = []
    for folder in folders:
        start = len(file_records)
        names = sorted(by_folder[folder], key=lambda n: n.encode("utf-8"))
        for name in names:
            payload = files[f"{folder}/{name}"]
            offset = len(paz0)
            paz0 += payload
            paz0 += b"\0" * ((-len(paz0)) % 16)
            name_offset = len(name_block)
            name_block += _flat_name(name)
            file_records.append(struct.pack("<IIIIHH", name_offset, offset, len(payload), len(payload), 0, 0))
        folder_records.append(struct.pack("<IIII", calculate_pa_checksum(folder), dir_offsets[folder], start, len(names)))
    (group / "0.paz").write_bytes(bytes(paz0))
    (group / "1.paz").write_bytes(paz1)
    pamt = bytearray()
    pamt += struct.pack("<III", 0, 2, 0x610D3AB2)
    pamt += struct.pack("<III", 0, calculate_pa_checksum(bytes(paz0)), len(paz0))
    pamt += struct.pack("<III", 1, calculate_pa_checksum(paz1), len(paz1))
    pamt += struct.pack("<I", len(dir_block)) + dir_block
    pamt += struct.pack("<I", len(name_block)) + name_block
    pamt += struct.pack("<I", len(folder_records)) + b"".join(folder_records)
    pamt += struct.pack("<I", len(file_records)) + b"".join(file_records)
    pamt_crc = calculate_pa_checksum(bytes(pamt[12:]))
    struct.pack_into("<I", pamt, 0, pamt_crc)
    pamt_path = group / "0.pamt"
    pamt_path.write_bytes(bytes(pamt))
    # the mount list, in the shape the game ships: a header, one record per directory,
    # the size of the string table, and the names the records point into
    table = b"0009" + bytes(1)
    papgt = bytearray(12)
    papgt += struct.pack("<III", 0x007FFF00, 0, pamt_crc)
    papgt += struct.pack("<I", len(table)) + table
    struct.pack_into("<I", papgt, 4, calculate_pa_checksum(bytes(papgt[12:])))
    (meta / "0.papgt").write_bytes(bytes(papgt))
    return pamt_path


def _read(entry) -> bytes:
    return read_archive_entry_data(entry)[0]


class _PackageCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.pamt_path = build_package(self.root, synthetic_files())
        self.entries = parse_archive_pamt(self.pamt_path)
        self.service = NewItemService()
        self.snapshot = self.service.build_snapshot(self.entries, read_entry=_read)
        self._backup_patch = patch("cdmw.core.archive_patching.ARCHIVE_PATCH_BACKUP_ROOT", self.root / "backups")
        self._backup_patch.start()

    def tearDown(self) -> None:
        self._backup_patch.stop()
        self._temp.cleanup()

    def reread(self) -> dict[str, bytes]:
        return {e.path.replace("\\", "/"): _read(e) for e in parse_archive_pamt(self.pamt_path)}


class SnapshotTests(_PackageCase):
    def test_snapshot_and_context_describe_the_template(self) -> None:
        snap = self.snapshot
        self.assertEqual(sorted(snap.rows), [COPPER, 11, 15, OTHER, TEMPLATE, 1002791, 1002793, 1002812])
        self.assertEqual(snap.keys_by_name["Ziane_OneHandSword"], TEMPLATE)
        self.assertEqual(snap.languages, ("eng", "ger"))
        self.assertEqual([s.name for s in snap.stores], ["Store_Camp_Equipment", "Store_Pai_BlackMarket"])
        self.assertIn(STEM, snap.model_stems)
        family = snap.family(TEMPLATE)
        self.assertEqual(family.model_stem, STEM)
        self.assertEqual(family.owned_stems, (f"{STEM}_r", f"{STEM}_l"))
        self.assertEqual(family.borrowed_stems, ("cd_phm_01_sword_0168_r_in_index01",))
        self.assertEqual(family.missing_files, ())
        context = build_context(snap, TEMPLATE)
        self.assertEqual(context.template.equip_type_name, "OneHandSword")
        self.assertEqual(context.template.model_stem, STEM)
        self.assertEqual(context.template.item_group_keys, (17010, 17011))
        self.assertEqual(context.template.levels[0].status_keys, (DDD,))
        self.assertEqual(context.store_stock_names["Store_Camp_Equipment"], frozenset({"Cigar_OneHandSword"}))
        self.assertIn(NAME_KEY, context.localization_keys)
        self.assertTrue(context.store_insert_supported and context.stat_shape_edits_supported)
        self.assertEqual(snapshot_task(self.entries, service=self.service, read_entry=_read)(lambda _m: None, None).rows.keys(), snap.rows.keys())

    def test_snapshot_reuses_the_archive_browsers_published_indexes(self) -> None:
        path_index: dict[str, tuple] = {}
        basename_index: dict[str, tuple] = {}
        extension_index: dict[str, tuple] = {}
        for entry in self.entries:
            path = str(entry.path).replace("\\", "/").strip("/").lower()
            path_index[path] = (*path_index.get(path, ()), entry)
            basename = path.rsplit("/", 1)[-1]
            basename_index[basename] = (*basename_index.get(basename, ()), entry)
            extension = Path(path).suffix.lower()
            extension_index[extension] = (*extension_index.get(extension, ()), entry)

        snapshot = self.service.build_snapshot(
            self.entries,
            read_entry=_read,
            entries_by_normalized_path=path_index,
            entries_by_basename=basename_index,
            entries_by_extension=extension_index,
        )

        reused_path_index, reused_basename_index = snapshot.archive_index_maps()
        self.assertIs(reused_path_index, path_index)
        self.assertIs(reused_basename_index, basename_index)
        self.assertEqual(snapshot.row(TEMPLATE).string_key, self.snapshot.row(TEMPLATE).string_key)
        self.assertEqual(snapshot.model_stems, self.snapshot.model_stems)
        self.assertEqual(snapshot.effect_stems, self.snapshot.effect_stems)


    def test_the_validation_context_is_built_once_per_template(self) -> None:
        """The studio validates on every edit, and the context's frozensets span the
        whole snapshot, so it is kept per template on the read-only snapshot."""

        first = build_context(self.snapshot, TEMPLATE)
        self.assertIs(build_context(self.snapshot, TEMPLATE), first)
        other = build_context(self.snapshot, OTHER)
        self.assertIsNot(other, first)
        self.assertEqual(other.template.key, OTHER)
        self.assertEqual(self.snapshot.item_names()[TEMPLATE], "Ziane_OneHandSword")
        self.assertIs(self.snapshot.item_names(), self.snapshot.item_names())


class PlanTests(_PackageCase):
    def _spec(self, **changes) -> NewItemSpec:
        base = dict(
            template_key=TEMPLATE, internal_name="Ziane_Clone_OneHandSword",
            display_names={"eng": "Wolf's Fang (Clone)", "ger": "Wolfszahn (Klon)"},
            descriptions={"eng": "A cloned sword."},
        )
        base.update(changes)
        return NewItemSpec(**base)

    def test_template_model_plan_touches_only_tables(self) -> None:
        plan = self.service.plan(self._spec(
            stat_edits=(StatEdit(0, DDD, 20000), StatEdit(0, 1000007, 500), StatEdit(2, DDD, 30000)),
            buy_price_edits=(BuyPriceEdit(0, COPPER, 999),), price_edits=(PriceEdit(11, 250),), max_stack_count=3,
            placement=Placement(PlacementKind.SWAP, "Store_Camp_Equipment", "Cigar_OneHandSword"),
        ), self.snapshot)
        self.assertEqual(plan.additions, ())
        self.assertEqual(plan.spec.item_key, 1990000)
        self.assertEqual((plan.spec.name_key, plan.spec.desc_key), ("8546984919040112", "8546984919040113"))
        self.assertIsNone(plan.spec.stem)
        touched = {request.entry.path.replace("\\", "/") for request in plan.patches}
        self.assertEqual(touched, {
            f"{BIN}/iteminfo.pabgb", f"{BIN}/iteminfo.pabgh", f"{BIN}/itemgroupinfo.pabgb", f"{BIN}/itemgroupinfo.pabgh",
            f"{BIN}/storeinfo.pabgb", f"{BIN}/storeinfo.pabgh", f"{LOC}/localizationstring_eng.paloc", f"{LOC}/localizationstring_ger.paloc",
        }, "no StringInfo, no pappt, no files: the template model and icon are kept")
        files = dict(plan.loose_files)
        rows = parse_pabgh_table(files[f"{BIN}/iteminfo.pabgh"], payload=files[f"{BIN}/iteminfo.pabgb"]).row_spans(len(files[f"{BIN}/iteminfo.pabgb"]))
        self.assertEqual(len(rows), len(self.snapshot.rows) + 1)
        raw = files[f"{BIN}/iteminfo.pabgb"][rows[-1][1]:rows[-1][2]]
        item = parse_iteminfo_row(raw, item_keys=set(self.snapshot.rows) | {1990000})
        self.assertEqual((item.key, item.string_key, item.name_key, item.desc_key), (1990000, "Ziane_Clone_OneHandSword", "8546984919040112", "8546984919040113"))
        self.assertEqual(item.max_stack_count, 3)
        self.assertEqual(item.stat(0, DDD).value, 20000)
        self.assertEqual(item.stat(0, 1000007).value, 500)
        self.assertEqual(item.stat(2, DDD).value, 30000, "a third level was added by copying the second")
        self.assertEqual(item.enchant_count, 3)
        self.assertEqual([p.price for p in item.enchant_levels[0].buy_prices if p.item_key == COPPER], [999])
        self.assertEqual([p.price for p in item.price_list if p.item_key == 11], [250])
        # the template row is untouched, and the model hashes still name the template's parts
        template = parse_iteminfo_row(files[f"{BIN}/iteminfo.pabgb"][rows[0][1]:rows[0][2]])
        self.assertEqual(template.raw, self.snapshot.row(TEMPLATE).raw)
        self.assertIn(struct.pack("<I", stringinfo_key(f"{STEM}_r")), raw)
        stores = {s.name: s for s in parse_store_table(files[f"{BIN}/storeinfo.pabgb"], files[f"{BIN}/storeinfo.pabgh"])}
        self.assertEqual([e.item_key for e in stores["Store_Camp_Equipment"].entries], [1990000, 50001])
        self.assertIsNone(stores["Store_Camp_Equipment"].entries[0].requirement_item_key, "the line's unlock requirement is dropped by default")
        self.assertFalse(plan.manifest["store"]["requirement_kept"])
        self.assertTrue(any("sells freely" in line for line in plan.summary_lines), plan.summary_lines)
        kept = self.service.plan(self._spec(placement=Placement(PlacementKind.SWAP, "Store_Camp_Equipment", "Cigar_OneHandSword", keep_requirement=True)), self.snapshot)
        kept_files = dict(kept.loose_files)
        kept_store = {s.name: s for s in parse_store_table(kept_files[f"{BIN}/storeinfo.pabgb"], kept_files[f"{BIN}/storeinfo.pabgh"])}["Store_Camp_Equipment"]
        self.assertEqual(kept_store.entries[0].requirement_item_key, self.snapshot.store("Store_Camp_Equipment").entries[0].requirement_item_key)
        self.assertTrue(any("keeps its unlock requirement" in w for w in kept.warnings), kept.warnings)
        self.assertEqual(stores["Store_Camp_Equipment"].entries[0].count, self.snapshot.store("Store_Camp_Equipment").entries[0].count, "no stock count asked: the line keeps its own")
        self.assertIsNone(plan.manifest["store"]["stock_count"])
        endless = self.service.plan(self._spec(placement=Placement(PlacementKind.SWAP, "Store_Camp_Equipment", "Cigar_OneHandSword", stock_count=UNLIMITED_STOCK)), self.snapshot)
        endless_files = dict(endless.loose_files)
        endless_store = {s.name: s for s in parse_store_table(endless_files[f"{BIN}/storeinfo.pabgb"], endless_files[f"{BIN}/storeinfo.pabgh"])}["Store_Camp_Equipment"]
        self.assertEqual(endless_store.entries[0].count, UNLIMITED_STOCK)
        self.assertEqual(endless.manifest["store"]["stock_count"], UNLIMITED_STOCK)
        self.assertTrue(any("unlimited stock" in line for line in endless.summary_lines), endless.summary_lines)
        groups = parse_item_group_table(files[f"{BIN}/itemgroupinfo.pabgb"], files[f"{BIN}/itemgroupinfo.pabgh"])
        self.assertEqual([g.members for g in groups], [(OTHER, TEMPLATE, 1990000, 13800), (TEMPLATE, 1990000), (OTHER,)])
        eng = parse_paloc(files[f"{LOC}/localizationstring_eng.paloc"]).index()
        ger = parse_paloc(files[f"{LOC}/localizationstring_ger.paloc"]).index()
        self.assertEqual((eng["8546984919040112"].text, eng["8546984919040112"].category), ("Wolf's Fang (Clone)", 7))
        self.assertEqual(eng["8546984919040113"].text, "A cloned sword.")
        self.assertEqual(ger["8546984919040112"].text, "Wolfszahn (Klon)")
        self.assertEqual(ger["8546984919040113"].text, "A cloned sword.", "no German description: English fallback")
        self.assertTrue(any("unproven" in w for w in plan.warnings), plan.warnings)
        self.assertEqual(plan.manifest["item_groups"], ["ItemGroup_Equip_Weapon_OneHandSword", "ItemGroup_Equip"])
        self.assertEqual(plan.manifest["store"]["old_item"], "Cigar_OneHandSword")
        self.assertTrue(any("ItemInfo: row 1990000" in line for line in plan.summary_lines))

    def test_imported_model_and_generated_icon_add_a_family(self) -> None:
        model = ModelFiles(
            pac_data=b"PAC imported mesh",
            side_files={PAC_XML: b"<pac_xml><texture>cd_phm_01_sword_0109_d.dds</texture><texture>extra_n.dds</texture></pac_xml>",
                        f"character/texture/1_pc/{STEM}_d.dds": b"DDS diffuse", "character/texture/1_pc/extra_n.dds": b"DDS extra"},
        )
        spec = self._spec(model_source=ModelSource.IMPORTED, icon=IconSource.GENERATED, item_groups=ItemGroupsChoice.EXPLICIT, explicit_item_groups=(17012,))
        allocated = self.service.allocate(spec, self.snapshot)
        self.assertEqual(allocated.stem, "cd_phm_01_sword_9109")
        icon = NewItemIcon(
            icon_string="ItemIcon_Prefab_cd_phm_01_sword_9109", icon_hash=stringinfo_key("ItemIcon_Prefab_cd_phm_01_sword_9109"),
            target_path="ui/texture/icon/itemicon_prefab_cd_phm_01_sword_9109.dds", payload_data=_fake_dds(),
            add_request=ArchiveAddRequest.from_template(self.snapshot.entry(ICON), "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_9109.dds", _fake_dds()),
            build=None,
        )
        plan = self.service.plan(spec, self.snapshot, model=model, icon=icon)
        new_stem = "cd_phm_01_sword_9109"
        added = {request.path: request for request in plan.additions}
        self.assertEqual(set(added), {
            f"character/model/{MODEL_FOLDER}/{new_stem}.pac", f"character/modelproperty/{MODEL_FOLDER}/{new_stem}.pac_xml",
            # no mesh physics: the template's binds cloth to the template's own vertices
            f"character/bin__/prefab/{FOLDER}/{new_stem}_r.prefab", f"character/bin__/prefab/{FOLDER}/{new_stem}_l.prefab",
            # the sheathed (_IN) part of the item's own: the borrowed scabbard record cloned, its prefab re-pathed to the imported mesh
            f"character/bin__/prefab/{FOLDER}/{new_stem}_r_in.prefab",
            f"character/texture/1_pc/{new_stem}_d.dds", f"character/texture/1_pc/{new_stem}_extra_n.dds",
            "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_9109.dds",
        })
        sheathed = decode_prefab_binary(added[f"character/bin__/prefab/{FOLDER}/{new_stem}_r_in.prefab"].payload_data)
        self.assertEqual([s.text for s in sheathed.resource_strings()], [f"character/model/{MODEL_FOLDER}/{new_stem}.pac"], "the sheathed part draws the imported mesh, not the borrowed scabbard")
        self.assertEqual(plan.manifest["sheathed_records"], {"cd_phm_01_sword_0168_r_in_index01": f"{new_stem}_r_in"})
        self.assertEqual(plan.manifest["sheathed_model"], "own_model")
        self.assertEqual(added[f"character/model/{MODEL_FOLDER}/{new_stem}.pac"].payload_data, b"PAC imported mesh")
        self.assertEqual(
            added[f"character/modelproperty/{MODEL_FOLDER}/{new_stem}.pac_xml"].payload_data,
            b"<pac_xml><texture>cd_phm_01_sword_9109_d.dds</texture><texture>cd_phm_01_sword_9109_extra_n.dds</texture></pac_xml>",
        )
        for hand in ("r", "l"):
            prefab = decode_prefab_binary(added[f"character/bin__/prefab/{FOLDER}/{new_stem}_{hand}.prefab"].payload_data)
            self.assertEqual([s.text for s in prefab.resource_strings()], [f"character/model/{MODEL_FOLDER}/{new_stem}.pac"])
        self.assertTrue(all(request.pamt_path == self.pamt_path for request in plan.additions))
        files = dict(plan.loose_files)
        strings = stringinfo_index(parse_stringinfo(files[f"{BIN}/stringinfo.pabgb"], files[f"{BIN}/stringinfo.pabgh"]))
        for text in (f"{new_stem}_r", f"{new_stem}_l", f"{new_stem}_r_in", "ItemIcon_Prefab_cd_phm_01_sword_9109"):
            self.assertEqual(strings[stringinfo_key(text)], text)
        pappt = parse_pappt(files["character/bin__/partprefabtable.pappt"])
        stems = [r.stem for r in pappt.records]
        self.assertEqual(stems.index(f"{new_stem}_r"), stems.index(f"{STEM}_r") + 1)
        self.assertEqual(pappt.find(f"{new_stem}_l").parts, pappt.find(f"{STEM}_l").parts)
        self.assertEqual(pappt.find(f"{new_stem}_r_in").parts, pappt.find("cd_phm_01_sword_0168_r_in_index01").parts, "the sheathed record keeps its part slot")
        rows = parse_pabgh_table(files[f"{BIN}/iteminfo.pabgh"], payload=files[f"{BIN}/iteminfo.pabgb"]).row_spans(len(files[f"{BIN}/iteminfo.pabgb"]))
        raw = files[f"{BIN}/iteminfo.pabgb"][rows[-1][1]:rows[-1][2]]
        for old, new in ((f"{STEM}_r", f"{new_stem}_r"), (f"{STEM}_l", f"{new_stem}_l"), (ICON_STRING, "ItemIcon_Prefab_cd_phm_01_sword_9109"), ("cd_phm_01_sword_0168_r_in_index01", f"{new_stem}_r_in")):
            self.assertNotIn(struct.pack("<I", stringinfo_key(old)), raw)
            self.assertIn(struct.pack("<I", stringinfo_key(new)), raw)
        # asked to keep the template's, the borrowed sheath stays borrowed and no _in prefab is written
        kept = self.service.plan(self._spec(model_source=ModelSource.IMPORTED, icon=IconSource.GENERATED, item_groups=ItemGroupsChoice.EXPLICIT, explicit_item_groups=(17012,), sheathed_model=SheathedModel.TEMPLATE), self.snapshot, model=model, icon=icon)
        self.assertNotIn(f"character/bin__/prefab/{FOLDER}/{new_stem}_r_in.prefab", {r.path for r in kept.additions})
        kept_files = dict(kept.loose_files)
        kept_rows = parse_pabgh_table(kept_files[f"{BIN}/iteminfo.pabgh"], payload=kept_files[f"{BIN}/iteminfo.pabgb"]).row_spans(len(kept_files[f"{BIN}/iteminfo.pabgb"]))
        self.assertIn(struct.pack("<I", stringinfo_key("cd_phm_01_sword_0168_r_in_index01")), kept_files[f"{BIN}/iteminfo.pabgb"][kept_rows[-1][1]:kept_rows[-1][2]], "the borrowed sheath stays borrowed")
        self.assertEqual(kept.manifest["sheathed_records"], {})
        groups = parse_item_group_table(files[f"{BIN}/itemgroupinfo.pabgb"], files[f"{BIN}/itemgroupinfo.pabgh"])
        self.assertEqual([g.members for g in groups], [(OTHER, TEMPLATE, 13800), (TEMPLATE,), (OTHER, 1990000)])
        self.assertEqual(plan.new_paths, tuple(added))
        self.assertEqual(plan.manifest["pappt_records"], {f"{STEM}_r": f"{new_stem}_r", f"{STEM}_l": f"{new_stem}_l"})
        self.assertEqual(plan.manifest["icon"]["path"], "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_9109.dds")
        # the UI's icon registry gets the new name, shaped like the template's line
        self.assertTrue(plan.manifest["icon"]["registered"])
        registry = files["ui/xml/texture/cd_item_icon.xml"]
        self.assertIn(b'<Texture Name="ItemIcon_Prefab_cd_phm_01_sword_9109"\tFilename="UI/texture/icon/ItemIcon_Prefab_cd_phm_01_sword_9109.dds" Type="Image" GetRect="0,0,256,256"/>\r\n', registry)
        self.assertTrue(registry.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(any("icon registry" in line for line in plan.summary_lines))

    def test_an_imported_model_does_not_inherit_the_template_s_physics(self) -> None:
        """A template's mesh physics binds cloth and collision to the template's own
        vertices. Copied onto a model of one's own it drives whichever vertices those
        indices land on, which is how an imported hammer's handle ended up swinging like
        cloth. The game finds the file by the stem, so leaving it out leaves the item
        without physics; the choice is on the Model step for a template whose cloth is
        wanted."""

        spec = NewItemSpec(
            template_key=TEMPLATE, internal_name="Ziane_Clone_OneHandSword", display_names={"eng": "X"},
            model_source=ModelSource.IMPORTED,
        )
        plan = self.service.plan(self.service.allocate(spec, self.snapshot), self.snapshot, model=ModelFiles(pac_data=b"PAC"))
        physics = [path for path in plan.new_paths if path.lower().endswith(".hkx")]
        self.assertEqual(physics, [], "the template's physics is not copied by default")
        self.assertTrue(any("mesh physics" in line for line in plan.summary_lines), plan.summary_lines)

        wanted = self.service.plan(
            self.service.allocate(replace(spec, keep_template_physics=True), self.snapshot),
            self.snapshot, model=ModelFiles(pac_data=b"PAC"),
        )
        self.assertTrue([path for path in wanted.new_paths if path.lower().endswith(".hkx")], "asked for, it is copied")

        # a template-model item keeps it: the mesh is the template's own, so its physics fits
        template_model = self.service.plan(
            self.service.allocate(replace(spec, model_source=ModelSource.TEMPLATE), self.snapshot),
            self.snapshot,
        )
        self.assertEqual([path for path in template_model.new_paths if path.lower().endswith(".hkx")], [])

    def test_own_enhancement_rows_are_cloned_and_repointed(self) -> None:
        from cdmw.core.multichangeinfo_table import find_multichange_keys, parse_multichange_table
        from cdmw.domain.new_item.spec import EnhancementRows

        shared = self.service.plan(self._spec(), self.snapshot)
        self.assertNotIn(f"{BIN}/multichangeinfo.pabgb", shared.loose_files)
        template_keys = find_multichange_keys(self.snapshot.row(TEMPLATE), self.snapshot.multichange_rows)
        self.assertEqual(template_keys, (MC_ROW_0, MC_ROW_1))
        plan = self.service.plan(self._spec(enhancement=EnhancementRows.OWN), self.snapshot)
        files = dict(plan.loose_files)
        rows = {r.key: r for r in parse_multichange_table(files[f"{BIN}/multichangeinfo.pabgb"], files[f"{BIN}/multichangeinfo.pabgh"])}
        self.assertEqual(len(rows), 5)
        new_keys = tuple(plan.manifest["enhancement_rows"].values())
        self.assertEqual(new_keys, (1990000, 1990001))
        self.assertEqual([rows[k].name for k in new_keys], ["Ziane_Clone_OneHandSword_0", "Ziane_Clone_OneHandSword_1"])
        self.assertEqual([rows[k].item_key for k in new_keys], [1990000, 1990000])
        self.assertEqual(rows[new_keys[0]].raw[rows[new_keys[0]].name_end:], rows[MC_ROW_0].raw[rows[MC_ROW_0].name_end:].replace(struct.pack("<I", TEMPLATE), struct.pack("<I", 1990000), 1))
        spans = parse_pabgh_table(files[f"{BIN}/iteminfo.pabgh"], payload=files[f"{BIN}/iteminfo.pabgb"]).row_spans(len(files[f"{BIN}/iteminfo.pabgb"]))
        clone = parse_iteminfo_row(files[f"{BIN}/iteminfo.pabgb"][spans[-1][1]:spans[-1][2]], item_keys=set(self.snapshot.rows) | {1990000})
        self.assertEqual(find_multichange_keys(clone, rows), new_keys, "the clone's list points at its own rows")
        self.assertTrue(any("enhancement row" in w for w in plan.warnings))
        self.assertTrue(any("MultiChangeInfo" in line for line in plan.summary_lines))

    def test_socket_items_replace_the_templates_perks(self) -> None:
        context = build_context(self.snapshot, TEMPLATE)
        self.assertEqual(context.template.socket_items, (1002791,))
        self.assertEqual(context.socket_item_keys, frozenset({1002791}))
        plan = self.service.plan(self._spec(socket_items=(1002793, 1002812, 1002791, 1002793)), self.snapshot)
        files = dict(plan.loose_files)
        spans = parse_pabgh_table(files[f"{BIN}/iteminfo.pabgh"], payload=files[f"{BIN}/iteminfo.pabgb"]).row_spans(len(files[f"{BIN}/iteminfo.pabgb"]))
        clone = parse_iteminfo_row(files[f"{BIN}/iteminfo.pabgb"][spans[-1][1]:spans[-1][2]], item_keys=set(self.snapshot.rows) | {1990000})
        self.assertEqual(clone.socket_items, (1002793, 1002812, 1002791, 1002793))
        self.assertEqual([(s.status_key, s.value) for s in clone.enchant_levels[0].stats], [(s.status_key, s.value) for s in self.snapshot.row(TEMPLATE).enchant_levels[0].stats], "the ladder is untouched")
        self.assertEqual(plan.manifest["socket_items"], [1002793, 1002812, 1002791, 1002793])
        self.assertTrue(any("socket items: 4" in line for line in plan.summary_lines), plan.summary_lines)
        self.assertFalse(any("socket" in w for w in plan.warnings), "four is the shipped maximum")
        # the template has one socket slot; four gems need four, priced like the shipped progression
        self.assertEqual(clone.add_socket_materials, ((COPPER, 500, 0), (COPPER, 1000, 0), (COPPER, 2000, 0), (COPPER, 3000, 0)))
        self.assertEqual(plan.manifest["socket_slots"], [[COPPER, 500, 0], [COPPER, 1000, 0], [COPPER, 2000, 0], [COPPER, 3000, 0]])
        self.assertTrue(any("socket slots: grown from 1 to 4" in line for line in plan.summary_lines))
        same = self.service.plan(self._spec(socket_items=(1002791,)), self.snapshot)
        self.assertNotIn("socket_items", same.manifest, "the template's own list changes nothing")
        five = self.service.plan(self._spec(socket_items=(1002791,) * 5), self.snapshot)
        self.assertTrue(any("5 socket items" in w for w in five.warnings), five.warnings)
        # a gem nothing in the game carries has no evidence an equipment row may hold it;
        # 108 of the 190 gems in the shipped archives are in that position
        self.assertTrue(any("carried by no shipped item" in w for w in plan.warnings), plan.warnings)
        self.assertFalse(any("carried by no shipped item" in w for w in same.warnings), "the template's own perk is carried")
        six = self.service.plan(self._spec(socket_items=(1002791,) * 6), self.snapshot)
        self.assertTrue(any("6 socket slots" in w for w in six.warnings), six.warnings)
        with self.assertRaises(NewItemPlanError):
            self.service.plan(self._spec(socket_items=(424242,)), self.snapshot)

    def test_a_stat_written_far_outside_the_shipped_range_is_flagged(self) -> None:
        """The tables read fine either way; the item behaves strangely in play. Shipped
        equipment carries AttackSpeedRate between 30 and 90 million, so the 1,000 a spin
        box starts at is three orders of magnitude out, and the plan should say so."""

        # measured while the snapshot was built, on the worker: the measure is 17 ms but
        # the import it needs is 1.5 s under shiboken's feature hook, and paid on the first
        # template chosen that was a window that stopped answering
        self.assertIsNotNone(
            getattr(self.snapshot, "_status_ranges", None),
            "the shipped stat corpus is measured by the builder, not by the first reader to ask",
        )
        ranges = self.snapshot.status_value_ranges()
        self.assertIn(DDD, ranges, "the corpus measures what the rows carry")
        entries, low, middle, high = ranges[DDD]
        self.assertGreater(entries, 0)
        self.assertLessEqual(low, middle)
        self.assertLessEqual(middle, high)

        inside = self.service.plan(self._spec(stat_edits=(StatEdit(0, DDD, middle),)), self.snapshot)
        self.assertFalse(any("shipped equipment carries it" in w for w in inside.warnings), inside.warnings)
        outside = self.service.plan(self._spec(stat_edits=(StatEdit(0, DDD, 1),)), self.snapshot)
        self.assertTrue(any("shipped equipment carries it" in w for w in outside.warnings), outside.warnings)
        self.assertTrue(any(f"{low:,}" in w and f"{high:,}" in w for w in outside.warnings), outside.warnings)

    def test_an_effect_gives_the_item_prefabs_of_its_own_with_an_effect_component(self) -> None:
        context = build_context(self.snapshot, TEMPLATE)
        self.assertEqual(context.effect_stems, frozenset({"fx_test_fire", "fx_test_ice"}))
        spec = self._spec(model_source=ModelSource.TEMPLATE, effect="fx_test_fire.level.effect")
        self.assertTrue(spec.needs_own_family and spec.needs_new_stem)
        plan = self.service.plan(spec, self.snapshot)
        added = {request.path: request for request in plan.additions}
        new_stem = plan.spec.stem
        self.assertEqual(new_stem, "cd_phm_01_sword_9109")
        self.assertEqual(set(added), {
            f"character/model/{MODEL_FOLDER}/{new_stem}.pac", f"character/modelproperty/{MODEL_FOLDER}/{new_stem}.pac_xml",
            f"character/bin__/meshphysics/{MODEL_FOLDER}/{new_stem}.hkx",
            f"character/bin__/prefab/{FOLDER}/{new_stem}_r.prefab", f"character/bin__/prefab/{FOLDER}/{new_stem}_l.prefab",
        }, "the template's family copied under the new stem, no textures, no icon")
        self.assertEqual(added[f"character/model/{MODEL_FOLDER}/{new_stem}.pac"].payload_data, self.snapshot.payload(PAC), "the template's own mesh")
        for hand in ("r", "l"):
            doc = decode_prefab_binary(added[f"character/bin__/prefab/{FOLDER}/{new_stem}_{hand}.prefab"].payload_data)
            self.assertTrue(doc.walk_complete, doc.walk_note)
            self.assertEqual([o.component_type for o in doc.objects], ["SkinnedMeshComponent", "EffectComponent"])
            self.assertEqual([r.text for r in doc.resource_strings()], [f"character/model/{MODEL_FOLDER}/{new_stem}.pac", "fx_test_fire.level.effect"])
            self.assertIn("EffectComponent", [t.type_name for t in doc.types])
        self.assertEqual(plan.manifest["effect"]["path"], "fx_test_fire.level.effect")
        self.assertEqual(len(plan.manifest["effect"]["prefabs"]), 2)
        self.assertEqual((plan.manifest["effect"]["scale"], plan.manifest["effect"]["offset"]), (1.0, [0.0, 0.0, 0.0]))
        self.assertTrue(any("grafted" in w and "scale or an offset" in w for w in plan.warnings), plan.warnings)
        self.assertTrue(any(line.startswith("effect: fx_test_fire") and "scale 1" in line for line in plan.summary_lines))
        # the grafted component carries the spec's transform: a uniform scale and an offset in the weapon's axes
        from cdmw.core.prefab_component_graft import encode_transform
        placed = self.service.plan(self._spec(model_source=ModelSource.TEMPLATE, effect="fx_test_fire.level.effect", effect_scale=0.25, effect_offset=(0.0, 0.1, -0.05)), self.snapshot)
        prefab = {r.path: r for r in placed.additions}[f"character/bin__/prefab/{FOLDER}/{new_stem}_r.prefab"].payload_data
        self.assertIn(encode_transform(scale=(0.25, 0.25, 0.25), position=(0.0, 0.1, -0.05)), prefab)
        self.assertNotIn(encode_transform(), prefab, "no identity transform left in the graft")
        self.assertTrue(any("scale 0.25, offset 0 0.1 -0.05" in line for line in placed.summary_lines), placed.summary_lines)
        # and a turn goes in as the quaternion of the same rotation the viewport showed
        from cdmw.services.effect_placement_rotation import euler_xyz_quaternion
        turned = self.service.plan(
            self._spec(model_source=ModelSource.TEMPLATE, effect="fx_test_fire.level.effect", effect_rotation_degrees=(0.0, 0.0, 90.0)),
            self.snapshot,
        )
        turned_prefab = {r.path: r for r in turned.additions}[f"character/bin__/prefab/{FOLDER}/{new_stem}_r.prefab"].payload_data
        self.assertIn(encode_transform(rotation=euler_xyz_quaternion((0.0, 0.0, 90.0))), turned_prefab)
        self.assertEqual(turned.manifest["effect"]["rotation_degrees"], [0.0, 0.0, 90.0])
        self.assertTrue(any("rotation 0 0 90 deg" in line for line in turned.summary_lines), turned.summary_lines)
        # the item's row points at its own part stems and the part-prefab table knows them
        files = dict(plan.loose_files)
        pappt = parse_pappt(files["character/bin__/partprefabtable.pappt"])
        self.assertIsNotNone(pappt.find(f"{new_stem}_r"))
        # rules: an unknown stem is refused before anything is planned; a bad shape too
        with self.assertRaises(NewItemPlanError) as caught:
            self.service.plan(self._spec(model_source=ModelSource.TEMPLATE, effect="fx_nope.level.effect"), self.snapshot)
        self.assertIn("effect.unknown", [i.code for i in caught.exception.issues])
        with self.assertRaises(NewItemPlanError) as caught:
            self.service.plan(self._spec(model_source=ModelSource.TEMPLATE, effect="not an effect"), self.snapshot)
        self.assertIn("effect.shape", [i.code for i in caught.exception.issues])
        # on an imported model the effect rides on the imported family
        imported = self.service.plan(self._spec(model_source=ModelSource.IMPORTED, effect="fx_test_ice.level.effect"), self.snapshot, model=ModelFiles(pac_data=b"PAC imported mesh"))
        doc = decode_prefab_binary({r.path: r for r in imported.additions}[f"character/bin__/prefab/{FOLDER}/{new_stem}_r.prefab"].payload_data)
        self.assertEqual([r.text for r in doc.resource_strings()], [f"character/model/{MODEL_FOLDER}/{new_stem}.pac", "fx_test_ice.level.effect"])

    def test_effect_target_preflight_fails_closed_before_planning(self) -> None:
        spec = self._spec(model_source=ModelSource.TEMPLATE, effect="fx_test_fire.level.effect")
        compatible = self.service.inspect_effect_targets(spec, self.snapshot)
        self.assertTrue(compatible.supported)
        self.assertEqual(len(compatible.target_prefabs), 2)

        broken_path = f"character/bin__/prefab/{FOLDER}/{STEM}_l.prefab"
        self.snapshot._payloads[broken_path] = b"not a prefab"
        refused = self.service.inspect_effect_targets(spec, self.snapshot)
        self.assertFalse(refused.supported)
        self.assertIn(broken_path, refused.errors[0])
        with self.assertRaisesRegex(NewItemPlanError, "cannot carry the visual effect"):
            self.service.plan(spec, self.snapshot)

    def test_an_effect_is_grafted_into_an_owned_sheathed_prefab(self) -> None:
        spec = self._spec(
            model_source=ModelSource.IMPORTED,
            sheathed_model=SheathedModel.OWN_MODEL,
            effect="fx_test_fire.level.effect",
        )
        compatibility = self.service.inspect_effect_targets(spec, self.snapshot)
        self.assertTrue(compatibility.supported, compatibility.errors)
        self.assertEqual(len(compatibility.target_prefabs), 3)
        plan = self.service.plan(spec, self.snapshot, model=ModelFiles(pac_data=b"PAC imported mesh"))
        new_stem = str(plan.spec.stem)
        additions = {request.path: request.payload_data for request in plan.additions}
        sheathed = decode_prefab_binary(
            additions[f"character/bin__/prefab/{FOLDER}/{new_stem}_r_in.prefab"]
        )
        self.assertEqual(
            [item.component_type for item in sheathed.objects],
            ["SkinnedMeshComponent", "EffectComponent"],
        )
        self.assertEqual(
            [item.text for item in sheathed.resource_strings()],
            [f"character/model/{MODEL_FOLDER}/{new_stem}.pac", "fx_test_fire.level.effect"],
        )
        self.assertEqual(len(plan.manifest["effect"]["prefabs"]), 3)

    def test_a_look_clones_the_effect_and_its_emitters_under_the_items_stems(self) -> None:
        from cdmw.core.effect_binary import decode_effect_binary
        from cdmw.domain.new_item.spec import EffectLook

        fixtures = Path(__file__).parent / "fixtures" / "effects"
        files = synthetic_files()
        files["effect/binary__/releasebin/fx_real_fire.pae"] = (fixtures / "fx_hit_common_fire_attach_a_loop.pae").read_bytes()
        files["effect/binary__/emitter/cdem_last_fire_circle_trail_001a.paem"] = (fixtures / "cdem_last_fire_circle_trail_001a.paem").read_bytes()
        files["effect/binary__/renderpreset/fx_fire_uber_ember_01.parg"] = (fixtures / "fx_fire_uber_ember_01.parg").read_bytes()
        pamt_path = build_package(self.root / "look", files)
        snapshot = self.service.build_snapshot(parse_archive_pamt(pamt_path), read_entry=_read)
        look = EffectLook(color=(0.2, 0.4, 1.0), intensity=2.0, size=0.5, rate=2.0, lifetime=1.0)
        plan = self.service.plan(self._spec(model_source=ModelSource.TEMPLATE, effect="fx_real_fire.level.effect", effect_look=look), snapshot)
        added = {request.path: request for request in plan.additions}
        key = plan.spec.item_key
        effect_stem = f"fx_re_n{key % 100000:05d}"
        emitter_stem = f"cdem_last_fire_circle_tra_n{key % 100000:05d}"
        self.assertEqual(len(effect_stem), len("fx_real_fire"))
        self.assertIn(f"effect/binary__/releasebin/{effect_stem}.pae", added)
        self.assertIn(f"effect/binary__/emitter/{emitter_stem}.paem", added)
        # the clone decodes, names the cloned emitter and carries the look
        effect = decode_effect_binary(added[f"effect/binary__/releasebin/{effect_stem}.pae"].payload_data)
        self.assertTrue(effect.walk_complete, effect.walk_note)
        # the file's authoring name is not this package's stem, so it stays (a shipped file's is, and is renamed with it)
        self.assertEqual(effect.root.value("_effectDataName").value, "fx/materialfx/fx_hit_common_fire_attach_a_loop")
        self.assertIn(f"emitter/{emitter_stem}", effect.emitter_names())
        self.assertIn("emitter/cdem_material_firefly_alpha_uberstandard", effect.emitter_names(), "the emitter the package lacks keeps its shipped name")
        emitter = decode_effect_binary(added[f"effect/binary__/emitter/{emitter_stem}.paem"].payload_data)
        self.assertTrue(emitter.walk_complete, emitter.walk_note)
        self.assertEqual(emitter.root.value("_emitterDataName").value, f"emitter/{emitter_stem}")
        # the render preset the effect names is cloned and the clone points at it
        preset_stem = f"fx_fire_uber_e_n{key % 100000:05d}"
        self.assertIn(f"effect/binary__/renderpreset/{preset_stem}.parg", added)
        from cdmw.core.effect_edit import preset_names_of

        self.assertIn(("render", preset_stem), preset_names_of(effect))
        self.assertNotIn(("render", "fx_fire_uber_ember_01"), preset_names_of(effect))
        preset = decode_effect_binary(added[f"effect/binary__/renderpreset/{preset_stem}.parg"].payload_data)
        self.assertTrue(preset.walk_complete, preset.walk_note)
        # the graft names the clone, and the manifest says what was edited
        prefab = decode_prefab_binary(added[f"character/bin__/prefab/{FOLDER}/{plan.spec.stem}_r.prefab"].payload_data)
        self.assertIn(f"{effect_stem}.level.effect", [r.text for r in prefab.resource_strings()])
        self.assertEqual(plan.manifest["effect"]["path"], f"{effect_stem}.level.effect")
        look_manifest = plan.manifest["effect"]["look"]
        self.assertEqual(look_manifest["source"], "fx_real_fire.level.effect")
        self.assertEqual(look_manifest["color"], [0.2, 0.4, 1.0])
        self.assertGreater(look_manifest["edited"].get("_spawnCountMin", 0), 0)
        self.assertTrue(any(line.startswith("effect look: fx_real_fire cloned as") for line in plan.summary_lines))
        self.assertTrue(any("firefly" in w and "do not have" in w for w in plan.warnings), plan.warnings)
        self.assertTrue(any(issue.code == "effect.look.unproven" for issue in plan.issues))
        # a default look leaves the shipped effect alone
        plain = self.service.plan(self._spec(model_source=ModelSource.TEMPLATE, effect="fx_real_fire.level.effect"), snapshot)
        self.assertFalse(any(path.startswith("effect/") for path in (r.path for r in plain.additions)))
        self.assertIsNone(plain.manifest["effect"]["look"])

    def test_refusals(self) -> None:
        with self.assertRaises(NewItemPlanError) as caught:
            self.service.plan(self._spec(internal_name="Ziane_OneHandSword"), self.snapshot)
        self.assertTrue(any(issue.code == "internal_name.taken" for issue in caught.exception.issues))
        with self.assertRaisesRegex(NewItemPlanError, "no build was given"):
            self.service.plan(self._spec(model_source=ModelSource.IMPORTED), self.snapshot)
        with self.assertRaisesRegex(NewItemPlanError, "generated icon"):
            self.service.plan(self._spec(icon=IconSource.GENERATED), self.snapshot)
        with self.assertRaisesRegex(NewItemPlanError, "skips level"):
            self.service.plan(self._spec(stat_edits=(StatEdit(4, DDD, 1),)), self.snapshot)
        with self.assertRaises(NewItemPlanError):
            self.service.plan(self._spec(placement=Placement(PlacementKind.SWAP, "Store_Camp_Equipment", "Nope")), self.snapshot)
        insert = self.service.plan(self._spec(placement=Placement(PlacementKind.INSERT, "Store_Pai_BlackMarket", price=5)), self.snapshot)
        self.assertTrue(any("no price" in w for w in insert.warnings), insert.warnings)
        self.assertFalse(any("unproven" in w and "stock entry" in w for w in insert.warnings), "a whole new stock entry sold in game (2026-08-18)")
        files = dict(insert.loose_files)
        stores = {s.name: s for s in parse_store_table(files[f"{BIN}/storeinfo.pabgb"], files[f"{BIN}/storeinfo.pabgh"])}
        self.assertEqual([e.item_key for e in stores["Store_Pai_BlackMarket"].entries], [TEMPLATE, 1990000])


class WriteTests(_PackageCase):
    def _plan(self):
        spec = NewItemSpec(
            template_key=TEMPLATE, internal_name="Ziane_Clone_OneHandSword", display_names={"eng": "Wolf's Fang (Clone)"},
            model_source=ModelSource.IMPORTED, placement=Placement(PlacementKind.SWAP, "Store_Camp_Equipment", "Cigar_OneHandSword"),
        )
        return self.service.plan(spec, self.snapshot, model=ModelFiles(pac_data=b"PAC imported mesh"))

    def test_install_writes_the_package_and_reads_back(self) -> None:
        plan = self._plan()
        mutations = ArchiveMutationService()
        with self.assertRaisesRegex(NewItemInstallRefused, "confirmation"):
            self.service.install(plan, mutation_service=mutations, confirmed=False, game_running=lambda: False)
        with self.assertRaisesRegex(NewItemInstallRefused, "running"):
            self.service.install(plan, mutation_service=mutations, confirmed=True, game_running=lambda: True)
        logs: list[str] = []
        with patch("cdmw.services.new_item_service.game_is_running", lambda: False):
            result = install_task(plan, service=self.service, mutation_service=mutations, confirmed=True)(logs.append, None)
        self.assertTrue(result.backup_dir.is_dir())
        self.assertTrue(any("Backup created" in line for line in logs), logs[:5])
        self.assertEqual(sorted(result.added_paths), sorted(plan.new_paths))
        after = self.reread()
        for path, data in plan.loose_files.items():
            self.assertEqual(after[path], data, path)
        rows = parse_pabgh_table(after[f"{BIN}/iteminfo.pabgh"], payload=after[f"{BIN}/iteminfo.pabgb"]).row_spans(len(after[f"{BIN}/iteminfo.pabgb"]))
        item = parse_iteminfo_row(after[f"{BIN}/iteminfo.pabgb"][rows[-1][1]:rows[-1][2]])
        self.assertEqual((item.key, item.string_key), (1990000, "Ziane_Clone_OneHandSword"))
        # the installed archive is itself a valid snapshot again, and the new item resolves
        again = self.service.build_snapshot(parse_archive_pamt(self.pamt_path), read_entry=_read)
        family = again.family(1990000)
        self.assertEqual(family.model_stem, "cd_phm_01_sword_9109")
        self.assertEqual(family.owned_stems, ("cd_phm_01_sword_9109_r", "cd_phm_01_sword_9109_r_in", "cd_phm_01_sword_9109_l"), "the installed item owns its sheathed part too")
        self.assertEqual(
            [item.role for item in family.missing_files], ["hkx"],
            "the only file the family goes without is the template's mesh physics, which an imported model does not inherit",
        )
        self.assertEqual([s for s in again.stores if s.name == "Store_Camp_Equipment"][0].entries[0].item_key, 1990000)

    def test_installing_as_an_overlay_leaves_the_shipped_archives_alone(self) -> None:
        """The same plan, written as a directory of its own and mounted first. What the
        game reads changes; what the game shipped does not, so the backup is the mount
        list and the registry rather than every payload file the plan touches."""

        from cdmw.core.papgt_format import parse_papgt
        from cdmw.core.archive_scan_cache import discover_pamt_files

        plan = self._plan()
        mutations = ArchiveMutationService()
        shipped = {path: path.read_bytes() for path in sorted(self.root.glob("0009/*.paz"))}
        with self.assertRaisesRegex(NewItemInstallRefused, "confirmation"):
            self.service.install_overlay(plan, mutation_service=mutations, confirmed=False, game_running=lambda: False)
        logs: list[str] = []
        with patch("cdmw.services.new_item_service.game_is_running", lambda: False):
            result = self.service.install_overlay(plan, mutation_service=mutations, confirmed=True, on_log=logs.append)

        self.assertTrue((result.directory / "0.pamt").is_file())
        self.assertTrue((result.directory / "0.paz").is_file())
        self.assertGreaterEqual(result.file_count, len(plan.patches) + len(plan.additions))
        for path, before in shipped.items():
            self.assertEqual(path.read_bytes(), before, f"{path.name} was rewritten by an overlay install")

        mounted = parse_papgt((self.root / "meta" / "0.papgt").read_bytes())
        self.assertEqual(mounted[0].name, result.directory.name)
        self.assertEqual(mounted[0].pamt_checksum, result.pamt_checksum)
        self.assertEqual(discover_pamt_files(self.root)[0].parent.name, result.directory.name)

        # the item resolves out of the overlay, through the same snapshot the studio builds
        entries: dict[str, object] = {}
        for pamt in discover_pamt_files(self.root):
            for entry in parse_archive_pamt(pamt):
                entries.setdefault(entry.path, entry)
        again = self.service.build_snapshot(tuple(entries.values()), read_entry=_read)
        self.assertIn(1990000, again.rows)
        self.assertEqual(again.rows[1990000].string_key, "Ziane_Clone_OneHandSword")
        family = again.family(1990000)
        self.assertEqual(family.model_stem, "cd_phm_01_sword_9109")
        self.assertEqual([item.role for item in family.missing_files], ["hkx"], "no inherited mesh physics")
        if result.backup_dir is not None:
            names = sorted(path.name for path in result.backup_dir.iterdir())
            self.assertNotIn("0009_0.paz", names, "no shipped payload file is in the backup")

    def test_an_item_installed_the_old_way_on_top_of_an_overlay(self) -> None:
        """Both install buttons stay on the step, so the two routes meet: an overlay is
        mounted first, the studio re-reads and the next plan's entries are the overlay's,
        and Install then patches an archive this workbench wrote rather than one the game
        shipped. Both items have to survive that, and the overlay has to stay readable."""

        from cdmw.core.archive_scan_cache import discover_pamt_files

        first = self._plan()
        mutations = ArchiveMutationService()
        with patch("cdmw.services.new_item_service.game_is_running", lambda: False):
            overlay = self.service.install_overlay(first, mutation_service=mutations, confirmed=True)

        # what the studio does after an install: read the archives again, in mount order
        entries: dict[str, object] = {}
        for pamt in discover_pamt_files(self.root):
            for entry in parse_archive_pamt(pamt):
                entries.setdefault(entry.path, entry)
        snapshot = self.service.build_snapshot(tuple(entries.values()), read_entry=_read)
        self.assertEqual(
            Path(snapshot.entry(f"{BIN}/iteminfo.pabgb").pamt_path).parent.name,
            overlay.directory.name,
            "the next plan is built against the overlay's copy of the table",
        )

        second = self.service.plan(
            NewItemSpec(
                template_key=TEMPLATE, internal_name="Ziane_Second_OneHandSword", display_names={"eng": "Second"},
                model_source=ModelSource.IMPORTED,
            ),
            snapshot,
            model=ModelFiles(pac_data=b"PAC a second mesh"),
        )
        self.assertNotEqual(second.spec.item_key, first.spec.item_key, "the key after the one in the overlay")
        with patch("cdmw.services.new_item_service.game_is_running", lambda: False):
            self.service.install(second, mutation_service=mutations, confirmed=True)

        after: dict[str, object] = {}
        for pamt in discover_pamt_files(self.root):
            for entry in parse_archive_pamt(pamt):
                after.setdefault(entry.path, entry)
        again = self.service.build_snapshot(tuple(after.values()), read_entry=_read)
        self.assertIn(first.spec.item_key, again.rows, "the item the overlay carries")
        self.assertIn(second.spec.item_key, again.rows, "the item patched on top of it")
        for key in (first.spec.item_key, second.spec.item_key):
            self.assertEqual([item.role for item in again.family(key).missing_files], ["hkx"], "no inherited mesh physics")

    def test_a_read_that_fails_after_the_archives_moved_says_so(self) -> None:
        """Another program rewriting the archives -- a mod manager mounting or unmounting
        them -- moves every payload, and the entries a snapshot was built from then point
        at the wrong bytes. The read fails somewhere deep in decompression or decryption,
        and the message that surfaces has to name the cause rather than the symptom."""

        from cdmw.core.archive_patching import patch_archive_entries
        from cdmw.domain.archives.mutation import ArchivePatchRequest
        from cdmw.services.new_item_snapshot import NewItemSnapshotError

        snapshot = self.snapshot
        path = f"{BIN}/stringinfo.pabgb"
        entry = snapshot.entry(path)

        # the same file, written again: the payload moves to the end of the PAZ, so the
        # entry this snapshot holds now points at bytes that are not the file
        patch_archive_entries((ArchivePatchRequest(entry, b"a rewritten table"),))

        def refuse(_entry):
            raise ValueError(f"ChaCha20 decryption validation failed for {path}")

        snapshot._payloads.pop(path.lower(), None)
        object.__setattr__(snapshot, "read_entry", refuse)
        with self.assertRaises(NewItemSnapshotError) as caught:
            snapshot.payload(path)
        message = str(caught.exception)
        self.assertIn("not where the workbench last saw it", message)
        self.assertIn("read the archives again", message)
        self.assertIn(path, message)

    def test_export_writes_a_loose_mod_with_new_paths(self) -> None:
        plan = self._plan()
        out = self.root / "export"
        result = export_task(plan, out, service=self.service, manager="CDUMM")(lambda _m: None, None)
        self.assertEqual(result.manager, "CDUMM")
        self.assertEqual(sorted(result.payload_paths), sorted(plan.loose_files))
        self.assertEqual(result.new_paths, plan.new_paths)
        files_root = out / "files"
        self.assertTrue((files_root / "character" / "model" / Path(MODEL_FOLDER) / "cd_phm_01_sword_9109.pac").is_file())
        manifest_path = out / "manifest.json"
        self.assertTrue(manifest_path.is_file(), sorted(p.name for p in out.iterdir()))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        text = json.dumps(manifest)
        self.assertIn("cd_phm_01_sword_9109", text)
        with self.assertRaisesRegex(ValueError, "manager profile"):
            self.service.export_loose(plan, self.root / "x", manager="nope")
        jmm = self.service.export_loose(plan, self.root / "jmm", manager="JMM")
        self.assertTrue((self.root / "jmm" / "character" / "model" / Path(MODEL_FOLDER) / "cd_phm_01_sword_9109.pac").is_file())
        self.assertEqual(jmm.manager, "JMM")

    def test_a_failed_export_leaves_the_existing_folder_unchanged(self) -> None:
        plan = self._plan()
        out = self.root / "atomic_failure"
        out.mkdir()
        (out / "keep.txt").write_bytes(b"original")
        before = {
            path.relative_to(out).as_posix(): path.read_bytes()
            for path in out.rglob("*")
            if path.is_file()
        }

        with patch("cdmw.core.mod_package.finalize_mod_package_export", side_effect=RuntimeError("metadata failed")):
            with self.assertRaisesRegex(RuntimeError, "metadata failed"):
                self.service.export_loose(plan, out, manager="JMM")

        after = {
            path.relative_to(out).as_posix(): path.read_bytes()
            for path in out.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

    def test_cancelling_mid_export_never_publishes_the_staged_files(self) -> None:
        plan = self._plan()
        out = self.root / "atomic_cancel"
        out.mkdir()
        (out / "keep.txt").write_bytes(b"original")
        stop = threading.Event()
        original_write = Path.write_bytes
        wrote_staged_file = False

        def cancelling_write(path: Path, payload: bytes) -> int:
            nonlocal wrote_staged_file
            result = original_write(path, payload)
            if ".cdmw-stage-" in str(path) and not wrote_staged_file:
                wrote_staged_file = True
                stop.set()
            return result

        with patch.object(Path, "write_bytes", cancelling_write):
            with self.assertRaises(RunCancelled):
                self.service.export_loose(plan, out, manager="JMM", stop_event=stop)

        self.assertTrue(wrote_staged_file, "the cancellation happened after staging began")
        self.assertEqual(
            {
                path.relative_to(out).as_posix(): path.read_bytes()
                for path in out.rglob("*")
                if path.is_file()
            },
            {"keep.txt": b"original"},
        )

    def test_plan_task_runs_the_service(self) -> None:
        spec = NewItemSpec(template_key=TEMPLATE, internal_name="Ziane_Clone_OneHandSword", display_names={"eng": "X"})
        plan = plan_task(spec, self.snapshot, service=self.service)(lambda _m: None, None)
        self.assertEqual(plan.spec.item_key, 1990000)


class TextureRegistryTests(_PackageCase):
    """New `.dds` files are registered in `meta/0.pathc`, written and backed up with the install."""

    NEW_ICON = "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_9109.dds"

    def setUp(self) -> None:
        super().setUp()
        from cdmw.core.pathc_format import PathcEntry, PathcTable, encode_pathc, pathc_checksum

        icon_header = _fake_dds()[:128] + bytes(20)
        # the shipped registry tags a colour-with-alpha (DXT5) header 13 in dwReserved2; a header is only reused when its tag matches too
        small = bytearray(_fake_dds(4, 4)[:128])
        struct.pack_into("<I", small, 124, 13)
        small_header = bytes(small) + bytes(20)
        rows = sorted((
            PathcEntry(pathc_checksum(ICON), 0, 255, 255, struct.pack("<4I", 65536, 65536, 0, 0)),
            PathcEntry(pathc_checksum("ui/texture/icon/itemicon_prefab_cd_phm_01_sword_0016.dds"), 0, 255, 255, struct.pack("<4I", 65536, 65536, 0, 0)),
            PathcEntry(pathc_checksum(f"character/texture/1_pc/{STEM}_d.dds"), 1, 255, 255, struct.pack("<4I", 16, 0, 0, 0)),
        ), key=lambda row: row.checksum)
        self.pathc_path = self.root / "meta" / "0.pathc"
        self.pathc_before = encode_pathc(PathcTable(0, 148, (icon_header, small_header), tuple(rows), (), b""))
        self.pathc_path.write_bytes(self.pathc_before)
        self.snapshot = self.service.build_snapshot(self.entries, read_entry=_read)

    def _plan(self):
        spec = NewItemSpec(
            template_key=TEMPLATE, internal_name="Ziane_Clone_OneHandSword", display_names={"eng": "Wolf's Fang (Clone)"},
            model_source=ModelSource.IMPORTED, icon=IconSource.GENERATED,
        )
        model = ModelFiles(pac_data=b"PAC imported mesh", side_files={f"character/texture/1_pc/{STEM}_d.dds": _fake_dds(4, 4) + bytes(16)})
        allocated = self.service.allocate(spec, self.snapshot)
        icon = NewItemIcon(
            icon_string="ItemIcon_Prefab_cd_phm_01_sword_9109", icon_hash=stringinfo_key("ItemIcon_Prefab_cd_phm_01_sword_9109"),
            target_path=self.NEW_ICON, payload_data=_fake_dds() + bytes(65536),
            add_request=ArchiveAddRequest.from_template(self.snapshot.entry(ICON), self.NEW_ICON, _fake_dds() + bytes(65536)), build=None,
        )
        return self.service.plan(allocated, self.snapshot, model=model, icon=icon)

    def test_plan_registers_every_new_dds(self) -> None:
        from cdmw.core.pathc_format import parse_pathc

        self.assertIsNotNone(self.snapshot.pathc)
        plan = self._plan()
        self.assertEqual([m.path for m in plan.meta_files], ["meta/0.pathc"])
        table = parse_pathc(plan.meta_files[0].payload_data)
        self.assertEqual(len(table.entries), 5)
        icon = table.find(self.NEW_ICON)
        texture = table.find("character/texture/1_pc/cd_phm_01_sword_9109_d.dds")
        self.assertEqual((icon.header_index, icon.block_infos), (0, struct.pack("<4I", 65536, 65536, 0, 0)), "like the template's icon")
        self.assertEqual((texture.header_index, texture.block_infos), (1, struct.pack("<4I", 16, 0, 0, 0)), "under the header its own DDS header equals")
        self.assertEqual(sorted(plan.manifest["texture_registry"]), sorted([self.NEW_ICON, "character/texture/1_pc/cd_phm_01_sword_9109_d.dds"]))
        self.assertIn("meta/0.pathc", plan.touched_paths)
        self.assertNotIn("meta/0.pathc", plan.loose_files, "a loose mod leaves the registry to the manager")
        self.assertTrue(any("texture registry" in line for line in plan.summary_lines))
        # a texture of a shape the registry has never seen gets a header row of its own
        odd = ModelFiles(pac_data=b"PAC", side_files={f"character/texture/1_pc/{STEM}_d.dds": _fake_dds(8, 8) + bytes(64)})
        odd_plan = self.service.plan(self.service.allocate(NewItemSpec(template_key=TEMPLATE, internal_name="Ziane_Odd_OneHandSword", display_names={"eng": "X"}, model_source=ModelSource.IMPORTED), self.snapshot), self.snapshot, model=odd)
        odd_table = parse_pathc(odd_plan.meta_files[0].payload_data)
        self.assertEqual(len(odd_table.headers), 3, "one header row added for the 8x8 shape")
        self.assertEqual(odd_table.find("character/texture/1_pc/cd_phm_01_sword_9109_d.dds").header_index, 2)

    def test_without_a_registry_the_plan_only_warns(self) -> None:
        self.pathc_path.unlink()
        snapshot = self.service.build_snapshot(self.entries, read_entry=_read)
        self.assertIsNone(snapshot.pathc)
        spec = self.service.allocate(NewItemSpec(template_key=TEMPLATE, internal_name="Ziane_Clone_OneHandSword", display_names={"eng": "X"}, model_source=ModelSource.IMPORTED), snapshot)
        plan = self.service.plan(spec, snapshot, model=ModelFiles(pac_data=b"PAC", side_files={f"character/texture/1_pc/{STEM}_d.dds": _fake_dds(4, 4)}))
        self.assertEqual(plan.meta_files, ())
        self.assertTrue(any("meta/0.pathc" in w for w in plan.warnings), plan.warnings)

    def test_an_overlay_install_writes_the_registry_beside_the_overlay(self) -> None:
        """An item with a texture of its own carries a rewritten `meta/0.pathc`, and the
        overlay route has to write it exactly as the patching route does: the registry is
        a loose file beside the archives, not an entry inside one, so an overlay that
        skipped it would mount a texture the game cannot look up."""

        from cdmw.core.papgt_format import parse_papgt

        plan = self._plan()
        self.assertEqual([m.path for m in plan.meta_files], ["meta/0.pathc"])
        mutations = ArchiveMutationService()
        shipped = {path: path.read_bytes() for path in sorted(self.root.glob("0009/*.paz"))}
        with patch("cdmw.services.new_item_service.game_is_running", lambda: False):
            result = self.service.install_overlay(plan, mutation_service=mutations, confirmed=True)

        self.assertEqual(self.pathc_path.read_bytes(), plan.meta_files[0].payload_data, "the registry the plan built")
        self.assertNotEqual(self.pathc_path.read_bytes(), self.pathc_before)
        for path, before in shipped.items():
            self.assertEqual(path.read_bytes(), before, f"{path.name} was rewritten by an overlay install")
        self.assertEqual(parse_papgt((self.root / "meta" / "0.papgt").read_bytes())[0].name, result.directory.name)
        # the registry is in the backup, so removing the overlay puts it back
        manifest = json.loads((result.backup_dir / "backup_manifest.json").read_text(encoding="utf-8"))
        originals = {Path(item["original_path"]).resolve() for item in manifest["files"]}
        self.assertIn(self.pathc_path.resolve(), originals)
        mutations.restore_backup(result.backup_dir, confirmed=True)
        self.assertEqual(self.pathc_path.read_bytes(), self.pathc_before, "restoring the backup restores the registry too")

    def test_install_writes_the_registry_under_the_backup(self) -> None:
        plan = self._plan()
        mutations = ArchiveMutationService()
        with patch("cdmw.services.new_item_service.game_is_running", lambda: False):
            result = self.service.install(plan, mutation_service=mutations, confirmed=True)
        self.assertEqual(result.meta_paths, ["meta/0.pathc"])
        self.assertEqual(self.pathc_path.read_bytes(), plan.meta_files[0].payload_data)
        manifest = json.loads((result.backup_dir / "backup_manifest.json").read_text(encoding="utf-8"))
        originals = {Path(item["original_path"]).resolve() for item in manifest["files"]}
        self.assertIn(self.pathc_path.resolve(), originals)
        mutations.restore_backup(result.backup_dir, confirmed=True)
        self.assertEqual(self.pathc_path.read_bytes(), self.pathc_before, "restoring the backup restores the registry too")


if __name__ == "__main__":
    unittest.main()


import pytest  # noqa: E402


@pytest.mark.real_game
class VanillaNewItemTests(unittest.TestCase):
    """The snapshot and a plan against the shipped tables (nothing is written)."""

    def test_snapshot_and_plans_against_the_shipped_archives(self) -> None:
        import time
        from tools.placement_studio import corpus

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        entries = [entry for _package, entry in corpus._iter_archive_entries(corpus.game_root())]
        service = NewItemService()
        started = time.perf_counter()
        snapshot = service.build_snapshot(entries)
        elapsed = time.perf_counter() - started
        self.assertGreater(len(snapshot.rows), 6000)
        self.assertEqual(len(snapshot.languages), 14)
        self.assertLess(elapsed, 120.0, f"snapshot took {elapsed:.1f}s")
        ziane = snapshot.keys_by_name["Ziane_OneHandSword"]
        context = build_context(snapshot, ziane)
        self.assertEqual(context.template.equip_type_name, "OneHandSword")
        self.assertEqual(context.template.owned_stems, ("cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l"))
        self.assertIn("Store_Pai_BlackMarket", context.store_names)
        self.assertIn("Ziane_OneHandSword", context.store_stock_names["Store_Pai_BlackMarket"])
        spec = NewItemSpec(
            template_key=ziane, internal_name="Ziane_GateClone_OneHandSword",
            display_names={"eng": "Wolf's Fang (gate)"}, descriptions={"eng": "A planning gate."},
            stat_edits=(StatEdit(0, DDD, 99999),),
            placement=Placement(PlacementKind.SWAP, "Store_Pai_BlackMarket", "Ziane_OneHandSword"),
        )
        plan = service.plan(spec, snapshot)
        self.assertEqual(plan.additions, ())
        self.assertEqual(len([p for p in plan.patches if p.entry.path.endswith(".paloc")]), 14)
        self.assertNotIn(plan.spec.item_key, snapshot.rows)
        # the localisation keys are the ones the game computes, and every shipped row agrees
        self.assertEqual((plan.spec.name_key, plan.spec.desc_key), localization_keys(plan.spec.item_key))
        shipped = [row for row in snapshot.rows.values() if row.key < 1_990_000 and row.name_key]
        self.assertGreater(len(shipped), 6000)
        self.assertEqual([row.key for row in shipped if row.name_key != localization_keys(row.key)[0]], [], "a shipped name key that is not (key << 32) | 0x70")
        self.assertEqual([row.key for row in shipped if row.desc_key and row.desc_key != localization_keys(row.key)[1]], [], "a shipped description key that is not (key << 32) | 0x71")
        # and the new records sit in the table's numeric order (between their numeric neighbours), not at the end
        eng = parse_paloc(dict(plan.loose_files)[f"{LOC}/localizationstring_eng.paloc"]).entries
        at = [index for index, entry in enumerate(eng) if entry.key == plan.spec.name_key]
        self.assertEqual(len(at), 1)
        before = [int(e.key) for e in eng[:at[0]] if e.key.isdigit()]
        after = [int(e.key) for e in eng[at[0] + 2:] if e.key.isdigit()]
        self.assertEqual(eng[at[0] + 1].key, plan.spec.desc_key)
        self.assertLess(before[-1], int(plan.spec.name_key))
        self.assertGreater(after[0], int(plan.spec.desc_key))
        self.assertLess(at[0], len(eng) - 2, "the records were appended rather than slotted in")
        imported = service.plan(
            NewItemSpec(template_key=ziane, internal_name="Ziane_GateCloneB_OneHandSword", display_names={"eng": "B"}, model_source=ModelSource.IMPORTED),
            snapshot,
            model=ModelFiles(pac_data=snapshot.payload("character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0109.pac")),
        )
        # an imported model draws its own sheathed look by default (SheathedModel.OWN_MODEL),
        # so the borrowed _in prefabs are cloned under the stem too
        self.assertEqual(sorted(request.path.rsplit("/", 1)[-1] for request in imported.additions), sorted([
            f"{imported.spec.stem}.hkx", f"{imported.spec.stem}.pac", f"{imported.spec.stem}.pac_xml",
            f"{imported.spec.stem}_l.prefab", f"{imported.spec.stem}_r.prefab",
            f"{imported.spec.stem}_l_in.prefab", f"{imported.spec.stem}_r_in.prefab",
        ]))
        self.assertTrue(imported.spec.stem.startswith("cd_phm_01_sword_"))
        for request in imported.additions:
            self.assertFalse(snapshot.has_entry(request.path), request.path)
