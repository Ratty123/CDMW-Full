"""Owned-file validation and atomic publication for immutable Rust previews."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import replace
from functools import wraps
from pathlib import Path, PurePosixPath
from uuid import uuid4

from cdmw.domain.cancellation import RunCancelled

# One SHA-256 per file per process. Preview files are immutable once
# published: a file verified here is trusted again while it keeps its volume,
# file id, size and modification time. Hard links share one file id, so a
# promoted package that links its direct package's files reuses those checks.
# A verification is remembered only when it happened at least
# _VERIFIED_MIN_AGE_NS after the file's last write; a same-size rewrite inside
# one timestamp tick keeps its time, and a later rewrite never can.
_VERIFIED_FILE_LIMIT = 65_536
_VERIFIED_MIN_AGE_NS = 100_000_000
# Volumes whose times are whole 10 ms steps (FAT, exFAT) need a wider margin.
_VERIFIED_COARSE_STEP_NS = 10_000_000
_VERIFIED_COARSE_MIN_AGE_NS = 3_000_000_000
_verified_files_lock = threading.Lock()
_verified_files: "OrderedDict[tuple[int, int, int, int], str]" = OrderedDict()


def _verified_file_key(stat_result: os.stat_result) -> tuple[int, int, int, int] | None:
    inode = int(getattr(stat_result, "st_ino", 0) or 0)
    if inode == 0:
        # No stable file id on this filesystem: nothing is remembered.
        return None
    return (int(stat_result.st_dev), inode, int(stat_result.st_size), int(stat_result.st_mtime_ns))


def verified_preview_file_digest(stat_result: os.stat_result) -> str | None:
    """The SHA-256 this process verified for the file, if it is unchanged."""

    key = _verified_file_key(stat_result)
    if key is None:
        return None
    with _verified_files_lock:
        digest = _verified_files.get(key)
        if digest is not None:
            _verified_files.move_to_end(key)
        return digest


def remember_verified_preview_file(
    stat_result: os.stat_result,
    digest: str,
    verified_at_ns: int,
    *,
    path: Path | str | None = None,
) -> None:
    """Remember a digest computed from the file as ``stat_result`` described it.

    ``verified_at_ns`` is when its bytes started to be read. With ``path`` the
    file is checked again, so a change while it was read is never remembered.
    """

    key = _verified_file_key(stat_result)
    if key is None or len(str(digest or "")) != 64:
        return
    if path is not None:
        try:
            if _verified_file_key(os.stat(path)) != key:
                return
        except OSError:
            return
    mtime = key[3]
    margin = _VERIFIED_COARSE_MIN_AGE_NS if mtime % _VERIFIED_COARSE_STEP_NS == 0 else _VERIFIED_MIN_AGE_NS
    if verified_at_ns - mtime < margin:
        return
    with _verified_files_lock:
        _verified_files[key] = str(digest).upper()
        _verified_files.move_to_end(key)
        while len(_verified_files) > _VERIFIED_FILE_LIMIT:
            _verified_files.popitem(last=False)


def forget_verified_preview_files() -> None:
    """Start from an empty memo (tests)."""

    with _verified_files_lock:
        _verified_files.clear()


def atomic_preview_publication(builder):
    """Build in an owned sibling directory; expose a package only on success."""

    @wraps(builder)
    def publish(*args, **kwargs):
        output = kwargs.get("output_package_dir")
        root = Path(kwargs.get("output_root") or Path(tempfile.gettempdir()) / "cdmw_rust_preview")
        destination = Path(output) if output is not None else root / f"package_{uuid4().hex}"
        destination = destination.absolute()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        staging = Path(tempfile.mkdtemp(prefix=".rust-preview-", dir=destination.parent))
        package_dir = staging / "package"
        try:
            result = builder(*args, **{**kwargs, "output_package_dir": package_dir})
            cancelled = kwargs.get("cancelled")
            if cancelled is not None and cancelled():
                raise RunCancelled("preview package preparation cancelled.")
            # Windows rename refuses an existing destination. Never overwrite a
            # resident/cached package, including a concurrent publisher's output.
            published = replace(
                result,
                package_dir=destination,
                manifest_path=destination / result.manifest_path.relative_to(package_dir),
                status_path=destination / result.status_path.relative_to(package_dir),
                output_dir=destination / result.output_dir.relative_to(package_dir),
                edit_operations_path=destination / result.edit_operations_path.relative_to(package_dir),
            )
            os.rename(package_dir, destination)
            return published
        finally:
            # Only this freshly allocated sibling is owned by this invocation.
            shutil.rmtree(staging)

    return publish


def validate_preview_files(package_dir: Path, payload: dict, *, hash_unverified: bool = True) -> None:
    """Reject incomplete, changed, escaping or writable cached preview inputs.

    With ``hash_unverified=False`` (the checks that run on the UI thread) no
    file content is read: a file this process has not verified is accepted on
    structure, size and containment, since the worker that produced or found
    the package and the helper that loads it both verify every digest.
    """

    root = package_dir.resolve(strict=True)
    if not str(payload.get("session_id", "")).strip() or int(payload.get("process_generation", 0)) <= 0:
        raise ValueError("preview session identity is missing")
    policy = payload.get("output_policy")
    if not isinstance(policy, dict) or policy.get("policy") != "read_only_preview" or policy.get("archive_writes") is not False:
        raise ValueError("preview output policy must be read-only")
    reference_fields = {"path", "data_type", "count", "byte_length", "sha256", "content_type"}
    for name in ("document", "channels"):
        value = payload.get(name)
        if not isinstance(value, dict) or not reference_fields <= value.keys():
            raise ValueError(f"preview {name} reference is missing")

    for group in ("textures", "effect_textures"):
        for texture in payload.get(group, ()):
            value = texture.get("file") if isinstance(texture, dict) else None
            if not isinstance(value, dict) or not reference_fields <= value.keys():
                raise ValueError(f"preview {group} file reference is missing")

    verified = {}

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if "path" in value and {"byte_length", "data_type", "content_type"}.intersection(value):
                if not reference_fields <= value.keys():
                    raise ValueError("preview resource reference is incomplete")
                if not isinstance(value["count"], int) or isinstance(value["count"], bool) or value["count"] < 0:
                    raise ValueError("preview resource count is invalid")
                name = str(value["path"])
                relative = PurePosixPath(name.replace("\\", "/"))
                if not name or relative.is_absolute() or any(part in {"..", "."} or ":" in part for part in relative.parts):
                    raise ValueError("preview resource path is not contained")
                candidate = (root / Path(*relative.parts)).resolve(strict=True)
                candidate.relative_to(root)
                size = int(value["byte_length"])
                digest = str(value["sha256"]).upper()
                identity = (size, digest)
                stat_result = candidate.stat()
                if size < 0 or size > 512 * 1024 * 1024 or stat_result.st_size != size:
                    raise ValueError("preview resource size does not match")
                if candidate in verified:
                    if verified[candidate] != identity:
                        raise ValueError("preview resource has conflicting identities")
                    return
                if len(digest) != 64:
                    raise ValueError("preview resource SHA-256 does not match")
                known = verified_preview_file_digest(stat_result)
                if known is not None:
                    if known != digest:
                        raise ValueError("preview resource SHA-256 does not match")
                elif hash_unverified:
                    verified_at_ns = time.time_ns()
                    with candidate.open("rb") as stream:
                        before = os.fstat(stream.fileno())
                        actual = hashlib.file_digest(stream, "sha256").hexdigest().upper()
                    if actual != digest:
                        raise ValueError("preview resource SHA-256 does not match")
                    remember_verified_preview_file(before, actual, verified_at_ns, path=candidate)
                verified[candidate] = identity
                if value.get("content_type") == "application/json" and hash_unverified:
                    # Geometry/channels JSON may contain additional references.
                    # The UI-thread check reads no content; the worker that
                    # verified this package already followed them.
                    with candidate.open(encoding="utf-8") as stream:
                        nested = json.load(stream)
                    if not isinstance(nested, dict):
                        raise ValueError("preview JSON resource is not an object")
                    visit(nested)
            else:
                for item in value.values():
                    visit(item)

    visit(payload)
