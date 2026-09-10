"""Portable game identity and original payloads for reviewing exported mods.

These files are package metadata, never game payloads. Unknown originals remain
unknown; a mod's current bytes must never be promoted to its original baseline.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
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
        text = raw.decode("utf-8", errors="ignore")
        result["build"] = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())[:240]
    executable = resolve_crimson_desert_executable(root)
    if executable is not None:
        result["executable_sha256"] = hash_file(executable, stop_event)
    return result


def build_status(recorded: Mapping | None, current: Mapping) -> str:
    recorded = recorded if isinstance(recorded, Mapping) else {}
    compared = False
    for key in ("executable_sha256", "paver_sha256", "build"):
        old, new = recorded.get(key), current.get(key)
        if isinstance(old, str) and isinstance(new, str) and old and new:
            compared = True
            if old != new:
                return "changed"
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
    source = root / COMPATIBILITY_FILE
    if not source.exists():
        return None
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
           "capture_patch_compatibility", "compatibility_from_payloads", "digest", "game_identity",
           "hash_file", "payload_path", "read_compatibility", "write_compatibility"]
