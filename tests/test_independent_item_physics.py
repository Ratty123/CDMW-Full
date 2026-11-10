"""Physics is a checked stock copy, never an opaque payload to transplant."""
from dataclasses import replace
import hashlib
import struct
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cdmw.core import archive_hkx_copy as hkx_copy
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.equipment_visibility import POSTFIX_PATH, matching_postfixes
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services.independent_item_install import resolve_items
from cdmw.services.independent_item_package import from_plan, package_bytes, read_package
from cdmw.domain.new_item.spec import ModelSource
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.services.independent_item_physics import audit_physics_copy, _material_binding
from cdmw.services.new_item_planning import ModelFiles
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_skinning import strip_template_material_physics
from cdmw.services.new_item_variants import xml_path
from tests.test_archive_overlay_manager import shop_spec
from tests.test_independent_items import imported_game
from tests.test_new_item_service import PAC, PAC_XML, HKX, build_package, imported_pac, _read
from tests.test_new_item_variant_authoring import selections

CATALOGUE = 'character/descriptors/pbd/pbdconfig.xml'
PROFILE = 'character/descriptors/pbd/material/test.xml'
POSTFIX = b'<PostfixCondition Type="Hide" SourcePartPrefabPostfix="_R"><TargetPart PartName="CD_Hair"/></PostfixCondition>'


def chunk(tag, data, *, container=False):
    return struct.pack('>I', (0 if container else 0x40000000) | (len(data) + 8)) + tag + data


@pytest.fixture
def collision(monkeypatch):
    # Synthetic type dictionary. Production's two shipped dictionary witnesses
    # stay closed; this fixture tests boundaries without committing game assets.
    types = chunk(b'TYPE', chunk(b'MTTP', bytes(4)) + chunk(b'TST1', b'hknpConvexShape\0')
                  + chunk(b'TNA1', bytes((2, 0, 0))) + chunk(b'TPAD', b''), container=True)
    monkeypatch.setitem(hkx_copy._SCHEMAS, hashlib.sha256(types).hexdigest(), 'hknpConvexShape')
    records = bytes(12) + struct.pack('<III', 0x10000001, 0, 1)
    return chunk(b'TAG0', chunk(b'SDKV', b'20240200') + chunk(b'DATA', bytes(64)) + types
                 + chunk(b'INDX', chunk(b'ITEM', records), container=True), container=True)


def physics_game(path, collision, *, postfix=False):
    _, original = imported_game(path)
    files = {key: original.payload(key) for key in original.entries}
    files[HKX] = collision
    files[PAC_XML] = files[PAC_XML].replace(b'_jiggleWindWeight="0"', b'_jiggleWindWeight="0" _pbdSimulationMaterialName="TestCloth"')
    files[CATALOGUE] = b'<Config><Material Name="TestCloth" Filename="Material/Test.xml"/></Config>'
    files[PROFILE] = b'<Profile><Damping>8.125</Damping><UnknownAuthoredSetting Value="7"/></Profile>'
    if postfix:
        files[POSTFIX_PATH] = POSTFIX
    entries = parse_archive_pamt(build_package(path / 'game', files))
    service = NewItemService()
    return service, service.build_snapshot(entries, read_entry=_read)


def owned_copy(snapshot):
    model = PAC.replace('.pac', '_copy.pac')
    physics = HKX.replace('.hkx', '_copy.hkx')
    return physics, {model: snapshot.payload(PAC), xml_path(model): snapshot.payload(PAC_XML)}, {model: [(PAC, '')]}


def test_collision_copy_checks_sections_and_item_boundaries(collision):
    hkx_copy.validate_hkx_copy_source(collision)
    invalid = [collision[:-1], collision + b'extra', collision.replace(b'20240200', b'20250100'),
               collision.replace(b'hknpConvexShape', b'hknpUnknownType')]
    offset = collision.index(b'ITEM') + 16
    for flags, position, count in ((0x10000002, 0, 1), (0x30000001, 0, 1),
                                    (0x10000001, 64, 1), (0x10000001, 0, 0)):
        edited = bytearray(collision)
        struct.pack_into('<III', edited, offset, flags, position, count)
        invalid.append(bytes(edited))
    for data in invalid:
        with pytest.raises(ValueError, match='unverified collision layout'):
            hkx_copy.validate_hkx_copy_source(data)


