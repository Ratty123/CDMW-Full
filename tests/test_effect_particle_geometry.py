"""Particle geometry selection must follow the emitter, not an unused filename."""

from types import SimpleNamespace

import pytest

from cdmw.core.effect_binary import decode_effect_binary
from cdmw.core.effect_writer import serialize_effect, set_typed_value
from cdmw.domain.new_item.effect_authoring import EffectLook, EmitterEdit
from cdmw.services.effect_preview_model import effect_preview_json, preview_effect_from_snapshot
from cdmw.services.effect_recipe import compile_effect_recipe
from tests.test_effect_authoring import STEM, Snapshot


MESH_PATH = "effect/mesh/owned-particle.pam"
EFFECT_PATH = f"effect/binary__/releasebin/{STEM}.pae"


def _self_contained_emitter(geometry):
    snapshot = Snapshot()
    source = compile_effect_recipe(
        snapshot,
        snapshot.data[EFFECT_PATH],
        EffectLook(emitter_order=(0,), emitters=(EmitterEdit(0, values=(("_spawnVolumeType", (0.,)),)),)),
    )
    document = decode_effect_binary(source)
    emitter = document.root.child("_emitterVariationDataArray")[0].child("_internalEmitterData")
    assert set_typed_value(document, emitter, "_meshObjectFileName", MESH_PATH)
    render = emitter.child("_renderData")
    if geometry is None:
        render.values = [v for v in render.values if v.name != "_geometryType"]
    else:
        assert set_typed_value(document, render, "_geometryType", geometry)
    snapshot.data[EFFECT_PATH] = serialize_effect(source, document)
    return snapshot


@pytest.mark.parametrize("geometry", [None, 0, 2])
@pytest.mark.parametrize("mesh_present", [False, True])
def test_sprite_geometry_ignores_unused_mesh_while_mesh_particles_keep_it(geometry, mesh_present):
    snapshot = _self_contained_emitter(geometry)
    if mesh_present:
        snapshot.data[MESH_PATH] = b"owned mesh decoded by the injected parser"
    parsed_paths = []

    def parse_mesh(_data, name):
        parsed_paths.append(name)
        return SimpleNamespace(format="pam", submeshes=[SimpleNamespace(
            vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
            uvs=[(0., 0.), (1., 0.), (0., 1.)], faces=[(0, 1, 2)],
        )])

    preview = preview_effect_from_snapshot(snapshot, STEM, parse_mesh=parse_mesh)
    emitter = preview.emitters[0]
    if geometry == 2:
        assert emitter.kind == "mesh"
        assert emitter.mesh == MESH_PATH
        assert bool(emitter.particle_faces) is mesh_present
        assert parsed_paths == (["owned-particle.pam"] if mesh_present else [])
        assert any("particle geometry unavailable" in n for n in preview.notes) is not mesh_present
    else:
        assert emitter.kind == "billboard"
        assert emitter.mesh == ""
        assert parsed_paths == []
        assert not any("particle geometry unavailable" in n for n in preview.notes)
        assert '"kind": "billboard"' in effect_preview_json(preview)


def test_explicit_sprite_override_wins_over_the_inherited_mesh_geometry():
    snapshot = Snapshot()
    path = "effect/binary__/emitter/cdem_last_fire_circle_trail_001a.paem"
    source = snapshot.data[path]
    document = decode_effect_binary(source)
    assert set_typed_value(document, document.root, "_meshObjectFileName", MESH_PATH)
    assert set_typed_value(document, document.root.child("_renderData"), "_geometryType", 2)
    snapshot.data[path] = serialize_effect(source, document)
    source = snapshot.data[EFFECT_PATH]
    document = decode_effect_binary(source)
    override = document.root.child("_emitterVariationDataArray")[0].child("_internalEmitterData")
    assert set_typed_value(document, override.child("_renderData"), "_geometryType", 0)
    snapshot.data[EFFECT_PATH] = serialize_effect(source, document)
    preview = preview_effect_from_snapshot(snapshot, STEM)
    assert preview.emitters[0].kind == "billboard"
    assert preview.emitters[0].mesh == ""
