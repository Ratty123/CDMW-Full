"""Material sidecars are read whole; only text previews stop at the preview limit."""
from cdmw.constants import ARCHIVE_TEXT_PREVIEW_LIMIT
from cdmw.domain.archives.format import try_decode_text_like_archive_data


def _large_sidecar() -> bytes:
    row = '\t<MaterialParameterTexture StringItemID="_detailHeightMaskB" Index="33"/>\r\n'
    rows = row * (ARCHIVE_TEXT_PREVIEW_LIMIT // len(row) + 50)
    return ("﻿<ModelPropertyList>\r\n" + rows + "</ModelPropertyList>\r\n").encode("utf-8")


def test_preview_stops_at_the_limit_and_content_reads_keep_everything():
    data = _large_sidecar()
    assert len(data) > ARCHIVE_TEXT_PREVIEW_LIMIT
    assert not try_decode_text_like_archive_data(data).endswith("</ModelPropertyList>\r\n")
    assert try_decode_text_like_archive_data(data, limit=None) == data.decode("utf-8-sig")


def test_builder_reads_a_large_template_sidecar_whole(monkeypatch):
    """A template material file over 240 KB, such as the upperbody of Demian's
    Leather Armor (455 KB), was cut mid-tag. An import over it then wrote a
    malformed material file, and Create New Item's Build plan was refused with
    "Physics XML cannot be edited without preserving its structure"."""
    import cdmw.core.archive_extraction as extraction
    import cdmw.core.archive_model_references as references
    from cdmw.core.archive_mesh_import_supplemental import _collect_original_mesh_sidecar_texts

    data = _large_sidecar()
    sidecar = object()
    monkeypatch.setattr(references, "_find_archive_model_sidecar_entries", lambda _entry, _index: (sidecar,))
    monkeypatch.setattr(extraction, "read_archive_entry_data", lambda _entry, stop_event=None: (data, False, ""))

    ((entry, text),) = _collect_original_mesh_sidecar_texts(object(), {})
    assert entry is sidecar
    assert text == data.decode("utf-8-sig")


def test_replacement_and_sidecar_editor_readers_keep_large_sidecars_whole():
    """Import Replacement and the material sidecar editor parse the sidecar they read; both
    used the preview decoder and lost every material past 240 KB."""
    from cdmw.services.mesh_replacement_materials import _sidecar_text
    from cdmw.ui.archive_browser.material_sidecar_actions import ArchiveMaterialSidecarActionsMixin

    data = _large_sidecar()
    assert _sidecar_text(data) == data.decode("utf-8-sig")
    assert ArchiveMaterialSidecarActionsMixin._decode_material_sidecar_bytes(data) == data.decode("utf-8-sig")
