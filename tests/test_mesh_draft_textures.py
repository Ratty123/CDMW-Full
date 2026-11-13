"""A draft keeps its texture projects, so texture work survives a restart (decision 48)."""
from __future__ import annotations

import json

import numpy as np

from cdmw.models import TextureEditorDocument, TextureEditorLayer
from cdmw.services.mesh_draft_textures import (
    DraftTexture,
    draft_texture_key,
    load_draft_textures,
    remove_draft_texture,
    save_draft_texture,
)


def _document():
    layers = (TextureEditorLayer("base", "Base", "base.png"), TextureEditorLayer("paint", "Paint", "paint.png", opacity=70))
    return TextureEditorDocument("Owned", 8, 4, active_layer_id="paint", layers=layers)


def _pixels():
    rng = np.random.default_rng(3)
    return {"base": rng.integers(0, 256, (4, 8, 4), dtype=np.uint8), "paint": rng.integers(0, 256, (4, 8, 4), dtype=np.uint8)}


TEXTURE = DraftTexture(resource_id="character/texture/own0.dds", channel="base", source_path="character/texture/own0.dds",
                       output_path="character/texture/thing_r0123456789abcdef.dds", parts=("part0",),
                       affected_submeshes=(0,), original_format="BC7_UNORM_SRGB",
                       sidecar_path="character/modelproperty/thing.pac_xml")


def test_a_saved_texture_comes_back_with_its_layers_and_where_it_goes(tmp_path):
    pixels = _pixels()
    save_draft_texture(tmp_path, TEXTURE, _document(), pixels)
    (loaded,) = load_draft_textures(tmp_path)
    assert loaded.problem == "" and loaded.texture == TEXTURE
    assert [layer.layer_id for layer in loaded.document.layers] == ["base", "paint"]
    assert loaded.document.layers[1].opacity == 70
    for layer_id, array in pixels.items():
        np.testing.assert_array_equal(loaded.layer_pixels[layer_id], array)


def test_saving_again_replaces_the_texture_and_keys_are_stable(tmp_path):
    save_draft_texture(tmp_path, TEXTURE, _document(), _pixels())
    changed = _pixels()
    changed["paint"][:] = 7
    save_draft_texture(tmp_path, TEXTURE, _document(), changed)
    (loaded,) = load_draft_textures(tmp_path)
    assert int(loaded.layer_pixels["paint"][0, 0, 0]) == 7
    assert draft_texture_key("Character/Texture/OWN0.dds", "BASE") == TEXTURE.key
    assert draft_texture_key("a.dds", "base") != draft_texture_key("a.dds", "normal")
    manifest = json.loads((tmp_path / "textures" / "manifest.json").read_text())
    assert list(manifest["textures"]) == [TEXTURE.key]


def test_an_unreadable_project_is_reported_and_the_rest_still_load(tmp_path):
    other = DraftTexture(resource_id="character/texture/own1.dds", channel="base", source_path="character/texture/own1.dds",
                         output_path="character/texture/own1.dds")
    save_draft_texture(tmp_path, TEXTURE, _document(), _pixels())
    project = save_draft_texture(tmp_path, other, _document(), _pixels())
    project.write_text("{ not json", encoding="utf-8")
    loaded = {item.texture.resource_id: item for item in load_draft_textures(tmp_path)}
    assert loaded["character/texture/own0.dds"].problem == ""
    broken = loaded["character/texture/own1.dds"]
    assert broken.document is None and "own1.dds" in broken.problem


def test_removing_a_texture_forgets_its_project(tmp_path):
    save_draft_texture(tmp_path, TEXTURE, _document(), _pixels())
    remove_draft_texture(tmp_path, TEXTURE.resource_id, TEXTURE.channel)
    assert load_draft_textures(tmp_path) == ()
    assert not (tmp_path / "textures" / TEXTURE.key).exists()
    assert load_draft_textures(tmp_path / "empty") == ()
