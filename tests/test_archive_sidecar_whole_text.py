"""A material sidecar is parsed whole, not cut at the text preview limit.

`cd_m0001_00_so_phm_ub_33012.pac_xml` is 508,914 bytes with four material sets.
Cut at the 240,000 byte preview limit it lost the textures of its later sets,
and a preview built from that list failed with `source_dds_unavailable`.
"""
from pathlib import Path

from cdmw.constants import ARCHIVE_TEXT_PREVIEW_LIMIT
from cdmw.core import archive_model_references
from cdmw.domain.archives.format import try_decode_text_like_archive_data
from cdmw.models import ArchiveEntry


def _wrapper(name: str, texture: str) -> str:
    return (
        f'<SkinnedMeshMaterialWrapper ItemID="1" _subMeshName="{name}">\n'
        '<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2">\n'
        '<MaterialParameterTexture StringItemID="_grimeDiffuseTextureG" _name="_grimeDiffuseTextureG" Index="1">\n'
        f'<ResourceReferencePath_ITexture Name="_value" _path="{texture}"/>\n'
        "</MaterialParameterTexture>\n</Material>\n</SkinnedMeshMaterialWrapper>\n"
    )


def _long_sidecar() -> bytes:
    early = _wrapper("early", "character/texture/early_layer.dds")
    filler = "<!-- padding -->\n" * (ARCHIVE_TEXT_PREVIEW_LIMIT // 17 + 64)
    late = _wrapper("late", "character/texture/cd_texturelayer_002_0023.dds")
    text = f"<SkinnedMeshPropertyCommon>\n{early}{filler}{late}</SkinnedMeshPropertyCommon>\n"
    assert text.index("cd_texturelayer_002_0023") > ARCHIVE_TEXT_PREVIEW_LIMIT
    return text.encode("utf-8")


def test_the_preview_decode_is_cut_and_the_whole_decode_is_not():
    data = _long_sidecar()
    preview = try_decode_text_like_archive_data(data)
    assert preview is not None and len(preview) == ARCHIVE_TEXT_PREVIEW_LIMIT
    assert "cd_texturelayer_002_0023" not in preview
    whole = try_decode_text_like_archive_data(data, limit=None)
    assert whole is not None and len(whole) == len(data)
    assert "cd_texturelayer_002_0023" in whole


def test_a_model_sidecar_keeps_the_textures_past_the_preview_limit(tmp_path: Path, monkeypatch):
    data = _long_sidecar()
    entry = ArchiveEntry(
        path="character/modelproperty/long_armour.pac_xml",
        pamt_path=tmp_path / "0.pamt",
        paz_file=tmp_path / "0.paz",
        offset=0,
        comp_size=len(data),
        orig_size=len(data),
        flags=0,
        paz_index=0,
    )
    monkeypatch.setattr(
        archive_model_references, "read_archive_entry_data",
        lambda _entry, stop_event=None: (data, False, ""),
    )
    with archive_model_references._MODEL_SIDECAR_PARSE_CACHE_LOCK:
        archive_model_references._MODEL_SIDECAR_PARSE_CACHE.clear()
    bindings, *_ = archive_model_references._extract_model_sidecar_entry_bindings_cached(entry)
    textures = {binding.texture_path.replace("\\", "/").lower() for binding in bindings}
    assert "character/texture/early_layer.dds" in textures
    assert "character/texture/cd_texturelayer_002_0023.dds" in textures
