"""Read the mods DMM serves to the game at run time; never change anything of DMM's.

DMM 5 no longer writes its mods into the game's archive folders. It writes
``bin64/dmm/manifest.tsv`` and its runtime plugin (``bin64/DmmRuntime.asi``) hands
the listed files to the game's pack readers in place of the game's own:

    # Written by DMM. ...
    dmm-runtime<TAB>1
    build<TAB><hex of meta/0.paver><TAB><size of CrimsonDesert.exe>
    file<TAB><game path><TAB><full path of the file DMM serves>

The game folders stay vanilla, so CDMW's archive catalogue alone shows vanilla
files. With this overlay on, a file CDMW prepares from the catalogue (previews,
the Mesh Editor) is replaced by the file DMM serves for
the same game path, as the game would see it. The served file is copied into
CDMW's workspace first, so a later mount in DMM cannot change it under an open
editor. Game tables and archive metadata always stay the game's own: edits made
from them would otherwise copy another mod's rows into the new mod.

The plugin serves nothing when the game updated after the mount, and neither
does this overlay. This is experimental: it is checked against DMM 5.0.4 and
DmmRuntime 1.3.1 only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from stat import S_ISREG
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Mapping

MANIFEST_RELATIVE_PATH = Path("bin64") / "dmm" / "manifest.tsv"
DMM_BUILT_FILES_RELATIVE_PATH = Path("bin64") / "dmm" / "files"
SHOW_MOUNTED_MODS_SETTING = "dmm/show_mounted_mods"
SUPPORTED_MANIFEST_VERSION = 1
#: DMM's runtime manifest lists a few hundred to a few thousand files.
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_SERVED_FILE_BYTES = 2 * 1024 * 1024 * 1024
#: Copies kept for prepared entries; the oldest go first above this.
COPY_FOLDER_LIMIT_BYTES = 4 * 1024 * 1024 * 1024
COPY_FOLDER_NAME = "dmm-mounted"
#: Always the game's own, even when DMM serves a changed copy.
KEEP_GAME_EXTENSIONS = frozenset({
    ".pabgb", ".pabgh", ".staticinfobody", ".staticinfoheader", ".pappt",
    ".paloc", ".papgt", ".pamt", ".paz", ".pathc", ".paver", ".papk",
})
DMM_MERGED_LABEL = "merged by DMM"
#: The prepared-note part that marks a file DMM serves (``DMM mod: <mod>``).
DMM_NOTE_PREFIX = "DMM mod:"
_GROUP_FOLDER = re.compile(r"\d{4}")


class DmmManifestError(ValueError):
    """The manifest cannot be read the way DmmRuntime reads it."""


@dataclass(frozen=True, slots=True)
class DmmServedFile:
    game_path: str
    source: Path
    mod: str


@dataclass(frozen=True, slots=True)
class DmmRuntimeMount:
    """One manifest as read: what DMM serves and whether it serves anything now."""

    game_root: Path
    manifest_path: Path
    build: str
    exe_size: int
    files: Mapping[str, DmmServedFile] = field(default_factory=dict)
    #: Empty when the plugin serves the files; otherwise why it serves nothing.
    problem: str = ""

    @property
    def serving(self) -> bool:
        return not self.problem and bool(self.files)

    @property
    def mods(self) -> tuple[str, ...]:
        return tuple(sorted({served.mod for served in self.files.values()}, key=str.casefold))


def normalized_game_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/").casefold()


def is_dmm_note(note: object) -> bool:
    """Whether a prepared note (comma-joined parts) says DMM serves the file."""

    return any(part.strip().startswith(DMM_NOTE_PREFIX) for part in str(note or "").split(","))


def is_dmm_added_entry(entry: object) -> bool:
    """An entry for a file a DMM mod adds: the game has no file of its own there.

    Such an entry names DMM's manifest as its source and CDMW's copy as its data.
    The source alone decides: an edited result of it keeps the source but gets
    the Mesh Editor's note.
    """

    pamt = Path(str(getattr(entry, "pamt_path", "") or ""))
    return (pamt.name.casefold() == MANIFEST_RELATIVE_PATH.name
            and pamt.parent.name.casefold() == MANIFEST_RELATIVE_PATH.parent.name
            and pamt.parent.parent.name.casefold() == MANIFEST_RELATIVE_PATH.parent.parent.name)


def _file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _source_path(text: str) -> Path:
    """The served file's path as Windows writes it, usable on this system."""

    text = text.strip()
    if os.name == "nt" or not re.match(r"^[A-Za-z]:[\\/]", text):
        return Path(text)
    return Path(PureWindowsPath(text).as_posix())


