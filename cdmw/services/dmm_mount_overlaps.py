"""Read-only enabled-mod overlap and mount-sync inspection for DMM 5."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping

from cdmw.services.dmm_runtime_mount import (
    DMM_MERGED_LABEL,
    DmmRuntimeMount,
    DmmServedFile,
    mod_label,
    mod_root_from_source,
    normalized_game_path,
)
from cdmw.services.dmm_send import dmm_mods_folder, find_dmm

_MAX_CONFIG_BYTES = 16 * 1024 * 1024
_GROUP_FOLDER = re.compile(r"\d{4}")
_ARCHIVE_SUFFIXES = frozenset({".zip", ".7z", ".rar"})
_METADATA_FILENAMES = frozenset({
    "mod.json",
    "manifest.json",
    "cdmw_operations.json",
    "operations.json",
    "info.xml",
})
_DEFAULT_GAME_ROOTS = frozenset({
    "character",
    "ui",
    "gamedata",
    "effect",
    "sound",
    "world",
    "scene",
    "script",
    "shader",
    "texture",
    "common",
    "meta",
    "localization",
    "movie",
    "video",
    "font",
    "system",
})
_DEFAULT_ROOT_FILES = frozenset({"paconfig.txt"})


@dataclass(frozen=True, slots=True)
class DmmOverlapAnalysis:
    """Result of checking DMM's manifest and enabled mod library (strictly read-only)."""

    dmm_install: Path | None = None
    mods_folder: Path | None = None
    config_checked: bool = False
    config_note: str = ""
    overlaps_by_path: Mapping[str, tuple[DmmServedFile, ...]] = field(default_factory=dict)
    merged_contributors_by_path: Mapping[str, tuple[DmmServedFile, ...]] = field(default_factory=dict)
    mod_folders: Mapping[str, Path] = field(default_factory=dict)
    unmounted_enabled_mods: tuple[str, ...] = ()
    disabled_but_mounted_mods: tuple[str, ...] = ()
    truncated: bool = False


def infer_dmm_install(saved_dmm_folder: str, mount: DmmRuntimeMount | None) -> Path | None:
    """Locate DMM's install folder from settings, usual places, or served file paths."""

    install = find_dmm(saved_dmm_folder)
    if install is not None:
        return install
    if mount is None or not mount.files:
        return None
    seen_candidates: set[str] = set()
    for served in mount.files.values():
        for parent in Path(served.source).parents:
            if parent.name.casefold() not in {"mods", "archive_cache"}:
                continue
            candidate = parent.parent
            key = str(candidate).casefold()
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            if (candidate / "DMM.exe").is_file() or (candidate / "config.json").is_file():
                return candidate
    return None


def infer_game_path(
    rel_parts: tuple[str, ...],
    known_roots: frozenset[str] = _DEFAULT_GAME_ROOTS,
    known_root_files: frozenset[str] = _DEFAULT_ROOT_FILES,
) -> str | None:
    """Map a mod-relative path tuple to a normalized-case game path, or None if non-game."""

    if not rel_parts or any(part.startswith(".") for part in rel_parts):
        return None
    filename = rel_parts[-1].casefold()
    if filename in _METADATA_FILENAMES or filename.startswith("readme."):
        return None
    for idx, part in enumerate(rel_parts[:-1]):
        if _GROUP_FOLDER.fullmatch(part):
            tail = rel_parts[idx + 1:]
            return "/".join(tail) if tail else None
    prefix_limit = min(3, len(rel_parts) - 1)
    for idx in range(prefix_limit):
        if rel_parts[idx].casefold() in known_roots:
            return "/".join(rel_parts[idx:])
    if len(rel_parts) == 1 and filename in known_root_files:
        return rel_parts[0]
    return None


def _resolve_mods_folder(install: Path, config: Mapping[str, object]) -> Path | None:
    if (install / "DMM.exe").is_file():
        return dmm_mods_folder(install)
    configured = config.get("modsPath")
    mods = install / "mods"
    if isinstance(configured, str) and configured.strip():
        candidate = Path(configured)
        mods = candidate if candidate.is_absolute() else install / candidate
    return mods if mods.is_dir() else None


