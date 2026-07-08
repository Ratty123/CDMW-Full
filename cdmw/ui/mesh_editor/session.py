from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - import guard keeps source tests light.
    from cdmw.models import ArchiveEntry
except ImportError:  # pragma: no cover
    ArchiveEntry = object  # type: ignore[assignment]

try:  # pragma: no cover
    from cdmw.modding.scene_importer import SceneImportResult
except ImportError:  # pragma: no cover
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
