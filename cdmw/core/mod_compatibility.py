"""Portable game identity and original payloads for reviewing exported mods.

These files are package metadata, never game payloads. Unknown originals remain
unknown; a mod's current bytes must never be promoted to its original baseline.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping

from cdmw.constants import APP_VERSION
from cdmw.domain.cancellation import raise_if_cancelled

COMPATIBILITY_FILE = "cdmw-compatibility.json"
BASELINE_FILE = "cdmw-baseline.zip"
COMPATIBILITY_FORMAT = "cdmw_mod_compatibility_v1"
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_BASELINE_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024


def payload_path(value: str) -> str:
    text = str(value).replace("\\", "/")
    parts = text.split("/")
    if not text or text.startswith("/") or any(p in ("", ".", "..") for p in parts) or ":" in text or "\0" in text:
        raise ValueError(f"Invalid compatibility payload path: {text!r}")
    return PurePosixPath(*parts).as_posix().lower()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path, stop_event=None) -> str:
    hasher = hashlib.sha256()
    before = path.stat()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            raise_if_cancelled(stop_event, "Game build check cancelled.")
            hasher.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError(f"Source changed during the game build check: {path}")
    return hasher.hexdigest()


def decode_paver_build(raw: bytes) -> str:
    """Read the binary version tuple, retaining legacy text PAVER support."""
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        text = ""
    if text and all(ch.isprintable() or ch in "\r\n\t" for ch in text):
        return " ".join(text.split())[:240]
    # The installed record is three little-endian u16 version fields followed
    # by four opaque build bytes. The latter are not a printable build label.
    if len(raw) == 10:
        major, minor, patch = struct.unpack_from("<3H", raw)
        return f"{major}.{minor:02}.{patch:02}"
    return ""


def game_identity(game_root: Path | None, stop_event=None) -> dict:
    """Keep mount-list changes separate from game build identity."""
    result = {"game": "Crimson Desert", "build": "", "paver_sha256": "", "executable_sha256": ""}
    if game_root is None:
        return result
    from cdmw.core.archive_scan_cache import resolve_crimson_desert_executable

    root = Path(game_root)
    paver = root / "meta/0.paver"
    if paver.is_file():
        result["paver_sha256"] = hash_file(paver, stop_event)
        with paver.open("rb") as stream:
            raw = stream.read(4096)
        result["build"] = decode_paver_build(raw)
    executable = resolve_crimson_desert_executable(root)
    if executable is not None:
        result["executable_sha256"] = hash_file(executable, stop_event)
    return result


def build_status(recorded: Mapping | None, current: Mapping) -> str:
    recorded = recorded if isinstance(recorded, Mapping) else {}
    compared = False
    matched_paver = False
    for key in ("executable_sha256", "paver_sha256"):
        old, new = recorded.get(key), current.get(key)
        if isinstance(old, str) and isinstance(new, str) and old and new:
            compared = True
            if old != new:
                return "changed"
            if key == "paver_sha256":
                matched_paver = True
    if matched_paver:
        # Identical version bytes can acquire a corrected display label.
        return "same"
    old, new = recorded.get("build"), current.get("build")
    if isinstance(old, str) and isinstance(new, str) and old and new:
        return "same" if old == new else "changed"
    return "same" if compared else "unknown"


def build_label(identity: Mapping | None) -> str:
    identity = identity if isinstance(identity, Mapping) else {}
    return str(identity.get("build") or ("EXE " + str(identity["executable_sha256"])[:12]
               if identity.get("executable_sha256") else "Unknown"))


@dataclass(frozen=True)
class ModCompatibility:
    target_game: dict = field(default_factory=dict)
    files: tuple[dict, ...] = ()
    originals: Mapping[str, bytes | None] = field(default_factory=dict, repr=False)
    dependencies: tuple[dict, ...] = ()


def compatibility_from_payloads(after: Mapping[str, bytes], before: Mapping[str, bytes | None], *,
                                target_game=None, dependencies=()) -> ModCompatibility:
    originals, records = {}, []
    total = 0
    for raw_path, data in sorted(after.items()):
        path = payload_path(raw_path)
        original = before.get(path)
        known = path in before
        if original is not None:
            if len(original) > MAX_FILE_BYTES or total + len(original) > MAX_BASELINE_BYTES:
                known = False
            else:
                total += len(original)
        if known:
            originals[path] = original
        records.append({"path": path, "sha256": digest(data), "baseline_known": known,
                        "baseline_sha256": digest(original) if known and original is not None else None})
    return ModCompatibility(dict(target_game or game_identity(None)), tuple(records), originals, tuple(dependencies))


def capture_patch_compatibility(requests, additions=(), *, game_root=None, metadata_files=(),
                                read_entry=None, dependencies=(), stop_event=None) -> ModCompatibility:
    from cdmw.core.archive_extraction import read_archive_entry_data

    reader = read_entry or (lambda entry: read_archive_entry_data(entry)[0])
    before, after = {}, {}
    for request in requests:
        raise_if_cancelled(stop_event, "Mod baseline capture cancelled.")
        path = payload_path(request.entry.path)
        after[path] = bytes(request.payload_data)
        try:
            before[path] = bytes(reader(request.entry))
        except (OSError, ValueError):
            # Some export routes have no readable original. Preserve that fact.
            pass
    for request in additions:
        path = payload_path(request.path)
        after[path], before[path] = bytes(request.payload_data), None
    for raw_path, data in metadata_files:
        path = payload_path(raw_path)
        if path != "meta/0.pathc":
            continue
        after[path] = bytes(data)
        source = Path(game_root) / path if game_root is not None else None
        if source is not None and source.is_file():
            before[path] = source.read_bytes()
    return compatibility_from_payloads(after, before, target_game=game_identity(game_root, stop_event),
                                       dependencies=dependencies)


def write_compatibility(root: Path, compatibility: ModCompatibility, *, stop_event=None) -> tuple[Path, ...]:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        seen = set()
        for data in compatibility.originals.values():
            raise_if_cancelled(stop_event, "Mod baseline export cancelled.")
            if data is not None and digest(data) not in seen:
                key = digest(data)
                with archive.open(key, "w") as target:
                    for offset in range(0, len(data), 1024 * 1024):
                        raise_if_cancelled(stop_event, "Mod baseline export cancelled.")
                        target.write(data[offset:offset + 1024 * 1024])
                seen.add(key)
    baseline = stream.getvalue()
    raise_if_cancelled(stop_event, "Mod baseline export cancelled.")
    from cdmw.core.atomic_file import atomic_write_bytes
    baseline_path = root / BASELINE_FILE
    atomic_write_bytes(baseline_path, baseline)
    payload = {"format": COMPATIBILITY_FORMAT, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "cdmw_version": APP_VERSION, "target_game": compatibility.target_game,
               "files": list(compatibility.files), "dependencies": list(compatibility.dependencies),
               "baseline_archive": BASELINE_FILE, "baseline_archive_sha256": digest(baseline)}
    manifest = root / COMPATIBILITY_FILE
    atomic_write_bytes(manifest, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return manifest, baseline_path


def read_compatibility(root: Path, *, stop_event=None) -> ModCompatibility | None:
    """Read bounded, hash-checked metadata without extracting arbitrary ZIP paths."""
    root = Path(root).resolve()
    if root.is_file() and root.suffix.lower() == ".zip":
        with zipfile.ZipFile(root) as package:
            candidates = [item for item in package.infolist() if item.filename == COMPATIBILITY_FILE
                          or item.filename.endswith("/" + COMPATIBILITY_FILE)]
            if not candidates:
                return None
            if len(candidates) != 1 or candidates[0].file_size > MAX_METADATA_BYTES:
                raise ValueError("Ambiguous or oversized compatibility metadata in ZIP package.")
            prefix = candidates[0].filename[:-len(COMPATIBILITY_FILE)]
            baseline = package.getinfo(prefix + BASELINE_FILE)
            if baseline.file_size > MAX_BASELINE_BYTES + MAX_METADATA_BYTES:
                raise ValueError("Oversized mod baseline in ZIP package.")
            with tempfile.TemporaryDirectory(prefix="cdmw-mod-evidence-") as temporary:
                directory = Path(temporary)
                for info, name in ((candidates[0], COMPATIBILITY_FILE), (baseline, BASELINE_FILE)):
                    with package.open(info) as source, (directory / name).open("wb") as target:
                        while data := source.read(1024 * 1024):
                            raise_if_cancelled(stop_event, "Mod compatibility read cancelled.")
                            target.write(data)
                return read_compatibility(directory, stop_event=stop_event)
    from cdmw.core.mod_export_history import mod_metadata_path

    source = mod_metadata_path(root, COMPATIBILITY_FILE, stop_event=stop_event)
    if not source.exists():
        return None
    root = source.parent
    if source.is_symlink() or source.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError("Invalid or oversized mod compatibility metadata.")
    payload = json.loads(source.read_bytes())
    if not isinstance(payload, dict) or payload.get("format") != COMPATIBILITY_FORMAT:
        raise ValueError("Unsupported mod compatibility metadata.")
    if not isinstance(payload.get("target_game"), dict) or not isinstance(payload.get("files"), list):
        raise ValueError("Invalid mod compatibility fields.")
    if payload.get("baseline_archive") != BASELINE_FILE:
        raise ValueError("Invalid mod baseline archive path.")
    baseline_path = root / BASELINE_FILE
    if baseline_path.is_symlink() or not baseline_path.is_file() or baseline_path.stat().st_size > MAX_BASELINE_BYTES + MAX_METADATA_BYTES:
        raise ValueError("Missing or oversized mod baseline archive.")
    if hash_file(baseline_path, stop_event) != payload.get("baseline_archive_sha256"):
        raise ValueError("Mod baseline archive changed since export.")
    originals, records, seen = {}, [], set()
    with zipfile.ZipFile(baseline_path) as archive:
        members = archive.infolist()
        if len(members) > 100000 or sum(item.file_size for item in members) > MAX_BASELINE_BYTES:
            raise ValueError("Mod baseline archive exceeds the supported size.")
        if len({item.filename for item in members}) != len(members) or any(
                not re.fullmatch(r"[0-9a-f]{64}", item.filename) or item.file_size > MAX_FILE_BYTES for item in members):
            raise ValueError("Invalid mod baseline archive members.")
        cache = {}
        for record in payload["files"]:
            raise_if_cancelled(stop_event, "Mod compatibility check cancelled.")
            if not isinstance(record, dict):
                raise ValueError("Invalid mod baseline record.")
            path = payload_path(record.get("path", ""))
            if path in seen or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
                raise ValueError("Duplicate or invalid mod baseline record.")
            seen.add(path)
            if not isinstance(record.get("baseline_known"), bool):
                raise ValueError("Invalid mod baseline availability.")
            if record["baseline_known"]:
                checksum = record.get("baseline_sha256")
                if checksum is None:
                    originals[path] = None
                else:
                    if not re.fullmatch(r"[0-9a-f]{64}", str(checksum)):
                        raise ValueError("Invalid mod baseline checksum.")
                    if checksum not in cache:
                        data = archive.read(checksum)
                        if digest(data) != checksum:
                            raise ValueError(f"Mod baseline checksum mismatch: {path}")
                        cache[checksum] = data
                    originals[path] = cache[checksum]
            records.append(dict(record, path=path))
    dependencies = payload.get("dependencies", [])
    if not isinstance(dependencies, list) or any(not isinstance(item, dict) for item in dependencies):
        raise ValueError("Invalid mod dependency records.")
    for item in dependencies:
        payload_path(item.get("path", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            raise ValueError("Invalid mod dependency checksum.")
    return ModCompatibility(payload["target_game"], tuple(records), originals, tuple(dependencies))


__all__ = ["BASELINE_FILE", "COMPATIBILITY_FILE", "ModCompatibility", "build_label", "build_status",
           "capture_patch_compatibility", "compatibility_from_payloads", "decode_paver_build", "digest", "game_identity",
           "hash_file", "payload_path", "read_compatibility", "write_compatibility"]


# This is an opaque, negotiated export, not optional metadata on loose files.
# The complete schema and examples live beside this owner in SEMANTIC_EXPORT.md.
SEMANTIC_EXPORT_FILE = "cdmw-semantic.cditem"
SEMANTIC_EXPORT_FORMAT = "cdmw_mod_semantic_export"
SEMANTIC_EXPORT_VERSION = 1


def semantic_export_path(source) -> Path | None:
    """Cheap admission check; no payload decoding on synchronous UI callers."""
    if not isinstance(source, (str, Path)):
        return None
    path = Path(source)
    if path.is_file():
        return path if path.suffix.lower() == ".cditem" else None
    if not path.is_dir():
        return None
    entries = tuple(path.iterdir())
    candidates = [entry for entry in entries if entry.name.casefold() == SEMANTIC_EXPORT_FILE]
    if not candidates:
        return None
    if (len(candidates) != 1 or len(entries) != 1
            or candidates[0].name != SEMANTIC_EXPORT_FILE
            or candidates[0].is_symlink() or not candidates[0].is_file()
            or path.is_symlink() or getattr(path, "is_junction", lambda: False)()):
        raise ValueError("A semantic export requires its single opaque .cditem wrapper; extra or linked files refuse.")
    return candidates[0]


def _semantic_path(value, *, index=False):
    if (not isinstance(value, str) or len(value) > 512 or payload_path(value) != value
            or any(part.rstrip(" .") != part for part in value.split("/"))):
        raise ValueError("Invalid or non-normalized semantic export path.")
    if index:
        if not re.fullmatch(r"[0-9]{4}/[^/]+\.pamt", value):
            raise ValueError("Invalid semantic export archive-index path.")
    elif value != "meta/0.pathc":
        from cdmw.services.independent_item_package import virtual_path
        virtual_path(value)
    return value


def _semantic_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate semantic export metadata key.")
        result[key] = value
    return result


def _semantic_hash_record(value):
    if (not isinstance(value, dict) or set(value) != {"size", "sha256"}
            or type(value["size"]) is not int or not 0 <= value["size"] <= MAX_FILE_BYTES
            or not isinstance(value["sha256"], str)
            or not re.fullmatch("[0-9a-f]{64}", value["sha256"])):
        raise ValueError("Invalid semantic export payload size or digest.")
    return value


@dataclass(frozen=True)
class SemanticExport:
    """Retained intent and compiled evidence. Admission always recompiles intent."""
    packages: tuple[bytes, ...]
    files: tuple[tuple[str, bytes, int], ...]
    originals: Mapping[str, bytes | None]
    bindings: dict
    compiler: dict
    witnesses: dict
    target_game: dict = field(default_factory=dict)
    source: Path | None = field(default=None, compare=False, repr=False)
    artifact_digest: str = field(default="", compare=False)
    folder: Path | None = field(default=None, compare=False, repr=False)

    def validate(self, stop_event=None):
        if self.source is not None:
            if self.folder is not None and semantic_export_path(self.folder) != self.source:
                raise ValueError("The semantic export folder changed after review.")
            if self.source.is_symlink() or hash_file(self.source, stop_event) != self.artifact_digest:
                raise ValueError("The semantic export changed after review.")
        raise_if_cancelled(stop_event)

    def validate_source(self, snapshot, root, stop_event=None):
        """Require the recorded original inputs, never the exported edited files."""
        from cdmw.domain.new_item.compilation import compiler_stamp
        if self.compiler != compiler_stamp():
            raise ValueError("The semantic export compiler is unsupported. Export again with the current compiler.")
        root = Path(root).resolve()
        self.validate(stop_event)
        current_game = game_identity(root, stop_event)
        from cdmw.core.archive_scan_cache import (
            crimson_desert_executable_candidates, resolve_crimson_desert_executable)
        identity_paths = {'paver_sha256': root / 'meta/0.paver',
                          'executable_sha256': resolve_crimson_desert_executable(root)}
        for key in ('paver_sha256', 'executable_sha256'):
            if self.target_game.get(key) and self.target_game[key] != current_game.get(key):
                raise ValueError(f'Semantic export game identity changed: {key}.')
            if self.target_game.get(key):
                # The source tracker carries exact immutable-file digests as well
                # as parsed PAMT witnesses. Keep this compared build identity
                # pinned through physical publication and worker transfer.
                if identity_paths[key] is None:
                    raise ValueError(f'Semantic export game identity is missing: {key}.')
                if key == 'executable_sha256':
                    # Creating an earlier candidate must invalidate the reviewed
                    # executable selection, even when the old file stays equal.
                    for candidate in crimson_desert_executable_candidates(root):
                        snapshot.provenance.pin_file(candidate)
                        if candidate.resolve() == identity_paths[key].resolve():
                            break
                        if candidate.is_file():
                            raise ValueError(f'Semantic export game identity changed: {key}.')
                snapshot.provenance.pin_index(identity_paths[key], self.target_game[key], stop_event)
        if build_status(self.target_game, current_game) == 'changed':
            raise ValueError('Semantic export game build changed.')
        witnessed = {str(Path(path).resolve().relative_to(root)).replace("\\", "/").lower(): checksum
                     for path, checksum in snapshot.provenance.capture().indexes
                     if Path(path).suffix.lower() == '.pamt'
                     and Path(path).resolve().is_relative_to(root)}
        expected_indexes = {row["path"]: row["sha256"] for row in self.witnesses["indexes"]}
        if witnessed != expected_indexes:
            raise ValueError("The semantic export archive indexes differ from the witnessed game baseline.")
        for row in self.witnesses["indexes"]:
            raise_if_cancelled(stop_event)
            path = root / row["path"]
            if (path.is_symlink() or not path.is_file() or path.stat().st_size != row["size"]
                    or hash_file(path, stop_event) != row["sha256"]):
                raise ValueError(f"Semantic export source index changed: {row['path']}.")
            snapshot.provenance.pin_index(path, row["sha256"], stop_event)
        for row in self.witnesses["payloads"]:
            raise_if_cancelled(stop_event)
            if row["path"] == "meta/0.pathc":
                from cdmw.core.pathc_format import encode_pathc
                data = encode_pathc(snapshot.pathc) if snapshot.pathc is not None else None
            else:
                data = snapshot.payload(row["path"]) if snapshot.has_entry(row["path"]) else None
            if data is None or len(data) != row["size"] or digest(data) != row["sha256"]:
                raise ValueError(f"Semantic export original source changed: {row['path']}.")
        if 'meta/0.pathc' in self.originals:
            from cdmw.core.pathc_format import encode_pathc
            original = self.originals['meta/0.pathc']
            current = encode_pathc(snapshot.pathc) if snapshot.pathc is not None else None
            if current != original:
                raise ValueError('Semantic export original texture registry changed.')
        self.validate(stop_event)
        return self


def _read_semantic_bytes(raw, *, required=False, stop_event=None, package_cache=None):
    from cdmw.services.independent_item_package import (
        MAX_TOTAL, MAX_FILES, canonical, read_package, package_metadata, _read_member,
    )
    from cdmw.services.independent_item_install import _validate_registry
    from cdmw.domain.new_item.compilation import validate_compiler_stamp
    from cdmw.domain.new_item.package_links import resolve_package_graph
    if len(raw) > MAX_TOTAL + MAX_METADATA_BYTES:
        raise ValueError("The semantic export exceeds the supported size.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if "semantic.json" not in names:
                if required or "item.json" not in names:
                    raise ValueError("Missing required semantic export metadata.")
                return None
            if (len(infos) > MAX_FILES or len(set(names)) != len(names)
                    or sum(item.file_size for item in infos) > MAX_TOTAL + MAX_METADATA_BYTES):
                raise ValueError("Duplicate or oversized semantic export entries.")
            for item in infos:
                limit = (MAX_METADATA_BYTES if item.filename == "semantic.json" else
                         MAX_TOTAL if item.filename.startswith("packages/") else MAX_FILE_BYTES)
                if (item.file_size > limit or item.flag_bits & 1 or item.is_dir()
                        or (item.external_attr >> 16) & 0o170000 == 0o120000
                        or item.filename != "semantic.json" and not re.fullmatch(
                            r"(?:packages/[0-9a-f]{64}\.cditem|payloads/[0-9a-f]{64})", item.filename)):
                    raise ValueError("Unsafe or unsupported semantic export entry.")
            meta = json.loads(_read_member(archive, "semantic.json", stop_event),
                              object_pairs_hook=_semantic_unique)
            keys = {"format", "version", "requires", "compiler", "target_game",
                    "packages", "files", "bindings", "witnesses"}
            if (not isinstance(meta, dict) or set(meta) != keys
                    or meta["format"] != SEMANTIC_EXPORT_FORMAT
                    or type(meta["version"]) is not int or meta["version"] != SEMANTIC_EXPORT_VERSION
                    or meta["requires"] != {"export.semantic": 1}
                    or type(meta["requires"].get("export.semantic")) is not int):
                raise ValueError("Unsupported required semantic export format or capability version.")
            validate_compiler_stamp(meta["compiler"])
            game = meta["target_game"]
            if (not isinstance(game, dict) or set(game) - {"game", "build", "paver_sha256", "executable_sha256"}
                    or any(not isinstance(value, str) or len(value) > 512 or "\0" in value for value in game.values())):
                raise ValueError("Invalid semantic export game identity.")
            for key in ('paver_sha256', 'executable_sha256'):
                if game.get(key) and not re.fullmatch('[0-9a-f]{64}', game[key]):
                    raise ValueError('Invalid semantic export game digest.')
            records = meta["packages"]
            if not isinstance(records, list) or not 1 <= len(records) <= 128:
                raise ValueError("Invalid semantic export contributor inventory.")
            packages, decoded, identities, used, logical_size = [], [], set(), {"semantic.json"}, 0
            for row in records:
                raise_if_cancelled(stop_event)
                if (not isinstance(row, dict) or set(row) != {"identity", "content", "artifact", "size"}
                        or type(row["size"]) is not int or not 0 < row["size"] <= MAX_TOTAL
                        or any(not isinstance(row[key], str) or not re.fullmatch("[0-9a-f]{64}", row[key])
                               for key in ("content", "artifact"))):
                    raise ValueError("Invalid semantic export contributor record.")
                name = f"packages/{row['artifact']}.cditem"
                data = _read_member(archive, name, stop_event)
                if len(data) != row["size"] or digest(data) != row["artifact"]:
                    raise ValueError("Semantic export contributor checksum or size mismatch.")
                package = read_package(data, stop_event=stop_event, cache=package_cache)
                if (package.identity != row["identity"] or package.digest != row["content"]
                        or package.identity in identities):
                    raise ValueError("Contradictory or duplicate semantic export contributor identity.")
                logical_size += len(canonical(package_metadata(package))) + sum(map(len, package.blobs.values()))
                if logical_size > MAX_TOTAL:
                    raise ValueError("Semantic export contributors exceed the selected-package size limit.")
                identities.add(package.identity)
                used.add(name)
                packages.append(data)
                decoded.append(package)
            # Exact provider pins and exported-reference requirements are owned by
            # the original package graph, including source-equal assignments.
            resolve_package_graph(decoded, stop_event=stop_event)
            bindings = _validate_registry(meta["bindings"])
            if set(bindings["items"]) != identities:
                raise ValueError("Semantic export bindings do not match its contributors.")
            for package in decoded:
                row = bindings["items"][package.identity]
                if row["layer"] is not None or row["digest"] != package.digest or row["title"] != package.title:
                    raise ValueError("Semantic export contributor bindings disagree with retained intent.")
            witnesses = meta["witnesses"]
            if not isinstance(witnesses, dict) or set(witnesses) != {"payloads", "indexes"}:
                raise ValueError("Missing semantic export source witnesses.")
            for kind in ("payloads", "indexes"):
                rows = witnesses[kind]
                if not isinstance(rows, list) or not 1 <= len(rows) <= 65536:
                    raise ValueError("Invalid semantic export source witness inventory.")
                seen = set()
                for row in rows:
                    if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
                        raise ValueError("Invalid semantic export source witness.")
                    path = _semantic_path(row["path"], index=kind == "indexes")
                    _semantic_hash_record({key: row[key] for key in ("size", "sha256")})
                    if path in seen:
                        raise ValueError("Duplicate semantic export source path.")
                    seen.add(path)
            source_hashes = {row["path"]: row["sha256"] for row in witnesses["payloads"]}
            for package in decoded:
                if any(source_hashes.get(path) != checksum for path, checksum in package.dependencies.items()):
                    raise ValueError("Semantic export dependencies disagree with original source witnesses.")
            rows = meta["files"]
            if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
                raise ValueError("Invalid semantic export output inventory.")
            files, originals, paths, cache = [], {}, set(), {}
            output_size = baseline_size = 0
            def payload(record):
                record = _semantic_hash_record(record)
                name = "payloads/" + record["sha256"]
                if name not in cache:
                    cache[name] = _read_member(archive, name, stop_event)
                data = cache[name]
                if len(data) != record["size"] or digest(data) != record["sha256"]:
                    raise ValueError("Semantic export payload checksum or size mismatch.")
                used.add(name)
                return data
            for row in rows:
                raise_if_cancelled(stop_event)
                if not isinstance(row, dict) or set(row) != {"path", "size", "sha256", "flags", "baseline"}:
                    raise ValueError("Invalid semantic export output record.")
                path = _semantic_path(row["path"])
                if path in paths or type(row["flags"]) is not int or not 0 <= row["flags"] <= 0xffffffff:
                    raise ValueError("Duplicate semantic export payload path or invalid flags.")
                paths.add(path)
                data = payload({key: row[key] for key in ("size", "sha256")})
                original = None if row["baseline"] is None else payload(row["baseline"])
                output_size += len(data)
                baseline_size += len(original) if original is not None else 0
                if output_size > MAX_TOTAL or baseline_size > MAX_BASELINE_BYTES:
                    raise ValueError('Semantic export logical output or baseline size limit exceeded.')
                if original is not None and path != 'meta/0.pathc' and source_hashes.get(path) != digest(original):
                    raise ValueError("Semantic export baseline disagrees with its original source witness.")
                files.append((path, data, row["flags"]))
                originals[path] = original
            if set(names) != used:
                raise ValueError("Semantic export contains undeclared or unreferenced entries.")
            return SemanticExport(tuple(packages), tuple(files), originals, bindings,
                                  meta["compiler"], witnesses, game, artifact_digest=digest(raw))
    except (zipfile.BadZipFile, KeyError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError(f"Invalid semantic export: {error}") from error


def read_semantic_export(source, *, stop_event=None, package_cache=None) -> SemanticExport | None:
    from dataclasses import replace
    from cdmw.services.independent_item_package import MAX_TOTAL
    if isinstance(source, bytes):
        return _read_semantic_bytes(source, stop_event=stop_event, package_cache=package_cache)
    path = semantic_export_path(source)
    if path is None:
        return None
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("Linked semantic export files are unsupported.")
    if path.stat().st_size > MAX_TOTAL + MAX_METADATA_BYTES:
        raise ValueError("The semantic export exceeds the supported size.")
    if path.name.casefold() != SEMANTIC_EXPORT_FILE:
        # This is only dispatch, not admission. Ordinary packages are fully
        # verified by their owner. Avoid reading their complete artifact merely
        # to discover that their central directory has no semantic envelope.
        raise_if_cancelled(stop_event)
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if 'semantic.json' not in names and 'item.json' in names:
                    return None
        except zipfile.BadZipFile as error:
            raise ValueError(f'Invalid semantic export: {error}') from error
    before = hash_file(path, stop_event)
    raw = path.read_bytes()
    if digest(raw) != before:
        raise ValueError("The semantic export changed while reading.")
    value = _read_semantic_bytes(raw, required=path.name.casefold() == SEMANTIC_EXPORT_FILE,
                               stop_event=stop_event, package_cache=package_cache)
    if value is None:
        return None
    folder = Path(source) if Path(source).is_dir() else None
    value = replace(value, source=path, folder=folder)
    value.validate(stop_event)
    return value


def write_semantic_export(root, export: SemanticExport, *, stop_event=None) -> tuple[Path, ...]:
    """Write into the existing directory publisher's staging area, with readback."""
    from cdmw.core.atomic_file import atomic_binary_writer
    from cdmw.services.independent_item_package import MAX_TOTAL, canonical, read_package
    root = Path(root)
    export.validate(stop_event)
    if (sum(len(data) for _, data, _ in export.files) > MAX_TOTAL
            or sum(len(data) for data in export.originals.values() if data is not None) > MAX_BASELINE_BYTES):
        raise ValueError('Semantic export logical output or baseline size limit exceeded.')
    members, packages, files = {}, [], []
    def record(data):
        if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
            raise ValueError("Semantic export payload exceeds its supported size.")
        checksum = digest(data)
        members["payloads/" + checksum] = data
        return {"size": len(data), "sha256": checksum}
    for data in export.packages:
        package = read_package(data, stop_event=stop_event)
        checksum = digest(data)
        members[f"packages/{checksum}.cditem"] = data
        packages.append({"identity": package.identity, "content": package.digest,
                         "artifact": checksum, "size": len(data)})
    if set(export.originals) != {path for path, _, _ in export.files}:
        raise ValueError("Semantic export originals do not match every emitted payload.")
    for path, data, flags in export.files:
        raise_if_cancelled(stop_event)
        original = export.originals[path]
        files.append({"path": path, **record(data), "flags": flags,
                      "baseline": None if original is None else record(original)})
    meta = {"format": SEMANTIC_EXPORT_FORMAT, "version": SEMANTIC_EXPORT_VERSION,
            "requires": {"export.semantic": 1}, "compiler": export.compiler,
            "target_game": export.target_game, "packages": packages, "files": files,
            "bindings": export.bindings, "witnesses": export.witnesses}
    data = canonical(meta)
    if len(data) > MAX_METADATA_BYTES or sum(map(len, members.values())) > MAX_TOTAL:
        raise ValueError("The semantic export exceeds the supported size.")
    members["semantic.json"] = data
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, data in sorted(members.items()):
            raise_if_cancelled(stop_event)
            with archive.open(name, "w") as target:
                for offset in range(0, len(data), 1024 * 1024):
                    raise_if_cancelled(stop_event)
                    target.write(data[offset:offset + 1024 * 1024])
    raw = stream.getvalue()
    _read_semantic_bytes(raw, required=True, stop_event=stop_event)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("Semantic export staging must be empty.")
    destination = root / SEMANTIC_EXPORT_FILE
    with atomic_binary_writer(destination) as target:
        for offset in range(0, len(raw), 1024 * 1024):
            raise_if_cancelled(stop_event)
            target.write(raw[offset:offset + 1024 * 1024])
        raise_if_cancelled(stop_event)
    verified = read_semantic_export(root, stop_event=stop_event)
    if verified is None or verified.artifact_digest != digest(raw):
        raise ValueError("Semantic export failed final on-disk readback.")
    export.validate(stop_event)
    return (destination,)
