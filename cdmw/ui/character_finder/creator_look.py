"""Resolve Kliff's Character Creator look to archive entries through the resident worker."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import ArchiveEntryDto, ArchiveLookupKind, ArchiveLookupRequest, ArchiveLookupResult
from cdmw.domain.archives.catalogue_operations import PrepareEntriesRequest, PrepareEntriesResult
from cdmw.domain.character_creator import (
    CharacterCreatorError, CharacterCreatorLook, CharacterCreatorResolvedPart, kliff_look_detail, resolve_kliff_look,
)

_LOOKUP_LIMIT = 512


def character_creator_folder(package_root: str | Path) -> Path | None:
    """``bin64/CharacterCreator`` beside the game executable, when the mod is installed."""
    from cdmw.core.archive_scan_cache import resolve_crimson_desert_executable

    text = str(package_root or "").strip()
    executable = resolve_crimson_desert_executable(Path(text)) if text else None
    if executable is None:
        return None
    folder = executable.parent / "CharacterCreator"
    return folder if (folder / "menu.txt").is_file() else None


def read_kliff_look(folder: Path) -> CharacterCreatorLook:
    """Read the mod's files without changing them."""

    folder = Path(folder)

    def read(path: Path, required: bool) -> str:
        try:
            return path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            if required:
                raise CharacterCreatorError(f"{path} is missing; reinstall Character Creator.") from None
            return ""
        except OSError as error:
            raise CharacterCreatorError(f"{path} could not be read: {error}") from None

    return resolve_kliff_look(read(folder / "data.version", True), read(folder / "menu.txt", True),
                              read(folder / "profile.txt", False), read(folder / "identity.txt", False))


_BASE_LOOKS = {
    (0, 0): "Kliff is built on the male human base look.",
    (1, 0): "Kliff is built on the female human base look.",
    (0, 1): "Kliff is built on the male orc base look.",
    (1, 1): "Kliff is built on the female orc base look.",
    (0, 2): "Kliff is built on the male dwarf base look.",
    (1, 2): "Kliff is built on the female dwarf base look.",
    (0, 3): "Kliff is built on the male goblin base look.",
    (1, 3): "Kliff is built on the female goblin base look.",
}


def look_report_lines(look: CharacterCreatorLook) -> tuple[str, ...]:
    """What the mod changes that the FBX files do not carry."""
    lines = [_BASE_LOOKS[(look.gender, look.race)]]
    if look.scaled_body is not None:
        lines.append(f"Height {look.height_percent:+g}%: body scale {look.body_scale:g} becomes "
                     f"{look.scaled_body:.4g} in game; not applied to the FBX files.")
    else:
        lines.append(f"Height {look.height_percent:+g}%; not applied to the FBX files.")
    if look.head_scale is not None:
        lines.append(f"Head scale {look.head_scale:g}; not applied to the FBX files.")
    head = next((part.prefab for part in look.parts if part.slot == 1), "")
    if look.face_details and look.face_details != head:
        lines.append(f"Face details come from {look.face_details}; not exported.")
    if look.decoration_count:
        lines.append(f"{look.decoration_count} colour and slider values; not exported.")
    return tuple(lines)


def prefab_model_paths(data: bytes) -> tuple[str, ...]:
    """The PACs a ``.prefab`` names, in its own order."""
    from cdmw.core.prefab_binary import decode_prefab_binary

    paths = (item.text.replace("\\", "/").strip() for item in decode_prefab_binary(data).resource_strings())
    return tuple(dict.fromkeys(path for path in paths if path.casefold().endswith(".pac")))


def _normalized(path: str) -> str:
    return path.replace("\\", "/").strip("/").casefold()


def _current(candidates) -> ArchiveEntryDto | None:
    """The entry the game loads among copies of one path."""
    usable = [item for item in candidates if not str(item.override_state or "").casefold().startswith("shadowed")]
    active = [item for item in usable if item.is_active_override
              or str(item.override_state or "").casefold().startswith("active")]
    chosen = active or usable
    return chosen[0] if chosen else None


