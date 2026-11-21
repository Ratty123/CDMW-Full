"""Prepare each worn PAC's own archive context without blocking the editor."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path

from cdmw.domain.archives.item_sets import MAX_SET_FILES

from PySide6.QtCore import QObject, QTimer, Signal

from cdmw.domain.archives.catalogue import ArchiveEntryDto
from cdmw.models import ArchiveEntry
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.archive_browser.remote_preview_dependencies import (
    MAX_ARCHIVE_PREVIEW_ENTRIES,
    ArchivePreviewDependencySet,
    ArchiveRemotePreviewDependencyProvider,
)
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext

#: Maximum concurrent dependency lookups when talking to the real catalogue service.
MAX_CONCURRENT_PREPARATION_SLOTS = 4
#: Bounded LRU size for prepared per-piece archive dependency contexts.
MAX_PREPARED_CONTEXT_CACHE = 64


def _normalize_prefab_stems(preferred_prefab_stems: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(stem or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()
            for stem in preferred_prefab_stems
            if str(stem or "").strip()
        )
    )[:32]


def _normalize_scope_entry_ids(scope_entry_ids: Sequence[int]) -> tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            int(entry_id)
            for entry_id in scope_entry_ids
            if not isinstance(entry_id, bool) and int(entry_id) >= 0
        )
    )[:MAX_ARCHIVE_PREVIEW_ENTRIES]


def _prepared_context_cache_key(
    session_id: str,
    entry_id: int,
    preferred_prefab_stems: Sequence[str],
    scope_entry_ids: Sequence[int],
) -> tuple[str, int, tuple[str, ...], tuple[int, ...]]:
    return (
        str(session_id or ""),
        int(entry_id),
        _normalize_prefab_stems(preferred_prefab_stems),
        _normalize_scope_entry_ids(scope_entry_ids),
    )


def _cached_context_still_valid(
    context: ArchiveWorkflowDependencyContext,
    expected_identity: object | None = None,
) -> bool:
    selected = getattr(context, "selected_entry", None)
    if not isinstance(selected, ArchiveEntry):
        return False
    if expected_identity is not None and selected.identity != expected_identity:
        return False
    prepared_path = getattr(selected, "prepared_path", None)
    if prepared_path is None:
        return False
    try:
        return Path(prepared_path).is_file()
    except (OSError, TypeError, ValueError):
        return False


class ItemSetEditorPreparation(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: object,
        parent: QObject | None = None,
        *,
        max_concurrency: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._generation = 0
        self._members: tuple[ArchiveEntryDto, ...] = ()
        self._resolved_contexts: dict[int, ArchiveWorkflowDependencyContext] = {}
        self._next_member_index = 0
        self._queued_ready_generation = -1
        self.edit_set = False
        self._preferred_prefab_stems: tuple[str, ...] = ()
        self._scope_entry_ids: tuple[int, ...] = ()
        # The item scope each recently emitted set of contexts was resolved with, so a
        # set is only ever cached under its own scope (whether or not it was opened).
        self._emitted_scopes: list[tuple[tuple[object, ...], tuple[tuple[str, ...], tuple[int, ...]]]] = []
        if max_concurrency is None:
            slot_count = (
                MAX_CONCURRENT_PREPARATION_SLOTS
                if isinstance(service, ArchiveCatalogueService)
                else 1
            )
        else:
            slot_count = max(1, min(MAX_CONCURRENT_PREPARATION_SLOTS, int(max_concurrency)))
        self._providers: tuple[ArchiveRemotePreviewDependencyProvider, ...] = tuple(
            ArchiveRemotePreviewDependencyProvider(service, self, include_content_analysis=False)
            for _ in range(slot_count)
        )
        self._provider = self._providers[0]
        self._slot_member_index: list[int | None] = [None] * len(self._providers)
        for slot_index, provider in enumerate(self._providers):
            provider.ready.connect(
                lambda generation, snapshot, idx=slot_index: self._prepared(idx, generation, snapshot)
            )
            provider.failed.connect(
                lambda generation, message, idx=slot_index: self._failed(idx, generation, message)
            )
        self._context_cache: OrderedDict[
            tuple[str, int, tuple[str, ...], tuple[int, ...]],
            ArchiveWorkflowDependencyContext,
        ] = OrderedDict()
        self._identity_cache_keys: dict[
            object, tuple[str, int, tuple[str, ...], tuple[int, ...]]
        ] = {}
        service.session_published.connect(self._session_changed)
        if parent is not None:
            parent.destroyed.connect(self.cancel)

    @property
    def max_concurrency(self) -> int:
        return len(self._providers)

    @property
    def pending(self) -> bool:
        return bool(self._members)

    def _remember_cached_context(
        self,
        key: tuple[str, int, tuple[str, ...], tuple[int, ...]],
        context: ArchiveWorkflowDependencyContext,
    ) -> None:
        self._context_cache[key] = context
        self._context_cache.move_to_end(key)
        selected = getattr(context, "selected_entry", None)
        if isinstance(selected, ArchiveEntry):
            self._identity_cache_keys[selected.identity] = key
        while len(self._context_cache) > MAX_PREPARED_CONTEXT_CACHE:
            evicted_key, evicted_context = self._context_cache.popitem(last=False)
            evicted_entry = getattr(evicted_context, "selected_entry", None)
            if (
                isinstance(evicted_entry, ArchiveEntry)
                and self._identity_cache_keys.get(evicted_entry.identity) == evicted_key
            ):
                self._identity_cache_keys.pop(evicted_entry.identity, None)

    def _cached_context_for(
        self,
        member: ArchiveEntryDto,
        preferred_prefab_stems: Sequence[str],
        scope_entry_ids: Sequence[int],
    ) -> ArchiveWorkflowDependencyContext | None:
        key = _prepared_context_cache_key(
            member.session_id,
            member.entry_id,
            preferred_prefab_stems,
            scope_entry_ids,
        )
        cached = self._context_cache.get(key)
        if cached is None:
            return None
        expected_identity = ArchiveCatalogueService.compatibility_entry(member).identity
        if not _cached_context_still_valid(cached, expected_identity=expected_identity):
            self._context_cache.pop(key, None)
            if self._identity_cache_keys.get(expected_identity) == key:
                self._identity_cache_keys.pop(expected_identity, None)
            return None
        self._context_cache.move_to_end(key)
        return cached

    def _remember_emitted_scope(self, contexts: tuple[object, ...]) -> None:
        self._emitted_scopes.append((contexts, (self._preferred_prefab_stems, self._scope_entry_ids)))
        del self._emitted_scopes[:-8]

    def _scope_of_emitted(self, contexts: Sequence[object]):
        """The scope these exact context objects were emitted with (in any order), or None."""
        wanted = {id(context) for context in contexts or ()}
        if not wanted:
            return None
        for emitted, scope in reversed(self._emitted_scopes):
            if {id(context) for context in emitted} == wanted:
                return scope
        return None

    def cache_contexts(
        self,
        contexts: Sequence[object],
        *,
        members: Sequence[ArchiveEntryDto] = (),
        preferred_prefab_stems: Sequence[str] = (),
        scope_entry_ids: Sequence[int] = (),
    ) -> int:
        """Seed the bounded cache from already-prepared piece contexts (e.g. on piece switch).

        A context is stored under the item scope it was resolved with, not the scope
        asked for now: another variant of the same files picks other prefabs and must
        be resolved again.
        """
        emitted_scope = self._scope_of_emitted(contexts)
        if emitted_scope is None:
            return 0
        preferred_prefab_stems, scope_entry_ids = emitted_scope
        session = getattr(self._service, "current_session", None)
        session_id = str(getattr(session, "session_id", "") or "")
        members_by_identity = {
            ArchiveCatalogueService.compatibility_entry(member).identity: member
            for member in members
            if isinstance(member, ArchiveEntryDto)
            and (not session_id or member.session_id == session_id)
        }
        stored = 0
        for context in contexts or ():
            if not isinstance(context, ArchiveWorkflowDependencyContext):
                continue
            if not _cached_context_still_valid(context):
                continue
            identity = context.selected_entry.identity
            member = members_by_identity.get(identity)
            if member is not None:
                key = _prepared_context_cache_key(
                    member.session_id,
                    member.entry_id,
                    preferred_prefab_stems,
                    scope_entry_ids,
                )
            else:
                remembered = self._identity_cache_keys.get(identity)
                if remembered is None or (session_id and remembered[0] != session_id):
                    continue
                key = remembered
            self._remember_cached_context(key, context)
            stored += 1
        return stored

    def start(self, selected: ArchiveEntry, members: tuple[ArchiveEntryDto, ...], *,
              preferred_prefab_stems: tuple[str, ...] = (), scope_entry_ids: tuple[int, ...] = ()) -> bool:
        """``preferred_prefab_stems``/``scope_entry_ids``: the scoped item's prefabs, as Browse
        asks for them, so each file's context leads with the prefab that picks its variant."""
        self.cancel()
        self._preferred_prefab_stems = tuple(preferred_prefab_stems)
        self._scope_entry_ids = tuple(scope_entry_ids)
        session = self._service.current_session
        matching = [member for member in members
                    if ArchiveCatalogueService.compatibility_entry(member).identity == selected.identity]
        if (session is None or not 1 <= len(members) <= MAX_SET_FILES or len(matching) != 1
                or len({member.entry_id for member in members}) != len(members)
                or any(member.session_id != session.session_id or member.extension.casefold() != ".pac"
                       for member in members)):
            self.failed.emit("This choice has incomplete or ambiguous dependencies.")
            return False
        self._members = (matching[0], *(member for member in members if member is not matching[0]))
        self._resolved_contexts.clear()
        self._next_member_index = 0
        for index, member in enumerate(self._members):
            cached = self._cached_context_for(
                member,
                self._preferred_prefab_stems,
                self._scope_entry_ids,
            )
            if cached is not None:
                self._resolved_contexts[index] = cached
        if len(self._resolved_contexts) == len(self._members):
            generation = self._generation
            self._queued_ready_generation = generation
            QTimer.singleShot(0, lambda gen=generation: self._emit_cached_ready(gen))
            return True
        return self._dispatch_available_slots()

    def cancel(self, *_: object) -> None:
        self._generation += 1
        self._queued_ready_generation = -1
        self._members = ()
        self._resolved_contexts.clear()
        self._next_member_index = 0
        for slot_index, provider in enumerate(self._providers):
            self._slot_member_index[slot_index] = None
            provider.cancel(clear_snapshot=True)

    def _emit_cached_ready(self, generation: int) -> None:
        if (
            generation != self._generation
            or generation != self._queued_ready_generation
            or not self._members
        ):
            return
        self._queued_ready_generation = -1
        contexts = tuple(self._resolved_contexts[i] for i in range(len(self._members)))
        self._members = ()
        self._resolved_contexts.clear()
        self._next_member_index = 0
        self._remember_emitted_scope(contexts)
        self.ready.emit(contexts)

    def _dispatch_available_slots(self) -> bool:
        generation = self._generation
        for slot_index, provider in enumerate(self._providers):
            if self._slot_member_index[slot_index] is not None:
                continue
            while (
                self._next_member_index < len(self._members)
                and self._next_member_index in self._resolved_contexts
            ):
                self._next_member_index += 1
            if self._next_member_index >= len(self._members):
                break
            member_index = self._next_member_index
            self._next_member_index += 1
            self._slot_member_index[slot_index] = member_index
            started = provider.request(
                self._members[member_index],
                ui_request_id=generation,
                preferred_prefab_stems=self._preferred_prefab_stems,
                scope_entry_ids=self._scope_entry_ids,
            )
            if not started or self._generation != generation or not self._members:
                return False
        return bool(self._members)

    def _prepared(self, slot_index: int, generation: int, snapshot: object) -> None:
        if generation != self._generation or not self._members:
            return
        member_index = self._slot_member_index[slot_index]
        if member_index is None or not 0 <= member_index < len(self._members):
            return
        self._slot_member_index[slot_index] = None
        member = self._members[member_index]
        if (not isinstance(snapshot, ArchivePreviewDependencySet) or snapshot.truncated
                or snapshot.session_id != member.session_id or snapshot.entry_id != member.entry_id):
            self._failed(slot_index, generation, "This choice has incomplete or ambiguous dependencies.")
            return
        context = ArchiveWorkflowDependencyContext(
            snapshot.selected_entry, snapshot.entries, snapshot.entries_by_normalized_path,
            snapshot.entries_by_basename, True,
        )
        self._resolved_contexts[member_index] = context
        key = _prepared_context_cache_key(
            member.session_id,
            member.entry_id,
            self._preferred_prefab_stems,
            self._scope_entry_ids,
        )
        self._remember_cached_context(key, context)
        if len(self._resolved_contexts) < len(self._members):
            self._dispatch_available_slots()
            return
        contexts = tuple(self._resolved_contexts[i] for i in range(len(self._members)))
        self._members = ()
        self._resolved_contexts.clear()
        self._next_member_index = 0
        self._remember_emitted_scope(contexts)
        self.ready.emit(contexts)

    def _failed(self, _slot_index: int, generation: int, message: str) -> None:
        if generation != self._generation or not self._members:
            return
        self.cancel()
        self.failed.emit(message)

    def _session_changed(self, _session: object) -> None:
        self._context_cache.clear()
        self._identity_cache_keys.clear()
        self._emitted_scopes.clear()
        if self.pending:
            self.cancel()
            self.failed.emit("The archive catalogue changed while preparing the item set.")


