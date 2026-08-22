"""The New Item Studio's service: snapshot, validate, allocate, plan, export, install.

No Qt here and no direct archive writes: reading goes through
:mod:`cdmw.services.new_item_snapshot`, planning through
:mod:`cdmw.services.new_item_planning`, and installing through
:class:`~cdmw.services.archive_mutation_service.ArchiveMutationService`, which owns
the backup, the checksum chain and the restore. Long calls (the snapshot, a plan
with fourteen language tables, an install with its PAZ checksums) are meant to run
through :mod:`cdmw.workers.new_item_workers`.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping, Optional, Tuple

from cdmw.core.item_icon_addition import NewItemIcon, build_new_item_icon
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchResult
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.library.item_icons import ITEM_ICON_DEFAULT_BACKGROUND_MODE
from cdmw.domain.new_item.allocation import AllocationError, allocate_item_key, localization_keys, suggest_stem
from cdmw.domain.new_item.rules import NewItemContext, ValidationIssue, has_errors, validate_against_context, validate_spec
from cdmw.domain.new_item.spec import IconSource, NewItemSpec
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.services.new_item_materials import route_model_files
from cdmw.services.new_item_planning import (
    ModelFiles,
    NewItemPlan,
    NewItemPlanError,
    build_plan,
    model_files_from_import,
    planned_icon_string,
)
from cdmw.services.new_item_snapshot import NewItemSnapshot, build_context, build_snapshot

GAME_EXECUTABLE = "CrimsonDesert.exe"

#: The loose-mod layouts the Placement Studio's golden packages established, by manager.
LOOSE_EXPORT_PROFILES: Mapping[str, Mapping[str, object]] = {
    "CDUMM": {"manager_targets": ("cdumm",), "structure": "files_wrapper", "create_manifest_json": True, "create_modinfo_json": True, "create_no_encrypt_file": True, "create_mod_json": False, "kind": "archive_loose_mod"},
    # DMM mounts a prebuilt archive group rather than routing loose table files: its own
    # mount summary counts mods as JSON, browser/file, standalone-overlay or group-replace,
    # and a six-megabyte iteminfo.pabgb belongs to the last two. `archive_group` writes
    # what it mounts.
    "DMM": {"manager_targets": ("dmm",), "structure": "archive_group", "create_manifest_json": True, "create_modinfo_json": True, "create_no_encrypt_file": False, "create_mod_json": False, "kind": "archive_override_mod"},
    "JMM": {"manager_targets": ("jmm",), "structure": "game_relative", "create_manifest_json": False, "create_modinfo_json": False, "create_no_encrypt_file": False, "create_mod_json": False, "kind": "loose_mod"},
}


class NewItemInstallRefused(RuntimeError):
    """Raised when an install must not start: the game is running, or the plan was not confirmed."""


@dataclass(frozen=True, slots=True)
class NewItemExportResult:
    package_root: Path
    manager: str
    payload_paths: Tuple[str, ...]
    new_paths: Tuple[str, ...]
    metadata_files: Tuple[str, ...]


def game_is_running(image_name: str = GAME_EXECUTABLE) -> bool:
    """Whether the game's executable has a live process (Windows only; False elsewhere)."""

    if os.name != "nt":
        return False
    from cdmw.core.chainner import list_process_ids_by_image_name

    return bool(list_process_ids_by_image_name(image_name))


