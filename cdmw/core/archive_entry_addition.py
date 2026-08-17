"""Add brand-new entries to a package index (PAMT), alongside in-place patches.

Replacing an entry only rewrites its 20-byte file record, which is what
:mod:`cdmw.core.archive_patching` does in place. Adding an entry cannot: it needs
a new name-block record, a new file record inside its folder's contiguous range,
and every later folder's start shifted by one. :class:`PamtDocument` is the full
structural model that makes that a rebuild rather than a byte splice.

Layout facts the rebuild relies on, measured on the installed build (0009: 7,496
folders, 427,871 files) and re-checked at parse time:

* the folder table is in file-start order and its ranges tile the file table
  without gaps, so a folder's files are found by index range, not by search;
* inside a folder the file names are in byte order (3,455 of 3,455 folders with
  more than one file), which is where a new record goes;
* a name-block entry may be flat (parent 0xFFFFFFFF), which is how the shipped
  tables root every chain and how the read-side resolver already treats it.

The in-game proof is the 2026-08-17 spike: five records added this way (a .pac,
.pac_xml, .hkx and two .prefab under existing folders) loaded and rendered.

Dependency direction: this module builds on :mod:`cdmw.core.archive_patching`
(payload primitives, backups, the checksum chain and the shared mutation runner)
and never the other way round.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from cdmw.core import archive_patching as _patching
from cdmw.core.archive_format import VfsPathResolver, calculate_pa_checksum
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest, ArchivePatchResult, MetaFileWrite


def _normalize(value: str) -> str:
    return _patching._normalize_virtual_path(value)


# --------------------------------------------------------------------------- model


@dataclass(slots=True)
class PamtFileRecord:
    name_offset: int
    paz_offset: int
    comp_size: int
    orig_size: int
    paz_index: int
    flags: int
    rel_name: str
    full_path: str


@dataclass(slots=True)
class PamtFolderRecord:
    folder_hash: int
    name_offset: int
    start: int
    count: int
    path: str


@dataclass(slots=True)
class PamtDocument:
    unknown: int
    paz_records: List[tuple[int, int, int]]
    dir_block: bytes
    name_block: bytearray
    folders: List[PamtFolderRecord]
    files: List[PamtFileRecord]
    index_by_path: Dict[str, int]

    def rebuild_index(self) -> None:
        self.index_by_path = {_normalize(record.full_path): position for position, record in enumerate(self.files)}
        if len(self.index_by_path) != len(self.files):
            raise ValueError("The PAMT names the same virtual path twice.")

    def folder_for(self, folder_path: str) -> Optional[PamtFolderRecord]:
        wanted = _normalize(folder_path)
        matches = [folder for folder in self.folders if _normalize(folder.path) == wanted]
        if len(matches) != 1:
            return None
        return matches[0]

    def replace_file(self, path: str, *, paz_index: int, paz_offset: int, comp_size: int, orig_size: int) -> None:
        record = self.files[self.index_by_path[_normalize(path)]]
        record.paz_index = int(paz_index)
        record.paz_offset = int(paz_offset)
        record.comp_size = int(comp_size)
        record.orig_size = int(orig_size)

    def add_file(self, path: str, *, paz_index: int, paz_offset: int, comp_size: int, orig_size: int, flags: int) -> int:
        """Insert a record for `path` under its existing folder; returns its file index."""

        clean = str(path or "").replace("\\", "/").strip("/")
        folder_path, _sep, base = clean.rpartition("/")
        folder = self.folder_for(folder_path)
        if folder is None:
            raise ValueError(f"Folder {folder_path!r} is not in this PAMT (new folders are not supported yet).")
        name_bytes = base.encode("utf-8")
        siblings = [self.files[position].rel_name for position in range(folder.start, folder.start + folder.count)]
        if siblings != sorted(siblings):
            raise ValueError(f"Folder {folder_path!r} is not in byte order, so a new record has no deterministic slot.")
        slot = folder.start
        while slot < folder.start + folder.count and self.files[slot].rel_name < base:
            slot += 1
        name_offset = len(self.name_block)
        self.name_block += struct.pack("<IB", 0xFFFFFFFF, len(name_bytes)) + name_bytes
        self.files.insert(
            slot,
            PamtFileRecord(
                name_offset=name_offset,
                paz_offset=int(paz_offset),
                comp_size=int(comp_size),
                orig_size=int(orig_size),
                paz_index=int(paz_index),
                flags=int(flags),
                rel_name=base,
                full_path=clean,
            ),
        )
        folder.count += 1
        position = self.folders.index(folder)
        for later in self.folders[position + 1 :]:
            later.start += 1
        self.rebuild_index()
        return slot

    def set_paz_record(self, paz_index: int, *, checksum: int, size: int) -> None:
        stored_index, _checksum, _size = self.paz_records[paz_index]
        self.paz_records[paz_index] = (stored_index, int(checksum) & 0xFFFFFFFF, int(size) & 0xFFFFFFFF)

    def serialize(self) -> bytes:
        out = bytearray()
        out += struct.pack("<III", 0, len(self.paz_records), self.unknown)
        for record in self.paz_records:
            out += struct.pack("<III", *record)
        out += struct.pack("<I", len(self.dir_block)) + self.dir_block
        out += struct.pack("<I", len(self.name_block)) + bytes(self.name_block)
        out += struct.pack("<I", len(self.folders))
        for folder in self.folders:
            out += struct.pack("<IIII", folder.folder_hash, folder.name_offset, folder.start, folder.count)
        out += struct.pack("<I", len(self.files))
        for record in self.files:
            out += struct.pack(
                "<IIIIHH",
                record.name_offset,
                record.paz_offset,
                record.comp_size,
                record.orig_size,
                record.paz_index,
                record.flags,
            )
        struct.pack_into("<I", out, 0, calculate_pa_checksum(bytes(out[12:])))
        return bytes(out)


def parse_pamt_document(data: bytes, *, name: str = "PAMT") -> PamtDocument:
    """Parse a whole PAMT into a rebuildable model, refusing anything off-layout."""

    def fail(message: str) -> ValueError:
        return ValueError(f"{name}: {message}")

    if len(data) < 12:
        raise fail("too small to hold a header")
    off = 0
    _header_crc, paz_count, unknown = struct.unpack_from("<III", data, off)
    off += 12
    if off + paz_count * 12 > len(data):
        raise fail("PAZ table is truncated")
    paz_records = [struct.unpack_from("<III", data, off + index * 12) for index in range(paz_count)]
    off += paz_count * 12
    if off + 4 > len(data):
        raise fail("directory block length is truncated")
    dir_size = struct.unpack_from("<I", data, off)[0]
    off += 4
    dir_block = bytes(data[off : off + dir_size])
    if len(dir_block) != dir_size:
        raise fail("directory block is truncated")
    off += dir_size
    if off + 4 > len(data):
        raise fail("file-name block length is truncated")
    name_size = struct.unpack_from("<I", data, off)[0]
    off += 4
    name_block = bytearray(data[off : off + name_size])
    if len(name_block) != name_size:
        raise fail("file-name block is truncated")
    off += name_size
    if off + 4 > len(data):
        raise fail("folder table length is truncated")
    folder_count = struct.unpack_from("<I", data, off)[0]
    off += 4
    if off + folder_count * 16 > len(data):
        raise fail("folder table is truncated")
    dir_resolver = VfsPathResolver(dir_block, max_cache_entries=200_000)
    folders: List[PamtFolderRecord] = []
    for index in range(folder_count):
        folder_hash, name_offset, start, count = struct.unpack_from("<IIII", data, off + index * 16)
        folders.append(
            PamtFolderRecord(
                folder_hash=folder_hash,
                name_offset=name_offset,
                start=start,
                count=count,
                path=dir_resolver.get_full_path(name_offset).replace("\\", "/").strip("/"),
            )
        )
    off += folder_count * 16
    if off + 4 > len(data):
        raise fail("file table length is truncated")
    file_count = struct.unpack_from("<I", data, off)[0]
    off += 4
    record_size = struct.calcsize("<IIIIHH")
    if off + file_count * record_size > len(data):
        raise fail("file table is truncated")
    name_resolver = VfsPathResolver(bytes(name_block), max_cache_entries=1_000_000)
    files: List[PamtFileRecord] = []
    for index in range(file_count):
        name_offset, paz_offset, comp_size, orig_size, paz_index, flags = struct.unpack_from(
            "<IIIIHH", data, off + index * record_size
        )
        if paz_index >= paz_count:
            raise fail(f"file record {index} points at PAZ index {paz_index} of {paz_count}")
        files.append(
            PamtFileRecord(
                name_offset=name_offset,
                paz_offset=paz_offset,
                comp_size=comp_size,
                orig_size=orig_size,
                paz_index=paz_index,
                flags=flags,
                rel_name=name_resolver.get_full_path(name_offset).replace("\\", "/").strip("/"),
                full_path="",
            )
        )
    off += file_count * record_size
    if off != len(data):
        raise fail(f"{len(data) - off} trailing byte(s) after the file table")

    # Folder ranges must be in order and tile the file table; that is what makes
    # "insert at index" a well-defined operation.
    expected_start = 0
    for position, folder in enumerate(folders):
        if folder.start < expected_start:
            raise fail(f"folder #{position} starts at {folder.start}, before the previous folder ended at {expected_start}")
        if folder.start != expected_start:
            raise fail(f"folder #{position} leaves a gap: starts at {folder.start}, previous ended at {expected_start}")
        for index in range(folder.start, folder.start + folder.count):
            if index >= len(files):
                raise fail(f"folder #{position} runs past the file table")
            files[index].full_path = f"{folder.path}/{files[index].rel_name}".strip("/") if folder.path else files[index].rel_name
        expected_start = folder.start + folder.count
    if expected_start != len(files):
        raise fail(f"folders cover {expected_start} of {len(files)} file record(s)")

    document = PamtDocument(
        unknown=unknown,
        paz_records=list(paz_records),
        dir_block=dir_block,
        name_block=name_block,
        folders=folders,
        files=files,
        index_by_path={},
    )
    document.rebuild_index()
    return document


def verify_rebuilt_document(
    original: PamtDocument,
    rebuilt_bytes: bytes,
    *,
    replaced: Mapping[str, tuple[int, int, int, int]],
    added: Mapping[str, tuple[int, int, int, int, int]],
    name: str,
) -> None:
    """Re-read the serialized PAMT and prove it is the old one plus exactly these edits."""

    rebuilt = parse_pamt_document(rebuilt_bytes, name=name)
    expected_paths = set(original.index_by_path) | set(added)
    if set(rebuilt.index_by_path) != expected_paths:
        raise ValueError(f"{name}: the rebuilt PAMT does not hold the old entries plus the additions.")
    if len(rebuilt.folders) != len(original.folders):
        raise ValueError(f"{name}: the rebuilt PAMT changed the folder count.")
    for path, position in original.index_by_path.items():
        before = original.files[position]
        after = rebuilt.files[rebuilt.index_by_path[path]]
        expected = replaced.get(path)
        if expected is None:
            expected = (before.paz_index, before.paz_offset, before.comp_size, before.orig_size)
        actual = (after.paz_index, after.paz_offset, after.comp_size, after.orig_size)
        if actual != expected or after.flags != before.flags:
            raise ValueError(f"{name}: entry {path} did not survive the rebuild as expected.")
    for path, (paz_index, paz_offset, comp_size, orig_size, flags) in added.items():
        after = rebuilt.files[rebuilt.index_by_path[path]]
        if (after.paz_index, after.paz_offset, after.comp_size, after.orig_size, after.flags) != (
            paz_index, paz_offset, comp_size, orig_size, flags,
        ):
            raise ValueError(f"{name}: added entry {path} did not read back as written.")


# --------------------------------------------------------------------------- preflight


def _validate_archive_add_flags(flags: int) -> None:
    compression_type = int(flags) & 0x0F
    encryption_type = (int(flags) >> 4) & 0x0F
    _patching._validate_archive_patch_compression_type(compression_type)
    if encryption_type not in {0, 3}:
        raise ValueError(f"Adding archive entries does not support encryption type {encryption_type} yet.")


def _process_add_payload(request: ArchiveAddRequest) -> bytes:
    processed = _patching._compress_archive_payload(request.payload_data, request.compression_type)
    if request.encryption_type:
        processed = _patching._crypt_archive_payload(processed, request.basename)
    return processed


def smallest_paz_index(pamt_path: Path, document: PamtDocument) -> int:
    """New payloads go to the group's smallest PAZ: least to back up, quickest to checksum."""

    sizes: Dict[int, int] = {}
    for paz_index in range(len(document.paz_records)):
        candidate = pamt_path.parent / f"{paz_index}.paz"
        if candidate.is_file():
            sizes[paz_index] = candidate.stat().st_size
    if not sizes:
        raise FileNotFoundError(f"No .paz files exist beside {pamt_path}.")
    return min(sizes, key=lambda index: (sizes[index], index))


