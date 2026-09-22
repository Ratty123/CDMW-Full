from dataclasses import replace
from functools import partial
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.new_item import template_preview_cache


def test_native_cache_probe_does_not_wait_for_unprepared_textures(tmp_path, monkeypatch):
    from cdmw.services import mesh_rust_preview_cache
    from cdmw.ui.new_item.template_preview_dependencies import PreparedTemplateDependencies

    ticket = PreparedTemplateDependencies()
    entry = SimpleNamespace(identity="template")
    cached = tmp_path / "cached"
    looked_up = []

    def lookup(**context):
        looked_up.append(context)
        return SimpleNamespace(package_dir=cached)

    monkeypatch.setattr(template_preview_cache, "template_preview_cache_identity", lambda *_: "ready-template")
    monkeypatch.setattr(mesh_rust_preview_cache, "lookup_rust_preview_package_from_preview_core_identity", lookup)
    probe = partial(template_preview_cache.build_native_template_preview,
                    entry, (entry,), (), (), 17, SimpleNamespace(), threading.Event(),
                    output_root=tmp_path, native_preview_core_cache_root=tmp_path / "native",
                    render_settings=ModelPreviewRenderSettings(), cache_mode="balanced",
                    cache_only=True, prepared_dependencies=ticket)

    assert probe() is None, "texture preparation cannot delay the geometry worker's cache probe"
    assert not looked_up, "an incomplete dependency snapshot is not a valid cache identity"
    ticket.entries = (entry,)
    ticket.done.set()
    assert probe() == cached, "completed dependency snapshots still use the immediate textured cache hit"
    assert len(looked_up) == 1


def _native_helmet(tmp_path):
    """Two independently editable wrappers sharing one underlying material."""
    import copy
    from tests.test_rust_preview_material_oracle_parity import _layer, _write_preview_core_package

    native = tmp_path / "native-helmet"
    _write_preview_core_package(native, layers=[_layer(role="base", source_parameter="_diffuseTexture")])
    manifest = native / "manifest.json"
    document = json.loads(manifest.read_text())
    first = document["batches"][0]
    first["material_name"] = "helmet_shell"
    second = copy.deepcopy(first)
    second["index"] = 1
    document["batches"].append(second)
    # Material slots can arrive in a different order from the geometry batches.
    document["material_slots"] = [
        {"batch_index": 1, "submesh_name": "helmet_eye", "material_name": "helmet_shell"},
        {"batch_index": 0, "submesh_name": "helmet_shell", "material_name": "helmet_shell"},
    ]
    manifest.write_text(json.dumps(document))
    return native


@pytest.mark.parametrize("first_character", [False, True])
def test_template_character_toggle_keeps_each_cached_material_stage(tmp_path, first_character):
    from cdmw.domain.new_item.translucency import TranslucencyChoice
    from cdmw.services.mesh_dotnet_reference_composite import decode_dotnet_native_preview_package
    from cdmw.ui.new_item.controller_preview_mixin import _template_progressive_source
    from cdmw.ui.new_item.item_preview import _PreviewPackageTask

    native = _native_helmet(tmp_path)
    original = (native / "manifest.json").read_bytes()
    character = decode_dotnet_native_preview_package(native)

    def material_build(stop, **context):
        return context["consume_native_package"](native)

    packages = {}
    for template_key, enabled in ((17, first_character), (17, not first_character),
                                  (29, not first_character), (17, first_character)):
        token, source = _template_progressive_source(
            ("template", template_key), template_key,
            lambda _: decode_dotnet_native_preview_package(native), material_build,
            enabled, lambda _: character if enabled else None,
            translucency=TranslucencyChoice(("helmet_eye",), 0.2, 0.4,
                surface_settings=(("helmet_eye", 0.9, 0.0),)),
        )
        task = _PreviewPackageTask(
            output_root=tmp_path / "output", token=token, candidate=source,
            is_placement=True, full_stage=False, base_package=None,
            render_settings=ModelPreviewRenderSettings(), cache_mode="balanced",
            native_preview_core_cache_root=tmp_path / "native-cache",
            source_usage_required=False, source_usage_acquired=False,
        )
        stages = []
        product = task(None, lambda current, total, path: stages.append((current, Path(path))), threading.Event())
        stages.append((3, product.package_dir))
        assert any(stage == 2 for stage, _ in stages), "exercise the fast material handoff too"
        for stage, package in stages:
            manifest = json.loads((package / "manifest.json").read_text())
            scene = manifest["state"]["preview_scene"]
            assert scene["reference_submesh_count"] == (2 if enabled else 0)
        key = (template_key, enabled)
        if key in packages:
            assert packages[key] == product.package_dir, "revisiting the same scene should reuse its cache"
        packages[key] = product.package_dir
    assert packages[(17, False)] != packages[(17, True)]
    assert (native / "manifest.json").read_bytes() == original


