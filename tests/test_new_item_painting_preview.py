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


def test_a_part_the_decode_left_bare_takes_its_texture_from_the_paintings_material_file(tmp_path, picture):
    """cd_in_dpw_picture_06 (2026-11-17): two metal trims came out untextured, though the
    painting's .pami binds them to cd_bg_trimborder_metal_06.dds."""
    def decode(*_args, **_kwargs):
        decoded = _decoded()
        decoded.preview_model.meshes.append(ModelPreviewMesh(material_name="cd_bg_trimborder_metal_01"))
        return decoded

    pami = ('<StaticMeshInstance><MaterialData><Material PrimitiveName="cd_bg_trimborder_metal_01"><Parameters>'
            '<MaterialParameterTexture Name="_baseColorTexture" Value="object/texture/cd_bg_trimborder_metal_06.dds"/>'
            '</Parameters></Material><Material PrimitiveName="cd_bg_wood_01"><Parameters>'
            '<MaterialParameterTexture Name="_baseColorTexture" Value="object/texture/other.dds"/>'
            '</Parameters></Material></MaterialData></StaticMeshInstance>')
    asked = []

    def preview(entry, *, stop_event=None):
        asked.append(entry)
        return f"{entry}.png"

    model = painting_preview_model("e", FRAME, str(picture), "fill", texture_entries_by_normalized_path={},
                                   texture_entries_by_basename={}, folder=tmp_path, decode=decode, pami_text=pami,
                                   texture_entry_of=lambda path: f"entry:{path}", texture_preview=preview)
    trim = model.meshes[2]
    assert trim.preview_texture_path == "entry:object/texture/cd_bg_trimborder_metal_06.dds.png"
    assert trim.preview_base_texture_source == "pami"
    # Parts the decode textured keep their texture; the canvas gets the picture, not the .pami's.
    assert model.meshes[1].preview_texture_path == "wood.png"
    assert asked == ["entry:object/texture/cd_bg_trimborder_metal_06.dds"]


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


def _stock_shaped_frame():
    """A frame built the way the game's are (`cd_in_dpw_picture_*.pam`, game 1.0.0.3663): the
    canvas faces -z, away from the wall at z = 0, its triangles wound so that their normal
    points at -z, with u running along +x across the atlas cell and v running down -y. The
    back board faces the wall."""
    u0, v0, u1, v1 = FRAME.canvas.uv_rect
    corners = [(-0.35, 1.25), (0.35, 1.25), (-0.35, 0.0), (0.35, 0.0)]
    canvas = ModelPreviewMesh(
        material_name=FRAME.canvas.material, preview_texture_path="shipped.png",
        positions=[(x, y, -0.02) for x, y in corners],
        normals=[(0.0, 0.0, -1.0)] * 4,
        texture_coordinates=[(u0 + (u1 - u0) * (x + 0.35) / 0.7, v0 + (v1 - v0) * (1.25 - y) / 1.25) for x, y in corners],
        indices=[0, 1, 2, 1, 3, 2])
    back = ModelPreviewMesh(
        material_name="cd_bg_wood_01", preview_texture_path="wood.png",
        positions=[(x, y, 0.0) for x, y in corners], normals=[(0.0, 0.0, 1.0)] * 4,
        texture_coordinates=[(0.0, 0.0)] * 4, indices=[0, 2, 1, 1, 2, 3])
    return SimpleNamespace(preview_model=ModelPreviewData(path=FRAME.mesh, meshes=[canvas, back]))


def _screen(model):
    """Where the viewport puts things: its first camera (`semantic_initial_view`, the package's
    framing) through a right-handed look-at, as `camera.rs` and `look_at_rh` draw it."""
    import numpy as np

    from cdmw.services.mesh_rust_preview_package import semantic_initial_view

    points = np.array([p for mesh in model.meshes for p in mesh.positions], dtype=float)
    view = semantic_initial_view((points.min(0), points.max(0)), "grounded")
    forward = np.array(view["view_direction"], dtype=float)
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.array(view["screen_up_direction"], dtype=float))
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return forward, (lambda point: (float(np.dot(point, right)), float(np.dot(point, up))))