def _item_scope(bridge: object) -> dict:
    """The scoped item's prefabs, which Browse's preview of the set asks for too."""
    return {"preferred_prefab_stems": tuple(getattr(bridge, "item_scope_preferred_prefab_stems", ()) or ()),
            "scope_entry_ids": tuple(getattr(bridge, "item_scope_entry_ids", ()) or ())}


def prepare_item_set_for_editor(shell: object, entry: ArchiveEntry, *, edit_set: bool = False) -> bool:
    """Capture browser membership before any selection or catalogue can change."""
    bridge = getattr(shell.archive, "archive_remote_bridge", None)
    contains = getattr(bridge, "item_set_contains", None)
    if not callable(contains) or not contains(entry):
        pending = getattr(getattr(shell, "mesh_editor_tab", None), "item_set_preparation", None)
        if pending is not None:
            pending.cancel()
        return False
    preparation = _tab_preparation(shell)
    preparation.edit_set = bool(edit_set)
    # The parts this open took from the Scene panel travel with the preparation,
    # like a set open's (review of fb9194c7c).
    preparation.hidden_parts = getattr(shell, "_mesh_editor_hidden_parts_for_open", None)
    shell._mesh_editor_hidden_parts_for_open = None
    members = tuple(bridge.item_set_members)
    scope = _item_scope(bridge)
    existing_contexts = tuple(getattr(getattr(shell, "mesh_editor_tab", None), "item_set_contexts", ()) or ())
    if existing_contexts:
        preparation.cache_contexts(existing_contexts, members=members, **scope)
    preparation.start(entry, members, **scope)
    return True


