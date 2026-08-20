"""The golden replay: `NewItemService.plan()` reproduces the in-game-verified spike byte for byte.

`tests/fixtures/new_item_golden/` holds the pre-spike source trimmed to what the two
clones touch and the spike's own output. The gate plans Clone A (template model) and
Clone B (cloned model family) with the spike's keys and names and asserts identical
ItemInfo rows, StringInfo rows, part-prefab records, store rows, group memberships,
localisation records, re-pathed prefabs and file hashes. Anything that drifts here
has drifted from something the game accepted. (The spike's localisation keys were
not the derived form the game looks up, so its names were blank; they are passed
explicitly here so the replay stays exact, and the allocator no longer makes them.)
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.archive_format import parse_archive_pamt  # noqa: E402
from cdmw.core.itemgroupinfo_table import parse_item_group_table  # noqa: E402
from cdmw.core.iteminfo_row import parse_iteminfo_row  # noqa: E402
from cdmw.core.paloc_format import parse_paloc  # noqa: E402
from cdmw.core.pappt_format import parse_pappt  # noqa: E402
from cdmw.core.storeinfo_table import parse_store_row, parse_store_table, swap_stock_item  # noqa: E402
from cdmw.core.stringinfo_table import parse_stringinfo, stringinfo_key  # noqa: E402
from cdmw.core.structured_binary_editor import parse_pabgh_table  # noqa: E402
from cdmw.domain.new_item.spec import ModelSource, NewItemSpec, Placement, PlacementKind, SheathedModel  # noqa: E402
from cdmw.services.new_item_planning import ModelFiles, NewItemPlan  # noqa: E402
from cdmw.services.new_item_service import NewItemService  # noqa: E402
from test_new_item_service import _read, build_package  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "new_item_golden"
BIN = "gamedata/binary__/client/bin"
LOC = "gamedata/stringtable/binary__"
FOLDER = "1_pc/01_phm/weapon/01_onehandweapon"
MODEL_FOLDER = "1_pc/1_phm/weapon/1_onehandweapon"
TEMPLATE_PAC = f"character/model/{MODEL_FOLDER}/cd_phm_01_sword_0109.pac"
CLONE_A, CLONE_B = 1990001, 1990002
NEW_STEM = "cd_phm_01_sword_9109"


def _source_files() -> dict[str, bytes]:
    files = {}
    for path in FIXTURE.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(FIXTURE).as_posix()
        if relative.startswith("expected/") or relative == "README.md":
            continue
        files[relative] = path.read_bytes()
    return files


class GoldenReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        root = Path(cls._temp.name)
        cls.pamt_path = build_package(root, _source_files())
        cls.service = NewItemService()
        cls.snapshot = cls.service.build_snapshot(parse_archive_pamt(cls.pamt_path), read_entry=_read)
        cls.golden = json.loads((FIXTURE / "expected" / "golden.json").read_text(encoding="utf-8"))
        cls.spec = cls.golden["spec"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    # ------------------------------------------------------------------ helpers

    def _spec(self, key: int, *, store: str, victim: str, model: ModelSource) -> NewItemSpec:
        item = self.spec["items"][str(key)]
        return NewItemSpec(
            template_key=int(self.spec["template_key"]),
            internal_name=item["internal_name"],
            display_names={"eng": item["display_name"]},
            descriptions={"eng": self.spec["descriptions"][str(key)]},
            item_key=key,
            stem=NEW_STEM if model is ModelSource.IMPORTED else None,
            name_key=item["name_key"],
            desc_key=item["desc_key"],
            model_source=model,
            # the spike kept borrowing the template's sheathed (_IN) parts; the studio gives an imported model its own now
            sheathed_model=SheathedModel.TEMPLATE,
            # the spike copied the template's mesh physics onto the imported model, which is
            # what put cloth on a handle; the studio leaves it out unless asked, so the
            # replay asks
            keep_template_physics=True,
            # the spike swapped the item in place and kept the line's unlock requirement (a collection's knowledge);
            # the studio drops it by default now, so the replay says so explicitly
            placement=Placement(PlacementKind.SWAP, store, victim, keep_requirement=True),
        )

    def _plan(self, key: int, store: str, victim: str) -> NewItemPlan:
        model = ModelSource.IMPORTED if key == CLONE_B else ModelSource.TEMPLATE
        files = ModelFiles(pac_data=self.snapshot.payload(TEMPLATE_PAC)) if key == CLONE_B else None
        return self.service.plan(self._spec(key, store=store, victim=victim, model=model), self.snapshot, model=files)

    def _last_row(self, plan: NewItemPlan, stem: str) -> bytes:
        payload = plan.loose_files[f"{BIN}/{stem}.pabgb"]
        header = plan.loose_files[f"{BIN}/{stem}.pabgh"]
        spans = parse_pabgh_table(header, payload=payload).row_spans(len(payload))
        return payload[spans[-1][1]:spans[-1][2]]

    def _victims(self, key: int) -> dict[str, str]:
        out = {}
        for store, swaps in self.spec["store_swaps"].items():
            for victim, target in swaps.items():
                if int(target) == key:
                    out[store] = victim
        return out

    def _expected_store(self, store: str, key: int) -> bytes:
        """The spike's store row with the other clone's swap undone."""

        row = parse_store_row((FIXTURE / "expected" / f"store_{store}.bin").read_bytes())
        other = CLONE_B if key == CLONE_A else CLONE_A
        other_victim = self._victims(other)[store]
        return swap_stock_item(row, other, self.snapshot.keys_by_name[other_victim]).raw

    # ------------------------------------------------------------------ gates

    def test_the_fixture_is_the_pre_spike_source(self) -> None:
        self.assertNotIn(CLONE_A, self.snapshot.rows)
        self.assertNotIn(CLONE_B, self.snapshot.rows)
        self.assertIsNone(self.snapshot.pappt.find(f"{NEW_STEM}_r"))
        family = self.snapshot.family(int(self.spec["template_key"]))
        self.assertEqual(family.model_stem, "cd_phm_01_sword_0109")
        self.assertEqual(family.owned_stems, ("cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l"))
        self.assertEqual(family.borrowed_stems, ("cd_phm_01_sword_0168_r_in_index01", "cd_phm_01_sword_0168_l_in_index01"))
        self.assertEqual(len(self.snapshot.languages), 14)
        self.assertEqual(len(self.snapshot.item_groups), 11)

    def test_clone_a_reproduces_the_spike(self) -> None:
        for store, victim in self._victims(CLONE_A).items():
            plan = self._plan(CLONE_A, store, victim)
            self.assertEqual(plan.additions, ())
            row = self._last_row(plan, "iteminfo")
            self.assertEqual(row, (FIXTURE / "expected" / f"iteminfo_{CLONE_A}.bin").read_bytes(), "ItemInfo row differs from the spike's")
            self.assertEqual(self._store_row(plan, store), self._expected_store(store, CLONE_A), store)
            self._assert_groups(plan, keep=CLONE_A, drop=CLONE_B)
            self._assert_paloc(plan, CLONE_A)
        item = parse_iteminfo_row((FIXTURE / "expected" / f"iteminfo_{CLONE_A}.bin").read_bytes())
        self.assertEqual((item.key, item.string_key), (CLONE_A, "ZianeCloneA_OneHandSword"))

    def test_clone_b_reproduces_the_spike(self) -> None:
        for store, victim in self._victims(CLONE_B).items():
            plan = self._plan(CLONE_B, store, victim)
            self.assertEqual(self._last_row(plan, "iteminfo"), (FIXTURE / "expected" / f"iteminfo_{CLONE_B}.bin").read_bytes(), "ItemInfo row differs from the spike's")
            self.assertEqual(self._store_row(plan, store), self._expected_store(store, CLONE_B), store)
            self._assert_groups(plan, keep=CLONE_B, drop=CLONE_A)
            self._assert_paloc(plan, CLONE_B)
            self._assert_strings(plan)
            self._assert_pappt(plan)
            self._assert_files(plan)

    # ------------------------------------------------------------------ assertions

    def _store_row(self, plan: NewItemPlan, store: str) -> bytes:
        payload = plan.loose_files[f"{BIN}/storeinfo.pabgb"]
        header = plan.loose_files[f"{BIN}/storeinfo.pabgh"]
        return {row.name: row for row in parse_store_table(payload, header)}[store].raw

    def _assert_groups(self, plan: NewItemPlan, *, keep: int, drop: int) -> None:
        payload = plan.loose_files[f"{BIN}/itemgroupinfo.pabgb"]
        header = plan.loose_files[f"{BIN}/itemgroupinfo.pabgh"]
        mine = {str(g.key): list(g.members) for g in parse_item_group_table(payload, header)}
        expected = {key: [m for m in value["members"] if m != drop] for key, value in self.golden["item_groups"].items()}
        self.assertEqual(mine, expected, "item group memberships differ from the spike's")
        for members in mine.values():
            self.assertIn(keep, members)

    def _assert_paloc(self, plan: NewItemPlan, key: int) -> None:
        item = self.spec["items"][str(key)]
        for language, records in self.golden["paloc"].items():
            table = parse_paloc(plan.loose_files[f"{LOC}/localizationstring_{language}.paloc"]).index()
            for category, loc_key, text, reserved in records:
                if loc_key not in (item["name_key"], item["desc_key"]):
                    continue
                entry = table[loc_key]
                self.assertEqual((entry.category, entry.text, entry.reserved), (category, text, reserved), f"{language} {loc_key}")

    def _assert_strings(self, plan: NewItemPlan) -> None:
        payload = plan.loose_files[f"{BIN}/stringinfo.pabgb"]
        header = plan.loose_files[f"{BIN}/stringinfo.pabgh"]
        spans = parse_pabgh_table(header, payload=payload).row_spans(len(payload))
        rows = {row.row_id: payload[s:e] for row, s, e in spans}
        for text, hex_row in self.golden["stringinfo_rows"].items():
            self.assertEqual(rows[stringinfo_key(text)], bytes.fromhex(hex_row), text)
        texts = {row.key: row.text for row in parse_stringinfo(payload, header)}
        self.assertEqual(texts[stringinfo_key(f"{NEW_STEM}_r")], f"{NEW_STEM}_r")

    def _assert_pappt(self, plan: NewItemPlan) -> None:
        table = parse_pappt(plan.loose_files["character/bin__/partprefabtable.pappt"])
        stems = [record.stem for record in table.records]
        for stem, expected in self.golden["pappt_records"].items():
            record = table.find(stem)
            self.assertIsNotNone(record, stem)
            self.assertEqual(
                {"folder": record.folder, "sockets_path": record.sockets_path, "extra": record.extra, "flag": record.flag, "parts": [[p.name, p.flag] for p in record.parts]},
                expected, stem,
            )
        # both new records sit right beside the template's, as the spike spliced them (order within the pair is free)
        anchor = stems.index("cd_phm_01_sword_0109_r")
        self.assertEqual(sorted(stems[anchor + 1:anchor + 3]), sorted([f"{NEW_STEM}_l", f"{NEW_STEM}_r"]))

    def _assert_files(self, plan: NewItemPlan) -> None:
        added = {request.path: request.payload_data for request in plan.additions}
        for hand in ("r", "l"):
            path = f"character/bin__/prefab/{FOLDER}/{NEW_STEM}_{hand}.prefab"
            self.assertEqual(added[path], (FIXTURE / "expected" / f"{NEW_STEM}_{hand}.prefab").read_bytes(), path)
        for path, digest in self.golden["new_file_sha256"].items():
            self.assertEqual(hashlib.sha256(added[path]).hexdigest(), digest, path)
        self.assertEqual(sorted(added), sorted(list(self.golden["new_file_sha256"]) + [f"character/bin__/prefab/{FOLDER}/{NEW_STEM}_{h}.prefab" for h in ("r", "l")]))


if __name__ == "__main__":
    unittest.main()
