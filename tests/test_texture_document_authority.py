"""One document per edited texture; the mesh session's store is derived from it (decision 48)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cdmw.models import TextureEditorDocument, TextureEditorLayer
from cdmw.services.texture_document_authority import (
    TextureDocumentAuthority,
    TextureDocumentKey,
    TextureDocumentOpenElsewhere,
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


def _store_bytes(service, session_id, key) -> bytes:
    resource = service._session(session_id).committed_texture_resources[(key.resource_id, key.channel)]
    return Path(resource.raw_bgra_path).read_bytes()


def test_a_second_widget_gets_the_open_document_not_a_copy(editor):  # noqa: F811
    service, session_id = editor
    authority = TextureDocumentAuthority(service)
    key = TextureDocumentKey.of(session_id, "Character/Texture/Own0.dds", "BASE")
    entry = authority.open(key, _document(), {"paint": _pixels(10)}, owner="Mesh Editor")
    assert authority.open(TextureDocumentKey.of(session_id, "character/texture/own0.dds"), _document(), {},
                          owner="Mesh Editor") is entry
    with pytest.raises(TextureDocumentOpenElsewhere) as elsewhere:
        authority.open(key, _document(), {"paint": _pixels(99)}, owner="Texture Editor")
    assert elsewhere.value.owner == "Mesh Editor" and "Mesh Editor" in str(elsewhere.value)
    with pytest.raises(TextureDocumentOpenElsewhere):
        authority.commit(key, _document(), {"paint": _pixels(99)}, owner="Texture Editor")


def test_the_mesh_store_is_the_documents_flattened_pixels(editor):  # noqa: F811
    service, session_id = editor
    authority = TextureDocumentAuthority(service)
    key = TextureDocumentKey.of(session_id, "character/texture/own0.dds")
    document = _document()
    authority.open(key, document, {"paint": _pixels(10)}, owner="Mesh Editor", affected_submeshes=(0,))
    first = authority.commit(key, document, {"paint": _pixels(10)}, owner="Mesh Editor")
    assert _store_bytes(service, session_id, key) == flattened_bgra(document, {"paint": _pixels(10)}).tobytes()
    assert (key.resource_id, key.channel) in {(r.resource_id, r.channel)
                                              for r in service.capture_export_snapshot(session_id).texture_resources}

    stroke = _pixels(10)
    stroke[2:5, 3:9, 0] = 200  # a stroke inside (3, 2, 6, 3)
    second = authority.commit(key, document, {"paint": stroke}, owner="Mesh Editor", rect=(3, 2, 6, 3))
    assert second == first + 1
    assert _store_bytes(service, session_id, key) == flattened_bgra(document, {"paint": stroke}).tobytes()
    assert authority.get(key).revision == 2 and authority.get(key).mesh_revision == second


def test_nothing_else_may_write_the_store_behind_the_document(editor):  # noqa: F811
    service, session_id = editor
    authority = TextureDocumentAuthority(service)
    key = TextureDocumentKey.of(session_id, "character/texture/own1.dds")
    document = _document()
    authority.open(key, document, {"paint": _pixels(1)}, owner="Mesh Editor")
    authority.commit(key, document, {"paint": _pixels(1)}, owner="Mesh Editor")
    # A second writer (the old direct patch path) changes the store under the document.
    service.commit_texture_snapshot(session_id, key.resource_id, channel=key.channel, width=16, height=8,
                                    row_pitch=64, bgra=bytes(16 * 8 * 4))
    with pytest.raises(RuntimeError, match="stale"):
        authority.commit(key, document, {"paint": _pixels(2)}, owner="Mesh Editor", rect=(0, 0, 4, 4))


def test_a_resized_document_is_written_whole_and_a_closed_session_forgets_its_documents(editor):  # noqa: F811
    service, session_id = editor
    authority = TextureDocumentAuthority(service)
    key = TextureDocumentKey.of(session_id, "character/texture/own0.dds")
    authority.open(key, _document(), {"paint": _pixels(5)}, owner="Mesh Editor")
    authority.commit(key, _document(), {"paint": _pixels(5)}, owner="Mesh Editor")
    bigger = _document(32, 16)
    authority.commit(key, bigger, {"paint": _pixels(6, 32, 16)}, owner="Mesh Editor", rect=(0, 0, 2, 2))
    assert _store_bytes(service, session_id, key) == flattened_bgra(bigger, {"paint": _pixels(6, 32, 16)}).tobytes()
    authority.close_session(session_id)
    assert authority.get(key) is None
