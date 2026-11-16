"""Which other game files use a texture opened for editing in the Mesh Editor (step 8, item 5).

When a texture is opened from the Textures panel, the archive's Find References search
(``ArchiveReferenceSearchController``, the one Browse Archives uses) looks for the game
files that point at it, in the background. Only confirmed references count; the opened
model's own files (its PAC and sidecars, by name) are not "other" files. The dock says
what was found before the first stroke matters, and Build Mod's plan names it again.

The search reads the formats Find References reads for the texture, in up to three
stages: first the model property files and the tiny formats (``QUICK_REFERENCE_SOURCES``),
which takes seconds and for a character texture already finds the files that name it;
then the other small formats; last the bulky ones (``BULK_REFERENCE_SOURCES``: models,
levels and prefabs), about a minute on game 1.0.0.3663. Until the last stage is done the
dock says what was found so far and that it is still searching, never that there is
nothing. The first stage has its own controller, so a texture opened later gets its
first answer while an earlier texture's later stages are still reading.
Finished answers are kept for the archive session, shared by every Mesh Editor tab; an
answer that ended in a problem (cancelled, not scanned) is searched again next time.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable, Iterable

from PySide6.QtCore import QObject, Signal

CHECKING_TEXT = "Checking whether other game files use this texture..."
NONE_YET_TEXT = "Checking whether other game files use this texture: none found yet, still searching the rest of the game files..."
NOT_CHECKED_TEXT = "Whether other game files use this texture is not known: {reason}"
OTHER_FILES_TEXT = "Other game files use this texture, and the mod changes it for them too: {files}."
FOUND_SO_FAR_TEXT = ("Other game files use this texture, and the mod changes it for them too: {files}. "
                     "Still searching the rest of the game files for more...")
MAYBE_MORE_TEXT = ("Other game files use this texture, and the mod changes it for them too: {files}. "
                   "There may be more: {reason}")
#: The Game file column's own "first + N more" (Drafts & Mods), so it reads the same.
MORE_TEXT = "{first} + {count} more"
SHOWN = 3
LIMIT_REASON = "the search stopped at its limit."
CANCELLED_REASON = "the search was cancelled."
#: Finished answers kept per archive session, across Mesh Editor tabs.
CACHE_SIZE = 1024


@dataclass(frozen=True, slots=True)
class SharedTextureResult:
    game_path: str
    finished: bool = False
    other_files: tuple[str, ...] = ()
    #: Why the search could not tell, or could not tell everything ("" when it could).
    problem: str = ""
    #: A first stage is done: what was found so far is known, the rest is still being read.
    first_stage_done: bool = False
    session_id: str = ""

    @property
    def sharing_notice(self) -> str:
        if self.problem:
            if self.other_files:
                return MAYBE_MORE_TEXT.format(files=joined_file_names(self.other_files), reason=self.problem)
            return NOT_CHECKED_TEXT.format(reason=self.problem)
        if not self.finished:
            if not self.first_stage_done:
                return CHECKING_TEXT
            if self.other_files:
                return FOUND_SO_FAR_TEXT.format(files=joined_file_names(self.other_files))
            return NONE_YET_TEXT
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


def confirmed_files(references: Iterable[object]) -> tuple[str, ...]:
    """The files a search confirmed as naming the texture, each once."""

    from cdmw.core.archive_reverse_references import reference_evidence_group

    found = []
    for reference in references:
        path = str(getattr(reference, "resolved_archive_path", "") or "")
        if not path or reference_evidence_group(getattr(reference, "relation_confidence", "")) != "Confirmed references":
            continue
        if path not in found:
            found.append(path)
    return tuple(found)


def _without_own(paths: Iterable[str], own_stems: Iterable[str]) -> tuple[str, ...]:
    own = {stem.casefold() for stem in own_stems if stem}
    return tuple(sorted({path for path in paths if _stem(path) not in own}, key=str.casefold))


def other_files(references: Iterable[object], own_stems: Iterable[str]) -> tuple[str, ...]:
    """The confirmed referencing files that are not the opened model's own."""

    return _without_own(confirmed_files(references), own_stems)


