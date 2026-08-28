"""Install a mutation plan as an archive directory of its own, leaving the shipped ones
alone.

The patcher route writes the plan's payloads into the archives the game shipped: every
touched `.paz` is backed up whole and re-checksummed, which for one new item is fifteen
files and 0.62 GB. This route writes the same payloads into a new directory beside them and
names that directory first in `meta/0.papgt`, which is where the game looks first. What
gets backed up is then the mount list and the texture registry, both of them under a
kilobyte, and what gets written is a few megabytes that were not there before.

Two things follow from the game taking the first directory that holds a path:

* the overlay has to carry every file the mods before it changed, not only the ones this
  plan touches, or mounting it first would hide them. Everything already in the workbench's
  own overlay is carried forward, and this plan's files replace their namesakes;
* the workbench has to read the archives in the same order the game does, or it would plan
  against a shipped table while the game reads the overlay's. `discover_pamt_files` orders
  its results by the mount list for that reason.
"""

from __future__ import annotations

import shutil
import threading
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, papgt_with_directory, parse_papgt
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest
from cdmw.domain.cancellation import raise_if_cancelled

__all__ = [
    "OVERLAY_DIRECTORY_FIRST",
    "OVERLAY_OWNER_MARKER",
    "OVERLAY_OWNER_BYTES",
    "OverlayInstallResult",
    "OverlayInstallPreparation",
    "apply_overlay_install",
    "install_overlay",
    "is_cdmw_overlay_directory",
    "overlay_directory_name",
    "prepare_overlay_install",
    "restore_last_overlay_install",
]

#: Where the workbench's own overlay directory starts looking for a free name. The shipped
#: install ends at 0035, and the game reads a directory only if the mount list names it, so
#: an unmounted 0036 left by something else is not in the way.
OVERLAY_DIRECTORY_FIRST = 36
OVERLAY_OWNER_MARKER = ".cdmw-new-item-overlay"
OVERLAY_OWNER_BYTES = b"CDMW New Item Studio overlay v1\n"


@dataclass(frozen=True, slots=True)
class OverlayInstallResult:
    """What an overlay install wrote."""

    directory: Path
    pamt_checksum: int
    file_count: int
    payload_bytes: int
    carried_forward: int
    backup_dir: Optional[Path]
    paths: Tuple[str, ...]
    receipt_path: Optional[Path] = None


@dataclass(frozen=True, slots=True)
class OverlayInstallPreparation:
    """Fully composed overlay bytes and the exact files an apply may touch."""

    package_root: Path
    directory_name: str
    directory: Path
    papgt_path: Path
    papgt_before: bytes
    papgt_after: bytes
    mount_list_before: Tuple[str, ...]
    mount_list_after: Tuple[str, ...]
    requested_paths: Tuple[str, ...]
    carried_forward_paths: Tuple[str, ...]
    all_paths: Tuple[str, ...]
    pamt_bytes: bytes
    paz_bytes: bytes
    pamt_checksum: int
    meta_files: Tuple[Tuple[str, bytes], ...]
    backup_targets: Tuple[Path, ...]
    created_files: Tuple[Path, ...]
    receipt_path: Path
    marker_path: Path
    rollback_files: Tuple[Tuple[Path, bytes], ...]


