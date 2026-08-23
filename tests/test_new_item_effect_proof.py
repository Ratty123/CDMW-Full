from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.services.new_item_effect_targets import EffectTargetCompatibility
from tools.new_item_effect_proof import (
    _atomic_json,
    _confirmation,
    _family_kind,
    _fit_and_center,
    _system_temp_output,
    select_representatives,
)


def test_real_archive_family_categories_are_asset_neutral() -> None:
    assert _family_kind("OneHandSword", ("character/model/1_pc/weapon/item.pac",)) == "weapon"
    assert _family_kind("Cloak", ("character/model/1_pc/armor/cloak.pac",)) == "armour"
    assert _family_kind("BackPack", ("character/model/1_pc/armor/18_acc/bag.pac",)) == "accessory"
    assert _family_kind("ToolHammer", ("character/model/6_object/tools/hammer.pac",)) == ""


def test_representatives_use_bekker_then_first_compatible_sorted_family() -> None:
    records = {
        1: ("OneHandSword", "Earlier_OneHandSword", "character/model/1_pc/weapon/a.pac"),
        2: ("OneHandSword", "Bekker_OneHandSword", "character/model/1_pc/weapon/b.pac"),
        3: ("Cloak", "A_Cloak", "character/model/1_pc/armor/a.pac"),
        4: ("Cloak", "B_Cloak", "character/model/1_pc/armor/b.pac"),
        5: ("BackPack", "A_Backpack", "character/model/1_pc/armor/18_acc/a.pac"),
    }

    class Snapshot:
        rows = {key: SimpleNamespace(string_key=name) for key, (_equip, name, _path) in records.items()}

        @staticmethod
        def equip_type_name(row):
            return next(equip for equip, name, _path in records.values() if name == row.string_key)

        @staticmethod
        def family(key):
            path = records[key][2]
            return SimpleNamespace(files=(SimpleNamespace(path=path, exists=True),))

    class Service:
        @staticmethod
        def inspect_effect_targets(spec, _snapshot):
            supported = spec.template_key in {1, 2, 4, 5}
            return EffectTargetCompatibility(supported, (f"target/{spec.template_key}.prefab",), () if supported else ("bad",))

    selected = select_representatives(Snapshot(), Service())
    assert [(item.category, item.template_key) for item in selected] == [
        ("weapon", 2),
        ("armour", 4),
        ("accessory", 5),
    ]


def test_fit_to_item_matches_the_workspace_scale_and_center_rules() -> None:
    item = SimpleNamespace(bbox_min=(-1.0, 1.0, -3.0), bbox_max=(1.0, 5.0, 1.0))
    effect = SimpleNamespace(box_min=(-10.0, -2.0, -1.0), box_max=(10.0, 2.0, 1.0))
    scale, center = _fit_and_center(item, effect)
    assert scale == 0.2
    assert center == (0.0, 3.0, -1.0)


def test_proof_writes_atomically_only_under_system_temp() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = _system_temp_output(Path(folder))
        path = root / "proof.json"
        _atomic_json(path, {"ok": True})
        assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}
        assert list(root.glob(".proof.json.*.tmp")) == []
    with pytest.raises(ValueError, match="system temp"):
        _system_temp_output(Path(__file__).resolve().parents[1] / "proof-output")


def test_mutating_proof_actions_use_exact_category_tokens() -> None:
    assert _confirmation("install", "weapon") == "INSTALL-WEAPON-EFFECT-PROOF"
    assert _confirmation("remove", "accessory") == "REMOVE-ACCESSORY-EFFECT-PROOF"
