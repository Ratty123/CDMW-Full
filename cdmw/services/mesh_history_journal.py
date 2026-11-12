"""Undo history that survives a restart (P14): a journal of a draft's saved states.

A journal step is one autosave generation of a draft's layer project
(``generation-*/`` beside ``mesh_layer_project.json``). Its record holds the
generation's folder name, its depth in the edit history, the history labels
and parts of the steps it holds, its size and the SHA-256 of its
``generation.json`` (which holds the SHA-256 of every snapshot file it names,
so the digest covers them as well). Nothing is ever run again: a step back
loads the state that was saved.

Records are one JSON line each, appended with flush and fsync after their
generation is complete, so a crash mid-write leaves at most a truncated last
line, which is ignored. Replacing or dropping records rewrites the file
atomically.

``draft`` records are states the draft itself was at (the descriptor pointed at
them). The Mesh Editor edits a shadow session, and the draft receives its work
at Finish; until then the newest unfinished state is kept as one recovery point
(``editor_recovery.json`` and its generation), which a Mesh Editor reopened on
the same draft state after a crash continues from.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from cdmw.core.atomic_file import atomic_write_text

JOURNAL_NAME = "history_journal.jsonl"
JOURNAL_FORMAT = "cdmw_mesh_history_journal_v1"
RECOVERY_NAME = "editor_recovery.json"
RECOVERY_FORMAT = "cdmw_mesh_editor_recovery_v1"
KIND_DRAFT = "draft"
KIND_EDITOR = "editor"
_KINDS = frozenset({KIND_DRAFT, KIND_EDITOR})

_ROOT_LOCKS: dict[str, threading.RLock] = {}
_ROOT_LOCKS_GUARD = threading.Lock()


def project_lock(project_root: Path) -> threading.RLock:
    """The one lock for writing generations and records of a draft's journal."""

    key = os.path.normcase(str(Path(project_root).resolve()))
    with _ROOT_LOCKS_GUARD:
        lock = _ROOT_LOCKS.get(key)
        if lock is None:
            lock = _ROOT_LOCKS[key] = threading.RLock()
        return lock


@dataclass(frozen=True, slots=True)
class JournalRecord:
    generation: str
    depth: int
    digest: str
    size_bytes: int
    kind: str = KIND_DRAFT
    labels: tuple[str, ...] = ()
    part_ids: tuple[int, ...] = ()
    created_at: float = 0.0

    def line(self) -> str:
        return json.dumps({
            "format": JOURNAL_FORMAT,
            "type": "step",
            "generation": self.generation,
            "depth": self.depth,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "kind": self.kind,
            "labels": list(self.labels),
            "part_ids": list(self.part_ids),
            "created_at": self.created_at,
        }, sort_keys=True, separators=(",", ":"))


@dataclass(slots=True)
class Journal:
    records: list[JournalRecord] = field(default_factory=list)
    clean_generation: str = ""
    #: Lines that could not be read; only a truncated last line is expected.
    ignored_lines: int = 0

    def record_for(self, generation: str) -> JournalRecord | None:
        return next((record for record in self.records if record.generation == generation), None)

    def before(self, depth: int) -> JournalRecord | None:
        earlier = [record for record in self.records if record.depth < depth]
        return earlier[-1] if earlier else None

    def after(self, depth: int) -> JournalRecord | None:
        later = [record for record in self.records if record.depth > depth]
        return later[0] if later else None

    @property
    def size_bytes(self) -> int:
        return sum(record.size_bytes for record in self.records)


def journal_path(project_root: Path) -> Path:
    return Path(project_root) / JOURNAL_NAME


def generation_digest(project_root: Path, generation: str) -> str:
    manifest = _generation_dir(project_root, generation) / "generation.json"
    digest = hashlib.sha256()
    with manifest.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generation_size(project_root: Path, generation: str) -> int:
    total = 0
    for path in _generation_dir(project_root, generation).rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def read_journal(project_root: Path) -> Journal:
    """The journal's records by depth; unreadable lines are counted and skipped."""

    path = journal_path(project_root)
    journal = Journal()
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return journal
    by_depth: dict[int, JournalRecord] = {}
    for raw_line in data.splitlines():
        if not raw_line.strip():
            continue
        try:
            # A line that is not text (a damaged byte) is unreadable on its own; the
            # others still count (section 8.7 A12).
            item = json.loads(raw_line.decode("utf-8"))
            if not isinstance(item, dict) or item.get("format") != JOURNAL_FORMAT:
                raise ValueError
            if item.get("type") == "clean":
                journal.clean_generation = str(item.get("generation") or "")
                continue
            record = JournalRecord(
                generation=_generation_name(item.get("generation")),
                depth=_non_negative(item.get("depth")),
                digest=_digest(item.get("digest")),
                size_bytes=_non_negative(item.get("size_bytes")),
                kind=str(item.get("kind") or KIND_DRAFT) if item.get("kind") in _KINDS else KIND_DRAFT,
                labels=tuple(str(label) for label in item.get("labels") or ())[:64],
                part_ids=tuple(_non_negative(part) for part in item.get("part_ids") or ())[:4096],
                created_at=float(item.get("created_at") or 0.0),
            )
        except (TypeError, ValueError, OverflowError):  # UnicodeDecodeError is a ValueError
            journal.ignored_lines += 1
            continue
        by_depth[record.depth] = record  # a later line for a depth replaces it
    journal.records = [by_depth[depth] for depth in sorted(by_depth)]
    return journal


