"""Mesh faces to texture pixels (Select From Mesh Selection) and back (textures.mesh_at)."""

from __future__ import annotations

import math
import time

import numpy as np
import pytest

from cdmw.domain.textures.editor_selection import apply_texture_editor_mask_selection
from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
from cdmw.domain.textures.uv_selection import UvPart, texel_position, uv_faces_covering, uv_faces_mask
from cdmw.models import TextureEditorDocument, TextureEditorLayer

QUAD_FACES = ((0, 1, 2), (0, 2, 3))


def _quad(u0, v0, u1, v1, part=0, flip_v=False):
    return UvPart(part, ((u0, v0), (u1, v0), (u1, v1), (u0, v1)), QUAD_FACES, flip_v=flip_v)


def _reference(width, height, part, face):
    """Brute force: each pixel centre against every repeat of the triangle in pixels."""

    a, b, c = (texel_position(*part.uvs[i], width, height, flip_v=part.flip_v) for i in part.faces[face])
    area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if area < 0:
        b, c = c, b
    mask = np.zeros((height, width), dtype=bool)
    xs, ys = [p[0] for p in (a, b, c)], [p[1] for p in (a, b, c)]
    for tx in range(math.floor(min(xs) / width) - 1, math.floor(max(xs) / width) + 2):
        for ty in range(math.floor(min(ys) / height) - 1, math.floor(max(ys) / height) + 2):
            gx, gy = np.meshgrid(np.arange(width) + 0.5 + tx * width, np.arange(height) + 0.5 + ty * height)
            inside = np.ones_like(gx, dtype=bool)
            for p, q in ((a, b), (b, c), (c, a)):
                ex, ey = q[0] - p[0], q[1] - p[1]
                inside &= (ex * (gy - p[1]) - ey * (gx - p[0])) / max(math.hypot(ex, ey), 1e-300) >= -1e-6
            mask |= inside
    if not mask.any():
        cx, cy = (a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0
        mask[math.floor(cy) % height, math.floor(cx) % width] = True
    return mask


def test_a_quad_selects_its_pixels_with_no_gap_along_the_shared_diagonal() -> None:
    mask, report = uv_faces_mask(8, 4, [_quad(0.0, 0.0, 0.5, 1.0)])
    expected = np.zeros((4, 8), dtype=np.uint8)
    expected[:, :4] = 255
    assert np.array_equal(mask, expected)
    assert report.faces == 2 and report.wrapped_faces == 0 and report.faces_under_a_pixel == 0


def test_v_zero_is_the_top_row_unless_the_material_flips_v() -> None:
    top, _ = uv_faces_mask(4, 8, [_quad(0.0, 0.0, 1.0, 0.25)])
    assert top[:2].all() and not top[2:].any()
    bottom, _ = uv_faces_mask(4, 8, [_quad(0.0, 0.0, 1.0, 0.25, flip_v=True)])
    assert bottom[6:].all() and not bottom[:6].any()


def test_a_pixel_centre_on_an_edge_counts() -> None:
    # The quad's right edge runs through the centres of column 2 (x = 2.5 pixels).
    mask, _ = uv_faces_mask(8, 2, [_quad(0.0, 0.0, 2.5 / 8, 1.0)])
    assert mask[:, :3].all() and not mask[:, 3:].any()


def test_uvs_outside_zero_to_one_wrap_as_the_3d_view_repeats_the_texture() -> None:
    plain, _ = uv_faces_mask(16, 16, [_quad(0.25, 0.25, 0.5, 0.75)])
    for du, dv in ((1.0, 0.0), (-2.0, 3.0), (5.0, -1.0)):
        shifted, report = uv_faces_mask(16, 16, [_quad(0.25 + du, 0.25 + dv, 0.5 + du, 0.75 + dv)])
        assert np.array_equal(shifted, plain), (du, dv)
        assert report.wrapped_faces == 2


def test_a_face_across_the_texture_edge_selects_both_sides() -> None:
    # U 0.85 to 1.15 is x 8.5 to 11.5: the centres of columns 8, 9, 10 and 11, wrapped.
    mask, _ = uv_faces_mask(10, 2, [_quad(0.85, 0.0, 1.15, 1.0)])
    assert mask[:, [8, 9, 0, 1]].all() and not mask[:, 2:8].any()


def test_a_mirrored_face_covers_the_same_pixels() -> None:
    uvs = ((0.1, 0.1), (0.9, 0.2), (0.4, 0.9))
    forward, _ = uv_faces_mask(32, 32, [UvPart(0, uvs, ((0, 1, 2),))])
    mirrored, _ = uv_faces_mask(32, 32, [UvPart(0, uvs, ((0, 2, 1),))])
    assert forward.any() and np.array_equal(forward, mirrored)


def test_overlapping_and_mirrored_uvs_list_every_face_on_the_pixel() -> None:
    # Faces 0 and 1 share the left half (a mirrored pair); face 2 is on its own.
    uvs = ((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0))
    part = UvPart(3, uvs, ((0, 1, 2), (2, 1, 0), (1, 4, 5)))
    assert uv_faces_covering(8, 8, [part], pixel=(3, 1)) == {3: [0, 1]}
    assert uv_faces_covering(8, 8, [part], pixel=(7, 1)) == {3: [2]}
    only_first, _ = uv_faces_mask(8, 8, [part], {3: [0]})
    assert uv_faces_covering(8, 8, [part], mask=only_first) == {3: [0, 1]}


def test_a_face_under_one_pixel_still_selects_the_pixel_under_its_centre() -> None:
    tiny = UvPart(0, ((0.51, 0.51), (0.52, 0.51), (0.51, 0.52)), ((0, 1, 2),))
    mask, report = uv_faces_mask(10, 10, [tiny])
    assert np.argwhere(mask).tolist() == [[5, 5]] and report.faces_under_a_pixel == 1
    flat = UvPart(0, ((0.05, 0.05), (0.95, 0.95), (0.5, 0.5)), ((0, 1, 2),))
    mask, report = uv_faces_mask(10, 10, [flat])
    assert np.argwhere(mask).tolist() == [[5, 5]] and report.faces_under_a_pixel == 1
    assert uv_faces_covering(10, 10, [flat], pixel=(5, 5)) == {0: [0]}


def test_broken_faces_are_counted_and_left_out() -> None:
    part = UvPart(0, ((0.0, 0.0), (1.0, 0.0), (float("nan"), 1.0), (0.0, 1.0)),
                  ((0, 1, 3), (0, 1, 2), (0, 1, 9)))
    mask, report = uv_faces_mask(4, 4, [part])
    assert report.faces == 1 and report.skipped_faces == 2 and mask.any()
    assert uv_faces_mask(4, 4, [UvPart(0, (), ((0, 1, 2),))])[1].skipped_faces == 1


def test_only_the_parts_and_faces_asked_for_count() -> None:
    parts = [_quad(0.0, 0.0, 0.5, 1.0, part=0), _quad(0.5, 0.0, 1.0, 1.0, part=4)]
    mask, report = uv_faces_mask(8, 4, parts, {4: None})
    assert mask[:, 4:].all() and not mask[:, :4].any() and report.faces_by_part == {4: 2}
    one, _ = uv_faces_mask(8, 4, parts, {0: [1], 9: None})
    assert one.any() and not one[:, 4:].any()


@pytest.mark.parametrize("size", [16, 300])
def test_matches_a_brute_force_pixel_test_for_small_large_and_tiled_faces(size) -> None:
    # 16 px keeps every face in the batched path; at 300 px most take the row-span path.
    rng = np.random.default_rng(7)
    uvs = rng.uniform(-1.5, 2.5, size=(36, 2))
    uvs[24:] = uvs[0] + rng.uniform(-0.03, 0.03, size=(12, 2))  # small faces too
    faces = [tuple(int(i) for i in rng.choice(36, 3, replace=False)) for _ in range(30)]
    faces += [(0, 24 + i, 25 + i) for i in range(10)]
    part = UvPart(0, uvs, faces)
    for face in range(len(faces)):
        mask, _ = uv_faces_mask(size, size, [part], {0: [face]})
        assert np.array_equal(mask > 0, _reference(size, size, part, face)), face


def test_a_pixel_lists_a_face_exactly_when_the_face_selects_that_pixel() -> None:
    rng = np.random.default_rng(3)
    uvs = rng.uniform(-0.5, 1.5, size=(20, 2))
    faces = [tuple(int(i) for i in rng.choice(20, 3, replace=False)) for _ in range(25)]
    part = UvPart(2, uvs, faces)
    size = 90
    masks = [uv_faces_mask(size, size, [part], {2: [face]})[0] > 0 for face in range(len(faces))]
    for x, y in rng.integers(0, size, size=(60, 2)):
        listed = uv_faces_covering(size, size, [part], pixel=(int(x), int(y))).get(2, [])
        assert listed == [face for face, mask in enumerate(masks) if mask[y, x]], (x, y)


def test_a_face_spanning_many_repeats_fills_the_texture() -> None:
    mask, report = uv_faces_mask(128, 64, [_quad(0.0, 0.0, 20.0, 20.0)])
    assert mask.all() and report.wrapped_faces == 2 and report.too_many_repeats == 0
    _, beyond = uv_faces_mask(8, 8, [_quad(0.0, 0.0, 100.0, 100.0)])
    assert beyond.too_many_repeats == 2


def test_a_whole_part_at_4096_is_quick() -> None:
    # About 32,000 faces in a grid over the texture: a whole dense part.
    n = 127
    grid = np.stack(np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n)), axis=-1).reshape(-1, 2)
    faces = []
    for row in range(n - 1):
        for column in range(n - 1):
            i = row * n + column
            faces += [(i, i + 1, i + n + 1), (i, i + n + 1, i + n)]
    started = time.perf_counter()
    mask, report = uv_faces_mask(4096, 4096, [UvPart(0, grid, faces)])
    elapsed = time.perf_counter() - started
    assert mask.all() and report.faces == len(faces)
    # About a second on the development machine; the bound catches a per-pixel Python
    # loop, not a slow run under load.
    assert elapsed < 60.0, elapsed