@dataclass(slots=True)
class NewItemService:
    settings: object | None = None

    # ------------------------------------------------------------------ reading

    def build_snapshot(
        self,
        entries: Iterable[ArchiveEntry],
        *,
        read_entry: Optional[Callable[[ArchiveEntry], bytes]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> NewItemSnapshot:
        return build_snapshot(entries, read_entry=read_entry, on_log=on_log, stop_event=stop_event)

    def build_context(self, snapshot: NewItemSnapshot, template_key: int) -> NewItemContext:
        return build_context(snapshot, template_key)

    # ------------------------------------------------------------------ rules

    def validate(self, spec: NewItemSpec, snapshot: NewItemSnapshot) -> Tuple[ValidationIssue, ...]:
        """Offline shape rules, then the collision rules against the snapshot."""

        issues = list(validate_spec(spec))
        if not has_errors(issues) and spec.template_key in snapshot.rows:
            issues.extend(validate_against_context(spec, build_context(snapshot, spec.template_key)))
        return tuple(issues)

    def allocate(
        self,
        spec: NewItemSpec,
        snapshot: NewItemSnapshot,
        *,
        reserved_keys: Iterable[int] = (),
        reserved_stems: Iterable[str] = (),
    ) -> NewItemSpec:
        """The spec with item key, stem (when needed) and localisation keys filled in.

        `reserved_keys` and `reserved_stems` are identities the caller has already handed
        out but the snapshot cannot see yet: a plan built earlier in the session, or an
        item written as a loose mod rather than installed. Without them a second item
        would be allocated the first one's key and stem, and installing it would overwrite
        the first.
        """

        try:
            used = set(snapshot.rows) | {int(value) for value in reserved_keys}
            item_key = allocate_item_key(used, preferred=spec.item_key)
            stem = spec.stem
            if spec.needs_new_stem and stem is None:
                family = snapshot.family(spec.template_key)
                taken = set(snapshot.pappt.index()) | set(snapshot.stringinfo_texts.values()) | set(snapshot.model_stems)
                taken |= {str(value) for value in reserved_stems if value}
                stem = suggest_stem(family.model_stem, taken)
        except AllocationError as exc:
            raise NewItemPlanError(str(exc)) from exc
        name_key, desc_key = localization_keys(item_key)
        template = snapshot.row(spec.template_key)
        return spec.with_allocations(
            item_key=item_key,
            stem=stem,
            name_key=name_key,
            desc_key=desc_key if template.desc_offset is not None else spec.desc_key,
        )

    # ------------------------------------------------------------------ planning

    def build_icon(
        self,
        spec: NewItemSpec,
        snapshot: NewItemSnapshot,
        source_path: Path,
        *,
        background_mode: str = ITEM_ICON_DEFAULT_BACKGROUND_MODE,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> NewItemIcon:
        """Generate the new item's icon from an image, shaped like the template's icon."""

        family = snapshot.family(spec.template_key)
        icon_files = [item for item in family.files_for("icon") if item.exists]
        if not icon_files:
            raise NewItemPlanError(f"{snapshot.row(spec.template_key).string_key} has no icon file to shape the new one after")
        reference = snapshot.entry(icon_files[0].path)
        return build_new_item_icon(
            source_path=Path(source_path),
            reference_entry=reference,
            reference_payload=snapshot.payload(icon_files[0].path),
            icon_string=planned_icon_string(spec, snapshot),
            background_mode=background_mode,
            existing_paths=snapshot.has_entry,
            on_log=on_log,
            stop_event=stop_event,
        )

    def plan(
        self,
        spec: NewItemSpec,
        snapshot: NewItemSnapshot,
        *,
        model: object | None = None,
        scene: object | None = None,
        icon: Optional[NewItemIcon] = None,
        icon_source_path: Optional[Path] = None,
        reserved_keys: Iterable[int] = (),
        reserved_stems: Iterable[str] = (),
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> NewItemPlan:
        """Validate, allocate and compose. `model` is a Builder result or :class:`ModelFiles`.

        A Builder result's materials are written the way `spec.material_route` says;
        the plain-PBR route reads the source's own textures through `scene` (the
        scene import result the Builder ran from) when it is given, and falls back
        to the Builder's textures when it is not. `ModelFiles` are taken as they are.

        A generated icon comes either pre-built (`icon`) or from `icon_source_path`,
        which this builds through the icon generator first.
        """

        raise_if_cancelled(stop_event, "New item plan cancelled.")
        issues = self.validate(spec, snapshot)
        if has_errors(issues):
            raise NewItemPlanError("; ".join(issue.message for issue in issues if issue.is_error), issues)
        allocated = self.allocate(spec, snapshot, reserved_keys=reserved_keys, reserved_stems=reserved_stems)
        more = validate_against_context(allocated, build_context(snapshot, allocated.template_key))
        if has_errors(more):
            raise NewItemPlanError("; ".join(issue.message for issue in more if issue.is_error), more)
        files: Optional[ModelFiles] = None
        if isinstance(model, ModelFiles):
            files = model
        elif model is not None:
            files = model_files_from_import(model, family=snapshot.family(allocated.template_key))
            raise_if_cancelled(stop_event, "New item plan cancelled.")
            files = route_model_files(files, allocated.material_route, result=model, scene=scene, glow=allocated.glow, on_log=on_log)
        built = icon
        if allocated.icon is IconSource.GENERATED and built is None:
            if icon_source_path is None:
                raise NewItemPlanError("the spec asks for a generated icon; give an icon or an image to build one from")
            built = self.build_icon(allocated, snapshot, icon_source_path, on_log=on_log, stop_event=stop_event)
        return build_plan(allocated, snapshot, model=files, icon=built, issues=tuple(issues) + tuple(more), on_log=on_log, stop_event=stop_event)

    # ------------------------------------------------------------------ writing

    def export_loose(
        self,
        plan: NewItemPlan,
        package_root: Path,
        *,
        manager: str = "CDUMM",
        package_info: Optional[ModPackageInfo] = None,
        options: Optional[ModPackageExportOptions] = None,
        created_utc: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> NewItemExportResult:
        """Write the plan as a loose mod under `package_root`, in one manager's layout."""

        from cdmw.core.mod_package import finalize_mod_package_export

        profile = LOOSE_EXPORT_PROFILES.get(str(manager or "").upper())
        if profile is None and options is None:
            raise ValueError(f"Unknown loose-mod manager profile {manager!r}; one of {', '.join(LOOSE_EXPORT_PROFILES)}")
        root = Path(package_root).expanduser().resolve()

        def write(staging: Path) -> NewItemExportResult:
            if str((profile or {}).get("structure") or "") == "archive_group" and options is None:
                return self._export_archive_group(
                    plan,
                    staging,
                    existing_root=root,
                    manager=manager,
                    package_info=package_info,
                    created_utc=created_utc,
                    stop_event=stop_event,
                )
            payload_paths = []
            for game_path, data in sorted(plan.loose_files.items()):
                raise_if_cancelled(stop_event, "New item export cancelled.")
                target = staging.joinpath(*PurePosixPath(game_path).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                payload_paths.append(game_path)
            info = package_info or ModPackageInfo(
                title=f"New item {plan.spec.internal_name}",
                description=f"Adds {plan.spec.internal_name} (item {plan.spec.item_key}) cloned from item {plan.spec.template_key}.",
            )
            resolved_options = options
            if resolved_options is None:
                resolved_options = ModPackageExportOptions(
                    manager_targets=tuple(profile["manager_targets"]),
                    structure=str(profile["structure"]),
                    create_manifest_json=bool(profile["create_manifest_json"]),
                    create_modinfo_json=bool(profile["create_modinfo_json"]),
                    create_mod_json=bool(profile["create_mod_json"]),
                    create_no_encrypt_file=bool(profile["create_no_encrypt_file"]),
                )
            kind = str((profile or {}).get("kind") or "archive_loose_mod")
            result = finalize_mod_package_export(
                staging,
                info,
                kind=kind,
                payload_paths=payload_paths,
                new_file_paths=list(plan.new_paths),
                options=resolved_options,
                created_utc=created_utc,
            )
            metadata = tuple(sorted(Path(path).name for path in getattr(result, "metadata_files", ()) or ()))
            return NewItemExportResult(
                package_root=staging,
                manager=str(manager or "").upper() or "custom",
                payload_paths=tuple(payload_paths),
                new_paths=tuple(plan.new_paths),
                metadata_files=metadata,
            )

        return _publish_package_atomically(root, write, stop_event=stop_event)

    def _export_archive_group(
        self,
        plan: NewItemPlan,
        root: Path,
        *,
        existing_root: Optional[Path] = None,
        manager: str,
        package_info: Optional[ModPackageInfo] = None,
        created_utc: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> NewItemExportResult:
        """The mod folder as an archive group: what a manager that mounts groups reads."""

        from cdmw.services.new_item_overlay_export import export_overlay_mod

        info = package_info or ModPackageInfo(
            title=f"New item {plan.spec.internal_name}",
            description=f"Adds {plan.spec.internal_name} (item {plan.spec.item_key}) cloned from item {plan.spec.template_key}.",
        )
        try:
            game_root = _package_root_of(plan)
        except NewItemInstallRefused:
            game_root = None
        source_root = Path(existing_root) if existing_root is not None else root
        group = _existing_archive_group(source_root)
        carried_plan = _carry_forward_archive_group(plan, source_root, group, stop_event=stop_event)
        raise_if_cancelled(stop_event, "New item export cancelled.")
        written = export_overlay_mod(
            carried_plan, root,
            group=group,
            title=str(getattr(info, "title", "") or ""),
            description=str(getattr(info, "description", "") or ""),
            author=str(getattr(info, "author", "") or ""),
            version=str(getattr(info, "version", "") or "1.0.0"),
            created_utc=str(created_utc or ""),
            game_root=game_root,
        )
        return NewItemExportResult(
            package_root=root,
            manager=str(manager or "").upper() or "custom",
            payload_paths=written.paths,
            new_paths=tuple(plan.new_paths),
            metadata_files=tuple(sorted(written.metadata_files)),
        )

    def install(
        self,
        plan: NewItemPlan,
        *,
        mutation_service,
        confirmed: bool = False,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
        game_running: Optional[Callable[[], bool]] = None,
    ) -> ArchivePatchResult:
        """Write the plan into the game archives through the mutation service.

        Refused while the game runs (its archives are open) and without `confirmed`;
        the mutation service backs up, validates, applies and restores on failure.
        """

        if not confirmed:
            raise NewItemInstallRefused("Installing a new item into the game archives requires explicit confirmation.")
        running = game_running if game_running is not None else game_is_running
        if running():
            raise NewItemInstallRefused(f"{GAME_EXECUTABLE} is running; close the game before installing, its archives are open.")
        if not plan.patches and not plan.additions:
            raise NewItemInstallRefused("The plan changes nothing.")
        mutation_plan = mutation_service.prepare_patch(
            plan.patches,
            additions=plan.additions,
            meta_files=plan.meta_files,
            confirmed=True,
            description=f"New item {plan.spec.internal_name} ({plan.spec.item_key}) from template {plan.spec.template_key}",
        )
        mutation_service.validate_patch(mutation_plan, stop_event=stop_event)
        return mutation_service.apply_patch(mutation_plan, on_log=on_log, stop_event=stop_event)

    def install_overlay(
        self,
        plan: NewItemPlan,
        *,
        mutation_service,
        confirmed: bool = False,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
        game_running: Optional[Callable[[], bool]] = None,
    ):
        """Write the plan as its own archive directory, mounted ahead of the shipped ones.

        The shipped archives are not opened for writing at all: what changes is a new
        directory beside them, `meta/0.papgt` naming it first, and the texture registry.
        The backup is those two files and whatever the workbench's own overlay held
        before, so an install is kilobytes of backup instead of gigabytes.
        """

        from cdmw.services.archive_overlay_install import install_overlay as write_overlay

        if not confirmed:
            raise NewItemInstallRefused("Installing a new item into the game archives requires explicit confirmation.")
        running = game_running if game_running is not None else game_is_running
        if running():
            raise NewItemInstallRefused(f"{GAME_EXECUTABLE} is running; close the game before installing, its archives are open.")
        if not plan.patches and not plan.additions:
            raise NewItemInstallRefused("The plan changes nothing.")
        if not hasattr(mutation_service, "backup_files") or not hasattr(mutation_service, "restore_backup"):
            raise NewItemInstallRefused("The archive mutation service is not available in this window.")
        package_root = _package_root_of(plan)
        description = f"New item {plan.spec.internal_name} ({plan.spec.item_key}) as an overlay"

        def backup(paths, label):
            return mutation_service.backup_files(paths, description=f"{description}: {label}", on_log=on_log)

        def restore(path):
            return mutation_service.restore_backup(path, confirmed=True, on_log=on_log)

        return write_overlay(
            plan.patches,
            plan.additions,
            package_root=package_root,
            meta_files=[(write.path, write.payload_data) for write in plan.meta_files],
            backup=backup,
            restore_backup=restore,
            game_running=running,
            confirmed=True,
            on_log=on_log,
            stop_event=stop_event,
        )


def _publish_package_atomically(
    package_root: Path,
    writer: Callable[[Path], NewItemExportResult],
    *,
    stop_event: Optional[threading.Event] = None,
) -> NewItemExportResult:
    """Build beside the destination, then publish with a rollback rename."""

    from cdmw.core.atomic_file import atomic_publish_directory

    root = Path(package_root).expanduser().resolve()
    parent = root.parent
    if root == parent:
        raise ValueError(f"Loose root does not exist or is not a folder: {root}")
    if root.exists() and not root.is_dir():
        raise ValueError(f"Loose root does not exist or is not a folder: {root}")
    parent.mkdir(parents=True, exist_ok=True)
    raise_if_cancelled(stop_event, "New item export cancelled.")
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.cdmw-stage-", dir=parent))
    try:
        if root.is_dir():
            shutil.copytree(root, staging, dirs_exist_ok=True)
        raise_if_cancelled(stop_event, "New item export cancelled.")
        result = writer(staging)
        raise_if_cancelled(stop_event, "New item export cancelled.")
        atomic_publish_directory(staging, root)
        return replace(result, package_root=root)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _existing_archive_group(root: Path) -> str:
    """The first archive group an existing DMM package mounts, or an empty string."""

    package = Path(root)
    if not package.is_dir():
        return ""
    from cdmw.core.papgt_format import parse_papgt

    mount = package / "meta" / "0.papgt"
    if mount.is_file():
        for item in parse_papgt(mount.read_bytes()):
            name = str(item.name)
            if (package / name / "0.pamt").is_file() and (package / name / "0.paz").is_file():
                return name
    return next(
        (
            path.parent.name
            for path in sorted(package.glob("*/0.pamt"))
            if (path.parent / "0.paz").is_file()
        ),
        "",
    )


def _carry_forward_archive_group(
    plan: NewItemPlan,
    root: Path,
    group: str,
    *,
    stop_event: Optional[threading.Event] = None,
) -> NewItemPlan:
    """Keep files from a prior DMM export that the new plan does not replace."""

    if not group:
        return plan
    pamt = Path(root) / group / "0.pamt"
    if not pamt.is_file():
        return plan
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt

    changed = {
        str(request.entry.path).replace("\\", "/").strip("/").casefold()
        for request in plan.patches
    }
    changed.update(str(item.path).replace("\\", "/").strip("/").casefold() for item in plan.additions)
    carried = []
    for entry in parse_archive_pamt(pamt):
        raise_if_cancelled(stop_event, "New item export cancelled.")
        path = str(entry.path).replace("\\", "/").strip("/")
        if path.casefold() in changed:
            continue
        payload, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
        carried.append(
            ArchiveAddRequest(
                pamt_path=Path(entry.pamt_path),
                path=path,
                payload_data=bytes(payload),
                flags=int(entry.flags),
            )
        )
    return replace(plan, additions=tuple(carried) + tuple(plan.additions)) if carried else plan


def _package_root_of(plan: NewItemPlan) -> Path:
    """The install this plan was built against: the folder that holds `meta/0.papgt`."""

    for request in plan.patches:
        pamt_path = Path(request.entry.pamt_path)
        return pamt_path.parent.parent
    for addition in plan.additions:
        return Path(addition.pamt_path).parent.parent
    raise NewItemInstallRefused("The plan names no archive to install into.")


__all__ = [
    "GAME_EXECUTABLE",
    "LOOSE_EXPORT_PROFILES",
    "NewItemExportResult",
    "NewItemInstallRefused",
    "NewItemService",
    "game_is_running",
]
