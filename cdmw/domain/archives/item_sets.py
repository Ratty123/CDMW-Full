"""Worn model membership and primary selection for catalogue item scopes."""
from pathlib import PurePosixPath

from cdmw.domain.archives.catalogue import ArchiveEntryDto


def worn_set_members(entries: tuple[ArchiveEntryDto, ...]) -> tuple[ArchiveEntryDto, ...]:
    models = tuple(entry for entry in entries if entry.extension.casefold() == ".pac")
    worn = tuple(entry for entry in models if "dropitem" not in entry.path.casefold())
    candidates = worn or (models if len(models) == 1 else ())

    def rank(entry: ArchiveEntryDto) -> tuple[bool, int, str, int]:
        stem = PurePosixPath(entry.path.replace("\\", "/")).stem.casefold()
        return (not ("_ub_" in stem and "_ub_acc_" not in stem),
                -entry.original_size, entry.path.casefold(), entry.entry_id)

    return tuple(sorted(candidates, key=rank))