def test_the_3d_view_shows_the_picture_the_way_round_the_game_does(tmp_path):
    """The game shows a shipped picture unmirrored from the front: its item icons, renders of
    the painting from the front, match the decoded DDS cell for cell (the rooster of
    `cd_in_dpw_picture_animal_01.dds` faces right in both). The viewport is right-handed and
    looks from -z, so before the frame was mirrored the picture's left edge (the canvas's
    lowest u) was drawn on the right of the screen."""
    import numpy as np

    path = tmp_path / "asymmetric.png"
    image = Image.new("RGB", (280, 500), (120, 20, 40))
    image.paste((0, 160, 60), (0, 0, 280, 80))     # green at the top
    image.paste((220, 30, 30), (0, 80, 50, 500))   # red down the left side
    image.save(path)
    decoded = _stock_shaped_frame()
    model = painting_preview_model("frame-entry", FRAME, str(path), "fill", texture_entries_by_normalized_path={},
                                   texture_entries_by_basename={}, folder=tmp_path / "out",
                                   decode=lambda *_a, **_k: decoded)
    forward, screen = _screen(model)
    canvas = model.meshes[0]
    texture = Image.open(canvas.preview_texture_path).convert("RGB")

    def colour(index):
        u, v = canvas.texture_coordinates[index]
        x = min(texture.width - 1, int(u * texture.width))
        y = min(texture.height - 1, int(v * texture.height))
        return texture.getpixel((x, y))

    placed = [(screen(canvas.positions[i]), i) for i in range(4)]
    left_top = min(placed, key=lambda item: (round(item[0][0], 6), -item[0][1]))[1]
    right_bottom = max(placed, key=lambda item: (round(item[0][0], 6), -item[0][1]))[1]
    # The canvas's lowest u, the picture's left edge, is on the left of the screen.
    assert canvas.texture_coordinates[left_top][0] < canvas.texture_coordinates[right_bottom][0]
    assert colour(left_top) == (0, 160, 60)          # its top left corner is the green band
    bottom_left = min(placed, key=lambda item: (round(item[0][0], 6), item[0][1]))[1]
    assert colour(bottom_left) == (220, 30, 30)      # down the left side the red bar
    # Every face still faces the camera after the mirror, so it is drawn lit, not culled.
    for mesh, facing in ((canvas, -1.0), (model.meshes[1], 1.0)):
        points = np.array(mesh.positions)
        for a, b, c in np.array(mesh.indices).reshape(-1, 3):
            normal = np.cross(points[b] - points[a], points[c] - points[a])
            assert np.dot(normal, -forward) * -facing > 0
            assert np.dot(normal, np.array(mesh.normals[a])) > 0
    # The decode, which may be cached and shared, is not mirrored with it.
    assert decoded.preview_model.meshes[0].positions[0] == (-0.35, 1.25, -0.02)
    assert decoded.preview_model.meshes[0].indices == [0, 1, 2, 1, 3, 2]


def test_the_frame_shows_the_games_own_picture_the_same_way_round(tmp_path):
    decoded = _stock_shaped_frame()
    model = painting_preview_model("frame-entry", FRAME, "", "fill", texture_entries_by_normalized_path={},
                                   texture_entries_by_basename={}, folder=tmp_path, decode=lambda *_a, **_k: decoded)
    _forward, screen = _screen(model)
    canvas = model.meshes[0]
    order = sorted(range(4), key=lambda i: screen(canvas.positions[i])[0])
    assert canvas.preview_texture_path == "shipped.png"
    assert {canvas.texture_coordinates[i][0] for i in order[:2]} == {FRAME.canvas.uv_rect[0]}
