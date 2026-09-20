"""Synthetic FAI3 records, matching ArchiveIndex's fixed-width wire layout."""
import json
from pathlib import Path
import struct
from uuid import uuid4

from cdmw.core.archive_resident_index import ResidentArchiveSource


def write_resident_index(root, entries, generation, *, override_flags=()):
    generation.mkdir(parents=True)
    strings = bytearray()
    offsets = {}

    def string(value):
        value = str(value)
        if value not in offsets:
            raw = value.encode("utf-8")
            offsets[value] = len(strings), len(raw)
            strings.extend(raw)
        return offsets[value]

    records = bytearray()
    for row, entry in enumerate(entries):
        path, path_len = string(entry.path)
        pamt, pamt_len = string(entry.pamt_path)
        paz, paz_len = string(entry.paz_file)
        records.extend(struct.pack("<6Q8I", path, pamt, paz, entry.offset, entry.comp_size, entry.orig_size,
                                   path_len, pamt_len, paz_len, entry.flags, entry.paz_index,
                                   override_flags[row] if override_flags else 0, 0, 0))
    header = struct.pack("<8sIIQQQQ", b"CDMWFAI3", 3, 80, len(entries), 64, 64 + len(records), len(strings))
    index = generation / "archive.ali"
    index.write_bytes(header.ljust(64, b"\0") + records + strings)
    paths = {Path(e.pamt_path) for e in entries} | {Path(e.paz_file) for e in entries}
    paths.update(path for path in (root / "meta").glob("*") if path.is_file())
    fingerprint = uuid4().hex
    manifest = {
        "fingerprint": fingerprint, "package_root": str(root), "index_version": 3,
        "entry_count": len(entries),
        "source_files": [{"relative_path": path.relative_to(root).as_posix(), "size": path.stat().st_size,
                          "modified_utc_ticks": path.stat().st_mtime_ns // 100 + 621355968000000000}
                         for path in sorted(paths)],
    }
    (generation / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return ResidentArchiveSource(str(root), fingerprint, str(index), len(entries))
