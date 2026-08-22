"""Emit installable mod packages from one plan, for every manager layout.

The app already has a proven packaging pipeline — it produced the golden mods, which carry
`"generator": "Crimson Desert Mod Workbench"`. This module reuses `cdmw.core.mod_package`
rather than reimplementing manifests, so the JMM descriptor-alias rule, `.no_encrypt`
handling and manifest schema stay in one place and cannot drift apart from the app.

What is new here is the mapping from a *placement plan* to a package: which paths are new
rather than overwrites, and a README that states what the mod actually changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .ops import Plan

# Layouts observed across the golden corpus. `files_wrapper` nests payloads under `files/`;
# `game_relative` puts the game tree at the package root.
MANAGER_PROFILES: Dict[str, Dict[str, object]] = {
    "CDUMM": {
        "manager_targets": ("cdumm",),
        "structure": "files_wrapper",
        "create_manifest_json": True,
        "create_modinfo_json": True,
        "create_no_encrypt_file": True,
        "create_mod_json": False,
        "kind": "archive_loose_mod",
    },
    "DMM": {
        "manager_targets": ("dmm",),
        "structure": "game_relative",
        "create_manifest_json": True,
        "create_modinfo_json": True,
        "create_no_encrypt_file": False,
        "create_mod_json": False,
        "kind": "archive_loose_mod",
    },
    "JMM": {
        "manager_targets": ("jmm",),
        "structure": "game_relative",
        "create_manifest_json": False,
        "create_modinfo_json": False,
        "create_no_encrypt_file": False,
        "create_mod_json": False,
        # The goldens' JMM mod.json declares loose_mod, which is also the app writer's default.
        "kind": "loose_mod",
    },
}

# The in-game checks the tuning guide requires before a placement change is trusted.
#
# Ordered as a run, not as a menu: a save load first, then the states a stowed weapon is seen
# in, then the ones that only a wider animation scope can break, then the two that catch a
# change which only looks right on the frame you were watching.
IN_GAME_CHECKLIST: Tuple[str, ...] = (
    "Load a save.",
    "Stand idle with the weapon stowed.",
    "Draw the weapon.",
    "Stow the weapon.",
    "Walk and run with the weapon stowed.",
    "Walk and run with the weapon drawn.",
    "Crouch, and move while crouched.",
    "Sit down and stand up again.",
    "Mount a horse and dismount if the package includes riding files.",
    "Equip a shield and repeat draw/stow if shield placement changed.",
    "Watch the weapon and its case through every draw and stow transition, "
    "including the frames where one becomes visible and the other hides.",
    "Check clipping from back, side, and front camera angles.",
    "Reload the character, then reload the save, and check the placement again.",
)

PASS_CRITERIA: Tuple[str, ...] = (
    "Weapon and sheath stay together in every state above.",
    "The weapon is on the side and the destination the package README names.",
    "The weapon is not inverted from any camera angle.",
    "The draw/stow hand reaches close enough.",
    "The off-hand and the shield are unchanged, unless a full-body donor was accepted "
    "on purpose.",
    "No other weapon moved, and no other weapon's animations changed.",
    "The weapon never snaps back to its vanilla position in a context the package covers.",
    "The shield does not snap, rotate wrongly, or cover the camera.",
    "No teleport or eject on horseback.",
)


class PackagingError(RuntimeError):
    """Raised when a package cannot be laid out as requested."""


@dataclass(frozen=True, slots=True)
class PackageMetadata:
    """The human-facing fields a manager displays."""

    name: str
    version: str = "1.0.0"
    author: str = ""
    description: str = ""

    def title_for(self, manager: str) -> str:
        # JMM shows the raw name, and the goldens carry the manager in it.
        return f"{self.name} - {manager}" if manager == "JMM" else self.name


@dataclass(frozen=True, slots=True)
class PackageResult:
    manager: str
    root: Path
    payload_paths: tuple[str, ...] = field(default=())
    new_paths: tuple[str, ...] = field(default=())
    metadata_files: tuple[str, ...] = field(default=())

    @property
    def file_count(self) -> int:
        return len(self.payload_paths)

    def describe(self) -> str:
        return (
            f"{self.manager:<6} {self.file_count:>4} payload file(s), "
            f"{len(self.new_paths)} new path(s) -> {self.root}"
        )


# The guide's JMM rule: "If either path is in new_paths, both should be in new_paths."
# A manager quirk rather than a truth about the game — only the root-level alias is genuinely
# new — so it is encoded here as a closure over the pair rather than left to the author.
DESCRIPTOR_ALIAS_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        "character/phm_description_player_kliff.xml",
        "character/descriptors/characterdescription/phm_description_player_kliff.xml",
    ),
    (
        "character/phm_description_player_001.xml",
        "character/descriptors/characterdescription/phm_description_player_001.xml",
    ),
    (
        "character/phw_description_player_001.xml",
        "character/descriptors/characterdescription/phw_description_player_001.xml",
    ),
)


def apply_alias_closure(new_paths: Iterable[str], shipped: Iterable[str]) -> List[str]:
    """If one half of a descriptor alias pair is new, declare both — when both are shipped."""

    result = set(new_paths)
    available = set(shipped)
    for left, right in DESCRIPTOR_ALIAS_PAIRS:
        if result & {left, right} and {left, right} <= available:
            result.update((left, right))
    return sorted(result)


def derive_new_paths(paths: Iterable[str], baseline) -> List[str]:
    """Paths the game does not already ship — these are additions, not overwrites.

    Derived from the pinned baseline rather than declared by hand, so a new file can never be
    silently packaged as an overwrite. The alias closure is then applied so the JMM rule holds.
    """

    shipped = list(paths)
    genuinely_new = [path for path in shipped if path not in baseline]
    return apply_alias_closure(genuinely_new, shipped)


def build_readme(
    plan: Plan,
    metadata: PackageMetadata,
    *,
    manager: str,
    payload_paths: Sequence[str],
    new_paths: Sequence[str],
    scope=None,
) -> str:
    """A README describing what the mod changes, generated from the operation list.

    `scope` is a `preflight.PackageScopeSummary` when the package was built from selected
    operations. Without it the README still describes the files; with it, it also states which
    operations, which equipment unit, which linked rows and which animation families — the
    facts that make an unexpected batch visible to somebody reading it afterwards.
    """

    tiers = plan.tier_counts()
    lines: List[str] = [
        f"{metadata.title_for(manager)}",
        "=" * max(12, len(metadata.title_for(manager))),
        "",
    ]
    if metadata.description:
        lines += [metadata.description, ""]
    lines += [
        f"Version : {metadata.version}",
        f"Author  : {metadata.author or '-'}",
        f"Manager : {manager}",
        f"Files   : {len(payload_paths)}",
        "",
    ]

    if scope is not None:
        lines += _scope_section(scope)

    lines += ["Changes", "-------"]
    labels = {
        "A": "socket transform edits",
        "A2": "socket definitions created",
        "B": "descriptor routing edits",
        "B2": "descriptor alias / attribute additions",
        "C": "action-chart socket retargets (same length)",
        "D": "payload substitutions from existing game files",
        "E": "carried payloads",
    }
    # An animation replacement is opaque bytes and lands in tier D or E alongside genuine
    # prerequisites, so counting by tier alone filed a batch of draws under "carried
    # prerequisite payloads" — where nobody reviewing the package would look for them.
    animation_ops = [
        op for op in plan.operations
        if str(op.detail.get("payload_kind") or "") == "animation"
    ]
    animation_by_tier: Dict[str, int] = {}
    for op in animation_ops:
        animation_by_tier[op.tier] = animation_by_tier.get(op.tier, 0) + 1
    for tier, count in tiers.items():
        remainder = count - animation_by_tier.get(tier, 0)
        if remainder:
            lines.append(f"  {remainder:>4}  {labels.get(tier, tier)}")
    if animation_ops:
        lines.append(f"  {len(animation_ops):>4}  animation substitutions")
    lines.append("")

    if animation_ops:
        lines += ["Animations replaced", "-------------------"]
        for op in animation_ops[:60]:
            lines.append(f"  {op.game_path}")
        if len(animation_ops) > 60:
            lines.append(f"  ... and {len(animation_ops) - 60} more")
        lines.append("")

    # Spell out the actual edits: this is what a reviewer needs, and it is free to produce.
    socket_edits = [op for op in plan.operations if op.kind in {"xml_attr", "xml_attr_add"}]
    if socket_edits:
        lines += ["Edited values", "-------------"]
        for op in socket_edits[:40]:
            attribute = op.detail.get("attr", "")
            old = op.detail.get("old", "(absent)")
            new = op.detail.get("new", "")
            lines.append(f"  {op.target}.{attribute}: {old} -> {new}")
        if len(socket_edits) > 40:
            lines.append(f"  ... and {len(socket_edits) - 40} more")
        lines.append("")

    created = [op for op in plan.operations if op.kind == "xml_element_add"]
    if created:
        lines += ["Sockets created", "---------------"]
        for op in created:
            lines.append(f"  {op.target}")
        lines.append("")

    retargets = [op for op in plan.operations if op.kind == "paac_retarget"]
    if retargets:
        lines += ["Animation retargets", "-------------------"]
        for op in retargets:
            sites = len(op.detail.get("offsets") or [])
            lines.append(
                f"  {op.detail.get('old')} -> {op.detail.get('new')}"
                f"  ({sites} site(s) in {PurePosixPath(op.game_path).name})"
            )
        lines += [
            "",
            "  Retargets are same-length in-place string patches: the file size is unchanged",
            "  and every byte outside the patched spans is identical to vanilla.",
            "",
        ]

    if new_paths:
        lines += ["New files (not present in vanilla)", "----------------------------------"]
        for path in new_paths:
            lines.append(f"  {path}")
        lines.append("")

    lines += ["Test checklist", "--------------"]
    lines += [f"  [ ] {item}" for item in IN_GAME_CHECKLIST]
    lines += ["", "Pass means", "----------"]
    lines += [f"  - {item}" for item in PASS_CRITERIA]
    lines.append("")
    return "\n".join(lines)


def _scope_section(scope) -> List[str]:
    """The operation scope, stated in the README rather than only in the build dialog."""

    lines = ["Operation scope", "---------------"]
    lines.append(f"  Operations       : {', '.join(scope.operations) or '-'}")
    lines.append(f"  Equipment        : {', '.join(scope.equipment_units) or '-'}")
    lines.append(f"  Linked parts     : {', '.join(scope.linked_parts) or '-'}")
    lines.append(f"  Destination      : {scope.destination or '-'}")
    lines.append(f"  Descriptor rows  : {', '.join(scope.descriptor_parts) or '-'}")
    if scope.created_sockets:
        lines.append("  New child sockets:")
        for name in scope.created_sockets:
            source = dict(scope.orientation_sources).get(name, "")
            lines.append(f"    {name}{f'  ({source})' if source else ''}")
    if scope.modified_sockets:
        lines.append(f"  Sockets changed  : {', '.join(scope.modified_sockets)}")
    lines.append(
        f"  Shared sockets changed in place: {len(scope.shared_sockets_modified)}"
    )
    if scope.animation_targets:
        lines.append("  Animation target families:")
        for name, count in scope.animation_targets.items():
            lines.append(f"    {name}: {count}")
    if scope.animation_donors:
        lines.append("  Animation donor families:")
        for name, count in scope.animation_donors.items():
            lines.append(f"    {name}: {count}")
    if scope.borrowed_count or scope.mounted_count:
        lines.append(f"  Borrowed-character clips: {scope.borrowed_count}")
        lines.append(f"  Mounted clips           : {scope.mounted_count}")
    if scope.warnings_accepted:
        lines.append("  Warnings accepted:")
        lines += [f"    - {item}" for item in scope.warnings_accepted]
    lines.append("")
    return lines


def _lay_out_payload(root: Path, files: Mapping[str, bytes]) -> List[str]:
    written: List[str] = []
    for game_path, data in sorted(files.items()):
        target = root.joinpath(*PurePosixPath(game_path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(game_path)
    return written


def build_package(
    manager: str,
    plan: Plan,
    files: Mapping[str, bytes],
    metadata: PackageMetadata,
    *,
    out_root: Path,
    baseline=None,
    created_utc: Optional[str] = None,
    write_readme: bool = True,
    scope=None,
    manifest: Optional[Mapping[str, object]] = None,
) -> PackageResult:
    """Write one manager's package. Reuses the app's finalizer for all metadata."""

    profile = MANAGER_PROFILES.get(manager.upper())
    if profile is None:
        raise PackagingError(f"Unknown manager profile: {manager!r}")
    if not files:
        raise PackagingError("Nothing to package: no edited files")

    from cdmw.core.mod_package import finalize_mod_package_export
    from cdmw.domain.packages.export_policy import ModPackageExportOptions
    from cdmw.models import ModPackageInfo

    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    payload_paths = _lay_out_payload(root, files)
    new_paths = derive_new_paths(payload_paths, baseline) if baseline is not None else []

    info = ModPackageInfo(
        title=metadata.title_for(manager.upper()),
        version=metadata.version,
        author=metadata.author,
        description=metadata.description,
    )
    options = ModPackageExportOptions(
        manager_targets=tuple(profile["manager_targets"]),
        structure=str(profile["structure"]),
        create_manifest_json=bool(profile["create_manifest_json"]),
        create_modinfo_json=bool(profile["create_modinfo_json"]),
        create_mod_json=bool(profile["create_mod_json"]),
        create_no_encrypt_file=bool(profile["create_no_encrypt_file"]),
    )

    result = finalize_mod_package_export(
        root,
        info,
        kind=str(profile.get("kind") or "archive_loose_mod"),
        payload_paths=payload_paths,
        new_file_paths=new_paths,
        options=options,
        created_utc=created_utc,
    )

    if write_readme:
        (root / "README.txt").write_text(
            build_readme(
                plan,
                metadata,
                manager=manager.upper(),
                payload_paths=payload_paths,
                new_paths=new_paths,
                scope=scope,
            ),
            encoding="utf-8",
        )

    if manifest is not None:
        from .preflight import write_operation_manifest

        write_operation_manifest(root, manifest)

    metadata_files = tuple(
        sorted(
            Path(path).name
            for path in getattr(result, "metadata_files", ()) or ()
        )
    )
    return PackageResult(
        manager=manager.upper(),
        root=root,
        payload_paths=tuple(payload_paths),
        new_paths=tuple(new_paths),
        metadata_files=metadata_files,
    )


def build_all(
    plan: Plan,
    files: Mapping[str, bytes],
    metadata: PackageMetadata,
    *,
    out_root: Path,
    baseline=None,
    created_utc: Optional[str] = None,
    managers: Sequence[str] = ("CDUMM", "DMM", "JMM"),
    scope=None,
    manifest: Optional[Mapping[str, object]] = None,
) -> List[PackageResult]:
    """Emit every manager layout from one plan — the point of the operation model."""

    results: List[PackageResult] = []
    for manager in managers:
        target = Path(out_root) / f"{metadata.name} - {manager.upper()}"
        results.append(
            build_package(
                manager,
                plan,
                files,
                metadata,
                out_root=target,
                baseline=baseline,
                created_utc=created_utc,
                scope=scope,
                manifest=manifest,
            )
        )
    return results


# ── packaging selected operations ────────────────────────────────────


#: What `build_for_operations` was asked to package.
SELECTION_LATEST = "latest"
SELECTION_SELECTED = "selected"
SELECTION_ALL = "all"


def operation_ids_for(session, mode: str, chosen: Sequence[str] = ()) -> List[str]:
    """Which operation ids a selection mode means.

    `latest` is the default and the only one that needs no confirmation: it is the operation
    the user has just accepted, and nothing else.
    """

    operations = session.operations()
    if mode == SELECTION_ALL:
        return [op.operation_id for op in operations]
    if mode == SELECTION_SELECTED:
        wanted = set(chosen)
        return [op.operation_id for op in operations if op.operation_id in wanted]
    return [operations[-1].operation_id] if operations else []


def build_for_operations(
    session,
    operation_ids: Sequence[str],
    metadata: PackageMetadata,
    *,
    out_root: Path,
    baseline=None,
    created_utc: Optional[str] = None,
    managers: Sequence[str] = ("CDUMM", "DMM", "JMM"),
    units: Optional[Mapping[str, object]] = None,
    shared_socket_users: Optional[Mapping[str, Sequence[str]]] = None,
    replacements: Sequence[object] = (),
    accept_warnings: bool = False,
) -> Tuple[List[PackageResult], object]:
    """Package exactly these operations, replayed onto vanilla, or refuse and say why.

    This replaces calling the builder with the global session preview. The isolated replay is
    what makes an earlier experiment unable to reach the package; the preflight is what proves
    it, and what stops an in-scope change that is nonetheless unsafe — a shared socket edited
    in place, a case row left behind, an animation family that is not this weapon's.

    Returns `(results, preflight)`. `results` is empty when the preflight blocked.
    """

    from .preflight import operation_manifest, run_preflight

    wanted = list(dict.fromkeys(operation_ids))
    if not wanted:
        raise PackagingError("No operation selected, so there is nothing to package")

    verdict = run_preflight(
        session,
        wanted,
        units=units,
        shared_socket_users=shared_socket_users,
        replacements=replacements,
    )
    if verdict.blocked:
        return [], verdict
    if verdict.needs_confirmation and not accept_warnings:
        return [], verdict

    isolated = session.isolated_session(wanted)
    files = isolated.preview()
    if not files:
        raise PackagingError(
            "The selected operation changes no file, so there is nothing to package"
        )
    plan = isolated.to_plan(metadata.name or "operation")
    selected = [op for op in session.operations() if op.operation_id in set(wanted)]
    manifest = operation_manifest(selected, verdict.summary, units=units)

    results = build_all(
        plan,
        files,
        metadata,
        out_root=Path(out_root),
        baseline=baseline,
        created_utc=created_utc,
        managers=managers,
        scope=verdict.summary,
        manifest=manifest,
    )
    return results, verdict
