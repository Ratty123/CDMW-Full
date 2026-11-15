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
                         output_path="character/texture/own1.dds", in_place=True)
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


def test_a_save_into_a_draft_a_newer_build_wrote_changes_nothing(tmp_path):
    """M6: the manifest is read before the project is written."""
    import pytest

    from cdmw.services import mesh_draft_textures as textures

    project = textures._project_path(tmp_path, TEXTURE.key)
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_bytes(b"a newer build's texture project")
    (project.parent.parent / textures.MANIFEST_NAME).write_text(
        json.dumps({"version": textures.MANIFEST_VERSION + 1, "textures": {TEXTURE.key: {}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="newer"):
        save_draft_texture(tmp_path, TEXTURE, _document(), _pixels())
    assert project.read_bytes() == b"a newer build's texture project"


def test_two_saves_at_once_keep_both_textures(tmp_path):
    """M7: the manifest's read-modify-write is serialised per draft."""
    import threading

    others = [DraftTexture(resource_id=f"character/texture/own{i}.dds", channel="base",
                           source_path=f"character/texture/own{i}.dds", output_path=f"character/texture/own{i}.dds", in_place=True)
              for i in range(6)]
    threads = [threading.Thread(target=save_draft_texture, args=(tmp_path, texture, _document(), _pixels()))
               for texture in others]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert {item.texture.resource_id for item in load_draft_textures(tmp_path)} == {t.resource_id for t in others}


def test_a_changed_game_copy_is_said_plainly_and_identity_survives_a_restart(tmp_path):
    """M8: the source's hash and size are kept, so a game update is named, not a size error."""
    import hashlib
    from dataclasses import replace

    from cdmw.services.mesh_draft_textures import source_changed

    original = b"DDS original bytes"
    texture = replace(TEXTURE, source_sha256=hashlib.sha256(original).hexdigest(), source_width=8, source_height=4,
                      finish_generation=3)
    save_draft_texture(tmp_path, texture, _document(), _pixels())
    (loaded,) = load_draft_textures(tmp_path)
    assert loaded.texture == texture
    assert source_changed(loaded.texture, original, width=8, height=4) == ""
    assert "changed since this edit was saved" in source_changed(loaded.texture, b"patched", width=8, height=4)
    assert "is now 16x8" in source_changed(loaded.texture, b"patched", width=16, height=8)


def test_a_bad_manifest_row_costs_only_that_texture(tmp_path):
    save_draft_texture(tmp_path, TEXTURE, _document(), _pixels())
    manifest_path = tmp_path / "textures" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["textures"]["broken"] = {"resource_id": "x.dds", "affected_submeshes": ["not a number"]}
    manifest_path.write_text(json.dumps(manifest))
    loaded = {item.texture.resource_id: item for item in load_draft_textures(tmp_path)}
    assert loaded[TEXTURE.resource_id].problem == "" and loaded["broken"].problem


# ----- review follow-ups before the merge -------------------------------------------------
def _sharing(in_place, needs_unique=False):
    from cdmw.services.model_textures import TextureSharing

    return TextureSharing(path="character/texture/own0.dds", other_parts=(), shared_name=False, other_files=None,
                          needs_unique=needs_unique, reason="", in_place=in_place)


def test_an_edit_at_the_source_path_needs_the_in_place_decision(tmp_path):
    """Sharing that is not known yet (needs_unique False, in_place False) cannot write in place."""
    import pytest

    from cdmw.services.mesh_draft_textures import draft_texture_write_path

    same = dict(resource_id="character/texture/own0.dds", channel="base", source_path="character/texture/own0.dds",
                output_path="Character\\Texture\\OWN0.dds")
    with pytest.raises(ValueError, match="Make it unique first"):
        DraftTexture.for_sharing(_sharing(in_place=False), **same)
    with pytest.raises(ValueError, match="Make it unique first"):
        DraftTexture(**same)
    allowed = DraftTexture.for_sharing(_sharing(in_place=True), **same)
    save_draft_texture(tmp_path, allowed, _document(), _pixels())
    (loaded,) = load_draft_textures(tmp_path)
    assert loaded.texture.in_place and draft_texture_write_path(loaded.texture) == same["output_path"]
    # A unique copy needs no decision; Build writes it at its own path.
    assert draft_texture_write_path(TEXTURE) == TEXTURE.output_path


def test_a_saved_in_place_row_without_the_decision_is_that_textures_problem_only(tmp_path):
    """A manifest edited by hand (or by an older build) cannot turn into an in-place write at Build."""
    from dataclasses import replace

    import pytest

    from cdmw.services.mesh_draft_textures import draft_texture_write_path

    own = DraftTexture(resource_id="character/texture/own1.dds", channel="base", source_path="character/texture/own1.dds",
                       output_path="character/texture/own1.dds", in_place=True)
    save_draft_texture(tmp_path, TEXTURE, _document(), _pixels())
    save_draft_texture(tmp_path, own, _document(), _pixels())
    manifest_path = tmp_path / "textures" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["textures"][own.key]["in_place"] = False
    manifest_path.write_text(json.dumps(manifest))
    loaded = {item.texture.resource_id: item for item in load_draft_textures(tmp_path)}
    assert loaded["character/texture/own0.dds"].problem == ""
    # Not lost: the edit is kept and the sharing decision is asked again (review of
    # rr/parity-p6-python). Until it is, the texture has no output to write to.
    row = loaded[own.resource_id]
    assert row.needs_sharing and row.document is not None and "asks again" in row.problem
    assert row.texture.output_path == "" and not row.texture.in_place
    with pytest.raises(ValueError, match="no output path"):
        draft_texture_write_path(row.texture)
    with pytest.raises(ValueError, match="Make it unique first"):
        replace(own, in_place=False)


def test_a_leading_dot_slash_names_the_same_path():
    from cdmw.services.mesh_draft_textures import _same_path

    assert _same_path("./character/texture/own0.dds", "character/texture/own0.dds")
    assert _same_path(".\\Character\\Texture\\OWN0.dds", "/character/texture/own0.dds")
    assert not _same_path("./character/texture/own1.dds", "character/texture/own0.dds")


def test_a_crash_between_the_two_moves_restores_the_previous_save(tmp_path):
    """save_texture_editor_project: the project is copied to its .backup, the assets folder moved
    to its .backup, then the new assets moved in; a crash there leaves the old JSON with new assets."""
    import os
    import shutil

    from cdmw.core.texture_editor_project_io import _texture_editor_assets_dir

    first = _pixels()
    project = save_draft_texture(tmp_path, TEXTURE, _document(), first)
    second = _pixels()
    second["paint"][:] = 9
    second_root = tmp_path / "second"
    newer = save_draft_texture(second_root, TEXTURE, _document(), second)
    assets = _texture_editor_assets_dir(project)
    transaction = "0" * 32
    shutil.copy2(project, project.parent / f".{project.name}.{transaction}.backup")
    os.replace(assets, project.parent / f".{assets.name}.{transaction}.backup")
    shutil.copytree(_texture_editor_assets_dir(newer), assets)
    # The new assets hold other file names than the old JSON expects.
    for child in assets.iterdir():
        child.rename(child.with_name("new-" + child.name))
    (loaded,) = load_draft_textures(tmp_path)
    assert loaded.document is not None and "previous save was restored" in loaded.problem
    np.testing.assert_array_equal(loaded.layer_pixels["paint"], first["paint"])
    assert not list(project.parent.glob(f".{project.name}.*")) and not list(project.parent.glob(f".{assets.name}.*"))
    (again,) = load_draft_textures(tmp_path)
    assert again.problem == ""


def test_half_a_backup_is_not_restored_and_the_project_stays_as_found(tmp_path):
    project = save_draft_texture(tmp_path, TEXTURE, _document(), _pixels())
    (project.parent / f".{project.name}.{'1' * 32}.backup").write_text("{}", encoding="utf-8")
    project.write_text("{ not json", encoding="utf-8")
    (loaded,) = load_draft_textures(tmp_path)
    assert loaded.document is None and "could not be read" in loaded.problem
    assert project.read_text(encoding="utf-8") == "{ not json"