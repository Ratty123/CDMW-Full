"""Send to DMM writes a new item into DMM's mods folder without touching foreign folders."""
import json

import pytest

from cdmw.services.dmm_send import destination, dmm_mods_folder, find_dmm, send_plan
from tests.test_new_item_compact_dlc import setup, spec


def _dmm(tmp_path, mods_path=None):
    install = tmp_path / "DMM"
    install.mkdir()
    (install / "DMM.exe").write_bytes(b"MZ")
    mods = install / "mods" if mods_path is None else mods_path
    mods.mkdir(parents=True, exist_ok=True)
    if mods_path is not None:
        (install / "config.json").write_text(json.dumps({"modsPath": str(mods_path)}), encoding="utf-8")
    return install, mods


def test_dmm_folder_comes_from_its_own_config_and_must_hold_dmm_exe(tmp_path):
    install, mods = _dmm(tmp_path, tmp_path / "elsewhere" / "mods")
    assert find_dmm(str(install)) == install
    assert dmm_mods_folder(install) == mods
    with pytest.raises(ValueError, match="DMM.exe"):
        dmm_mods_folder(tmp_path / "elsewhere")


def test_a_folder_cdmw_did_not_write_is_never_replaced(tmp_path):
    _install, mods = _dmm(tmp_path)
    (mods / "Frost").mkdir()
    (mods / "Frost" / "manifest.json").write_text(json.dumps({"generator": "Someone else"}), encoding="utf-8")
    with pytest.raises(ValueError, match="CDMW did not write"):
        destination(mods, "Frost")
    assert destination(mods, "Ember") == (mods / "Ember", False)


def test_send_writes_the_dmm_mod_and_a_resend_replaces_only_cdmws_copy(tmp_path):
    service, snapshot = setup(tmp_path)
    plan = service.plan(spec("CompactOwned"), snapshot, capture_independent=True)
    _install, mods = _dmm(tmp_path)
    first = send_plan(plan, mods, "Frost blade", service=service)
    assert first.folder == mods / "Frost blade" and not first.replaced
    assert (first.folder / "0036" / "0.pamt").is_file()
    assert json.loads((first.folder / "manifest.json").read_text(encoding="utf-8"))["manager_targets"] == ["dmm"]
    (first.folder / "stale.txt").write_text("from the earlier send", encoding="utf-8")
    second = send_plan(plan, mods, "Frost blade", service=service)
    assert second.replaced and not (second.folder / "stale.txt").exists()
    assert sorted(path.name for path in mods.iterdir()) == ["Frost blade"]
    assert not any(path.name.startswith(".cdmw-send-") for path in mods.parent.iterdir())


def test_several_packages_go_to_dmm_as_one_composed_mod(tmp_path):
    from cdmw.services.dmm_send import send_item_packages
    from tests.test_virtual_loader import game_bytes, packages
    root, files = packages(tmp_path)
    before = game_bytes(root)
    _install, mods = _dmm(tmp_path)
    steps = []
    result = send_item_packages(files, root, mods, "Two items", on_progress=lambda value, total, detail: steps.append(value))
    assert result.folder == mods / "Two items" and not result.replaced
    manifest = json.loads((result.folder / "manifest.json").read_text(encoding="utf-8"))
    overrides = manifest["overrides"]
    # One copy of each shared table, carrying both items, rather than two mods that hide each other.
    assert len(overrides) == len(set(overrides))
    assert "gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody" in overrides
    # DMM reads every .json in a mod folder as a mod; only what DMM needs is shipped.
    shipped = {p.relative_to(result.folder).as_posix() for p in result.folder.rglob("*") if p.is_file()}
    assert shipped - {"meta/0.pathc"} == {"0036/0.pamt", "0036/0.paz", "manifest.json", "modinfo.json",
                                         "CDMW items - shops and groups.json"}
    # Shops and groups go as additions DMM applies to base and DLC rows, not as table copies.
    operations = json.loads((result.folder / "CDMW items - shops and groups.json").read_text(encoding="utf-8"))
    ops = {target["file"]: target["intents"] for target in operations["targets"]}
    assert operations["format"] == 3 and ops["storeinfo.pabgb"]
    assert all(intent["op"] == "array_append" for intent in ops["storeinfo.pabgb"])
    assert not any("storeinfo" in path or "itemgroupinfo" in path for path in overrides)
    # Archives stay as shipped; only the item identities are kept beside them.
    assert game_bytes(root) == before
    assert [p.relative_to(root).as_posix() for p in (root / ".cdmw").rglob("*") if p.is_file()] == [".cdmw/independent-items.json"]
    assert steps == sorted(steps) and steps[-1] == 100
    again = send_item_packages(files, root, mods, "Two items")
    assert again.replaced


def test_a_later_send_keeps_every_item_key(tmp_path):
    from cdmw.services.dmm_send import send_item_packages
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.independent_item_package import read_package
    from tests.test_virtual_loader import packages
    root, files = packages(tmp_path, count=3)
    _install, mods = _dmm(tmp_path)
    send_item_packages(files, root, mods, "CDMW items")
    first = {identity: row["values"] for identity, row in load_registry(root)["items"].items()}
    # Dropping the first item and reordering the rest must not renumber them.
    send_item_packages(tuple(reversed(files[1:])), root, mods, "CDMW items")
    second = {identity: row["values"] for identity, row in load_registry(root)["items"].items()}
    for path in files[1:]:
        identity = read_package(path).identity
        assert second[identity] == first[identity]
