"""Rules for combining several built Mesh Editor mods into one mod (GitHub issue 31).

A Mesh Editor build is a mod folder that replaces one or more game files (its
mesh targets) and may add companion files (textures and materials written by
Import Replacement). Two builds can be combined when no game file is written by
both. A companion that two builds carry with the same bytes is kept once; any
other shared path is a conflict, and a conflict refuses the whole combination
with the path and the builds named.

This module is pure: it reads nothing from disk and writes nothing. The service
`cdmw.services.mesh_build_combine_service` reads the builds and writes the
combined mod.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterable, Sequence

#: Output layouts a combined mod can take.
LAYOUT_LOOSE = "loose"
LAYOUT_ARCHIVE_GROUP = "archive_group"

#: Formats that count as the game files a build edits, as opposed to companions.
MESH_TARGET_FORMATS = frozenset({"pac", "pam", "pamlod", "pab", "hkx"})

CONFLICT_SHARED_TARGET = "shared_target"
CONFLICT_DIFFERENT_COMPANION = "different_companion"
CONFLICT_DIFFERENT_GAME = "different_game"


def normalize_game_path(value: object) -> str:
    """Game-relative, forward slashes, lower case; refuse paths that escape."""

    text = str(value or "").replace("\\", "/").strip().strip("/")
    parts = PurePosixPath(text.casefold()).parts
    if not parts or any(part in ("..", ".") or ":" in part for part in parts):
        raise ValueError(f"Invalid game file path: {value!r}")
    return PurePosixPath(*parts).as_posix()


@dataclass(frozen=True, slots=True)
class MeshBuildFile:
    """One payload file of a build, at its game path."""

    path: str
    sha256: str
    size: int = 0
    package_group: str = ""
    format: str = ""
    note: str = ""
    is_new: bool = False

    @property
    def key(self) -> str:
        return normalize_game_path(self.path)

    @property
    def is_mesh_target(self) -> bool:
        suffix = (self.format or PurePosixPath(self.path).suffix.lstrip(".")).casefold()
        return suffix in MESH_TARGET_FORMATS and not self.is_new


@dataclass(frozen=True, slots=True)
class MeshBuildSource:
    """A built mod as read from its folder; `label` names it in messages."""

    label: str
    folder: str
    layout: str
    manager_profile: str
    files: tuple[MeshBuildFile, ...]
    title: str = ""
    target_game_build: str = ""
    session_formats: tuple[str, ...] = ()

    @property
    def target_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files if item.is_mesh_target)


@dataclass(frozen=True, slots=True)
class MeshBuildConflict:
    kind: str
    path: str
    builds: tuple[str, ...]

    @property
    def message(self) -> str:
        names = _names(self.builds)
        if self.kind == CONFLICT_SHARED_TARGET:
            return (f"{names} all change {self.path}. Combine builds that change different game files, "
                    "or edit both changes in one Mesh Editor session.")
        if self.kind == CONFLICT_DIFFERENT_COMPANION:
            return f"{names} write different versions of {self.path}. Rebuild one of them so the file names differ."
        return f"{names} were built against different game versions. Rebuild them against the same game version."


@dataclass(frozen=True, slots=True)
class MeshBuildCombinePlan:
    """What a combination would write, or why it is refused."""

    sources: tuple[MeshBuildSource, ...]
    files: tuple[tuple[MeshBuildFile, str], ...]
    conflicts: tuple[MeshBuildConflict, ...]
    layout: str
    manager_profile: str
    shared_companions: tuple[str, ...] = field(default=())

    @property
    def can_combine(self) -> bool:
        return not self.conflicts

    @property
    def refusal(self) -> str:
        """One message naming every conflict; empty when the plan can be written."""

        if not self.conflicts:
            return ""
        lines = [conflict.message for conflict in self.conflicts]
        if len(lines) == 1:
            return "These builds cannot be combined: " + lines[0]
        return "These builds cannot be combined:\n" + "\n".join(f"- {line}" for line in lines)

    @property
    def target_paths(self) -> tuple[str, ...]:
        """Every game file the combined mod edits, in build order."""

        return tuple(item.path for item, _label in self.files if item.is_mesh_target)


def _names(labels: Sequence[str]) -> str:
    quoted = [f'"{label}"' for label in labels]
    if len(quoted) <= 2:
        return " and ".join(quoted)
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


def combined_output_layout(sources: Iterable[MeshBuildSource]) -> tuple[str, str]:
    """The layout and manager profile of the combined mod.

    The one place this choice is made. Loose builds for one manager combine
    into a loose mod for that manager, because the loose writer then records
    every file's package group itself. Any archive-group build, or a mix of
    managers, gives a DMM archive group built by the existing merge service.
    """

    sources = tuple(sources)
    profiles = {source.manager_profile or "dmm" for source in sources}
    if sources and all(source.layout == LAYOUT_LOOSE for source in sources) and len(profiles) == 1:
        return LAYOUT_LOOSE, profiles.pop()
    return LAYOUT_ARCHIVE_GROUP, "dmm"


def plan_mesh_build_combine(sources: Sequence[MeshBuildSource]) -> MeshBuildCombinePlan:
    """Merge the builds' files and name every conflict. Never raises for a conflict."""

    sources = tuple(sources)
    if len(sources) < 2:
        raise ValueError("Select at least two built mods to combine.")
    folders = [str(source.folder).replace("\\", "/").casefold().rstrip("/") for source in sources]
    if len(set(folders)) != len(folders):
        raise ValueError("The same built mod is selected more than once.")
    owners: dict[str, list[tuple[MeshBuildSource, MeshBuildFile]]] = {}
    order: list[str] = []
    for source in sources:
        seen: set[str] = set()
        for item in source.files:
            key = item.key
            if key in seen:
                raise ValueError(f'"{source.label}" lists {item.path} twice.')
            seen.add(key)
            if key not in owners:
                owners[key] = []
                order.append(key)
            owners[key].append((source, item))
    conflicts: list[MeshBuildConflict] = []
    games = {source.target_game_build for source in sources if source.target_game_build}
    if len(games) > 1:
        conflicts.append(MeshBuildConflict(CONFLICT_DIFFERENT_GAME, "",
                                           tuple(source.label for source in sources if source.target_game_build)))
    files: list[tuple[MeshBuildFile, str]] = []
    shared: list[str] = []
    for key in order:
        claims = owners[key]
        first_source, first = claims[0]
        if len(claims) > 1:
            labels = tuple(source.label for source, _item in claims)
            if any(item.is_mesh_target for _source, item in claims):
                conflicts.append(MeshBuildConflict(CONFLICT_SHARED_TARGET, first.path, labels))
                continue
            if len({item.sha256 for _source, item in claims}) > 1:
                conflicts.append(MeshBuildConflict(CONFLICT_DIFFERENT_COMPANION, first.path, labels))
                continue
            shared.append(first.path)
        files.append((first, first_source.label))
    layout, profile = combined_output_layout(sources)
    return MeshBuildCombinePlan(sources, tuple(files), tuple(conflicts), layout, profile, tuple(shared))


__all__ = [
    "CONFLICT_DIFFERENT_COMPANION",
    "CONFLICT_DIFFERENT_GAME",
    "CONFLICT_SHARED_TARGET",
    "LAYOUT_ARCHIVE_GROUP",
    "LAYOUT_LOOSE",
    "MESH_TARGET_FORMATS",
    "MeshBuildCombinePlan",
    "MeshBuildConflict",
    "MeshBuildFile",
    "MeshBuildSource",
    "combined_output_layout",
    "normalize_game_path",
    "plan_mesh_build_combine",
]
