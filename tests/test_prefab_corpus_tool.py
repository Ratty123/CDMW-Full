from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import tools.report_prefab_json_import_corpus as corpus_tool


def _lp(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(4, "little") + encoded


def test_prefab_corpus_tool_write_report_preserves_existing_file_when_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "report.json"
    output.write_text('{"old": true}', encoding="utf-8")

    def fail_validation(_path: Path) -> None:
        raise ValueError("bad generated report")

    monkeypatch.setattr(corpus_tool, "_validate_written_report", fail_validation)

    with pytest.raises(ValueError, match="bad generated report"):
        corpus_tool._write_report(output, {"new": True})

    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}
    assert not output.with_name("report.json.tmp").exists()


def test_prefab_corpus_tool_writes_loose_no_edit_report(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac"))
    output = tmp_path / "report.json"

    result = subprocess.run(
        [
            sys.executable,
            "tools/report_prefab_json_import_corpus.py",
            "--out-json",
            str(output),
            "--no-edit-probes",
            str(source),
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert b"\x00" not in output.read_bytes()
    assert report["summary"]["files_scanned"] == 1
    assert report["summary"]["edit_probes_enabled"] is False
    assert report["summary"]["no_edit_roundtrip_failed"] == 0
    assert report["gate"]["json_layout_no_edit_rebuild_ready"] is True
    status = json.loads(result.stdout)
    assert status["summary"]["files_scanned"] == 1
    assert status["summary"]["experimental_length_change_resource_rebuild_probe_status_effective_expected_counts"] == {
        "skipped|false": 1
    }
    assert status["summary"]["experimental_length_change_placement_rebuild_probe_status_effective_expected_counts"] == {
        "skipped|false": 1
    }
    assert status["gate"]["resource_resize_offset_gate_ready"] is False
    assert status["gate"]["placement_resize_offset_gate_ready"] is False
    assert status["gate"]["resize_offset_validator_ready"] is False
    assert status["gate"]["resource_effective_resize_offset_model_ready"] is False
    assert status["gate"]["placement_effective_resize_offset_model_ready"] is False
    assert status["gate"]["effective_resize_offset_model_ready"] is False
    assert status["gate"]["length_changing_failed_subgates"] == [
        "same_length_import_ready",
        "resize_offset_validator_ready",
        "descriptor_value_editing_ready",
        "transform_value_editing_ready",
        "array_resizing_ready",
        "unknown_reference_preservation_ready",
    ]
    assert status["gate"]["descriptor_count_semantics_proven"] is False
    assert status["gate"]["array_count_hint_semantics_proven"] is False
    assert status["gate"]["descriptor_word3_semantics_proven"] is False
    assert status["gate"]["descriptor_count_mutation_proven"] is False
    assert status["gate"]["transform_payload_layout_proven"] is False
    assert status["gate"]["transform_value_semantics_proven"] is False
    assert status["gate"]["transform_value_mutation_proven"] is False
    assert status["gate"]["array_payload_layout_proven"] is False
    assert status["gate"]["array_count_mutation_proven"] is False
    assert status["gate"]["unknown_block_edit_semantics_proven"] is False
    assert status["gate"]["reference_descriptor_edit_semantics_proven"] is False
    assert status["gate"]["unknown_reference_preservation_ready"] is False
    detail_counts = status["gate"]["length_changing_blocker_detail_counts"]
    assert detail_counts["resource_length_probe_edit_probes_disabled_skipped_rows"] == 1
    assert detail_counts["placement_length_probe_edit_probes_disabled_skipped_rows"] == 1
    assert detail_counts["resource_length_probe_no_safe_candidate_skipped_rows"] == 0
    assert detail_counts["placement_length_probe_no_safe_candidate_skipped_rows"] == 0
    assert detail_counts["resource_length_probe_overlap_ambiguous_skipped_rows"] == 0


def test_prefab_corpus_tool_scans_loose_shard(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac"))
    (source / "b.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp("character/model/test_b.pac"))
    output = tmp_path / "report.json"

    subprocess.run(
        [
            sys.executable,
            "tools/report_prefab_json_import_corpus.py",
            "--out-json",
            str(output),
            "--no-edit-probes",
            "--scan-offset",
            "1",
            "--scan-count",
            "1",
            str(source),
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["files_discovered"] == 2
    assert report["summary"]["files_scanned"] == 1
    assert report["summary"]["scan_offset"] == 1
    assert report["summary"]["scan_count"] == 1
    assert [row["path"] for row in report["rows"]] == ["b.prefab"]


def test_prefab_corpus_tool_exits_nonzero_for_empty_report(tmp_path: Path) -> None:
    source = tmp_path / "empty"
    source.mkdir()
    output = tmp_path / "report.json"

    result = subprocess.run(
        [
            sys.executable,
            "tools/report_prefab_json_import_corpus.py",
            "--out-json",
            str(output),
            "--no-edit-probes",
            str(source),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["files_scanned"] == 0


def test_prefab_corpus_tool_merges_complete_shards(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac"))
    (source / "b.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp("character/model/test_b.pac"))
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    merged_path = tmp_path / "merged.json"
    root = Path(__file__).resolve().parents[1]

    for offset, output in [(0, first), (1, second)]:
        subprocess.run(
            [
                sys.executable,
                "tools/report_prefab_json_import_corpus.py",
                "--out-json",
                str(output),
                "--no-edit-probes",
                "--scan-offset",
                str(offset),
                "--scan-count",
                "1",
                str(source),
            ],
            check=True,
            cwd=root,
            text=True,
            capture_output=True,
        )

    result = subprocess.run(
        [
            sys.executable,
            "tools/report_prefab_json_import_corpus.py",
            "--out-json",
            str(merged_path),
            "--merge-reports",
            str(first),
            str(second),
        ],
        check=True,
        cwd=root,
        text=True,
        capture_output=True,
    )

    report = json.loads(merged_path.read_text(encoding="utf-8"))
    assert report["summary"]["coverage_complete"] is True
    assert report["gate"]["full_corpus_no_edit_rebuild_ready"] is True
    status = json.loads(result.stdout)
    assert status["summary"]["coverage_complete"] is True


def test_prefab_corpus_tool_expands_merge_report_globs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    reports_dir = tmp_path / "reports"
    source.mkdir()
    reports_dir.mkdir()
    (source / "a.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac"))
    (source / "b.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp("character/model/test_b.pac"))
    root = Path(__file__).resolve().parents[1]

    for offset in (0, 1):
        subprocess.run(
            [
                sys.executable,
                "tools/report_prefab_json_import_corpus.py",
                "--out-json",
                str(reports_dir / f"shard-{offset}.json"),
                "--no-edit-probes",
                "--scan-offset",
                str(offset),
                "--scan-count",
                "1",
                str(source),
            ],
            check=True,
            cwd=root,
            text=True,
            capture_output=True,
        )

    merged_path = tmp_path / "merged.json"
    result = subprocess.run(
        [
            sys.executable,
            "tools/report_prefab_json_import_corpus.py",
            "--out-json",
            str(merged_path),
            "--merge-reports",
            str(reports_dir / "shard-*.json"),
        ],
        check=True,
        cwd=root,
        text=True,
        capture_output=True,
    )

    report = json.loads(merged_path.read_text(encoding="utf-8"))
    assert report["summary"]["merged_report_count"] == 2
    assert report["summary"]["coverage_complete"] is True
    assert json.loads(result.stdout)["gate"]["full_corpus_no_edit_rebuild_ready"] is True


def test_prefab_corpus_tool_writes_shard_batch_and_merged_report(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shard_dir = tmp_path / "shards"
    merged_path = tmp_path / "merged.json"
    source.mkdir()
    (source / "a.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac"))
    (source / "b.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp("character/model/test_b.pac"))

    result = subprocess.run(
        [
            sys.executable,
            "tools/report_prefab_json_import_corpus.py",
            "--out-json",
            str(merged_path),
            "--shard-dir",
            str(shard_dir),
            "--shard-size",
            "1",
            "--no-edit-probes",
            str(source),
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    shard_paths = sorted(path.name for path in shard_dir.glob("*.json"))
    report = json.loads(merged_path.read_text(encoding="utf-8"))
    assert shard_paths == ["prefab-corpus-shard-000000-000001.json", "prefab-corpus-shard-000001-000001.json"]
    assert report["summary"]["merged_report_count"] == 2
    assert report["summary"]["coverage_complete"] is True
    assert report["gate"]["full_corpus_no_edit_rebuild_ready"] is True
    assert json.loads(result.stdout)["summary"]["files_scanned"] == 2


def test_prefab_corpus_tool_can_resume_limited_shard_batches(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shard_dir = tmp_path / "shards"
    merged_path = tmp_path / "merged.json"
    source.mkdir()
    for name in ("a", "b", "c"):
        (source / f"{name}.prefab").write_bytes(b"\xff\xff\x04\x00" + _lp(f"character/model/test_{name}.pac"))
    root = Path(__file__).resolve().parents[1]

    first = subprocess.run(
        [
            sys.executable,
            "tools/report_prefab_json_import_corpus.py",
            "--out-json",
            str(merged_path),
            "--shard-dir",
            str(shard_dir),
            "--shard-size",
            "1",
            "--max-shards",
            "1",
            "--no-edit-probes",
            str(source),
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )

    assert first.returncode == 1
    assert sorted(path.name for path in shard_dir.glob("*.json")) == ["prefab-corpus-shard-000000-000001.json"]

    second = subprocess.run(
        [
            sys.executable,
            "tools/report_prefab_json_import_corpus.py",
            "--out-json",
            str(merged_path),
            "--shard-dir",
            str(shard_dir),
            "--shard-size",
            "1",
            "--max-shards",
            "1",
            "--resume-shards",
            "--no-edit-probes",
            str(source),
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )

    report = json.loads(merged_path.read_text(encoding="utf-8"))
    assert second.returncode == 1
    assert sorted(path.name for path in shard_dir.glob("*.json")) == [
        "prefab-corpus-shard-000000-000001.json",
        "prefab-corpus-shard-000001-000001.json",
    ]
    assert report["summary"]["files_scanned"] == 2
    assert report["summary"]["coverage_complete"] is False
