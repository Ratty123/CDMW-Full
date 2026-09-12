"""Immutable input and output boundaries for character preview jobs."""
from dataclasses import dataclass
from .archives.character_catalogue import CharacterCatalogDetailResult
from cdmw.models import ArchiveEntry


@dataclass(frozen=True, slots=True)
class CharacterPreviewInputs:
    detail: CharacterCatalogDetailResult
    entries_by_id: dict[int, ArchiveEntry]
    entries: tuple[ArchiveEntry, ...]
    dependencies_complete: bool


@dataclass(frozen=True, slots=True)
class CharacterRenderResult:
    key: str
    package_path: str
    thumbnail_path: str
    status: str
    notes: tuple[str, ...]
    cache_hit: bool = False
