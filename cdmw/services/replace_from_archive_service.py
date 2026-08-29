"""Plan and publish exact archive-to-archive mesh-family replacements."""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath

from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.domain.archives.mutation import ArchivePatchRequest
from cdmw.domain.archives.replace_from_archive import (
    ReplaceFromArchiveActionKind,
    ReplaceFromArchiveCharacterMode,
    ReplaceFromArchiveFileAction,
    ReplaceFromArchivePlan,
    ReplaceFromArchiveRequest,
)
from cdmw.domain.archives.safety import safe_archive_output_path
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.domain.packages.layout import normalize_mod_package_payload_path
from cdmw.domain.xml_text import decode_xml_text_payload, encode_xml_text_like_source
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.services.archive_query_service import (
    find_archive_model_related_entries,
    find_archive_model_sidecar_entries,
)
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.archive_workflow_service import (
    build_character_swap_plan,
    build_iteminfo_behavior_equip_type_patch,
    build_pac_xml_stack_equip_type_patch,
    build_part_in_out_socket_class_copy_patch,
    build_prefab_attachment_profile_patch,
    export_archive_payloads_to_mod_ready_loose,
    infer_part_in_out_weapon_class,
    infer_stack_equip_type_for_socket,
    inspect_prefab_attachment_profile_fields,
)
from cdmw.services.atomic_file_service import atomic_publish_directory

