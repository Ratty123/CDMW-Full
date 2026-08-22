"""Shared archive-group overlay package writer."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Tuple

from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.core.papgt_format import papgt_with_directory
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.archive_overlay_install import (
    OVERLAY_DIRECTORY_FIRST,
    _processed_payload,
    overlay_directory_name,
)


@dataclass(frozen=True, slots=True)
class ArchiveOverlayPackageResult:
    package_root: Path
    group: str
    file_count: int
    payload_bytes: int
    paths: Tuple[str, ...]
    metadata_files: Tuple[str, ...]
    mount_list_written: bool


def export_archive_overlay_package(
    requests: Sequence[ArchivePatchRequest],
    additions: Sequence[ArchiveAddRequest] = (),
    *,
    package_root: Path,
    group: str = "",
    game_root: Optional[Path] = None,
    metadata_files: Iterable[tuple[str, bytes]] = (),
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: threading.Event | None = None,
) -> ArchiveOverlayPackageResult:
    """Write immutable patch payloads as one manager-mountable archive group."""

    root = Path(package_root)
    files: dict[str, OverlayFile] = {}
    for request in requests:
        raise_if_cancelled(stop_event, "Overlay package export cancelled while composing patches.")
        entry = request.entry
        path = str(entry.path).replace("\\", "/").strip("/")
        files[path] = OverlayFile(
            path=path,
            payload=_processed_payload(
                request.payload_data,
                compression_type=int(entry.compression_type),
                encrypted=bool(entry.encrypted),
                basename=str(entry.basename),
            ),
            orig_size=len(request.payload_data),
            flags=int(entry.flags),
        )
    for addition in additions:
        raise_if_cancelled(stop_event, "Overlay package export cancelled while composing additions.")
        path = str(addition.path).replace("\\", "/").strip("/")
        files[path] = OverlayFile(
            path=path,
            payload=_processed_payload(
                addition.payload_data,
                compression_type=int(addition.compression_type),
                encrypted=bool(addition.encryption_type),
                basename=str(addition.basename),
            ),
            orig_size=len(addition.payload_data),
            flags=int(addition.flags),
        )
    if not files:
        raise ValueError("An archive overlay package needs at least one file.")

    name = str(group or "") or (
        overlay_directory_name(Path(game_root))
        if game_root is not None and Path(game_root).is_dir()
        else f"{OVERLAY_DIRECTORY_FIRST:04d}"
    )
    built = build_overlay_archive(sorted(files.values(), key=lambda item: item.path), on_log=on_log)
    raise_if_cancelled(stop_event, "Overlay package export cancelled before publishing.")
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(directory / "0.paz", built.paz_bytes)
    atomic_write_bytes(directory / "0.pamt", built.pamt_bytes)

    mount_written = False
    if game_root is not None:
        source = Path(game_root) / "meta" / "0.papgt"
        if source.is_file():
            mounted = papgt_with_directory(source.read_bytes(), name, built.pamt_checksum, first=True)
            (root / "meta").mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(root / "meta" / "0.papgt", mounted)
            mount_written = True

    written: list[str] = []
    for relative, payload in metadata_files:
        raise_if_cancelled(stop_event, "Overlay package export cancelled before metadata publication.")
        normalized = Path(str(relative).replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"Overlay package metadata path escapes the package: {relative}")
        target = root / normalized
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, bytes(payload))
        written.append(normalized.as_posix())

    if on_log is not None:
        on_log(
            f"Wrote {name}/0.pamt and 0.paz: {len(files)} file(s), "
            f"{len(built.paz_bytes):,} bytes."
        )
    return ArchiveOverlayPackageResult(
        package_root=root,
        group=name,
        file_count=len(files),
        payload_bytes=len(built.paz_bytes),
        paths=tuple(sorted(files)),
        metadata_files=tuple(written),
        mount_list_written=mount_written,
    )


__all__ = ["ArchiveOverlayPackageResult", "export_archive_overlay_package"]
