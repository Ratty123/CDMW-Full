"""Cancellable loose-target discovery for attachment placement."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cdmw.core.common import read_text_file_cancellable
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.mesh.session import PlacementLooseFileSpec, PlacementLooseRootPreparation
from cdmw.models import ArchiveEntry
from cdmw.workers.directory_scan_workers import DirectoryScanRequest, scan_directory_files


_SUPPORT_SUFFIXES = (
    ".prefab",
    ".hkx",
    ".hkt",
    ".paa",
    ".paa_metabin",
    ".motionblending",
    ".sockets.xml",
)
_TEXTURE_PATH_PATTERN = re.compile(
    r"""(?:_path|path)\s*=\s*["'](?P<path>[^"']+\.(?:dds|png))["']""",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AttachmentLoosePreflightRequest:
    request_id: int = 0
    target_entry: ArchiveEntry | None = None
    output_root_paths: tuple[str, ...] = ()
    raw_extract_root_path: str = ""
    preview_loose_file_path: str = ""
    material_sidecar_paths: tuple[str, ...] = ()
    item_icon_paths: tuple[str, ...] = ()
    support_paths: tuple[tuple[str, str], ...] = ()
    archive_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]] | None = None
    max_results: int = 100_000
    max_entries: int = 2_000_000


@dataclass(frozen=True, slots=True)
class AttachmentLoosePreflightResult:
    request_id: int
    roots: tuple[PlacementLooseRootPreparation, ...]


def _normalize_virtual(raw_path: object) -> str:
    normalized = str(raw_path or "").replace("\\", "/").strip().lstrip("/")
    return normalized[6:] if normalized.casefold().startswith("files/") else normalized


def _resolve_existing_directory(raw: object) -> Path | None:
    if not str(raw or "").strip():
        return None
    try:
        path = Path(str(raw)).expanduser().resolve()
    except OSError:
        return None
    return path if path.is_dir() else None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _discover_roots(
    request: AttachmentLoosePreflightRequest,
    *,
    stop_event: threading.Event | None,
) -> tuple[Path, ...]:
    entry = request.target_entry
    target_path = _normalize_virtual(getattr(entry, "path", ""))
    if not target_path:
        return ()
    raw_extract_root = _resolve_existing_directory(request.raw_extract_root_path)
    roots: list[Path] = []
    seen: set[str] = set()

    def has_target_file(root: Path) -> bool:
        relative = PurePosixPath(target_path)
        return (root / "files").joinpath(*relative.parts).is_file() or root.joinpath(*relative.parts).is_file()

    def add_root(raw_root: Path) -> None:
        raise_if_cancelled(stop_event, "Attachment loose-target scan cancelled.")
        try:
            root = raw_root.expanduser().resolve()
        except OSError:
            return
        if raw_extract_root is not None and _is_relative_to(root, raw_extract_root):
            return
        if re.fullmatch(r"\d{4}", root.name) and root.parent.name.strip().casefold() == "archive_extract":
            return
        key = str(root).casefold()
        if key in seen or not root.is_dir() or not has_target_file(root):
            return
        seen.add(key)
        roots.append(root)

    for raw_path in request.output_root_paths:
        raise_if_cancelled(stop_event, "Attachment loose-target scan cancelled.")
        base_root = _resolve_existing_directory(raw_path)
        if base_root is None:
            continue
        add_root(base_root)
        try:
            children = tuple(base_root.iterdir())
        except OSError:
            children = ()
        for child in children:
            raise_if_cancelled(stop_event, "Attachment loose-target scan cancelled.")
            try:
                is_directory = child.is_dir()
            except OSError:
                is_directory = False
            if is_directory:
                add_root(child)

    if request.preview_loose_file_path:
        try:
            loose_file = Path(request.preview_loose_file_path).expanduser().resolve()
        except OSError:
            loose_file = Path()
        if loose_file.is_file():
            for parent in loose_file.parents:
                add_root(parent.parent if parent.name.casefold() == "files" else parent)

    def modified_time(root: Path) -> float:
        try:
            return root.stat().st_mtime
        except OSError:
            return 0.0

    roots.sort(key=modified_time, reverse=True)
    return tuple(roots)


def _kind_for_support_action(action: object) -> str:
    normalized = str(action or "").casefold()
    if "prefab" in normalized:
        return "placement_target_prefab"
    if "hkx" in normalized or "hkt" in normalized or "physics" in normalized:
        return "placement_target_physics"
    if "paa" in normalized or "motion" in normalized:
        return "placement_target_motion"
    if "socket" in normalized:
        return "placement_target_socket"
    if "icon" in normalized:
        return "placement_target_icon"
    if "material" in normalized:
        return "placement_target_material"
    if "pac" in normalized or "model" in normalized:
        return "placement_target_model"
    return "placement_target_support"


def _prepare_root(
    request: AttachmentLoosePreflightRequest,
    root: Path,
    *,
    stop_event: threading.Event | None,
) -> PlacementLooseRootPreparation:
    entry = request.target_entry
    if not isinstance(entry, ArchiveEntry):
        return PlacementLooseRootPreparation(root)
    files_root = root / "files" if (root / "files").is_dir() else root
    archive_entries = request.archive_entries_by_normalized_path or {}
    specs: list[PlacementLooseFileSpec] = []
    seen: set[str] = set()

    def local_path_for_virtual(virtual_path: str) -> Path | None:
        normalized = _normalize_virtual(virtual_path)
        if not normalized:
            return None
        relative = PurePosixPath(normalized)
        for base in (files_root, root):
            raise_if_cancelled(stop_event, "Attachment loose-target scan cancelled.")
            candidate = base.joinpath(*relative.parts)
            if candidate.is_file():
                return candidate
        return None

    def add_virtual(virtual_path: object, kind: str) -> Path | None:
        normalized = _normalize_virtual(virtual_path)
        key = normalized.casefold()
        if not normalized:
            return None
        if key in seen:
            return local_path_for_virtual(normalized)
        local_path = local_path_for_virtual(normalized)
        if local_path is None:
            return None
        seen.add(key)
        matches = archive_entries.get(key, ())
        specs.append(
            PlacementLooseFileSpec(
                source_path=local_path,
                target_path=normalized,
                kind=kind,
                target_entry=matches[0] if matches else None,
                note=f"Preserve existing target loose file from {root.name}.",
            )
        )
        return local_path

    def add_local_path(local_path: Path, kind: str) -> None:
        try:
            base = files_root if _is_relative_to(local_path, files_root) else root
            relative = local_path.resolve().relative_to(base.resolve())
        except (OSError, ValueError):
            return
        normalized = _normalize_virtual(PurePosixPath(*relative.parts).as_posix())
        key = normalized.casefold()
        if not normalized or key in seen:
            return
        seen.add(key)
        matches = archive_entries.get(key, ())
        specs.append(
            PlacementLooseFileSpec(
                source_path=local_path,
                target_path=normalized,
                kind=kind,
                target_entry=matches[0] if matches else None,
                note=f"Preserve target-owned loose support file from {root.name}.",
            )
        )

    target_path = _normalize_virtual(entry.path)
    target_stem = PurePosixPath(target_path).stem
    add_virtual(target_path, "placement_target_model")
    sidecar_paths = list(request.material_sidecar_paths)
    if entry.extension in {".pac", ".pam", ".pamlod"}:
        sidecar_paths.insert(0, target_path.replace("/model/", "/modelproperty/") + "_xml")
    sidecar_files = tuple(
        local
        for sidecar_path in dict.fromkeys(sidecar_paths)
        if isinstance((local := add_virtual(sidecar_path, "placement_target_material")), Path)
    )
    for sidecar_file in sidecar_files:
        try:
            text = read_text_file_cancellable(
                sidecar_file,
                stop_event=stop_event,
                max_bytes=16 * 1024 * 1024,
                encoding="utf-8-sig",
                errors="ignore",
            )
        except OSError:
            continue
        for match in _TEXTURE_PATH_PATTERN.finditer(text):
            raise_if_cancelled(stop_event, "Attachment loose-target scan cancelled.")
            add_virtual(match.group("path"), "placement_target_texture")

    for icon_path in request.item_icon_paths:
        add_virtual(icon_path, "placement_target_icon")
    for icon_basename in (
        f"itemicon_prefab_{target_stem}.dds",
        f"itemicon_{target_stem}.dds",
        f"icon_prefab_{target_stem}.dds",
        f"icon_{target_stem}.dds",
    ):
        add_virtual(f"ui/texture/icon/{icon_basename}", "placement_target_icon")
    for action, support_path in request.support_paths:
        add_virtual(support_path, _kind_for_support_action(action))

    scan = scan_directory_files(
        DirectoryScanRequest(
            request_id=request.request_id,
            root=files_root,
            suffixes=_SUPPORT_SUFFIXES,
            max_results=request.max_results,
            max_entries=request.max_entries,
        ),
        stop_event=stop_event,
    )
    target_stem_key = target_stem.casefold()
    for candidate_index, candidate in enumerate(scan.paths):
        if not candidate_index & 1023:
            raise_if_cancelled(stop_event, "Attachment loose-target scan cancelled.")
            time.sleep(0.001)
        candidate_name = candidate.name.casefold()
        if not candidate_name.startswith(target_stem_key):
            continue
        candidate_stem = candidate_name.rsplit(".", 1)[0]
        if (
            candidate_stem == target_stem_key
            or candidate_stem.startswith(f"{target_stem_key}_")
            or candidate_name.startswith(f"{target_stem_key}.")
        ):
            suffix = ".sockets.xml" if candidate_name.endswith(".sockets.xml") else candidate.suffix.casefold()
            add_local_path(candidate, _kind_for_support_action(suffix))
    warning = (
        "Target loose support scan exceeded its safety limit; choose a smaller package root."
        if scan.truncated
        else ""
    )
    return PlacementLooseRootPreparation(root=root, specs=tuple(specs), warning=warning)


def prepare_attachment_loose_targets(
    request: AttachmentLoosePreflightRequest,
    *,
    stop_event: threading.Event | None = None,
) -> AttachmentLoosePreflightResult:
    roots = _discover_roots(request, stop_event=stop_event)
    prepared: list[PlacementLooseRootPreparation] = []
    for root in roots:
        raise_if_cancelled(stop_event, "Attachment loose-target scan cancelled.")
        try:
            prepared.append(_prepare_root(request, root, stop_event=stop_event))
        except Exception as exc:
            raise_if_cancelled(stop_event, "Attachment loose-target scan cancelled.")
            prepared.append(
                PlacementLooseRootPreparation(
                    root=root,
                    warning=f"Target loose support scan failed: {exc}",
                )
            )
    return AttachmentLoosePreflightResult(request.request_id, tuple(prepared))


__all__ = [
    "AttachmentLoosePreflightRequest",
    "AttachmentLoosePreflightResult",
    "prepare_attachment_loose_targets",
]
