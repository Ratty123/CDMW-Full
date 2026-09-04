"""Rendering inputs that used to be silently lost before reaching Rust."""
import struct
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cdmw.core.effect_binary import ReflectNode, ReflectValue, decode_effect_binary
from cdmw.core.effect_edit import EmitterLayout
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.effect_preview_geometry import load_particle_geometry, particle_geometry
from cdmw.services.effect_preview_model import _Source, _emitter_preview, build_effect_preview
from tests.test_effect_preview_model import EFFECT


def value(name, data):
    if isinstance(data, str):
        return ReflectValue(name, "string", 1, data.encode(), 0)
    if isinstance(data, bool):
        return ReflectValue(name, "bool", 0, bytes([data]), 0)
    if isinstance(data, tuple):
        return ReflectValue(name, f"float{len(data)}", 0, struct.pack(f"<{len(data)}f", *data), 0)
    return ReflectValue(name, "float", 0, struct.pack("<f", data), 0)


def node(kind, values=(), children=()):
    return ReflectNode(kind, 0, values=[value(k, v) for k, v in values], children=list(children))


def material(label, path):
    parameter = node("Parameter", [("_name", label)], [("_value", node("Texture", [("_path", path)]))])
    return node("Material", children=[("_parameters", (parameter,))])


def preview(*nodes, name="test"):
    return _emitter_preview(name, [_Source(n, EmitterLayout()) for n in nodes], {}, [])


def test_mask_smoke_uses_base_colour_opacity_and_packed_grid():
    source = node("EmitterData", children=[
        ("_effectMaterialData2", material("_textureMask", "effect/smoke_4pack.dds")),
        ("_renderData", node("EmitterRenderData", [("_color", (0.04, 0.03, 0.02)), ("_emissiveColor", (1., 1., 1.)), ("_opacity", 0.4), ("_sequenceCountX", 10), ("_sequenceCountY", 10)])),
    ])
    result = preview(source)
    assert result.texture_is_mask and result.texture_channels == 4
    assert result.sequence == (5, 5)
    assert result.blend == "alpha"
    assert result.color_over_life[4] == pytest.approx((0.04, 0.03, 0.02))
    assert 0 < max(result.alpha_over_life) <= 0.401


def test_base_textured_mesh_is_visible_with_zero_emissive_brightness():
    source = node("EmitterData", [("_meshObjectFileName", "effect/stone.pam")], [
        ("_effectMaterialData2", material("_textureBase", "effect/white.dds")),
        ("_renderData", node("EmitterRenderData", [("_color", (0.3, 0.5, 0.8)), ("_emissiveBrightness", 0.0)])),
    ])
    result = preview(source)
    assert result.kind == "mesh" and result.brightness == 1
    assert result.color_over_life[0] == pytest.approx((0.3, 0.5, 0.8))


def test_dim_emissive_curve_does_not_extinguish_a_sparks_base_colour():
    curve = ReflectNode("Curve", 0, values=[
        ReflectValue("_splineID", "int", 0, struct.pack("<i", 21), 0),
        ReflectValue("_componentCount", "int", 0, struct.pack("<i", 4), 0),
        ReflectValue("_splineData", "float4", 3, struct.pack("<8e", *([0.001, 0.0001, 0.00001, 0.0] * 2)), 0),
    ])
    source = node("EmitterData", children=[
        ("_effectMaterialData2", material("_textureBase", "effect/glow.dds")),
        ("_renderData", node("EmitterRenderData", [("_color", (0.8, 0.2, 0.01)), ("_brightness", (2., 2., 2.))])),
        ("_curveEntryDataList", (curve,)),
    ])
    result = preview(source)
    assert result.color_over_life[0] == pytest.approx((0.8, 0.2, 0.01))
    assert result.brightness == 2.0


def test_explicit_empty_mesh_and_authored_velocity_override_the_base():
    base = node("EmitterData", [("_meshObjectFileName", "old.pam")], [
        ("_emitterDynamicData", node("EmitterDynamicData", [("_velocityMin", (1., 1., 1.)), ("_velocityMax", (2., 3., 4.))])),
    ])
    override = node("EmitterData", [("_meshObjectFileName", "")], [
        ("_emitterDynamicData", node("EmitterDynamicData", [("_velocityMin", (0., 0.5, 0.))])),
        ("_effectMaterialData2", material("_textureEmissive", "lightning.dds")),
    ])
    result = preview(override, base, name="spark_once_lightning")
    assert result.kind == "billboard" and result.mesh == ""
    assert result.velocity == ((0., 0.5, 0.), (2., 3., 4.))


def test_inline_emitters_are_complete_and_disabled_sound_emitters_are_omitted():
    embedded = node("EmitterData", children=[("_spawnData", node("EmitterSpawnData", [("_spawnTermMin", 0.), ("_spawnTermMax", 0.)]))])
    silent = node("EmitterData", [("_enableParticleRender", False)])
    variations = tuple(node("Variation", [("_emitterDataName", name)], [("_internalEmitterData", item)]) for name, item in (("flash", embedded), ("sound", silent)))
    original = decode_effect_binary(EFFECT.read_bytes())
    doc = replace(original, root=node("EffectData", children=[("_emitterVariationDataArray", variations)]))
    result = build_effect_preview("test", doc)
    assert not result.notes
    assert len(result.emitters) == 1
    assert not result.emitters[0].loop
    assert result.emitters[0].bursts_per_second == 0


def test_geometry_preserves_triangles_and_uvs_across_submeshes():
    sub = SimpleNamespace(vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], faces=[(0, 1, 2)], uvs=[(0., 0.), (1., 0.), (0., 1.)])
    vertices, uvs, faces = particle_geometry(SimpleNamespace(submeshes=[sub, sub]))
    assert len(vertices) == len(uvs) == 6
    assert faces == ((0, 1, 2), (3, 4, 5))


@pytest.mark.parametrize("vertices,faces", [([(float("nan"), 0, 0)] * 3, [(0, 1, 2)]), ([(0, 0, 0)] * 3, [(0, 1, 9)]), ([(0, 0, 0)] * 4097, [(0, 1, 2)])])
def test_invalid_or_oversized_mesh_is_rejected(vertices, faces):
    with pytest.raises(ValueError):
        particle_geometry(SimpleNamespace(submeshes=[SimpleNamespace(vertices=vertices, faces=faces, uvs=[])]))


def test_particle_mesh_load_observes_cancellation_before_archive_reads():
    def cancel():
        raise RunCancelled
    snapshot = SimpleNamespace(has_entry=lambda path: pytest.fail("read after cancellation"))
    with pytest.raises(RunCancelled):
        load_particle_geometry(SimpleNamespace(emitters=[preview(node("EmitterData"))], notes=()), snapshot, None, cancel)
