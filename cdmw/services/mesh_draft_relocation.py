"""Aim a resumed draft's saved archive locations at the game file it opened over.

A draft saves where its replacement target and its Refit sources lived. After a
game update the same path moves (another offset, size or package file), and
Build Mod refused the resumed draft as aimed at a different target. The session
proves it is still the same file: a draft opens its saved copy of the source,
and the replacement and the Refit primary recorded that copy's hash.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

__all__ = ["rebase_restored_archive_locations"]


def _normalized(path: object) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").casefold()


def rebase_restored_archive_locations(service, session_id: str, entry) -> bool:
    """Rebase the restored replacement target and Refit primary onto ``entry``.

    Only a location is changed, and only for the entry's own path when the
    session's source bytes are the ones the draft recorded. Other Refit sources
    keep their saved locations; their live entries are not known here.
    Returns whether anything moved.
    """

    from cdmw.services.mesh_replacement_import import archive_location

    session = service._session(session_id)
    location = archive_location(entry)
    path = _normalized(entry.path)
    moved = False
    with session.export_lock:
        source = hashlib.sha256(bytes(session.original_data or b"")).hexdigest() if session.original_data else ""
        if not source:
            return False
        state = session.replacement_state
        if (state is not None and state.target_location is not None and state.target_location != location
                and _normalized(state.target_path) == path
                and str(state.target_sha256 or "").casefold() == source):
            session.replacement_state = replace(state, target_location=location)
            moved = True
        context = session.archive_refit_context
        primary = context.assets[0] if context is not None and context.assets else None
        if (primary is not None and primary.entry.identity != entry.identity
                and _normalized(primary.entry.path) == path
                and hashlib.sha256(bytes(primary.source.original_data or b"")).hexdigest() == source):
            relocated = replace(
                primary.entry, pamt_path=entry.pamt_path, paz_file=entry.paz_file, offset=entry.offset,
                comp_size=entry.comp_size, orig_size=entry.orig_size, flags=entry.flags,
                paz_index=entry.paz_index,
            )
            session.archive_refit_context = replace(
                context, assets=(replace(primary, entry=relocated), *context.assets[1:]),
            )
            moved = True
    return moved