def test_a_neighbour_across_a_shared_edge_does_not_share_the_pixels() -> None:
    # A square quad at 8 x 8: its diagonal runs through pixel centres, which both
    # triangles cover, yet only a face with a pixel strictly inside is listed as sharing.
    quad = UvPart(0, ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)), ((0, 1, 2), (1, 3, 2)))
    first, _ = uv_faces_mask(8, 8, [quad], {0: [0]})
    assert uv_faces_covering(8, 8, [quad], mask=first) == {0: [0, 1]}
    assert uv_faces_covering(8, 8, [quad], mask=first, strict=True) == {0: [0]}
    mirrored = UvPart(0, quad.uvs, ((0, 1, 2), (1, 3, 2), (0, 2, 1)))
    assert uv_faces_covering(8, 8, [mirrored], mask=first, strict=True) == {0: [0, 2]}


def test_sharing_is_counted_before_grow_and_grow_widens_the_mask() -> None:
    from cdmw.services.mesh_texture_selection import TextureMeshSnapshot, build_texture_mesh_selection

    grid = UvPart(0, ((0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (0.0, 1.0), (0.5, 1.0), (1.0, 1.0)),
                  ((0, 1, 4), (0, 4, 3), (1, 2, 5), (1, 5, 4)))
    snapshot = TextureMeshSnapshot("t.dds", "base_color", 0, (grid,), {0: "Chest"}, {0: (0, 1)})
    plain = build_texture_mesh_selection(snapshot, 16, 8)
    grown = build_texture_mesh_selection(snapshot, 16, 8, grow=2)
    assert plain.shared == {} and grown.shared == {}
    assert plain.pixels == 8 * 8 and grown.pixels > plain.pixels and grown.mask[:, 9].all()
    assert not any("share these pixels" in note for note in grown.notes)


def test_the_mask_combines_with_the_selection_by_the_editor_mode() -> None:
    document = TextureEditorDocument("Probe", 8, 4, active_layer_id="paint",
                                     layers=(TextureEditorLayer("paint", "Paint", "unused.png"),))
    left, _ = uv_faces_mask(8, 4, [_quad(0.0, 0.0, 0.5, 1.0)])
    middle, _ = uv_faces_mask(8, 4, [_quad(0.25, 0.0, 0.75, 1.0)])

    def selected(doc):
        mask = build_texture_editor_selection_mask(8, 4, doc.selection)
        return np.zeros((4, 8), bool) if mask is None else mask > 0

    base = apply_texture_editor_mask_selection(document, left)
    assert np.array_equal(selected(base), left > 0)
    assert np.array_equal(selected(apply_texture_editor_mask_selection(base, middle, combine_mode="replace")), middle > 0)
    assert selected(apply_texture_editor_mask_selection(base, middle, combine_mode="add"))[:, :6].all()
    subtracted = selected(apply_texture_editor_mask_selection(base, middle, combine_mode="subtract"))
    assert subtracted[:, :2].all() and not subtracted[:, 2:].any()
    crossed = selected(apply_texture_editor_mask_selection(base, middle, combine_mode="intersect"))
    assert crossed[:, 2:4].all() and not crossed[:, :2].any() and not crossed[:, 4:].any()
    with pytest.raises(ValueError):
        apply_texture_editor_mask_selection(document, np.zeros((5, 8), np.uint8))
