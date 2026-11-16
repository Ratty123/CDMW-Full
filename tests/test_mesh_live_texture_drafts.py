"""Step 8 item 3: texture edits made live are kept in the draft and read back after a restart."""

from __future__ import annotations

import numpy as np
import pytest

from cdmw.services.mesh_draft_textures import load_draft_textures
from cdmw.services.mesh_live_texture_drafts import (
    LiveDraftEdit,
    forget_live_edits,
    restore_live_edits,
    save_live_edits,
)

KEY = "a" * 64
OTHER = "b" * 64
GAME = "character/texture/cd_phm_00_ub_00_0374_n.dds"


def _pixels(seed: int, size: tuple[int, int] = (16, 8)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(size[1], size[0], 4), dtype=np.uint8)


def test_an_edit_is_kept_in_the_draft_and_comes_back_exactly(tmp_path):
    draft = tmp_path / "draft"
    edited = _pixels(1)
    assert save_live_edits(draft, [LiveDraftEdit(KEY, "normal", GAME, edited, original_format="BC5_UNORM")]) == (KEY,)
    assert (draft / "textures" / "manifest.json").is_file()
    (restored,) = restore_live_edits(draft)
    assert (restored.live_key, restored.role, restored.game_path, restored.problem) == (KEY, "normal", GAME, "")
    assert np.array_equal(restored.rgba, edited)
    # Saved again with a newer edit: the newer one is what comes back.
    newer = _pixels(2)
    save_live_edits(draft, [LiveDraftEdit(KEY, "normal", GAME, newer)])
    assert np.array_equal(restore_live_edits(draft)[0].rgba, newer)
    # The row says it is written at its own game path, which is what the live Build Mod does.
    (row,) = load_draft_textures(draft)
    assert row.texture.in_place and row.texture.output_path == GAME


def test_an_edit_undone_to_the_original_is_forgotten_and_others_stay(tmp_path):
    draft = tmp_path / "draft"
    save_live_edits(draft, [LiveDraftEdit(KEY, "normal", GAME, _pixels(1)),
                            LiveDraftEdit(OTHER, "base", "character/texture/other_d.dds", _pixels(3))])
    forget_live_edits(draft, [(KEY, "normal")])
    assert [edit.live_key for edit in restore_live_edits(draft)] == [OTHER]


def test_a_damaged_kept_edit_says_so_and_the_others_still_come_back(tmp_path):
    draft = tmp_path / "draft"
    save_live_edits(draft, [LiveDraftEdit(KEY, "normal", GAME, _pixels(1)),
                            LiveDraftEdit(OTHER, "base", "character/texture/other_d.dds", _pixels(3))])
    for project in (draft / "textures").rglob("*.json"):
        if project.name != "manifest.json" and "aaaa" in project.parent.name:
            project.write_text("{not json", encoding="utf-8")
    restored = {edit.live_key: edit for edit in restore_live_edits(draft)}
    assert restored[OTHER].rgba is not None and restored[OTHER].problem == ""
    assert restored[KEY].rgba is None and GAME in restored[KEY].problem


def test_an_image_that_is_not_rgba_is_refused_with_its_game_path(tmp_path):
    with pytest.raises(OSError, match=GAME):
        save_live_edits(tmp_path / "draft", [LiveDraftEdit(KEY, "normal", GAME, np.zeros((4, 4), np.uint8))])
    assert restore_live_edits(tmp_path / "draft") == ()