def _tab_preparation(shell: object) -> "ItemSetEditorPreparation":
    """The tab's one set preparation, with one ready handler for every way in.

    A member open and a set open both use it; whichever made it first used to
    decide what every later open did with its unticked parts (review of fb9194c7c).
    """

    tab = shell.mesh_editor_tab
    preparation = getattr(tab, "item_set_preparation", None)
    if preparation is None:
        preparation = ItemSetEditorPreparation(shell.archive.archive_catalogue_service, tab)
        tab.item_set_preparation = preparation
        preparation.ready.connect(lambda contexts: _open_prepared_set(shell, preparation, contexts))
        preparation.failed.connect(lambda message: shell.set_status_message(message, error=True))
    return preparation


def open_prepared_item_piece(shell: object, contexts: tuple, *, edit_set: bool = False) -> None:
    if not contexts or getattr(shell, "_shutting_down", False):
        return
    shell._open_archive_mesh_editor_with_dependencies(
        contexts[0].selected_entry, contexts[0], item_set_contexts=contexts,
        **({"edit_item_set": True} if edit_set else {}),
    )


def switch_item_piece(shell: object, index: int) -> None:
    tab = getattr(shell, "mesh_editor_tab", None)
    contexts = tuple(getattr(tab, "item_set_contexts", ()) or ())
    if isinstance(index, int) and 0 < index < len(contexts):
        preparation = getattr(tab, "item_set_preparation", None)
        cache_contexts = getattr(preparation, "cache_contexts", None)
        if callable(cache_contexts):
            archive = getattr(shell, "archive", None)
            bridge = getattr(archive, "archive_remote_bridge", None)
            members = tuple(getattr(bridge, "item_set_members", ()) or ())
            cache_contexts(contexts, members=members, **_item_scope(bridge))
        open_prepared_item_piece(shell, (contexts[index], *contexts[:index], *contexts[index + 1:]))


