from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.item_model_family import FamilyFile, FamilyPart, ItemModelFamily  # noqa: E402
from cdmw.core.pappt_format import PartPrefabPart, PartPrefabRecord  # noqa: E402
from cdmw.domain.new_item.spec import ModelSource, NewItemSpec, SheathedModel  # noqa: E402
from cdmw.services.new_item_effect_targets import effect_target_source_paths, inspect_effect_targets  # noqa: E402
from cdmw.services.new_item_snapshot import EFFECT_DONOR_PATH, EFFECT_DONOR_PREFAB  # noqa: E402
from test_prefab_component_graft import build_prefab  # noqa: E402


def _record(stem: str, folder: str, *, slot: str = "CD_Equipment") -> PartPrefabRecord:
    return PartPrefabRecord(
        stem=stem,
        folder=folder,
        sockets_path="",
        parts=(PartPrefabPart(slot),),
    )


def _family(kind: str, count: int = 1, *, borrowed_only: bool = False) -> ItemModelFamily:
    folder = f"1_pc/01_phm/equipment/{kind.casefold()}"
    parts = []
    files = []
    for index in range(count):
        stem = f"cd_test_{kind.casefold()}_{index:02d}"
        record = _record(stem, folder)
        parts.append(FamilyPart(stem=stem, hash=index + 1, record=record, pac_path=f"character/model/{stem}.pac", owned=not borrowed_only))
        if not borrowed_only:
            files.append(FamilyFile("prefab", record.prefab_path, True))
    return ItemModelFamily(
        item_key=1,
        model_stem=f"cd_test_{kind.casefold()}",
        model_folder=folder,
        parts=tuple(parts),
        files=tuple(files),
        icon_string=None,
        icon_hash=None,
    )


class _Snapshot:
    def __init__(self, family: ItemModelFamily, payloads: dict[str, bytes]) -> None:
        self._family = family
        self._payloads = {path.casefold(): data for path, data in payloads.items()}

    def family(self, _key: int) -> ItemModelFamily:
        return self._family

    def has_entry(self, path: str) -> bool:
        return str(path).casefold() in self._payloads

    def payload(self, path: str) -> bytes:
        return self._payloads[str(path).casefold()]


def _compatible_prefab(mesh_path: str) -> bytes:
    return build_prefab(
        component="SkinnedMeshComponent",
        member_kind="pointer",
        value=mesh_path,
        pointee_type="ResourceReferencePath_SkinnedMesh",
    )


def _donor() -> bytes:
    return build_prefab(
        component="EffectComponent",
        member_kind="object",
        value=EFFECT_DONOR_PATH,
        with_transform=True,
        pointee_type="EffectDataReferencePath",
    )


def _spec(**changes) -> NewItemSpec:
    values = dict(
        template_key=1,
        internal_name="Effect_Target_Test",
        display_names={"eng": "Effect target test"},
        effect="fx_test.level.effect",
    )
    values.update(changes)
    return NewItemSpec(**values)


class EffectTargetTests(unittest.TestCase):
    def _snapshot(self, family: ItemModelFamily, *, broken: tuple[str, ...] = ()) -> _Snapshot:
        payloads = {EFFECT_DONOR_PREFAB: _donor()}
        for item in family.files_for("prefab"):
            payloads[item.path] = b"not a prefab" if item.path in broken else _compatible_prefab(f"character/model/{Path(item.path).stem}.pac")
        return _Snapshot(family, payloads)

    def test_weapon_armour_accessory_and_other_families_share_the_structural_preflight(self) -> None:
        for kind in ("Weapon", "Armour", "Accessory", "Lantern"):
            with self.subTest(kind=kind):
                family = _family(kind)
                result = inspect_effect_targets(self._snapshot(family), _spec())
                self.assertTrue(result.supported, result.errors)
                self.assertEqual(result.target_prefabs, tuple(item.path for item in family.files_for("prefab")))

    def test_every_owned_prefab_must_pass_and_one_failure_refuses_the_whole_set(self) -> None:
        family = _family("Multi", count=3)
        broken = family.files_for("prefab")[1].path
        result = inspect_effect_targets(self._snapshot(family, broken=(broken,)), _spec())
        self.assertFalse(result.supported)
        self.assertEqual(result.target_prefabs, tuple(item.path for item in family.files_for("prefab")))
        self.assertEqual(len(result.errors), 1)
        self.assertIn(broken, result.errors[0])

    def test_a_borrowed_only_family_never_turns_a_shared_prefab_into_an_effect_target(self) -> None:
        family = _family("Borrowed", borrowed_only=True)
        result = inspect_effect_targets(self._snapshot(family), _spec())
        self.assertFalse(result.supported)
        self.assertEqual(result.target_prefabs, ())
        self.assertIn("no clonable prefab", result.message)

    def test_only_explicitly_owned_sheathed_variants_extend_the_target_set(self) -> None:
        base = _family("Weapon")
        sheath = _record("cd_test_weapon_r_in", base.model_folder, slot="CD_Equipment_IN_R")
        borrowed = FamilyPart(
            stem=sheath.stem,
            hash=99,
            record=sheath,
            pac_path="character/model/shared_sheath.pac",
            owned=False,
        )
        family = ItemModelFamily(
            item_key=base.item_key,
            model_stem=base.model_stem,
            model_folder=base.model_folder,
            parts=(*base.parts, borrowed),
            files=base.files,
            icon_string=None,
            icon_hash=None,
        )
        self.assertNotIn(sheath.prefab_path, effect_target_source_paths(family))
        targets = effect_target_source_paths(
            family,
            model_source=ModelSource.IMPORTED,
            sheathed_model=SheathedModel.OWN_MODEL,
        )
        self.assertEqual(targets, (base.files[0].path, sheath.prefab_path))


if __name__ == "__main__":
    unittest.main()
