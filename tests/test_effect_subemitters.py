"""Parent-driven particles need a carrier birth even when its geometry is hidden."""

import copy
import struct
from dataclasses import replace

import pytest

from cdmw.core.effect_binary import ReflectNode, ReflectValue, decode_effect_binary
from cdmw.services.effect_preview_model import build_effect_preview
from tests.test_effect_authoring import FIXTURES, STEM


def _value(name, type_name, raw, kind=0):
    return ReflectValue(name, type_name, kind, raw, 0)


def _variation(identity, *, parent=None, children=(), count=1, drawn=True, spawn_type=None):
    values = [_value('_emitterVariationID', 'EmitterVariationID', struct.pack('<I', identity))]
    if parent is not None:
        values.append(_value('_superEmitterVariationID', 'EmitterVariationID', struct.pack('<I', parent)))
    spawn_values = [_value('_spawnCountMax', 'uint', struct.pack('<I', count))]
    if spawn_type is not None:
        spawn_values.append(_value('_emitterSpawnType', 'EmitterSpawnType', bytes([spawn_type]), 2))
    emitter = ReflectNode('EmitterData', 0, values=[
        _value('_enableParticleRender', 'bool', bytes([drawn])),
    ], children=[('_spawnData', ReflectNode('EmitterSpawnData', 0, values=spawn_values))])
    links = tuple(ReflectNode('SubEmitterData', 0, values=[
        _value('_subEmitterVariationID', 'EmitterVariationID', struct.pack('<I', child)),
    ]) for child in children)
    return ReflectNode('EmitterVariationData', 0, values=values, children=[
        ('_internalEmitterData', emitter), ('_subEmitterDataList', links),
    ])


def _preview(*variations, emitter_documents=None):
    document = decode_effect_binary((FIXTURES / (STEM + '.pae')).read_bytes())
    root = copy.deepcopy(document.root)
    root.children = [('_emitterVariationDataArray', tuple(variations))]
    return build_effect_preview(STEM, replace(document, root=root), emitter_documents=emitter_documents or {})


def test_zero_spawn_carrier_cannot_create_its_ribbon_or_spark_children():
    preview = _preview(
        _variation(10, count=0, drawn=False, children=(20, 30)),
        _variation(20, parent=10, spawn_type=1),
        _variation(30, parent=10, spawn_type=1),
    )
    assert preview.emitters == ()
    assert [e['enabled'] for e in preview.editor_emitters] == [False, True, True]


def test_hiding_carrier_geometry_does_not_disable_its_emissions():
    preview = _preview(
        _variation(10, drawn=False, children=(20,)),
        _variation(20, parent=10, spawn_type=1),
    )
    assert [e.source_index for e in preview.emitters] == [1]


def test_ids_survive_reordering_and_an_unrelated_emitter_stays_visible():
    preview = _preview(
        _variation(20, parent=10, spawn_type=1),
        _variation(70),
        _variation(10, count=0, drawn=False, children=(20,)),
    )
    assert [e.source_index for e in preview.emitters] == [1]


def test_a_chain_with_no_parent_births_cannot_start_its_descendants():
    preview = _preview(
        _variation(10, count=0, drawn=False, children=(20,)),
        _variation(20, parent=10, spawn_type=1, children=(30,)),
        _variation(30, parent=20, spawn_type=1),
    )
    assert preview.emitters == ()


@pytest.mark.parametrize('case', ['no_link', 'wrong_parent', 'autonomous', 'duplicate_id', 'missing_parent'])
def test_incomplete_or_ambiguous_relationships_do_not_silence_independent_particles(case):
    variations = [
        _variation(10, count=0, drawn=False, children=() if case == 'no_link' else (20,)),
        _variation(20, parent=99 if case == 'wrong_parent' else 10,
                   spawn_type=0 if case == 'autonomous' else 1),
    ]
    if case == 'duplicate_id':
        variations.append(_variation(10, drawn=False))
    if case == 'missing_parent':
        variations = variations[1:]
    preview = _preview(*variations)
    assert len(preview.emitters) == 1


def test_absent_spawn_count_is_not_evidence_that_a_carrier_cannot_spawn():
    parent = _variation(10, drawn=False, children=(20,))
    parent.child('_internalEmitterData').child('_spawnData').values.clear()
    preview = _preview(parent, _variation(20, parent=10, spawn_type=1))
    assert len(preview.emitters) == 1


@pytest.mark.parametrize('override', [None, 1])
def test_inherited_zero_count_and_explicit_override_use_the_resolved_carrier(override):
    path = 'effect/binary__/emitter/owned_carrier.paem'
    parent = _variation(10, count=0, drawn=False, children=(20,))
    embedded = parent.child('_internalEmitterData')
    base = copy.deepcopy(embedded)
    embedded.type_name = path
    embedded.child('_spawnData').values = ([] if override is None else [
        _value('_spawnCountMax', 'uint', struct.pack('<I', override)),
    ])
    document = decode_effect_binary((FIXTURES / (STEM + '.pae')).read_bytes())
    preview = _preview(parent, _variation(20, parent=10, spawn_type=1),
                       emitter_documents={path: replace(document, root=base)})
    assert len(preview.emitters) == (0 if override is None else 1)