@pytest.mark.parametrize("surface", ["appearance", "effects"])
@pytest.mark.parametrize("selected", ["helmet_shell", "helmet_eye"])
def test_template_appearance_uses_wrapper_identity_instead_of_shared_material(tmp_path, surface, selected):
    from cdmw.domain.new_item.spec import GlowChoice
    from cdmw.domain.new_item.translucency import TranslucencyChoice
    from cdmw.ui.new_item.controller_preview_mixin import _template_progressive_source
    from cdmw.ui.new_item.effect_item_source import PlannedEffectItemSource
    from cdmw.ui.new_item.item_preview import PlacementScene, build_item_preview_package
    from cdmw.ui.new_item.model_import import ModelPlacement

    native = _native_helmet(tmp_path)
    context = dict(output_root=tmp_path / "output", native_preview_core_cache_root=tmp_path / "native-cache",
                   render_settings=ModelPreviewRenderSettings(), cache_mode="off")
    stop = threading.Event()
    glow = GlowChoice((selected,), (1.0, 0.0, 0.0), 4.0)
    glass = TranslucencyChoice((selected,), 0.2, 0.4, surface_settings=((selected, 0.9, 0.0),))

    def material_build(stop, **kwargs):
        return kwargs["consume_native_package"](native)

    if surface == "appearance":
        _, source = _template_progressive_source(
            ("template", 17), 17, lambda _: None, material_build, False, lambda _: None, glow, glass,
        )
        package = source.materials(stop, **context)
    else:
        source = PlannedEffectItemSource(source=None, placement=ModelPlacement(offset=(0.1, 0.0, 0.0)), applied=False,
            preview_model=None, rebuilt_data=b"", snapshot=None, template_key=17, glow=glow,
            translucency=glass, template_build=material_build, preview_context=context)
        package = source.consume(stop, lambda result: build_item_preview_package(
            PlacementScene(template=None, model=result[0]), token="effects", stop_event=stop,
            output_root=tmp_path / "effects"))
    manifest = json.loads((package / "manifest.json").read_text())
    parts = manifest["state"]["preview_scene"]["part_identities"]
    assert [part["name"] for part in parts] == ["helmet_shell", "helmet_eye"]
    assert [part["material"] for part in parts] == ["helmet_shell", "helmet_shell"]
    for index, name in enumerate(("helmet_shell", "helmet_eye")):
        row = manifest["material_presentations"][index]
        assert row["translucency"] == ([0.2, 0.4] if name == selected else None)
        assert row["translucency_surface"] == ([0.9, 0.0] if name == selected else None)
        assert (row.get("emissive_intensity") == 4.0) == (name == selected)


def test_placement_material_upgrade_does_not_temporarily_hide_character(tmp_path):
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame
    from tests.test_new_item_item_preview import ItemPreviewFrameTests

    app = QApplication.instance() or QApplication([])
    frame = ItemPreviewFrame(output_root=tmp_path, host_factory=ItemPreviewFrameTests._fake_host_class())
    frame._ensure_host()
    frame._pending = ("helmet-character", object())
    try:
        for stage in ("geometry", "fast_materials", "materials"):
            package = tmp_path / f"package_{stage}"
            package.mkdir()
            frame._package_ready(package, "helmet-character", True, stage)
        modes = [call[1][0] for call in frame.host.calls if call[0] == "set_display_mode"]
        assert modes == ["overlay"] * 3
    finally:
        frame.shutdown()
        app.processEvents()