def open_current_item_set(shell: object) -> None:
    bridge = getattr(shell.archive, "archive_remote_bridge", None)
    members = tuple(getattr(bridge, "item_set_members", ()))
    if members:
        from cdmw.ui.mesh_editor.tab_rust_editor import hold_warmups_for_mesh_editor_open

        hold_warmups_for_mesh_editor_open(shell.archive, shell)
        prepare_item_set_for_editor(shell, ArchiveCatalogueService.compatibility_entry(members[0]), edit_set=True)


def _path_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


def open_ticked_parts(shell: object) -> bool:
    """Open in Mesh Editor every file with a ticked part in the Scene panel, as one session (P5).

    An Item Finder set opens its ticked members; any other preview opens the
    previewed file, with the prefab components that are loaded and ticked as
    further files of the same session. Files with no ticked part are not
    opened. In a single file, the parts left unticked start with View off; no
    part is excluded from output unless the user changes Include.
    """

    archive = shell.archive
    panel = getattr(archive, "archive_item_set_components", None)
    files = tuple(panel.ticked_files()) if panel is not None else ()
    if not files:
        shell.set_status_message("Tick at least one part in the Scene panel to open it in Mesh Editor.", error=True)
        return False
    wanted = [path for path, _unticked in files]
    bridge = getattr(archive, "archive_remote_bridge", None)
    current = archive._current_archive_entry()
    if bridge is not None and bridge.item_set_contains(getattr(archive, "archive_preview_request_entry", None)):
        members = tuple(member for member in bridge.item_set_members if _path_key(member.path) in wanted)
        return _open_members(shell, members, files)
    if len(wanted) == 1:
        # One file: the ordinary open, its unticked parts hidden in the editor's view.
        entry = current if _path_key(getattr(current, "path", "")) == wanted[0] else None
        if entry is None:
            shell.set_status_message("Select the file in Browse Archives before opening it in Mesh Editor.", error=True)
            return False
        shell._mesh_editor_pending_hidden_parts = {wanted[0]: dict(files)[wanted[0]]}
        shell._launch_archive_mesh_editor_for_entry(entry)
        return True
    from cdmw.domain.archives.catalogue import ArchiveLookupKind
    from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

    session = getattr(bridge, "current_session", None)
    if session is None:
        shell.set_status_message("Load the game's archives before opening several files.", error=True)
        return False
    primary = _path_key(getattr(current, "path", ""))
    ordered = sorted(wanted, key=lambda path: path != primary)

    def found(outcome) -> None:
        by_path = {}
        for dto in outcome.entries:
            key = _path_key(dto.path)
            if key in ordered and (key not in by_path or dto.is_active_override):
                by_path[key] = dto
        if len(by_path) != len(ordered):
            missing = ", ".join(path for path in ordered if path not in by_path)
            shell.set_status_message(f"These files could not be found in the archives: {missing}", error=True)
            return
        _open_members(shell, tuple(by_path[path] for path in ordered), files)

    start_live_catalogue_lookup(
        archive, "_scene_ticked_lookup",
        lookup_requests(session.session_id, ArchiveLookupKind.EXACT_PATHS, ordered),
        on_done=found,
        on_error=lambda message: shell.set_status_message(str(message), error=True),
    )
    return True


