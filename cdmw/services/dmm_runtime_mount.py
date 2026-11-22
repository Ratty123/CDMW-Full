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
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

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
    ".pabgb", ".pabgh", ".paloc", ".papgt", ".pamt", ".paz", ".pathc", ".paver", ".papk",
})
DMM_MERGED_LABEL = "merged by DMM"
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
        self._copy_root = Path(copy_root) if copy_root is not None else None
        self._enabled = True
        self._mounts: dict[str, tuple[tuple[int, int] | None, DmmRuntimeMount | None, str]] = {}
        self._copies: dict[tuple[str, int, int], PreparedDmmFile] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

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
        manifest = root / MANIFEST_RELATIVE_PATH
        try:
            stat = manifest.stat()
            stamp: tuple[int, int] | None = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            stamp = None
        key = str(root).casefold()
        with self._lock:
            cached = self._mounts.get(key)
            if cached is not None and cached[0] == stamp:
                return cached[1], cached[2]
            mount, error = None, ""
            if stamp is not None:
                try:
                    mount = read_runtime_mount(root)
                except (OSError, UnicodeDecodeError, DmmManifestError) as exc:
                    error = f"DMM's runtime manifest cannot be read: {exc}"
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
        with self._lock:
            known = self._copies.get(key)
            if known is not None and known.path.is_file() and known.path.stat().st_size == known.size:
                return known
        prepared = self._copy(source, served)
        with self._lock:
            self._copies[key] = prepared
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
            else:
                os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        self._prune(root, keep=target)
        return PreparedDmmFile(target, size, sha, served.mod)

    @staticmethod
    def _prune(root: Path, *, keep: Path) -> None:
        try:
            files = [path for path in root.glob("*/*") if path.is_file()]
            total = sum(path.stat().st_size for path in files)
            if total <= COPY_FOLDER_LIMIT_BYTES:
                return
            for path in sorted(files, key=lambda item: item.stat().st_mtime_ns):
                if total <= COPY_FOLDER_LIMIT_BYTES:
                    break
                if path == keep:
                    continue
                size = path.stat().st_size
                path.unlink(missing_ok=True)
                total -= size
        except OSError:
            return

    def clear_copies(self) -> None:
        with self._lock:
            self._copies.clear()
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
