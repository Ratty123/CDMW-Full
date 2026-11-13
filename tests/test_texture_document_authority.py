"""One document per edited texture; the mesh session's store is derived from it (decision 48).

Includes the review's M2 to M5 (REPORT-review.md): token-held documents, loose key
matching, measured dirty regions, and staleness after a mesh Undo or a second writer.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cdmw.models import TextureEditorDocument, TextureEditorLayer
from cdmw.services.texture_document_authority import (
    TextureDocumentAuthority,
    TextureDocumentKey,
    TextureDocumentOpenElsewhere,
    TextureDocumentStale,
    flattened_bgra,
)
from tests.test_mesh_editor_replacement import editor  # noqa: F401  (fixture)


def _document(width=16, height=8):
    return TextureEditorDocument("Owned", width, height, active_layer_id="paint",
                                 layers=(TextureEditorLayer("paint", "Paint", "unused.png"),))


def _pixels(value, width=16, height=8):
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[..., 0], pixels[..., 1], pixels[..., 2], pixels[..., 3] = value, 20, 30, 255
    return pixels


def _resource(service, session_id, resource_id, channel="base"):
    return service._session(session_id).committed_texture_resources[(resource_id, channel)]


def _store_bytes(service, session_id, resource_id, channel="base") -> bytes:
    return Path(_resource(service, session_id, resource_id, channel).raw_bgra_path).read_bytes()


class _Recorder:
    """The real service, recording the regions written."""

    def __init__(self, service):
        self.service, self.regions = service, []

    def __getattr__(self, name):
        return getattr(self.service, name)

    def commit_texture_region(self, *args, rect, **kwargs):
        self.regions.append(tuple(rect))
        return self.service.commit_texture_region(*args, rect=rect, **kwargs)


def test_a_document_is_held_by_its_token_not_its_owners_name(editor):  # noqa: F811
    service, session_id = editor
    authority = TextureDocumentAuthority(service)
    key = TextureDocumentKey.of(session_id, "character/texture/own0.dds")
    entry = authority.open(key, _document(), {"paint": _pixels(10)}, owner="Texture Editor")
    # A second Texture Editor document on the same texture has the same label, not the token (M3).
    with pytest.raises(TextureDocumentOpenElsewhere) as elsewhere:
        authority.open(key, _document(), {"paint": _pixels(99)}, owner="Texture Editor")
    assert elsewhere.value.owner == "Texture Editor"
    with pytest.raises(TextureDocumentOpenElsewhere):
        authority.commit(key, _document(), {"paint": _pixels(99)}, token="not the token")
    assert authority.open(key, _document(), {}, owner="Texture Editor", token=entry.token) is entry
    with pytest.raises(TextureDocumentOpenElsewhere):
        authority.close(key, token="not the token")
    authority.close(key, token=entry.token)
    assert authority.get(key) is None


def test_keys_match_in_any_spelling_and_the_store_keeps_the_sessions(editor):  # noqa: F811
    service, session_id = editor
    authority = TextureDocumentAuthority(service)
    key = TextureDocumentKey.of(session_id, "Character/Texture/Own0.dds", "BASE")
    entry = authority.open(key, _document(), {"paint": _pixels(10)}, owner="Mesh Editor")
    other = TextureDocumentKey.of(session_id, "character\\texture\\own0.dds", "base")
    assert other == key and authority.get(other) is entry
    with pytest.raises(TextureDocumentOpenElsewhere):
        authority.open(other, _document(), {}, owner="Texture Editor")
    authority.commit(key, _document(), {"paint": _pixels(10)}, token=entry.token)
    # The store has the session's own spelling, not a casefolded copy (M4).
    resources = service._session(session_id).committed_texture_resources
    assert ("Character/Texture/Own0.dds", "base") in resources


def test_the_mesh_store_is_the_documents_flattened_pixels_and_only_changes_are_written(editor):  # noqa: F811
    service, session_id = editor
    recorder = _Recorder(service)
    authority = TextureDocumentAuthority(recorder)
    key = TextureDocumentKey.of(session_id, "character/texture/own0.dds")
    document = _document()
    entry = authority.open(key, document, {"paint": _pixels(10)}, owner="Mesh Editor", affected_submeshes=(0,))
    first = authority.commit(key, document, {"paint": _pixels(10)}, token=entry.token)
    assert _store_bytes(service, session_id, key.resource_id) == flattened_bgra(document, {"paint": _pixels(10)}).tobytes()

    stroke = _pixels(10)
    stroke[2:5, 3:9, 0] = 200
    stroke[7, 15, 0] = 1  # outside the rectangle the caller names, as symmetry or a fill would be (M5)
    second = authority.commit(key, document, {"paint": stroke}, token=entry.token, rect=(3, 2, 6, 3))
    assert second == first + 1
    assert recorder.regions == [(3, 2, 13, 6)]
    assert _store_bytes(service, session_id, key.resource_id) == flattened_bgra(document, {"paint": stroke}).tobytes()
    # Nothing changed: nothing written, the revision stays.
    assert authority.commit(key, document, {"paint": stroke}, token=entry.token) == second
    assert recorder.regions == [(3, 2, 13, 6)]


def test_a_second_writer_or_a_mesh_undo_makes_the_document_stale_until_it_reloads(editor):  # noqa: F811
    service, session_id = editor
    authority = TextureDocumentAuthority(service)
    key = TextureDocumentKey.of(session_id, "character/texture/own1.dds")
    document = _document()
    entry = authority.open(key, document, {"paint": _pixels(1)}, owner="Mesh Editor")
    authority.commit(key, document, {"paint": _pixels(1)}, token=entry.token)
    # Something else writes the store: a mesh Undo restoring an earlier copy, or a second writer (M2).
    undone = bytes(_pixels(7)[..., [2, 1, 0, 3]].tobytes())
    service.commit_texture_snapshot(session_id, key.resource_id, channel=key.channel, width=16, height=8,
                                    row_pitch=64, bgra=undone)
    for whole in (False, True):  # partial and whole writes are both refused
        pixels = _pixels(2) if whole else _pixels(1)
        if not whole:
            pixels[0, 0, 0] = 9
        with pytest.raises(TextureDocumentStale):
            authority.commit(key, document if not whole else _document(32, 16),
                             {"paint": pixels if not whole else _pixels(2, 32, 16)}, token=entry.token)
    assert _store_bytes(service, session_id, key.resource_id) == undone
    reloaded = authority.reload_from_store(key, token=entry.token)
    assert reloaded.tobytes() == undone
    rgba = np.ascontiguousarray(reloaded[..., [2, 1, 0, 3]])
    authority.adopt(key, document, {"paint": rgba}, token=entry.token)
    changed = rgba.copy()
    changed[1, 1, 0] = 250
    authority.commit(key, document, {"paint": changed}, token=entry.token)
    assert _store_bytes(service, session_id, key.resource_id) == flattened_bgra(document, {"paint": changed}).tobytes()


def test_a_resized_document_is_written_whole_and_a_closed_session_forgets_its_documents(editor):  # noqa: F811
    service, session_id = editor
    authority = TextureDocumentAuthority(service)
    key = TextureDocumentKey.of(session_id, "character/texture/own0.dds")
    entry = authority.open(key, _document(), {"paint": _pixels(5)}, owner="Mesh Editor")
    authority.commit(key, _document(), {"paint": _pixels(5)}, token=entry.token)
    bigger = _document(32, 16)
    authority.commit(key, bigger, {"paint": _pixels(6, 32, 16)}, token=entry.token, rect=(0, 0, 2, 2))
    assert _store_bytes(service, session_id, key.resource_id) == flattened_bgra(bigger, {"paint": _pixels(6, 32, 16)}).tobytes()
    authority.close_session(session_id)
    assert authority.get(key) is None