def test_unchanged_physics_pins_cloth_and_allows_render_material_edits(tmp_path, collision):
    _, snapshot = physics_game(tmp_path, collision)
    physics, outputs, bindings = owned_copy(snapshot)
    side = next(path for path in outputs if path.endswith('.pac_xml'))
    outputs[side] = outputs[side].replace(b'<Vector Name="_parameters">',
        b'<Vector Name="_parameters"><MaterialParameterFloat _name="_emissiveIntensity" _value="0.45"/>')
    required = set()
    audit_physics_copy(physics, collision, outputs, bindings, snapshot, required.add)
    assert {HKX, PAC_XML, CATALOGUE, PROFILE} <= required


@pytest.mark.parametrize('changed', ['collision', 'mesh', 'cloth', 'missing_sidecar', 'ambiguous_mesh', 'missing_profile'])
def test_changed_or_incomplete_physics_graph_refuses(tmp_path, collision, changed):
    _, snapshot = physics_game(tmp_path, collision)
    physics, outputs, bindings = owned_copy(snapshot)
    data = collision
    model = next(iter(bindings))
    side = xml_path(model)
    if changed == 'collision':
        data = data[:-1] + bytes((data[-1] ^ 1,))
    elif changed == 'mesh':
        outputs[model] += b'changed geometry or skin/cloth data'
    elif changed == 'cloth':
        outputs[side] = outputs[side].replace(b'TestCloth', b'OtherCloth')
    elif changed == 'missing_sidecar':
        del outputs[side]
    elif changed == 'ambiguous_mesh':
        bindings[model].append(('character/model/other.pac', ''))
    elif changed == 'missing_profile':
        original = snapshot.payload
        snapshot = SimpleNamespace(entry=snapshot.entry, payload=lambda path: b'<Config/>' if path == CATALOGUE else original(path))
    with pytest.raises(IndependentItemError):
        audit_physics_copy(physics, data, outputs, bindings, snapshot, lambda path: None)


@pytest.mark.parametrize('xml', [b'<x>' * 66 + b'</x>' * 66,
    b'<!DOCTYPE x [<!ENTITY data "test">]><x/>',
    b'<Material _pbdSimulationMaterialName="hidden"/>'])
def test_material_comparison_rejects_unbounded_or_hidden_physics(xml):
    with pytest.raises(ValueError):
        _material_binding(xml)


@pytest.mark.parametrize('reverse', [False, True])
def test_physics_packages_roundtrip_and_resolve_distinct_assets(tmp_path, collision, reverse):
    packages, plans = [], []
    for ordinal in range(2):
        service, snapshot = physics_game(tmp_path / f'author{ordinal}', collision, postfix=True)
        choice = replace(shop_spec('SamePhysicsItem'), variants=(selections(snapshot)[0],))
        plan = service.plan(choice, snapshot, capture_independent=True)
        assert POSTFIX_PATH not in plan.loose_files
        assert any(matching_postfixes(POSTFIX, source) for source in plan.manifest['pappt_records'])
        for source, owned in plan.manifest['pappt_records'].items():
            assert matching_postfixes(POSTFIX, source) == matching_postfixes(POSTFIX, owned)
        package = from_plan(plan, uuid4().hex)
        assert read_package(package_bytes(package)) == package
        assert {HKX, PAC_XML, CATALOGUE, PROFILE} <= package.dependencies.keys()
        plans.append(plan)
        packages.append(package)
    assert plans[0].spec.item_key == plans[1].spec.item_key
    assert plans[0].spec.stem == plans[1].spec.stem
    physics_game(tmp_path / 'recipient', collision, postfix=True)
    selected = packages[::-1] if reverse else packages
    resolved = resolve_items([package_bytes(p) for p in selected], tmp_path / 'recipient/game')
    paths = []
    for _package, changes in resolved.contributions:
        owned_physics = [path for path, value in changes.items() if path.endswith('.hkx') and value['before'] is None]
        assert len(owned_physics) == 1
        path = owned_physics[0]
        assert changes[path]['after'] == collision
        assert POSTFIX_PATH not in changes
        paths.append(path)
    assert len(set(paths)) == 2
    assert not (tmp_path / 'recipient/game/.cdmw/independent-items.json').exists()


