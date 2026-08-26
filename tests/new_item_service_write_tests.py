"""Write, texture-registry, and real-game cases for the New Item service."""

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
import pytest

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

def _read(entry) -> bytes:
    return read_archive_entry_data(entry)[0]

class _WriteTestsMixin:
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

class _TextureRegistryTestsMixin:
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

class _VanillaNewItemTestsMixin:
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
        self.assertEqual(len(snapshot.languages), 15)
        self.assertIn("ara", snapshot.languages, "game 2.00.00 adds Arabic localization")
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
