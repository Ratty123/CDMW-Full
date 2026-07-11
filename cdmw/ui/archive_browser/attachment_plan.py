"""Archive browser attachment placement package planning."""

from __future__ import annotations

import dataclasses
from types import MappingProxyType
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from cdmw.domain.mesh.session import PlacementWorkspacePreparation
from cdmw.services.archive_query_service import (
    build_archive_asset_family_graph,
    build_archive_item_icon_references_from_catalog,
    build_archive_relationship_references,
    merge_archive_reference_rows,
)
from cdmw.models import (
    ArchiveEntry,
    ArchiveEntryIdentity,
    ArchiveModelTextureReference,
    AssetFamilyGraph,
    ModPackageInfo,
)
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.workers.attachment_io_workers import (
    ATTACHMENT_PAYLOAD_MAX_BYTES,
    AttachmentPayloadReadRequest,
    run_attachment_payload_read,
)
from cdmw.workers.attachment_loose_workers import (
    AttachmentLoosePreflightRequest,
    prepare_attachment_loose_targets,
)


class ArchiveAttachmentPlanMixin:

    def _open_archive_attachment_placement_workspace_dialog(
        self,
        entry: Optional[ArchiveEntry] = None,
    ) -> None:
        source_entry = entry if isinstance(entry, ArchiveEntry) else self._current_archive_entry()
        if not isinstance(source_entry, ArchiveEntry):
            self.set_status_message("Select a model, prefab, HKX, or socket XML file first.", error=True)
            return
        self._run_archive_attachment_placement_prepare(
            source_entry,
            None,
            status_message=f"Preparing target-owned placement builder for {source_entry.basename}...",
            on_prepared=lambda preparation: self._open_archive_attachment_placement_diff_dialog(
                source_entry,
                None,
                preparation=preparation,
            ),
        )

    @staticmethod
    def _build_archive_asset_family_graph_from_snapshots(
        entry: ArchiveEntry,
        *,
        archive_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]],
        archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
        archive_item_asset_catalog: Sequence[object],
    ) -> Tuple[AssetFamilyGraph, Tuple[ArchiveModelTextureReference, ...]]:
        references = build_archive_relationship_references(
            entry,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
        )
        combined_references = list(references)
        item_icon_references = build_archive_item_icon_references_from_catalog(
            entry,
            tuple(archive_item_asset_catalog or ()),
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
            related_references=tuple(combined_references),
        )
        if item_icon_references:
            combined_references = list(merge_archive_reference_rows(combined_references, item_icon_references))
        graph = build_archive_asset_family_graph(entry, tuple(combined_references))
        return graph, tuple(combined_references)

    def _run_archive_attachment_placement_prepare(
        self,
        target_entry: ArchiveEntry,
        donor_entry: Optional[ArchiveEntry],
        *,
        status_message: str,
        on_prepared: Callable[[PlacementWorkspacePreparation], None],
        on_error: Optional[Callable[[str], None]] = None,
    ) -> bool:
        if not isinstance(target_entry, ArchiveEntry):
            self.set_status_message("Select a model, prefab, HKX, or socket XML file first.", error=True)
            return False
        if donor_entry is not None and not isinstance(donor_entry, ArchiveEntry):
            donor_entry = None
        request_id = int(getattr(self, "_attachment_placement_prepare_request_id", 0) or 0) + 1
        self._attachment_placement_prepare_request_id = request_id
        active_attachment_worker = getattr(self, "_attachment_placement_prepare_worker", None)
        queue_latest = bool(
            self._background_task_active()
            and active_attachment_worker is not None
            and active_attachment_worker is getattr(self, "utility_worker", None)
        )
        if self._background_task_active() and not queue_latest:
            self.set_status_message(
                "Another background task is still running. Wait for it to finish before preparing placement.",
                error=True,
            )
            return False
        if queue_latest:
            stop = getattr(active_attachment_worker, "stop", None)
            if callable(stop):
                stop()

        path_index_snapshot = self.archive_entries_by_normalized_path
        basename_index_snapshot = self.archive_entries_by_basename
        item_catalog_snapshot = tuple(getattr(self, "archive_item_asset_catalog", ()) or ())
        output_root_widget = getattr(self, "output_root_edit", None)
        output_root_text = output_root_widget.text().strip() if output_root_widget is not None else ""
        raw_extract_widget = getattr(self, "archive_extract_root_edit", None)
        raw_extract_root_text = raw_extract_widget.text().strip() if raw_extract_widget is not None else ""
        current_preview = getattr(self, "current_archive_preview_result", None)
        preview_loose_file_path = str(getattr(current_preview, "loose_file_path", "") or "").strip()
        build_graph = self._build_archive_asset_family_graph_from_snapshots
        donor_snapshot = donor_entry

        def _task(log: Callable[[str], None], stop_event: object) -> PlacementWorkspacePreparation:
            log(f"Resolving target placement family: {target_entry.path}")
            target_graph, target_references = build_graph(
                target_entry,
                archive_entries_by_normalized_path=path_index_snapshot,
                archive_entries_by_basename=basename_index_snapshot,
                archive_item_asset_catalog=item_catalog_snapshot,
            )
            donor_graph: Optional[AssetFamilyGraph] = None
            donor_references: Tuple[ArchiveModelTextureReference, ...] = ()
            if isinstance(donor_snapshot, ArchiveEntry):
                log(f"Resolving source placement family: {donor_snapshot.path}")
                donor_graph, donor_references = build_graph(
                    donor_snapshot,
                    archive_entries_by_normalized_path=path_index_snapshot,
                    archive_entries_by_basename=basename_index_snapshot,
                    archive_item_asset_catalog=item_catalog_snapshot,
                )
            target_subclass_tokens = tuple(
                sorted(
                    self._attachment_package_weapon_subclass_tokens(
                        target_entry,
                        target_graph,
                        allow_archive_reads=True,
                        stop_event=stop_event,
                    )
                )
            )
            donor_subclass_tokens = (
                tuple(
                    sorted(
                        self._attachment_package_weapon_subclass_tokens(
                            donor_snapshot,
                            donor_graph,
                            allow_archive_reads=True,
                            stop_event=stop_event,
                        )
                    )
                )
                if isinstance(donor_snapshot, ArchiveEntry) and isinstance(donor_graph, AssetFamilyGraph)
                else ()
            )
            target_socket_entry = self._attachment_socket_entry_from_selection(target_graph)
            target_socket_document = (
                self._attachment_visual_socket_document_from_path(
                    target_socket_entry.path,
                    preferred_entry=target_socket_entry,
                    stop_event=stop_event,
                )
                if isinstance(target_socket_entry, ArchiveEntry)
                else None
            )
            donor_socket_entry = (
                self._attachment_socket_entry_from_selection(donor_graph)
                if isinstance(donor_graph, AssetFamilyGraph)
                else None
            )
            donor_socket_document = (
                self._attachment_visual_socket_document_from_path(
                    donor_socket_entry.path,
                    preferred_entry=donor_socket_entry,
                    stop_event=stop_event,
                )
                if isinstance(donor_socket_entry, ArchiveEntry)
                else None
            )
            character_socket_entry = next(
                (
                    candidate
                    for basename in ("phm_01.pab.sockets.xml", "identityskeleton.pab.sockets.xml")
                    for candidate in tuple(basename_index_snapshot.get(basename, ()) or ())
                    if isinstance(candidate, ArchiveEntry)
                ),
                None,
            )
            character_socket_document = (
                self._attachment_visual_socket_document_from_path(
                    character_socket_entry.path,
                    preferred_entry=character_socket_entry,
                    stop_event=stop_event,
                )
                if isinstance(character_socket_entry, ArchiveEntry)
                else None
            )
            payload_entries: List[ArchiveEntry] = []
            seen_payloads: set[ArchiveEntryIdentity] = set()

            def add_payload_entry(candidate: object) -> None:
                if not isinstance(candidate, ArchiveEntry):
                    return
                if str(candidate.extension or "").casefold() not in {
                    ".xml",
                    ".prefab",
                    ".pac_xml",
                    ".pam_xml",
                    ".pamlod_xml",
                }:
                    return
                if candidate.identity in seen_payloads:
                    return
                seen_payloads.add(candidate.identity)
                payload_entries.append(candidate)

            for candidate in self._attachment_package_graph_entries(target_entry, target_graph):
                add_payload_entry(candidate)
            if isinstance(donor_snapshot, ArchiveEntry) and isinstance(donor_graph, AssetFamilyGraph):
                for candidate in self._attachment_package_graph_entries(donor_snapshot, donor_graph):
                    add_payload_entry(candidate)
            for basename in (
                "phm_description_player_kliff.xml",
                "phm_01.pab.sockets.xml",
                "identityskeleton.pab.sockets.xml",
            ):
                for candidate in tuple(basename_index_snapshot.get(basename, ()) or ()):
                    add_payload_entry(candidate)

            archive_payloads: List[Tuple[ArchiveEntryIdentity, bytes]] = []
            remaining_payload_bytes = 128 * 1024 * 1024
            for candidate in payload_entries:
                raise_if_cancelled(stop_event, "Attachment placement preparation cancelled.")
                if remaining_payload_bytes <= 0:
                    break
                try:
                    payload = run_attachment_payload_read(
                        AttachmentPayloadReadRequest(
                            archive_entry=candidate,
                            max_bytes=min(ATTACHMENT_PAYLOAD_MAX_BYTES, remaining_payload_bytes),
                        ),
                        stop_event=stop_event,
                    ).data
                except Exception:
                    raise_if_cancelled(stop_event, "Attachment placement preparation cancelled.")
                    continue
                archive_payloads.append((candidate.identity, payload))
                remaining_payload_bytes -= len(payload)
            raise_if_cancelled(stop_event, "Attachment placement preparation cancelled.")
            target_model = self._attachment_visual_model_entry(target_entry, target_graph)
            material_sidecar = self._attachment_package_material_sidecar_for_model(
                target_entry,
                target_graph,
                target_model,
            )
            icon_entries = tuple(self._attachment_package_item_icon_entries(target_entry, target_graph))
            support_entries = tuple(self._attachment_package_target_support_entries(target_entry, target_graph))
            loose_result = prepare_attachment_loose_targets(
                AttachmentLoosePreflightRequest(
                    request_id=request_id,
                    target_entry=target_entry,
                    output_root_paths=(output_root_text,) if output_root_text else (),
                    raw_extract_root_path=raw_extract_root_text,
                    preview_loose_file_path=preview_loose_file_path,
                    material_sidecar_paths=(material_sidecar.path,) if isinstance(material_sidecar, ArchiveEntry) else (),
                    item_icon_paths=tuple(entry.path for entry in icon_entries),
                    support_paths=tuple((action, entry.path) for action, entry, _note in support_entries),
                    archive_entries_by_normalized_path=(
                        MappingProxyType(path_index_snapshot)
                        if isinstance(path_index_snapshot, dict)
                        else path_index_snapshot
                    ),
                ),
                stop_event=stop_event,
            )
            return PlacementWorkspacePreparation(
                request_id=request_id,
                target_entry=target_entry,
                donor_entry=donor_snapshot,
                target_graph=target_graph,
                target_references=target_references,
                donor_graph=donor_graph,
                donor_references=donor_references,
                target_subclass_tokens=target_subclass_tokens,
                donor_subclass_tokens=donor_subclass_tokens,
                target_socket_document=target_socket_document,
                donor_socket_document=donor_socket_document,
                character_socket_document=character_socket_document,
                archive_payloads=tuple(archive_payloads),
                target_loose_roots=loose_result.roots,
            )

        def _complete(result: object) -> None:
            if not isinstance(result, PlacementWorkspacePreparation):
                self.set_status_message("Placement preparation finished with an unexpected result payload.", error=True)
                return
            if result.request_id != int(getattr(self, "_attachment_placement_prepare_request_id", 0) or 0):
                return
            if isinstance(result.target_graph, AssetFamilyGraph):
                self._remember_archive_asset_family_graph(result.target_entry, result.target_graph, result.target_references)
            if isinstance(result.donor_entry, ArchiveEntry) and isinstance(result.donor_graph, AssetFamilyGraph):
                self._remember_archive_asset_family_graph(result.donor_entry, result.donor_graph, result.donor_references)
            token_cache = getattr(self, "_attachment_weapon_subclass_token_cache", None)
            if not isinstance(token_cache, dict):
                token_cache = {}
                self._attachment_weapon_subclass_token_cache = token_cache
            token_cache[self._attachment_package_entry_key(result.target_entry)] = tuple(result.target_subclass_tokens)
            if isinstance(result.donor_entry, ArchiveEntry):
                token_cache[self._attachment_package_entry_key(result.donor_entry)] = tuple(result.donor_subclass_tokens)
            on_prepared(result)

        def _error(message: str) -> None:
            if request_id != int(getattr(self, "_attachment_placement_prepare_request_id", 0) or 0):
                return
            if on_error is not None:
                on_error(message)

        def _start() -> None:
            if (
                request_id != int(getattr(self, "_attachment_placement_prepare_request_id", 0) or 0)
                or bool(getattr(self, "_shutting_down", False))
            ):
                return
            self._run_utility_task(
                status_message=status_message,
                task=_task,
                on_complete=_complete,
                on_error=_error,
                show_archive_progress=True,
                task_accepts_cancel=True,
            )
            self._attachment_placement_prepare_worker = getattr(self, "utility_worker", None)

        if queue_latest:
            self._run_when_background_idle(_start, label="loading the latest placement selection")
        else:
            _start()
        return True

    def _cancel_archive_attachment_placement_prepare(self) -> None:
        worker = getattr(self, "_attachment_placement_prepare_worker", None)
        if worker is None or worker is not getattr(self, "utility_worker", None):
            return
        self._attachment_placement_prepare_request_id = int(
            getattr(self, "_attachment_placement_prepare_request_id", 0) or 0
        ) + 1
        stop = getattr(worker, "stop", None)
        if callable(stop):
            stop()

    @staticmethod
    def _placement_swap_package_info_with_diagnostics(
        package_info: ModPackageInfo,
        diagnostics: Sequence[str],
    ) -> ModPackageInfo:
        clean_lines = [str(line or "").strip() for line in diagnostics if str(line or "").strip()]
        if not clean_lines:
            return package_info
        base_description = str(package_info.description or "").strip()
        diagnostic_text = "Placement diagnostics:\n" + "\n".join(f"- {line}" for line in clean_lines[:24])
        description = f"{base_description}\n\n{diagnostic_text}" if base_description else diagnostic_text
        return dataclasses.replace(package_info, description=description)

    def _build_attachment_donor_package_plan(
        self,
        target_entry: ArchiveEntry,
        donor_entry: ArchiveEntry,
        target_graph: AssetFamilyGraph,
        donor_graph: AssetFamilyGraph,
        *,
        legacy_raw_prefab_copy: bool = False,
        copy_source_icon: bool = False,
        experimental_copy_source_model: bool = False,
        experimental_copy_source_hkx: bool = False,
    ) -> Tuple[List[dict], List[str]]:
        plan_rows: List[dict] = []
        warnings: List[str] = []
        seen_targets: set[str] = set()

        def add_row(action: str, donor: ArchiveEntry, target: ArchiveEntry, note: str) -> None:
            target_key = target.path.replace("\\", "/").strip().casefold()
            donor_key = donor.path.replace("\\", "/").strip().casefold()
            row_key = f"{target_key}|{donor_key}|{action.casefold()}"
            if row_key in seen_targets:
                return
            if target_key in seen_targets and not self._same_archive_entry(donor, target):
                warnings.append(f"Skipped duplicate target path: {target.path}")
                return
            seen_targets.add(row_key if self._same_archive_entry(donor, target) else target_key)
            plan_rows.append(
                {
                    "action": action,
                    "donor_entry": donor,
                    "target_entry": target,
                    "note": note,
                }
            )

        target_prefab = self._choose_attachment_package_target_entry(
            donor_entry,
            target_entry,
            target_graph,
            {".prefab"},
        )
        donor_prefab = self._choose_attachment_package_donor_prefab(donor_entry, donor_graph, target_prefab)
        compatibility = self._attachment_package_placement_compatibility(
            target_entry,
            donor_entry,
            target_graph,
            donor_graph,
        )
        compatibility_status = str(compatibility.get("status") or "Unknown")
        target_weapon_tokens = set(compatibility.get("target_handedness") or ())
        donor_weapon_tokens = set(compatibility.get("donor_handedness") or ())
        target_subclass_tokens = set(compatibility.get("target_subclasses") or ())
        donor_subclass_tokens = set(compatibility.get("donor_subclasses") or ())
        cross_handedness = bool(compatibility.get("cross_handedness"))
        cross_category_risky = bool(compatibility.get("risky"))
        preserve_target_context = bool(cross_handedness or cross_category_risky)
        warnings.append(
            "Placement compatibility: "
            f"{compatibility_status} (target {compatibility.get('target_label')}; source {compatibility.get('donor_label')})."
        )
        if not legacy_raw_prefab_copy:
            warnings.append(
                "Target-only placement mode: source weapon supplies placement/profile values only; source model, material, textures, prefab bytes, icon, motion, and HKX are not copied."
            )
            if copy_source_icon:
                source_icon_rows, source_icon_warnings = self._attachment_package_source_icon_override_rows(
                    target_entry,
                    donor_entry,
                    target_graph,
                    donor_graph,
                )
                warnings.extend(source_icon_warnings)
                for source_icon, target_icon, note in source_icon_rows:
                    add_row("Copy source item icon bytes (explicit)", source_icon, target_icon, note)
            return plan_rows, warnings
        if cross_category_risky:
            warnings.append(
                "Cross weapon-class placement source detected. Cross-category risky: the placement source appears to be a different weapon subclass. "
                "Default placement-only mode should be used; legacy raw prefab copy may reference incompatible source files."
            )
        elif compatibility_status == "Unknown":
            warnings.append(
                "Unknown placement compatibility: review the package plan before building, especially for non-sword weapon families."
            )
        if isinstance(donor_prefab, ArchiveEntry) and isinstance(target_prefab, ArchiveEntry):
            target_prefab_entries = self._attachment_package_target_prefab_entries_for_donor(
                target_entry,
                target_graph,
                donor_prefab,
                target_prefab,
            )
            for target_prefab_entry in target_prefab_entries:
                side_suffix = self._attachment_package_side_suffix(target_prefab_entry.path)
                side_note = (
                    f" Covers target side-specific prefab {side_suffix}."
                    if side_suffix in {"_l", "_r"}
                    else ""
                )
                add_row(
                    "Copy source prefab bytes",
                    donor_prefab,
                    target_prefab_entry,
                    "Overrides the target prefab with placement-source fields under the target virtual path; review internal source model/socket references."
                    + side_note,
                )
            if len(target_prefab_entries) > 1:
                warnings.append(
                    "Target uses side-specific prefab variants; source prefab will be written to each resolved target side path so the active in-game side is covered."
                )
            for socket_entry in self._attachment_package_socket_entries_for_prefab(donor_graph, donor_prefab):
                add_row(
                    "Include source socket XML dependency",
                    socket_entry,
                    socket_entry,
                    "Kept at the source virtual path because the copied source prefab refers to this socket descriptor.",
                )
        elif donor_prefab is not None:
            warnings.append("Source prefab was found, but no resolved target prefab path was available to override.")
        else:
            warnings.append("No source prefab was resolved for this asset family.")

        source_icon_target_keys: set[str] = set()
        source_icon_rows, source_icon_warnings = self._attachment_package_source_icon_override_rows(
            target_entry,
            donor_entry,
            target_graph,
            donor_graph,
        )
        warnings.extend(source_icon_warnings)
        if copy_source_icon:
            for source_icon, target_icon, note in source_icon_rows:
                add_row("Copy source item icon bytes (explicit)", source_icon, target_icon, note)
                source_icon_target_keys.add(target_icon.path.replace("\\", "/").strip().casefold())

        experimental_target_keys: set[str] = set()
        if experimental_copy_source_model:
            source_model = self._attachment_visual_model_entry(donor_entry, donor_graph)
            target_model = self._attachment_visual_model_entry(target_entry, target_graph)
            if isinstance(source_model, ArchiveEntry) and isinstance(target_model, ArchiveEntry):
                add_row(
                    "Copy source PAC/model bytes (experimental)",
                    source_model,
                    target_model,
                    "Experimental full swap: writes the visible placement-source model bytes onto the target model path.",
                )
                experimental_target_keys.add(target_model.path.replace("\\", "/").strip().casefold())
            else:
                warnings.append("Experimental visible-model mode could not resolve both source and target PAC/model paths.")

            source_material = self._attachment_package_material_sidecar_for_model(donor_entry, donor_graph, source_model)
            target_material = self._attachment_package_material_sidecar_for_model(target_entry, target_graph, target_model)
            if isinstance(source_material, ArchiveEntry) and isinstance(target_material, ArchiveEntry):
                add_row(
                    "Copy source material sidecar bytes (experimental)",
                    source_material,
                    target_material,
                    "Experimental full swap: writes the source .pac_xml/material sidecar onto the target material path so source texture bindings can follow.",
                )
                experimental_target_keys.add(target_material.path.replace("\\", "/").strip().casefold())
            elif isinstance(source_model, ArchiveEntry) or isinstance(target_model, ArchiveEntry):
                warnings.append("Experimental visible-model mode could not resolve both source and target material sidecar paths.")

            if not experimental_copy_source_hkx:
                warnings.append(
                    "Experimental visible-model mode keeps target HKX/physics by default. Enable source HKX/physics only when you intentionally want to replace the target physics contract."
                )

        for action, support_entry, note in self._attachment_package_target_support_entries(target_entry, target_graph):
            if action == "Preserve target item icon bytes" and support_entry.path.replace("\\", "/").strip().casefold() in source_icon_target_keys:
                continue
            if support_entry.path.replace("\\", "/").strip().casefold() in experimental_target_keys:
                continue
            add_row(action, support_entry, support_entry, note)

        if preserve_target_context:
            target_text = ", ".join(sorted(target_weapon_tokens | target_subclass_tokens)) or "unknown"
            donor_text = ", ".join(sorted(donor_weapon_tokens | donor_subclass_tokens)) or "unknown"
            if cross_category_risky:
                warnings.append(
                    "Placement copied with target context preserved "
                    f"({donor_text} source -> {target_text} target). "
                    "Legacy raw prefab mode is enabled; source icon and raw source HKX/HKT are still copied only when explicitly enabled."
                )
            else:
                warnings.append(
                    "Known compatible handedness placement copy "
                    f"({donor_text} source -> {target_text} target): legacy raw prefab copy is enabled; target model/material/motion context is preserved where resolved."
                )

        for extension in (".hkx", ".hkt"):
            donor_hkx_entries = self._attachment_package_entries_with_extension(donor_entry, donor_graph, {extension})
            target_hkx_entries = self._attachment_package_entries_with_extension(target_entry, target_graph, {extension})
            if not experimental_copy_source_hkx:
                for target_hkx in target_hkx_entries[:1]:
                    add_row(
                        "Preserve target HKX/HKT physics bytes",
                        target_hkx,
                        target_hkx,
                        "Target physics is kept instead of copying source HKX into the target path.",
                    )
                if donor_hkx_entries:
                    if target_hkx_entries:
                        warnings.append(f"Skipped source {extension}: target-owned physics is preserved instead.")
                    else:
                        warnings.append(f"Skipped source {extension}: source HKX/physics is disabled unless the replacement-only source-HKX option is enabled.")
                continue
            for donor_hkx in donor_hkx_entries[:1]:
                target_hkx = self._choose_attachment_package_target_entry(
                    donor_hkx,
                    target_entry,
                    target_graph,
                    {extension},
                )
                if isinstance(target_hkx, ArchiveEntry):
                    action = (
                        "Replacement-only: copy source HKX/HKT physics bytes"
                        if experimental_copy_source_hkx
                        else "Copy source HKX/HKT physics bytes"
                    )
                    note = (
                        "Replacement-only path: source physics bytes are written to the target HKX/HKT path; not used by normal placement moves."
                        if experimental_copy_source_hkx
                        else "Uses the proven source-copy workflow; HKX table editing remains disabled."
                    )
                    add_row(
                        action,
                        donor_hkx,
                        target_hkx,
                        note,
                    )
                else:
                    warnings.append(f"Skipped {donor_hkx.basename}: no matching target {extension} path was resolved.")

        motion_extensions = {".paa", ".paa_metabin", ".motionblending"}
        target_motion_available = (
            target_entry.extension in motion_extensions
            or bool(self._attachment_package_entries_with_extension(target_entry, target_graph, motion_extensions))
        )
        donor_motion_entries = self._attachment_package_entries_with_extension(donor_entry, donor_graph, motion_extensions)
        if preserve_target_context:
            if donor_motion_entries:
                warnings.append("Skipped source PAA/motion copy across placement classes; target motion context is preserved when resolved.")
        elif target_motion_available or donor_entry.extension in motion_extensions:
            for donor_motion in donor_motion_entries:
                target_motion = self._choose_attachment_package_target_entry(
                    donor_motion,
                    target_entry,
                    target_graph,
                    {donor_motion.extension},
                )
                if isinstance(target_motion, ArchiveEntry):
                    add_row(
                        "Copy source PAA/motion bytes",
                        donor_motion,
                        target_motion,
                        "Animation/motion bytes are copied only when both source and target motion paths are resolved.",
                    )
                else:
                    warnings.append(f"Skipped {donor_motion.basename}: no matching target motion path was resolved.")
        elif donor_motion_entries:
            warnings.append("Source motion files were found, but this target asset did not expose a matching motion path.")

        if not plan_rows:
            warnings.append("No safe source-copy package rows could be built from the resolved family evidence.")
        return plan_rows, warnings
