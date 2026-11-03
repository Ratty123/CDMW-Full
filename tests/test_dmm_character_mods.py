"""Installed-file discovery and update guards use owned, mutable DMM fixtures."""
import json
from types import SimpleNamespace
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.dmm_character_mods import scan_character_library, character_model_paths, normalized
from cdmw.services.dmm_character_models import retain_installed_sources, validate_installed_sources
from cdmw.services.new_item_provenance import StaleNewItemSource
from tests.test_new_item_provenance import setup_game, spec


def write(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
    return target


def manifest(root, folder, title, version):
    return write(root, folder + '/mod.json', json.dumps({'modinfo': {'title': title, 'version': version}}))


@pytest.fixture
def installed(tmp_path):
    install = tmp_path / 'DMM'
    write(install, 'DMM.exe', b'owned fixture; never executable')
    mods = install / 'Library'
    manifest(mods, 'renamed/creator', 'Character Creator Enhanced - Anywhere', '9.1.30')
    manifest(mods, 'fit', 'Female Armor Fit', '1.0.9')
    manifest(mods, 'module', 'Female Armor Module', '3.1')
    model = 'character/model/1_pc/1_phm/armor/9_upperbody/zz_test.pac'
    write(mods, 'fit/0009/' + model, b'owned model')
    for folder, group in (('fit', 'FemaleFitBodies'), ('module', 'FemaleArmorModuleBodies')):
        write(mods, folder + '/0009/character/descriptors/conditionalpartprefab/conditionalpartprefab_common.xml',
              f'<PartPrefabGroup Name="{group}"><PartPrefab Name="body" WholeWord="True"/></PartPrefabGroup>'
              f'<Condition SourcePartPrefab="original"><If Type="Match" TargetPartPrefab="zz_test" MatchPartPrefabGroup="{group}"/></Condition>')
    config = {'configVersion': 1, 'modsPath': 'Library', 'activeBrowserMods': ['fit'],
              'activeMods': [{'fileName': 'renamed/creator/Equip All Armor.json', 'disabledIndices': []}],
              'activeAsiMods': ['CharacterCreator'], 'definitiveLoadOrder': ['browser:module']}
    write(install, 'config.json', json.dumps(config))
    return install, mods, model, config


def test_versions_nested_roots_selection_and_alternatives(installed):
    install, mods, model, _ = installed
    library = scan_character_library(str(install))
    assert library.mods_folder == mods
    assert {m.kind: m.version for m in library.mods} == {'creator': '9.1.30', 'fit': '1.0.9', 'module': '3.1'}
    assert library.mod('fit').selected
    assert not library.mod('module').selected  # Load-order presence is not selection.
    assert library.equip_all_selected and library.creator_asi_selected
    assert character_model_paths(library, 'fit').paths == (model,)
    assert model not in library.sources('module')
    with pytest.raises(ValueError, match='DMM was not found'):
        scan_character_library(str(install / 'missing'))


@pytest.mark.parametrize('change', ('replace', 'add', 'delete', 'version', 'config'))
def test_update_without_reimport_or_version_bump_invalidates_old_source(installed, change):
    install, mods, model, config = installed
    old = scan_character_library(str(install))
    if change == 'replace':
        write(mods, 'fit/0009/' + model, b'changed mesh')
    elif change == 'add':
        write(mods, 'fit/0009/' + model.replace('zz_test', 'new_refit'), b'new mesh')
    elif change == 'delete':
        (mods / 'fit/0009' / model).unlink()
    elif change == 'version':
        manifest(mods, 'fit', 'Female Armor Fit', '1.0.10')
    else:
        config['activeBrowserMods'] = ['module']
        write(install, 'config.json', json.dumps(config))
    with pytest.raises(StaleNewItemSource):
        old.revision.validate()
    new = scan_character_library(str(install))
    assert new.identity != old.identity
    if change == 'add':
        assert len(character_model_paths(new, 'fit').paths) == 2


def test_missing_module_targets_are_reported_not_guessed(installed):
    install, _, _, _ = installed
    snapshot = SimpleNamespace(pappt=SimpleNamespace(records=()), entry_paths_with_extensions=lambda _ext: (), has_entry=lambda _: False)
    result = character_model_paths(scan_character_library(str(install)), 'module', snapshot)
    assert not result.paths and result.unresolved == ('zz_test',)


def test_unknown_rules_and_configuration_refuse_and_cancel_is_observed(installed):
    install, mods, _, config = installed
    stop = threading.Event(); stop.set()
    with pytest.raises(RunCancelled):
        scan_character_library(str(install), stop_event=stop)
    path = mods / 'fit/0009/character/descriptors/conditionalpartprefab/conditionalpartprefab_common.xml'
    path.write_text(path.read_text().replace('Type="Match"', 'Type="FutureRule"'))
    with pytest.raises(ValueError, match='unsupported replacement'):
        scan_character_library(str(install))
    config['configVersion'] = 2
    write(install, 'config.json', json.dumps(config))
    with pytest.raises(ValueError, match='configuration format'):
        scan_character_library(str(install))
    with pytest.raises(ValueError):
        normalized('../outside.pac')


def test_installed_sources_cannot_enter_any_export_plan(installed, tmp_path):
    install, mods, model, _ = installed
    library = scan_character_library(str(install))
    owner = SimpleNamespace(dmm_source_revision=library.revision)
    service, snapshot, _ = setup_game(tmp_path)
    plan = service.plan(spec(), snapshot)
    with pytest.raises(ValueError, match='fitting references only'):
        retain_installed_sources(plan, (owner,))
    with pytest.raises(ValueError, match='fitting references only'):
        validate_installed_sources((owner,))
    assert retain_installed_sources(plan, ()) is plan


def test_names_follow_explicit_item_rule_and_prefab_not_similar_filenames(installed):
    from dataclasses import replace
    from cdmw.core.iteminfo_behavior import read_behavior_fields, set_behavior_fields
    from tests.test_new_item_wearers import _row
    from tests.test_prefab_binary_edit import _build
    install, mods, model, _ = installed
    prefab = 'character/bin__/prefab/owned/zz_test.prefab'
    write(mods, 'fit/0009/' + prefab, _build(model))
    unrelated = model.replace('zz_test', 'zz_test_alike')
    write(mods, 'fit/0009/' + unrelated, b'unnamed')
    row = _row()
    fields = read_behavior_fields(row.raw)
    fields['prefabs'][0]['prefabs'] = [123]
    row = replace(row, raw=set_behavior_fields(row.raw, {'prefabs': fields['prefabs']}))
    snapshot = SimpleNamespace(
        pappt=SimpleNamespace(records=(SimpleNamespace(stem='zz_test', prefab_path=prefab),)),
        rows={row.key: row}, stringinfo_texts={123: 'original'},
        item_display_names=lambda: {row.key: 'White Bloodwind Leather Armor'},
        entry_paths_with_extensions=lambda _ext: (), has_entry=lambda _: False)
    result = character_model_paths(scan_character_library(str(install)), 'fit', snapshot)
    assert dict(result.item_names) == {model: ('White Bloodwind Leather Armor',)}
    assert unrelated in result.paths and unrelated not in dict(result.item_names)


@pytest.mark.parametrize('folder,category', (
    ('1_pc/1_phm/armor/9_upperbody', 'chest'),
    ('1_pc/2_phw/armor_south/10_lowerbody', 'legs'),
    ('1_pc/9_pgm/head/head_sub', 'head'),
    ('1_pc/1_phm/armor/11_hand', 'gloves'),
    ('7_horse/armor/9_upperbody', 'other'),
    ('2_mon/cd_m0001_00_twofeet/armor/9_upperbody', 'chest'),
))
def test_category_describes_part_without_claiming_wearer(folder, category):
    from cdmw.domain.new_item.installed_model_category import character_model_category
    assert character_model_category('character/model/' + folder + '/model.pac') == category
