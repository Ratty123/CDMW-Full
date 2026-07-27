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
    if (root / "mod.json").is_file():
        return "JMM"
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


def archive_entry_sizes(suffix: str, *, contains: str = "") -> Dict[str, int]:
    """path -> uncompressed size, read from the archive tables without extracting anything."""

    wanted = suffix.lower()
    needle = contains.lower()
    found: Dict[str, int] = {}
    for _package, entry in _iter_archive_entries(game_root()):
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


def _iter_archive_entries(root: Path):
    from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt

    for pamt in discover_pamt_files(root):
        package = pamt.parent.name
        try:
            entries = parse_archive_pamt(pamt)
        except Exception:
            continue
        for entry in entries:
            yield package, entry


def extract_baseline(
    wanted: Iterable[str],
    *,
    out_root: Optional[Path] = None,
    on_log=None,
) -> Baseline:
    """Extract exactly the requested game paths from the archives into a pinned baseline."""

    from cdmw.core.archive_extraction import read_archive_entry_data

    log = on_log or (lambda _message: None)
    base = Path(out_root) if out_root is not None else baseline_root()
    base.mkdir(parents=True, exist_ok=True)

    targets = {normalize_game_path(p) for p in wanted if str(p).strip()}
    log(f"Resolving {len(targets):,} path(s) across archive tables...")

    # Later packages patch earlier ones, so the highest package wins.
    located: Dict[str, tuple[str, object]] = {}
    for package, entry in _iter_archive_entries(game_root()):
        key = normalize_game_path(entry.path)
        if key not in targets:
            continue
        previous = located.get(key)
        if previous is None or package >= previous[0]:
            located[key] = (package, entry)

    missing = sorted(targets - set(located))
    log(f"Resolved {len(located):,}; missing {len(missing):,}")

    records: Dict[str, BaselineRecord] = {}
    failed: List[str] = []
    for index, (key, (package, entry)) in enumerate(sorted(located.items()), start=1):
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the sweep
            failed.append(f"{key}: {exc}")
            continue
        out_path = base / key
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        records[key] = BaselineRecord(key, sha256_bytes(data), len(data), package)
        if index % 25 == 0:
            log(f"  extracted {index:,}/{len(located):,}")

    manifest = {
        "format": "cdmw_placement_studio_baseline_v1",
        "game_root": str(game_root()),
        "requested": len(targets),
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
    (base / "baseline.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"Baseline written: {len(records):,} file(s) at {base}")
    return Baseline(base, records)
