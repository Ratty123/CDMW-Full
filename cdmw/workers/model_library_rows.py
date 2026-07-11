"""Cancellable row preparation for Model Library."""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cdmw.core.common import read_text_file_cancellable
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.library.models import (
    DEFAULT_MODEL_MIRROR_URL,
    is_importable_model_path,
    mirror_download_candidates,
)
_METADATA_MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FrozenModelLibrarySequence:
    items: tuple[object, ...]
    sequence_type: str


@dataclass(frozen=True, slots=True)
class FrozenModelLibraryPayload:
    items: tuple[tuple[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {key: _thaw_value(value) for key, value in self.items}


@dataclass(frozen=True, slots=True)
class ModelLibraryDeleteTarget:
    path: str
    label: str
    target_kind: str
    allowed_root: str
    identity: str


@dataclass(frozen=True, slots=True)
class ModelLibraryPreparedRow:
    payload: FrozenModelLibraryPayload
    columns: tuple[str, ...]
    size_bytes: int
    downloaded: bool
    texture_status_kind: str
    local_delete_target: Optional[ModelLibraryDeleteTarget]
    no_texture_delete_target: Optional[ModelLibraryDeleteTarget]


@dataclass(frozen=True, slots=True)
class ModelLibraryRowsRequest:
    request_id: int
    view: str
    rows: tuple[FrozenModelLibraryPayload, ...]
    download_root: str
    mirror_url: str = DEFAULT_MODEL_MIRROR_URL
    preferred_format: str = "gltf"
    query: str = ""
    local_filter_field: str = "all"
    local_texture_filter: str = "all"
    column_filters: tuple[tuple[int, str], ...] = ()
    hide_downloaded: bool = False
    sort_column: int = 1
    sort_descending: bool = False
    normalize_local: bool = False


@dataclass(frozen=True, slots=True)
class ModelLibraryPreparedRowsResult:
    request_id: int
    view: str
    all_rows: tuple[ModelLibraryPreparedRow, ...]
    visible_indices: tuple[int, ...]
    hidden_downloaded_count: int


def freeze_model_library_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[FrozenModelLibraryPayload, ...]:
    frozen: list[FrozenModelLibraryPayload] = []
    for row in rows:
        raise_if_cancelled(stop_event, "Model Library row preparation cancelled.")
        frozen.append(_freeze_payload(row))
    return tuple(frozen)


def prepare_model_library_rows(
    request: ModelLibraryRowsRequest,
    *,
    stop_event: Optional[threading.Event] = None,
) -> ModelLibraryPreparedRowsResult:
    """Normalize, probe, filter, and sort one immutable row snapshot."""

    rows = [row.to_dict() for row in request.rows]
    if request.view == "local" and request.normalize_local:
        rows = normalize_local_model_rows(rows, Path(request.download_root), stop_event=stop_event)
    mirror_dirs = (
        _mirror_download_directory_index(Path(request.download_root), stop_event=stop_event)
        if request.view == "mirror"
        else {}
    )
    prepared = tuple(
        _prepare_row(row, request, mirror_dirs, stop_event=stop_event)
        for row in rows
    )
    visible: list[int] = []
    hidden = 0
    terms = _terms(request.query)
    column_filters = tuple((int(column), _terms(query)) for column, query in request.column_filters)
    for index, row in enumerate(prepared):
        raise_if_cancelled(stop_event, "Model Library row preparation cancelled.")
        payload = row.payload.to_dict()
        if request.view == "local":
            if terms and not _local_payload_matches(payload, terms, request.local_filter_field):
                continue
            if not _texture_filter_matches(row.texture_status_kind, request.local_texture_filter):
                continue
        elif request.hide_downloaded and row.downloaded:
            hidden += 1
            continue
        if not _column_filters_match(row, column_filters):
            continue
        visible.append(index)
    if request.sort_column >= 0:
        visible.sort(
            key=lambda index: _row_sort_key(prepared[index], request.sort_column),
            reverse=request.sort_descending,
        )
    raise_if_cancelled(stop_event, "Model Library row preparation cancelled.")
    return ModelLibraryPreparedRowsResult(
        request_id=request.request_id,
        view=request.view,
        all_rows=prepared,
        visible_indices=tuple(visible),
        hidden_downloaded_count=hidden,
    )


def normalize_local_model_rows(
    rows: Iterable[Mapping[str, object]],
    download_root: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> list[dict[str, object]]:
    """Collapse files sharing trusted model metadata into one downloaded row."""

    resolved_download_root = _resolved(download_root)
    grouped: dict[str, list[dict[str, object]]] = {}
    metadata_by_group: dict[str, dict[str, object]] = {}
    metadata_path_by_group: dict[str, Path] = {}
    passthrough: list[dict[str, object]] = []
    for source_row in rows:
        raise_if_cancelled(stop_event, "Model Library row normalization cancelled.")
        row = dict(source_row)
        metadata_path = _metadata_path_for_row(row, resolved_download_root)
        if metadata_path is None:
            passthrough.append(row)
            continue
        key = _path_identity(metadata_path.parent)
        grouped.setdefault(key, []).append(row)
        metadata_path_by_group.setdefault(key, metadata_path)
        if key not in metadata_by_group:
            metadata_by_group[key] = _read_metadata(metadata_path, stop_event=stop_event)
    normalized = list(passthrough)
    for key, group_rows in grouped.items():
        raise_if_cancelled(stop_event, "Model Library row normalization cancelled.")
        metadata_path = metadata_path_by_group[key]
        display_root = _display_root(metadata_path, group_rows, resolved_download_root)
        normalized.append(
            _download_group_row(
                metadata_path.parent,
                metadata_by_group.get(key, {}),
                group_rows,
                display_root,
            )
        )
    normalized.sort(key=lambda row: (str(row.get("name", "")).casefold(), str(row.get("path", "")).casefold()))
    return normalized


def _freeze_payload(payload: Mapping[str, object]) -> FrozenModelLibraryPayload:
    return FrozenModelLibraryPayload(tuple((str(key), _freeze_value(value)) for key, value in payload.items()))


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_payload(value)
    if isinstance(value, list):
        return FrozenModelLibrarySequence(tuple(_freeze_value(item) for item in value), "list")
    if isinstance(value, tuple):
        return FrozenModelLibrarySequence(tuple(_freeze_value(item) for item in value), "tuple")
    if isinstance(value, set):
        items = sorted((_freeze_value(item) for item in value), key=repr)
        return FrozenModelLibrarySequence(tuple(items), "set")
    if isinstance(value, Path):
        return str(value)
    return value


def _thaw_value(value: object) -> object:
    if isinstance(value, FrozenModelLibraryPayload):
        return value.to_dict()
    if isinstance(value, FrozenModelLibrarySequence):
        items = tuple(_thaw_value(item) for item in value.items)
        if value.sequence_type == "list":
            return list(items)
        if value.sequence_type == "set":
            return set(items)
        return items
    return value


def _prepare_row(
    source: Mapping[str, object],
    request: ModelLibraryRowsRequest,
    mirror_dirs: Mapping[str, Path],
    *,
    stop_event: Optional[threading.Event],
) -> ModelLibraryPreparedRow:
    payload = dict(source)
    kind = str(payload.get("kind", "") or "")
    if kind == "mirror":
        _prepare_mirror_local_state(payload, request, mirror_dirs, stop_event=stop_event)
        candidates = mirror_download_candidates(
            payload,
            str(payload.get("mirror_url", "") or request.mirror_url or DEFAULT_MODEL_MIRROR_URL),
            preferred_format=request.preferred_format,
        )
        formats = ", ".join(candidate.format for candidate in candidates) or "-"
        size_bytes = _mirror_size_bytes(payload)
        local_status = str(payload.get("local_status", "") or "")
        texture_status = str(payload.get("texture_status", "") or "").strip()
        if not texture_status:
            texture_status = "Unknown" if local_status else "Download to check"
        columns = (
            "",
            str(payload.get("name", "") or "Untitled model"),
            "Mirror",
            local_status,
            texture_status,
            formats,
            _format_size(size_bytes) if size_bytes > 0 else "-",
            str(payload.get("license_label", "") or ""),
            str(payload.get("creator_name", "") or payload.get("creator_username", "") or ""),
            str(payload.get("viewer_url", "") or payload.get("metadata_url", "") or ""),
        )
    else:
        size_bytes = _int_value(payload.get("size"))
        local_status = _local_status(payload)
        texture_status = str(payload.get("texture_status", "") or "").strip() or _default_texture_status(payload)
        payload["local_status"] = local_status
        payload["texture_status"] = texture_status
        columns = (
            "",
            str(payload.get("name", "") or "Untitled model"),
            str(payload.get("source", "") or "Local"),
            local_status,
            texture_status,
            str(payload.get("extension", "") or ""),
            _format_size(size_bytes),
            str(payload.get("license_label", "") or ""),
            str(payload.get("creator_name", "") or payload.get("creator_username", "") or ""),
            str(payload.get("relative_path", "") or payload.get("path", "") or ""),
        )
    texture_kind = _texture_status_kind(texture_status)
    local_target = _local_delete_target(payload, Path(request.download_root))
    no_texture_target = (
        _downloaded_delete_target(payload, Path(request.download_root))
        if texture_kind == "missing"
        else None
    )
    return ModelLibraryPreparedRow(
        payload=_freeze_payload(payload),
        columns=columns,
        size_bytes=size_bytes,
        downloaded=bool(kind == "mirror" and str(payload.get("local_status", "") or "").strip()),
        texture_status_kind=texture_kind,
        local_delete_target=local_target,
        no_texture_delete_target=no_texture_target,
    )


def _prepare_mirror_local_state(
    payload: dict[str, object],
    request: ModelLibraryRowsRequest,
    mirror_dirs: Mapping[str, Path],
    *,
    stop_event: Optional[threading.Event],
) -> None:
    raise_if_cancelled(stop_event, "Model Library row preparation cancelled.")
    asset_text = str(payload.get("asset_dir", "") or "").strip()
    asset_dir = Path(asset_text) if asset_text else None
    if asset_dir is None or not asset_dir.is_dir():
        asset_dir = mirror_dirs.get(str(payload.get("uid", "") or payload.get("id", "") or "").casefold())
    if asset_dir is not None and asset_dir.is_dir():
        payload["asset_dir"] = str(asset_dir)
    archive_text = str(payload.get("archive_path", "") or "").strip()
    archive_path = Path(archive_text) if archive_text else None
    if (archive_path is None or not archive_path.is_file()) and asset_dir is not None and asset_dir.is_dir():
        candidates = mirror_download_candidates(
            payload,
            str(payload.get("mirror_url", "") or request.mirror_url or DEFAULT_MODEL_MIRROR_URL),
            preferred_format=request.preferred_format,
        )
        archive_path = next(
            (asset_dir / candidate.filename for candidate in candidates if (asset_dir / candidate.filename).is_file()),
            None,
        )
    if archive_path is not None and archive_path.is_file():
        payload["archive_path"] = str(archive_path)
    import_text = str(payload.get("import_path", "") or "").strip()
    import_path = Path(import_text) if import_text else None
    if (
        (import_path is None or not import_path.is_file())
        and archive_path is not None
        and archive_path.is_file()
        and archive_path.suffix.casefold() == ".glb"
    ):
        import_path = archive_path
        payload["import_path"] = str(import_path)
    if import_path is not None and import_path.is_file() and is_importable_model_path(import_path):
        payload["local_status"] = "Ready"
    elif (archive_path is not None and archive_path.is_file()) or (asset_dir is not None and asset_dir.is_dir()):
        payload["local_status"] = "Downloaded"
    else:
        payload["local_status"] = ""


def _mirror_download_directory_index(
    download_root: Path,
    *,
    stop_event: Optional[threading.Event],
) -> dict[str, Path]:
    if not download_root.is_dir():
        return {}
    indexed: dict[str, tuple[float, Path]] = {}
    try:
        candidates = tuple(download_root.iterdir())
    except OSError:
        return {}
    for candidate in candidates:
        raise_if_cancelled(stop_event, "Model Library row preparation cancelled.")
        if not candidate.is_dir():
            continue
        metadata = _read_metadata(candidate / "model_metadata.json", stop_event=stop_event)
        uid = str(metadata.get("uid", "") or metadata.get("id", "") or "").strip().casefold()
        if not uid:
            continue
        try:
            modified_at = float(candidate.stat().st_mtime)
        except OSError:
            modified_at = 0.0
        current = indexed.get(uid)
        if current is None or modified_at > current[0]:
            indexed[uid] = (modified_at, candidate)
    return {uid: value[1] for uid, value in indexed.items()}


def _metadata_path_for_row(row: Mapping[str, object], download_root: Path) -> Optional[Path]:
    path = Path(str(row.get("path", "") or ""))
    metadata_path = _nearest_metadata(path, download_root, require_under_root=True)
    if metadata_path is not None:
        return metadata_path
    root_text = str(row.get("root", "") or "").strip()
    return _nearest_metadata(path, Path(root_text) if root_text else None, require_under_root=False)


def _nearest_metadata(path: Path, root: Optional[Path], *, require_under_root: bool) -> Optional[Path]:
    resolved_path = _resolved(path)
    resolved_root = _resolved(root) if root is not None else None
    if resolved_root is not None and not _is_under(resolved_path, resolved_root):
        return None
    start = resolved_path.parent if resolved_path.is_file() else resolved_path
    for candidate_dir in (start, *start.parents):
        if require_under_root and resolved_root is not None and candidate_dir == resolved_root.parent:
            break
        metadata_path = candidate_dir / "model_metadata.json"
        if metadata_path.is_file():
            return metadata_path
        if resolved_root is not None and candidate_dir == resolved_root:
            break
    return None


def _read_metadata(path: Path, *, stop_event: Optional[threading.Event]) -> dict[str, object]:
    try:
        payload = json.loads(
            read_text_file_cancellable(path, stop_event=stop_event, max_bytes=_METADATA_MAX_BYTES)
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _display_root(metadata_path: Path, rows: list[dict[str, object]], download_root: Path) -> Path:
    resolved_metadata = _resolved(metadata_path)
    if _is_under(resolved_metadata, download_root):
        return download_root
    for row in rows:
        root_text = str(row.get("root", "") or "").strip()
        if root_text and _is_under(resolved_metadata, _resolved(Path(root_text))):
            return _resolved(Path(root_text))
    return metadata_path.parent


def _download_group_row(
    asset_dir: Path,
    metadata: Mapping[str, object],
    rows: list[dict[str, object]],
    display_root: Path,
) -> dict[str, object]:
    import_path = _importable_path(rows)
    archive_path = _preferred_archive_path(asset_dir, metadata, rows)
    display_path = import_path or archive_path or Path(str(rows[0].get("path", "") or asset_dir))
    try:
        relative_path = str(display_path.relative_to(display_root))
    except ValueError:
        relative_path = str(display_path)
    size = 0
    for candidate in (archive_path, display_path):
        if candidate is not None and candidate.is_file():
            try:
                size = int(candidate.stat().st_size)
                break
            except OSError:
                pass
    modified_at = max((_float_value(row.get("modified_at")) for row in rows), default=0.0)
    user = metadata.get("user") if isinstance(metadata.get("user"), Mapping) else {}
    license_data = metadata.get("license") if isinstance(metadata.get("license"), Mapping) else {}
    import_supported = bool(import_path and import_path.is_file())
    if not import_supported and display_path.suffix.casefold() == ".zip":
        import_supported = any(
            str(row.get("path", "") or "") == str(display_path) and bool(row.get("import_supported"))
            for row in rows
        )
    return {
        "kind": "local",
        "name": str(metadata.get("name", "") or display_path.stem),
        "path": str(display_path),
        "root": str(display_root),
        "relative_path": relative_path,
        "extension": display_path.suffix.casefold(),
        "size": size,
        "modified_at": modified_at,
        "import_supported": import_supported,
        "source": "Downloaded",
        "asset_dir": str(asset_dir),
        "archive_path": str(archive_path) if archive_path else "",
        "import_path": str(import_path) if import_path else "",
        "uid": str(metadata.get("uid", "") or metadata.get("id", "") or ""),
        "viewer_url": str(metadata.get("viewer_url", "") or metadata.get("viewerUrl", "") or ""),
        "license_label": str(metadata.get("license_label", "") or license_data.get("label", "") or ""),
        "creator_name": str(metadata.get("creator_name", "") or user.get("displayName", "") or user.get("username", "") or ""),
        "creator_username": str(metadata.get("creator_username", "") or user.get("username", "") or ""),
        "texture_status": _group_texture_status(rows) or "Unknown",
    }


def _importable_path(rows: list[dict[str, object]]) -> Optional[Path]:
    priority = {".gltf": 0, ".glb": 1, ".obj": 2, ".dae": 3}
    candidates = [
        Path(str(row.get("path", "") or ""))
        for row in rows
        if bool(row.get("import_supported"))
    ]
    candidates = [path for path in candidates if path.is_file() and path.suffix.casefold() in priority]
    candidates.sort(key=lambda path: (priority[path.suffix.casefold()], str(path).casefold()))
    return candidates[0] if candidates else None


def _group_texture_status(rows: list[dict[str, object]]) -> str:
    statuses = [str(row.get("texture_status", "") or "").strip() for row in rows]
    for prefix in ("Found (", "In ZIP ("):
        match = next((status for status in statuses if status.startswith(prefix)), "")
        if match:
            return match
    if "Embedded/Unknown" in statuses:
        return "Embedded/Unknown"
    return next((status for status in statuses if status), "")


def _preferred_archive_path(
    asset_dir: Path,
    metadata: Mapping[str, object],
    rows: list[dict[str, object]],
) -> Optional[Path]:
    uid = str(metadata.get("uid", "") or metadata.get("id", "") or "")
    candidates = [asset_dir / name for name in (f"{uid}.zip", f"{uid}.glb", f"{uid}.source.zip") if uid]
    candidates.extend(
        path
        for path in (Path(str(row.get("path", "") or "")) for row in rows)
        if path.is_file() and path.suffix.casefold() in {".zip", ".glb"}
    )
    return next(
        (path for path in candidates if path.is_file() and not path.name.casefold().endswith(".source.zip")),
        next((path for path in candidates if path.is_file()), None),
    )


def _local_status(payload: Mapping[str, object]) -> str:
    path = Path(str(payload.get("path", "") or ""))
    can_import = bool(payload.get("import_supported")) if "import_supported" in payload else path.suffix.casefold() == ".zip"
    if can_import:
        return "ZIP ready" if path.suffix.casefold() == ".zip" else "Ready"
    return "ZIP" if path.suffix.casefold() == ".zip" else "Browse"


def _default_texture_status(payload: Mapping[str, object]) -> str:
    path = Path(str(payload.get("import_path", "") or payload.get("path", "") or ""))
    return "Embedded/Unknown" if path.suffix.casefold() == ".glb" else "Unknown"


def _mirror_size_bytes(payload: Mapping[str, object]) -> int:
    archives = payload.get("archives") if isinstance(payload.get("archives"), Mapping) else {}
    sizes = [_int_value(value.get("size")) for value in archives.values() if isinstance(value, Mapping)]
    return max(sizes, default=0)


def _format_size(size: int) -> str:
    value = max(0, int(size))
    if value < 1024:
        return f"{value} B"
    if value < 1024**2:
        return f"{value / 1024:.1f} KB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} MB"
    return f"{value / 1024**3:.1f} GB"


def _local_delete_target(payload: Mapping[str, object], download_root: Path) -> Optional[ModelLibraryDeleteTarget]:
    asset_text = str(payload.get("asset_dir", "") or "").strip()
    root_text = str(payload.get("root", "") or "").strip()
    asset_dir = Path(asset_text) if asset_text else None
    row_root = Path(root_text) if root_text else None
    if asset_dir is not None and asset_dir.is_dir() and (asset_dir / "model_metadata.json").is_file():
        allowed = download_root if _is_under(_resolved(asset_dir), _resolved(download_root)) else row_root
        if allowed is not None and _is_under(_resolved(asset_dir), _resolved(allowed)):
            return _delete_target(asset_dir, "downloaded model folder", "download_dir", allowed)
    archive_text = str(payload.get("archive_path", "") or "").strip()
    archive_path = Path(archive_text) if archive_text else None
    metadata_path = (
        _nearest_metadata(archive_path, _resolved(download_root), require_under_root=True)
        if archive_path is not None and archive_path.is_file()
        else None
    )
    if metadata_path is not None and metadata_path.parent.is_dir():
        return _delete_target(metadata_path.parent, "downloaded model folder", "download_dir", download_root)
    path_text = str(payload.get("path", "") or "").strip()
    path = Path(path_text) if path_text else None
    if payload.get("kind") == "local" and path is not None and path.is_file() and row_root is not None:
        return _delete_target(path, "local model file", "local_file", row_root)
    return None


def _downloaded_delete_target(payload: Mapping[str, object], download_root: Path) -> Optional[ModelLibraryDeleteTarget]:
    target = _local_delete_target(payload, download_root)
    if target is None or target.target_kind != "download_dir":
        return None
    if not _is_under(_resolved(Path(target.path)), _resolved(download_root)):
        return None
    return target


def _delete_target(path: Path, label: str, kind: str, allowed_root: Path) -> ModelLibraryDeleteTarget:
    absolute_path = Path(os.path.abspath(str(path)))
    absolute_root = Path(os.path.abspath(str(allowed_root)))
    return ModelLibraryDeleteTarget(
        path=str(absolute_path),
        label=label,
        target_kind=kind,
        allowed_root=str(absolute_root),
        identity=_path_identity(absolute_path),
    )


def _local_payload_matches(payload: Mapping[str, object], terms: tuple[str, ...], field: str) -> bool:
    keys_by_field = {
        "name": ("name",),
        "creator": ("creator_name", "creator_username", "source"),
        "license": ("license_label", "license_slug"),
        "format": ("extension", "format", "source"),
        "path": ("relative_path", "path", "root", "asset_dir", "archive_path", "import_path"),
        "uid": ("uid", "id"),
    }
    keys = keys_by_field.get(field, tuple(dict.fromkeys(key for values in keys_by_field.values() for key in values)))
    values: list[str] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if str(item).strip())
        elif value is not None and str(value).strip():
            values.append(str(value))
    haystack = " ".join(values).casefold()
    return bool(haystack) and all(term in haystack for term in terms)


def _texture_filter_matches(kind: str, mode: str) -> bool:
    if mode == "has":
        return kind == "present"
    if mode == "missing":
        return kind == "missing"
    return True


def _texture_status_kind(status: str) -> str:
    text = str(status or "").strip()
    if text == "None found":
        return "missing"
    if text.startswith(("Found (", "In ZIP (", "Resolved (")):
        return "present"
    return "unknown"


def _column_filters_match(
    row: ModelLibraryPreparedRow,
    filters: tuple[tuple[int, tuple[str, ...]], ...],
) -> bool:
    for column, terms in filters:
        if not terms:
            continue
        text = row.columns[column].casefold() if 0 <= column < len(row.columns) else ""
        if not text or not all(term in text for term in terms):
            return False
    return True


def _row_sort_key(row: ModelLibraryPreparedRow, column: int) -> tuple[object, object, str]:
    name = row.columns[1].casefold()
    if column == 6:
        return (row.size_bytes, 0, name)
    text = row.columns[column].casefold() if 0 <= column < len(row.columns) else ""
    return (1 if column == 1 and text.strip().isdigit() else 0, text, name)


def _terms(value: str) -> tuple[str, ...]:
    return tuple(term.casefold() for term in re.findall(r"[^\s,;]+", str(value or "")) if term.strip())


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _path_identity(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path))).casefold()


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "FrozenModelLibraryPayload",
    "ModelLibraryDeleteTarget",
    "ModelLibraryPreparedRow",
    "ModelLibraryPreparedRowsResult",
    "ModelLibraryRowsRequest",
    "freeze_model_library_rows",
    "normalize_local_model_rows",
    "prepare_model_library_rows",
]
