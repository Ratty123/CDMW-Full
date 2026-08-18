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
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping, Optional, Tuple

from cdmw.core.item_icon_addition import NewItemIcon, build_new_item_icon
from cdmw.domain.archives.mutation import ArchivePatchResult
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
    "DMM": {"manager_targets": ("dmm",), "structure": "game_relative", "create_manifest_json": True, "create_modinfo_json": True, "create_no_encrypt_file": False, "create_mod_json": False, "kind": "archive_loose_mod"},
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

    def allocate(self, spec: NewItemSpec, snapshot: NewItemSnapshot) -> NewItemSpec:
        """The spec with item key, stem (when needed) and localisation keys filled in."""

        try:
            item_key = allocate_item_key(snapshot.rows, preferred=spec.item_key)
            stem = spec.stem
            if spec.needs_new_stem and stem is None:
                family = snapshot.family(spec.template_key)
                taken = set(snapshot.pappt.index()) | set(snapshot.stringinfo_texts.values()) | set(snapshot.model_stems)
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
        allocated = self.allocate(spec, snapshot)
        more = validate_against_context(allocated, build_context(snapshot, allocated.template_key))
        if has_errors(more):
            raise NewItemPlanError("; ".join(issue.message for issue in more if issue.is_error), more)
        files: Optional[ModelFiles] = None
        if isinstance(model, ModelFiles):
            files = model
        elif model is not None:
            files = model_files_from_import(model, family=snapshot.family(allocated.template_key))
            raise_if_cancelled(stop_event, "New item plan cancelled.")
            files = route_model_files(files, allocated.material_route, result=model, scene=scene, on_log=on_log)
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
        root = Path(package_root)
        root.mkdir(parents=True, exist_ok=True)
        payload_paths = []
        for game_path, data in sorted(plan.loose_files.items()):
            raise_if_cancelled(stop_event, "New item export cancelled.")
            target = root.joinpath(*PurePosixPath(game_path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            payload_paths.append(game_path)
        info = package_info or ModPackageInfo(
            title=f"New item {plan.spec.internal_name}",
            description=f"Adds {plan.spec.internal_name} (item {plan.spec.item_key}) cloned from item {plan.spec.template_key}.",
        )
        if options is None:
            options = ModPackageExportOptions(
                manager_targets=tuple(profile["manager_targets"]),
                structure=str(profile["structure"]),
                create_manifest_json=bool(profile["create_manifest_json"]),
                create_modinfo_json=bool(profile["create_modinfo_json"]),
                create_mod_json=bool(profile["create_mod_json"]),
                create_no_encrypt_file=bool(profile["create_no_encrypt_file"]),
            )
        kind = str((profile or {}).get("kind") or "archive_loose_mod")
        result = finalize_mod_package_export(
            root, info, kind=kind, payload_paths=payload_paths, new_file_paths=list(plan.new_paths),
            options=options, created_utc=created_utc,
        )
        metadata = tuple(sorted(Path(path).name for path in getattr(result, "metadata_files", ()) or ()))
        return NewItemExportResult(
            package_root=root, manager=str(manager or "").upper() or "custom",
            payload_paths=tuple(payload_paths), new_paths=tuple(plan.new_paths), metadata_files=metadata,
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


__all__ = [
    "GAME_EXECUTABLE",
    "LOOSE_EXPORT_PROFILES",
    "NewItemExportResult",
    "NewItemInstallRefused",
    "NewItemService",
    "game_is_running",
]
