"""Rendering inputs that used to be silently lost before reaching Rust."""
import struct
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cdmw.core.effect_binary import ReflectNode, ReflectValue, decode_effect_binary
from cdmw.core.effect_edit import EmitterLayout
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.effect_preview_geometry import MAX_VERTICES, decode_effect_vertex, load_particle_geometry, particle_geometry, particle_shader_attributes
from cdmw.services.effect_preview_model import EffectPreview, _Source, _emitter_preview, build_effect_preview
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


@pytest.mark.parametrize("vertices,faces", [([(float("nan"), 0, 0)] * 3, [(0, 1, 2)]), ([(0, 0, 0)] * 3, [(0, 1, 9)]), ([(0, 0, 0)] * (MAX_VERTICES + 1), [(0, 1, 2)])])
def test_invalid_or_oversized_mesh_is_rejected(vertices, faces):
    with pytest.raises(ValueError):
        particle_geometry(SimpleNamespace(submeshes=[SimpleNamespace(vertices=vertices, faces=faces, uvs=[])]))


def test_particle_mesh_load_observes_cancellation_before_archive_reads():
    def cancel():
        raise RunCancelled
    snapshot = SimpleNamespace(has_entry=lambda path: pytest.fail("read after cancellation"))
    with pytest.raises(RunCancelled):
        load_particle_geometry(SimpleNamespace(emitters=[preview(node("EmitterData"))], notes=()), snapshot, None, cancel)


def test_lightning_sized_mesh_retains_every_triangle():
    sub = SimpleNamespace(vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
                          faces=[(0, 1, 2)] * 3338, uvs=[(0., 0.)] * 3)
    _vertices, _uvs, faces = particle_geometry(SimpleNamespace(submeshes=[sub]))
    assert len(faces) == 3338


def test_missing_particle_mesh_is_not_replaced_with_a_sprite():
    emitter = replace(preview(node("EmitterData")), kind="mesh", mesh="missing.pam", texture="glow.dds")
    result = load_particle_geometry(EffectPreview("missing", (emitter,), (0.,) * 3, (1.,) * 3),
                                    SimpleNamespace(has_entry=lambda _: False), None, lambda: None)
    assert result.emitters[0].kind == "mesh"
    assert not result.emitters[0].particle_faces
    assert "particle geometry unavailable" in result.notes[0]


def test_additive_emission_is_independent_of_base_opacity_and_reads_lifetime_flags():
    source = node("EmitterData", children=[
        ("_effectMaterialData2", material("_textureEmissive", "glow.dds")),
        ("_renderData", node("EmitterRenderData", [("_opacity", 0.0)])),
        ("_spawnData", node("EmitterSpawnData", [("_isInfiniteParticle", True), ("_useCureveRepeat", True)])),
    ])
    result = preview(source)
    assert result.blend == "additive"
    assert max(result.alpha_over_life) > 0
    assert result.infinite_life and result.repeat_curves


def test_reordered_scalar_curve_cannot_supply_rgb_and_removed_colour_stays_removed():
    from cdmw.services.effect_preview_model import _curve_from
    from cdmw.core.effect_edit import COLOR_CURVE_ID
    progress = node("Curve", [("_componentCount", 1)])
    progress.wire["owner"] = 16
    progress.values.append(ReflectValue("_splineData", "uint16", 3, struct.pack("<8e", *([.5] * 8)), 0))
    override = node("EmitterData", children=[("_curveEntryDataList", (progress,))])
    colour = node("Curve", [("_splineID", COLOR_CURVE_ID), ("_componentCount", 4)])
    colour.values[0] = ReflectValue("_splineID", "int", 0, struct.pack("<i", COLOR_CURVE_ID), 0)
    colour.values.append(ReflectValue("_splineData", "uint16", 3, struct.pack("<8e", *([0., 0., 1., 0.] * 2)), 0))
    base = node("EmitterData", children=[("_curveEntryDataList", (colour,))])
    sources = [_Source(override, EmitterLayout((COLOR_CURVE_ID,))), _Source(base, EmitterLayout())]
    assert _curve_from(sources, COLOR_CURVE_ID, 4)[0] == (0., 0., 1., 0.)
    override.wire["_curveEntryDataList"] = {"pairs": struct.pack("<Q", COLOR_CURVE_ID)}
    assert _curve_from(sources, COLOR_CURVE_ID, 4) == ()
    override.children = [("_curveEntryDataList", (progress, colour))]
    assert _curve_from(sources, COLOR_CURVE_ID, 4)[0] == (0., 0., 1., 0.)


