"""EyeCover export and the explicitly approximate independent-weight preview."""
from dataclasses import replace
from io import BytesIO
import struct
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from cdmw.core.material_shader_controls import equipment_shader_options, rewrite_shader_controls
from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.mesh.shader_controls import EYE_COVER, ShaderControls, catalogue_payload, validate_choices
from cdmw.services.new_item_shader_controls import apply_shader_controls
from cdmw.services.new_item_template_model import prepare_template_model
from tests.test_shader_controls import material, field
from tests.test_translucency_surface import source_files, PAC, XML, SP
from tests.test_new_item_rust_ui import studio, _send


def controls(**values):
    return ShaderControls(EYE_COVER.shader, tuple((key, (value,)) for key, value in values.items()))


def pixels(data):
    with Image.open(BytesIO(data)) as image:
        return image.convert("RGBA").copy()


@pytest.mark.parametrize("source", ["SkinnedMeshStandard", "SkinnedMeshEmissive", "SkinnedMeshTranslucent", EYE_COVER.shader])
def test_eye_cover_compatible_sources_and_typed_byte(source):
    original = material(source, field("_eyeCoverDiffuseParameter", str(0x12345680), "Byte4"))
    assert EYE_COVER.shader in equipment_shader_options(original)["blade"][1]
    edited, found = rewrite_shader_controls(original, (("Blade", controls(_eyeCoverDiffuseParameter=.25)),),
        texture_paths={"blade": {"_alphaTexture": "owned/alpha.dds", "_materialTexture": "owned/surface.dds"}})
    wrapper = find_material_wrappers(edited)[0]
    assert found == {"blade"}
    assert wrapper.shader == EYE_COVER.shader
    assert int(wrapper.value("_eyeCoverDiffuseParameter")) == 0x12345640
    parameter = next(p for p in wrapper.parameters if p.name == "_eyeCoverDiffuseParameter")
    assert parameter.kind == "Byte4" and parameter.item_id == "123"
    assert wrapper.value("_wingFlowProgress") is None


@pytest.mark.parametrize("route", ["template", "prepared"])
def test_private_bc7_textures_preserve_source_and_other_materials(route, monkeypatch):
    from cdmw.core import texture_native
    real_encode = texture_native.encode_dds_with_directxtex
    logs = []
    def encode_with_heartbeat(*args, on_log=None, **kwargs):
        if on_log:
            on_log("Native texture encode is still running after 30s (timeout 120s).")
        return real_encode(*args, on_log=on_log, **kwargs)
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", encode_with_heartbeat)
    files = source_files()
    original = dict(files.side_files)
    settings = (("Blade", controls(_eyeCoverDiffuseParameter=.2, surface_alpha=.3, material_red=.1,
                                  roughness=.8, metallic=.2)),)
    if route == "template":
        payloads = {PAC: files.pac_data, **files.side_files}
        snapshot = SimpleNamespace(payload=payloads.__getitem__, has_entry=payloads.__contains__)
        output = prepare_template_model(snapshot, [PAC], shader_controls=settings, on_log=logs.append)
    else:
        output = apply_shader_controls(files, settings, on_log=logs.append)
    for role in ("surface alpha", "material"):
        messages = [line for line in logs if line.startswith(f"Blade: EyeCover {role}:")]
        assert "Preparing texture" in messages[0]
        assert any("BC7 texture" in line and "mip levels" in line for line in messages)
        assert any("still running after 30s" in line for line in messages)
        assert "Encoded texture in" in messages[-1]
    assert files.side_files == original and output.pac_data == files.pac_data
    wrappers = find_material_wrappers(output.side_files[XML].decode())
    old = find_material_wrappers(original[XML].decode())
    assert output.side_files[XML].decode()[wrappers[1].start:wrappers[1].end] == original[XML].decode()[old[1].start:old[1].end]
    blade = wrappers[0]
    assert blade.shader == EYE_COVER.shader
    assert int(blade.value("_eyeCoverDiffuseParameter")) == 51
    for role in ("_baseColorTexture", "_normalTexture", "_emissiveIntensityTexture"):
        assert blade.textures[role] == old[0].textures[role]
    if route == "prepared":
        assert output.side_files[SP] == original[SP]
    else:
        assert SP not in output.side_files  # The template keeps its shared archive dependency.
    for role, expected in (("_alphaTexture", (76, 255, 255, 255)), ("_materialTexture", (26, 204, 51, 190))):
        data = output.side_files[blade.textures[role]]
        assert data[84:88] == b"DX10" and struct.unpack_from("<I", data, 128)[0] == 98  # BC7_UNORM
        assert struct.unpack_from("<I", data, 28)[0] >= 3  # Full mips, including solid alpha.
        assert all(abs(actual - wanted) <= 3 for actual, wanted in zip(pixels(data).getpixel((0, 0)), expected))