@dataclass(slots=True)
class AddPlan:
    document: PamtDocument
    target_paz_index: int
    requests: List[ArchiveAddRequest]


def preflight_archive_add_requests(
    papgt_path: Path,
    grouped_additions: Mapping[Path, Sequence[ArchiveAddRequest]],
) -> Dict[Path, AddPlan]:
    """Refuse, before any backup or write, everything the rebuild cannot do."""

    for pamt_path in grouped_additions:
        if not pamt_path.is_file():
            raise FileNotFoundError(f"Could not find archive metadata file {pamt_path}.")
    _patching._verify_crc_chain(papgt_path, grouped_additions.keys())

    plans: Dict[Path, AddPlan] = {}
    for pamt_path, requests in grouped_additions.items():
        label = f"{pamt_path.parent.name}/{pamt_path.name}"
        document = parse_pamt_document(pamt_path.read_bytes(), name=label)
        seen: set[str] = set()
        for request in requests:
            clean = str(request.path or "").replace("\\", "/").strip("/")
            normalized = _normalize(clean)
            if not clean or ".." in clean.split("/") or "/" not in clean:
                raise ValueError(f"New archive path {request.path!r} must be a folder-qualified virtual path.")
            if normalized in seen:
                raise ValueError(f"New archive path {clean} is requested twice.")
            seen.add(normalized)
            if normalized in document.index_by_path:
                raise ValueError(f"{clean} already exists in {label}; patch it instead of adding it.")
            if len(request.basename.encode("utf-8")) > 255:
                raise ValueError(f"New archive name {request.basename!r} is longer than the 255 bytes a name record allows.")
            folder_path = clean.rpartition("/")[0]
            if document.folder_for(folder_path) is None:
                raise ValueError(
                    f"Folder {folder_path!r} is not in {label}; adding entries under a new folder is not supported yet."
                )
            _validate_archive_add_flags(request.flags)
        plans[pamt_path] = AddPlan(
            document=document,
            target_paz_index=smallest_paz_index(pamt_path, document),
            requests=list(requests),
        )
    return plans


