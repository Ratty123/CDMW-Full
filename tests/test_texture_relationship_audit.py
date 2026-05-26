from __future__ import annotations

import json
from pathlib import Path

from tools.audit_texture_relationships import main


def _minimal_dxt1_dds(width: int = 4, height: int = 4) -> bytes:
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = int(height).to_bytes(4, "little")
    header[12:16] = int(width).to_bytes(4, "little")
    header[16:20] = (8).to_bytes(4, "little")
    header[24:28] = (1).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = b"DXT1"
    return b"DDS " + bytes(header) + (b"\x00" * 8)


def _write(path: Path, payload: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload, encoding="utf-8")


def test_texture_relationship_audit_reports_pairs_refs_formats_and_family_companions(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    game_root = tmp_path / "game"
    family_root = tmp_path / "family"
    json_out = tmp_path / "out" / "audit.json"
    md_out = tmp_path / "out" / "audit.md"
    game_root.mkdir()

    _write(archive_root / "character/model/body.pac", b"PAC")
    _write(
        archive_root / "character/modelproperty/body.pac_xml",
        """
        <MaterialParameterTexture _name="_baseColorTexture">
          <ResourceReferencePath_ITexture Name="_value" _path="character/texture/body_d.dds"/>
        </MaterialParameterTexture>
        <ResourceReferencePath_ITexture value="shared.dds"/>
        <ResourceReferencePath_ITexture value="character/texture/missing.dds"/>
        <ResourceReferencePath_ITexture value="bad path.dds"/>
        <ResourceReferencePath_ITexture value=""/>
        """,
    )
    _write(archive_root / "character/modelproperty/orphan.pac_xml", "<Material />")
    _write(archive_root / "character/texture/body_d.dds", _minimal_dxt1_dds())
    _write(archive_root / "character/texture/body_n.dds", _minimal_dxt1_dds())
    _write(archive_root / "character/texture/a/shared.dds", _minimal_dxt1_dds())
    _write(archive_root / "character/texture/b/shared.dds", _minimal_dxt1_dds())

    _write(family_root / "character/model/family_body.pac", b"PAC")
    _write(family_root / "character/bin__/meshphysics/family_body.hkx", b"HKX")
    _write(family_root / "character/skeleton/family_body.pab", b"PAB")
    _write(family_root / "character/bin__/prefab/family_body_l.prefab", b"SceneObject")

    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    exit_code = main(
        [
            "--archive-root",
            str(archive_root),
            "--game-root",
            str(game_root),
            "--family-root",
            str(family_root),
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ]
    )

    assert exit_code == 0
    report = json.loads(json_out.read_text(encoding="utf-8"))
    counts = report["counts"]
    assert counts["dds_files"] == 4
    assert counts["pac_files"] == 2
    assert counts["pac_xml_files"] == 2
    assert counts["pac_with_pac_xml"] == 1
    assert counts["pac_without_pac_xml"] == 1
    assert counts["pac_xml_without_pac"] == 1
    assert counts["sidecar_dds_refs_total"] == 3
    assert counts["sidecar_dds_refs_resolved"] == 1
    assert counts["sidecar_dds_refs_missing"] == 1
    assert counts["sidecar_dds_refs_ambiguous_basename"] == 1
    assert counts["malformed_refs"] == 2
    assert counts["ambiguous_dds_basenames"] == 1
    assert counts["family_hkx_companions"] == 1
    assert counts["family_pab_companions"] == 1
    assert counts["family_prefab_companions"] == 1
    assert counts["tex_files"] == 0

    assert report["dds_suffixes"]["_d"]["formats"]["BC1_UNORM"] == 1
    assert report["dds_suffixes"]["_n"]["formats"]["BC1_UNORM"] == 1
    assert report["dds_formats"]["BC1_UNORM"] == 4
    assert report["pac_pac_xml_pairs"][0]["status"] == "exact"
    assert report["orphan_pac_xml"][0]["path"] == "character/modelproperty/orphan.pac_xml"
    assert report["ambiguous_basenames"][0]["basename"] == "shared.dds"
    assert {row["status"] for row in report["sidecar_dds_refs"]} == {
        "resolved_exact",
        "ambiguous_basename",
        "missing",
    }
    family = report["family_companions"][0]
    assert family["hkx"][0]["path"] == "character/bin__/meshphysics/family_body.hkx"
    assert family["pab"][0]["path"] == "character/skeleton/family_body.pab"
    assert family["prefab"][0]["path"] == "character/bin__/prefab/family_body_l.prefab"
    assert report["family_examples"][0]["dds"] == 0
    assert report["family_examples"][0]["pab"] == 1
    risky = report["top_risky_parameter_patterns"]
    assert risky
    assert risky[0]["risk_refs"] >= 1
    assert any(row["parameter_name"] in {"_baseColorTexture", "(unknown)"} for row in risky)
    assert "Texture Relationship Audit" in md_out.read_text(encoding="utf-8")
    assert "Top Risky Parameter Patterns" in md_out.read_text(encoding="utf-8")

    after = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    for rel_path, payload in before.items():
        assert after[rel_path] == payload