def test_reordered_inherited_material_parameters_follow_their_stable_keys():
    from cdmw.services.effect_preview_model import _read_material
    parameter = node("Parameter", [("_value", 2.)])
    parameter.wire["owner"] = 22
    source = node("Material", children=[("_parameters", (parameter,))])
    layout = EmitterLayout(parameter_names=("_temperatureColorSpline", "_temperatureBrightness"), parameter_keys=(11, 22))
    assert _read_material(source, layout).temperature_brightness == 2.


@pytest.mark.parametrize("sign_bits,normal_z,tangent_sign", [(0, -1., -1.), (1, -1., 1.), (2, 1., 1.), (3, 1., -1.)])
def test_effect_vertex_matches_shader_packing_and_bgra_channel_order(sign_bits, normal_z, tangent_sign):
    # Shader decode: XY=511 maps to zero; the two high bits encode normal Z
    # and tangent handedness. The unrelated position words must not enter it.
    packed = 511 | (511 << 10) | (511 << 20) | (sign_bits << 30)
    data = struct.pack("<4H2eII", 100, 200, 300, 511 | 0x8000, .25, .75, packed, 0x80402010)
    normal, tangent, colour = decode_effect_vertex(data, 0)
    assert normal == pytest.approx((0., 0., normal_z))
    assert tangent == pytest.approx((0., 0., 1., tangent_sign))
    assert colour == pytest.approx((64/255., 32/255., 16/255., 128/255.))
    negative_tangent = bytearray(data)
    struct.pack_into("<H", negative_tangent, 6, 511)
    assert decode_effect_vertex(negative_tangent, 0)[1][2] == -1.


def test_effect_vertex_does_not_guess_unknown_layouts_or_read_truncated_records():
    sub = SimpleNamespace(vertices=[(0., 0., 0.)] * 3, source_vertex_offsets=[0, 20, 40])
    parsed = SimpleNamespace(format="pam", submeshes=[sub])
    assert len(particle_shader_attributes(parsed, bytes(60))[0]) == 3
    parsed.format = "pac"
    assert particle_shader_attributes(parsed, bytes(60)) == ((), (), ())
    parsed.format = "pam"
    sub.source_vertex_offsets = [0, 40, 80]
    assert particle_shader_attributes(parsed, bytes(100)) == ((), (), ())
    with pytest.raises(ValueError, match="truncated EffectVertex"):
        decode_effect_vertex(bytes(19), 0)
    with pytest.raises(ValueError, match="truncated EffectVertex"):
        decode_effect_vertex(bytes(20), -1)


def test_particle_vertex_inputs_survive_real_preview_serialization():
    import json
    from cdmw.services.effect_preview_model import effect_preview_json

    packed = 511 | (1022 << 10) | (511 << 20)
    vertex = struct.pack("<4H2eII", 0, 0, 0, 511, 0., 1., packed, 0xff11ff80)
    sub = SimpleNamespace(vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
                          uvs=[(0., 1.)] * 3, faces=[(0, 1, 2)], source_vertex_offsets=[0, 20, 40],
                          normals=[(0., 1., 0.)] * 3)
    emitter = replace(preview(node("EmitterData")), kind="mesh", mesh="lightning.pam")
    result = load_particle_geometry(EffectPreview("test", (emitter, emitter), (0.,) * 3, (1.,) * 3),
                                    SimpleNamespace(has_entry=lambda _: True, payload=lambda _: vertex * 3),
                                    lambda *_: SimpleNamespace(format="pam", submeshes=[sub]), lambda: None)
    serialized = json.loads(effect_preview_json(result))["emitters"][0]
    assert serialized["particle_normals"][0] == pytest.approx([1., 0., 0.])
    assert serialized["particle_colors"][0] == pytest.approx([17/255., 1., 128/255., 1.])
    assert len(serialized["particle_tangents"]) == len(serialized["particle_vertices"]) == 3