_PHYSICS_EXTENSIONS = {".hkx", ".hkt"}
_MOTION_EXTENSIONS = {".paa", ".paa_metabin", ".motionblending"}
_SIDECAR_EXTENSIONS = {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami", ".xml"}
_CHARACTER_MARKERS = ("/character/model/", "/character/appearance/")
_WEAPON_MARKERS = (
    "/weapon/",
    "/shield/",
    "/subweapon/",
    "/onehandweapon/",
    "/twohandweapon/",
    "/bow/",
    "/musket/",
    "/instrument/",
)


def archive_entries_are_character_pair(
    target: ArchiveEntry, source: ArchiveEntry
) -> bool:
    return _is_character(target) and _is_character(source)


def build_replace_from_archive_plan(
    request: ReplaceFromArchiveRequest,
    *,
    entries: Sequence[ArchiveEntry],
    entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]],
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    stop_event: threading.Event | None = None,
) -> ReplaceFromArchivePlan:
    """Build one immutable, read-only file mapping for a loose replacement mod."""

    target = request.target_entry
    source = request.source_entry
    warnings: list[str] = []
    blockers: list[str] = []
    actions: list[ReplaceFromArchiveFileAction] = []
    target_keys: set[str] = set()

    def add_action(action: ReplaceFromArchiveFileAction) -> None:
        if action.kind is ReplaceFromArchiveActionKind.REUSE:
            actions.append(action)
            return
        raw_key = _normalized(action.target_path)
        if not raw_key:
            blockers.append(f"{action.role} has no resolved target path.")
            return
        try:
            safe_archive_output_path(
                Path("__replace_from_archive_path_check__"),
                action.target_path,
                error_message="path is not a safe game-relative payload path",
            )
            package_path = normalize_mod_package_payload_path(action.target_path)
        except ValueError as exc:
            blockers.append(f"{action.role} has an invalid target path: {exc}")
            return
        key = package_path.as_posix().casefold()
        if not key:
            blockers.append(f"{action.role} has no resolved package target path.")
            return
        if key in target_keys:
            blockers.append(
                f"More than one replacement action targets {action.target_path}."
            )
            return
        target_keys.add(key)
        actions.append(action)

    if _same_entry(target, source):
        blockers.append("Choose a source mesh different from the current target.")
    target_extension = _extension(target)
    source_extension = _extension(source)
    if (
        target_extension not in ARCHIVE_MESH_EXTENSIONS
        or source_extension not in ARCHIVE_MESH_EXTENSIONS
    ):
        blockers.append(
            "Replace from Archive requires PAC, PAM, or PAMLOD mesh entries."
        )
    elif target_extension != source_extension:
        blockers.append(
            f"The source and target mesh containers differ ({source_extension} to {target_extension})."
        )

    source_payload = b""
    source_mesh = None
    if not blockers:
        try:
            source_payload = _read(source, stop_event)
            source_mesh = parse_mesh(source_payload, source.path)
            if not getattr(source_mesh, "submeshes", None):
                blockers.append(
                    "The selected source did not contain recoverable mesh parts."
                )
        except Exception as exc:  # noqa: BLE001 - parser/read failures become plan blockers
            blockers.append(f"The selected source mesh could not be read: {exc}")
    if source_payload and not blockers:
        add_action(
            ReplaceFromArchiveFileAction(
                role="Model",
                kind=ReplaceFromArchiveActionKind.COPY,
                source_entry=source,
                target_entry=target,
                payload_data=source_payload,
                note="Exact source archive mesh bytes replace the selected target model.",
            )
        )
        try:
            target_mesh = parse_mesh(_read(target, stop_event), target.path)
            if bool(getattr(target_mesh, "has_bones", False)) != bool(
                getattr(source_mesh, "has_bones", False)
            ):
                warnings.append(
                    "Source and target rig contracts differ; the selected identity mode and target routing remain authoritative."
                )
        except Exception as exc:  # noqa: BLE001 - comparison is optional warning evidence
            warnings.append(f"Target rig comparison was unavailable: {exc}")

    raise_if_cancelled(stop_event, "Replace from Archive planning cancelled.")
    source_related = _related(source, entries_by_basename)
    target_related = _related(target, entries_by_basename)

    target_family = _asset_family(target)
    source_family = _asset_family(source)
    if target_family != source_family:
        warnings.append(
            f"Cross-family replacement selected ({source_family} source to {target_family} target); "
            "only companions with proven target roles will be mapped."
        )
    elif target_family in {"world", "unknown"}:
        warnings.append(
            f"The {target_family} asset family has no complete behavior contract; "
            "unresolved companions will remain unchanged."
        )

    source_sidecars = _sidecars(source, entries_by_basename)
    target_sidecars = _sidecars(target, entries_by_basename)
    source_sidecar = _preferred_sidecar(source, source_sidecars)
    target_sidecar = _preferred_sidecar(target, target_sidecars)
    source_prefab = _first_extension(source_related, {".prefab"})
    target_prefab = _first_extension(target_related, {".prefab"})
    source_prefab_fields: dict[str, str] = {}
    if source_prefab is not None:
        try:
            source_prefab_fields = {
                str(field.field_name): str(field.value)
                for field in inspect_prefab_attachment_profile_fields(
                    _read(source_prefab, stop_event)
                )
            }
        except Exception as exc:  # noqa: BLE001 - binary metadata failures are warning-only
            warnings.append(f"Source placement metadata could not be read: {exc}")

    if source_sidecar is not None and target_sidecar is not None:
        sidecar_payload = b""
        sidecar_read_ok = False
        sidecar_changed = False
        note = "Source material sidecar replaces the matching target material contract."
        try:
            sidecar_payload = _read(source_sidecar, stop_event)
            sidecar_read_ok = True
            attached_socket = source_prefab_fields.get("_attachedSocketName", "")
            equip_type = infer_stack_equip_type_for_socket(attached_socket)
            if equip_type:
                decoded = decode_xml_text_payload(sidecar_payload)
                stack_patch = build_pac_xml_stack_equip_type_patch(
                    decoded.text, equip_type=equip_type
                )
                if stack_patch.changed:
                    sidecar_payload = encode_xml_text_like_source(
                        stack_patch.text, sidecar_payload
                    )
                    sidecar_changed = True
                    note += f" Stack equip type follows {equip_type}."
        except Exception as exc:  # noqa: BLE001 - sidecar preparation is warning-only
            warnings.append(f"Source material sidecar could not be prepared: {exc}")
        if sidecar_read_ok:
            add_action(
                ReplaceFromArchiveFileAction(
                    role="Material sidecar",
                    kind=(
                        ReplaceFromArchiveActionKind.PATCH
                        if sidecar_changed
                        else ReplaceFromArchiveActionKind.COPY
                    ),
                    source_entry=source_sidecar,
                    target_entry=target_sidecar,
                    payload_data=sidecar_payload,
                    note=note,
                )
            )
    elif source_sidecar is None:
        warnings.append(
            "No source material sidecar was resolved; the replacement may render with target materials."
        )
    else:
        warnings.append(
            "No target material-sidecar path was resolved; source materials cannot be mapped safely."
        )

    _add_paired_lod_action(
        add_action, warnings, source, target, source_related, target_related
    )
    _add_role_copy_actions(
        add_action,
        warnings,
        role="Physics",
        extensions=_PHYSICS_EXTENSIONS,
        source_model=source,
        target_model=target,
        source_entries=source_related,
        target_entries=target_related,
    )
    _add_role_copy_actions(
        add_action,
        warnings,
        role="Motion",
        extensions=_MOTION_EXTENSIONS,
        source_model=source,
        target_model=target,
        source_entries=source_related,
        target_entries=target_related,
    )

    for texture in sorted(
        (entry for entry in source_related if _extension(entry) == ".dds"),
        key=lambda entry: entry.path.casefold(),
    ):
        add_action(
            ReplaceFromArchiveFileAction(
                role="Texture reference",
                kind=ReplaceFromArchiveActionKind.REUSE,
                source_entry=texture,
                target_entry=None,
                note="Reused from its existing source archive path; no duplicate DDS is written.",
            )
        )

    if _is_weapon(target) or _is_weapon(source):
        _add_weapon_placement_actions(
            add_action,
            warnings,
            target=target,
            source=source,
            target_prefab=target_prefab,
            source_prefab=source_prefab,
            source_fields=source_prefab_fields,
            entries=entries,
            stop_event=stop_event,
        )

    if archive_entries_are_character_pair(target, source):
        _add_character_actions(
            add_action,
            warnings,
            request=request,
            entries=entries,
            source_related=source_related,
            target_related=target_related,
            stop_event=stop_event,
        )

    if (
        request.character_mode is not ReplaceFromArchiveCharacterMode.NOT_CHARACTER
        and not archive_entries_are_character_pair(target, source)
    ):
        warnings.append(
            "The selected character identity mode was ignored because this is not a character-to-character pair."
        )

    raise_if_cancelled(stop_event, "Replace from Archive planning cancelled.")
    return ReplaceFromArchivePlan(
        request=request,
        actions=tuple(actions),
        warnings=tuple(dict.fromkeys(warnings)),
        blockers=tuple(dict.fromkeys(blockers)),
    )


