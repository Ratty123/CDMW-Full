"""Explicit read-only New Item corpus discovery for both shipped generations.

Missing required input is an error. Callers opt into live tests; this module never
turns a missing current table into a skipped test or a legacy mod fallback.
"""
from functools import lru_cache
from pathlib import Path

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.item_sources import LEGACY_TABLE_ROOT, STATIC_TABLE_ROOT, resolve_item_data_sources
from cdmw.services.new_item_snapshot import TablePair


@lru_cache(maxsize=2)
def _sources(root: Path):
    from tools.placement_studio import corpus
    if not root.is_dir():
        raise FileNotFoundError(f"Required game corpus is unavailable: {root}")
    def fail(path,error):
        raise ValueError(f"Required corpus archive could not be read: {path}: {error}") from error
    entries = [entry for _package, entry in corpus._iter_archive_entries(root,on_error=fail)
               if entry.path.lower().startswith((LEGACY_TABLE_ROOT + "/", STATIC_TABLE_ROOT + "/"))]
    return resolve_item_data_sources(entries)


def read_table(stem: str, root: Path | None = None) -> TablePair:
    from tools.placement_studio import corpus
    root = Path(root) if root is not None else corpus.game_root()
    sources = _sources(root)
    pair = sources.tables.get(stem)
    if pair is None:
        generation = "current" if sources.static_layout else "legacy"
        raise FileNotFoundError(f"Required {generation} corpus table {stem} is unavailable in {root}")
    body, head = pair
    return TablePair(body, head, bytes(read_archive_entry_data(body)[0]), bytes(read_archive_entry_data(head)[0]))