def test_procedural_material_preserves_keyed_values_and_partial_spline_overrides():
    from cdmw.services.effect_preview_model import _shader_material

    point = node("SplinePoint", [("_position", (.4, .8)), ("_outterTangent", .7)])
    point.wire["owner"] = 17
    curve = node("SplineData", children=[("_pointListForSerialize", (point,))])
    curve.wire["owner"] = 0
    instance = node("SplineDataInstance", children=[("_dataForSerialize", (curve,))])
    parameter = node("MaterialParameterSplineRef", [("_name", "_progressSpline")],
                     [("_value", node("SplineRef", children=[("_splineDataInstance", instance)]))])
    parameter.wire["owner"] = 11
    thickness = node("MaterialParameterFloat2", [("_name", "_mainBranchThickness"), ("_value", (.1, .2))])
    thickness.wire["owner"] = 22
    base = node("EmitterData", children=[("_effectMaterialData2", node("Material", [("_materialName", "EffectTest_Lightning")], [("_parameters", (parameter, thickness))]))])
    changed = node("MaterialParameterFloat2", [("_value", (.3, .4))])
    changed.wire["owner"] = 22
    changed.override = 1
    moved_point = node("SplinePoint", [("_position", (.5, .9))])
    moved_point.wire["owner"] = 17
    moved_point.override = 1
    changed_curve = node("SplineData", children=[("_pointListForSerialize", (moved_point,))])
    changed_curve.wire["owner"] = 0
    changed_curve.override = 1
    changed_instance = node("SplineDataInstance", children=[("_dataForSerialize", (changed_curve,))])
    inherited = node("MaterialParameterSplineRef", children=[("_value", node("SplineRef", children=[("_splineDataInstance", changed_instance)]))])
    inherited.wire["owner"] = 11
    inherited.override = 1
    override = node("EmitterData", children=[("_effectMaterialData2", node("Material", children=[("_parameters", (changed, inherited))]))])
    material = _shader_material([_Source(override, EmitterLayout()), _Source(base, EmitterLayout())])
    assert material["name"] == "EffectTest_Lightning"
    assert material["values"]["_mainBranchThickness"] == pytest.approx((.3, .4))
    decoded = material["splines"]["_progressSpline"]["components"][0][0]
    assert decoded["position"] == pytest.approx((.5, .9))
    assert decoded["outer_tangent"] == pytest.approx(.7)
    assert material["splines"]["_progressSpline"]["samples"][0] == pytest.approx((.9,) * 128)
    assert thickness.value("_value").value == pytest.approx((.1, .2))


def test_surface_spawn_preserves_authored_volume_and_explains_required_mesh():
    transform = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., -.1, 0., -.15, 1.)
    dynamic = node("EmitterDynamicData", [("_spawnVolumeData", (.01, .1, .2, 0.))])
    dynamic.values.append(ReflectValue("_spawnVolumeTransform", "float4x4", 0, struct.pack("<16f", *transform), 0))
    source = node("EmitterData", children=[
        ("_spawnData", node("EmitterSpawnData", [("_spawnVolumeType", 6.), ("_surfaceDensity", 100.), ("_useUniformSurfaceDensity", True)])),
        ("_emitterDynamicData", dynamic),
    ])
    notes = []
    result = _emitter_preview("surface", [_Source(source, EmitterLayout())], {}, notes)
    assert result.spawn_volume_type == 6
    assert result.spawn_volume_data == pytest.approx((.01, .1, .2, 0.))
    assert result.spawn_volume_transform == pytest.approx(transform)
    assert result.spawn_surface_density == 100.
    assert result.spawn_uniform_surface_density
    assert result.spawn_normal_alignment is False  # Verified native EmitterSpawnData constructor.
    assert "requires a target mesh surface" in notes[0]
    default = preview(node("EmitterData"))
    assert default.spawn_surface_density == 10000.
    assert default.spawn_uniform_surface_density is False
