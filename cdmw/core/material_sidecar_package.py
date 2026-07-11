"""Cancellable, transactional material-sidecar package export."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import tempfile
import threading
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from uuid import uuid4

from cdmw.core.atomic_file import atomic_publish_directory
from cdmw.core.common import raise_if_cancelled
from cdmw.core.mod_package import (
    MeshLooseModFile,
    ModPackageExportOptions,
    normalize_mod_package_payload_path,
    resolve_mod_package_root,
    write_mesh_loose_mod_package_metadata,
)
from cdmw.models import ArchiveEntry, ModPackageInfo


_WRITE_CHUNK_SIZE = 1024 * 1024
_CANCEL_MESSAGE = "Material sidecar package export cancelled."


@dataclasses.dataclass(slots=True, frozen=True)
class MaterialSidecarExportResult:
    package_root: Path
    written_files: tuple[Path, ...]
    metadata_files: tuple[Path, ...]


def _remove_path(path: Path, *, ignore_errors: bool = False) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.exists():
            shutil.rmtree(path)
    except OSError:
        if not ignore_errors:
            raise


def _validated_package_root(parent_root: Path, package_info: ModPackageInfo) -> Path:
    resolved_parent = parent_root.expanduser().resolve()
    package_root = resolve_mod_package_root(resolved_parent, package_info).resolve()
    if package_root == resolved_parent or resolved_parent not in package_root.parents:
        raise ValueError(f"Refusing to publish material sidecar package outside the export root: {package_root}")
    if package_root.exists() and not package_root.is_dir():
        raise NotADirectoryError(package_root)
    package_root.parent.mkdir(parents=True, exist_ok=True)
    return package_root


def _write_text(path: Path, text: str, stop_event: threading.Event | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for offset in range(0, len(text), _WRITE_CHUNK_SIZE):
            raise_if_cancelled(stop_event, _CANCEL_MESSAGE)
            handle.write(text[offset : offset + _WRITE_CHUNK_SIZE])
    raise_if_cancelled(stop_event, _CANCEL_MESSAGE)


def _write_bytes(path: Path, payload: bytes, stop_event: threading.Event | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    view = memoryview(payload)
    with path.open("wb") as handle:
        for offset in range(0, len(view), _WRITE_CHUNK_SIZE):
            raise_if_cancelled(stop_event, _CANCEL_MESSAGE)
            handle.write(view[offset : offset + _WRITE_CHUNK_SIZE])
    raise_if_cancelled(stop_event, _CANCEL_MESSAGE)


def _publish_fresh_package(staged_root: Path, package_root: Path) -> None:
    """Publish the directory and optional sibling ZIP with rollback."""
    staged_zip = staged_root.with_suffix(".zip")
    package_zip = package_root.with_suffix(".zip")
    if package_zip.exists() and not package_zip.is_file():
        raise IsADirectoryError(package_zip)
    nonce = uuid4().hex
    backup_root = package_root.with_name(f".{package_root.name}.{nonce}.bak")
    backup_zip = package_zip.with_name(f".{package_zip.name}.{nonce}.bak")
    root_backed_up = False
    zip_backed_up = False
    root_published = False
    zip_published = False
    try:
        if package_root.exists():
            os.replace(package_root, backup_root)
            root_backed_up = True
        if package_zip.exists():
            os.replace(package_zip, backup_zip)
            zip_backed_up = True
        atomic_publish_directory(staged_root, package_root)
        root_published = True
        if staged_zip.exists():
            os.replace(staged_zip, package_zip)
            zip_published = True
    except Exception:
        if zip_published:
            package_zip.unlink(missing_ok=True)
        if root_published:
            _remove_path(package_root)
        if zip_backed_up and backup_zip.exists():
            os.replace(backup_zip, package_zip)
        if root_backed_up and backup_root.exists():
            os.replace(backup_root, package_root)
        raise
    else:
        if root_backed_up:
            _remove_path(backup_root, ignore_errors=True)
        if zip_backed_up:
            _remove_path(backup_zip, ignore_errors=True)


def export_material_sidecar_mod_package(
    *,
    edited_entry: ArchiveEntry,
    edited_text: str,
    related_entries: Sequence[ArchiveEntry],
    parent_root: Path,
    package_info: ModPackageInfo,
    export_options: ModPackageExportOptions | None = None,
    create_no_encrypt_file: bool = True,
    read_entry_bytes: Callable[[ArchiveEntry], bytes],
    on_log: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> MaterialSidecarExportResult:
    package_root = _validated_package_root(parent_root, package_info)
    raise_if_cancelled(stop_event, _CANCEL_MESSAGE)
    staging_parent = Path(
        tempfile.mkdtemp(prefix=f".{package_root.name}.", suffix=".tmp", dir=package_root.parent)
    )
    staged_root = staging_parent / "package"

    def log(message: str) -> None:
        if on_log is not None:
            on_log(message)

    try:
        written_files: list[Path] = []
        file_rows: list[MeshLooseModFile] = []
        written_virtual_paths: set[str] = set()

        edited_payload_path = normalize_mod_package_payload_path(edited_entry.path).as_posix()
        edited_target = staged_root.joinpath(*PurePosixPath(edited_payload_path).parts)
        _write_text(edited_target, edited_text, stop_event)
        written_files.append(edited_target)
        written_virtual_paths.add(edited_payload_path.lower())
        file_rows.append(
            MeshLooseModFile(
                path=edited_payload_path,
                package_group=edited_entry.pamt_path.parent.name,
                format=PurePosixPath(edited_payload_path).suffix.lstrip(".").lower(),
                generated_from=edited_entry.path,
                note="Edited material sidecar generated from archive XML values.",
            )
        )
        log(f"Wrote edited material sidecar: {edited_payload_path}")

        for related_entry in related_entries:
            raise_if_cancelled(stop_event, _CANCEL_MESSAGE)
            if related_entry.path == edited_entry.path:
                continue
            payload_path = normalize_mod_package_payload_path(related_entry.path).as_posix()
            if not payload_path or payload_path.lower() in written_virtual_paths:
                continue
            payload = read_entry_bytes(related_entry)
            raise_if_cancelled(stop_event, _CANCEL_MESSAGE)
            target_path = staged_root.joinpath(*PurePosixPath(payload_path).parts)
            _write_bytes(target_path, payload, stop_event)
            written_files.append(target_path)
            written_virtual_paths.add(payload_path.lower())
            file_rows.append(
                MeshLooseModFile(
                    path=payload_path,
                    package_group=related_entry.pamt_path.parent.name,
                    format=PurePosixPath(payload_path).suffix.lstrip(".").lower(),
                    generated_from=edited_entry.path,
                    note="Related material companion copied from archive.",
                )
            )
            log(f"Copied related material file: {payload_path}")

        manifest_path = staged_root / "material_sidecar_edits.json"
        _write_text(
            manifest_path,
            json.dumps(
                {
                    "edited_entry": edited_entry.path,
                    "related_entries": [entry.path for entry in related_entries],
                    "file_count": len(file_rows),
                },
                indent=2,
            ),
            stop_event,
        )
        raise_if_cancelled(stop_event, _CANCEL_MESSAGE)
        metadata_files = write_mesh_loose_mod_package_metadata(
            staged_root,
            package_info,
            assets=(),
            files=file_rows,
            include_paired_lod=False,
            export_options=export_options,
            create_no_encrypt_file=create_no_encrypt_file,
            stop_event=stop_event,
        )
        metadata_files.append(manifest_path)
        raise_if_cancelled(stop_event, _CANCEL_MESSAGE)
        _publish_fresh_package(staged_root, package_root)
        return MaterialSidecarExportResult(
            package_root=package_root,
            written_files=tuple(package_root / path.relative_to(staged_root) for path in written_files),
            metadata_files=tuple(package_root / path.relative_to(staged_root) for path in metadata_files),
        )
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


__all__ = ["MaterialSidecarExportResult", "export_material_sidecar_mod_package"]