def verify_record(project_root: Path, record: JournalRecord) -> str:
    """Empty when the record's generation is the one that was saved, else why not."""

    try:
        actual = generation_digest(project_root, record.generation)
    except (OSError, ValueError) as exc:
        return f"{record.generation}: {exc}"
    if actual != record.digest:
        return f"{record.generation}: its saved state does not match the journal's digest"
    return ""


def record_state(
    project_root: Path,
    record: JournalRecord,
    *,
    future_valid: bool,
    max_steps: int,
    max_bytes: int,
    keep: Iterable[str] = (),
) -> Journal:
    """Put ``record`` at its depth, drop what it supersedes and prune to the limits.

    ``future_valid`` is False after an edit: deeper records are a future that
    can no longer be reached, as a redo stack is cleared. True after an undo or
    redo, which only moved within the history. Generations of dropped records
    are deleted unless they are in ``keep`` (the descriptor's current and
    previous generation). The caller holds ``project_lock``.
    """

    root = Path(project_root)
    kept = {name for name in keep if name}
    kept.add(record.generation)
    journal = read_journal(root)
    before = list(journal.records)
    records = [item for item in before if item.depth != record.depth
               and (future_valid or item.depth < record.depth)]
    replaced = next((item for item in before if item.depth == record.depth), None)
    if future_valid and replaced is not None and journal.clean_generation == replaced.generation:
        # An undo or redo back to the finished state saves it again under a new
        # name; it is still the state that was finished.
        journal.clean_generation = record.generation
    records.append(record)
    records.sort(key=lambda item: item.depth)
    limit_steps = max(1, int(max_steps or 1))
    limit_bytes = max(0, int(max_bytes or 0))
    while len(records) > 1 and (len(records) > limit_steps or sum(item.size_bytes for item in records) > limit_bytes):
        # The shallowest step goes first, as the oldest undo entry does. The new
        # state always stays, so a large state alone still has its journal.
        victim = 0 if records[0] is not record else 1
        if victim >= len(records):
            break
        records.pop(victim)
    journal.records = records
    appended = (len(records) == len(before) + 1 and records[:-1] == before and records[-1] is record)
    if appended and journal.ignored_lines == 0 and (replaced is None or not journal.clean_generation):
        _append_line(root, record.line())
    else:
        _rewrite(root, journal)
    _delete_generations(root, {item.generation for item in before} - {item.generation for item in records} - kept)
    return journal


def drop_after(project_root: Path, depth: int, *, keep: Iterable[str] = ()) -> Journal:
    """Drop every record deeper than ``depth`` (a discarded editor session)."""

    root = Path(project_root)
    journal = read_journal(root)
    dropped = [item for item in journal.records if item.depth > depth]
    if not dropped and not journal.ignored_lines:
        return journal
    journal.records = [item for item in journal.records if item.depth <= depth]
    _rewrite(root, journal)
    _delete_generations(root, {item.generation for item in dropped} - {name for name in keep if name})
    return journal


def mark_clean(project_root: Path, generation: str) -> None:
    """Record ``generation`` as the state the user last finished or built."""

    root = Path(project_root)
    if not journal_path(root).is_file():
        return
    _append_line(root, json.dumps({"format": JOURNAL_FORMAT, "type": "clean", "generation": str(generation)},
                                  sort_keys=True, separators=(",", ":")))


def prune_unjournaled_generations(project_root: Path, keep: Iterable[str] = ()) -> None:
    """Remove generation folders no record names and the descriptor does not use.

    Called under ``project_lock``, so no generation is half-written meanwhile.
    """

    root = Path(project_root)
    current = read_journal(root)
    if current.ignored_lines:
        # A line could not be read: it may name a step, so nothing is removed (8.7 A12).
        return
    named = {record.generation for record in current.records} | {name for name in keep if name}
    recovery = read_editor_recovery(root)
    if recovery is not None:
        named.add(recovery["generation"])
    _delete_generations(root, {
        path.name for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and path.name.startswith("generation-") and path.name not in named
    })


