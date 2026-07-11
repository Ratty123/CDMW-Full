from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from unittest import mock

import cdmw.core.external_model_audit as external_model_audit
from cdmw.core.external_model_audit import build_external_model_audit_catalogue
from cdmw.core.external_model_audit_resume import external_model_source_fingerprint
from tools.audit_external_model_catalogue import main


def test_zip_fingerprint_includes_parent_crc_and_expanded_size(tmp_path: Path) -> None:
    archive = tmp_path / "model.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("scene/model.gltf", b"{}")

    fingerprint = external_model_source_fingerprint(archive)

    member = fingerprint["zip_members"][0]
    assert member["member_path"] == "scene/model.gltf"
    assert member["expanded_size"] == 2
    assert isinstance(member["crc"], int)
    assert member["parent_fingerprint"] == {
        "normalized_path": fingerprint["normalized_path"],
        "size": fingerprint["size"],
        "mtime_ns": fingerprint["mtime_ns"],
    }


def test_zip_model_members_are_completely_classified_without_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "models.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("scene/a.gltf", b"{}")
        handle.writestr("scene/b.gltf", b"{}")
        handle.writestr("scene/readme.txt", b"notes")

    report = build_external_model_audit_catalogue([tmp_path])

    row = report["models"][0]
    members = row["zip_member_rows"]
    assert [member["member_path"] for member in members] == ["scene/a.gltf", "scene/b.gltf"]
    assert {member["classification"] for member in members} == {"review_required"}
    assert report["zip_member_progress"]["discovered"] == 2
    assert report["zip_member_progress"]["accounted"] == 2
    assert report["zip_member_progress"]["complete"] is True
    assert report["corpus_ok"] is True


def test_safely_blocked_asset_is_accounted_without_becoming_corpus_crash(tmp_path: Path) -> None:
    (tmp_path / "broken.gltf").write_text("{}", encoding="utf-8")
    with mock.patch(
        "cdmw.core.external_model_audit._audit_external_model_file",
        return_value={"audit_status": "failed", "warnings": ("parse failed safely",)},
    ):
        report = build_external_model_audit_catalogue([tmp_path])

    assert report["classification_counts"] == {"safely_blocked": 1}
    assert report["read_parse_error_count"] == 1
    assert report["read_parse_crash_count"] == 0
    assert report["unclassified_count"] == 0
    assert report["corpus_ok"] is True


def test_matching_resume_reuses_row_and_changed_stamp_reaudits(tmp_path: Path) -> None:
    source = tmp_path / "model.fbx"
    source.write_bytes(b"fbx")
    first = build_external_model_audit_catalogue([tmp_path])

    with mock.patch(
        "cdmw.core.external_model_audit._audit_external_model_file",
        side_effect=AssertionError("matching row must be reused"),
    ):
        resumed = build_external_model_audit_catalogue([tmp_path], resume_report=first)

    assert resumed["progress"]["complete"] is True
    assert resumed["progress"]["audited_this_run"] == 0
    assert resumed["models"][0]["resume_reused"] is True

    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    with mock.patch(
        "cdmw.core.external_model_audit._audit_external_model_file",
        wraps=external_model_audit._audit_external_model_file,
    ) as audit:
        changed = build_external_model_audit_catalogue([tmp_path], resume_report=resumed)

    assert audit.call_count == 1
    assert changed["progress"]["audited_this_run"] == 1


def test_chunks_accumulate_to_complete_report(tmp_path: Path) -> None:
    (tmp_path / "a.fbx").write_bytes(b"a")
    (tmp_path / "b.fbx").write_bytes(b"b")

    first = build_external_model_audit_catalogue([tmp_path], chunk_size=1, chunk_index=0)
    second = build_external_model_audit_catalogue(
        [tmp_path],
        chunk_size=1,
        chunk_index=1,
        resume_report=first,
    )

    assert first["progress"]["accounted"] == 1
    assert first["progress"]["pending"] == 1
    assert second["progress"]["complete"] is True
    assert second["progress"]["accounted"] == 2
    assert second["progress"]["audited_this_run"] == 1
    assert second["progress"]["reused"] == 1


def test_cli_uses_environment_root_and_resumes_output(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "model.fbx").write_bytes(b"fbx")
    output = tmp_path / "audit.json"
    monkeypatch.setenv("CDMW_MODEL_CATALOGUE_ROOT", str(tmp_path))

    assert main(["--out-json", str(output), "--chunk-size", "1"]) == 0
    assert main(["--out-json", str(output), "--resume", "--chunk-size", "1"]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == 2
    assert report["roots"] == [str(tmp_path.resolve())]
    assert report["progress"]["complete"] is True
    assert report["progress"]["reused"] == 1
    assert not tuple(tmp_path.glob(".*.tmp"))