def test_unknown_stock_collision_is_not_accepted_just_because_it_is_stock(tmp_path):
    service, snapshot = physics_game(tmp_path, b'opaque collision payload')
    choice = replace(shop_spec('UnknownPhysics'), variants=(selections(snapshot)[0],))
    with pytest.raises(IndependentItemError, match='unverified collision layout'):
        service.plan(choice, snapshot, capture_independent=True)


def replacement_plan(service, snapshot, name, route, **options):
    if route == 'variant':
        choice = replace(selections(snapshot)[0], custom_model=True)
        return service.plan(replace(shop_spec(name), variants=(choice,)), snapshot,
                            variant_models={choice.identity: ModelFiles(imported_pac(100))}, **options)
    return service.plan(replace(shop_spec(name), model_source=ModelSource.IMPORTED), snapshot,
                        model=ModelFiles(imported_pac(100)), **options)


@pytest.mark.parametrize('route', ['variant', 'family'])
def test_replacement_mesh_package_carries_the_template_collision_shape(tmp_path, collision, route):
    # Game 2.04.02 logs every model stem it finds no mesh physics for. The
    # replacement keeps the template's rigid shape; its cloth is stripped.
    service, snapshot = physics_game(tmp_path / 'author', collision)
    plan = replacement_plan(service, snapshot, 'ReplacementPhysics', route, capture_independent=True)
    owned = [path for path in plan.new_paths if path.endswith('.hkx')]
    assert [plan.loose_files[path] for path in owned] == [collision]
    model = 'character/model/' + owned[0][len('character/bin__/meshphysics/'):-4] + '.pac'
    assert b'TestCloth' not in plan.loose_files[xml_path(model)]
    package = from_plan(plan, uuid4().hex)
    assert read_package(package_bytes(package)) == package
    assert HKX in package.dependencies
    physics_game(tmp_path / 'recipient', collision)
    resolved = resolve_items([package_bytes(package)], tmp_path / 'recipient/game')
    (_package, changes), = resolved.contributions
    assert [value['after'] for path, value in changes.items()
            if path.endswith('.hkx') and value['before'] is None] == [collision]


@pytest.mark.parametrize('kept', [None, 'material', 'jiggle', 'layout'])
def test_replacement_mesh_keeps_the_collision_shape_never_template_cloth(tmp_path, collision, kept, monkeypatch):
    _, snapshot = physics_game(tmp_path, collision)
    physics, outputs, bindings = owned_copy(snapshot)
    model = next(iter(bindings))
    outputs[model] = imported_pac(100)
    if kept != 'material':
        outputs[xml_path(model)] = strip_template_material_physics(outputs[xml_path(model)])
    if kept == 'jiggle':
        mesh = bytearray(outputs[model])
        mesh[pac_cloth_lods(outputs[model])[0].submeshes[0].source_vertex_offsets[0] + 38] = 0
        outputs[model] = bytes(mesh)
    elif kept == 'layout':
        monkeypatch.setattr(hkx_copy, '_SCHEMAS', {})
    if kept is None:
        audit_physics_copy(physics, collision, outputs, bindings, snapshot, lambda path: None)
        return
    with pytest.raises(IndependentItemError, match='unverified collision layout' if kept == 'layout' else 'replacement model'):
        audit_physics_copy(physics, collision, outputs, bindings, snapshot, lambda path: None)