def test_defaults_do_not_inherit_stock_face_maps_and_unchecked_channels_keep_source():
    files = source_files()
    output = apply_shader_controls(files, (("Blade", controls()),))
    blade = find_material_wrappers(output.side_files[XML].decode())[0]
    assert blade.textures["_materialTexture"] == SP
    assert pixels(output.side_files[blade.textures["_alphaTexture"]]).getpixel((0, 0)) == (255, 255, 255, 255)
    assert blade.value("_eyeCoverDiffuseParameter") == "128"
    assert next(p for p in blade.parameters if p.name == "_eyeCoverDiffuseParameter").item_id == EYE_COVER.fields[0].item_id
    # No surface map: create neutral material red/roughness/metallic instead of a face map.
    from cdmw.services.new_item_planning import ModelFiles
    output = apply_shader_controls(ModelFiles(b"pac", {XML: material().encode()}), (("Blade", controls()),))
    blade = find_material_wrappers(output.side_files[XML].decode())[0]
    assert pixels(output.side_files[blade.textures["_materialTexture"]]).getpixel((0, 0))[:3] == (0, 0, 0)
    # Changing only red preserves the source roughness, metallic and alpha channels.
    output = apply_shader_controls(files, (("Blade", controls(material_red=.2)),))
    blade = find_material_wrappers(output.side_files[XML].decode())[0]
    source, edited = pixels(files.side_files[SP]), pixels(output.side_files[blade.textures["_materialTexture"]])
    for xy in ((0, 0), (7, 0)):
        assert all(abs(a - b) <= 3 for a, b in zip(source.getpixel(xy)[1:], edited.getpixel(xy)[1:]))


