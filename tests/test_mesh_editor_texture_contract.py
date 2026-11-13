"""The P6 contract file names only Python that exists, and matches the region queue's wire shape."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[1] / "cdmw" / "resources" / "mesh_editor_texture_contract.json"

NAMES = {
    "cdmw.services.model_textures": ("model_texture_list", "texture_sharing", "make_texture_unique", "TEXTURE_GROUPS"),
    "cdmw.domain.textures.original_output": ("check_texture_editable", "original_texture_output", "TextureOutputRefused"),
    "cdmw.services.texture_document_authority": ("TextureDocumentAuthority", "TextureDocumentKey", "TextureDocumentOpenElsewhere"),
    "cdmw.services.mesh_draft_textures": ("save_draft_texture", "load_draft_textures", "DraftTexture", "LoadedDraftTexture"),
    "cdmw.services.texture_editor_service": ("TextureEditorNativeDdsService",),
    "cdmw.domain.textures.editor_brush": ("apply_texture_editor_stroke",),
}


def test_the_contract_is_json_with_every_section():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["protocol"] == "cdmw_rust_mesh_editor_protocol_v1"
    assert {row["event"] for row in contract["helper_to_host"]} >= {"paint_stroke"}
    assert [row["event"] for row in contract["host_to_helper"]] == ["texture_region_update"]
    assert len(contract["tab_hooks"]) >= 9 and contract["refusal_codes"]


def test_every_python_name_it_calls_exists():
    text = CONTRACT.read_text(encoding="utf-8")
    for module_name, names in NAMES.items():
        module = importlib.import_module(module_name)
        for name in names:
            assert name in text, name
            assert hasattr(module, name), f"{module_name}.{name}"
    assert hasattr(importlib.import_module("cdmw.services.texture_editor_service").TextureEditorNativeDdsService,
                   "export_matching_original")
    from cdmw.services.model_textures import TEXTURE_GROUPS

    assert all(group in text for group in TEXTURE_GROUPS)


def test_the_region_update_is_the_queues_own_shape():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    shape = contract["host_to_helper"][0]["shape"]
    source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "mesh_editor" / "resident_texture_update_queue.py").read_text(encoding="utf-8")
    assert "cdmw_resident_texture_region_update_v1" in shape and '"cdmw_resident_texture_region_update_v1"' in source
    for field in ("edit_revision", "texture_revision", "generation", "affected_submeshes", "texture_width",
                  "texture_height", "pixel_format", "row_pitch", "delete_after"):
        assert field in shape and f'"{field}"' in source, field
