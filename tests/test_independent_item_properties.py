"""New scalar intent survives portable compilation without extending frozen v1."""
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from cdmw.core.iteminfo_properties import read_item_properties
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.mod_package import UnsupportedCapability
from cdmw.domain.new_item.rules import validate_spec
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.independent_item_codec import encode
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_rebuild, prepare_remove
from cdmw.services.independent_item_package import from_plan, package_bytes, package_metadata, read_package, unpack_recipe
from cdmw.services.independent_mod_package import migrate_v1, read_v2
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_fields import virtual_row
from tests.test_independent_items import setup_game
from tests.test_iteminfo_properties import property_row
from tests.test_new_item_service import _table4
from tests.test_virtual_loader import game_bytes


@pytest.fixture
def equipment_game(monkeypatch):
    from tests import test_new_item_provenance as source
    original = source.current_files

    def files():
        result = original()
        body_path = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
        header_path = body_path.replace('staticinfobody', 'staticinfoheader')
        body, header = result[body_path], result[header_path]
        rows = []
        for directory, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body)):
            raw = body[start:end]
            if parse_iteminfo_row(raw).stat_block_offset is not None:
                raw = property_row(raw, marker=0x12)[0]
            rows.append((directory.row_id, raw))
        result[body_path], result[header_path] = _table4(rows)
        return result

    monkeypatch.setattr(source, 'current_files', files)


@pytest.mark.parametrize('virtual', (False, True))
@pytest.mark.parametrize('values', (
    {'item_tier': 255, 'required_level': 0xffffffff, 'max_durability': 65535},
    {'item_tier': 0, 'required_level': 0, 'max_durability': 0},
))
def test_properties_export_compile_rebuild_and_remove_on_both_routes(tmp_path, equipment_game, virtual, values):
    service, snapshot, _ = setup_game(tmp_path / 'author')
    template = snapshot.rows[1001295].raw
    choice = replace(shop_spec('PropertyItem'), **values)
    plan = service.plan(choice, snapshot, capture_independent=True)
    package = from_plan(plan, uuid4().hex)
    meta = package_metadata(package)
    assert meta['version'] == 2 and meta['requires'] == {'item.legacy': 1, 'item.properties': 1}
    assert {name: getattr(unpack_recipe(package)[0], name) for name in values} == values
    assert read_package(package_bytes(package)) == package
    assert snapshot.rows[1001295].raw == template
    # The retained recipe and original digest still use only the frozen v1 fields.
    legacy = from_plan(replace(plan, spec=replace(plan.spec, **dict.fromkeys(values))), package.identity)
    assert package.recipe == legacy.recipe
    assert meta['provenance']['source_digest'] == legacy.digest
    assert package_metadata(legacy)['version'] == 1
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    before = game_bytes(root)
    backups = Backups(tmp_path)
    if virtual:
        path = tmp_path / 'properties.cditem'
        path.write_bytes(package_bytes(package))
        profile = VirtualProfile((path,))
        prepared = prepare_profile(profile, root)
        publish_profile(prepared)
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        actual = virtual_row(root, key)
        again = prepare_profile(profile, root)
        assert dict(again.files) == dict(prepared.files)
        publish_profile(prepare_profile(VirtualProfile(()), root))
        assert game_bytes(root) == before
    else:
        backups.apply(prepare_install([package_bytes(package)], root).preparation)
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        actual = snapshot_of(root).rows[key]
        backups.apply(prepare_rebuild(package.identity, root).preparation)
        assert snapshot_of(root).rows[key].raw == actual.raw
        backups.apply(prepare_remove(package.identity, root))
        assert game_bytes(root) == before
    assert {name: entry[0] for name, entry in read_item_properties(actual).items()} == values


@pytest.mark.parametrize('mutation', ('empty', 'unknown', 'boolean', 'tier-range', 'level-range',
                                     'durability-range', 'duplicate', 'no-item', 'version'))
def test_invalid_properties_refuse_at_package_admission(tmp_path, mutation):
    service, snapshot, _ = setup_game(tmp_path)
    original = from_plan(service.plan(shop_spec('Original'), snapshot, capture_independent=True), uuid4().hex)
    manifest = deepcopy(migrate_v1(original).manifest)
    data = {'item_tier': 2, 'required_level': None, 'max_durability': None}
    module = {'id': 'properties', 'type': 'item.properties', 'version': 1, 'required': True, 'data': data}
    manifest['requires']['item.properties'] = 1
    manifest['modules'].append(module)
    if mutation == 'empty':
        data['item_tier'] = None
    elif mutation == 'unknown':
        data['weight'] = 12
    elif mutation == 'boolean':
        data['item_tier'] = True
    elif mutation.endswith('-range'):
        name, limit = {'tier-range': ('item_tier', 256), 'level-range': ('required_level', 1 << 32),
                       'durability-range': ('max_durability', 65536)}[mutation]
        data[name] = limit
    elif mutation == 'duplicate':
        manifest['modules'].append(dict(module, id='other_properties'))
    elif mutation == 'no-item':
        manifest['modules'] = [module]
    elif mutation == 'version':
        manifest['requires']['item.properties'] = module['version'] = 99
    with pytest.raises(IndependentItemError):
        read_v2(manifest, original.blobs)


def test_v1_refuses_new_intent_and_unverified_template_refuses_durability(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    for field in ('item_tier', 'required_level', 'max_durability'):
        choice = replace(shop_spec('Extended'), **{field: 0})
        with pytest.raises(IndependentItemError, match='v1'):
            encode(choice)
        invalid = replace(choice, **{field: -1})
        assert any(issue.code == 'item_property.range' and issue.field == field for issue in validate_spec(invalid))
    with pytest.raises(ValueError, match='no verified max_durability'):
        service.plan(replace(shop_spec('Unknown'), max_durability=50), snapshot, capture_independent=True)


def test_partial_level_override_preserves_opaque_durability_and_inherits_other_fields(tmp_path):
    from cdmw.domain.archives.iteminfo_composition import rows_of
    service, snapshot, _ = setup_game(tmp_path)
    template = snapshot.rows[1001295]
    assert 'max_durability' not in read_item_properties(template)
    plan = service.plan(replace(shop_spec('LevelOnly'), required_level=91), snapshot, capture_independent=True)
    package = from_plan(plan, uuid4().hex)
    spec = unpack_recipe(read_package(package_bytes(package)))[0]
    assert (spec.item_tier, spec.required_level, spec.max_durability) == (None, 91, None)
    base = 'gamedata/binarystaticinfo__/bin/iteminfo.'
    row = parse_iteminfo_row(rows_of(plan.loose_files[base + 'staticinfobody'],
                                   plan.loose_files[base + 'staticinfoheader'])[plan.spec.item_key])
    assert read_item_properties(row)['required_level'][0] == 91
    assert row.raw[row.stat_block_end:] == template.raw[template.stat_block_end:]
