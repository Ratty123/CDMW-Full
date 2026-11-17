"""A frame's canvas and the picture texture planned for it, on synthetic meshes and images."""
import struct

import pytest
from PIL import Image

from cdmw.core.painting_picture import (
    FIT_FILL,
    FIT_WHOLE,
    PaintingPictureError,
    compose_picture,
    dds_size,
    find_canvas,
    full_mip_count,
    load_picture,
    plan_picture_texture,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def quad(material, width, height, uv, *, flip_v=False, z=0.0):
    """A canvas quad centred at the origin; `uv` is (u0, v0, u1, v1), v growing down unless flipped."""
    u0, v0, u1, v1 = uv
    top, bottom = (v1, v0) if flip_v else (v0, v1)
    vertices = [(-width / 2, height / 2, z), (width / 2, height / 2, z), (-width / 2, -height / 2, z), (width / 2, -height / 2, z)]
    uvs = [(u0, top), (u1, top), (u0, bottom), (u1, bottom)]
    return SubMesh(name=material, material=material, vertices=vertices, uvs=uvs, faces=[(0, 1, 2), (1, 3, 2)])


def frame(*submeshes):
    return ParsedMesh(path="object/frames/test_frame.pam", format="pam", submeshes=list(submeshes))


def test_the_canvas_is_the_one_upright_planar_picture_surface():
    mesh = frame(quad("cd_in_picture_09", 0.775, 0.639, (0.134, 0.003, 0.909, 0.993)),
                 quad("cd_bg_wood_01", 0.86, 0.75, (0.0, 0.0, 1.0, 1.0), flip_v=True))
    canvas = find_canvas(mesh, ["cd_in_picture_09", "cd_bg_wood_01", "cd_rope_02"])
    assert canvas.material == "cd_in_picture_09"
    assert canvas.uv_rect == pytest.approx((0.134, 0.003, 0.909, 0.993))
    assert canvas.size_m == pytest.approx((0.775, 0.639), abs=1e-6)


def test_a_frame_whose_canvas_is_turned_round_is_refused():
    with pytest.raises(PaintingPictureError, match="has 0 canvas surfaces"):
        find_canvas(frame(quad("cd_in_picture_14", 1.12, 1.6, (0, 0, 1, 1), flip_v=True)), ["cd_in_picture_14"])


def test_a_surface_without_a_picture_material_is_not_a_canvas():
    with pytest.raises(PaintingPictureError, match="has 0 canvas surfaces"):
        find_canvas(frame(quad("cd_bg_trimborder_metal_08", 1, 1, (0, 0, 1, 1))), ["cd_in_picture_09"])


def test_the_texture_plan_keeps_the_source_size_with_full_mips_and_maps_the_canvas_rect():
    canvas = find_canvas(frame(quad("pic", 0.7, 0.424, (0.0, 0.004, 1.0, 0.695))), ["pic"])
    plan = plan_picture_texture((256, 256), canvas)
    assert (plan.width, plan.height, plan.mip_count, plan.dds_format) == (256, 256, 9, "BC1_UNORM")
    assert plan.rect == (0, 1, 256, 178)
    assert plan.aspect == pytest.approx(0.7 / 0.424, rel=1e-3)
    assert [full_mip_count(*size) for size in ((512, 256), (1024, 512), (1024, 1024))] == [10, 11, 11]


def test_uvs_overhanging_the_texture_are_clamped():
    canvas = find_canvas(frame(quad("pic", 0.996, 1.51, (-0.026, -0.048, 0.365, 0.544))), ["pic"])
    assert canvas.uv_rect == pytest.approx((0.0, 0.0, 0.365, 0.544))
    assert plan_picture_texture((1024, 1024), canvas).rect == (0, 0, 374, 558)


def test_a_texture_size_bc1_cannot_hold_is_refused():
    canvas = find_canvas(frame(quad("pic", 1, 1, (0, 0, 1, 1))), ["pic"])
    with pytest.raises(PaintingPictureError, match="multiples of 4"):
        plan_picture_texture((250, 256), canvas)


def picture(width, height):
    """Left half red, right half blue; the top eighth green."""
    image = Image.new("RGB", (width, height), (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, width // 2, height))
    image.paste((0, 255, 0), (0, 0, width, height // 8))
    return image


def test_the_picture_lands_upright_in_the_canvas_rect_and_its_edges_extend_outward():
    canvas = find_canvas(frame(quad("pic", 1.0, 0.5, (0.25, 0.0, 0.75, 0.5))), ["pic"])
    plan = plan_picture_texture((64, 64), canvas)
    assert plan.rect == (16, 0, 48, 32)
    image = compose_picture(picture(200, 100), plan, fit=FIT_FILL)
    assert image.size == (64, 64) and image.mode == "RGBA"
    assert image.getpixel((20, 16))[:3] == (255, 0, 0)       # left of the picture
    assert image.getpixel((44, 16))[:3] == (0, 0, 255)       # right of the picture
    assert image.getpixel((2, 16))[:3] == (255, 0, 0)        # left of the rect repeats the left edge
    assert image.getpixel((44, 60))[:3] == (0, 0, 255)       # below the rect repeats the bottom row
    assert image.getpixel((30, 0))[:3] == (0, 255, 0)        # the top stays at the top
    assert image.getpixel((30, 30))[1] < 64                  # and not at the bottom
    assert {image.getpixel((x, y))[3] for x in range(0, 64, 7) for y in range(0, 64, 7)} == {255}


def test_the_picture_is_written_the_way_round_the_shipped_pictures_are():
    """A pin, not a fix: the build was checked against the game and found right (2026-11-17,
    `.work/research/2026-11-17-painting-mirror`). Every offered frame's canvas faces -z with u
    along +x and v down -y, and the game's own item icons show each shipped picture's canvas
    cell (`plan_picture_texture(...).rect`) unmirrored and upright, the animal atlases
    included. So the picture's left edge goes to the cell's lowest u and its top to the lowest
    v, as in `cd_in_dpw_picture_animal_01.dds`, whose rooster cell (u 0.648 to 1.0, v 0.099
    to 0.439 on `cd_in_dpw_picture_animal_12`) faces right in the DDS and in game."""
    rooster = find_canvas(frame(quad("pic", 0.704, 0.68, (0.648, 0.099, 1.0, 0.439), z=-0.02)), ["pic"])
    plan = plan_picture_texture((1024, 1024), rooster)
    left, top, right, bottom = plan.rect
    assert (left, top, right, bottom) == pytest.approx((663, 101, 1024, 450), abs=1)
    image = compose_picture(picture(704, 680), plan, fit=FIT_FILL)
    middle = (left + right) // 2
    assert image.getpixel((left + 4, 300))[:3] == (255, 0, 0)     # the picture's left at the cell's lowest u
    assert image.getpixel((right - 4, 300))[:3] == (0, 0, 255)    # its right at the highest u
    assert image.getpixel((middle, top + 3))[:3] == (0, 255, 0)   # its top at the lowest v
    assert image.getpixel((middle, bottom - 3))[1] < 64


def test_fill_crops_and_whole_pads_to_the_canvas_shape():
    canvas = find_canvas(frame(quad("pic", 1.0, 1.0, (0, 0, 1, 1))), ["pic"])
    plan = plan_picture_texture((32, 32), canvas)
    wide = Image.new("RGB", (300, 100), (255, 0, 0))
    wide.paste((0, 0, 255), (100, 0, 200, 100))              # blue middle third
    filled = compose_picture(wide, plan, fit=FIT_FILL)
    assert filled.getpixel((1, 16))[:3] == (0, 0, 255)       # the red sides are cropped away
    whole = compose_picture(wide, plan, fit=FIT_WHOLE)
    assert whole.getpixel((1, 16))[:3] == (255, 0, 0)        # the whole width is kept
    assert whole.getpixel((16, 1))[:3] != (255, 0, 0)        # with bands above and below


def test_refusals_for_a_missing_or_unreadable_picture(tmp_path):
    with pytest.raises(PaintingPictureError, match="Choose a picture"):
        load_picture("")
    with pytest.raises(PaintingPictureError, match="does not exist"):
        load_picture(tmp_path / "missing.png")
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a picture")
    with pytest.raises(PaintingPictureError, match="could not be read as a picture"):
        load_picture(broken)
    good = tmp_path / "good.jpg"
    picture(8, 4).save(good)
    assert load_picture(good).size == (8, 4)


def test_dds_size_reads_the_header():
    header = b"DDS " + struct.pack("<II", 124, 0) + struct.pack("<II", 256, 512)
    assert dds_size(header) == (512, 256)
    with pytest.raises(PaintingPictureError):
        dds_size(b"PNG")