def export_replace_from_archive_plan(
    plan: ReplaceFromArchivePlan,
    *,
    parent_root: Path,
    package_info: ModPackageInfo,
    export_options: ModPackageExportOptions,
    create_no_encrypt_file: bool,
    on_log: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> ArchiveLooseExportResult:
    """Build under a sibling staging root, then atomically publish each package."""

    if not plan.can_build:
        raise ValueError("Replace from Archive plan has blocking issues.")
    requests: list[ArchivePatchRequest] = []
    for action in plan.copied_actions:
        raise_if_cancelled(stop_event, "Replace from Archive export cancelled.")
        if not isinstance(action.target_entry, ArchiveEntry):
            raise TypeError(f"{action.role} has no target archive entry.")
        payload = bytes(action.payload_data or b"")
        if not payload:
            if not isinstance(action.source_entry, ArchiveEntry):
                raise ValueError(f"{action.role} has no source archive entry.")
            payload = _read(action.source_entry, stop_event)
        requests.append(ArchivePatchRequest(action.target_entry, payload))
    if not requests:
        raise ValueError("Replace from Archive produced no writable payloads.")

    root = parent_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(
        tempfile.mkdtemp(prefix=".cdmw-replace-from-archive-", dir=str(root))
    )

    def _cancellable_log(message: str) -> None:
        raise_if_cancelled(stop_event, "Replace from Archive export cancelled.")
        if on_log is not None:
            on_log(message)
        raise_if_cancelled(stop_event, "Replace from Archive export cancelled.")

    try:
        result = export_archive_payloads_to_mod_ready_loose(
            requests,
            parent_root=staging_parent,
            package_info=_package_info_with_plan(package_info, plan),
            export_options=dataclasses.replace(export_options, create_zip=False),
            create_no_encrypt_file=create_no_encrypt_file,
            on_log=_cancellable_log,
        )
        _validate_staged_package_result(result, plan)
        raise_if_cancelled(
            stop_event, "Replace from Archive export cancelled before publication."
        )
        staged_roots = tuple(result.package_roots or (result.package_root,))
        published_roots: list[Path] = []
        written_files: list[Path] = []
        for staged_root in staged_roots:
            relative = staged_root.resolve().relative_to(staging_parent.resolve())
            final_root = root / relative
            atomic_publish_directory(staged_root, final_root)
            published_roots.append(final_root)
            written_files.extend(
                sorted(
                    (path for path in final_root.rglob("*") if path.is_file()),
                    key=lambda path: path.as_posix().casefold(),
                )
            )
        return ArchiveLooseExportResult(
            package_root=published_roots[0],
            written_files=written_files,
            package_roots=tuple(published_roots),
        )
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def _add_weapon_placement_actions(
    add_action: Callable[[ReplaceFromArchiveFileAction], None],
    warnings: list[str],
    *,
    target: ArchiveEntry,
    source: ArchiveEntry,
    target_prefab: ArchiveEntry | None,
    source_prefab: ArchiveEntry | None,
    source_fields: Mapping[str, str],
    entries: Sequence[ArchiveEntry],
    stop_event: threading.Event | None,
) -> None:
    attached = str(source_fields.get("_attachedSocketName", "") or "")
    pivot = str(source_fields.get("_pivotSocketName", "") or "")
    if target_prefab is None or source_prefab is None:
        warnings.append(
            "Validated weapon placement could not be produced because source or target prefab metadata is missing."
        )
    elif not attached or not pivot:
        warnings.append(
            "Validated weapon placement could not be produced from the source prefab socket fields."
        )
    else:
        try:
            target_payload = _read(target_prefab, stop_event)
            patch = build_prefab_attachment_profile_patch(
                target_payload,
                attached_socket_name=attached,
                pivot_socket_name=pivot,
                part_name=str(source_fields.get("_partName", "") or ""),
                socket_file_path=str(source_fields.get("_socketFileName", "") or ""),
                allow_length_changes=False,
            )
            add_action(
                ReplaceFromArchiveFileAction(
                    role="Weapon placement",
                    kind=ReplaceFromArchiveActionKind.PATCH,
                    source_entry=source_prefab,
                    target_entry=target_prefab,
                    payload_data=patch.data,
                    note=f"Target-owned prefab placement follows {attached} / {pivot}.",
                )
            )
        except Exception as exc:  # noqa: BLE001 - validated patcher failures remain warnings
            warnings.append(f"Validated weapon placement could not be produced: {exc}")

    table_names = (
        "iteminfo.pabgb",
        "iteminfo.pabgh",
        "equiptypeinfo.pabgb",
        "equiptypeinfo.pabgh",
    )
    tables = {name: _first_basename(entries, name) for name in table_names}
    if not all(tables.values()):
        warnings.append(
            "Full weapon equip behavior could not be patched because ItemInfo or EquipTypeInfo was outside the prepared dependency set."
        )
    else:
        try:
            behavior = build_iteminfo_behavior_equip_type_patch(
                _read(tables["iteminfo.pabgb"], stop_event),  # type: ignore[arg-type]
                _read(tables["iteminfo.pabgh"], stop_event),  # type: ignore[arg-type]
                _read(tables["equiptypeinfo.pabgb"], stop_event),  # type: ignore[arg-type]
                _read(tables["equiptypeinfo.pabgh"], stop_event),  # type: ignore[arg-type]
                target_model_path=target.path,
                source_model_path=source.path,
                target_weapon_class=infer_part_in_out_weapon_class(target.path),
                source_weapon_class=infer_part_in_out_weapon_class(source.path),
            )
            if behavior.blocking_reason:
                warnings.append(
                    f"Full weapon equip behavior was not patched: {behavior.blocking_reason}"
                )
            elif behavior.changed:
                add_action(
                    ReplaceFromArchiveFileAction(
                        role="Weapon equip behavior",
                        kind=ReplaceFromArchiveActionKind.PATCH,
                        source_entry=tables["iteminfo.pabgb"],
                        target_entry=tables["iteminfo.pabgb"],
                        payload_data=behavior.data,
                        note=f"Target equip behavior follows {behavior.new_equip_type_name}.",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - validated patcher failures remain warnings
            warnings.append(f"Full weapon equip behavior could not be patched: {exc}")

    part_in_out = next(
        (
            entry
            for entry in entries
            if "partinoutsocket" in entry.basename.casefold()
            and _extension(entry) in {".xml", ".app_xml"}
        ),
        None,
    )
    target_class = infer_part_in_out_weapon_class(target.path)
    source_class = infer_part_in_out_weapon_class(source.path)
    if part_in_out is None or not target_class or not source_class:
        warnings.append(
            "Held and stowed weapon placement could not be patched because the shared PartInOut socket table was not resolved."
        )
        return
    try:
        original = _read(part_in_out, stop_event)
        decoded = decode_xml_text_payload(original)
        stowed = build_part_in_out_socket_class_copy_patch(
            decoded.text,
            target_weapon_class=target_class,
            source_weapon_class=source_class,
            placement_state="stowed",
        )
        held = build_part_in_out_socket_class_copy_patch(
            stowed.text,
            target_weapon_class=target_class,
            source_weapon_class=source_class,
            placement_state="held",
        )
        if stowed.diffs or held.diffs:
            add_action(
                ReplaceFromArchiveFileAction(
                    role="Weapon held/stowed sockets",
                    kind=ReplaceFromArchiveActionKind.PATCH,
                    source_entry=part_in_out,
                    target_entry=part_in_out,
                    payload_data=encode_xml_text_like_source(held.text, original),
                    note="Target-owned PartInOut rows follow the source weapon class for held and stowed placement.",
                )
            )
        else:
            warnings.append(
                "Held and stowed weapon placement rows were present but no validated target-owned socket changes were produced."
            )
    except Exception as exc:  # noqa: BLE001 - validated patcher failures remain warnings
        warnings.append(f"Held and stowed weapon placement could not be patched: {exc}")


def _add_character_actions(
    add_action: Callable[[ReplaceFromArchiveFileAction], None],
    warnings: list[str],
    *,
    request: ReplaceFromArchiveRequest,
    entries: Sequence[ArchiveEntry],
    source_related: Sequence[ArchiveEntry],
    target_related: Sequence[ArchiveEntry],
    stop_event: threading.Event | None,
) -> None:
    mode = request.character_mode
    if mode is ReplaceFromArchiveCharacterMode.NOT_CHARACTER:
        warnings.append(
            "Choose how this character replacement should handle appearance identity."
        )
        return
    if mode is ReplaceFromArchiveCharacterMode.PRESERVE_TARGET:
        return
    if mode is ReplaceFromArchiveCharacterMode.BODY_HEAD_PATCH:
        try:
            relationship_plan = build_character_swap_plan(
                request.target_entry,
                request.source_entry,
                entries,
            )
            payload = bytes(
                getattr(relationship_plan, "patched_target_app_xml", b"") or b""
            )
            target_path = str(
                getattr(relationship_plan, "patched_target_app_path", "") or ""
            )
            target_app = _entry_for_path(entries, target_path)
            if payload and target_app is not None:
                add_action(
                    ReplaceFromArchiveFileAction(
                        role="Character body/head identity",
                        kind=ReplaceFromArchiveActionKind.PATCH,
                        source_entry=None,
                        target_entry=target_app,
                        payload_data=payload,
                        note="Body and head references follow the source while target hair, armour, skeleton, and animation remain.",
                    )
                )
            else:
                warnings.append(
                    "No surgical target appearance patch could be produced for this character pair."
                )
        except Exception as exc:  # noqa: BLE001 - relationship gaps remain warnings
            warnings.append(
                f"Character body/head identity patch could not be produced: {exc}"
            )
        return
    source_app = _best_appearance(request.source_entry, source_related, entries)
    target_app = _best_appearance(request.target_entry, target_related, entries)
    if source_app is None or target_app is None:
        warnings.append(
            "Full source character identity could not resolve both source and target APP XML descriptors."
        )
        return
    try:
        payload = _read(source_app, stop_event)
        add_action(
            ReplaceFromArchiveFileAction(
                role="Full character identity",
                kind=ReplaceFromArchiveActionKind.COPY,
                source_entry=source_app,
                target_entry=target_app,
                payload_data=payload,
                note="Target appearance redirects to the complete source appearance graph.",
            )
        )
    except Exception as exc:  # noqa: BLE001 - appearance read gaps remain warnings
        warnings.append(f"Full source character identity could not be read: {exc}")


def _add_paired_lod_action(
    add_action: Callable[[ReplaceFromArchiveFileAction], None],
    warnings: list[str],
    source: ArchiveEntry,
    target: ArchiveEntry,
    source_related: Sequence[ArchiveEntry],
    target_related: Sequence[ArchiveEntry],
) -> None:
    pair_extension = (
        ".pamlod"
        if _extension(target) == ".pam"
        else ".pam"
        if _extension(target) == ".pamlod"
        else ""
    )
    if not pair_extension:
        return
    target_pair = _first_extension(target_related, {pair_extension})
    source_pair = _first_extension(source_related, {pair_extension})
    if target_pair is None:
        if source_pair is not None:
            warnings.append(
                f"Source has a paired {pair_extension} file but the target has no proven paired path; the source pair was skipped."
            )
        return
    if source_pair is None:
        warnings.append(
            f"Target has a paired {pair_extension} file but the source pair was not resolved; the target pair remains unchanged."
        )
        return
    add_action(
        ReplaceFromArchiveFileAction(
            role="Paired LOD",
            kind=ReplaceFromArchiveActionKind.COPY,
            source_entry=source_pair,
            target_entry=target_pair,
            note="Matching source runtime LOD replaces the target pair.",
        )
    )


def _add_role_copy_actions(
    add_action: Callable[[ReplaceFromArchiveFileAction], None],
    warnings: list[str],
    *,
    role: str,
    extensions: set[str],
    source_model: ArchiveEntry,
    target_model: ArchiveEntry,
    source_entries: Sequence[ArchiveEntry],
    target_entries: Sequence[ArchiveEntry],
) -> None:
    sources = [entry for entry in source_entries if _extension(entry) in extensions]
    targets = [entry for entry in target_entries if _extension(entry) in extensions]
    for source_entry in sources:
        target_entry = _matching_target_companion(
            source_entry, source_model, target_model, targets
        )
        if target_entry is None:
            warnings.append(
                f"{role} companion {source_entry.basename} has no resolved target path and was skipped."
            )
            continue
        add_action(
            ReplaceFromArchiveFileAction(
                role=role,
                kind=ReplaceFromArchiveActionKind.COPY,
                source_entry=source_entry,
                target_entry=target_entry,
                note=f"Source {role.casefold()} bytes replace the matching target companion.",
            )
        )


def _matching_target_companion(
    source_entry: ArchiveEntry,
    source_model: ArchiveEntry,
    target_model: ArchiveEntry,
    candidates: Sequence[ArchiveEntry],
) -> ArchiveEntry | None:
    same_extension = [
        entry for entry in candidates if _extension(entry) == _extension(source_entry)
    ]
    if not same_extension:
        return None
    source_stem = PurePosixPath(source_model.path.replace("\\", "/")).stem.casefold()
    target_stem = PurePosixPath(target_model.path.replace("\\", "/")).stem
    source_path = source_entry.path.replace("\\", "/")
    expected_name = PurePosixPath(source_path).name
    if source_stem:
        match_at = expected_name.casefold().find(source_stem)
        if match_at >= 0:
            expected_name = (
                expected_name[:match_at]
                + target_stem
                + expected_name[match_at + len(source_stem) :]
            )
    for candidate in same_extension:
        if candidate.basename.casefold() == expected_name.casefold():
            return candidate
    return None


def _validate_staged_package_result(
    result: ArchiveLooseExportResult,
    plan: ReplaceFromArchivePlan,
) -> None:
    expected_paths = {
        normalize_mod_package_payload_path(action.target_path).as_posix().casefold()
        for action in plan.copied_actions
    }
    roots = tuple(result.package_roots or (result.package_root,))
    if not roots:
        raise ValueError("Replace from Archive export produced no staged package root.")
    for root in roots:
        resolved = Path(root).resolve()
        manifest_path = next(
            (
                candidate
                for candidate in (
                    resolved / "manifest.json",
                    resolved / "mod.json",
                    resolved / "mod.field.json",
                    resolved / "modinfo.json",
                )
                if candidate.is_file()
            ),
            None,
        )
        if manifest_path is None:
            raise ValueError(f"Staged package manifest is missing beneath: {resolved}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Staged package manifest is unreadable: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValueError("Staged package manifest does not contain an object.")  # noqa: TRY004
        if (
            manifest_path.name == "manifest.json"
            and manifest.get("kind") != "archive_loose_mod"
        ):
            raise ValueError(
                "Staged package manifest does not describe an archive loose mod."
            )
        files_root = (
            str(manifest.get("files_root") or manifest.get("files_dir") or "")
            .replace("\\", "/")
            .strip("/")
        )
        missing = sorted(
            expected
            for expected in expected_paths
            if not any(
                candidate.is_file()
                for candidate in (
                    resolved.joinpath(*PurePosixPath(expected).parts),
                    resolved.joinpath(*PurePosixPath(files_root, expected).parts)
                    if files_root
                    else resolved.joinpath(*PurePosixPath(expected).parts),
                )
            )
        )
        if missing:
            raise ValueError(
                "Staged package is missing planned payloads: " + ", ".join(missing[:4])
            )


def _package_info_with_plan(
    package_info: ModPackageInfo, plan: ReplaceFromArchivePlan
) -> ModPackageInfo:
    summary = [
        "Replace from Archive:",
        f"- Target: {plan.request.target_entry.path}",
        f"- Source: {plan.request.source_entry.path}",
        f"- Payloads: {len(plan.copied_actions):,}",
        f"- Reused source textures: {sum(action.kind is ReplaceFromArchiveActionKind.REUSE for action in plan.actions):,}",
    ]
    reused_paths = [
        action.source_path
        for action in plan.actions
        if action.kind is ReplaceFromArchiveActionKind.REUSE
    ]
    summary.extend(f"- Reused texture: {path}" for path in reused_paths[:16])
    summary.extend(f"- Warning: {warning}" for warning in plan.warnings[:12])
    description = str(package_info.description or "").strip()
    return dataclasses.replace(
        package_info,
        description=(description + "\n\n" if description else "") + "\n".join(summary),
    )


def _related(
    entry: ArchiveEntry, by_basename: Mapping[str, Sequence[ArchiveEntry]]
) -> tuple[ArchiveEntry, ...]:
    return tuple(find_archive_model_related_entries(entry, dict(by_basename)))


def _sidecars(
    entry: ArchiveEntry, by_basename: Mapping[str, Sequence[ArchiveEntry]]
) -> tuple[ArchiveEntry, ...]:
    return tuple(find_archive_model_sidecar_entries(entry, dict(by_basename)))


def _preferred_sidecar(
    model: ArchiveEntry, sidecars: Sequence[ArchiveEntry]
) -> ArchiveEntry | None:
    preferred = {".pac": ".pac_xml", ".pam": ".pami", ".pamlod": ".pamlod_xml"}.get(
        _extension(model), ""
    )
    for entry in sidecars:
        if _extension(entry) == preferred:
            return entry
    return next(
        (entry for entry in sidecars if _extension(entry) in _SIDECAR_EXTENSIONS), None
    )


def _best_appearance(
    model: ArchiveEntry,
    related: Sequence[ArchiveEntry],
    entries: Sequence[ArchiveEntry],
) -> ArchiveEntry | None:
    candidates = [entry for entry in related if _extension(entry) == ".app_xml"]
    if not candidates:
        candidates = [entry for entry in entries if _extension(entry) == ".app_xml"]
    tokens = {
        token
        for token in PurePosixPath(model.path.casefold())
        .stem.replace("-", "_")
        .split("_")
        if len(token) > 2
    }
    return max(
        candidates,
        key=lambda entry: (
            len(tokens & set(PurePosixPath(entry.path.casefold()).stem.split("_"))),
            -len(entry.path),
        ),
        default=None,
    )


def _first_extension(
    entries: Sequence[ArchiveEntry], extensions: set[str]
) -> ArchiveEntry | None:
    return next((entry for entry in entries if _extension(entry) in extensions), None)


def _first_basename(
    entries: Sequence[ArchiveEntry], basename: str
) -> ArchiveEntry | None:
    wanted = basename.casefold()
    return next(
        (entry for entry in entries if entry.basename.casefold() == wanted), None
    )


def _entry_for_path(entries: Sequence[ArchiveEntry], path: str) -> ArchiveEntry | None:
    wanted = _normalized(path)
    return next((entry for entry in entries if _normalized(entry.path) == wanted), None)


def _read(entry: ArchiveEntry, stop_event: threading.Event | None) -> bytes:
    raise_if_cancelled(stop_event, "Replace from Archive cancelled.")
    data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
    raise_if_cancelled(stop_event, "Replace from Archive cancelled.")
    return bytes(data)


def _extension(entry: ArchiveEntry) -> str:
    return str(getattr(entry, "extension", "") or "").strip().casefold()


def _normalized(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


def _same_entry(left: ArchiveEntry, right: ArchiveEntry) -> bool:
    return left.identity == right.identity


def _is_character(entry: ArchiveEntry) -> bool:
    path = f"/{_normalized(entry.path).strip('/')}"
    return any(marker in path for marker in _CHARACTER_MARKERS) and not _is_weapon(
        entry
    )


def _is_weapon(entry: ArchiveEntry) -> bool:
    path = f"/{_normalized(entry.path).strip('/')}"
    return any(marker in path for marker in _WEAPON_MARKERS)


def _asset_family(entry: ArchiveEntry) -> str:
    if _is_weapon(entry):
        return "weapon"
    if _is_character(entry):
        return "character"
    path = f"/{_normalized(entry.path).strip('/')}"
    if any(
        marker in path
        for marker in ("/world/", "/object/", "/leveldata/", "/environment/")
    ):
        return "world"
    return "unknown"


__all__ = [
    "archive_entries_are_character_pair",
    "build_replace_from_archive_plan",
    "export_replace_from_archive_plan",
]
