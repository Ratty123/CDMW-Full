"""Owned-file validation and atomic publication for immutable Rust previews."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import replace
from functools import wraps
from pathlib import Path, PurePosixPath
from uuid import uuid4

from cdmw.domain.cancellation import RunCancelled


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
                raise RunCancelled("Rust preview package preparation cancelled.")
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


def validate_preview_files(package_dir: Path, payload: dict) -> None:
    """Reject incomplete, changed, escaping or writable cached preview inputs."""

    root = package_dir.resolve(strict=True)
    if not str(payload.get("session_id", "")).strip() or int(payload.get("process_generation", 0)) <= 0:
        raise ValueError("Rust preview session identity is missing")
    policy = payload.get("output_policy")
    if not isinstance(policy, dict) or policy.get("policy") != "read_only_preview" or policy.get("archive_writes") is not False:
        raise ValueError("Rust preview output policy must be read-only")
    reference_fields = {"path", "data_type", "count", "byte_length", "sha256", "content_type"}
    for name in ("document", "channels"):
        value = payload.get(name)
        if not isinstance(value, dict) or not reference_fields <= value.keys():
            raise ValueError(f"Rust preview {name} reference is missing")

    for group in ("textures", "effect_textures"):
        for texture in payload.get(group, ()):
            value = texture.get("file") if isinstance(texture, dict) else None
            if not isinstance(value, dict) or not reference_fields <= value.keys():
                raise ValueError(f"Rust preview {group} file reference is missing")

    verified = {}

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if "path" in value and {"byte_length", "data_type", "content_type"}.intersection(value):
                if not reference_fields <= value.keys():
                    raise ValueError("Rust preview resource reference is incomplete")
                if not isinstance(value["count"], int) or isinstance(value["count"], bool) or value["count"] < 0:
                    raise ValueError("Rust preview resource count is invalid")
                name = str(value["path"])
                relative = PurePosixPath(name.replace("\\", "/"))
                if not name or relative.is_absolute() or any(part in {"..", "."} or ":" in part for part in relative.parts):
                    raise ValueError("Rust preview resource path is not contained")
                candidate = (root / Path(*relative.parts)).resolve(strict=True)
                candidate.relative_to(root)
                size = int(value["byte_length"])
                digest = str(value["sha256"]).upper()
                identity = (size, digest)
                if size < 0 or size > 512 * 1024 * 1024 or candidate.stat().st_size != size:
                    raise ValueError("Rust preview resource size does not match")
                if candidate in verified:
                    if verified[candidate] != identity:
                        raise ValueError("Rust preview resource has conflicting identities")
                    return
                with candidate.open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest().upper()
                if len(digest) != 64 or actual != digest:
                    raise ValueError("Rust preview resource SHA-256 does not match")
                verified[candidate] = identity
                if value.get("content_type") == "application/json":
                    # Geometry/channels JSON may contain additional references.
                    with candidate.open(encoding="utf-8") as stream:
                        nested = json.load(stream)
                    if not isinstance(nested, dict):
                        raise ValueError("Rust preview JSON resource is not an object")
                    visit(nested)
            else:
                for item in value.values():
                    visit(item)

    visit(payload)