@pytest.mark.parametrize("late_result", [False, True])
def test_rapid_character_toggle_restarts_a_cancelled_request(tmp_path, monkeypatch, late_result):
    import time
    from PySide6.QtWidgets import QApplication
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame, _PreviewBuildProduct, _PreviewPackageTask
    from cdmw.ui.new_item.model_import import ModelPlacement
    from tests.test_new_item_item_preview import ItemPreviewFrameTests

    app = QApplication.instance() or QApplication([])
    frame = ItemPreviewFrame(output_root=tmp_path, host_factory=ItemPreviewFrameTests._fake_host_class())
    frame._ensure_host()
    started, release = threading.Event(), threading.Event()
    builds = []

    def build(task, log, progress, stop):
        builds.append(task.token)
        if len(builds) == 1:
            started.set()
            assert release.wait(3)
            assert stop.is_set()
            if not late_result:
                raise RunCancelled("superseded character toggle")
        package = tmp_path / f"package_{len(builds)}"
        package.mkdir()
        if len(builds) == 1:
            progress(2, 3, str(package))
        return _PreviewBuildProduct(package, task.candidate, "materials")

    def pump_until(predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.001)
        assert predicate()

    monkeypatch.setattr(_PreviewPackageTask, "__call__", build)
    try:
        frame.show_placement(object(), token="character-on", placement=ModelPlacement())
        pump_until(started.is_set)
        frame.show_placement(object(), token="character-off", placement=ModelPlacement())
        frame.show_placement(object(), token="character-on", placement=ModelPlacement())
        release.set()
        pump_until(lambda: frame._thread is None)
        assert builds == ["character-on", "character-on"]
        loads = [call[1][0] for call in frame.host.calls if call[0] == "load_package"]
        assert loads == [tmp_path / "package_2"], "cancelled work must not replace the latest scene"
    finally:
        release.set()
        frame.shutdown()
        pump_until(lambda: not frame.iter_shutdown_workers())


@pytest.mark.parametrize("appearance", ["translucency", "glow", "both"])
@pytest.mark.parametrize("include_character", [False, True])
def test_template_appearance_prepares_python_materials_before_overrides(tmp_path, appearance, include_character):
    from PIL import Image
    from cdmw.domain.new_item.spec import GlowChoice
    from cdmw.domain.new_item.translucency import TranslucencyChoice
    from cdmw.models import ModelPreviewData, ModelPreviewMesh
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.ui.new_item.controller_preview_mixin import _template_progressive_source
    from cdmw.ui.new_item.item_preview import _PreviewPackageTask

    textures = {}
    for role, colour in (("base", (40, 100, 180)), ("normal", (128, 128, 255)), ("emissive", (64, 64, 64))):
        path = tmp_path / f"{role}.dds"
        Image.new("RGBA", (4, 4), (*colour, 255)).save(path)
        textures[role] = str(path)
    template = ModelPreviewData(path="sword.pac", format="pac", meshes=[
        ModelPreviewMesh(
            material_name=name, texture_name="base", source_submesh_index=index,
            positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], indices=[0, 1, 2],
            normals=[(0, 0, 1)] * 3, texture_coordinates=[(0, 0), (1, 0), (0, 1)],
            preview_base_texture_default_path=textures["base"],
            preview_normal_texture_default_path=textures["normal"],
            preview_normal_texture_default_strength=1.0,
            preview_emissive_texture_default_path=textures["emissive"],
        ) for index, name in enumerate(("Blade", "Guard"))
    ])
    character = ParsedMesh(path="character.pac", format="pac", submeshes=[SubMesh(
        name="character", vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[(0, 1, 2)],
    )]) if include_character else None
    glow = GlowChoice(("Blade",), (1, 0, 0), 4) if appearance in {"glow", "both"} else None
    glass = TranslucencyChoice(("Blade",), 0.1, 0.3) if appearance in {"translucency", "both"} else None
    token, source = _template_progressive_source(
        ("template", 17), 17, lambda _: None, lambda _: template,
        include_character, lambda _: character, glow, glass,
    )
    task = _PreviewPackageTask(
        output_root=tmp_path / "output", token=token, candidate=source,
        is_placement=True, full_stage=True, base_package=None,
        render_settings=ModelPreviewRenderSettings(use_textures_by_default=True), cache_mode="off",
        native_preview_core_cache_root=None, source_usage_required=False, source_usage_acquired=False,
    )
    package = task(None, lambda *_: None, threading.Event()).package_dir
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    parts = {row["material_index"]: row for row in manifest["material_presentations"] if row["lod_index"] == 0}
    assert parts[0]["translucency"] == ([0.1, 0.3] if glass else None)
    assert parts[1]["translucency"] is None
    if glow:
        assert parts[0]["emissive_color"] == [1.0, 0.0, 0.0]
        assert parts[0]["emissive_intensity"] == 4.0
        assert parts[1].get("emissive_intensity") != 4.0
    for role in ("base_color", "normal", "emissive"):
        bindings = [row for row in manifest["textures"] if row["role"] == role]
        assert {0, 1} <= {index for row in bindings for index in row["material_indices_by_lod"][0]}
        expected = Path(textures["base" if role == "base_color" else role]).read_bytes()
        assert all((package / row["file"]["path"]).read_bytes() == expected for row in bindings)
    assert manifest["state"]["preview_scene"]["reference_submesh_count"] == int(include_character)
    assert all(not mesh.preview_native_material_overrides for mesh in template.meshes)
    assert all(not mesh.preview_texture_path for mesh in template.meshes), "the cached decoded template is unchanged"


