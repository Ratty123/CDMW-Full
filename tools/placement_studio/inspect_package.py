"""Read a built package back and say what is actually in it.

A README and a manifest are claims. This walks the files on disk, parses the descriptor and
socket diffs against vanilla, reads the animation family out of every clip path, and compares
all of it against the operation manifest the package shipped. A mismatch exits non-zero, so it
can sit in a gate rather than in somebody's memory.

Deliberately independent of the editor: it takes a directory and a baseline, and does not know
how the package was produced. A check that reuses the producer's own model cannot catch the
producer being wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import carry, ops
from .documents import DescriptorDocument, SocketDocument, is_descriptor_file, is_socket_file
from .preflight import MANIFEST_NAME

#: Files the package writes about itself rather than into the game.
METADATA_NAMES = frozenset(
    {
        "README.txt",
        "manifest.json",
        "modinfo.json",
        "mod.json",
        ".no_encrypt",
        MANIFEST_NAME,
    }
)


@dataclass(frozen=True, slots=True)
class PackageContents:
    """What the files on disk actually are."""

    root: Path
    payload_paths: Tuple[str, ...] = ()
    metadata_files: Tuple[str, ...] = ()
    by_extension: Mapping[str, int] = field(default_factory=dict)
    descriptor_parts: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    socket_changes: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    socket_additions: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    animation_targets: Mapping[str, int] = field(default_factory=dict)
    animation_paths: Tuple[str, ...] = ()
    unparsed: Tuple[str, ...] = ()

    def all_parts(self) -> Tuple[str, ...]:
        out: set = set()
        for names in self.descriptor_parts.values():
            out.update(names)
        return tuple(sorted(out))

    def all_socket_changes(self) -> Tuple[str, ...]:
        out: set = set()
        for names in self.socket_changes.values():
            out.update(names)
        return tuple(sorted(out))

    def all_socket_additions(self) -> Tuple[str, ...]:
        out: set = set()
        for names in self.socket_additions.values():
            out.update(names)
        return tuple(sorted(out))

    def render(self) -> str:
        lines = [
            f"Package: {self.root}",
            "",
            "Files by extension",
            "------------------",
        ]
        lines += [
            f"  {extension or '(none)'}: {count}"
            for extension, count in sorted(self.by_extension.items())
        ]
        lines += ["", "Descriptor rows changed", "-----------------------"]
        for path, names in sorted(self.descriptor_parts.items()):
            lines.append(f"  {path}")
            lines += [f"    {name}" for name in names]
        if not self.descriptor_parts:
            lines.append("  (none)")
        lines += ["", "Socket definitions", "------------------"]
        for path in sorted(set(self.socket_changes) | set(self.socket_additions)):
            lines.append(f"  {path}")
            for name in self.socket_additions.get(path, ()):
                lines.append(f"    + {name}")
            for name in self.socket_changes.get(path, ()):
                lines.append(f"    ~ {name}")
        if not self.socket_changes and not self.socket_additions:
            lines.append("  (none)")
        lines += ["", "Animation target families", "-------------------------"]
        lines += [
            f"  {family}: {count}"
            for family, count in sorted(self.animation_targets.items())
        ] or ["  (none)"]
        if self.unparsed:
            lines += ["", "Not parsed (carried whole)", "--------------------------"]
            lines += [f"  {path}" for path in self.unparsed]
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class InspectionResult:
    contents: PackageContents
    manifest: Optional[Mapping[str, object]] = None
    mismatches: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def render(self) -> str:
        lines = [self.contents.render()]
        if self.manifest is None:
            lines += ["", f"No {MANIFEST_NAME}: nothing to compare the files against."]
        elif self.mismatches:
            lines += ["", "Scope mismatches", "----------------"]
            lines += [f"  {item}" for item in self.mismatches]
        else:
            lines += ["", f"{MANIFEST_NAME} matches the files."]
        return "\n".join(lines)


def _game_path_of(root: Path, file: Path) -> str:
    """The package-relative path as a game path, with any `files/` wrapper stripped."""

    relative = PurePosixPath(file.relative_to(root).as_posix())
    parts = list(relative.parts)
    if parts and parts[0] == "files":
        parts = parts[1:]
    return "/".join(parts)


def read_contents(root: Path, baseline=None) -> PackageContents:
    """Walk a package and describe what it changes, parsed where it can be parsed."""

    root = Path(root)
    payload: List[str] = []
    metadata: List[str] = []
    by_extension: Dict[str, int] = {}
    descriptor_parts: Dict[str, Tuple[str, ...]] = {}
    socket_changes: Dict[str, Tuple[str, ...]] = {}
    socket_additions: Dict[str, Tuple[str, ...]] = {}
    animation_targets: Dict[str, int] = {}
    animation_paths: List[str] = []
    unparsed: List[str] = []

    for file in sorted(p for p in root.rglob("*") if p.is_file()):
        if file.name in METADATA_NAMES:
            metadata.append(file.name)
            continue
        game_path = _game_path_of(root, file)
        payload.append(game_path)
        by_extension[file.suffix.lower()] = by_extension.get(file.suffix.lower(), 0) + 1

        data = file.read_bytes()
        vanilla = None
        if baseline is not None and game_path in baseline:
            vanilla = baseline.read(game_path)

        if is_descriptor_file(game_path):
            names = _changed_descriptor_rows(game_path, vanilla, data)
            if names:
                descriptor_parts[game_path] = names
            continue
        if is_socket_file(game_path):
            changed, added = _changed_sockets(game_path, vanilla, data)
            if changed:
                socket_changes[game_path] = changed
            if added:
                socket_additions[game_path] = added
            continue
        if ops.is_animation_payload(game_path):
            animation_paths.append(game_path)
            family = carry.family_of(PurePosixPath(game_path).stem)
            if family:
                animation_targets[family] = animation_targets.get(family, 0) + 1
            continue
        unparsed.append(game_path)

    return PackageContents(
        root=root,
        payload_paths=tuple(payload),
        metadata_files=tuple(sorted(set(metadata))),
        by_extension=dict(sorted(by_extension.items())),
        descriptor_parts=dict(sorted(descriptor_parts.items())),
        socket_changes=dict(sorted(socket_changes.items())),
        socket_additions=dict(sorted(socket_additions.items())),
        animation_targets=dict(sorted(animation_targets.items())),
        animation_paths=tuple(sorted(animation_paths)),
        unparsed=tuple(sorted(unparsed)),
    )


def _changed_descriptor_rows(game_path: str, vanilla, data: bytes) -> Tuple[str, ...]:
    """Which rows differ from vanilla. Every row, when there is no vanilla to compare to."""

    modded = DescriptorDocument.load(data, game_path).part_map()
    if vanilla is None:
        return tuple(sorted(modded))
    original = DescriptorDocument.load(vanilla, game_path).part_map()
    return tuple(
        sorted(name for name, part in modded.items() if original.get(name) != part)
    )


def _changed_sockets(game_path: str, vanilla, data: bytes):
    modded = SocketDocument.load(data, game_path).socket_map()
    if vanilla is None:
        return (), tuple(sorted(modded))
    original = SocketDocument.load(vanilla, game_path).socket_map()
    added = tuple(sorted(name for name in modded if name not in original))
    changed = tuple(
        sorted(
            name
            for name, socket in modded.items()
            if name in original and original[name] != socket
        )
    )
    return changed, added


def read_manifest(root: Path) -> Optional[Mapping[str, object]]:
    target = Path(root) / MANIFEST_NAME
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def compare(contents: PackageContents, manifest: Mapping[str, object]) -> Tuple[str, ...]:
    """Where the manifest's claim and the files disagree.

    Both directions matter. A file the manifest does not mention is a leak; a claim with no file
    behind it means the package was assembled from something other than the operation it says.
    """

    out: List[str] = []

    claimed_parts = set(manifest.get("descriptor_parts") or ())
    actual_parts = set(contents.all_parts())
    for part in sorted(actual_parts - claimed_parts):
        out.append(f"{part} changed but the manifest does not list it")
    for part in sorted(claimed_parts - actual_parts):
        out.append(f"the manifest lists {part} but no file changes it")

    claimed_created = set(manifest.get("created_sockets") or ())
    actual_created = set(contents.all_socket_additions())
    for name in sorted(actual_created - claimed_created):
        out.append(f"socket {name} was added but the manifest does not list it")
    for name in sorted(claimed_created - actual_created):
        out.append(f"the manifest lists new socket {name} but no file defines it")

    claimed_shared = set(manifest.get("shared_sockets_modified") or ())
    claimed_modified = set(manifest.get("modified_sockets") or ()) | claimed_shared
    actual_modified = set(contents.all_socket_changes())
    for name in sorted(actual_modified - claimed_modified - actual_created):
        out.append(f"socket {name} was changed in place but the manifest does not list it")

    claimed_families = {
        str(name): int(count)
        for name, count in (manifest.get("animation_targets") or {}).items()
    }
    for family, count in sorted(contents.animation_targets.items()):
        if family not in claimed_families:
            out.append(
                f"{count} {family} animation file(s) shipped, which the manifest does not claim"
            )
        elif claimed_families[family] != count:
            out.append(
                f"the manifest claims {claimed_families[family]} {family} animation file(s) "
                f"but {count} shipped"
            )
    for family, count in sorted(claimed_families.items()):
        if family not in contents.animation_targets:
            out.append(f"the manifest claims {count} {family} file(s) but none shipped")

    claimed_paths = set(manifest.get("payload_paths") or ())
    if claimed_paths:
        actual_paths = set(contents.payload_paths)
        for path in sorted(actual_paths - claimed_paths):
            out.append(f"{path} is in the package but not in the manifest's payload list")
        for path in sorted(claimed_paths - actual_paths):
            out.append(f"the manifest lists {path} but it is not in the package")
    return tuple(out)


def inspect(root: Path, baseline=None) -> InspectionResult:
    contents = read_contents(root, baseline)
    manifest = read_manifest(root)
    mismatches = compare(contents, manifest) if manifest is not None else ()
    return InspectionResult(contents, manifest, mismatches)


def cmd_inspect_package(args) -> int:
    """`placement_studio inspect-package <dir>` — describe a package and check its manifest."""

    root = Path(getattr(args, "package", "") or "")
    if not root.is_dir():
        print(f"Not a directory: {root}")
        return 2

    baseline = None
    if not getattr(args, "no_baseline", False):
        try:
            from .corpus import Baseline

            baseline = Baseline.load()
        except Exception as error:  # noqa: BLE001 - a diff against vanilla is a bonus, not a gate
            print(f"(no baseline: {error}; reporting definitions rather than diffs)")

    result = inspect(root, baseline)
    print(result.render())
    print("-" * 72)
    if result.manifest is None:
        print("INSPECTION: no operation manifest to check against")
        return 0
    if result.ok:
        print("INSPECTION: PASS - the package contains exactly what its manifest claims")
        return 0
    print(f"INSPECTION: {len(result.mismatches)} scope mismatch(es); see above")
    return 1