# --------------------------------------------------------------------------- apply


def _apply_rebuild(
    pamt_path: Path,
    plan: AddPlan,
    group_patches: Sequence[ArchivePatchRequest],
    *,
    on_log: Optional[Callable[[str], None]],
) -> int:
    """Rebuild one PAMT with its additions (and any replacements); returns the new crc."""

    label = f"{pamt_path.parent.name}/{pamt_path.name}"
    document = plan.document
    original = parse_pamt_document(pamt_path.read_bytes(), name=label)
    _patching._safe_log(
        on_log,
        f"Rebuilding {label}: adding {len(plan.requests)} entrie(s)"
        + (f" and replacing {len(group_patches)}" if group_patches else "")
        + f"; new payloads go to {plan.target_paz_index}.paz...",
    )
    touched_paz_indices: set[int] = set()
    replaced: Dict[str, tuple[int, int, int, int]] = {}
    added: Dict[str, tuple[int, int, int, int, int]] = {}

    for request in group_patches:
        normalized_path = _normalize(request.entry.path)
        if normalized_path not in document.index_by_path:
            raise ValueError(f"Could not locate {request.entry.path} inside {pamt_path.name}.")
        _patching._safe_log(on_log, f"Preparing payload for {request.entry.path}...")
        processed_payload = _patching._compress_archive_payload(request.payload_data, request.entry.compression_type)
        if request.entry.encrypted:
            processed_payload = _patching._crypt_archive_payload(processed_payload, request.entry.basename)
        _patching._safe_log(
            on_log, f"Writing {request.entry.basename} to {request.entry.paz_file.name} at a safe append-only offset..."
        )
        new_offset = _patching._write_paz_payload(request.entry, processed_payload)
        document.replace_file(
            request.entry.path,
            paz_index=request.entry.paz_index,
            paz_offset=new_offset,
            comp_size=len(processed_payload),
            orig_size=len(request.payload_data),
        )
        replaced[normalized_path] = (int(request.entry.paz_index), new_offset, len(processed_payload), len(request.payload_data))
        touched_paz_indices.add(int(request.entry.paz_index))

    target_paz_path = pamt_path.parent / f"{plan.target_paz_index}.paz"
    for request in plan.requests:
        _patching._safe_log(on_log, f"Preparing payload for {request.path}...")
        processed_payload = _process_add_payload(request)
        _patching._safe_log(on_log, f"Writing {request.basename} to {target_paz_path.name} at a safe append-only offset...")
        new_offset = _patching._append_paz_payload(target_paz_path, processed_payload)
        slot = document.add_file(
            request.path,
            paz_index=plan.target_paz_index,
            paz_offset=new_offset,
            comp_size=len(processed_payload),
            orig_size=len(request.payload_data),
            flags=int(request.flags),
        )
        _patching._safe_log(on_log, f"Added {request.path} as file record #{slot}.")
        added[_normalize(request.path)] = (
            plan.target_paz_index, new_offset, len(processed_payload), len(request.payload_data), int(request.flags),
        )
        touched_paz_indices.add(plan.target_paz_index)

    for paz_index in sorted(touched_paz_indices):
        paz_path = pamt_path.parent / f"{paz_index}.paz"
        if not paz_path.is_file():
            raise FileNotFoundError(f"Could not find archive payload file {paz_path}.")
        _patching._safe_log(on_log, f"Recalculating checksum for {paz_path.name}...")
        paz_data = paz_path.read_bytes()
        document.set_paz_record(paz_index, checksum=calculate_pa_checksum(paz_data), size=len(paz_data))

    rebuilt = document.serialize()
    verify_rebuilt_document(original, rebuilt, replaced=replaced, added=added, name=label)
    _patching._safe_log(on_log, f"Writing rebuilt {pamt_path.name} ({len(document.files):,} file record(s))...")
    _patching._write_bytes_preserve_timestamps(pamt_path, rebuilt)
    return struct.unpack_from("<I", rebuilt, 0)[0]


