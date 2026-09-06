"""Effect recipes exercise the actual binary writer, preview and draft contracts."""
from dataclasses import replace
from pathlib import Path
import copy
import json

import pytest

from cdmw.core.effect_binary import EffectBinaryError, decode_effect_binary
from cdmw.core.effect_writer import serialize_effect, set_typed_value
from cdmw.domain.new_item.effect_authoring import EffectLayer, EffectLook, EmitterEdit
from cdmw.services.effect_recipe import compile_effect_recipe
from cdmw.services.effect_library_store import recipe_json, read_recipe, write_recipe
from cdmw.services.effect_preview_model import preview_effect_from_snapshot
from cdmw.ui.new_item.state import EffectWorkspaceState, NewItemDraft

FIXTURES = Path(__file__).parent / 'fixtures' / 'effects'
STEM = 'fx_hit_common_fire_attach_a_loop'


class Snapshot:
    def __init__(self):
        self.data = {}
        for path in FIXTURES.iterdir():
            folder = {'.pae': 'releasebin', '.paem': 'emitter', '.parg': 'renderpreset'}.get(path.suffix)
            if folder:
                self.data[f'effect/binary__/{folder}/{path.name}'] = path.read_bytes()

    def has_entry(self, path):
        return path in self.data

    def payload(self, path):
        return self.data[path]


@pytest.mark.parametrize('name', [p.name for p in FIXTURES.iterdir() if p.suffix in ('.pae','.paem','.parg')])
def test_writer_roundtrip_preserves_typed_graph(name):
    source = (FIXTURES / name).read_bytes()
    before = decode_effect_binary(source)
    rewritten = serialize_effect(source, before)
    assert rewritten == source
    after = decode_effect_binary(rewritten)
    values = lambda d: [(n.type_name, n.name, [(v.name,v.type_name,v.kind,v.raw,v.count) for v in n.values]) for n in d.root.walk()]
    assert values(after) == values(before)
    assert after.walk_complete


def test_writer_relocates_longer_names_and_duplicate_emitters():
    source = (FIXTURES / (STEM + '.pae')).read_bytes()
    doc = decode_effect_binary(source)
    set_typed_value(doc, doc.root, '_effectDataName', 'fx/custom/my_much_longer_newly_authored_effect_name')
    variations = doc.root.child('_emitterVariationDataArray')
    doc.root.children = [(k, (*variations, copy.deepcopy(variations[0])) if k == '_emitterVariationDataArray' else v) for k,v in doc.root.children]
    result = decode_effect_binary(serialize_effect(source, doc))
    assert result.root.value('_effectDataName').value.endswith('newly_authored_effect_name')
    assert len(result.root.child('_emitterVariationDataArray')) == 3


def test_reordering_does_not_read_removed_or_unedited_dependencies():
    snapshot = Snapshot()
    source = snapshot.payload(f'effect/binary__/releasebin/{STEM}.pae')
    snapshot.data.clear()
    for order in ((), (0,), (0,0)):
        result = compile_effect_recipe(snapshot, source, EffectLook(emitter_order=order))
        assert len(decode_effect_binary(result).root.child('_emitterVariationDataArray')) == len(order)


def test_writer_refuses_unknown_trailing_data_and_lookup_table_resize():
    source = (FIXTURES / (STEM + '.pae')).read_bytes()
    with pytest.raises(EffectBinaryError, match='Trailing'):
        serialize_effect(source + b'unknown', decode_effect_binary(source + b'unknown'))
    doc = decode_effect_binary(source)
    holder = doc.root.child('_emitterVariationDataArray')[0].child('_internalEmitterData')
    curves = holder.child('_curveEntryDataList')
    holder.children = [(k, (*curves,copy.deepcopy(curves[0])) if k == '_curveEntryDataList' else v) for k,v in holder.children]
    with pytest.raises(EffectBinaryError, match='lookup table'):
        serialize_effect(source, doc)