def texture_search_stages(entry: object) -> tuple[tuple[str, ...], ...]:
    """The plan's formats in the stages they are read in: quick ones first, bulky ones last.

    Every format of the plan is in exactly one stage; empty stages are left out.
    """

    from cdmw.core.archive_reverse_references import reference_search_plan
    from cdmw.domain.archives.reference_sources import BULK_REFERENCE_SOURCES, QUICK_REFERENCE_SOURCES

    formats = [extension for group in reference_search_plan(entry).groups for extension in group]
    stages = (tuple(extension for extension in formats if extension in QUICK_REFERENCE_SOURCES),
              tuple(extension for extension in formats
                    if extension not in QUICK_REFERENCE_SOURCES and extension not in BULK_REFERENCE_SOURCES),
              tuple(extension for extension in formats if extension in BULK_REFERENCE_SOURCES))
    return tuple(stage for stage in stages if stage)


def _bulky(formats: Iterable[str]) -> bool:
    from cdmw.domain.archives.reference_sources import BULK_REFERENCE_SOURCES

    return any(extension in BULK_REFERENCE_SOURCES for extension in formats)


@dataclass(frozen=True, slots=True)
class _Answer:
    """A finished search, before the opened model's own files are taken out."""

    confirmed: tuple[str, ...]
    limited: bool


_ANSWERS: OrderedDict[tuple[str, str], _Answer] = OrderedDict()


def forget_texture_users() -> None:
    """Drop every kept answer (a new archive scan gets a new session id anyway)."""

    _ANSWERS.clear()


def _keep_answer(session_id: str, key: str, answer: _Answer) -> None:
    _ANSWERS[(session_id, key)] = answer
    _ANSWERS.move_to_end((session_id, key))
    while len(_ANSWERS) > CACHE_SIZE:
        _ANSWERS.popitem(last=False)


@dataclass(slots=True)
class _Job:
    game_path: str
    key: str
    entry: object
    session_id: str
    stages: tuple[tuple[str, ...], ...]
    stage: int = 0
    confirmed: tuple[str, ...] = ()
    limited: bool = False


@dataclass(slots=True)
class _Lane:
    controller: object = None
    queue: list[_Job] = field(default_factory=list)
    running: _Job | None = None


FIRST, REST = "first", "rest"


