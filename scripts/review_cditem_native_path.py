"""Review retained private-resource research inputs and native path packets.

This offline tool uses the B112 wire contract. It does not load native code,
open a game process, verify capture provenance, or grant runtime admission.
The sealed research producers remain unchanged. See INDEPENDENT_ITEMS.md.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.core.archive_format import calculate_pa_checksum, parse_archive_pamt_bytes
from cdmw.core.papgt_format import parse_papgt

FORMAT = "cdmw_cditem_private_path_review_v1"
FIELDS = (
    "state", "error", "status", "thread", "module_base", "private_index",
    "file_record", "selected_group", "paz_ordinal", "output_slot",
    "output_handle", "characters", "returned_slot", "path_length", "flags",
    "last_error_before", "last_error_after", "provider", "vector_before",
    "count_before", "capacity_before", "vector_after", "count_after",
    "capacity_after", "provider_same", "item_owner", "item_count_before",
    "item_count_after", "item_same", "query_flags", "qpc_before", "qpc_after",
)
HEADER_BYTES, FRAME_BYTES, PATH_BYTES = 20, 768, 512
DOCUMENT_LIMIT = 256 * 1024
ARCHIVE_LIMIT = 8 * 1024 * 1024


def need(condition, message):
    if not condition:
        raise ValueError(message)


def _hash(value):
    need(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value),
         "An independent lowercase SHA-256 pin is required.")
    return value


def _literal_path(value):
    """Separator equivalence only; no case folding or dot resolution."""
    need(isinstance(value, str) and value and all(32 <= ord(c) < 127 for c in value),
         "A literal ASCII path is required.")
    value = value.replace("\\", "/")
    if value.startswith("/"):
        body = value[1:]
    else:
        need(re.match(r"^[A-Za-z]:/", value), "An absolute local path is required.")
        body = value[3:]
    parts = body.split("/")
    need(all(part and part not in (".", "..") and ":" not in part for part in parts),
         "Empty, relative, alternate-stream or device path components are unsupported.")
    return value


def _read_pinned(path, sha256, limit, size=None):
    path = Path(path)
    need(path.is_absolute(), "Pinned inputs must have absolute paths.")
    _hash(sha256)
    if size is not None:
        need(type(size) is int and 0 < size <= limit, "The declared input size is out of scope.")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    need(len(raw) <= limit and (size is None or len(raw) == size), "Pinned input size differs.")
    need(hashlib.sha256(raw).hexdigest() == sha256, "Pinned input digest differs: " + str(path))
    return raw


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, "Duplicate JSON field: " + key)
            value[key] = item
        return value

    def nonfinite(_):
        raise ValueError("Non-finite JSON numbers are unsupported.")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    need(isinstance(value, dict), "A JSON object is required.")
    return value


def _scope():
    return {
        "native_execution_verified": False,
        "native_payload_read_verified": False,
        "resource_use_verified": False,
        "native_admission": False,
    }


def inspect_preparation(prepared_path, prepared_sha256, native_input_path, native_input_sha256):
    """Bind the one-group, one-uncompressed-resource fixture without writing it."""
    prepared_raw = _read_pinned(prepared_path, prepared_sha256, DOCUMENT_LIMIT)
    prepared = _json(prepared_raw)
    root = prepared.get("root")
    canonical_root = _literal_path(root)
    need(len(root.encode("ascii")) < PATH_BYTES - 1, "The private root exceeds the native wire limit.")
    need(type(prepared.get("groups")) is int and prepared["groups"] == 1
         and type(prepared.get("pamt_entries")) is int and prepared["pamt_entries"] == 1
         and prepared.get("native_admission") is False,
         "Only the retained one-group, one-resource research input is supported.")
    resource = prepared.get("resource_path")
    need(isinstance(resource, str) and 0 < len(resource) < PATH_BYTES
         and all(32 <= ord(c) < 127 for c in resource)
         and all(p and p not in (".", "..") and ":" not in p
                 for p in resource.replace("\\", "/").split("/")),
         "A literal relative resource path is required.")
    for field in ("payload_bytes", "entry_offset", "entry_stored_bytes"):
        need(type(prepared.get(field)) is int and 0 <= prepared[field] <= ARCHIVE_LIMIT,
             "The prepared payload range is invalid: " + field)
    need(prepared["payload_bytes"] > 0, "An empty resource is outside this proof.")
    _hash(prepared.get("payload_sha256"))

    native_raw = _read_pinned(native_input_path, native_input_sha256, DOCUMENT_LIMIT)
    native_text = native_raw.decode("utf-8")
    need(not re.search(r'//|/\*|\*/|\\\r?\n|%:|\?\?', native_text),
         "Comments, line splicing and alternate preprocessing are unsupported in generated input.")
    root_pattern = r'^[ \t]*inline constexpr char root\[\]=R"\(([^"\r\n]*)\)";[ \t]*\r?$'
    resource_pattern = r'^[ \t]*inline constexpr char resource_path\[\]="([^"\\\r\n]*)";[ \t]*\r?$'
    roots = re.findall(root_pattern, native_text, re.MULTILINE)
    resources = re.findall(resource_pattern, native_text, re.MULTILINE)
    need(roots == [root] and resources == [resource],
         "The pinned native input must declare the exact prepared root and resource.")
    remainder = re.sub(root_pattern, "", native_text, flags=re.MULTILINE)
    remainder = re.sub(resource_pattern, "", remainder, flags=re.MULTILINE)
    body_lines = []
    for line in remainder.splitlines():
        if "#" in line:
            need(line.strip() in {"#pragma once", '#include "protocol.hpp"', "#include <span>"},
                 "Only the supported generated preamble is allowed.")
        else:
            body_lines.append(line)
    remainder = "\n".join(body_lines)
    # B98 also contains single-line wide raw literals for its pinned input files.
    # Remove only that supported literal form before detecting extra declarations.
    native_paths = re.findall(r'LR"\(([^"\r\n]*)\)"', remainder)
    remainder = re.sub(r'LR"\(([^"\r\n]*)\)"', "LITERAL", remainder)
    need(not re.search(r"\b(?:root|resource_path)\b", remainder)
         and not any(char in remainder for char in ('"', "'", "\\")),
         "Additional declarations, string literals or source escapes are unsupported.")

    references = prepared.get("files")
    need(isinstance(references, list) and len(references) == 3,
         "Exactly one private PAPGT, PAMT and PAZ are required.")
    captured, pins = {}, {}
    for reference in references:
        need(isinstance(reference, dict) and set(reference) == {"path", "bytes", "sha256"},
             "Invalid prepared file reference.")
        name = _literal_path(reference["path"])
        need(name.startswith(canonical_root + "/") and name not in captured,
             "A prepared file is outside its root or duplicated.")
        captured[name] = _read_pinned(reference["path"], reference["sha256"],
                                      ARCHIVE_LIMIT, reference["bytes"])
        pins[name] = dict(reference)

    need(all(_literal_path(path) in captured for path in native_paths),
         "A native input file literal does not name a prepared pinned file.")
    mount_path = canonical_root + "/meta/0.papgt"
    need(mount_path in captured, "The exact prepared private mount file is missing.")
    groups = parse_papgt(captured[mount_path])
    need(len(groups) == 1, "The private mount must contain exactly one group.")
    group = groups[0]
    need(group.name not in ("", ".", "..") and all(32 <= ord(c) < 127 for c in group.name)
         and not any(c in group.name for c in "/\\:"),
         "A literal private group directory is required.")
    index_path = canonical_root + "/" + group.name + "/0.pamt"
    need(index_path in captured, "The mount does not name the pinned private index.")
    index_raw = captured[index_path]
    need(len(index_raw) >= 12, "The private index is truncated.")
    stored_checksum, paz_count, _ = struct.unpack_from("<III", index_raw)
    need(paz_count == 1 and stored_checksum == group.pamt_checksum
         and calculate_pa_checksum(index_raw[12:]) == stored_checksum,
         "The private mount/index checksum or archive count differs.")
    entries = parse_archive_pamt_bytes(index_raw, Path(index_path))
    need(len(entries) == 1, "The private index must contain exactly one resource.")
    entry = entries[0]
    archive_path = _literal_path(str(entry.paz_file))
    need(set(captured) == {mount_path, index_path, archive_path},
         "The selected resource does not use the exact declared archive.")
    need(entry.path == resource and entry.paz_index == 0 and entry.flags == 0
         and entry.offset == prepared["entry_offset"]
         and entry.comp_size == prepared["entry_stored_bytes"]
         and entry.comp_size == entry.orig_size == prepared["payload_bytes"],
         "The resource identity, range or uncompressed representation differs.")
    archive = captured[archive_path]
    end = entry.offset + entry.comp_size
    need(0 <= entry.offset < end <= len(archive), "The resource extends outside its archive.")
    need(hashlib.sha256(archive[entry.offset:end]).hexdigest() == prepared["payload_sha256"],
         "The prepared resource payload differs.")

    return {
        "format": FORMAT, "private_archive_inputs_consistent": True,
        "prepared_input": {"path": str(prepared_path), "bytes": len(prepared_raw),
                           "sha256": prepared_sha256},
        "native_input": {"path": str(native_input_path), "bytes": len(native_raw),
                         "sha256": native_input_sha256},
        "root": root, "archive": pins[archive_path], "resource_path": resource,
        "selected_group": 0, "paz_ordinal": entry.paz_index,
        "payload": {"offset": entry.offset, "bytes": entry.comp_size,
                    "sha256": prepared["payload_sha256"]},
        "scope": "Offline consistency of pinned preparation, native constants and private bytes.",
        **_scope(),
    }


def review_path_wire(raw, pid, metadata, root, archive_path):
    """Check the retained B112 packet against independently prepared identity."""
    need(type(pid) is int and 0 < pid <= 0xFFFFFFFF, "An exact nonzero process ID is required.")
    expected_root, expected_archive = _literal_path(root), _literal_path(archive_path)
    need(expected_archive.startswith(expected_root + "/")
         and len(archive_path.encode("ascii")) < PATH_BYTES, "The exact private archive is required.")
    need(HEADER_BYTES <= len(raw) <= HEADER_BYTES + 2 * FRAME_BYTES
         and (len(raw) - HEADER_BYTES) % FRAME_BYTES == 0, "Incomplete or oversized native path wire.")
    need(struct.unpack_from("<5I", raw) == (0x50494443, 1, pid, 32, PATH_BYTES),
         "Path magic, version, PID or layout differs.")
    frames = []
    for offset in range(HEADER_BYTES, len(raw), FRAME_BYTES):
        row = dict(zip(FIELDS, struct.unpack_from("<32Q", raw, offset)))
        row["path_bytes"] = raw[offset + 256:offset + FRAME_BYTES]
        frames.append(row)
    need(frames and frames[-1]["state"] in (1, 2), "A terminal native path result is required.")
    final = frames[-1]
    need(final["thread"] and final["status"] == 1, "The original callback identity is missing.")
    serialized = [{**{key: value for key, value in row.items() if key != "path_bytes"},
                   "path_hex": row["path_bytes"].hex()} for row in frames]
    if final["state"] == 2:
        need(final["error"] > 0, "An explicit native refusal code is required.")
        if len(frames) == 2:
            need(frames[0]["state"] == 3 and frames[0]["flags"] == 1,
                 "The original before-path marker is missing.")
        return {"path_packet_consistent": False, "frames": serialized,
                "issues": ["Native path refused at error " + str(final["error"])], **_scope()}

    need(isinstance(metadata, dict) and metadata.get("private_index_lookup_passed") is True
         and metadata.get("issues") == [] and metadata.get("native_admission") is False,
         "A separately reviewed metadata-query receipt is required.")
    meta_frames = metadata.get("frames")
    need(isinstance(meta_frames, list) and len(meta_frames) == 3
         and all(isinstance(row, dict) for row in meta_frames)
         and [row.get("state") for row in meta_frames] == [3, 4, 1],
         "Complete parent query states are required.")
    query = meta_frames[-1]
    joins = (("thread", "thread"), ("module_base", "module_base"),
             ("private_index", "private_index"), ("file_record", "lookup_record"),
             ("provider", "provider"), ("item_owner", "item_owner"),
             ("vector_before", "vector_after"), ("count_before", "count_after"),
             ("capacity_before", "capacity_after"))
    for name in {target for _, target in joins} | {"lookup_flags", "lookup_expected_record", "qpc_after"}:
        need(type(query.get(name)) is int and query[name] >= 0, "Invalid parent query field: " + name)
    need(query["lookup_flags"] == 0x70003
         and query["lookup_record"] == query["lookup_expected_record"] > 0,
         "The exact private metadata result is required.")
    need(len(frames) == 2 and frames[0]["state"] == 3 and final["error"] == 0,
         "One path attempt and one successful return are required.")
    before = frames[0]
    changing = {"state", "output_handle", "characters", "returned_slot", "path_length",
                "flags", "last_error_after", "vector_after", "count_after",
                "capacity_after", "provider_same", "item_count_after", "item_same", "qpc_after"}
    for key in FIELDS:
        if key not in changing:
            need(before[key] == final[key], "The path call input changed: " + key)
    need(before["flags"] == 1 and before["error"] == 0
         and before["path_bytes"] == bytes(PATH_BYTES)
         and all(before[key] == 0 for key in changing - {"state", "flags"}),
         "The before-call marker contains fabricated output.")
    need(final["flags"] == 31 and final["query_flags"] == 0x70003,
         "The native path return and shape witness differs.")
    for name, target in joins:
        need(final[name] == query[target], "The path follows another metadata object: " + name)
    need(final["selected_group"] == final["paz_ordinal"] == 0,
         "The path must select the prepared group and archive.")
    need(final["qpc_after"] >= final["qpc_before"] >= query["qpc_after"] > 0,
         "The metadata query must finish before the path call.")
    need(final["output_slot"] > 0 and final["output_slot"] % 8 == 0
         and final["returned_slot"] == final["output_slot"]
         and final["output_handle"] > 0 and final["characters"] > 0,
         "The fresh native output or slot-address return differs.")
    need(final["vector_before"] == final["vector_after"] > 0
         and 0 < final["count_before"] == final["count_after"]
         <= final["capacity_before"] == final["capacity_after"] < 256,
         "The original provider shape changed.")
    need(final["provider_same"] == final["item_same"] == 1
         and final["item_count_before"] == final["item_count_after"] == 6816,
         "The sequential provider or ItemInfo witness differs.")
    length, data = final["path_length"], final["path_bytes"]
    need(0 < length < PATH_BYTES and data[length] == 0 and not any(data[length + 1:]),
         "The path must be bounded, NUL-terminated and followed by a zero tail.")
    observed = data[:length].decode("ascii")
    need(_literal_path(observed) == expected_archive,
         "The observed path is not the exact independently prepared private archive.")
    return {
        "path_packet_consistent": True, "issues": [], "frames": serialized,
        "observed_path": observed, "expected_archive_path": archive_path,
        "scope": "Offline packet consistency only. Capture provenance and native open/read/use remain unverified.",
        **_scope(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "review"))
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--prepared-sha256", required=True)
    parser.add_argument("--native-input", type=Path, required=True)
    parser.add_argument("--native-input-sha256", required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--metadata-sha256")
    parser.add_argument("--wire", type=Path)
    parser.add_argument("--wire-sha256")
    parser.add_argument("--pid", type=int)
    args = parser.parse_args(argv)
    try:
        result = inspect_preparation(args.prepared, args.prepared_sha256,
                                     args.native_input, args.native_input_sha256)
        review_args = (args.metadata, args.metadata_sha256, args.wire, args.wire_sha256, args.pid)
        if args.operation == "prepare":
            need(all(value is None for value in review_args), "Packet inputs require the review operation.")
        else:
            need(all(value is not None for value in review_args), "Review requires pinned metadata, wire and PID.")
            metadata = _json(_read_pinned(args.metadata, args.metadata_sha256, DOCUMENT_LIMIT))
            raw = _read_pinned(args.wire, args.wire_sha256, HEADER_BYTES + 2 * FRAME_BYTES)
            result.update(review_path_wire(raw, args.pid, metadata, result["root"], result["archive"]["path"]))
            result["metadata_input"] = {"path": str(args.metadata), "sha256": args.metadata_sha256}
            result["wire_input"] = {"path": str(args.wire), "sha256": args.wire_sha256, "pid": args.pid}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 3 if result.get("path_packet_consistent") is False else 0


if __name__ == "__main__":
    sys.exit(main())