def test_emitter_edit_writes_absolute_values_curves_and_preview():
    snapshot = Snapshot()
    source = snapshot.payload(f'effect/binary__/releasebin/{STEM}.pae')
    look = EffectLook(emitter_order=(0,), emitters=(EmitterEdit(0, values=(('_spawnCountMin',(4.,)),('_spawnCountMax',(4.,))), opacity_curve=(0.,.75,0.), size_curve=(.1,2.,.1), color_curve=((1.,0.,0.),(0.,0.,1.))),))
    result = compile_effect_recipe(snapshot, source, look)
    doc = decode_effect_binary(result)
    node = doc.root.child('_emitterVariationDataArray')[0].child('_internalEmitterData')
    assert node.type_name == 'EmitterData'
    assert node.child('_spawnData').value('_spawnCountMin').value == 4
    assert len(node.child('_curveEntryDataList')) >= 3
    preview = preview_effect_from_snapshot(snapshot, STEM, look)
    assert len(preview.emitters) == 1
    assert len(preview.emitters[0].alpha_over_life) == 128
    assert max(preview.emitters[0].alpha_over_life) == pytest.approx(.75, abs=.01)


def test_disabled_emitter_remains_in_inspector_but_not_render_list():
    snapshot = Snapshot()
    look = EffectLook(emitter_order=(0,), emitters=(EmitterEdit(0, enabled=False),))
    preview = preview_effect_from_snapshot(snapshot, STEM, look)
    assert preview.emitters == ()
    assert len(preview.editor_emitters) == 1
    assert preview.editor_emitters[0]['enabled'] is False


def test_layer_recipe_and_draft_roundtrip(tmp_path):
    layers = (EffectLayer(STEM, name='Flame'), EffectLayer(STEM, name='Sparks', offset=(1.,2.,3.), look=EffectLook(emitters=(EmitterEdit(0, rate=2),), emitter_order=(0,0))))
    text = recipe_json(layers)
    assert read_recipe(text) == layers
    path = tmp_path / 'recipe.json'
    write_recipe(path, text)
    assert read_recipe(path.read_text(encoding='utf-8')) == layers
    state = EffectWorkspaceState.from_layers(layers, 1)
    draft = NewItemDraft()
    replace(state, scale=2).write_to(draft)
    restored = EffectWorkspaceState.from_draft(draft)
    assert restored.resolved_layers()[1].scale == 2
    assert restored.resolved_layers()[0] == layers[0]


def test_catalogue_discovers_inherited_texture_names_and_caches_dependencies():
    from types import SimpleNamespace
    from cdmw.services.effect_catalogue import build_effect_catalogue
    snapshot = Snapshot()
    path = 'effect/binary__/emitter/cdem_last_fire_circle_trail_001a.paem'
    source = snapshot.data[path]
    doc = decode_effect_binary(source)
    holder = next(n for n in doc.root.walk() if n.value('_path') and str(n.value('_path').value).endswith('.dds'))
    set_typed_value(doc, holder, '_path', 'effect/texture/whispering_rain.dds')
    snapshot.data[path] = serialize_effect(source, doc)
    snapshot.data['effect/binary__/releasebin/second.pae'] = snapshot.data[f'effect/binary__/releasebin/{STEM}.pae']
    snapshot.effect_stems = (STEM, 'second')
    snapshot.entries = {p:SimpleNamespace(path=p,orig_size=len(b)) for p,b in snapshot.data.items()}
    snapshot.entry = snapshot.entries.__getitem__
    reads = []
    def read(entry):
        reads.append(entry.path)
        return snapshot.data[entry.path]
    snapshot.read_entry = read
    catalogue = build_effect_catalogue(snapshot)
    assert len(catalogue.search('whispering rain')) == 2
    assert reads.count(path) == 1
    assert catalogue.get(STEM).missing_dependencies


def test_spawn_mesh_sampling_uses_triangle_area_and_is_repeatable():
    from types import SimpleNamespace
    from cdmw.services.effect_preview_geometry import sample_spawn_surface
    parsed = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[(0,0,0),(1,0,0),(0,1,0),(10,0,0),(14,0,0),(10,4,0)], faces=[(0,1,2),(3,4,5)])])
    points = sample_spawn_surface(parsed, 96)
    assert points == sample_spawn_surface(parsed, 96)
    assert len(points) == 96
    assert sum(p[0] >= 10 for p in points) > 80
    assert all(p not in parsed.submeshes[0].vertices for p in points)


@pytest.mark.parametrize('edit', [EmitterEdit(-1), EmitterEdit(0, rate=float('nan')), EmitterEdit(0, values=(('_spawnCountMin',(8.,)),('_spawnCountMax',(2.,)))), EmitterEdit(0, texture='../image.dds')])
def test_invalid_recipes_fail_before_serialization(edit):
    with pytest.raises((ValueError,TypeError)):
        read_recipe(json.dumps({'schema':1,'layers':[{'stem':STEM,'look':{'emitters':[__import__('dataclasses').asdict(edit)]}}]}))