def mod_label(source_text: str, game_path: str) -> str:
    """The DMM mod a served file comes from, as DMM's mount log names it."""

    parts = [part for part in re.split(r"[\\/]+", source_text.strip()) if part]
    tail = [part for part in game_path.replace("\\", "/").split("/") if part]
    lowered = [part.casefold() for part in parts]
    if len(parts) > len(tail) and lowered[-len(tail):] == [part.casefold() for part in tail]:
        parts = parts[:-len(tail)]
        lowered = lowered[:-len(tail)]
    if lowered[-3:] == ["bin64", "dmm", "files"]:
        return DMM_MERGED_LABEL
    if parts and _GROUP_FOLDER.fullmatch(parts[-1]):
        parts = parts[:-1]
        lowered = lowered[:-1]
    for anchor in ("archive_cache", "mods"):
        if anchor in lowered:
            index = len(lowered) - 1 - lowered[::-1].index(anchor)
            named = parts[index + 1:]
            if named:
                return "/".join(named)
    return parts[-1] if parts else "DMM"


def installed_build(game_root: Path) -> tuple[str, int]:
    """meta/0.paver as hex and the size of the game's exe, as the plugin compares them."""

    paver = (Path(game_root) / "meta" / "0.paver").read_bytes()
    exe = Path(game_root) / "bin64" / "CrimsonDesert.exe"
    return paver.hex(), exe.stat().st_size


def read_runtime_mount(game_root: Path | str) -> DmmRuntimeMount | None:
    """DMM's runtime manifest for this game folder, or None when nothing is mounted."""

    game_root = Path(game_root)
    manifest = game_root / MANIFEST_RELATIVE_PATH
    if not manifest.is_file():
        return None
    if manifest.is_symlink():
        raise DmmManifestError(f"{manifest} is a link; DMM writes it as a file.")
    if manifest.stat().st_size > MAX_MANIFEST_BYTES:
        raise DmmManifestError(f"{manifest} is unexpectedly large.")
    text = manifest.read_bytes().decode("utf-8-sig")
    version = None
    build = ""
    exe_size = -1
    files: dict[str, DmmServedFile] = {}
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        kind = fields[0]
        if version is None:
            if kind != "dmm-runtime" or len(fields) < 2:
                raise DmmManifestError(f"Manifest line {number} is not the dmm-runtime version line.")
            try:
                version = int(fields[1])
            except ValueError as exc:
                raise DmmManifestError(f"Manifest line {number} has no version number.") from exc
            if version != SUPPORTED_MANIFEST_VERSION:
                raise DmmManifestError(
                    f"DMM's runtime manifest is version {version}; CDMW reads version {SUPPORTED_MANIFEST_VERSION}.")
            continue
        if kind == "build":
            if len(fields) < 3:
                raise DmmManifestError(f"Manifest line {number} is not a build line.")
            build = fields[1].strip().casefold()
            try:
                exe_size = int(fields[2])
            except ValueError as exc:
                raise DmmManifestError(f"Manifest line {number} has no exe size.") from exc
            continue
        if kind == "file":
            if not build:
                raise DmmManifestError(f"Manifest line {number} lists a file before the build line.")
            if len(fields) < 3 or not fields[1].strip() or not fields[2].strip():
                raise DmmManifestError(f"Manifest line {number} is not a file line.")
            key = normalized_game_path(fields[1])
            parts = PurePosixPath(key).parts
            if not parts or ".." in parts or ":" in key:
                raise DmmManifestError(f"Manifest line {number} names an invalid game path.")
            # The plugin keeps the first line for a path, like the game's mount order.
            files.setdefault(key, DmmServedFile(fields[1].replace("\\", "/").strip().strip("/"),
                                                _source_path(fields[2]),
                                                mod_label(fields[2], fields[1])))
            continue
        # Lines this reader does not know (texture tables) change no file CDMW prepares.
    if version is None:
        raise DmmManifestError("DMM's runtime manifest has no dmm-runtime line.")
    if not build:
        raise DmmManifestError("DMM's runtime manifest has no build line.")
    problem = ""
    try:
        current_build, current_exe_size = installed_build(game_root)
    except OSError:
        problem = "CDMW could not read meta/0.paver or the game's exe, so DMM's mount cannot be checked."
    else:
        if (current_build, current_exe_size) != (build, exe_size):
            problem = ("DMM mounted these mods for another game build. The game has updated since, so DMM "
                       "serves nothing until you mount again in DMM.")
    return DmmRuntimeMount(game_root, manifest, build, exe_size, files, problem)


