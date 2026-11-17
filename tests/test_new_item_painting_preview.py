"""New painting's 3D view: the frame's decoded mesh with the composed picture on its canvas."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from cdmw.core.painting_picture import CanvasMapping, compose_picture, load_picture, plan_picture_texture
from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput
from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.services.new_item_painting_preview import (
    PaintingPreviewError,
    composed_picture_png,
    painting_preview_model,
    painting_preview_source,
)

# An atlas frame: the canvas samples one cell of a 512 x 256 texture.
FRAME = SimpleNamespace(
    mesh="object/00_common/interior/decopropw/cd_in_dpw_picture_animal_04.pam", stem="cd_in_dpw_picture_animal_04",
    texture_size=(512, 256),
    canvas=CanvasMapping(material="cd_in_dpw_picture_animal_01", uv_rect=(0.5, 0.0, 1.0, 1.0), size_m=(0.7, 1.25),
                         vertex_count=4))


def _decoded():
    base = PreviewMaterialTextureInput(slot_kind="base", source_texture_path="object/texture/cd_in_dpw_picture_animal_01.dds")
    normal = PreviewMaterialTextureInput(slot_kind="normal", source_texture_path="object/texture/n.dds")
    canvas = ModelPreviewMesh(material_name="cd_in_dpw_picture_animal_01", preview_texture_path="shipped.png",
                              preview_material_texture_inputs=(base, normal))
    wood = ModelPreviewMesh(material_name="cd_bg_wood_01", preview_texture_path="wood.png",
                            preview_material_texture_inputs=(PreviewMaterialTextureInput(slot_kind="base"),))
    return SimpleNamespace(preview_model=ModelPreviewData(path=FRAME.mesh, meshes=[canvas, wood]))


@pytest.fixture
def picture(tmp_path):
    path = tmp_path / "tall.png"
    image = Image.new("RGB", (300, 600), (20, 90, 200))
    image.paste((220, 30, 30), (0, 0, 300, 100))  # red at the top
    image.save(path)
    return path


def test_the_canvas_shows_the_texture_the_build_writes_and_the_frame_keeps_its_own(tmp_path, picture):
    decoded = _decoded()
    calls = []

    def decode(entry, **kwargs):
        calls.append((entry, kwargs))
        return decoded

    model = painting_preview_model("frame-entry", FRAME, str(picture), "fill", texture_entries_by_normalized_path={"a": 1},
                                   texture_entries_by_basename={"b": 2}, folder=tmp_path / "out", decode=decode)
    assert calls[0][0] == "frame-entry" and calls[0][1]["texture_entries_by_basename"] == {"b": 2}
    canvas, wood = model.meshes
    shown = Image.open(canvas.preview_texture_path)
    expected = compose_picture(load_picture(picture), plan_picture_texture(FRAME.texture_size, FRAME.canvas), fit="fill")
    # The whole texture as the build composes it, the picture in the atlas cell on the right.
    assert shown.size == (512, 256)
    assert shown.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()
    assert shown.getpixel((400, 2))[:3] == (220, 30, 30)
    assert canvas.preview_texture_dds_path == ""
    assert [value.slot_kind for value in canvas.preview_material_texture_inputs] == ["normal"]
    assert (wood.preview_texture_path, len(wood.preview_material_texture_inputs)) == ("wood.png", 1)
    # The decode itself is left as it was: it may be cached and shared.
    assert decoded.preview_model.meshes[0].preview_texture_path == "shipped.png"
    assert len(decoded.preview_model.meshes[0].preview_material_texture_inputs) == 2


def test_without_a_picture_the_frame_shows_the_games_picture(tmp_path):
    model = painting_preview_model("frame-entry", FRAME, "", "fill", texture_entries_by_normalized_path={},
                                   texture_entries_by_basename={}, folder=tmp_path, decode=lambda *_a, **_k: _decoded())
    assert model.meshes[0].preview_texture_path == "shipped.png"


def test_a_frame_without_its_canvas_or_mesh_is_refused(tmp_path, picture):
    def no_canvas(*_args, **_kwargs):
        decoded = _decoded()
        decoded.preview_model.meshes.pop(0)
        return decoded

    with pytest.raises(PaintingPreviewError, match="no canvas part"):
        painting_preview_model("e", FRAME, str(picture), "fill", texture_entries_by_normalized_path={},
                               texture_entries_by_basename={}, folder=tmp_path, decode=no_canvas)
    with pytest.raises(PaintingPreviewError, match="has no file"):
        painting_preview_model(None, FRAME, str(picture), "fill", texture_entries_by_normalized_path={},
                               texture_entries_by_basename={}, folder=tmp_path, decode=no_canvas)


def test_the_composed_picture_is_made_once_and_old_ones_are_cleared(tmp_path, picture):
    first = composed_picture_png(FRAME, picture, "fill", tmp_path)
    stamp = first.stat().st_mtime_ns
    assert composed_picture_png(FRAME, picture, "fill", tmp_path) == first
    assert first.stat().st_mtime_ns == stamp
    whole = composed_picture_png(FRAME, picture, "whole", tmp_path)
    assert whole != first
    for number in range(20):
        (tmp_path / f"canvas-old{number:02d}.png").write_bytes(b"x")
    composed_picture_png(FRAME, picture, "fill", tmp_path)
    assert len(list(tmp_path.glob("canvas-*.png"))) <= 12
    assert not list(tmp_path.glob("*.part.png"))


def test_the_source_reads_the_archives_only_when_the_worker_runs_it(tmp_path, picture, monkeypatch):
    seen = []

    class Snapshot:
        entries = {FRAME.mesh: "frame-entry"}

        def archive_index_maps(self):
            seen.append(threading.get_ident())
            return {}, {}

    monkeypatch.setattr("cdmw.services.archive_preview_service.build_archive_preview_result",
                        lambda entry, **_kwargs: _decoded())
    build = painting_preview_source(Snapshot(), FRAME, str(picture), "fill", folder=tmp_path)
    assert seen == []
    model = build(threading.Event())
    assert seen and model.meshes[0].preview_texture_path.endswith(".png")
