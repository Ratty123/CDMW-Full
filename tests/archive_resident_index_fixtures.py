"""Synthetic FAI3 records, matching ArchiveIndex's fixed-width wire layout."""
import json
from pathlib import Path
import struct
from uuid import uuid4

from cdmw.core.archive_resident_index import ResidentArchiveSource, _basename_hash


def write_resident_index(root, entries, generation, *, override_flags=(), sort_records=True):
    entries = tuple(entries)
    ordered = list(zip(entries, override_flags or (0,) * len(entries)))
    if sort_records:
        ordered.sort(key=lambda pair: pair[0].path.replace('\\', '/').strip('/').encode('utf-8').lower())
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
    for entry, active_flags in ordered:
        path, path_len = string(entry.path)
        pamt, pamt_len = string(entry.pamt_path)
        paz, paz_len = string(entry.paz_file)
        records.extend(struct.pack("<6Q8I", path, pamt, paz, entry.offset, entry.comp_size, entry.orig_size,
                                   path_len, pamt_len, paz_len, entry.flags, entry.paz_index,
                                   active_flags, 0, 0))
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
    source = ResidentArchiveSource(str(root), fingerprint, str(index), len(entries))
    write_dependency_index(source, [entry for entry, _ in ordered])
    return source


def write_dependency_index(source, entries, *, basename_hash=_basename_hash):
    """The ADI1 basename records and BinaryWriter facet payload used by .NET."""
    records = sorted((basename_hash(entry.basename), row) for row, entry in enumerate(entries))
    names = b''.join(struct.pack('<QQ', *record) for record in records)
    stem_records = sorted((basename_hash(entry.basename.rsplit('.', 1)[0]), row)
                          for row, entry in enumerate(entries))
    stems = b''.join(struct.pack('<QQ', *record) for record in stem_records)
    # Four empty facet tables are
    # valid BinaryWriter data; consumers of their counts use the managed fixture.
    facets = struct.pack('<4i', 0, 0, 0, 0)
    count = len(records)
    header = struct.pack('<8sII8Q', b'CDMWADI1', 1, 16, count, 80, 80 + count * 16,
                         80 + count * 32, len(facets), count, Path(source.index_path).stat().st_size, 0)
    Path(source.index_path).with_suffix('.adi').write_bytes(header + names + stems + facets)