@dataclass(frozen=True, slots=True)
class PreparedDmmFile:
    path: Path
    size: int
    sha256: str
    mod: str


class DmmMountOverlay:
    """The served files for one game folder, reread when DMM writes a new manifest."""

    def __init__(self, copy_root: Path | str | None = None) -> None:
        self._lock = threading.RLock()
        self._prepare_lock = threading.Lock()
        self._copy_root = Path(copy_root) if copy_root is not None else None
        self._enabled = True
        self._mounts: dict[str, tuple[tuple[object, ...] | None, DmmRuntimeMount | None, str]] = {}
        self._roots: dict[str, Path] = {}
        self._copies: dict[tuple[str, int, int], PreparedDmmFile] = {}
        #: Bytes in the copy folder as last counted; None until counted once.
        self._copy_bytes: int | None = None
        #: Changes whenever what the overlay serves may have changed.
        self._generation = 0
        self._listeners: list[object] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def generation(self) -> int:
        return self._generation

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        with self._lock:
            self._enabled = enabled
            self._generation += 1
        self._notify()

    def add_listener(self, callback) -> None:
        """``callback()`` runs on the caller's thread after a toggle or Check again."""

        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self) -> None:
        for callback in tuple(self._listeners):
            try:
                callback()
            except Exception:  # noqa: BLE001 - one stale listener must not stop the others
                continue

    def refresh(self, game_root: Path | str | None = None) -> None:
        """Read DMM's manifest and the game's build again (Check again), then tell listeners."""

        with self._lock:
            self._mounts.clear()
            self._generation += 1
        if game_root is not None and str(game_root).strip():
            self.mount(game_root)
        self._notify()

    def state_token(self, game_root: Path | str | None = None) -> tuple[object, ...]:
        """Changes whenever what the overlay serves may have changed; for cache keys.

        Rechecks the manifest, ``meta/0.paver`` and the game's exe of every game
        folder read so far (a few file stats), so a remount in DMM or a game
        update is noticed without Check again.
        """

        with self._lock:
            roots = list(self._roots.values())
        if game_root is not None and str(game_root).strip():
            roots.append(Path(str(game_root)).expanduser())
        for root in roots:
            self.mount(root)
        return ("dmm-overlay", self._enabled, self._generation)

    def copy_root(self) -> Path:
        if self._copy_root is None:
            from cdmw.app.app_folder import workspace_folder

            self._copy_root = workspace_folder() / COPY_FOLDER_NAME
        return self._copy_root

    def mount(self, game_root: Path | str) -> tuple[DmmRuntimeMount | None, str]:
        """The current mount for ``game_root`` and why it cannot be read, if it cannot."""

        root = Path(str(game_root or "")).expanduser()
        if not str(game_root or "").strip():
            return None, ""
        manifest_stamp = _file_stamp(root / MANIFEST_RELATIVE_PATH)
        # The plugin compares the mount's build with meta/0.paver and the exe, so a
        # game update changes what it serves although the manifest stays the same.
        stamp: tuple[object, ...] | None = None if manifest_stamp is None else (
            manifest_stamp, _file_stamp(root / "meta" / "0.paver"),
            _file_stamp(root / "bin64" / "CrimsonDesert.exe"))
        key = str(root).casefold()
        with self._lock:
            self._roots.setdefault(key, root)
            cached = self._mounts.get(key)
            if cached is not None and cached[0] == stamp:
                return cached[1], cached[2]
            mount, error = None, ""
            if stamp is not None:
                try:
                    mount = read_runtime_mount(root)
                except (OSError, UnicodeDecodeError, DmmManifestError) as exc:
                    error = f"DMM's runtime manifest cannot be read: {exc}"
            if cached is not None:
                self._generation += 1
            self._mounts[key] = (stamp, mount, error)
            return mount, error

    def served_file(self, game_root: Path | str, game_path: str) -> DmmServedFile | None:
        if not self._enabled:
            return None
        if PurePosixPath(normalized_game_path(game_path)).suffix in KEEP_GAME_EXTENSIONS:
            return None
        mount, _error = self.mount(game_root)
        if mount is None or not mount.serving:
            return None
        return mount.files.get(normalized_game_path(game_path))

    def serves_any(self, game_root: Path | str, game_paths: Iterable[str]) -> bool:
        """Whether DMM serves one of ``game_paths`` that the overlay would show; no file reads."""

        if not self._enabled:
            return False
        mount, _error = self.mount(game_root)
        if mount is None or not mount.serving:
            return False
        for game_path in game_paths:
            key = normalized_game_path(game_path)
            if key in mount.files and PurePosixPath(key).suffix not in KEEP_GAME_EXTENSIONS:
                return True
        return False

    def prepare(self, game_root: Path | str, game_path: str) -> PreparedDmmFile | None:
        """A private copy of the file DMM serves for ``game_path``, or None."""

        served = self.served_file(game_root, game_path)
        if served is None:
            return None
        source = served.source
        if source.is_symlink() or not source.is_file():
            return None
        if source.name.casefold() != PurePosixPath(served.game_path).name.casefold():
            return None
        stat = source.stat()
        if stat.st_size > MAX_SERVED_FILE_BYTES:
            return None
        key = (str(source).casefold(), stat.st_size, stat.st_mtime_ns)
        # Previews, exports and Files DMM adds prepare from their own threads. One at a
        # time, so a prune never deletes a copy that is made but not yet registered.
        with self._prepare_lock:
            with self._lock:
                known = self._copies.get(key)
            if known is not None and known.path.is_file() and known.path.stat().st_size == known.size:
                return known
            prepared = self._copy(source, served)
            with self._lock:
                self._copies[key] = prepared
            self._prune(keep=(prepared.path,))
        return prepared

    def _copy(self, source: Path, served: DmmServedFile) -> PreparedDmmFile:
        root = self.copy_root()
        root.mkdir(parents=True, exist_ok=True)
        suffix = PurePosixPath(served.game_path).suffix.casefold()
        handle, temporary_name = tempfile.mkstemp(prefix=".copy-", dir=root)
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(handle, "wb") as output, source.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    output.write(block)
                    size += len(block)
            sha = digest.hexdigest()
            target = root / sha[:2] / f"{sha}{suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file() and target.stat().st_size == size:
                temporary.unlink(missing_ok=True)
                try:
                    os.utime(target)  # a reused copy counts as recent when pruning
                except OSError:
                    pass
            else:
                os.replace(temporary, target)
                with self._lock:
                    if self._copy_bytes is not None:
                        self._copy_bytes += size
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return PreparedDmmFile(target, size, sha, served.mod)

    def _prune(self, *, keep: Iterable[Path] = ()) -> None:
        """Delete the oldest copies above the folder limit.

        The folder is counted once and the count kept up to date, so a copy costs
        no folder walk until the limit is passed. Copies handed out in this run go
        last, and ``keep`` never.
        """
        root = self.copy_root()
        with self._lock:
            known = self._copy_bytes
            handed_out = {str(item.path).casefold() for item in self._copies.values()}
        if known is not None and known <= COPY_FOLDER_LIMIT_BYTES:
            return
        files: list[tuple[Path, int, int]] = []
        try:
            for path in root.rglob("*"):
                if path.name.startswith(".copy-"):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if S_ISREG(stat.st_mode):
                    files.append((path, stat.st_size, stat.st_mtime_ns))
        except OSError:
            return
        total = sum(size for _path, size, _mtime in files)
        if total > COPY_FOLDER_LIMIT_BYTES:
            protected = {str(path).casefold() for path in keep}
            order = sorted(files, key=lambda item: (str(item[0]).casefold() in handed_out, item[2]))
            for path, size, _mtime in order:
                if total <= COPY_FOLDER_LIMIT_BYTES:
                    break
                if str(path).casefold() in protected:
                    continue
                try:
                    path.unlink()
                except OSError:
                    continue
                total -= size
                if path.parent.parent != root and path.parent != root:
                    try:
                        path.parent.rmdir()  # a folder an earlier version named a copy in, now empty
                    except OSError:
                        pass
        with self._lock:
            self._copy_bytes = total

    def clear_copies(self) -> None:
        with self._lock:
            self._copies.clear()
            self._copy_bytes = None
            root = self._copy_root
        if root is not None and root.is_dir():
            shutil.rmtree(root, ignore_errors=True)