@pytest.mark.parametrize("changed", ["primary", "other_texture", "other_index", "removed_archive", "native", "settings", "dependency", "prepared"])
def test_native_template_identity_tracks_all_archive_and_render_inputs(tmp_path, monkeypatch, changed):
    root = tmp_path / "game"
    primary = root / "0000"
    other = root / "0001"
    primary.mkdir(parents=True)
    other.mkdir()
    paths = {
        "primary": primary / "0.paz", "other_texture": other / "0.paz",
        "other_index": other / "0.pamt", "removed_archive": other / "1.paz",
        "native": tmp_path / "preview-core.exe",
        "prepared": tmp_path / "prepared.pac",
    }
    (primary / "0.pamt").write_bytes(b"index")
    for path in paths.values():
        path.write_bytes(b"before")
    monkeypatch.setattr(template_preview_cache, "find_native_preview_core_binary", lambda: paths["native"])
    entry = SimpleNamespace(path="item.pac", pamt_path=primary / "0.pamt", paz_file="0.paz", offset=7, comp_size=3)
    entry.prepared_path = paths["prepared"]
    settings = ModelPreviewRenderSettings(use_textures_by_default=True)
    stop = threading.Event()

    def identity():
        return template_preview_cache.template_preview_cache_identity(entry, (entry,), 17, settings, stop)

    before = identity()
    assert identity() == before
    if changed == "settings":
        settings = replace(settings, d3d11_tone_gamma=1.17)
    elif changed == "dependency":
        entry.offset += 1
    elif changed == "removed_archive":
        paths[changed].unlink()
    else:
        paths[changed].write_bytes(b"changed archive or compiler")
    assert identity() != before


@pytest.mark.parametrize("scene_kind", ["placement", "character"])
@pytest.mark.parametrize("outcome", ["success", "cancel", "error"])
def test_composite_consumes_native_template_before_staging_cleanup(tmp_path, monkeypatch, scene_kind, outcome):
    from PIL import Image
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services import mesh_dotnet_reference_composite, mesh_rust_preview_cache, preview_rendering_service
    from cdmw.ui.new_item.controller_preview_mixin import (
        _placement_progressive_source, _template_progressive_source,
    )
    from cdmw.ui.new_item.model_import import ModelPlacement

    def mesh(name):
        return ParsedMesh(path=name + ".pac", format="pac", submeshes=[SubMesh(
            name=name, vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            faces=[(0, 1, 2)], uvs=[(0, 0), (1, 0), (0, 1)],
        )])

    template, model, character = mesh("template"), mesh("imported"), mesh("character")
    staged = []

    def native_job(_entry, **kwargs):
        output = Path(kwargs["output_root"])
        output.mkdir(parents=True)
        Image.new("RGBA", (4, 4), (32, 96, 192, 255)).save(output / "base.png")
        staged.append(output)
        return SimpleNamespace(succeeded=True, package_path=output)

    def decode(package_path, *, cancelled):
        assert (package_path / "base.png").is_file()
        if outcome == "cancel":
            raise RunCancelled("composition cancelled")
        if outcome == "error":
            raise ValueError("composition failed")
        assert not cancelled()
        template.submeshes[0].preview_texture_path = str(package_path / "base.png")
        return template

    def reject_standalone_cache(**_kwargs):
        pytest.fail("a standalone template package cannot replace the combined scene")

    monkeypatch.setattr(template_preview_cache, "template_preview_cache_identity", lambda *_: "test-native")
    monkeypatch.setattr(preview_rendering_service, "run_native_preview_core_preview_job", native_job)
    monkeypatch.setattr(mesh_dotnet_reference_composite, "decode_dotnet_native_preview_package", decode)
    monkeypatch.setattr(mesh_rust_preview_cache, "lookup_rust_preview_package_from_preview_core_identity", reject_standalone_cache)
    entry = SimpleNamespace(path="item.pac", pamt_path=tmp_path / "game" / "0000" / "0.pamt")
    template_build = partial(
        template_preview_cache.build_native_template_preview,
        entry, (entry,), (), (), 17, SimpleNamespace(),
    )
    if scene_kind == "placement":
        imported = SimpleNamespace(
            baked_scene_mesh=lambda: model, baked_preview_mesh=lambda: model,
            baked_bounds=lambda: ((0, 0, 0), (1, 1, 0)), baked_origin=lambda: (0, 0, 0),
            acquire_usage=lambda: None,
        )
        source = _placement_progressive_source(
            imported, template_build, lambda _: template, ModelPlacement(),
            lambda _: None, ("placement", 17),
        )
    else:
        _, source = _template_progressive_source(
            ("template", 17), 17, lambda _: template, template_build, True, lambda _: character,
        )

    def build():
        return source.materials(
            threading.Event(), output_root=tmp_path / "output",
            native_preview_core_cache_root=tmp_path / "native-cache",
            render_settings=ModelPreviewRenderSettings(), cache_mode="balanced",
        )

    if outcome == "success":
        package = build()
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        scene = manifest["state"]["preview_scene"]
        assert scene["editable_submesh_count"] == 1
        assert scene["reference_submesh_count"] == 1
        assert manifest["textures"], "the template is textured in comparison views"
        assert all(path.stat().st_size > 128 for path in package.rglob("*.dds"))
    else:
        error = RunCancelled if outcome == "cancel" else ValueError
        with pytest.raises(error, match="composition"):
            build()
    assert len(staged) == 1
    assert not staged[0].exists(), "temporary native resources must close on every outcome"