class KliffLookPreparation(QObject):
    """Find each part's prefab and descriptor, read them, then find the PACs and shape files they name.

    Emits ``ready(token, detail, notes)`` with a Finder selection for the parts
    that resolved; ``notes`` names any part that did not.
    """

    ready = Signal(int, object, object)
    failed = Signal(int, str)
    progress = Signal(int, str)

    def __init__(self, service: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        service.batch_ready.connect(self._batch)
        service.result_ready.connect(self._result)
        service.request_failed.connect(self._request_failed)
        service.request_cancelled.connect(self._request_cancelled)
        self._request = None
        self._token = 0
        self._look = None

    def cancel(self) -> None:
        self._look = None
        request, self._request = self._request, None
        if request:
            try:
                self._service.cancel(request)
            except (AttributeError, RuntimeError):
                pass

    def start(self, session_id: str, look: CharacterCreatorLook, token: int) -> None:
        self.cancel()
        self._session_id, self._look, self._token = session_id, look, token
        self._entries: dict[int, ArchiveEntryDto] = {}
        self._truncated = False
        self._notes: list[str] = []
        names = tuple(dict.fromkeys(f"{part.prefab}{extension}" for part in look.parts
                                    for extension in (".prefab", ".prefabdata_xml")))
        self.progress.emit(token, "Finding the look's prefabs…")
        self._submit("prefabs", lambda: self._service.resolve_entries(ArchiveLookupRequest(
            session_id, ArchiveLookupKind.BASENAMES, values=names, limit=_LOOKUP_LIMIT), ui_generation=token))

    def _submit(self, stage: str, call) -> None:
        self._stage = stage
        try:
            self._request = call()
        except Exception as error:
            self._fail(str(error) or type(error).__name__)

    def _batch(self, request: str, _operation: str, result: object) -> None:
        if request != self._request or self._look is None:
            return
        if isinstance(result, ArchiveLookupResult) and result.session_id == self._session_id:
            self._entries.update((entry.entry_id, entry) for entry in result.entries)
            self._truncated |= result.truncated
        elif isinstance(result, PrepareEntriesResult):
            self._prepared.update((item.entry.entry_id, item.prepared_path) for item in result.items)

    def _result(self, request: str, operation: str, result: object) -> None:
        if request != self._request or self._look is None:
            return
        self._batch(request, operation, result)
        self._request = None
        try:
            if self._stage == "prefabs":
                self._prefabs_found()
            elif self._stage == "read":
                self._prefabs_read()
            else:
                self._files_found()
        except CharacterCreatorError as error:
            self._fail(str(error))
        except Exception as error:
            self._fail(f"The look's prefabs could not be read: {error}")

    def _pick(self, by_basename: dict[str, list[ArchiveEntryDto]], basename: str) -> ArchiveEntryDto | None:
        candidates = by_basename.get(basename.casefold(), [])
        paths = {_normalized(entry.path) for entry in candidates}
        if len(paths) > 1:
            raise CharacterCreatorError(f"{basename} is at {len(paths)} archive paths; CDMW cannot tell which one the game loads.")
        return _current(candidates)

    def _prefabs_found(self) -> None:
        if self._truncated:
            raise CharacterCreatorError("The archive lookup for the look's prefabs was cut short.")
        by_basename: dict[str, list[ArchiveEntryDto]] = {}
        for entry in self._entries.values():
            by_basename.setdefault(PurePosixPath(_normalized(entry.path)).name, []).append(entry)
        self._found = []
        for part in self._look.parts:
            prefab = self._pick(by_basename, part.prefab + ".prefab")
            if prefab is None:
                self._notes.append(f"{part.prefab}.prefab is not in the loaded archives; that part is skipped.")
                continue
            self._found.append((part, prefab, self._pick(by_basename, part.prefab + ".prefabdata_xml")))
        if not self._found:
            raise CharacterCreatorError("None of the look's prefabs is in the loaded archives.")
        ids = tuple(dict.fromkeys(entry.entry_id for _part, prefab, descriptor in self._found
                                  for entry in (prefab, descriptor) if entry is not None))
        self._prepared: dict[int, str] = {}
        self.progress.emit(self._token, "Reading the look's prefabs…")
        self._submit("read", lambda: self._service.prepare_entries(
            PrepareEntriesRequest(self._session_id, ids), ui_generation=self._token))

    def _prefabs_read(self) -> None:
        from cdmw.core.skeleton_resolver import descriptor_shape_paths

        def read(entry: ArchiveEntryDto) -> bytes:
            prepared = self._prepared.get(entry.entry_id)
            if not prepared:
                raise CharacterCreatorError(f"{entry.path} was not prepared by the archive worker.")
            return Path(prepared).read_bytes()

        self._named = []
        for part, prefab, descriptor in self._found:
            models = prefab_model_paths(read(prefab))
            if not models:
                self._notes.append(f"{prefab.path} names no model; that part is skipped.")
                continue
            shapes = descriptor_shape_paths(read(descriptor).decode("utf-8", "ignore")) if descriptor is not None else ()
            self._named.append((part, prefab, descriptor, models, shapes))
        paths = tuple(dict.fromkeys(path for *_head, models, shapes in self._named for path in (*models, *shapes)))
        if not paths:
            raise CharacterCreatorError("The look's prefabs name no model.")
        self._entries = {}
        self._truncated = False
        self.progress.emit(self._token, "Finding the look's models and face shapes…")
        self._submit("files", lambda: self._service.resolve_entries(ArchiveLookupRequest(
            self._session_id, ArchiveLookupKind.EXACT_PATHS, values=paths, limit=_LOOKUP_LIMIT), ui_generation=self._token))

    def _files_found(self) -> None:
        if self._truncated:
            raise CharacterCreatorError("The archive lookup for the look's models was cut short.")
        by_path: dict[str, list[ArchiveEntryDto]] = {}
        for entry in self._entries.values():
            by_path.setdefault(_normalized(entry.path), []).append(entry)
        resolved = []
        for part, prefab, descriptor, model_paths, shape_paths in self._named:
            models = tuple(entry for path in model_paths if (entry := _current(by_path.get(_normalized(path), ()))))
            missing = [path for path in model_paths if not by_path.get(_normalized(path))]
            if missing:
                self._notes.append(f"Not in the loaded archives: {', '.join(missing)}")
            if not models:
                continue
            shapes = tuple(entry for path in shape_paths if (entry := _current(by_path.get(_normalized(path), ()))))
            resolved.append(CharacterCreatorResolvedPart(part, prefab, descriptor, models, shapes))
        if not resolved:
            raise CharacterCreatorError("None of the look's models is in the loaded archives.")
        self._look = None
        self.ready.emit(self._token, kliff_look_detail(self._session_id, tuple(resolved)), tuple(self._notes))

    def _request_failed(self, request: str, error: object) -> None:
        if request == self._request:
            self._request = None
            self._fail(str(getattr(error, "message", error)))

    def _request_cancelled(self, request: str) -> None:
        if request == self._request:
            self._request = None
            self._fail("Reading Kliff's Character Creator look was cancelled.")

    def _fail(self, message: str) -> None:
        if self._look is None:
            return
        self.cancel()
        self.failed.emit(self._token, message)