_overlay: DmmMountOverlay | None = None


def setting_enabled(settings: object) -> bool:
    value = settings.value(SHOW_MOUNTED_MODS_SETTING, True)
    if isinstance(value, str):
        return value.strip().casefold() not in {"false", "0", "no", "off"}
    return bool(value)


def current_overlay() -> DmmMountOverlay:
    """The app's overlay, on unless Settings turned it off."""

    global _overlay
    if _overlay is None:
        overlay = DmmMountOverlay()
        try:
            from cdmw.services.settings_service import app_settings

            overlay.set_enabled(setting_enabled(app_settings()))
        except Exception:  # noqa: BLE001 - an unreadable settings file keeps the default
            pass
        _overlay = overlay
    return _overlay


def _reset_for_tests(overlay: DmmMountOverlay | None = None) -> None:
    global _overlay
    _overlay = overlay


def describe_mount(game_root: Path | str, overlay: DmmMountOverlay | None = None) -> dict[str, object]:
    """What DMM has mounted for this game folder, as Settings and the AI tool report it."""

    overlay = overlay or current_overlay()
    mount, error = overlay.mount(game_root)
    if not str(game_root or "").strip():
        state, message = "no_game_folder", "Choose the game folder first."
    elif error:
        state, message = "unreadable", error
    elif mount is None:
        state, message = "not_mounted", "DMM has nothing mounted at run time. CDMW shows the game's own files."
    elif mount.problem:
        state, message = "stale", mount.problem
    elif not overlay.enabled:
        state, message = "off", f"DMM serves {len(mount.files):,} file(s); CDMW shows the game's own files (turned off)."
    else:
        state = "serving"
        message = (f"DMM serves {len(mount.files):,} file(s) from {len(mount.mods):,} mod(s). CDMW shows them in "
                   "place of the game's files when it opens or previews them. Game tables stay the game's own.")
    mods: dict[str, int] = {}
    for served in (mount.files.values() if mount is not None else ()):
        mods[served.mod] = mods.get(served.mod, 0) + 1
    return {
        "state": state,
        "message": message,
        "enabled": overlay.enabled,
        "manifest": str(Path(str(game_root)) / MANIFEST_RELATIVE_PATH) if str(game_root or "").strip() else "",
        "files": len(mount.files) if mount is not None else 0,
        "mods": [{"mod": name, "files": count} for name, count in sorted(mods.items(), key=lambda item: item[0].casefold())],
    }