class SharedTextureCheck(QObject):
    """Searches the textures opened from the panel in stages: the first on one controller,
    the later ones, one texture at a time, on another."""

    changed = Signal(str)  # the game path whose result changed

    def __init__(self, controller_factory: Callable[[], object], entry_for: Callable[[str], object],
                 session_id: Callable[[], str], own_stems: Callable[[], Iterable[str]],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._factory = controller_factory
        self._entry_for = entry_for
        self._session_id = session_id
        self._own_stems = own_stems
        self._results: dict[str, SharedTextureResult] = {}
        self._lanes = {FIRST: _Lane(), REST: _Lane()}

    def texture_users_found(self, game_path: str) -> SharedTextureResult | None:
        key = _key(game_path)
        result = self._results.get(key)
        if result is not None:
            answer = _ANSWERS.get((result.session_id, key)) if result.finished else None
            # The opened model can change in the tab: its own files are taken out on every read.
            return self._texture_users_answer(game_path, result.session_id, answer) if answer is not None else result
        session_id = self._session_id()
        answer = _ANSWERS.get((session_id, key)) if session_id else None
        return self._texture_users_answer(game_path, session_id, answer) if answer is not None else None

    def search_texture_users(self, game_path: str) -> None:
        key = _key(game_path)
        if not key:
            return
        session_id = self._session_id()
        current = self._results.get(key)
        if current is not None and not current.finished:
            return  # still searching
        if (current is not None and current.session_id == session_id
                and current.problem in ("", LIMIT_REASON)):
            return  # answered for this session
        answer = _ANSWERS.get((session_id, key)) if session_id else None
        if answer is not None:
            self._results[key] = self._texture_users_answer(game_path, session_id, answer)
            self.changed.emit(game_path)
            return
        self._results[key] = SharedTextureResult(game_path, session_id=session_id)
        self.changed.emit(game_path)
        entry = self._entry_for(game_path)
        if entry is None or not session_id:
            reason = ("its game file is not in the archive catalogue." if entry is None
                      else "the game archives are not scanned.")
            self._record_texture_users(game_path, SharedTextureResult(game_path, True, (), reason, session_id=session_id))
            return
        job = _Job(game_path, key, entry, session_id, texture_search_stages(entry))
        if not job.stages:
            # No format stores paths of this kind, so no file can name it.
            self._finish_texture_search(job)
            return
        # A first stage of bulky formats would hold up the next texture's first answer.
        lane = REST if _bulky(job.stages[0]) else FIRST
        self._lanes[lane].queue.append(job)
        self._start_next_texture_search(lane)

    def stop_texture_searches(self) -> None:
        for lane in self._lanes.values():
            queued, lane.queue = lane.queue, []
            for job in queued:
                self._record_texture_users(job.game_path, self._texture_users_stopped(job, CANCELLED_REASON))
        for lane in self._lanes.values():
            if lane.controller is not None and getattr(lane.controller, "busy", False):
                lane.controller.cancel()

    def _start_next_texture_search(self, name: str) -> None:
        lane = self._lanes[name]
        if lane.running is not None or not lane.queue:
            return
        job = lane.queue.pop(0)
        if lane.controller is None:
            lane.controller = self._factory()
            lane.controller.updated.connect(lambda state, name=name: self._texture_stage_updated(name, state))
        lane.running = job
        if not lane.controller.start(job.entry, session_id=job.session_id, formats=job.stages[job.stage]):
            lane.running = None
            self._record_texture_users(job.game_path, self._texture_users_stopped(job, "another search is running."))
            self._start_next_texture_search(name)

    def _texture_stage_updated(self, name: str, state: object) -> None:
        lane = self._lanes[name]
        if lane.running is None or not getattr(state, "finished", False):
            return
        job, lane.running = lane.running, None
        error = str(getattr(state, "error", "") or "")
        if getattr(state, "cancelled", False) or error:
            self._record_texture_users(job.game_path, self._texture_users_stopped(job, CANCELLED_REASON if not error else error))
        else:
            job.confirmed = tuple(dict.fromkeys((*job.confirmed, *confirmed_files(getattr(state, "references", ())))))
            job.limited = job.limited or bool(getattr(state, "limited", False))
            job.stage += 1
            if job.stage < len(job.stages):
                self._record_texture_users(job.game_path, SharedTextureResult(
                    job.game_path, False, self._other_texture_users(job.confirmed), "", True, job.session_id))
                # A texture's later stages follow each other before the next texture's.
                queue = self._lanes[REST].queue
                if name == REST:
                    queue.insert(0, job)
                else:
                    queue.append(job)
                self._start_next_texture_search(REST)
            else:
                self._finish_texture_search(job)
        self._start_next_texture_search(name)

    def _finish_texture_search(self, job: _Job) -> None:
        answer = _Answer(job.confirmed, job.limited)
        _keep_answer(job.session_id, job.key, answer)
        self._record_texture_users(job.game_path, self._texture_users_answer(job.game_path, job.session_id, answer))

    def _texture_users_answer(self, game_path: str, session_id: str, answer: _Answer) -> SharedTextureResult:
        return SharedTextureResult(game_path, True, self._other_texture_users(answer.confirmed),
                                   LIMIT_REASON if answer.limited else "", True, session_id)

    def _texture_users_stopped(self, job: _Job, problem: str) -> SharedTextureResult:
        return SharedTextureResult(job.game_path, True, self._other_texture_users(job.confirmed), problem, True, job.session_id)

    def _other_texture_users(self, confirmed: Iterable[str]) -> tuple[str, ...]:
        return _without_own(confirmed, self._own_stems())

    def _record_texture_users(self, game_path: str, result: SharedTextureResult) -> None:
        self._results[_key(game_path)] = result
        self.changed.emit(game_path)


def _key(game_path: str) -> str:
    return str(game_path or "").replace("\\", "/").strip().casefold()


__all__ = ["CHECKING_TEXT", "FOUND_SO_FAR_TEXT", "MAYBE_MORE_TEXT", "NONE_YET_TEXT", "OTHER_FILES_TEXT",
           "SharedTextureCheck", "SharedTextureResult", "confirmed_files", "forget_texture_users",
           "joined_file_names", "other_files", "texture_search_stages"]