def read_editor_recovery(project_root: Path) -> dict[str, object] | None:
    """The unfinished Mesh Editor state kept for this draft, or None."""

    try:
        item = json.loads((Path(project_root) / RECOVERY_NAME).read_text(encoding="utf-8"))
        if not isinstance(item, dict) or item.get("format") != RECOVERY_FORMAT:
            return None
        return {
            "generation": _generation_name(item.get("generation")),
            "digest": _digest(item.get("digest")),
            "base_generation": str(item.get("base_generation") or ""),
            "saved_at": float(item.get("saved_at") or 0.0),
        }
    except (OSError, TypeError, ValueError):
        return None


def write_editor_recovery(project_root: Path, generation: str, *, base_generation: str) -> None:
    """Keep ``generation`` as the recovery point; the one it replaces is deleted.

    ``base_generation`` is the draft state the editor started from: a recovery
    point is offered only to an editor opened on that same state.
    """

    root = Path(project_root)
    previous = read_editor_recovery(root)
    atomic_write_text(root / RECOVERY_NAME, json.dumps({
        "format": RECOVERY_FORMAT,
        "generation": generation,
        "digest": generation_digest(root, generation),
        "base_generation": str(base_generation or ""),
        "saved_at": time.time(),
    }, indent=2, sort_keys=True))
    if previous is not None and previous["generation"] != generation:
        _delete_generations(root, (previous["generation"],))


def clear_editor_recovery(project_root: Path) -> None:
    """Drop the recovery point: its edits were finished or discarded."""

    root = Path(project_root)
    previous = read_editor_recovery(root)
    try:
        (root / RECOVERY_NAME).unlink()
    except FileNotFoundError:
        pass
    if previous is not None and journal_path(root).is_file():
        if read_journal(root).record_for(previous["generation"]) is not None:
            return
    if previous is not None:
        descriptor = _published_generations(root)
        if previous["generation"] not in descriptor:
            _delete_generations(root, (previous["generation"],))


def _published_generations(root: Path) -> set[str]:
    try:
        descriptor = json.loads((root / "mesh_layer_project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(descriptor, dict):
        return set()
    return {str(descriptor.get(key) or "") for key in ("current_generation", "previous_generation")} - {""}


def _append_line(root: Path, line: str) -> None:
    path = journal_path(root)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _rewrite(root: Path, journal: Journal) -> None:
    lines = [record.line() for record in journal.records]
    if journal.clean_generation and journal.record_for(journal.clean_generation) is not None:
        lines.append(json.dumps({"format": JOURNAL_FORMAT, "type": "clean", "generation": journal.clean_generation},
                                sort_keys=True, separators=(",", ":")))
    atomic_write_text(journal_path(root), "".join(line + "\n" for line in lines))
    journal.ignored_lines = 0


def _delete_generations(root: Path, names: Iterable[str]) -> None:
    for name in names:
        try:
            folder = _generation_dir(root, name)
        except ValueError:
            continue
        if folder.is_dir() and not folder.is_symlink():
            shutil.rmtree(folder, ignore_errors=True)


def _generation_dir(project_root: Path, generation: str) -> Path:
    root = Path(project_root).resolve()
    folder = (root / _generation_name(generation)).resolve()
    if folder.parent != root:
        raise ValueError("journal generation is outside the draft")
    return folder


def _generation_name(value: object) -> str:
    name = str(value or "")
    if not name.startswith("generation-") or "/" in name or "\\" in name or ".." in name:
        raise ValueError("journal record names no generation")
    return name


def _digest(value: object) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError("journal record digest is invalid")
    return text


def _non_negative(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError
    number = int(value)
    if number < 0:
        raise ValueError
    return number


def new_record(
    project_root: Path,
    generation: str,
    *,
    depth: int,
    kind: str = KIND_DRAFT,
    labels: Sequence[str] = (),
    part_ids: Sequence[int] = (),
) -> JournalRecord:
    return JournalRecord(
        generation=generation,
        depth=max(0, int(depth)),
        digest=generation_digest(project_root, generation),
        size_bytes=generation_size(project_root, generation),
        kind=kind if kind in _KINDS else KIND_DRAFT,
        labels=tuple(str(label) for label in labels if str(label))[:64],
        part_ids=tuple(sorted({int(part) for part in part_ids}))[:4096],
        created_at=time.time(),
    )