def prepare_overlay_install(
    requests: Sequence[ArchivePatchRequest],
    additions: Sequence[ArchiveAddRequest] = (),
    *,
    package_root: Path,
    meta_files: Iterable[Tuple[str, bytes]] = (),
    directory_name: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> OverlayInstallPreparation:
    """Compose and validate a complete overlay without changing the install."""

    root = Path(package_root).expanduser().resolve()
    papgt_path = root / "meta" / "0.papgt"
    if not papgt_path.is_file():
        raise FileNotFoundError(f"Could not find the archive mount list at {papgt_path}.")
    raise_if_cancelled(stop_event, "Overlay preparation cancelled before it started.")
    papgt_before = papgt_path.read_bytes()
    mounted_before = tuple(item.name for item in parse_papgt(papgt_before))
    mounted = set(mounted_before)
    existing = next(
        (
            item
            for item in sorted(mounted)
            if str(item).isdigit() and int(item) >= OVERLAY_DIRECTORY_FIRST
            and is_cdmw_overlay_directory(root / str(item))
        ),
        None,
    )
    name = directory_name or overlay_directory_name(root, existing=existing)
    directory = root / name
    if directory.exists() and not is_cdmw_overlay_directory(directory):
        raise ValueError(f"Archive directory {name} is not owned by CDMW and will not be reused.")
    carried = _existing_overlay_files(directory)
    if carried and on_log is not None:
        on_log(f"Carrying {len(carried)} file(s) forward from the overlay at {name}.")

    files: Dict[str, OverlayFile] = dict(carried)
    requested_paths: set[str] = set()
    for request in requests:
        raise_if_cancelled(stop_event, "Overlay preparation cancelled while composing patches.")
        entry = request.entry
        path = str(entry.path).replace("\\", "/").strip("/")
        requested_paths.add(path)
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
        raise_if_cancelled(stop_event, "Overlay preparation cancelled while composing additions.")
        path = str(addition.path).replace("\\", "/").strip("/")
        requested_paths.add(path)
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
    if not requested_paths:
        raise ValueError("An overlay install needs at least one requested file.")
    built = build_overlay_archive(sorted(files.values(), key=lambda item: item.path), on_log=on_log)
    papgt_after = papgt_with_directory(
        papgt_before,
        name,
        built.pamt_checksum,
        flags=PAPGT_DEFAULT_FLAGS,
        first=True,
    )
    mounted_after = tuple(item.name for item in parse_papgt(papgt_after))
    if not mounted_after or mounted_after[0] != name:
        raise RuntimeError("Prepared overlay mount list did not place the new group first")

    metas: list[tuple[str, bytes]] = []
    for relative, payload in meta_files:
        normalized = Path(str(relative).replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"Overlay metadata path escapes the package: {relative}")
        metas.append((normalized.as_posix(), bytes(payload)))
    receipt_path = root / ".cdmw" / "last-overlay-install.json"
    marker_path = directory / OVERLAY_OWNER_MARKER
    touched = [papgt_path, directory / "0.pamt", directory / "0.paz", marker_path]
    touched.extend(root / relative for relative, _payload in metas)
    touched.append(receipt_path)
    required_backup_targets = {papgt_path.resolve()}
    required_backup_targets.update((root / relative).resolve() for relative, _payload in metas)
    required_backup_targets.update(
        path.resolve()
        for path in (directory / "0.pamt", directory / "0.paz", marker_path, receipt_path)
        if path.is_file()
    )
    backup_targets = tuple(sorted(required_backup_targets))
    created_files = tuple(sorted({path.resolve() for path in touched if not path.exists()}))
    rollback_files = tuple((path.resolve(), path.read_bytes()) for path in touched if path.is_file())
    raise_if_cancelled(stop_event, "Overlay preparation cancelled before confirmation.")
    return OverlayInstallPreparation(
        package_root=root,
        directory_name=name,
        directory=directory,
        papgt_path=papgt_path,
        papgt_before=papgt_before,
        papgt_after=papgt_after,
        mount_list_before=mounted_before,
        mount_list_after=mounted_after,
        requested_paths=tuple(sorted(requested_paths)),
        carried_forward_paths=tuple(sorted(carried)),
        all_paths=tuple(sorted(files)),
        pamt_bytes=built.pamt_bytes,
        paz_bytes=built.paz_bytes,
        pamt_checksum=built.pamt_checksum,
        meta_files=tuple(metas),
        backup_targets=backup_targets,
        created_files=created_files,
        receipt_path=receipt_path,
        marker_path=marker_path,
        rollback_files=rollback_files,
    )


def _remove_created_overlay_files(preparation: OverlayInstallPreparation) -> None:
    for path in sorted(preparation.created_files, key=lambda item: len(item.parts), reverse=True):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
    for directory in (preparation.directory, preparation.receipt_path.parent):
        try:
            directory.rmdir()
        except OSError:
            pass


def _validate_staged_overlay(preparation: OverlayInstallPreparation) -> None:
    pamt_path = preparation.directory / "0.pamt"
    paz_path = preparation.directory / "0.paz"
    if pamt_path.read_bytes() != preparation.pamt_bytes or paz_path.read_bytes() != preparation.paz_bytes:
        raise RuntimeError("Staged overlay bytes do not match the confirmed preparation")
    entries = tuple(parse_archive_pamt(pamt_path))
    paths = tuple(sorted(str(entry.path).replace("\\", "/").strip("/") for entry in entries))
    if paths != preparation.all_paths:
        raise RuntimeError("Staged overlay index does not contain the complete prepared path set")
    payload_size = paz_path.stat().st_size
    if any(int(entry.offset) < 0 or int(entry.offset) + int(entry.comp_size) > payload_size for entry in entries):
        raise RuntimeError("Staged overlay index references bytes outside its payload")


def apply_overlay_install(
    preparation: OverlayInstallPreparation,
    *,
    confirmed: bool,
    backup: Optional[Callable[[Sequence[Path], str], Path]] = None,
    restore_backup: Optional[Callable[[Path], object]] = None,
    game_running: Optional[Callable[[], bool]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> OverlayInstallResult:
    """Apply one confirmed preparation, publishing the mount list last."""

    if not isinstance(preparation, OverlayInstallPreparation):
        raise TypeError("Overlay apply requires an OverlayInstallPreparation")
    if not confirmed:
        raise PermissionError("Overlay installation requires explicit confirmation")
    if game_running is not None and game_running():
        raise RuntimeError("The game is running; close it before installing an overlay")
    raise_if_cancelled(stop_event, "Overlay install cancelled before backup.")
    if preparation.papgt_path.read_bytes() != preparation.papgt_before:
        raise RuntimeError("The archive mount list changed after overlay preparation; prepare again")

    backup_dir: Optional[Path] = None
    if backup is not None:
        backup_dir = backup(
            preparation.backup_targets,
            f"Mount {preparation.directory_name} with {len(preparation.all_paths)} overlay file(s)",
        )
        if on_log is not None:
            on_log(f"Backup created: {backup_dir}")
    baseline_created: list[Path] = []
    try:
        raise_if_cancelled(stop_event, "Overlay install cancelled after backup.")
        for relative, _payload in preparation.meta_files:
            baseline = overlay_baseline_dir(preparation.package_root) / relative
            existed = baseline.is_file()
            kept = remember_overlay_baseline(preparation.package_root, relative)
            if kept is not None and not existed:
                baseline_created.append(kept)
        preparation.directory.mkdir(parents=True, exist_ok=True)
        _write_atomic(preparation.marker_path, OVERLAY_OWNER_BYTES)
        raise_if_cancelled(stop_event, "Overlay install cancelled after staging its owner marker.")
        _write_atomic(preparation.directory / "0.paz", preparation.paz_bytes)
        raise_if_cancelled(stop_event, "Overlay install cancelled after staging its payload.")
        _write_atomic(preparation.directory / "0.pamt", preparation.pamt_bytes)
        _validate_staged_overlay(preparation)
        raise_if_cancelled(stop_event, "Overlay install cancelled after staging its index.")
        for relative, payload in preparation.meta_files:
            target = preparation.package_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(target, payload)
            raise_if_cancelled(stop_event, "Overlay install cancelled while staging metadata.")
        receipt = {
            "format": "cdmw_overlay_install_receipt_v1",
            "created_at": time.time(),
            "package_root": str(preparation.package_root),
            "overlay_directory": preparation.directory_name,
            "mesh_paths": list(preparation.requested_paths),
            "mount_list_before": list(preparation.mount_list_before),
            "mount_list_after": list(preparation.mount_list_after),
            "carried_forward": list(preparation.carried_forward_paths),
            "backup_dir": str(backup_dir or ""),
            "backup_targets": [str(path) for path in preparation.backup_targets],
            "created_files": [str(path) for path in preparation.created_files],
        }
        preparation.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(
            preparation.receipt_path,
            (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        raise_if_cancelled(stop_event, "Overlay install cancelled before mount-list publication.")
        # Publication point: everything the mount list names is complete.
        _write_atomic(preparation.papgt_path, preparation.papgt_after)
    except BaseException as error:
        try:
            if backup_dir is not None and restore_backup is not None:
                restore_backup(backup_dir)
            else:
                for path, payload in preparation.rollback_files:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _write_atomic(path, payload)
        except Exception as rollback_error:
            raise RuntimeError(f"Overlay installation failed and its backup could not be restored: {rollback_error}") from error
        finally:
            _remove_created_overlay_files(preparation)
            for baseline in baseline_created:
                baseline.unlink(missing_ok=True)
        raise
    if on_log is not None:
        on_log(
            f"Mounted {preparation.directory_name} first in meta/0.papgt "
            f"({len(preparation.mount_list_after)} directories)."
        )
    return OverlayInstallResult(
        directory=preparation.directory,
        pamt_checksum=preparation.pamt_checksum,
        file_count=len(preparation.all_paths),
        payload_bytes=len(preparation.paz_bytes),
        carried_forward=len(preparation.carried_forward_paths),
        backup_dir=backup_dir,
        paths=preparation.all_paths,
        receipt_path=preparation.receipt_path,
    )


def restore_last_overlay_install(
    receipt_path: Path | str,
    *,
    confirmed: bool,
    restore_backup: Callable[[Path], object],
    game_running: Optional[Callable[[], bool]] = None,
) -> Path:
    """Restore one receipt and remove only paths that install created."""

    if not confirmed:
        raise PermissionError("Overlay restore requires explicit confirmation")
    if game_running is not None and game_running():
        raise RuntimeError("The game is running; close it before restoring an overlay")
    receipt = Path(receipt_path).expanduser().resolve()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != "cdmw_overlay_install_receipt_v1":
        raise ValueError("Unsupported overlay install receipt")
    root = Path(str(payload.get("package_root") or "")).expanduser().resolve()
    expected_receipt = root / ".cdmw" / "last-overlay-install.json"
    if receipt != expected_receipt:
        raise ValueError("Overlay receipt package root does not match the receipt location")
    overlay_name = str(payload.get("overlay_directory") or "")
    if not overlay_name.isdigit() or int(overlay_name) < OVERLAY_DIRECTORY_FIRST:
        raise ValueError("Overlay receipt names an invalid overlay directory")
    overlay_directory = root / overlay_name
    if not is_cdmw_overlay_directory(overlay_directory):
        raise ValueError("Overlay receipt does not name a CDMW-owned overlay directory")
    created_paths: list[Path] = []
    for raw in tuple(payload.get("created_files") or ()):
        path = Path(str(raw)).expanduser().resolve()
        if path != root and root not in path.parents:
            raise ValueError("Overlay receipt contains a created path outside the package root")
        created_paths.append(path)
    if len(set(created_paths)) != len(created_paths):
        raise ValueError("Overlay receipt contains duplicate created paths")
    allowed_created_paths = {
        (overlay_directory / "0.pamt").resolve(),
        (overlay_directory / "0.paz").resolve(),
        (overlay_directory / OVERLAY_OWNER_MARKER).resolve(),
        receipt,
    }
    unexpected_created = set(created_paths) - allowed_created_paths
    if unexpected_created:
        raise ValueError("Overlay receipt contains a created path not owned by the overlay install")
    backup_dir = Path(str(payload.get("backup_dir") or "")).expanduser().resolve()
    if not backup_dir.is_dir():
        raise FileNotFoundError("The overlay install backup named by the receipt is unavailable")
    raw_backup_targets = tuple(payload.get("backup_targets") or ())
    backup_targets: list[Path] = []
    for raw in raw_backup_targets:
        path = Path(str(raw)).expanduser().resolve()
        if path != root and root not in path.parents:
            raise ValueError("Overlay receipt contains a backup target outside the package root")
        backup_targets.append(path)
    if len(set(backup_targets)) != len(backup_targets):
        raise ValueError("Overlay receipt contains duplicate backup targets")
    if set(created_paths) != allowed_created_paths - set(backup_targets):
        raise ValueError("Overlay receipt targets do not match the install backup manifest")
    manifest_path = backup_dir / "backup_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("The overlay install backup manifest is unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(manifest_files, list):
        raise ValueError("The overlay install backup manifest is invalid")
    manifest_originals: set[Path] = set()
    for item in manifest_files:
        if not isinstance(item, dict):
            raise ValueError("The overlay install backup manifest contains an invalid file entry")
        original = Path(str(item.get("original_path") or "")).expanduser().resolve()
        backup_path = Path(str(item.get("backup_path") or "")).expanduser().resolve()
        if original != root and root not in original.parents:
            raise ValueError("The overlay install backup manifest targets a path outside the package root")
        if backup_path == backup_dir or backup_dir not in backup_path.parents or not backup_path.is_file():
            raise ValueError("The overlay install backup manifest names an unavailable backup file")
        if original in manifest_originals:
            raise ValueError("The overlay install backup manifest contains duplicate targets")
        manifest_originals.add(original)
    expected_originals = set(backup_targets) - set(created_paths)
    if manifest_originals != expected_originals:
        raise ValueError("Overlay receipt targets do not match the install backup manifest")
    if (root / "meta" / "0.papgt").resolve() not in manifest_originals:
        raise ValueError("The overlay install backup does not contain the archive mount list")
    restore_backup(backup_dir)
    for path in sorted(created_paths, key=lambda value: len(value.parts), reverse=True):
        path.unlink(missing_ok=True)
    for directory in (root / overlay_name, receipt.parent):
        try:
            directory.rmdir()
        except OSError:
            pass
    return root


def is_cdmw_overlay_directory(directory: Path) -> bool:
    """Whether ``directory`` carries the exact marker written by this installer."""

    marker = Path(directory) / OVERLAY_OWNER_MARKER
    try:
        return marker.is_file() and marker.read_bytes() == OVERLAY_OWNER_BYTES
    except OSError:
        return False


def overlay_directory_name(package_root: Path, *, existing: Optional[str] = None) -> str:
    """The directory the workbench's overlay lives in: the one it already mounted, else the
    first four-digit name at or after 0036 that no directory on disk uses."""

    root = Path(package_root)
    if existing and is_cdmw_overlay_directory(root / existing):
        return existing
    used = {child.name for child in root.iterdir() if child.is_dir()}
    for number in range(OVERLAY_DIRECTORY_FIRST, 10000):
        name = f"{number:04d}"
        if name not in used:
            return name
    raise ValueError("no free archive directory name is left under the package root")


def _processed_payload(payload: bytes, *, compression_type: int, encrypted: bool, basename: str) -> bytes:
    from cdmw.core import archive_patching as patching

    processed = patching._compress_archive_payload(bytes(payload), int(compression_type))
    if encrypted:
        processed = patching._crypt_archive_payload(processed, basename)
    return processed


def _existing_overlay_files(directory: Path) -> Dict[str, OverlayFile]:
    """What the workbench's overlay already holds, keyed by path, ready to carry forward."""

    if not is_cdmw_overlay_directory(directory):
        return {}
    pamt = directory / "0.pamt"
    paz = directory / "0.paz"
    if not pamt.is_file() or not paz.is_file():
        return {}
    payload = paz.read_bytes()
    out: Dict[str, OverlayFile] = {}
    for entry in parse_archive_pamt(pamt):
        chunk = payload[int(entry.offset) : int(entry.offset) + int(entry.comp_size)]
        if len(chunk) != int(entry.comp_size):
            continue
        out[str(entry.path)] = OverlayFile(path=str(entry.path), payload=chunk, orig_size=int(entry.orig_size), flags=int(entry.flags))
    return out


def install_overlay(
    requests: Sequence[ArchivePatchRequest],
    additions: Sequence[ArchiveAddRequest] = (),
    *,
    package_root: Path,
    meta_files: Iterable[Tuple[str, bytes]] = (),
    directory_name: Optional[str] = None,
    backup: Optional[Callable[[Sequence[Path], str], Path]] = None,
    restore_backup: Optional[Callable[[Path], object]] = None,
    game_running: Optional[Callable[[], bool]] = None,
    confirmed: bool = True,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> OverlayInstallResult:
    """Write `requests` and `additions` into an overlay directory and mount it first.

    `backup` is handed the files this is about to overwrite and returns where it put them;
    the shipped archives are not among them, because none of them is touched.
    """

    preparation = prepare_overlay_install(
        requests,
        additions,
        package_root=package_root,
        meta_files=meta_files,
        directory_name=directory_name,
        on_log=on_log,
        stop_event=stop_event,
    )
    return apply_overlay_install(
        preparation,
        confirmed=confirmed,
        backup=backup,
        restore_backup=restore_backup,
        game_running=game_running,
        on_log=on_log,
        stop_event=stop_event,
    )


def overlay_baseline_dir(package_root: Path) -> Path:
    """Where the workbench keeps the loose files an overlay overwrote, per install.

    `meta/0.pathc` is a loose file beside the archives rather than an entry inside one, so
    an overlay has nowhere to write it except in place, and removing the overlay has to put
    it back. The copy has to be the one from before the overlay existed: the workbench's
    own backup folders are not that, since the oldest of them is only as old as the first
    time this workbench touched the file, which may already have been a modified one.
    """

    import hashlib

    from cdmw.core.archive_patching import ARCHIVE_PATCH_BACKUP_ROOT

    fingerprint = hashlib.sha256(str(Path(package_root).resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return Path(ARCHIVE_PATCH_BACKUP_ROOT).parent / "overlay_baseline" / fingerprint


def remember_overlay_baseline(package_root: Path, relative: str) -> Optional[Path]:
    """Keep the file at `relative` as it is now, unless it is already kept. First write
    wins: what matters is the state before the overlay, not before the latest install."""

    root = Path(package_root)
    source = root / relative
    target = overlay_baseline_dir(root) / relative
    if target.is_file() or not source.is_file():
        return target if target.is_file() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(target, source.read_bytes())
    return target


def overlay_baseline_files(package_root: Path) -> Dict[str, Path]:
    """`{path relative to the package root: the copy from before the overlay}`."""

    base = overlay_baseline_dir(package_root)
    if not base.is_dir():
        return {}
    return {
        path.relative_to(base).as_posix(): path
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def forget_overlay_baseline(package_root: Path) -> None:
    """Drop the kept copies; the overlay they belonged to is gone."""

    import shutil

    shutil.rmtree(overlay_baseline_dir(package_root), ignore_errors=True)


def _write_atomic(path: Path, payload: bytes) -> None:
    """Write beside the target and move it into place, so a half-written archive never is."""

    temporary = path.with_suffix(path.suffix + ".cdmw_new")
    temporary.write_bytes(payload)
    temporary.replace(path)
