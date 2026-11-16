"""Which other game files use a texture opened for editing in the Mesh Editor (step 8, item 5).

When a texture is opened from the Textures panel, the archive's Find References search
(``ArchiveReferenceSearchController``, the one Browse Archives uses) looks for the game
files that point at it, in the background. Only confirmed references count; the opened
model's own files (its PAC and sidecars, by name) are not "other" files. The dock says
what was found before the first stroke matters, and Build Mod's plan names it again.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Iterable

from PySide6.QtCore import QObject, Signal

CHECKING_TEXT = "Checking whether other game files use this texture..."
NOT_CHECKED_TEXT = "Whether other game files use this texture is not known: {reason}"
OTHER_FILES_TEXT = "Other game files use this texture, and the mod changes it for them too: {files}."
#: The Game file column's own "first + N more" (Drafts & Mods), so it reads the same.
MORE_TEXT = "{first} + {count} more"
SHOWN = 3


@dataclass(frozen=True, slots=True)
class SharedTextureResult:
    game_path: str
    finished: bool = False
    other_files: tuple[str, ...] = ()
    #: Why the search could not tell ("" when it could).
    problem: str = ""

    @property
    def sharing_notice(self) -> str:
        if self.problem:
            return NOT_CHECKED_TEXT.format(reason=self.problem)
        if not self.finished:
            return CHECKING_TEXT
        if not self.other_files:
            return ""
        return OTHER_FILES_TEXT.format(files=joined_file_names(self.other_files))


def joined_file_names(paths: Iterable[str]) -> str:
    names = [PurePosixPath(str(path).replace("\\", "/")).name for path in paths]
    if len(names) <= SHOWN:
        return ", ".join(names)
    return MORE_TEXT.format(first=", ".join(names[:SHOWN]), count=len(names) - SHOWN)


def _stem(path: str) -> str:
    name = PurePosixPath(str(path).replace("\\", "/")).name.casefold()
    return name.split(".", 1)[0]


def other_files(references: Iterable[object], own_stems: Iterable[str]) -> tuple[str, ...]:
    """The confirmed referencing files that are not the opened model's own."""

    from cdmw.core.archive_reverse_references import reference_evidence_group

    own = {stem.casefold() for stem in own_stems if stem}
    found = []
    for reference in references:
        path = str(getattr(reference, "resolved_archive_path", "") or "")
        if not path or reference_evidence_group(getattr(reference, "relation_confidence", "")) != "Confirmed references":
            continue
        if _stem(path) in own:
            continue
        if path not in found:
            found.append(path)
    return tuple(sorted(found, key=str.casefold))


class SharedTextureCheck(QObject):
    """Runs one reference search at a time for the textures opened from the panel."""

    changed = Signal(str)  # the game path whose result changed

    def __init__(self, controller_factory: Callable[[], object], entry_for: Callable[[str], object],
                 session_id: Callable[[], str], own_stems: Callable[[], Iterable[str]],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._factory = controller_factory
        self._entry_for = entry_for
        self._session_id = session_id
        self._own_stems = own_stems
        self._controller = None
        self._results: dict[str, SharedTextureResult] = {}
        self._queue: list[str] = []
        self._running = ""

    def texture_users_found(self, game_path: str) -> SharedTextureResult | None:
        return self._results.get(_key(game_path))

    def search_texture_users(self, game_path: str) -> None:
        key = _key(game_path)
        if not key or key in self._results:
            return
        self._results[key] = SharedTextureResult(game_path)
        self._queue.append(game_path)
        self.changed.emit(game_path)
        self._start_next_texture_search()

    def stop_texture_searches(self) -> None:
        self._queue.clear()
        if self._controller is not None and getattr(self._controller, "busy", False):
            self._controller.cancel()

    def _start_next_texture_search(self) -> None:
        if self._running or not self._queue:
            return
        game_path = self._queue.pop(0)
        entry = self._entry_for(game_path)
        session_id = self._session_id()
        if entry is None or not session_id:
            reason = ("its game file is not in the archive catalogue." if entry is None
                      else "the game archives are not scanned.")
            self._record_texture_users(game_path, SharedTextureResult(game_path, True, (), reason))
            return
        if self._controller is None:
            self._controller = self._factory()
            self._controller.updated.connect(self._texture_search_updated)
        self._running = game_path
        if not self._controller.start(entry, session_id=session_id):
            self._running = ""
            self._record_texture_users(game_path, SharedTextureResult(game_path, True, (), "another search is running."))

    def _texture_search_updated(self, state: object) -> None:
        if not self._running or not getattr(state, "finished", False):
            return
        game_path, self._running = self._running, ""
        error = str(getattr(state, "error", "") or "")
        if getattr(state, "cancelled", False):
            result = SharedTextureResult(game_path, True, (), "the search was cancelled.")
        elif error:
            result = SharedTextureResult(game_path, True, (), error)
        else:
            files = other_files(getattr(state, "references", ()), self._own_stems())
            problem = "the search stopped at its limit." if getattr(state, "limited", False) and not files else ""
            result = SharedTextureResult(game_path, True, files, problem)
        self._record_texture_users(game_path, result)

    def _record_texture_users(self, game_path: str, result: SharedTextureResult) -> None:
        self._results[_key(game_path)] = result
        self.changed.emit(game_path)
        self._start_next_texture_search()


def _key(game_path: str) -> str:
    return str(game_path or "").replace("\\", "/").strip().casefold()


__all__ = ["CHECKING_TEXT", "OTHER_FILES_TEXT", "SharedTextureCheck", "SharedTextureResult", "joined_file_names",
           "other_files"]
