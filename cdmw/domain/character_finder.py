"""Immutable input and output boundaries for character preview jobs."""
from dataclasses import dataclass, replace
import re
from .archives.character_catalogue import CharacterCatalogDetailResult
from cdmw.models import ArchiveEntry

CHARACTER_FINDER_LOOKAHEAD_PAGES = 4
CHARACTER_FINDER_CACHED_PAGES = 8


def character_underwear_submesh_indices(parts) -> tuple[int, ...]:
    """Hide explicitly identified underwear without classifying body skin as clothing."""
    indices = set()
    for part in parts:
        tokens = set(re.findall(r"[a-z0-9]+", str(part.get("material", "")).casefold()))
        tokens.update(re.findall(r"[a-z0-9]+", str(part.get("name", "")).casefold()))
        index = part.get("source_submesh_index")
        if tokens.intersection({"uw", "underwear", "underpants"}) and type(index) is int and index >= 0:
            indices.add(index)
    return tuple(sorted(indices))


def character_preview_detail(detail: CharacterCatalogDetailResult) -> CharacterCatalogDetailResult:
    """Keep render inputs while leaving ownership information in the UI detail."""
    if not detail.row.embedded_face or detail.row.role not in {"body", "whole_character"}:
        if detail.total_file_count > len(detail.files):
            return detail
        context_ids = {entry_id for c in detail.components for entry_id in c.context_entry_ids}
        # Owning appearances are catalogue links. Their selected component
        # attributes and customization dependencies are already explicit inputs;
        # a different character label must not require extracting its app again.
        files = tuple(f for f in detail.files if f.extension != ".app_xml" or f.entry_id in context_ids)
        return replace(detail, files=files, total_file_count=len(files))
    components = tuple(c for c in detail.components if c.role in {"body", "whole_character"})
    model_ids = {entry_id for c in components for entry_id in c.model_entry_ids}
    if not model_ids or not model_ids.issubset(model.entry_id for model in detail.models):
        return detail
    needed = model_ids | {entry_id for c in components for entry_id in c.context_entry_ids}
    files = tuple(f for f in detail.files if f.entry_id in needed)
    # Incomplete detail pages still use the existing conservative preparation path.
    if not needed.issubset(f.entry_id for f in files):
        return detail
    return replace(detail, components=components, models=tuple(m for m in detail.models if m.entry_id in model_ids),
                   files=files, total_file_count=len(files))


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
    underwear_submesh_indices: tuple[int, ...] = ()
