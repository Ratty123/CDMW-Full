from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from cdmw.models import ArchiveEntry
from tools.audit_pac_xml_material_authority import (
    audit_pac_xml_material_authority_corpus,
    main,
)


_VALID_XML = (
    '<Root><SkinnedMeshMaterialWrapper _subMeshName="Body">'
    '<MaterialParameterTexture _name="_overlayColorTexture" />'
    "</SkinnedMeshMaterialWrapper></Root>"
)


def test_loose_corpus_chunks_resume_to_complete_accounting(tmp_path: Path) -> None:
    (tmp_path / "a.pac_xml").write_text(_VALID_XML, encoding="utf-8")
    (tmp_path / "b.pac_xml").write_text(_VALID_XML, encoding="utf-8")

    first = audit_pac_xml_material_authority_corpus(
        [tmp_path],
        include_archives=False,
        chunk_size=1,
        chunk_index=0,
    )
    second = audit_pac_xml_material_authority_corpus(
        [tmp_path],
        include_archives=False,
        chunk_size=1,
        chunk_index=1,
        resume_summary=first,
    )

    assert first["progress"]["complete"] is False
    assert first["ok"] is False
    assert second["progress"] == {
        "discovered": 2,
        "accounted": 2,
        "pending": 0,
        "complete": True,
        "chunk_index": 1,
        "chunk_size": 1,
        "audited_this_run": 1,
        "reused": 1,
    }
    assert second["classification_counts"] == {"supported": 2}
    assert second["ok"] is True


def test_archive_entry_uses_identity_and_preserves_pamt_paz_hashes(tmp_path: Path) -> None:
    package = tmp_path / "0009"
    package.mkdir()
    pamt = package / "0.pamt"
    paz = package / "0.paz"
    unrelated = package / "99.paz"
    pamt.write_bytes(b"index")
    paz.write_bytes(b"payload")
    unrelated.write_bytes(b"not a PAC_XML source")
    entry = ArchiveEntry(
        path="character/material/body.pac_xml",
        pamt_path=pamt,
        paz_file=paz,
        offset=4,
        comp_size=7,
        orig_size=len(_VALID_XML),
        flags=0,
        paz_index=0,
    )
    before = {pamt: pamt.read_bytes(), paz: paz.read_bytes()}

    with mock.patch(
        "tools.audit_pac_xml_material_authority.parse_archive_pamt",
        return_value=[entry],
    ), mock.patch(
        "tools.audit_pac_xml_material_authority.read_archive_entry_data",
        return_value=(_VALID_XML.encode("utf-8"), False, ""),
    ):
        summary = audit_pac_xml_material_authority_corpus([tmp_path])

    report = summary["reports"][0]
    assert report["source_file"] == "character/material/body.pac_xml"
    assert report["source_provenance"]["identity"] == entry.identity._asdict()
    assert report["classification"] == "supported"
    assert summary["source_archives_unchanged"] is True
    assert summary["archive_fingerprints_before"] == summary["archive_fingerprints_after"]
    assert str(unrelated.resolve()).casefold() not in {
        str(row["path"]).casefold() for row in summary["archive_fingerprints_before"]
    }
    assert summary["ok"] is True
    assert {path: path.read_bytes() for path in before} == before


def test_archive_mutation_fails_read_only_gate(tmp_path: Path) -> None:
    package = tmp_path / "0009"
    package.mkdir()
    pamt = package / "0.pamt"
    paz = package / "0.paz"
    pamt.write_bytes(b"index")
    paz.write_bytes(b"payload")
    entry = ArchiveEntry(
        path="body.pac_xml",
        pamt_path=pamt,
        paz_file=paz,
        offset=0,
        comp_size=7,
        orig_size=len(_VALID_XML),
        flags=0,
        paz_index=0,
    )

    def mutate_source(_entry: ArchiveEntry):
        paz.write_bytes(b"changed")
        return _VALID_XML.encode("utf-8"), False, ""

    with mock.patch(
        "tools.audit_pac_xml_material_authority.parse_archive_pamt",
        return_value=[entry],
    ), mock.patch(
        "tools.audit_pac_xml_material_authority.read_archive_entry_data",
        side_effect=mutate_source,
    ):
        summary = audit_pac_xml_material_authority_corpus([tmp_path])

    assert summary["source_archives_unchanged"] is False
    assert summary["ok"] is False


def test_malformed_source_is_classified_without_crashing(tmp_path: Path) -> None:
    (tmp_path / "broken.pac_xml").write_text("<broken>", encoding="utf-8")

    summary = audit_pac_xml_material_authority_corpus([tmp_path], include_archives=False)

    assert summary["progress"]["complete"] is True
    assert summary["classification_counts"] == {"safely_blocked": 1}
    assert summary["read_parse_error_count"] == 1
    assert summary["read_parse_crash_count"] == 0
    assert summary["unclassified_count"] == 0
    assert summary["ok"] is True


def test_cli_resume_publishes_complete_json_and_csv(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.pac_xml").write_text(_VALID_XML, encoding="utf-8")
    (corpus / "b.pac_xml").write_text(_VALID_XML, encoding="utf-8")
    output_json = tmp_path / "audit.json"
    output_csv = tmp_path / "audit.csv"
    common = [
        "--roots",
        str(corpus),
        "--out-json",
        str(output_json),
        "--out-csv",
        str(output_csv),
        "--loose-only",
        "--chunk-size",
        "1",
    ]

    assert main([*common, "--chunk-index", "0"]) == 1
    assert main([*common, "--chunk-index", "1", "--resume"]) == 0

    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["progress"]["complete"] is True
    assert report["progress"]["reused"] == 1
    assert output_csv.is_file()
    assert not tuple(tmp_path.glob(".*.tmp"))
