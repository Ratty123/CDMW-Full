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
    result = send_item_packages(files, root, mods, "Two items")
    assert result.folder == mods / "Two items" and not result.replaced
    manifest = json.loads((result.folder / "manifest.json").read_text(encoding="utf-8"))
    overrides = manifest["overrides"]
    # One copy of each shared table, carrying both items, rather than two mods that hide each other.
    assert len(overrides) == len(set(overrides))
    assert "gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody" in overrides
    assert (result.folder / "0036" / "0.pamt").is_file()
    assert game_bytes(root) == before and not (root / ".cdmw").exists()
    again = send_item_packages(files, root, mods, "Two items")
    assert again.replaced
