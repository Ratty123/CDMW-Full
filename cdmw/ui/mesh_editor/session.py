from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cdmw.modding.skeleton_parser import parse_pab

try:  # pragma: no cover - import guard keeps source tests light.
    from cdmw.models import ArchiveEntry
except Exception:  # pragma: no cover
    ArchiveEntry = object  # type: ignore[assignment]

try:  # pragma: no cover
    from cdmw.modding.scene_importer import SceneImportResult
except Exception:  # pragma: no cover
    SceneImportResult = object  # type: ignore[assignment]


@dataclass(slots=True)
class MeshEditorSessionRequest:
    target_entry: ArchiveEntry
    mode: str
    source_path: Optional[Path] = None
    source_entry: Optional[ArchiveEntry] = None
    source_skeleton: object | None = None
    supplemental_files: tuple[Path, ...] = ()
    scene_import_result: Optional[SceneImportResult] = None


def mesh_editor_source_skeleton(
    *,
    source_skeleton: object | None = None,
    source_path: Path | str | None = None,
    supplemental_files: tuple[Path, ...] = (),
    scene_import_result: object | None = None,
) -> object | None:
    if source_skeleton is not None:
        return source_skeleton
    imported_skeleton = getattr(scene_import_result, "source_skeleton", None)
    if imported_skeleton is not None:
        return imported_skeleton
    for path in _source_skeleton_candidate_paths(
        source_path=source_path,
        supplemental_files=supplemental_files,
        scene_import_result=scene_import_result,
    ):
        try:
            resolved = path.expanduser().resolve()
        except (OSError, RuntimeError):
            resolved = path
        if resolved.suffix.lower() != ".pab" or not resolved.is_file():
            continue
        try:
            return parse_pab(resolved.read_bytes(), str(resolved))
        except Exception:
            continue
    return None


def _source_skeleton_candidate_paths(
    *,
    source_path: Path | str | None,
    supplemental_files: tuple[Path, ...],
    scene_import_result: object | None,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if source_path is not None:
        path = Path(source_path)
        candidates.append(path)
        if path.suffix.lower() in {".pac", ".pam", ".pamlod"}:
            candidates.append(path.with_suffix(".pab"))
    candidates.extend(path for path in tuple(supplemental_files or ()) if isinstance(path, Path))
    candidates.extend(
        path
        for path in tuple(getattr(scene_import_result, "discovered_supplemental_files", ()) or ())
        if isinstance(path, Path)
    )
    result: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).replace("\\", "/").lower()
        if key and key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)
