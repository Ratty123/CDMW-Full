from __future__ import annotations

from array import array
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def write_i32_preview_delta(values: Sequence[int], suffix: str) -> tuple[dict[str, object], Path] | None:
    try:
        data = array("i", (int(value) for value in values))
    except (OverflowError, ValueError):
        return None
    if data.itemsize != 4:
        return None
    with tempfile.NamedTemporaryFile(prefix="cdmw_mesh_preview_delta_", suffix=suffix, delete=False) as handle:
        path = Path(handle.name)
        data.tofile(handle)
    return (
        {
            "path": str(path),
            "count": len(data),
            "components": 1,
            "type": "i32",
            "delete_after": True,
        },
        path,
    )


def sorted_nonnegative_indices(raw_values: Iterable[int] | None) -> list[int]:
    values: set[int] = set()
    try:
        iterator = iter(raw_values or ())
    except TypeError:
        return []
    for raw_value in iterator:
        try:
            value = int(raw_value)
        except (TypeError, ValueError, OverflowError):
            continue
        if value >= 0:
            values.add(value)
    return sorted(values)


def compact_nonnegative_indices(raw_values: Iterable[int] | None) -> tuple[tuple[int, int] | None, list[int]]:
    if isinstance(raw_values, range):
        count = len(raw_values)
        if raw_values.start >= 0 and raw_values.step == 1 and count > 0:
            return (raw_values.start, count), []
        return None, []
    values = sorted_nonnegative_indices(raw_values)
    if not values:
        return None, []
    start = values[0]
    for offset, value in enumerate(values):
        if value != start + offset:
            return None, values
    return (start, len(values)), []


def mesh_edit_json_groups(groups: Sequence[Mapping[str, object]] | None) -> Sequence[Mapping[str, object]]:
    if groups is None:
        return ()
    if isinstance(groups, (list, tuple)):
        return groups
    return tuple(groups)


def delete_after_paths(value: object) -> tuple[Path, ...]:
    paths: set[Path] = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, Mapping):
            if bool(item.get("delete_after")):
                for key in ("path", "payload_file"):
                    raw_path = str(item.get(key) or "").strip()
                    if raw_path:
                        paths.add(Path(raw_path))
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return tuple(paths)


def remove_paths(paths: Iterable[Path]) -> None:
    try:
        from cdmw.services.mesh_workflow_service import release_native_preview_delta_path
    except Exception:
        release_native_preview_delta_path = None
    for path in set(Path(item) for item in paths):
        if release_native_preview_delta_path is not None and release_native_preview_delta_path(path):
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "compact_nonnegative_indices",
    "delete_after_paths",
    "mesh_edit_json_groups",
    "remove_paths",
    "sorted_nonnegative_indices",
    "write_i32_preview_delta",
]