def apply_archive_mutations(
    patches: Sequence[ArchivePatchRequest] = (),
    additions: Sequence[ArchiveAddRequest] = (),
    *,
    meta_files: Sequence[MetaFileWrite] = (),
    on_log: Optional[Callable[[str], None]] = None,
) -> ArchivePatchResult:
    """Replace and/or add archive entries in one backed-up, checksum-chained write.

    Replacements keep the proven in-place record rewrite. A package group that
    receives additions is rebuilt through :class:`PamtDocument` instead, and its
    replacements ride along in that rebuild so one backup covers both. `meta_files`
    are loose index files beside the archives (`meta/0.pathc`), rewritten whole under
    the same backup once the archive chain verifies.
    """

    patches = tuple(patches or ())
    additions = tuple(additions or ())
    meta_files = tuple(meta_files or ())
    if not patches and not additions:
        raise ValueError("No archive modifications were provided.")
    for request in additions:
        if not isinstance(request, ArchiveAddRequest):
            raise TypeError("Archive additions must be ArchiveAddRequest values.")
    for request in meta_files:
        if not isinstance(request, MetaFileWrite):
            raise TypeError("Archive meta file writes must be MetaFileWrite values.")

    package_roots = {_patching._package_root_from_entry(request.entry).resolve() for request in patches}
    package_roots.update(Path(request.pamt_path).resolve().parent.parent for request in additions)
    if len(package_roots) != 1:
        raise ValueError("Archive patching currently requires all modified entries to come from the same package root.")
    package_root = next(iter(package_roots))
    papgt_path = package_root / "meta" / "0.papgt"
    if not papgt_path.is_file():
        raise FileNotFoundError(f"Could not find PAPGT root index at {papgt_path}.")
    meta_writes = {}
    for request in meta_files:
        target = (package_root / request.path).resolve()
        if package_root not in target.parents:
            raise ValueError(f"Meta file {request.path!r} is outside the package root.")
        if not target.is_file():
            raise FileNotFoundError(f"Meta file {request.path!r} does not exist under {package_root}; only shipped index files are rewritten.")
        meta_writes[request.path] = (target, request.payload_data)

    grouped_patches: Dict[Path, List[ArchivePatchRequest]] = {}
    for request in patches:
        grouped_patches.setdefault(request.entry.pamt_path.resolve(), []).append(request)
    grouped_additions: Dict[Path, List[ArchiveAddRequest]] = {}
    for request in additions:
        grouped_additions.setdefault(Path(request.pamt_path).resolve(), []).append(request)

    mutable_by_pamt = _patching._preflight_archive_patch_requests(papgt_path=papgt_path, grouped_requests=grouped_patches)
    add_plans = preflight_archive_add_requests(papgt_path, grouped_additions)

    backup_targets: List[Path] = [papgt_path]
    for pamt_path, group_requests in grouped_patches.items():
        backup_targets.append(pamt_path)
        backup_targets.extend({request.entry.paz_file.resolve() for request in group_requests})
    for pamt_path, plan in add_plans.items():
        backup_targets.append(pamt_path)
        backup_targets.append((pamt_path.parent / f"{plan.target_paz_index}.paz").resolve())
    if additions and patches:
        description = f"Patch {len(patches)} and add {len(additions)} archive entrie(s)"
    elif additions:
        description = f"Add {len(additions)} archive entrie(s)"
    else:
        description = f"Patch {len(patches)} archive entrie(s)"

    def apply_group(pamt_path: Path) -> int:
        group_patches = grouped_patches.get(pamt_path, [])
        plan = add_plans.get(pamt_path)
        if plan is None:
            return _patching._apply_in_place_patches(pamt_path, mutable_by_pamt[pamt_path], group_patches, on_log=on_log)
        return _apply_rebuild(pamt_path, plan, group_patches, on_log=on_log)

    return _patching._run_archive_mutation(
        papgt_path=papgt_path,
        ordered_pamts=list(dict.fromkeys(list(grouped_patches) + list(grouped_additions))),
        backup_targets=backup_targets,
        description=description,
        changed_paths=[request.entry.path for request in patches] + [request.path for request in additions],
        added_paths=[request.path for request in additions],
        apply_group=apply_group,
        on_log=on_log,
        meta_writes=meta_writes,
    )


def add_archive_entries(
    requests: Sequence[ArchiveAddRequest],
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> ArchivePatchResult:
    """Add brand-new entries under existing folders of their package groups."""

    if not requests:
        raise ValueError("No archive additions were provided.")
    return apply_archive_mutations((), tuple(requests), on_log=on_log)


__all__ = [
    "AddPlan",
    "ArchiveAddRequest",
    "PamtDocument",
    "PamtFileRecord",
    "PamtFolderRecord",
    "add_archive_entries",
    "apply_archive_mutations",
    "parse_pamt_document",
    "preflight_archive_add_requests",
    "smallest_paz_index",
    "verify_rebuilt_document",
]
