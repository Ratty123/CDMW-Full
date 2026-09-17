"""Regression coverage for preview ownership and authored texture revisions."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from cdmw.models import ModelPreviewRenderSettings, RunCancelled
from cdmw.rendering.native_preview_package_cache import acquire_native_preview_package_cache_lease_for_path
from cdmw.services import model_library_preview as preview
from cdmw.services.mesh_rust_preview_package import validate_rust_preview_package
from cdmw.workers.model_library_workers import remove_model_library_preview_package_dir
from tests.test_model_library_preview import _write_triangle_gltf


@pytest.mark.parametrize("delivery", ["stale", "shutdown"])
def test_late_ui_delivery_retires_undelivered_package(tmp_path, monkeypatch, delivery):
    from cdmw.ui.model_library import preview as ui_preview

    threads = []

    def remove(package):
        thread = remove_model_library_preview_package_dir(package)
        threads.append(thread)
        return thread

    monkeypatch.setattr(ui_preview, "remove_model_library_preview_package_dir", remove)

    class Owner(ui_preview.ModelLibraryInlinePreviewMixin):
        _task_thread = None
        _inline_preview_request_id = 0
        _pending_icon_generation_for_next_preview = False
        inline_preview_render_settings = ModelPreviewRenderSettings()
        inline_preview_stack = SimpleNamespace(setCurrentWidget=lambda widget: None)

        def _prepare_inline_preview_orientation_for_load(self, **kwargs):
            pass

        def _ensure_inline_d3d11_preview_host(self):
            return object()

        def _set_inline_preview_status(self, *args, **kwargs):
            pass

        def _run_task(self, status, task, complete, **kwargs):
            self.deliver = complete

    owner = Owner()
    owner._load_inline_model_preview(tmp_path / "model.obj", {"name": "Model"})
    package = tmp_path / "cdmw_rust_preview_undelivered" / "package"
    package.mkdir(parents=True)
    request_id = owner._inline_preview_request_id
    if delivery == "stale":
        owner._inline_preview_request_id += 1
    else:
        owner._model_library_shutting_down = True
    owner.deliver({"request_id": request_id, "rust_preview_package_path": str(package)})
    assert len(threads) == 1 and threads[0] is not None
    threads[0].join(5)
    assert not threads[0].is_alive()
    assert not package.parent.exists()
    assert not list(tmp_path.glob(".cdmw_retired_preview_*"))


@pytest.mark.parametrize("prefix", ["cdmw_dotnet_preview_", "cdmw_rust_preview_"])
def test_cleanup_removes_transient_wrapper_and_preserves_durable_packages(tmp_path, prefix):
    package = tmp_path / f"{prefix}owned" / "package"
    package.mkdir(parents=True)
    (package / "payload").write_bytes(b"owned")
    durable = tmp_path / "rust_wgpu_v1" / "packages" / "cached" / "package"
    durable.mkdir(parents=True)
    assert remove_model_library_preview_package_dir(durable) is None
    thread = remove_model_library_preview_package_dir(package)
    assert thread is not None
    thread.join(5)
    assert not thread.is_alive()
    assert not package.parent.exists()
    assert durable.exists()


def test_cleanup_waits_for_live_renderer_lease(tmp_path):
    package = tmp_path / "cdmw_rust_preview_owned" / "package"
    package.mkdir(parents=True)
    lease = acquire_native_preview_package_cache_lease_for_path(package)
    assert lease is not None
    thread = remove_model_library_preview_package_dir(package)
    try:
        thread.join(0.1)
        assert thread.is_alive()
        assert package.is_dir()
    finally:
        lease.release()
        thread.join(5)
    assert not thread.is_alive()
    assert not package.parent.exists()


@pytest.mark.parametrize("cached", [False, True])
def test_cancellation_after_real_package_build_cleans_only_private_output(tmp_path, monkeypatch, cached):
    monkeypatch.setattr(preview.tempfile, "tempdir", str(tmp_path))
    source = _write_triangle_gltf(tmp_path)
    if not cached:
        monkeypatch.setattr(preview, "_model_library_preview_package_cache_identity", lambda *a, **kw: None)
    stop = threading.Event()
    built = []
    build = preview._build_model_library_fast_package

    def cancel_after_build(*args, **kwargs):
        package = build(*args, **kwargs)
        built.append(Path(package))
        stop.set()
        return package

    monkeypatch.setattr(preview, "_build_model_library_fast_package", cancel_after_build)
    with pytest.raises(RunCancelled):
        preview.prepare_model_library_inline_preview(source, stop_event=stop)
    assert len(built) == 1
    assert built[0].exists() == cached
    if cached:
        assert validate_rust_preview_package(built[0]) == ()
    else:
        assert not built[0].parent.exists()


def _write_obj(root: Path, texture_key: str) -> Path:
    source = root / "triangle.obj"
    source.write_text(
        "mtllib triangle.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 0 1\nusemtl A\nf 1/1 2/2 3/3\n", encoding="utf-8",
    )
    (root / "triangle.mtl").write_text(
        f"newmtl A\nKd 1 1 1\nKe 1 1 1\n{texture_key} triangle_emissive.png\n", encoding="utf-8",
    )
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(root / "triangle_emissive.png")
    return source


@pytest.mark.parametrize("texture_key", [
    "map_Kd", "map_Ka", "map_Ks", "map_Ke", "map_Bump", "bump", "norm", "map_Ns",
    "map_Pr", "map_Pm", "map_d", "map_Tr", "disp", "decal", "map_PBR", "map_ORM",
    "map_roughness", "map_metallic",
])
def test_obj_cache_tracks_every_supported_texture_reference(tmp_path, texture_key):
    source = _write_obj(tmp_path, texture_key)
    settings = ModelPreviewRenderSettings()

    def identity():
        return preview._model_library_preview_package_cache_identity(
            source, source, extract_root=None, render_settings=settings,
            texture_flip_vertical=True, stop_event=None,
        )

    before = identity()
    assert before is not None
    Image.new("RGBA", (4, 4), (0, 255, 0, 255)).save(tmp_path / "triangle_emissive.png")
    assert identity() != before
    (tmp_path / "triangle_emissive.png").unlink()
    assert identity() is None


def test_emissive_edit_rebuilds_real_package_and_then_reuses_it(tmp_path, monkeypatch):
    monkeypatch.setattr(preview.tempfile, "tempdir", str(tmp_path))
    source = _write_obj(tmp_path, "map_Ke")
    first = preview.prepare_model_library_inline_preview(source)
    Image.new("RGBA", (4, 4), (0, 255, 0, 255)).save(tmp_path / "triangle_emissive.png")
    second = preview.prepare_model_library_inline_preview(source)
    first_path = Path(first["rust_preview_package_path"])
    second_path = Path(second["rust_preview_package_path"])
    assert first_path != second_path

    def emissive_hash(path):
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        return next(row["file"]["sha256"] for row in manifest["textures"] if row["role"] == "emissive")

    assert emissive_hash(first_path) != emissive_hash(second_path)
    assert validate_rust_preview_package(second_path) == ()

    def unexpected_import(*args, **kwargs):
        raise AssertionError("unchanged source should reuse its package")

    monkeypatch.setattr(preview, "import_scene_mesh_with_report", unexpected_import)
    assert preview.prepare_model_library_inline_preview(source)["rust_preview_package_path"] == str(second_path)


@pytest.mark.parametrize("declaration", ["", "mtllib\ttriangle.mtl", "mtllib triangle.mtl extra.mtl"])
def test_obj_cache_tracks_importer_material_library_forms(tmp_path, monkeypatch, declaration):
    monkeypatch.setattr(preview.tempfile, "tempdir", str(tmp_path))
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = _write_obj(inputs, "map_Ke")
    source.write_text(source.read_text().replace("mtllib triangle.mtl", declaration), encoding="utf-8")
    (inputs / "extra.mtl").write_text("newmtl unused\nKd 1 1 1\n", encoding="utf-8")
    first = preview.prepare_model_library_inline_preview(source)
    Image.new("RGBA", (4, 4), (0, 255, 0, 255)).save(inputs / "triangle_emissive.png")
    second = preview.prepare_model_library_inline_preview(source)
    assert first["textures"] == second["textures"] == 1
    assert first["rust_preview_package_path"] != second["rust_preview_package_path"]
    def emissive_hash(result):
        manifest = json.loads((Path(result["rust_preview_package_path"]) / "manifest.json").read_text(encoding="utf-8"))
        return next(row["file"]["sha256"] for row in manifest["textures"] if row["role"] == "emissive")

    assert emissive_hash(first) != emissive_hash(second)
    assert not Path(second["rust_preview_package_path"]).parent.name.startswith("cdmw_rust_preview_")
    third = preview.prepare_model_library_inline_preview(source)
    assert third["cache_hit"]
    assert third["rust_preview_package_path"] == second["rust_preview_package_path"]


def test_obj_texture_path_with_spaces_does_not_hash_a_basename_decoy(tmp_path):
    source = _write_obj(tmp_path, "map_Ke")
    texture = tmp_path / "textures" / "triangle emission.png"
    texture.parent.mkdir()
    (tmp_path / "triangle_emissive.png").replace(texture)
    Image.new("RGBA", (4, 4), (0, 0, 255, 255)).save(tmp_path / "emission.png")
    (tmp_path / "triangle.mtl").write_text(
        "newmtl A\nmap_Ke -clamp on textures/triangle emission.png\n", encoding="utf-8",
    )

    def identity():
        return preview._model_library_preview_package_cache_identity(
            source, source, extract_root=None, render_settings=ModelPreviewRenderSettings(),
            texture_flip_vertical=True, stop_event=None,
        )

    first = identity()
    assert first is not None
    Image.new("RGBA", (4, 4), (0, 255, 0, 255)).save(texture)
    assert identity() != first
