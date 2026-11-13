"""Review of refs/heads/rr/parity-p6-python (the first side thread; P6, decision 48).

The real services with owned data under tmp_path. Strict xfails: they fail on the
reviewed code; remove the marker with the fix. Skipped where the branch is not merged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("cdmw.services.mesh_draft_textures")

_PRECISION = ("Review of rr/parity-p6-python (REPORT-review.md): float, BC6H and SNORM originals pass the "
              "output-matching refusal but cannot survive the 8-bit document")
_ORDER = ("Review of rr/parity-p6-python (REPORT-review.md): a draft texture save replaces the project before "
          "it checks the manifest")


@pytest.mark.parametrize("fmt", ["BC5_SNORM", "BC4_SNORM", "BC6H_UF16", "R16G16B16A16_FLOAT", "R32_FLOAT"])
def test_an_original_the_document_cannot_hold_is_refused(fmt) -> None:
    """The edited texture is an RGBA8 document. original_texture_output accepts every name in
    WRITABLE_DDS_FORMATS, so a float or BC6H original loses its range above 1.0 and its
    precision, and an SNORM normal map loses its negative half (the 8-bit PNG goes through
    the encoder as [0, 1]). parse_dds marks these precision_sensitive; nothing reads it."""

    from cdmw.domain.textures.original_output import TextureOutputRefused, original_texture_output
    from cdmw.models import DdsInfo

    info = DdsInfo(width=256, height=256, mip_count=9, dds_format=fmt, source_path=Path("owned.dds"))
    with pytest.raises(TextureOutputRefused):
        original_texture_output(info)


def test_a_save_into_a_draft_a_newer_build_wrote_changes_nothing(tmp_path) -> None:
    """save_draft_texture writes the project first and reads the manifest after. With a
    manifest from a newer CDMW it raises "saved by a newer CDMW", but the newer build's
    project for that texture has already been replaced."""

    import json

    import numpy as np

    from cdmw.models import TextureEditorDocument, TextureEditorLayer
    from cdmw.services import mesh_draft_textures as textures

    texture = textures.DraftTexture(
        resource_id="character/texture/own0.dds", channel="base", source_path="character/texture/own0.dds",
        output_path="character/texture/own0.dds", parts=("part0",), affected_submeshes=(0,),
        original_format="BC7_UNORM_SRGB", sidecar_path="character/modelproperty/thing.pac_xml",
        # The model's own texture, written in place: since 3a2abb2a4 that has to be said.
        in_place=True)
    project = textures._project_path(tmp_path, texture.key)
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_bytes(b"a newer build's texture project")
    (project.parent.parent / textures.MANIFEST_NAME).write_text(
        json.dumps({"version": textures.MANIFEST_VERSION + 1, "textures": {texture.key: {}}}), encoding="utf-8")
    document = TextureEditorDocument("Owned", 8, 4, active_layer_id="base",
                                     layers=(TextureEditorLayer("base", "Base", "base.png"),))
    with pytest.raises(ValueError):
        textures.save_draft_texture(tmp_path, texture, document, {"base": np.zeros((4, 8, 4), dtype=np.uint8)})
    assert project.read_bytes() == b"a newer build's texture project", "the newer build's project was replaced"


_TAKEN = ("Review of rr/parity-p6-python (REPORT-review.md): Make unique misses a taken name written in "
          "another case or with backslashes")


@pytest.mark.parametrize("spelling", ["upper", "backslashes"])
def test_make_unique_refuses_a_taken_name_in_any_spelling(spelling) -> None:
    """make_texture_unique normalises its candidate but compares it with existing_paths as
    given. A mod folder listed with Windows separators, or in another case, holds the name
    and is not seen: the copy would be written over another file."""

    from cdmw.services.model_textures import make_texture_unique, unique_texture_path
    from tests.test_model_textures import SHARED, SIDECAR

    taken = unique_texture_path(SHARED, "thing")
    listed = taken.upper() if spelling == "upper" else taken.replace("/", "\\")
    with pytest.raises(ValueError, match="already exists"):
        make_texture_unique(SHARED, sidecar_path="x.pac_xml", sidecar_data=SIDECAR.encode(), parts=["part0"],
                            stem="thing", existing_paths={listed})
