"""Explicit, read-only installed-archive decode/material/mesh corpus audit.

Uses the archive worker's existing v3 catalogue and production native decoder.
Reports and short-lived parser inputs must be outside the game directory.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import ctypes
import hashlib
import json
import mmap
import os
from pathlib import Path
import random
import re
import struct
import subprocess
import tempfile
import time

MODELS = {".pac", ".pam", ".pamlod", ".pat"}
MATERIALS = {".pami", ".pac_xml", ".pam_xml", ".pamlod_xml", ".material"}
RECORD = struct.Struct("<6Q6I")
DDS_REFERENCE = re.compile(rb"[a-z0-9_./\\:-]+\.dds", re.I)


class Catalogue:
    def __init__(self, path: Path):
        self.stream = path.open("rb")
        self.data = mmap.mmap(self.stream.fileno(), 0, access=mmap.ACCESS_READ)
        if self.data[:8] != b"CDMWFAI3":
            raise ValueError("Expected a full archive v3 catalogue")
        version, size, self.count, self.records, self.strings, strings_size = struct.unpack_from("<II4Q", self.data, 8)
        if version != 3 or size != 80 or self.records + self.count * 80 > self.strings or self.strings + strings_size > len(self.data):
            raise ValueError("Invalid archive catalogue bounds")

    def entry(self, index: int) -> dict:
        if not 0 <= index < self.count:
            raise IndexError(index)
        row = RECORD.unpack_from(self.data, self.records + index * 80)
        strings = [self.data[self.strings + row[i]:self.strings + row[i] + row[6 + i]].decode("utf-8") for i in range(3)]
        return dict(id=index, path=strings[0], pamt=strings[1], paz=strings[2], offset=row[3],
                    stored=row[4], original=row[5], flags=row[9], paz_index=row[10])

    def close(self):
        self.data.close()
        self.stream.close()


class Decoder:
    def __init__(self, path: Path):
        self.library = ctypes.CDLL(str(path.resolve()))
        self.decode = self.library.cdmw_full_archive_decode_entry_with_context_utf8
        self.decode.argtypes = [ctypes.c_char_p] * 3 + [ctypes.c_uint64] * 3 + [ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        self.decode.restype = ctypes.c_int

    def read(self, entry: dict) -> tuple[bytes, str]:
        capacity = max(entry["stored"], entry["original"], 1)
        if capacity > 256 * 1024 * 1024:
            raise ValueError("audit_resource_limit: payload exceeds 256 MiB")
        output = ctypes.create_string_buffer(capacity)
        required = ctypes.c_size_t()
        note, error = ctypes.create_string_buffer(1024), ctypes.create_string_buffer(4096)
        status = self.decode(*(entry[key].encode("utf-8") for key in ("path", "pamt", "paz")),
            entry["offset"], entry["stored"], entry["original"], entry["flags"], output, capacity,
            ctypes.byref(required), note, len(note), error, len(error))
        if status:
            raise ValueError(f"native_status_{status}: {error.value.decode('utf-8', 'replace')}")
        return output.raw[:required.value], note.value.decode("utf-8", "replace")


def fingerprint(path: str) -> dict:
    source = Path(path)
    info = source.stat()
    result = {"size": info.st_size, "mtime_ns": info.st_mtime_ns}
    if source.suffix.lower() == ".pamt":
        with source.open("rb") as stream:
            result["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def geometry_audit(binary: Path, scratch: Path, entry: dict, payload: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix="mesh-", dir=scratch) as folder:
        root = Path(folder)
        source, report = root / ("input" + Path(entry["path"]).suffix), root / "report.json"
        source.write_bytes(payload)
        try:
            run = subprocess.run([str(binary), "mesh-audit-job", str(source), str(report), entry["path"]],
                capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            result = json.loads(report.read_text()) if report.is_file() else {"status": "error", "message": run.stderr.decode("utf-8", "replace")[-1000:]}
        except subprocess.TimeoutExpired:
            result = {"status": "timeout", "message": "Native geometry audit exceeded 20 seconds"}
        return {"id": entry["id"], "path": entry["path"], **result}


def run_scan(args) -> dict:
    started = time.monotonic()
    root = args.output.resolve()
    scratch = root / "scratch"
    catalogue = Catalogue(args.index)
    decoder = Decoder(args.decoder)
    rng = random.Random(20260925)
    counts, strata, sampled, geometry_samples = collections.Counter(), collections.Counter(), {}, {}
    all_paths, exhaustive, archive_paths = set(), set(), set()
    last_progress = time.monotonic()
    for index in range(catalogue.count):
        entry = catalogue.entry(index)
        extension = os.path.splitext(entry["path"])[1].lower()
        all_paths.add(entry["path"].replace("\\", "/").lstrip("/").casefold())
        archive_paths.update((entry["pamt"], entry["paz"]))
        counts[extension] += 1
        key = (extension, entry["flags"])
        strata[key] += 1
        bucket = sampled.setdefault(key, [])
        limit = args.samples_per_format
        if len(bucket) < limit:
            bucket.append(index)
        else:
            slot = rng.randrange(strata[key])
            if slot < limit:
                bucket[slot] = index
        if extension in MATERIALS or (extension in {".pam", ".pamlod"} and entry["flags"] & 15 == 1 and entry["stored"] != entry["original"]):
            exhaustive.add(index)
        if extension in MODELS:
            bucket = geometry_samples.setdefault(extension, [])
            if len(bucket) < args.geometry_per_format:
                bucket.append(index)
            else:
                slot = rng.randrange(counts[extension])
                if slot < args.geometry_per_format:
                    bucket[slot] = index
        if time.monotonic() - last_progress >= 15:
            print(json.dumps({"phase": "inventory", "completed": index + 1, "total": catalogue.count}), flush=True)
            last_progress = time.monotonic()
    geometry_ids = {index for bucket in geometry_samples.values() for index in bucket}
    selected = exhaustive | geometry_ids | {index for bucket in sampled.values() for index in bucket}
    if not archive_paths:
        catalogue.close()
        raise ValueError("Cannot audit an empty archive catalogue")
    archive_root = Path(os.path.commonpath(archive_paths)).resolve()
    if root.is_relative_to(archive_root):
        catalogue.close()
        raise ValueError("Audit output must be outside the source archive tree")
    root.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(exist_ok=True)
    before = {path: fingerprint(path) for path in sorted(archive_paths)}
    print(json.dumps({"phase": "inventory_complete", "entries": catalogue.count, "formats": len(counts), "selected": len(selected), "exhaustive_static_and_materials": len(exhaustive), "geometry": len(geometry_ids)}), flush=True)
    summary = {"schema": "cdmw_archive_format_scan_v1", "index": str(args.index.resolve()),
        "entry_count": catalogue.count, "inventory": dict(sorted(counts.items())),
        "selection": {"total": len(selected), "all_material_and_partial_static_entries": len(exhaustive), "geometry": len(geometry_ids), "samples_per_extension_and_flags": args.samples_per_format},
        "decoder_sha256": hashlib.sha256(args.decoder.read_bytes()).hexdigest(),
        "preview_core_sha256": hashlib.sha256(args.preview_core.read_bytes()).hexdigest()}
    stats = collections.defaultdict(collections.Counter)
    missing = collections.Counter()
    pending = set()
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool, (root / "decode-results.jsonl").open("w", encoding="utf-8") as records, (root / "geometry-results.jsonl").open("w", encoding="utf-8") as geometry_records, (root / "material-missing.jsonl").open("w", encoding="utf-8") as material_records:
        def accept_geometry(done):
            for future in done:
                result = future.result()
                extension = os.path.splitext(result["path"])[1].lower()
                stats[extension]["geometry_" + result["status"]] += 1
                geometry_records.write(json.dumps(result) + "\n")
                geometry_records.flush()
        for index in sorted(selected):
            entry = catalogue.entry(index)
            extension = os.path.splitext(entry["path"])[1].lower()
            stats[extension]["checked"] += 1
            record = {"id": index, "path": entry["path"], "stored": entry["stored"], "original": entry["original"], "flags": entry["flags"]}
            try:
                payload, note = decoder.read(entry)
                record.update(decoded=len(payload), note=note, status="ok", signature=payload[:12].hex())
                if "PartialRaw" in note:
                    record["status"] = "partial_raw"
                    stats[extension]["partial_raw"] += 1
                elif len(payload) != entry["original"]:
                    record["status"] = "size_mismatch"
                    stats[extension]["size_mismatch"] += 1
                else:
                    stats[extension]["decode_ok"] += 1
                if extension in MATERIALS:
                    references = {x.decode("ascii").replace("\\", "/") for x in DDS_REFERENCE.findall(payload)}
                    for reference in references:
                        normalized = reference.lstrip("/").casefold()
                        stats[extension]["dds_references"] += 1
                        if normalized in all_paths:
                            stats[extension]["dds_present"] += 1
                            if reference.startswith("/"):
                                stats[extension]["rooted_dds_present"] += 1
                        else:
                            stats[extension]["dds_absent_exact_path"] += 1
                            missing[normalized] += 1
                            material_records.write(json.dumps({"id": index, "path": entry["path"], "reference": reference}) + "\n")
                if index in geometry_ids and record["status"] == "ok":
                    pending.add(pool.submit(geometry_audit, args.preview_core.resolve(), scratch, entry, payload))
                    if len(pending) >= 8:
                        done, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                        accept_geometry(done)
            except Exception as exc:
                record.update(status="error", error=str(exc))
                stats[extension]["decode_error"] += 1
            records.write(json.dumps(record) + "\n")
            completed += 1
            if time.monotonic() - last_progress >= 15:
                records.flush()
                print(json.dumps({"phase": "decode", "completed": completed, "total": len(selected), "errors": sum(v["decode_error"] for v in stats.values())}), flush=True)
                last_progress = time.monotonic()
        accept_geometry(pending)
    after = {path: fingerprint(path) for path in sorted(archive_paths)}
    summary.update(results=dict(sorted((key, dict(value)) for key, value in stats.items())),
        missing_reference_examples=missing.most_common(40),
        archive_fingerprints_unchanged=before == after, archive_file_count=len(before),
        elapsed_seconds=round(time.monotonic() - started, 2))
    (root / "archive-fingerprints.json").write_text(json.dumps({"before": before, "after": after}, indent=2), encoding="utf-8")
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    catalogue.close()
    print(json.dumps({"phase": "complete", "report": str(root / "summary.json"), "elapsed_seconds": summary["elapsed_seconds"], "archive_fingerprints_unchanged": before == after}), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--preview-core", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples-per-format", type=int, default=128)
    parser.add_argument("--geometry-per-format", type=int, default=512)
    arguments = parser.parse_args()
    if arguments.samples_per_format < 1 or arguments.geometry_per_format < 1:
        parser.error("Sample counts must be positive")
    run_scan(arguments)
