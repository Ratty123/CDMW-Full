"""Archive files chosen for a Refit or Cloth command without its picker.

Refit's Choose from Archive and Cloth's archive collision input open a modal picker when
the editor's request arrives (``prepare_archive_refit_event``, ``prepare_cloth_collision_event``).
An AI connection names the file instead. CDMW resolves it here to the same host-prepared
objects the picker returns (the catalogue entry with its dependency set, or the prepared
file), and offers them to the editor's next request for that command, which takes them in
place of the picker. The helper never carries the path: only host-selected archive
objects enter the worker, as with the picker. UI thread only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

#: The commands whose picker an offered choice answers.
REFIT_COMMAND = "refit_choose_archive"
CLOTH_COMMAND = "cloth_collision_input"
_ATTRIBUTE = "_host_archive_choices"
_REFIT_EXTENSIONS = (".pac", ".pam", ".pamlod")
#: The cloth picker's own bounds (cloth_collision_flow.py).
_CLOTH_LIMITS = {"weapon": 32 * 1024 * 1024, "body": 8 * 1024 * 1024, "head": 8 * 1024 * 1024}


@dataclass(frozen=True)
class HostArchiveChoice:
    """What a picker would have returned for one command: its prepared arguments."""

    command: str
    role: str
    path: str
    service: object
    catalogue_session: object
    target_identity: object
    arguments: dict = field(default_factory=dict)

    def arguments_for(self, tab, role: str) -> dict:
        """The picker's arguments for the request now being prepared, checked as the picker checks them."""

        if role != self.role:
            raise ValueError(f"The archive file was chosen for {self.role}, not {role}.")
        if getattr(self.service, "current_session", None) is not self.catalogue_session:
            raise ValueError("The game archives changed after the archive file was chosen; choose it again.")
        target = tab._current_target_entry()
        if getattr(target, "identity", None) != self.target_identity:
            raise ValueError("The loaded archive mesh changed after the archive file was chosen.")
        return dict(self.arguments)


def offer(tab, choice: HostArchiveChoice) -> None:
    """Make ``choice`` the answer to the next request for its command, in place of the picker."""

    choices = dict(getattr(tab, _ATTRIBUTE, None) or {})
    choices[choice.command] = choice
    setattr(tab, _ATTRIBUTE, choices)


def take(tab, command: str) -> HostArchiveChoice | None:
    """The choice offered for ``command``, used once; None when the picker should ask."""

    choices = dict(getattr(tab, _ATTRIBUTE, None) or {})
    choice = choices.pop(command, None)
    setattr(tab, _ATTRIBUTE, choices)
    return choice


def withdraw(tab, command: str, choice: HostArchiveChoice | None = None) -> bool:
    """Withdraw an offer nothing used (the helper sent no request), so it cannot answer the user's
    next click. With ``choice``, only that offer. Returns whether one was withdrawn."""

    choices = dict(getattr(tab, _ATTRIBUTE, None) or {})
    if command not in choices or (choice is not None and choices[command] is not choice):
        return False
    choices.pop(command)
    setattr(tab, _ATTRIBUTE, choices)
    return True


def _owner(tab):
    from cdmw.ui.shell.tab_registry import DetachedToolWindow

    owner = tab.window()
    return owner.owner if isinstance(owner, DetachedToolWindow) else owner