def _open_prepared_set(shell: object, preparation: object, contexts: tuple) -> None:
    shell._mesh_editor_hidden_parts_for_open = getattr(preparation, "hidden_parts", None)
    preparation.hidden_parts = None
    open_prepared_item_piece(shell, contexts, edit_set=preparation.edit_set)


def _open_members(shell: object, members: tuple, files: tuple) -> bool:
    if not members:
        shell.set_status_message("None of the ticked files is part of this preview.", error=True)
        return False
    if len(members) > MAX_SET_FILES:
        shell.set_status_message(f"One Mesh Editor session holds at most {MAX_SET_FILES} files.", error=True)
        return False
    from cdmw.ui.mesh_editor.tab_rust_editor import hold_warmups_for_mesh_editor_open

    hold_warmups_for_mesh_editor_open(shell.archive, shell)
    # This set's open takes the unticked parts, and no other open does (8.9).
    shell._mesh_editor_pending_hidden_parts = None
    preparation = _tab_preparation(shell)
    preparation.edit_set = True
    # Held by the preparation, not the shell: the files are read in the background,
    # and another open started meanwhile takes the shell's parts for itself (review
    # of 0359504f6). They are handed over when this set's open starts.
    preparation.hidden_parts = dict(files)
    return bool(preparation.start(ArchiveCatalogueService.compatibility_entry(members[0]), members,
                                  **_item_scope(getattr(shell.archive, "archive_remote_bridge", None))))