@pytest.mark.parametrize('route', ['variant', 'family'])
def test_unrecognised_collision_stays_out_of_a_replacement_package_not_a_loose_export(tmp_path, route):
    service, snapshot = physics_game(tmp_path, b'opaque collision payload')
    package = replacement_plan(service, snapshot, 'OpaqueReplacement', route, capture_independent=True)
    assert not any(path.endswith('.hkx') for path in package.new_paths)
    assert any('packages' in line for line in package.summary_lines), package.summary_lines
    loose = replacement_plan(service, snapshot, 'OpaqueReplacement', route)
    assert [loose.loose_files[path] for path in loose.new_paths if path.endswith('.hkx')] == [b'opaque collision payload']


def test_variant_collision_retry_preserves_inherited_rule_suffix(tmp_path, collision, monkeypatch):
    service, snapshot = physics_game(tmp_path, collision, postfix=True)
    choice = replace(shop_spec('SamePhysicsItem'), variants=(selections(snapshot)[0],))
    first = service.plan(choice, snapshot, capture_independent=True)
    occupied = next(path for path in first.new_paths if path.endswith('.prefab'))
    has_entry = type(snapshot).has_entry
    monkeypatch.setattr(type(snapshot), 'has_entry', lambda self, path: path.lower() == occupied.lower() or has_entry(self, path))
    second = service.plan(choice, snapshot, capture_independent=True)
    assert second.manifest['pappt_records'] != first.manifest['pappt_records']
    assert POSTFIX_PATH not in second.loose_files
    for source, target in second.manifest['pappt_records'].items():
        assert matching_postfixes(POSTFIX, source) == matching_postfixes(POSTFIX, target) == ('_R',)


@pytest.mark.parametrize('route', ['variant', 'family'])
@pytest.mark.parametrize('painted', [True, False])
def test_kept_physics_on_a_replacement_needs_cloth_painted_for_it(tmp_path, collision, route, painted, monkeypatch):
    """Template cloth / physics stays on for a painted model. Its simulation bindings were
    written for it, so the package checks them as its own; the same bytes on an unpainted
    replacement are the template's, copied by index, and stay refused."""
    from cdmw.services import independent_item_physics as physics_audit

    audited = []
    real = physics_audit.audit_painted_cloth
    monkeypatch.setattr(physics_audit, 'audit_painted_cloth',
                        lambda path, *args, **kwargs: (audited.append(path), real(path, *args, **kwargs))[1])
    service, snapshot = physics_game(tmp_path, collision)
    model = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)}, cloth_painted=painted)
    if route == 'variant':
        choice = replace(selections(snapshot)[0], custom_model=True, keep_template_physics=True)
        spec, models = replace(shop_spec('PaintedPhysics'), variants=(choice,)), {'variant_models': {choice.identity: model}}
    else:
        spec = replace(shop_spec('PaintedPhysics'), model_source=ModelSource.IMPORTED, keep_template_physics=True)
        models = {'model': model}
    if not painted:
        with pytest.raises(IndependentItemError, match='replacement model'):
            service.plan(spec, snapshot, capture_independent=True, **models)
        assert audited == []
        return
    plan = service.plan(spec, snapshot, capture_independent=True, **models)
    owned = [path for path in plan.new_paths if path.endswith('.hkx')]
    assert [plan.loose_files[path] for path in owned] == [collision]
    assert audited == ['character/model/' + owned[0][len('character/bin__/meshphysics/'):-4] + '.pac']
    package = from_plan(plan, uuid4().hex)
    assert read_package(package_bytes(package)) == package


def test_recipient_cloth_profile_changes_refuse(tmp_path, collision):
    service, source = physics_game(tmp_path / 'author', collision)
    choice = replace(shop_spec('Physics'), variants=(selections(source)[0],))
    package = from_plan(service.plan(choice, source, capture_independent=True), uuid4().hex)
    _, destination = physics_game(tmp_path / 'recipient', collision)
    files = {path: destination.payload(path) for path in destination.entries}
    files[PROFILE] = b'<Profile><Damping>0</Damping></Profile>'
    build_package(tmp_path / 'recipient/game', files)
    with pytest.raises(IndependentItemError, match='dependency|game data|changed|differs'):
        resolve_items([package_bytes(package)], tmp_path / 'recipient/game')