def _normal(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").casefold()


def start(tab, command: str, role: str, path: str, *, on_done: Callable[[HostArchiveChoice], None],
          on_failed: Callable[[str], None]) -> Callable[[], None]:
    """Resolve the archive file at ``path`` for ``command``'s picker. Calls ``on_done`` with the
    choice or ``on_failed`` with the reason, later, on the UI thread. Returns a cancel function."""

    from cdmw.domain.archives.catalogue import ArchiveLookupKind
    from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

    cancelled = [False]
    cleanups: list[Callable[[], None]] = []

    def cancel() -> None:
        cancelled[0] = True
        while cleanups:
            try:
                cleanups.pop()()
            except (RuntimeError, TypeError):
                pass

    def fail(message: str) -> None:
        if not cancelled[0]:
            cancel()
            on_failed(message)

    def done(choice: HostArchiveChoice) -> None:
        if not cancelled[0]:
            cancel()
            on_done(choice)

    archive = getattr(_owner(tab), "archive", None)
    service = getattr(archive, "archive_catalogue_service", None)
    catalogue_session = getattr(service, "current_session", None)
    if catalogue_session is None:
        fail("Load the game archives in Browse Archives first.")
        return cancel
    target = tab._current_target_entry()
    wanted = _normal(path)

    def found(outcome) -> None:
        if cancelled[0]:
            return
        matches = [dto for dto in getattr(outcome, "entries", ()) or () if _normal(dto.path) == wanted]
        if not matches:
            fail(f"The loaded archives have no file {path}.")
            return
        # The file the game reads: an override wins, as Browse Archives lists it.
        entry = next((dto for dto in matches if getattr(dto, "is_active_override", False)), matches[0])
        if command == CLOTH_COMMAND:
            _prepare_collision_input(entry)
        else:
            _prepare_refit_source(entry)

    def _prepare_collision_input(entry) -> None:
        from cdmw.domain.archives.catalogue_operations import PrepareEntryRequest, PrepareEntryResult

        weapon = role == "weapon"
        extension = ".pac" if weapon else ".pabv"
        if str(entry.extension).lower() != extension:
            fail("A weapon collision input is a .pac file." if weapon
                 else "A body or head collision input is a .pabv file.")
            return
        limit = _CLOTH_LIMITS[role]
        if int(entry.original_size) > limit:
            fail("The selected archive input exceeds the preview size limit.")
            return
        box: dict[str, str] = {}

        def result(request_id: str, operation: str, payload: object) -> None:
            if request_id != box.get("id") or operation != "prepare_entry":
                return
            if (not isinstance(payload, PrepareEntryResult) or payload.entry.session_id != entry.session_id
                    or payload.entry.entry_id != entry.entry_id or payload.entry.identity != entry.identity
                    or not 0 < payload.size <= limit):
                fail("The selected archive input changed or exceeds the preview size limit.")
                return
            done(HostArchiveChoice(command, role, entry.path, service, catalogue_session, target.identity,
                                   {"role": role, "_archive_entry": entry, "_archive_prepared": payload}))

        def failed(request_id: str, error: object) -> None:
            if request_id == box.get("id"):
                fail(str(getattr(error, "message", "") or error or "The archive file could not be prepared."))

        def dropped(request_id: str) -> None:
            if request_id == box.get("id"):
                fail("Preparing the archive file was cancelled.")

        for signal, slot in ((service.result_ready, result), (service.request_failed, failed),
                             (service.request_cancelled, dropped)):
            signal.connect(slot)
            cleanups.append(lambda signal=signal, slot=slot: signal.disconnect(slot))
        try:
            box["id"] = service.prepare_entry(PrepareEntryRequest(catalogue_session.session_id, entry.entry_id),
                                              ui_generation=0)
        except Exception as exc:  # noqa: BLE001 - the service's refusal is the answer
            fail(str(exc) or "The archive file could not be prepared.")
            return
        cleanups.append(lambda: service.cancel(box["id"]))

    def _prepare_refit_source(entry) -> None:
        from cdmw.ui.archive_browser.remote_preview_dependencies import (
            ArchivePreviewDependencySet,
            ArchiveRemotePreviewDependencyProvider,
        )
        from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext

        if str(entry.extension).lower() not in _REFIT_EXTENSIONS:
            fail("A Refit body or armor is a .pac, .pam or .pamlod file.")
            return
        if service.compatibility_entry(entry).identity == target.identity:
            fail("The current target cannot also be the Refit source.")
            return
        provider = ArchiveRemotePreviewDependencyProvider(service, parent=tab)
        request_id = 1

        def ready(ui_request_id: int, payload: object) -> None:
            if ui_request_id != request_id or not isinstance(payload, ArchivePreviewDependencySet):
                return
            context = ArchiveWorkflowDependencyContext(
                selected_entry=payload.selected_entry, entries=payload.entries,
                entries_by_normalized_path=payload.entries_by_normalized_path,
                entries_by_basename=payload.entries_by_basename, remote=True)
            done(HostArchiveChoice(command, role, entry.path, service, catalogue_session, target.identity,
                                   {"_archive_entry": context.selected_entry, "_archive_dependencies": context}))

        def failed(ui_request_id: int, message: str) -> None:
            if ui_request_id == request_id:
                fail(message or "The archive file's dependencies could not be prepared.")

        provider.ready.connect(ready)
        provider.failed.connect(failed)

        def release() -> None:
            provider.cancel(clear_snapshot=True)
            provider.deleteLater()

        cleanups.append(release)
        provider.request(entry, ui_request_id=request_id)

    lookup = start_live_catalogue_lookup(archive, "_host_archive_choice_lookup",
                                         lookup_requests(catalogue_session.session_id, ArchiveLookupKind.EXACT_PATHS,
                                                         [str(path).replace("\\", "/").strip().strip("/")]),
                                         on_done=found, on_error=fail)
    if lookup is not None:
        cleanups.append(lookup.cancel)
    return cancel


__all__ = ["CLOTH_COMMAND", "REFIT_COMMAND", "HostArchiveChoice", "offer", "start", "take", "withdraw"]