@dataclass(frozen=True, slots=True)
class DmmExportSwap:
    game_path: str
    output_path: Path
    mod: str
    size: int
    sha256: str


def _write_over(target: Path, source: Path) -> None:
    handle, temporary_name = tempfile.mkstemp(prefix=".dmm-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as output, source.open("rb") as stream:
            shutil.copyfileobj(stream, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def exported_files(destination: Path, manifest_path: str | None,
                   items: Iterable[tuple[str, str | None, str]], items_complete: bool) -> tuple[list[tuple[str, Path]], str]:
    """(game path, written file) for every file an export wrote, and why the list may be short.

    The export manifest lists every written file; without one the streamed items are
    used, which the worker stops reporting after a few thousand.
    """
    destination = Path(destination)
    if manifest_path:
        try:
            document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            rows = document.get("entries") if isinstance(document, dict) else None
            if isinstance(rows, list):
                files = [(str(row["path"]), destination / str(row["output_path"]))
                         for row in rows if isinstance(row, dict) and row.get("path") and row.get("output_path")]
                return files, ""
        except (OSError, ValueError, KeyError, TypeError):
            pass
    files = [(path, Path(output)) for path, output, status in items
             if output and status in {"exported", "renamed"}]
    return files, "" if items_complete else "The export listed only part of its files, so DMM's versions may not replace all of them."


def apply_to_export(game_root: Path | str, destination: Path | str, files: Iterable[tuple[str, Path]],
                    manifest_path: str | None = None,
                    overlay: DmmMountOverlay | None = None) -> list[DmmExportSwap]:
    """Write DMM's served file over each exported file DMM serves (experimental).

    Only files inside ``destination`` are replaced. The export manifest then records,
    for each replaced file, the DMM mod and the bytes now in the folder.
    """
    overlay = overlay or current_overlay()
    if not overlay.enabled:
        return []
    root = Path(destination).resolve()
    swaps: list[DmmExportSwap] = []
    for game_path, output in files:
        try:
            prepared = overlay.prepare(game_root, game_path)
            if prepared is None:
                continue
            target = Path(output).resolve()
            if not target.is_relative_to(root) or not target.is_file() or target.is_symlink():
                continue
            _write_over(target, prepared.path)
        except OSError:
            continue
        swaps.append(DmmExportSwap(game_path, target, prepared.mod, prepared.size, prepared.sha256))
    if swaps and manifest_path:
        _note_swaps_in_manifest(Path(manifest_path), swaps, root)
    return swaps


def _note_swaps_in_manifest(manifest: Path, swaps: list[DmmExportSwap], root: Path) -> None:
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    rows = document.get("entries") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        return
    by_output = {swap.output_path.relative_to(root).as_posix().casefold(): swap for swap in swaps}
    for row in rows:
        if not isinstance(row, dict):
            continue
        swap = by_output.get(str(row.get("output_path", "")).replace("\\", "/").casefold())
        if swap is not None:
            row["dmm_mod"] = swap.mod
            row["dmm_size"] = swap.size
            row["dmm_sha256"] = swap.sha256
    document["dmm_runtime_mount"] = {"note": "Files with dmm_mod are the files DMM serves the game, not the game's own.",
                                     "replaced": len(swaps)}
    temporary = manifest.with_name(manifest.name + ".dmm-tmp")
    try:
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, manifest)
    except OSError:
        temporary.unlink(missing_ok=True)


MAX_ADDED_DEPENDENCIES = 256
_MAX_SCANNED_BYTES = 64 * 1024 * 1024


def added_entry(mount: DmmRuntimeMount, served: DmmServedFile, prepared: PreparedDmmFile):
    """A prepared ``ArchiveEntry`` for a file a DMM mod adds, read from CDMW's copy.

    It names DMM's manifest as its source (:func:`is_dmm_added_entry`); the game
    has no file of its own at that path.
    """
    from cdmw.models import ArchiveEntry

    return ArchiveEntry(path=served.game_path, pamt_path=mount.manifest_path, paz_file=prepared.path,
                        offset=0, comp_size=prepared.size, orig_size=prepared.size, flags=0, paz_index=0,
                        prepared_path=prepared.path, prepared_sha256=prepared.sha256,
                        prepared_note=f"{DMM_NOTE_PREFIX} {prepared.mod}",
                        prepared_size=prepared.size)


def added_dependency_entries(game_root: Path | str, entries: Iterable[object], *,
                             overlay: DmmMountOverlay | None = None) -> list[object]:
    """Files DMM serves that ``entries`` lack, named by the DMM files in ``entries``.

    Only a file DMM serves can name a file a mod adds, so only those are searched,
    then the added files themselves, a few rounds deep. Each found file becomes a
    prepared ``ArchiveEntry`` read from CDMW's copy (experimental).
    """
    overlay = overlay or current_overlay()
    mount, _error = overlay.mount(game_root)
    if not overlay.enabled or mount is None or not mount.serving:
        return []
    entries = list(entries)
    known = {normalized_game_path(getattr(entry, "path", "")) for entry in entries}
    candidates = {key: served for key, served in mount.files.items()
                  if key not in known and PurePosixPath(key).suffix not in KEEP_GAME_EXTENSIONS}
    if not candidates:
        return []
    pending = [entry for entry in entries if is_dmm_note(getattr(entry, "prepared_note", ""))]
    added: list[object] = []
    for _round in range(4):
        if not pending or not candidates or len(added) >= MAX_ADDED_DEPENDENCIES:
            break
        texts = []
        for entry in pending:
            path = getattr(entry, "prepared_path", None)
            try:
                if path is not None and Path(path).stat().st_size <= _MAX_SCANNED_BYTES:
                    texts.append(Path(path).read_bytes().lower())
            except OSError:
                continue
        pending = []
        for key, served in tuple(candidates.items()):
            name = PurePosixPath(key).name.encode("utf-8", "ignore")
            if not name or not any(name in text for text in texts):
                continue
            del candidates[key]
            try:
                prepared = overlay.prepare(game_root, served.game_path)
            except OSError:
                prepared = None
            if prepared is None:
                continue
            entry = added_entry(mount, served, prepared)
            added.append(entry)
            pending.append(entry)
            if len(added) >= MAX_ADDED_DEPENDENCIES:
                break
    return added