def test_invalid_missing_conflicting_and_cancelled_exports_fail_before_publication():
    files = source_files()
    for value in (-.1, 1.1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            controls(surface_alpha=value).validate()
    for kwargs in ({"glow_parts": ("blade",)}, {"translucent_parts": ("BLADE",)}):
        with pytest.raises(ValueError, match="restore Glow"):
            validate_choices((("Blade", controls()),), **kwargs)
    with pytest.raises(ValueError, match="texture preparation"):
        rewrite_shader_controls(material(), (("Blade", controls()),))
    with pytest.raises(ValueError, match="requires"):
        apply_shader_controls(replace(files, side_files={XML: material("SkinnedMeshStandard_Ver2").encode()}),
                              (("Blade", controls()),))
    with pytest.raises(ValueError, match="missing EyeCover source texture"):
        apply_shader_controls(replace(files, side_files={XML: files.side_files[XML]}),
                              (("Blade", controls(material_red=.2)),))
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        apply_shader_controls(files, (("Blade", controls(surface_alpha=.2)),), stop_event=stop)
    assert EYE_COVER.shader not in {row["shader"] for row in catalogue_payload()}  # New Item only.


def test_preview_routes_eye_cover_in_live_prepared_and_effects_materials():
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.shader_controls_preview import shader_preview_mesh, shader_preview_groups
    part = SubMesh(name="Blade", material="Blade")
    part.preview_native_material_overrides = {"translucency": [.1, .3]}
    other = SubMesh(name="Guard", material="Guard")
    mesh = ParsedMesh(path="imported.obj", submeshes=[part, other])
    settings = (("Blade", controls(surface_alpha=.2)),)
    prepared = shader_preview_mesh(mesh, settings)
    factors = shader_preview_groups(mesh, settings)[0]["shader_controls"]
    assert factors == prepared.submeshes[0].preview_native_material_overrides["shader_controls"]
    assert factors[:9] == [7., 0., 0., 0., 128 / 255, .2, -1., -1., -1.]
    assert len(factors) == 32
    assert prepared.submeshes[0] is not part and prepared.submeshes[1] is other
    assert shader_preview_groups(mesh, ())[0]["shader_controls"] is None
    assert part.preview_native_material_overrides == {"translucency": [.1, .3]}
    assert ShaderControls.from_dict(settings[0][1].to_dict()) == settings[0][1]
    from cdmw.ui.new_item.effect_item_source import PlannedEffectItemSource
    from cdmw.ui.new_item.model_import import ModelPlacement
    effects = PlannedEffectItemSource(object(), ModelPlacement(), False, None, b"", None, None, None,
                                     shader_controls=settings)
    effect_mesh, _ = effects._finish(mesh, "placed", threading.Event())
    assert effect_mesh.submeshes[0].preview_native_material_overrides["shader_controls"] == factors


def test_preview_uses_export_byte_rounding_and_inherited_low_byte():
    from cdmw.domain.mesh.shader_controls import preview_factors
    source = {"_eyeCoverDiffuseParameter": str(0xABCDEF80)}
    assert preview_factors(controls(), source)[4] == 128 / 255
    assert preview_factors(controls(_eyeCoverDiffuseParameter=.25, surface_alpha=.3,
                                   material_red=.1, roughness=.8, metallic=.2), source)[4:9] == (
        64 / 255, 76 / 255, 26 / 255, 204 / 255, 51 / 255)


def test_template_preview_binds_owned_surface_alpha_and_source_parameter(tmp_path, monkeypatch):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.shader_controls_preview import shader_preview_mesh
    from cdmw.services.mesh_rust_authoring import _mesh_texture_payloads, _mesh_material_presentations, _session_root_identity
    from tests.test_new_item_materials import dds
    monkeypatch.setattr("cdmw.services.shader_controls_preview.gettempdir", lambda: str(tmp_path))
    base = tmp_path / "base.dds"
    base.write_bytes(dds())
    part = SubMesh(name="Blade", material="Blade", vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
                   uvs=[(0., 0.), (1., 0.), (0., 1.)], faces=[(0, 1, 2)])
    part.preview_texture_dds_path = str(base)
    part.preview_texture_path = str(base)
    mesh = ParsedMesh(path="character/model/sword.pac", format="pac", submeshes=[part])
    from tests.test_pac_xml_standard_material import texture
    text = material(EYE_COVER.shader, field("_eyeCoverDiffuseParameter", str(0x12345640), "Byte4")
                    + texture("_alphaTexture", "124", "alpha.dds", 51))
    assert find_material_wrappers(text)[0].textures["_alphaTexture"] == "alpha.dds"
    payloads = {"character/modelproperty/sword.pac_xml": text.encode(), "alpha.dds": dds()}
    snapshot = SimpleNamespace(payload=payloads.__getitem__, has_entry=payloads.__contains__)
    preview = shader_preview_mesh(mesh, (("Blade", controls()),), snapshot=snapshot)
    assert preview.submeshes[0].preview_native_material_overrides["shader_controls"][4:9] == [64 / 255, -1., -1., -1., -1.]
    output = tmp_path / "package"
    output.mkdir()
    resources = _mesh_texture_payloads(output, preview, expected_root_identity=_session_root_identity(output))
    assert {row["role"] for row in resources} >= {"base_color", "shader_mask"}
    assert _mesh_material_presentations(preview)[0]["shader_controls"][0] == 7
    assert all(row["material_indices_by_lod"] == [[0]] for row in resources)
    assert not getattr(part, "preview_native_material_overrides", {})


def test_cancellation_after_encoding_does_not_publish_partial_materials(monkeypatch):
    files = source_files()
    before = dict(files.side_files)
    stop = threading.Event()
    def cancel_after_encode(source, output, *, stop_event, **kwargs):
        assert stop_event is stop
        output.write_bytes(b"unpublished encoder output")
        stop.set()
        return {"success": True}
    monkeypatch.setattr("cdmw.core.texture_native.encode_dds_with_directxtex", cancel_after_encode)
    with pytest.raises(RunCancelled):
        apply_shader_controls(files, (("Blade", controls(surface_alpha=.2)),), stop_event=stop)
    assert files.side_files == before


def test_import_owned_binding_and_clones_get_private_maps():
    from cdmw.services.new_item_planning import ModelFiles
    result = SimpleNamespace(source_owned_output_draw_sections=(
        SimpleNamespace(target_submesh_name="game_blade", source_material_name="Imported Blade"),))
    scene = SimpleNamespace(material_bindings=(SimpleNamespace(material_name="Imported Blade", texture_slots=()),))
    source = material(name="game_blade") + material(name="clone") + material(name="guard").replace("texture/base.dds", "guard.dds")
    files = ModelFiles(b"geometry", {XML: source.encode(), "texture/base.dds": b"owned base"})
    settings = (("Imported Blade", controls(surface_alpha=.2, material_red=.3)),)
    output = apply_shader_controls(files, settings, result=result, scene=scene)
    rows = find_material_wrappers(output.side_files[XML].decode())
    assert [row.shader for row in rows] == [EYE_COVER.shader, EYE_COVER.shader, "SkinnedMeshStandard"]
    assert all(row.textures["_alphaTexture"] in output.side_files for row in rows[:2])
    assert files.side_files[XML] == source.encode()


def test_dye_preview_keeps_source_maps_then_applies_eye_cover_without_bc7(tmp_path, monkeypatch):
    from cdmw.ui.new_item.dye_preview import variant_dye_preview_source
    from tests.test_new_item_appearance_dyes import fixture, MAPPING
    from tests.test_new_item_service import TEMPLATE
    _, snapshot, choice = fixture(tmp_path, "SkinnedMeshStandard")
    choice = replace(choice, dyes=MAPPING, shader_controls=(("blade", controls(surface_alpha=.2)),))
    state = SimpleNamespace(appearance=choice, result=None, source=None, scene=None)
    controller = SimpleNamespace(current_variant_identity=lambda: choice.identity, snapshot=snapshot,
        _sync_variant_state=lambda: None, _variant_states={choice.identity: state}, draft=SimpleNamespace(template_key=TEMPLATE))
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.ui.new_item import dye_preview
    original_assignments = dye_preview.prepare_dye_assignments
    def check(row, data, *args, **kwargs):
        actual = find_material_wrappers(data.decode())[0]
        assert actual.shader == "SkinnedMeshStandard"
        assert actual.value("_eyeCoverDiffuseParameter") is None
        return original_assignments(row, data, *args, **kwargs)
    monkeypatch.setattr("cdmw.ui.new_item.dye_preview.prepare_dye_assignments", check)
    mesh = ParsedMesh(path=choice.model_path, submeshes=[SubMesh(name="blade", material="blade")])
    monkeypatch.setattr("cdmw.services.mesh_dotnet_reference_composite.decode_dotnet_native_preview_package", lambda *a, **k: mesh)
    def native(*args, consume_native_package, **kwargs):
        return consume_native_package(object())
    monkeypatch.setattr("cdmw.ui.new_item.template_preview_cache.build_native_template_preview", native)
    captured = []
    def package(model, **kwargs):
        captured.append(model)
        return tmp_path
    monkeypatch.setattr("cdmw.ui.new_item.item_preview.build_item_preview_package", package)
    monkeypatch.setattr("cdmw.services.new_item_eye_cover._encode_channels", lambda *a, **k: pytest.fail("preview encoded export maps"))
    _, preview = variant_dye_preview_source(controller)
    preview.materials(threading.Event(), output_root=tmp_path, native_preview_core_cache_root=tmp_path)
    assert captured[0].submeshes[0].preview_native_material_overrides["shader_controls"][0] == 7
    assert captured[0].submeshes[0].preview_native_material_overrides["shader_controls"][5] == .2


def test_rust_bridge_exposes_controls_updates_draft_and_restores(studio, monkeypatch):
    from pathlib import Path
    from unittest.mock import Mock
    from cdmw.domain.new_item.spec import MaterialRoute, ModelSource
    from cdmw.ui.new_item.model_import import ModelImportSource
    from tests.test_new_item_glow_preview import _mesh
    _, tab, bridge = studio
    panel = tab.model_panel
    mesh = _mesh()
    tab.controller.model_import = ModelImportSource(Path("source.gltf"), Path("source.gltf"),
        SimpleNamespace(mesh=mesh), None, None, preview_mesh=mesh)
    tab.controller.draft.model_source = ModelSource.IMPORTED
    tab.controller.draft.material_route = MaterialRoute.PLAIN_PBR
    sender = Mock(return_value=True)
    tab.show_step(2)
    _send(bridge, panel.inspector_tabs, "tab", 1)
    monkeypatch.setattr(type(panel.preview), "showing_placement", property(lambda self: True))
    monkeypatch.setattr(panel.preview.host, "apply_material_parameter_groups", sender)
    editor = panel.shader_controls_editor
    editor.refresh((("Blade", "Blade"),), (), equipment_shader_options(material()))
    before = tab.controller._draft_revision
    _send(bridge, editor.family, "choose", editor.family.findData(EYE_COVER.shader))
    assert "Approximate preview" in editor.note.text() and editor.note.isVisibleTo(tab)
    for field_, enabled, spins in editor._rows:
        if not enabled.isChecked():
            _send(bridge, enabled, "toggle", True)
        _send(bridge, spins[0], "number", .25)
    saved = tab.controller.draft.shader_controls
    assert saved == (("Blade", controls(**{field.name: .25 for field in EYE_COVER.fields})),)
    sent = [group for group in sender.call_args.args[0] if group.get("shader_controls")]
    assert len(sent) == 1 and sent[0]["source_submesh_indices"] == [0]
    assert sent[0]["shader_controls"][:9] == [7., 0., 0., 0., *([64 / 255] * 5)]
    assert tab.controller._draft_revision > before
    assert not tab.controller.has_current_plan
    _send(bridge, editor.reset, "activate")
    assert tab.controller.draft.shader_controls == ()


@pytest.mark.parametrize("variant", [False, True])
@pytest.mark.parametrize("imported", [False, True])
def test_complete_plan_and_loose_export_include_owned_eye_cover_maps(tmp_path, variant, imported, monkeypatch):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.new_item_service import NewItemService
    from cdmw.services.new_item_variants import xml_path
    from cdmw.domain.new_item.spec import ModelSource
    from tests.test_new_item_provenance import current_files, spec
    from tests.test_new_item_service import PAC as TEMPLATE_PAC, PAC_XML, build_package, _read
    from tests.test_new_item_variant_authoring import selections

    data = current_files()
    owned = source_files()
    data.update({path: payload for path, payload in owned.side_files.items() if path != XML})
    data[PAC_XML] = owned.side_files[XML]
    original = dict(data)
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / "fixture", data)), read_entry=_read)
    settings = (("Blade", controls(_eyeCoverDiffuseParameter=.35, surface_alpha=.25, material_red=.1)),)
    request = replace(spec(), shader_controls=settings)
    kwargs = {}
    if imported:
        # These plan/export fixtures have opaque geometry; rig parsing has its own tests.
        monkeypatch.setattr("cdmw.services.new_item_variants.validate_variant_rig", lambda *_args, **_kwargs: None)
        request = replace(request, model_source=ModelSource.IMPORTED)
        imported_side = dict(owned.side_files)
        imported_side[PAC_XML] = imported_side.pop(XML)
        kwargs["model"] = replace(owned, pac_data=data[TEMPLATE_PAC], side_files=imported_side)
    if variant:
        binding = next(value for value in selections(snapshot) if value.model_path == TEMPLATE_PAC)
        request = replace(request, variants=(replace(binding, shader_controls=settings, custom_model=imported),))
        if imported:
            kwargs = {"variant_models": {binding.identity: kwargs["model"]}}
    logs = []
    plan = service.plan(request, snapshot, on_log=logs.append, **kwargs)
    assert any("EyeCover material: Encoding" in line for line in logs)
    assert any("EyeCover material: Encoded" in line for line in logs)
    output = next(path for path in plan.loose_files if path.endswith(".pac"))
    blade = find_material_wrappers(plan.loose_files[xml_path(output)].decode("utf-8-sig"))[0]
    assert blade.shader == EYE_COVER.shader
    assert int(blade.value("_eyeCoverDiffuseParameter")) == 89
    generated = [blade.textures[name] for name in ("_alphaTexture", "_materialTexture")]
    for path in generated:
        assert path in plan.loose_files and path not in original
        assert plan.loose_files[path].startswith(b"DDS ")
    assert any("Approximate viewport preview" in line for line in plan.summary_lines)
    service.export_loose(plan, tmp_path / "mod", manager="JMM")
    for path in generated:
        assert (tmp_path / "mod" / path).read_bytes() == plan.loose_files[path]
    assert all(snapshot.payload(path) == payload for path, payload in original.items())
