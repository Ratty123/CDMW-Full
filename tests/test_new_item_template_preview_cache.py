from dataclasses import replace
from functools import partial
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.new_item import template_preview_cache


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