def test_effects_and_template_reuse_one_native_material_package(tmp_path, monkeypatch):
    from cdmw.services import preview_rendering_service, mesh_dotnet_reference_composite
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.ui.new_item.effect_item_source import PlannedEffectItemSource
    from cdmw.ui.new_item.model_import import ModelPlacement
    calls, consumed = [], []

    def native_job(_entry, **kwargs):
        output = Path(kwargs["output_root"])
        output.mkdir(parents=True)
        (output / "base.dds").write_bytes(b"authored texture")
        (output / "manifest.json").write_text(json.dumps({"batches": [{"textures": {"base": "base.dds"}}]}))
        calls.append(output)
        return SimpleNamespace(succeeded=True, package_path=output)

    def decode(package, **_kwargs):
        consumed.append(package)
        assert (package / "base.dds").read_bytes() == b"authored texture"
        mesh = ParsedMesh(path="item.pac", format="pac", submeshes=[SubMesh(name="blade", vertices=[(0, 0, 0)])])
        mesh.submeshes[0].preview_texture_path = str(package / "base.dds")
        return mesh

    monkeypatch.setattr(template_preview_cache, "template_preview_cache_identity", lambda *_: "reuse-test")
    monkeypatch.setattr(preview_rendering_service, "run_native_preview_core_preview_job", native_job)
    monkeypatch.setattr(mesh_dotnet_reference_composite, "decode_dotnet_native_preview_package", decode)
    entry = SimpleNamespace(path="item.pac", pamt_path=tmp_path / "game" / "0000" / "0.pamt")
    build = partial(template_preview_cache.build_native_template_preview,
                    entry, (entry,), (), (), 17, SimpleNamespace())
    context = dict(output_root=tmp_path / "output", native_preview_core_cache_root=tmp_path / "native-cache",
                   render_settings=ModelPreviewRenderSettings(d3d11_tone_gamma=1.17), cache_mode="balanced")
    stop = threading.Event()
    first = build(stop, **context, consume_native_package=lambda package: package)
    item = PlannedEffectItemSource(source=None, placement=ModelPlacement(offset=(1, 0, 0)), applied=False,
        preview_model=None, rebuilt_data=b"", snapshot=None, template_key=17, glow=None,
        template_build=build, preview_context=context)

    def consume(result):
        mesh, kind = result
        assert kind == "template"
        assert mesh.submeshes[0].vertices == [(1, 0, 0)]
        assert Path(mesh.submeshes[0].preview_texture_path).is_file()
        return "effect package"

    assert item.consume(stop, consume) == "effect package"
    assert len(calls) == 1 and consumed == [first]
    assert first.is_dir(), "durable template textures remain reusable after Effects consumes them"
