"""Owned fixtures verify the research review tool, not actual game behavior."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from cdmw.core.archive_format import calculate_pa_checksum
from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, serialize_papgt
from scripts import review_cditem_native_path as review

PID = 1234
ROOT = r"D:\owned\private-root"
ARCHIVE = ROOT + r"\0000\0.paz"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": digest(raw)}


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path / "private-root"
    mount, index, archive = (root / name for name in ("meta/0.papgt", "0000/0.pamt", "0000/0.paz"))
    resource, payload = "cditem/probe/owned.bin", b"owned private resource bytes"
    built = build_overlay_archive((OverlayFile(resource, payload, len(payload), 0),))
    mount.parent.mkdir(parents=True)
    index.parent.mkdir(parents=True)
    mount.write_bytes(serialize_papgt((PapgtDirectory("0000", PAPGT_DEFAULT_FLAGS, built.pamt_checksum),)))
    index.write_bytes(built.pamt_bytes)
    archive.write_bytes(built.paz_bytes)
    manifest = {
        "root": str(root), "resource_path": resource, "payload_bytes": len(payload),
        "payload_sha256": digest(payload), "groups": 1, "pamt_entries": 1,
        "entry_offset": 0, "entry_stored_bytes": len(payload), "native_admission": False,
        "files": [pin(path) for path in (mount, index, archive)],
    }
    path, native = tmp_path / "prepared.json", tmp_path / "resource_input.hpp"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    native.write_text('#pragma once\n#include "protocol.hpp"\n#include <span>\n'
                      'inline constexpr char root[]=R"(' + str(root) + ')";\n'
                      'inline constexpr wchar_t papgt[]=LR"(' + str(mount) + ')";\n'
                      'inline constexpr char resource_path[]="' + resource + '";\n', encoding="utf-8")
    return {"path": path, "native": native, "manifest": manifest,
            "mount": mount, "index": index, "archive": archive, "root": root}


def inspect(fixture, prepared_sha=None, native_sha=None):
    return review.inspect_preparation(
        fixture["path"], prepared_sha or pin(fixture["path"])["sha256"],
        fixture["native"], native_sha or pin(fixture["native"])["sha256"])


def rewrite_manifest(fixture):
    fixture["path"].write_text(json.dumps(fixture["manifest"]), encoding="utf-8")


def repin_files(fixture):
    fixture["manifest"]["files"] = [pin(fixture[key]) for key in ("mount", "index", "archive")]
    rewrite_manifest(fixture)


def change_index(fixture, offset=None, flags=None):
    raw = bytearray(fixture["index"].read_bytes())
    if offset is not None:
        struct.pack_into("<I", raw, len(raw) - 16, offset)
    if flags is not None:
        struct.pack_into("<H", raw, len(raw) - 2, flags)
    checksum = calculate_pa_checksum(bytes(raw[12:]))
    struct.pack_into("<I", raw, 0, checksum)
    fixture["index"].write_bytes(raw)
    fixture["mount"].write_bytes(
        serialize_papgt((PapgtDirectory("0000", PAPGT_DEFAULT_FLAGS, checksum),)))
    repin_files(fixture)


def example(path=ARCHIVE):
    base = 0x140000000
    before = dict.fromkeys(review.FIELDS, 0)
    before.update(state=3, status=1, thread=987, module_base=base,
                  private_index=base + 0x7000, file_record=base + 0xD000,
                  output_slot=base + 0xE000, flags=1, last_error_before=123,
                  provider=base + 0x3000, vector_before=base + 0x4000,
                  count_before=1, capacity_before=1, item_owner=base + 0x5000,
                  item_count_before=6816, query_flags=0x70003, qpc_before=1200)
    final = dict(before)
    final.update(state=1, output_handle=base + 0xF000, characters=base + 0x10000,
                 returned_slot=before["output_slot"], flags=31, last_error_after=2,
                 vector_after=before["vector_before"], count_after=1, capacity_after=1,
                 provider_same=1, item_same=1, item_count_after=6816,
                 qpc_after=1300, path_length=len(path.encode("ascii")))
    query = dict(final, lookup_flags=0x70003, lookup_record=final["file_record"],
                 lookup_expected_record=final["file_record"], qpc_after=1200)
    metadata = {"private_index_lookup_passed": True, "issues": [], "native_admission": False,
                "frames": [{"state": 3}, {"state": 4}, query]}
    return before, final, metadata


def packet(before, final, path=ARCHIVE, pid=PID):
    def frame(row, text):
        return struct.pack("<32Q", *(row[name] for name in review.FIELDS)) + text.ljust(512, b"\0")
    return (struct.pack("<5I", 0x50494443, 1, pid, 32, 512) + frame(before, b"")
            + frame(final, path.encode("ascii") + b"\0"))


def check(before, final, metadata, path=ARCHIVE, **kwargs):
    return review.review_path_wire(packet(before, final, path, **kwargs), PID, metadata, ROOT, ARCHIVE)


def test_prepared_fixture_binds_archive_and_payload_without_native_claims(prepared):
    before = {str(p): p.read_bytes() for p in prepared["path"].parent.rglob("*") if p.is_file()}
    result = inspect(prepared)
    assert result["private_archive_inputs_consistent"] is True
    assert result["archive"] == pin(prepared["archive"])
    assert result["payload"]["sha256"] == prepared["manifest"]["payload_sha256"]
    assert all(result[key] is False for key in review._scope())
    assert before == {str(p): p.read_bytes() for p in prepared["path"].parent.rglob("*") if p.is_file()}


@pytest.mark.parametrize("key", ["mount", "index", "archive", "native"])
def test_changed_pinned_input_refuses(prepared, key):
    prepared_sha, native_sha = pin(prepared["path"])["sha256"], pin(prepared["native"])["sha256"]
    prepared[key].write_bytes(prepared[key].read_bytes() + b"x")
    with pytest.raises(ValueError, match="Pinned input"):
        inspect(prepared, prepared_sha, native_sha)


def test_rewritten_manifest_cannot_replace_independent_pin(prepared):
    original = pin(prepared["path"])["sha256"]
    prepared["manifest"]["payload_sha256"] = "0" * 64
    rewrite_manifest(prepared)
    with pytest.raises(ValueError, match="digest"):
        inspect(prepared, original)


def test_different_native_root_refuses_even_with_new_source_pin(prepared):
    prepared["native"].write_text(prepared["native"].read_text().replace("private-root", "sibling-root"))
    with pytest.raises(ValueError, match="exact prepared root"):
        inspect(prepared)


@pytest.mark.parametrize("wrapper", ["line-comment", "block-comment", "conditional", "second-declaration", "raw-string"])
def test_inactive_or_additional_native_declarations_refuse(prepared, wrapper):
    original = prepared["native"].read_text()
    different = ('inline constexpr char root[] = R"(D:\\other-root)";\n'
                 'inline constexpr char resource_path[] = "other/resource.bin";\n')
    if wrapper == "line-comment":
        changed = "\n".join("// " + line for line in original.splitlines()) + "\n" + different
    elif wrapper == "block-comment":
        changed = "/*\n" + original + "*/\n" + different
    elif wrapper == "conditional":
        changed = "#if 0\n" + original + "#endif\n" + different
    elif wrapper == "raw-string":
        changed = 'const char* text=R"unrelated(\n' + original + ')unrelated";\n'
    else:
        changed = original + different
    prepared["native"].write_text(changed)
    with pytest.raises(ValueError):
        inspect(prepared)


@pytest.mark.parametrize("field,value", [
    ("groups", 2), ("groups", True), ("pamt_entries", 2), ("payload_bytes", 0),
    ("entry_offset", 1), ("entry_stored_bytes", 1), ("resource_path", "../owned.bin"),
    ("payload_sha256", "f" * 64),
])
def test_preparation_shape_or_payload_identity_refuses(prepared, field, value):
    prepared["manifest"][field] = value
    rewrite_manifest(prepared)
    with pytest.raises(ValueError):
        inspect(prepared)


def test_rehashed_wrong_archive_bytes_still_refuse_payload_identity(prepared):
    raw = bytearray(prepared["archive"].read_bytes())
    raw[0] ^= 1
    prepared["archive"].write_bytes(raw)
    repin_files(prepared)
    with pytest.raises(ValueError, match="payload differs"):
        inspect(prepared)


def test_declared_sibling_archive_refuses_even_with_matching_hash(prepared):
    sibling = prepared["archive"].with_name("1.paz")
    sibling.write_bytes(prepared["archive"].read_bytes())
    prepared["manifest"]["files"][-1] = pin(sibling)
    rewrite_manifest(prepared)
    with pytest.raises(ValueError, match="exact declared archive"):
        inspect(prepared)


@pytest.mark.parametrize("kind", ["unsupported-storage", "out-of-range"])
def test_parsed_entry_refuses_unproven_representation_and_outside_slice(prepared, kind):
    if kind == "unsupported-storage":
        change_index(prepared, flags=1)
    else:
        offset = prepared["archive"].stat().st_size - 1
        prepared["manifest"]["entry_offset"] = offset
        change_index(prepared, offset=offset)
    with pytest.raises(ValueError, match="representation|outside"):
        inspect(prepared)


def test_mount_checksum_chain_mismatch_refuses(prepared):
    prepared["mount"].write_bytes(serialize_papgt((PapgtDirectory("0000", PAPGT_DEFAULT_FLAGS, 123),)))
    repin_files(prepared)
    with pytest.raises(ValueError, match="checksum"):
        inspect(prepared)


@pytest.mark.parametrize("path", [ARCHIVE, ARCHIVE.replace("\\", "/")])
def test_exact_packet_and_separator_equivalence_remain_offline_consistency(path):
    before, final, metadata = example(path)
    result = check(before, final, metadata, path)
    assert result["path_packet_consistent"] is True
    assert result["observed_path"] == path
    assert all(result[key] is False for key in review._scope())
    assert "provenance" in result["scope"]
    json.dumps(result)


@pytest.mark.parametrize("path", [
    ROOT + r"\0000\1.paz", ROOT + r"\0001\0.paz", ROOT + r"X\0000\0.paz",
    ROOT + r"\..\0000\0.paz", ROOT + r"\.\0000\0.paz", ROOT + r"\\0000\0.paz",
    ROOT + r"\0000\0.paz:stream", ARCHIVE.lower(), r"E:\owned\private-root\0000\0.paz",
])
def test_other_archive_or_path_alias_cannot_pass_root_membership(path):
    before, final, metadata = example(path)
    with pytest.raises(ValueError):
        check(before, final, metadata, path)


@pytest.mark.parametrize("field,value", [
    ("thread", 988), ("module_base", 0x180000000), ("private_index", 0x150000000),
    ("file_record", 0x150001000), ("returned_slot", 0x150002000), ("flags", 15),
    ("selected_group", 1), ("paz_ordinal", 1), ("count_after", 2), ("item_same", 0),
    ("qpc_before", 1199), ("query_flags", 0x30003),
])
def test_changed_packet_or_parent_identity_refuses(field, value):
    before, final, metadata = example()
    final[field] = value
    with pytest.raises(ValueError):
        check(before, final, metadata)


def test_wrong_pid_truncation_tail_and_fabricated_before_output_refuse():
    before, final, metadata = example()
    raw = packet(before, final)
    tail = bytearray(raw)
    tail[-1] = 1
    for candidate in (packet(before, final, pid=PID + 1), raw[:-1], raw[:20 + 768], bytes(tail)):
        with pytest.raises(ValueError):
            review.review_path_wire(candidate, PID, metadata, ROOT, ARCHIVE)
    before["output_handle"] = final["output_handle"]
    with pytest.raises(ValueError):
        check(before, final, metadata)


def test_missing_or_malformed_parent_cannot_establish_consistency():
    before, final, metadata = example()
    for bad in ({}, {**metadata, "private_index_lookup_passed": False},
                {**metadata, "frames": [3, 4, 1]}):
        with pytest.raises(ValueError):
            check(before, final, bad)
    bad = deepcopy(metadata)
    bad["frames"][-1]["count_after"] = True
    with pytest.raises(ValueError, match="parent query field"):
        check(before, final, bad)


def test_native_refusal_remains_failure():
    before, final, metadata = example()
    final.update(state=2, error=14, flags=7)
    result = check(before, final, metadata)
    assert result["path_packet_consistent"] is False and result["issues"]
    assert all(result[key] is False for key in review._scope())


def test_cli_preparation_and_review_are_real_read_only_consumers(prepared):
    arguments = [
        sys.executable, "scripts/review_cditem_native_path.py", "prepare",
        "--prepared", str(prepared["path"]), "--prepared-sha256", pin(prepared["path"])["sha256"],
        "--native-input", str(prepared["native"]), "--native-input-sha256", pin(prepared["native"])["sha256"],
    ]
    options = {"cwd": Path(__file__).resolve().parents[1], "capture_output": True,
               "text": True, "timeout": 30, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    run = subprocess.run(arguments, **options)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == inspect(prepared)

    observed = str(prepared["archive"])
    before, final, metadata = example(observed)
    meta_path, wire_path = prepared["path"].with_name("metadata.json"), prepared["path"].with_name("path.bin")
    meta_path.write_text(json.dumps(metadata))
    wire_path.write_bytes(packet(before, final, observed))
    arguments[2] = "review"
    arguments.extend(("--metadata", str(meta_path), "--metadata-sha256", pin(meta_path)["sha256"],
                      "--wire", str(wire_path), "--wire-sha256", pin(wire_path)["sha256"], "--pid", str(PID)))
    run = subprocess.run(arguments, **options)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["path_packet_consistent"] is True
    assert all(result[key] is False for key in review._scope())
    arguments[-1] = str(PID + 1)
    refused = subprocess.run(arguments, **options)
    assert refused.returncode == 2 and not refused.stdout
