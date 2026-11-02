"""Vanilla baseline extraction and golden-mod discovery.

The vanilla game is 134 GB across 33 packages. Phase 0 never scans that during replay:
it resolves the small set of paths the golden mods overwrite, extracts those once into a
pinned baseline directory, and hashes them. Every later step reads the baseline.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

def _install_root() -> Path:
    """Where the workspace lives, source tree or frozen build.

    A frozen build puts this module under `_internal/`, so a `__file__`-relative root resolves
    to `dist/<app>/_internal` and the baseline is written and looked for in the wrong place —
    which reads to the user as "no baseline" even when one exists. Matches
    `cdmw.app.bootstrap_reports.bootstrap_root`.
    """

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _install_root()

DEFAULT_GAME_ROOT = Path(r"C:\games\Steam\steamapps\common\Crimson Desert")
DEFAULT_GOLDEN_ROOT = Path(r"E:\Working mods\Placement and Animations")
DEFAULT_WORK_ROOT = REPO_ROOT / "workspace" / "placement_studio"

# Manager layouts differ in where the game-relative tree starts. CDUMM nests it under
# files/; the others put it at the package root. Anything outside these roots is
# packaging metadata, not game content.
_CONTENT_ROOTS = ("files",)
_GAME_TOP_LEVEL = frozenset({"character", "gamedata", "actionchart", "object", "ui", "effect"})

_METADATA_NAMES = frozenset({"manifest.json", "modinfo.json", "mod.json", "readme.txt", ".no_encrypt"})


def env_path(name: str, default: Path) -> Path:
    raw = str(os.environ.get(name, "") or "").strip()
    return Path(raw) if raw else default


def game_root() -> Path:
    return env_path("CDMW_PS_GAME_ROOT", DEFAULT_GAME_ROOT)


def golden_root() -> Path:
    return env_path("CDMW_PS_GOLDEN_ROOT", DEFAULT_GOLDEN_ROOT)


def work_root() -> Path:
    return env_path("CDMW_PS_WORK_ROOT", DEFAULT_WORK_ROOT)


def baseline_root() -> Path:
    return work_root() / "vanilla"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_game_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").lower()


# ── Golden corpus ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GoldenFile:
    """One content file inside a golden mod, mapped to its game-relative path."""

    game_path: str
    disk_path: Path
    size: int


# Mods layered on another mod rather than on vanilla. Their README states the base
# ("PHW/Damiane descriptor and socket placement based on CharacterCreator HumanFemale"),
# so vanilla replay cannot apply — the base bytes are not the game's.
_EXTERNAL_BASE_MARKERS = ("charactercreator",)


@dataclass(frozen=True, slots=True)
class GoldenMod:
    """A hand-built, in-game-verified mod used as an executable specification."""

    name: str
    group: str
    manager: str
    root: Path
    files: tuple[GoldenFile, ...] = field(default=())

    @property
    def key(self) -> str:
        return f"{self.group}/{self.name}"

    @property
    def external_base(self) -> str:
        lowered = self.name.lower()
        for marker in _EXTERNAL_BASE_MARKERS:
            if marker in lowered:
                return "CharacterCreator HumanFemale"
        return ""


def _manager_of(root: Path) -> str:
    name = root.name.upper()
    if (root / "files").is_dir() or (root / ".no_encrypt").exists():
        return "CDUMM"
    if name.endswith("- DMM") or (root / "modinfo.json").is_file():
        return "DMM"
    return "UNKNOWN"


def _content_base(root: Path) -> Path:
    for candidate in _CONTENT_ROOTS:
        nested = root / candidate
        if nested.is_dir():
            return nested
    return root


def discover_golden_mods(root: Optional[Path] = None) -> List[GoldenMod]:
    """Find every golden mod directory (a directory holding a game content tree)."""

    base = Path(root) if root is not None else golden_root()
    if not base.is_dir():
        raise FileNotFoundError(f"Golden corpus root not found: {base}")

    mods: List[GoldenMod] = []
    for group_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for mod_dir in sorted(p for p in group_dir.iterdir() if p.is_dir()):
            content = _content_base(mod_dir)
            if not any((content / top).is_dir() for top in _GAME_TOP_LEVEL):
                continue
            files: List[GoldenFile] = []
            for path in sorted(content.rglob("*")):
                if not path.is_file():
                    continue
                if path.name.lower() in _METADATA_NAMES:
                    continue
                rel = path.relative_to(content).as_posix()
                if rel.split("/", 1)[0].lower() not in _GAME_TOP_LEVEL:
                    continue
                files.append(GoldenFile(normalize_game_path(rel), path, path.stat().st_size))
            if files:
                mods.append(
                    GoldenMod(
                        name=mod_dir.name,
                        group=group_dir.name,
                        manager=_manager_of(mod_dir),
                        root=mod_dir,
                        files=tuple(files),
                    )
                )
    return mods


def golden_game_paths(mods: Sequence[GoldenMod]) -> List[str]:
    seen: set[str] = set()
    for mod in mods:
        for entry in mod.files:
            seen.add(entry.game_path)
    return sorted(seen)


# ── Vanilla baseline ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BaselineRecord:
    game_path: str
    sha256: str
    size: int
    package: str


class Baseline:
    """A pinned, hashed set of vanilla files extracted from the archives."""

    def __init__(self, root: Path, records: Mapping[str, BaselineRecord]) -> None:
        self._root = Path(root)
        self._records = dict(records)
        #: One sentence for the user when opening changed these copies, else "".
        self.note = ""

    @property
    def root(self) -> Path:
        return self._root

    def __contains__(self, game_path: str) -> bool:
        return normalize_game_path(game_path) in self._records

    def __len__(self) -> int:
        return len(self._records)

    def record(self, game_path: str) -> Optional[BaselineRecord]:
        return self._records.get(normalize_game_path(game_path))

    def paths(self) -> List[str]:
        return sorted(self._records)

    def read(self, game_path: str) -> bytes:
        key = normalize_game_path(game_path)
        if key not in self._records:
            raise KeyError(f"Not in pinned vanilla baseline: {game_path}")
        return (self._root / key).read_bytes()

    @classmethod
    def load(cls, root: Optional[Path] = None) -> "Baseline":
        base = Path(root) if root is not None else baseline_root()
        manifest = base / "baseline.json"
        if not manifest.is_file():
            raise FileNotFoundError(
                f"No pinned vanilla baseline at {base}. Run: placement_studio extract"
            )
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        records = {
            str(row["game_path"]): BaselineRecord(
                game_path=str(row["game_path"]),
                sha256=str(row["sha256"]),
                size=int(row["size"]),
                package=str(row.get("package", "")),
            )
            for row in payload.get("files", [])
        }
        return cls(base, records)


def archive_entry_sizes(suffix: str, *, contains: str = "", resident_catalogue=None) -> Dict[str, int]:
    """path -> uncompressed size, read from the archive tables without extracting anything."""

    wanted = suffix.lower()
    needle = contains.lower()
    found: Dict[str, int] = {}
    entries = (((entry.pamt_path.parent.name, entry) for entry in resident_catalogue.matching((wanted,), contains=needle))
               if resident_catalogue is not None else _iter_archive_entries(game_root()))
    for _package, entry in entries:
        path = normalize_game_path(entry.path)
        if path.endswith(wanted) and (not needle or needle in path):
            found[path] = int(getattr(entry, "orig_size", 0) or 0)
    return found


def archive_paths_matching(suffix: str, *, contains: str = "") -> List[str]:
    """Every archive path with a suffix, read from the tables without extracting anything."""

    wanted = suffix.lower()
    needle = contains.lower()
    found: set[str] = set()
    for _package, entry in _iter_archive_entries(game_root()):
        path = normalize_game_path(entry.path)
        if path.endswith(wanted) and (not needle or needle in path):
            found.add(path)
    return sorted(found)


def package_signature(root: Optional[Path] = None) -> List[list]:
    """What a cache built from the packages was built from: name, size and mtime.

    Shared rather than per-cache: the clip index, the wearables index and the
    extracted-content cache all go stale together, for the same reason, and three copies of
    this would be three chances to disagree.

    Covers the `.paz` archives as well as the `.pamt` tables. A cached row is a *location* —
    an offset and a length into a `.paz` — so a payload rewritten without its table changing
    is exactly the update that would be read back as a valid offset into different bytes.
    33 tables and 179 archives cost 8 ms to stat together, so the wider key is free.

    Nanosecond mtimes, not whole seconds: a rewrite inside the same second is otherwise
    invisible whenever the size happens to match. That is not sufficient on its own — an
    updater that preserves timestamps defeats any mtime scheme — which is why the callers
    also re-check the signature after a scan rather than trusting it once.
    """

    from cdmw.core.archive_format import discover_pamt_files

    base = Path(root) if root is not None else game_root()
    paths = set(discover_pamt_files(base))
    # Each DLC carries its own mount list beside the base game's; either one changing is an
    # update the caches have to see.
    for mount_list in (base / "meta/0.papgt", *base.glob("dlc/*/meta/0.papgt")):
        if mount_list.exists():
            paths.add(mount_list)
    try:
        paths |= set(base.rglob("*.paz"))
    except OSError:
        pass  # an unreadable tree signs as whatever was reachable; the scan will fail anyway

    signature: List[list] = []
    for package in sorted(paths):
        try:
            stat = package.stat()
        except OSError:
            continue
        signature.append([str(package), stat.st_size, stat.st_mtime_ns])
    return signature


def _package_label(root: Path, pamt: Path) -> str:
    """The table's folder, qualified by its DLC root when it has one.

    A DLC reuses the base game's folder names, so its `0009` labelled as plain `0009` reads
    as the base table that holds every character.
    """

    try:
        parts = Path(pamt).resolve().parent.relative_to(Path(root).resolve()).parts
    except (OSError, ValueError):
        return pamt.parent.name
    return "/".join(parts) if len(parts) > 1 else pamt.parent.name


def _iter_archive_entries(root: Path, *, on_error=None):
    """Every entry in every package table. A table that will not parse is skipped.

    `on_error` is called with `(pamt_path, exception)` for each skipped table. Skipping was
    always right for a *display* — one bad package should not empty the browser — but it is
    wrong to then persist the result: a transient read failure would be frozen into a cache
    and every later launch would serve the same incomplete index without retrying. Callers
    that store what they walked pass this and refuse to write when it fires.
    """

    from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt

    for pamt in discover_pamt_files(root):
        package = _package_label(Path(root), pamt)
        try:
            entries = parse_archive_pamt(pamt)
        except Exception as error:  # noqa: BLE001 - a bad package is not the end of the walk
            if on_error is not None:
                on_error(pamt, error)
            continue
        for entry in entries:
            yield package, entry


def extract_baseline(
    wanted: Iterable[str],
    *,
    out_root: Optional[Path] = None,
    on_log=None,
    resident_catalogue=None,
    existing: Optional[Baseline] = None,
    should_stop=None,
) -> Baseline:
    """Extract exactly the requested game paths from the archives into a pinned baseline."""

    from cdmw.core.archive_extraction import read_archive_entry_data

    log = on_log or (lambda _message: None)
    base = Path(out_root) if out_root is not None else baseline_root()
    if existing is not None and existing.root != base:
        raise ValueError("Cannot extend a different baseline directory")
    base.mkdir(parents=True, exist_ok=True)

    targets = {normalize_game_path(p) for p in wanted if str(p).strip()}
    records = {path: existing.record(path) for path in existing.paths()} if existing is not None else {}
    targets.difference_update(records)
    def check_cancelled():
        if should_stop is not None and should_stop():
            raise InterruptedError("Placement preparation cancelled")
    check_cancelled()
    log(f"Resolving {len(targets):,} path(s) across archive tables...")
    root = _source_root(resident_catalogue)
    signature = package_signature(root)
    located = _locate(targets, resident_catalogue)

    missing = sorted(targets - set(located))
    if resident_catalogue is not None:
        resident_catalogue.validate_sources()
    log(f"Resolved {len(located):,}; missing {len(missing):,}")

    failed: List[str] = []
    for index, (key, (package, entry)) in enumerate(sorted(located.items()), start=1):
        check_cancelled()
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the sweep
            failed.append(f"{key}: {exc}")
            continue
        check_cancelled()
        records[key] = _pin(base, key, data, package)
        if index % 25 == 0:
            log(f"  extracted {index:,}/{len(located):,}")

    check_cancelled()
    if resident_catalogue is not None:
        resident_catalogue.validate_sources()
    _write_manifest(base, records, root=root, signature=signature, requested=len(targets),
                    missing=missing, failed=failed, check_cancelled=check_cancelled)
    log(f"Baseline written: {len(records):,} file(s) at {base}")
    return Baseline(base, records)


def _source_root(resident_catalogue=None) -> Path:
    if resident_catalogue is not None:
        return Path(resident_catalogue.source.package_root)
    return game_root()


def _locate(targets, resident_catalogue=None) -> Dict[str, tuple]:
    """`path -> (package, entry)` as the game resolves each path: first in mount order wins.

    This used to keep the *highest* package name, which stopped meaning "the patch" once the
    DLC update put a second set of folders named 0000-0040 under `dlc/`.
    """

    located: Dict[str, tuple] = {}
    if resident_catalogue is not None:
        for key in sorted(targets):
            entry = resident_catalogue.active_entry(key)
            if entry is not None:
                located[key] = (_package_label(Path(resident_catalogue.source.package_root),
                                               Path(entry.pamt_path)), entry)
        return located
    # The mount lists decide what the game can see; a leftover mod folder they do not name
    # must not be pinned as vanilla.
    from .relationships import active_entries

    for package, entry in active_entries(game_root()):
        key = normalize_game_path(entry.path)
        if key in targets and key not in located:
            located[key] = (package, entry)
    return located


def _pin(base: Path, key: str, data: bytes, package: str) -> BaselineRecord:
    out_path = base / key
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = out_path.with_name(out_path.name + '.preparing')
    try:
        temporary.write_bytes(data)
        temporary.replace(out_path)
    finally:
        temporary.unlink(missing_ok=True)
    return BaselineRecord(key, sha256_bytes(data), len(data), package)


def _write_manifest(base: Path, records, *, root, signature, requested, missing, failed,
                    check_cancelled=lambda: None) -> None:
    manifest = {
        "format": "cdmw_placement_studio_baseline_v1",
        "game_root": str(root),
        # What the copies were taken from. `refresh_baseline` compares it with the installed
        # game on every open, so a game update cannot leave edits built on the old files.
        "signature": signature,
        "requested": requested,
        "extracted": len(records),
        "missing": missing,
        "failed": failed,
        "files": [
            {
                "game_path": record.game_path,
                "sha256": record.sha256,
                "size": record.size,
                "package": record.package,
            }
            for record in sorted(records.values(), key=lambda r: r.game_path)
        ],
    }
    check_cancelled()
    temporary = base / 'baseline.json.preparing'
    try:
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        check_cancelled()
        temporary.replace(base / 'baseline.json')
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class BaselineRefresh:
    """What `refresh_baseline` did to the pinned copies."""

    baseline: "Baseline"
    checked: bool = False
    changed: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()

    @property
    def updated(self) -> bool:
        return bool(self.changed or self.removed or self.added)

    def describe(self) -> str:
        if not self.updated:
            return "The game files Placement & Animations works from match the installed game."
        return (
            f"The installed game changed since Placement & Animations last read it: "
            f"{len(self.changed):,} file(s) updated, {len(self.removed):,} no longer in the "
            f"game, {len(self.added):,} newly found."
        )


def baseline_is_current(baseline: "Baseline", root: Optional[Path] = None) -> bool:
    """Whether the pinned copies were taken from the game as it is installed now."""

    stored = _stored_signature(baseline.root)
    return stored is not None and stored == package_signature(root)


def baseline_is_stale(baseline, root: Optional[Path] = None) -> bool:
    """True only when the copies are known to come from a game install other than this one.

    A baseline with no stored signature (a test fixture, or one taken before signatures) is
    not called stale here; `refresh_baseline` checks those on open.
    """

    base = getattr(baseline, "root", None)
    stored = _stored_signature(base) if base is not None else None
    if stored is None:
        return False
    if root is None:
        # Compared against the install the copies were taken from, not whatever the
        # environment points at now.
        try:
            recorded = json.loads((Path(base) / "baseline.json").read_text(encoding="utf-8"))
            root = Path(recorded["game_root"]) if recorded.get("game_root") else None
        except (OSError, ValueError, KeyError):
            root = None
    return stored != package_signature(root)


def _stored_signature(base: Path):
    try:
        payload = json.loads((Path(base) / "baseline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    signature = payload.get("signature")
    return signature if isinstance(signature, list) else None


def refresh_baseline(
    baseline: "Baseline",
    *,
    on_log=None,
    resident_catalogue=None,
    should_stop=None,
) -> BaselineRefresh:
    """Bring the pinned copies up to date with the installed game, when it has changed.

    The copies used to be taken once and trusted forever. After the October 2026 DLC update
    272 of 503 of them no longer matched the game -- every weapon prefab, both characters'
    descriptors, socket files and skeletons, and the action charts -- so every edit and every
    package was built on pre-update files and would have put them back into the game.

    Cheap when nothing changed: the archive signature is compared with the one stored at
    extraction. When it differs (or a baseline predates the signature), every pinned path is
    read again from the game, the changed ones are rewritten, the ones the game no longer
    ships are dropped, and paths that were missing are picked up if the game has them now.
    """

    log = on_log or (lambda _message: None)

    def check_cancelled():
        if should_stop is not None and should_stop():
            raise InterruptedError("Placement preparation cancelled")

    from cdmw.core.archive_extraction import read_archive_entry_data

    base = baseline.root
    root = _source_root(resident_catalogue)
    signature = package_signature(root)
    if _stored_signature(base) == signature:
        return BaselineRefresh(baseline)
    try:
        payload = json.loads((Path(base) / "baseline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    previously_missing = [normalize_game_path(p) for p in payload.get("missing", ()) or ()]
    wanted = set(baseline.paths()) | set(previously_missing)
    log(f"Checking {len(wanted):,} game file(s) against the installed game...")
    located = _locate(wanted, resident_catalogue)
    records = {path: baseline.record(path) for path in baseline.paths()}
    changed: List[str] = []
    added: List[str] = []
    failed: List[str] = []
    for index, (key, (package, entry)) in enumerate(sorted(located.items()), start=1):
        check_cancelled()
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the sweep
            failed.append(f"{key}: {exc}")
            continue
        previous = records.get(key)
        digest = sha256_bytes(data)
        if previous is not None and previous.sha256 == digest:
            if previous.package != package:
                records[key] = BaselineRecord(key, digest, len(data), package)
            continue
        records[key] = _pin(base, key, data, package)
        (changed if previous is not None else added).append(key)
        if index % 50 == 0:
            log(f"  checked {index:,}/{len(located):,}")
    # A copy that could not be read again is dropped with the ones the game no longer ships:
    # keeping it would mark an unchecked old file as current. It goes back on the missing
    # list, and the signature is left unset, so the next open tries it again.
    unreadable = {line.split(": ", 1)[0] for line in failed}
    removed = sorted(path for path in baseline.paths()
                     if path not in located or path in unreadable)
    for path in removed:
        records.pop(path, None)
    check_cancelled()
    if resident_catalogue is not None:
        resident_catalogue.validate_sources()
    if package_signature(root) != signature:
        raise RuntimeError("The game was updated while its files were being checked; reopen to retry")
    missing = sorted((wanted - set(located)) | unreadable)
    _write_manifest(base, records, root=root, signature=None if failed else signature,
                    requested=int(payload.get("requested", len(wanted)) or len(wanted)),
                    missing=missing, failed=failed, check_cancelled=check_cancelled)
    # Only once the manifest no longer lists them: deleting first and then failing would
    # leave a manifest naming files that are gone.
    for path in removed:
        try:
            (Path(base) / path).unlink()
        except OSError:
            pass
    refreshed = Baseline(base, records)
    result = BaselineRefresh(refreshed, True, tuple(sorted(changed)), tuple(removed), tuple(sorted(added)))
    log(result.describe())
    return result
