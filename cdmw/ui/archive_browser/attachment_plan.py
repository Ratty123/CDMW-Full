"""Archive browser attachment placement package planning."""

from __future__ import annotations

import dataclasses
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from cdmw.domain.mesh.session import PlacementWorkspacePreparation
from cdmw.core.archive import (
    build_archive_asset_family_graph,
    build_archive_item_icon_references_from_catalog,
    build_archive_relationship_references,
    merge_archive_reference_rows,
)
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    AssetFamilyGraph,
    ModPackageInfo,
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
        if self._background_task_active():
            self.set_status_message(
                "Another background task is still running. Wait for it to finish before preparing placement.",
                error=True,
            )
            return False

        path_index_snapshot = self.archive_entries_by_normalized_path
        basename_index_snapshot = self.archive_entries_by_basename
        item_catalog_snapshot = tuple(getattr(self, "archive_item_asset_catalog", ()) or ())
        build_graph = self._build_archive_asset_family_graph_from_snapshots
        donor_snapshot = donor_entry

        def _task(log: Callable[[str], None]) -> PlacementWorkspacePreparation:
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
            return PlacementWorkspacePreparation(
                target_entry=target_entry,
                donor_entry=donor_snapshot,
                target_graph=target_graph,
                target_references=target_references,
                donor_graph=donor_graph,
                donor_references=donor_references,
            )

        def _complete(result: object) -> None:
            if not isinstance(result, PlacementWorkspacePreparation):
                self.set_status_message("Placement preparation finished with an unexpected result payload.", error=True)
                return
            if isinstance(result.target_graph, AssetFamilyGraph):
                self._remember_archive_asset_family_graph(result.target_entry, result.target_graph, result.target_references)
            if isinstance(result.donor_entry, ArchiveEntry) and isinstance(result.donor_graph, AssetFamilyGraph):
                self._remember_archive_asset_family_graph(result.donor_entry, result.donor_graph, result.donor_references)
            on_prepared(result)

        def _error(message: str) -> None:
            if on_error is not None:
                on_error(message)

        self._run_utility_task(
            status_message=status_message,
            task=_task,
            on_complete=_complete,
            on_error=_error,
            show_archive_progress=True,
        )
        return True

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