def _archive_cache_matches(install: Path, entry: str, mount: DmmRuntimeMount) -> list[Path]:
    cache_root = install / "archive_cache"
    if not cache_root.is_dir():
        return []
    raw_name = Path(entry).name
    stem = Path(raw_name).stem.casefold()
    sanitized = re.sub(r"[^a-z0-9]+", "_", raw_name.casefold()).strip("_")
    stem_sanitized = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    matches: list[Path] = []
    seen: set[str] = set()
    try:
        children = sorted(cache_root.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        return []
    for child in children:
        if child.is_symlink() or not child.is_dir():
            continue
        name_fold = child.name.casefold()
        name_sanitized = re.sub(r"[^a-z0-9]+", "_", name_fold).strip("_")
        if (
            (sanitized and name_sanitized == sanitized)
            or (stem and name_fold.startswith(stem))
            or (stem_sanitized and name_sanitized.startswith(stem_sanitized))
        ):
            key = str(child).casefold()
            if key not in seen:
                seen.add(key)
                matches.append(child)
    if not matches and stem:
        # Fallback: match archive_cache subdirectories already referenced by manifest.tsv.
        for served in mount.files.values():
            try:
                rel = Path(served.source).relative_to(cache_root)
            except ValueError:
                continue
            if rel.parts:
                candidate = cache_root / rel.parts[0]
                if candidate.is_dir() and stem in candidate.name.casefold():
                    key = str(candidate).casefold()
                    if key not in seen:
                        seen.add(key)
                        matches.append(candidate)
    return matches


def _resolve_enabled_targets(
    install: Path,
    mods_folder: Path,
    active_browser_mods: list[str],
    mount: DmmRuntimeMount,
) -> list[tuple[str, Path, bool]]:
    """Return ``(entry_name, directory, is_under_mods_folder)`` tuples for enabled entries."""

    resolved_mods = mods_folder.resolve()
    resolved_cache = (install / "archive_cache").resolve() if (install / "archive_cache").is_dir() else None
    targets: list[tuple[str, Path, bool]] = []
    seen_dirs: set[str] = set()

    for raw_entry in active_browser_mods:
        entry = str(raw_entry or "").strip().replace("\\", "/").strip("/")
        if not entry:
            continue
        parts = PurePosixPath(entry).parts
        if not parts or ".." in parts or ":" in entry:
            continue
        candidate = mods_folder.joinpath(*parts)
        try:
            if candidate.is_symlink():
                continue
            if candidate.is_dir():
                resolved = candidate.resolve()
                if not resolved.is_relative_to(resolved_mods):
                    continue
                key = str(resolved).casefold()
                if key not in seen_dirs:
                    seen_dirs.add(key)
                    targets.append((entry, candidate, True))
                continue
        except OSError:
            continue

        # Archive entries (.zip/.7z/.rar) or extracted archive cache folders.
        if Path(entry).suffix.casefold() in _ARCHIVE_SUFFIXES or not candidate.exists():
            for cache_dir in _archive_cache_matches(install, entry, mount):
                try:
                    resolved = cache_dir.resolve()
                    if resolved_cache is not None and not resolved.is_relative_to(resolved_cache):
                        continue
                except OSError:
                    continue
                key = str(resolved).casefold()
                if key not in seen_dirs:
                    seen_dirs.add(key)
                    targets.append((entry, cache_dir, False))
    return targets


def _baseline_from_mount(mount: DmmRuntimeMount | None) -> tuple[dict[str, Path], dict[str, list[DmmServedFile]]]:
    mod_folders: dict[str, Path] = {}
    overlaps: dict[str, list[DmmServedFile]] = {}
    if mount is None:
        return mod_folders, overlaps
    for served in mount.files.values():
        if served.mod == DMM_MERGED_LABEL:
            continue
        folder = mod_root_from_source(served.source, served.game_path)
        if folder is not None and served.mod not in mod_folders:
            mod_folders[served.mod] = folder
    for key, dups in getattr(mount, "duplicates", {}).items():
        winner = mount.files.get(key)
        winner_src = str(winner.source).casefold() if winner is not None else ""
        winner_mod = winner.mod.casefold() if winner is not None else ""
        bucket = overlaps.setdefault(key, [])
        for dup in dups:
            folder = mod_root_from_source(dup.source, dup.game_path)
            if folder is not None and dup.mod not in mod_folders:
                mod_folders[dup.mod] = folder
            if str(dup.source).casefold() == winner_src:
                continue
            if dup.mod.casefold() == winner_mod and dup.mod != DMM_MERGED_LABEL:
                continue
            if all((item.mod.casefold(), str(item.source).casefold()) != (dup.mod.casefold(), str(dup.source).casefold())
                   for item in bucket):
                bucket.append(dup)
    return mod_folders, {k: v for k, v in overlaps.items() if v}


def scan_dmm_mount_overlaps(
    mount: DmmRuntimeMount | None,
    *,
    saved_dmm_folder: str = "",
    stop_event: threading.Event | None = None,
    max_walk_entries: int = 200_000,
) -> DmmOverlapAnalysis:
    """Inspect DMM's enabled mods read-only to find overridden files and out-of-sync mounts."""

    mod_folders, overlaps = _baseline_from_mount(mount)
    if mount is None or not mount.files:
        return DmmOverlapAnalysis(
            overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
            mod_folders=mod_folders,
        )
    if stop_event is not None and stop_event.is_set():
        return DmmOverlapAnalysis(
            overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
            mod_folders=mod_folders,
        )

    install = infer_dmm_install(saved_dmm_folder, mount)
    if install is None:
        return DmmOverlapAnalysis(
            config_checked=False,
            config_note="DMM folder not found; showing manifest.tsv entries only.",
            overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
            mod_folders=mod_folders,
        )

    config_path = install / "config.json"
    try:
        if config_path.is_symlink() or not config_path.is_file():
            return DmmOverlapAnalysis(
                dmm_install=install,
                config_checked=False,
                config_note="DMM config.json was not found; showing manifest.tsv entries only.",
                overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
                mod_folders=mod_folders,
            )
        if config_path.stat().st_size > _MAX_CONFIG_BYTES:
            return DmmOverlapAnalysis(
                dmm_install=install,
                config_checked=False,
                config_note="DMM config.json is unexpectedly large; showing manifest.tsv entries only.",
                overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
                mod_folders=mod_folders,
            )
        config = json.loads(config_path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return DmmOverlapAnalysis(
            dmm_install=install,
            config_checked=False,
            config_note=f"DMM config.json could not be read: {exc}",
            overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
            mod_folders=mod_folders,
        )
    if not isinstance(config, dict):
        return DmmOverlapAnalysis(
            dmm_install=install,
            config_checked=False,
            config_note="DMM config.json has an unexpected format; showing manifest.tsv entries only.",
            overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
            mod_folders=mod_folders,
        )

    try:
        mods_folder = _resolve_mods_folder(install, config)
    except ValueError as exc:
        return DmmOverlapAnalysis(
            dmm_install=install,
            config_checked=False,
            config_note=str(exc),
            overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
            mod_folders=mod_folders,
        )
    if mods_folder is None:
        return DmmOverlapAnalysis(
            dmm_install=install,
            config_checked=False,
            config_note="DMM mods folder was not found; showing manifest.tsv entries only.",
            overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
            mod_folders=mod_folders,
        )

    active_browser_mods = config.get("activeBrowserMods")
    if not isinstance(active_browser_mods, list) or not all(isinstance(v, str) for v in active_browser_mods):
        return DmmOverlapAnalysis(
            dmm_install=install,
            mods_folder=mods_folder,
            config_checked=False,
            config_note="DMM enabled mod list could not be read; showing manifest.tsv entries only.",
            overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
            mod_folders=mod_folders,
        )

    known_roots = set(_DEFAULT_GAME_ROOTS)
    known_root_files = set(_DEFAULT_ROOT_FILES)
    for key in mount.files:
        parts = PurePosixPath(key).parts
        if len(parts) > 1:
            known_roots.add(parts[0].casefold())
        elif len(parts) == 1:
            known_root_files.add(parts[0].casefold())
    roots_frozen = frozenset(known_roots)
    root_files_frozen = frozenset(known_root_files)

    targets = _resolve_enabled_targets(install, mods_folder, active_browser_mods, mount)
    merged_contributors: dict[str, list[DmmServedFile]] = {}
    walked_entries = 0
    truncated = False
    unmounted_enabled: list[str] = []
    enabled_mods_dirs: list[Path] = []

    for entry_name, target_dir, is_mods_dir in targets:
        if stop_event is not None and stop_event.is_set():
            break
        if is_mods_dir:
            try:
                enabled_mods_dirs.append(target_dir.resolve())
            except OSError:
                pass
        recognized_count = 0
        manifest_match_count = 0
        seen_labels_in_target: list[str] = []
        target_resolved = target_dir.resolve()

        for root, dirs, files in os.walk(target_dir, followlinks=False):
            if stop_event is not None and stop_event.is_set():
                break
            root_path = Path(root)
            safe_dirs: list[str] = []
            for d in dirs:
                if d.startswith("."):
                    continue
                d_path = root_path / d
                try:
                    if d_path.is_symlink() or not d_path.resolve().is_relative_to(target_resolved):
                        continue
                except OSError:
                    continue
                safe_dirs.append(d)
            dirs[:] = sorted(safe_dirs, key=str.casefold)

            for filename in sorted(files, key=str.casefold):
                if stop_event is not None and stop_event.is_set():
                    break
                walked_entries += 1
                if walked_entries > max_walk_entries:
                    truncated = True
                    break
                file_path = root_path / filename
                try:
                    if file_path.is_symlink() or not file_path.resolve().is_relative_to(target_resolved):
                        continue
                    rel_parts = file_path.relative_to(target_dir).parts
                except (OSError, ValueError):
                    continue
                game_path = infer_game_path(rel_parts, roots_frozen, root_files_frozen)
                if not game_path:
                    continue
                recognized_count += 1
                key = normalized_game_path(game_path)
                label = mod_label(str(file_path), game_path)
                if label and label not in seen_labels_in_target:
                    seen_labels_in_target.append(label)
                folder = mod_root_from_source(file_path, game_path) or target_dir
                mod_folders.setdefault(label, folder)

                winner = mount.files.get(key)
                if winner is None:
                    continue
                manifest_match_count += 1
                served_candidate = DmmServedFile(winner.game_path, file_path, label)
                if winner.mod == DMM_MERGED_LABEL:
                    bucket = merged_contributors.setdefault(key, [])
                    if all(
                        (item.mod.casefold(), str(item.source).casefold())
                        != (label.casefold(), str(file_path).casefold())
                        for item in bucket
                    ):
                        bucket.append(served_candidate)
                elif (
                    str(file_path).casefold() != str(winner.source).casefold()
                    and label.casefold() != winner.mod.casefold()
                ):
                    bucket = overlaps.setdefault(key, [])
                    if all(
                        (item.mod.casefold(), str(item.source).casefold())
                        != (label.casefold(), str(file_path).casefold())
                        for item in bucket
                    ):
                        bucket.append(served_candidate)
            if truncated or (stop_event is not None and stop_event.is_set()):
                break

        if (
            mount.serving
            and active_browser_mods
            and recognized_count > 0
            and manifest_match_count == 0
            and not truncated
            and not (stop_event is not None and stop_event.is_set())
        ):
            display = seen_labels_in_target[0] if len(seen_labels_in_target) == 1 else entry_name
            unmounted_enabled.append(display)
        if truncated:
            break

    disabled_but_mounted: list[str] = []
    if (
        mount.serving
        and active_browser_mods
        and not truncated
        and not (stop_event is not None and stop_event.is_set())
    ):
        resolved_mods = mods_folder.resolve()
        sources_by_mod: dict[str, list[Path]] = {}
        for served in mount.files.values():
            if served.mod == DMM_MERGED_LABEL:
                continue
            sources_by_mod.setdefault(served.mod, []).append(served.source)
        for mod_name, paths in sorted(sources_by_mod.items(), key=lambda pair: pair[0].casefold()):
            any_in_mods_folder = False
            any_in_enabled_dir = False
            for src in paths:
                try:
                    resolved = Path(src).resolve()
                except OSError:
                    continue
                if resolved.is_relative_to(resolved_mods):
                    any_in_mods_folder = True
                    if any(resolved.is_relative_to(enabled_dir) for enabled_dir in enabled_mods_dirs):
                        any_in_enabled_dir = True
                        break
            if any_in_mods_folder and not any_in_enabled_dir:
                disabled_but_mounted.append(mod_name)

    note = ""
    if truncated:
        note = "Enabled mod scan stopped early after checking the file safety cap."
    return DmmOverlapAnalysis(
        dmm_install=install,
        mods_folder=mods_folder,
        config_checked=True,
        config_note=note,
        overlaps_by_path={k: tuple(v) for k, v in overlaps.items()},
        merged_contributors_by_path={k: tuple(v) for k, v in merged_contributors.items()},
        mod_folders=mod_folders,
        unmounted_enabled_mods=tuple(dict.fromkeys(unmounted_enabled)),
        disabled_but_mounted_mods=tuple(dict.fromkeys(disabled_but_mounted)),
        truncated=truncated,
    )


def format_overlap_report(
    mount: DmmRuntimeMount | None,
    analysis: DmmOverlapAnalysis | None,
    *,
    overlay_enabled: bool = True,
) -> str:
    """Format a plain-text DMM mounted mods & file overlap summary for sharing."""

    if mount is None:
        return "DMM Mounted Mods: nothing mounted (no bin64/dmm/manifest.tsv)."
    overlaps = analysis.overlaps_by_path if analysis is not None else {}
    lines = [
        f"Game folder: {mount.game_root}",
        f"CDMW overlay: {'On' if overlay_enabled else 'Off'}",
        f"Mounted files: {len(mount.files):,} across {len(mount.mods):,} mod(s) | Overlaps: {len(overlaps):,}",
    ]
    if mount.problem:
        lines.append(f"Warning: {mount.problem}")
    if analysis is not None:
        if analysis.unmounted_enabled_mods:
            lines.append(
                "Enabled in DMM but not in current mount: " + ", ".join(analysis.unmounted_enabled_mods)
            )
        if analysis.disabled_but_mounted_mods:
            lines.append(
                "In current mount but disabled in DMM: " + ", ".join(analysis.disabled_but_mounted_mods)
            )
        if analysis.config_note:
            lines.append(f"Note: {analysis.config_note}")

    active_counts: dict[str, int] = {}
    for served in mount.files.values():
        active_counts[served.mod] = active_counts.get(served.mod, 0) + 1
    overridden_counts: dict[str, int] = {}
    for losers in overlaps.values():
        for loser in losers:
            overridden_counts[loser.mod] = overridden_counts.get(loser.mod, 0) + 1
    fully_overridden = sorted(
        (mod for mod, count in overridden_counts.items() if count > 0 and active_counts.get(mod, 0) == 0),
        key=str.casefold,
    )
    if fully_overridden:
        lines.append("")
        lines.append("Fully overridden enabled mods (0 active files):")
        for mod in fully_overridden:
            lines.append(f"- {mod} ({overridden_counts[mod]:,} overridden)")

    lines.append("")
    if not overlaps:
        lines.append("No overlapping files detected among mounted DMM mods.")
    else:
        lines.append("Overlapping files:")
        for key in sorted(overlaps):
            winner = mount.files.get(key)
            game_path = winner.game_path if winner is not None else overlaps[key][0].game_path
            winner_mod = winner.mod if winner is not None else "?"
            losers = ", ".join(item.mod for item in overlaps[key])
            lines.append(f"- {game_path} | Active: {winner_mod} | Overridden: {losers}")
    return "\n".join(lines)


__all__ = [
    "DmmOverlapAnalysis",
    "format_overlap_report",
    "infer_dmm_install",
    "infer_game_path",
    "scan_dmm_mount_overlaps",
]
