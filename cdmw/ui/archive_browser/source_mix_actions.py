"""Archive source-mix package dialog and helper resolution."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.services.preview_workflow_service import try_decode_text_like_archive_data
from cdmw.domain.archives.mesh_contracts import (
    ArchiveLooseExportResult,
    MeshImportSupplementalFileSpec,
)
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.archive_workflow_service import export_archive_payloads_to_mod_ready_loose
from cdmw.services.texture_workflow_service import (
    SourceMixCandidate,
    SourceMixSelection,
    normalize_source_mix_virtual_path,
    paired_counterpart_virtual_path,
    source_mix_role_for_virtual_path,
    validate_source_mix_selections,
)
from cdmw.services.texture_workflow_service import (
    normalize_texture_reference_for_sidecar_lookup,
    parse_texture_sidecar_bindings,
)
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.source_mix_task_controller import (
    source_mix_task_controller_for_guard,
)
from cdmw.workers.source_mix_workers import (
    SourceMixIndexSnapshot,
    SourceMixScanRequest,
    SourceMixScanResult,
    resolve_source_mix_candidate_targets,
    run_source_mix_scan,
)


class ArchiveSourceMixActionsMixin:
    def _source_mix_target_entries_by_virtual_path(
        self,
        entries: Sequence[ArchiveEntry],
    ) -> Dict[str, ArchiveEntry]:
        targets: Dict[str, ArchiveEntry] = {}
        for target_entry in entries:
            if not isinstance(target_entry, ArchiveEntry):
                continue
            normalized = normalize_source_mix_virtual_path(target_entry.path)
            if normalized and normalized not in targets:
                targets[normalized] = target_entry
        return targets

    def _source_mix_candidate_target_from_indexes(
        self,
        candidate: SourceMixCandidate,
    ) -> Tuple[Optional[ArchiveEntry], str, str]:
        normalized = candidate.normalized_virtual_path
        if normalized:
            for target_entry in tuple(self.archive_entries_by_normalized_path.get(normalized, ()) or ()):
                if isinstance(target_entry, ArchiveEntry):
                    return target_entry, "exact", "Exact virtual path"

        candidate_name = PurePosixPath(str(candidate.display_path or "").replace("\\", "/")).name.lower()
        if not candidate_name:
            return None, "extra", "Extra source file"
        basename_entries = tuple(self.archive_entries_by_basename.get(candidate_name, ()) or ())
        if normalized:
            for target_entry in basename_entries:
                if (
                    isinstance(target_entry, ArchiveEntry)
                    and normalize_source_mix_virtual_path(target_entry.path) == normalized
                ):
                    return target_entry, "exact", "Exact virtual path"
        candidate_extension = str(candidate.extension or PurePosixPath(candidate_name).suffix or "").lower()
        basename_matches: List[ArchiveEntry] = []
        for target_entry in basename_entries:
            if not isinstance(target_entry, ArchiveEntry):
                continue
            target_extension = str(getattr(target_entry, "extension", "") or "").lower()
            if candidate_extension and target_extension != candidate_extension:
                continue
            basename_matches.append(target_entry)
            if len(basename_matches) > 1:
                break
        if len(basename_matches) == 1:
            return (
                basename_matches[0],
                "basename",
                "Matched archive target by filename; common for compact or CrimsonForge-style loose packages.",
            )
        if len(basename_matches) > 1:
            return (
                None,
                "extra",
                "Extra source file; filename matched multiple archive targets, so no target was chosen automatically.",
            )
        return None, "extra", "Extra source file"

    def _resolve_source_mix_candidate_targets(
        self,
        candidates: Sequence[SourceMixCandidate],
    ) -> Tuple[SourceMixCandidate, ...]:
        return resolve_source_mix_candidate_targets(
            candidates,
            SourceMixIndexSnapshot.capture(
                self.archive_entries_by_normalized_path,
                self.archive_entries_by_basename,
            ),
        )

    def _source_mix_counterpart_entry(self, entry: ArchiveEntry) -> Optional[ArchiveEntry]:
        counterpart = paired_counterpart_virtual_path(entry.path)
        if not counterpart:
            return None
        for candidate in tuple(self.archive_entries_by_normalized_path.get(counterpart, ()) or ()):
            if isinstance(candidate, ArchiveEntry):
                return candidate
        raw_counterpart_path = PurePosixPath(entry.path.replace("\\", "/")).with_suffix(PurePosixPath(counterpart).suffix).as_posix()
        for candidate in tuple(self.archive_entries_by_normalized_path.get(raw_counterpart_path.lower(), ()) or ()):
            if isinstance(candidate, ArchiveEntry):
                return candidate
        for candidate in tuple(getattr(self, "archive_entries", ()) or ()):
            if isinstance(candidate, ArchiveEntry) and normalize_source_mix_virtual_path(candidate.path) == counterpart:
                return candidate
        return None

    def _source_mix_default_target_entries(self, entry: ArchiveEntry) -> Tuple[ArchiveEntry, ...]:
        targets: List[ArchiveEntry] = [entry]
        counterpart_entry = self._source_mix_counterpart_entry(entry)
        if counterpart_entry is not None and not self._same_archive_entry(counterpart_entry, entry):
            targets.append(counterpart_entry)
        return tuple(targets)

    def _source_mix_lookup_keys_for_texture_path(self, path_value: str) -> Tuple[str, ...]:
        normalized = normalize_texture_reference_for_sidecar_lookup(path_value)
        if not normalized:
            return ()
        keys: List[str] = []

        def _add(value: str) -> None:
            key = normalize_source_mix_virtual_path(value)
            if key and key not in keys:
                keys.append(key)

        _add(normalized)
        if "/texture/" in normalized:
            _add(normalized.replace("/texture/", "/textures/"))
        if "/textures/" in normalized:
            _add(normalized.replace("/textures/", "/texture/"))
        basename = PurePosixPath(normalized).name
        if basename:
            _add(basename)
        return tuple(keys)

    def _source_mix_sidecar_referenced_payload_specs(
        self,
        selected_candidates: Sequence[SourceMixCandidate],
        all_candidates: Sequence[SourceMixCandidate],
    ) -> Tuple[MeshImportSupplementalFileSpec, ...]:
        selected_source_keys = {
            (
                candidate.layer.source_id,
                candidate.display_path.lower(),
                str(candidate.source_path or ""),
                int(candidate.size or 0),
            )
            for candidate in selected_candidates
            if isinstance(candidate, SourceMixCandidate)
        }
        candidates_by_lookup_key: Dict[str, SourceMixCandidate] = {}
        candidates_by_basename: Dict[str, List[SourceMixCandidate]] = defaultdict(list)
        for candidate in all_candidates:
            if not isinstance(candidate, SourceMixCandidate):
                continue
            if (candidate.role or source_mix_role_for_virtual_path(candidate.display_path)) != "Texture":
                continue
            for key in self._source_mix_lookup_keys_for_texture_path(candidate.display_path):
                candidates_by_lookup_key.setdefault(key, candidate)
            basename = PurePosixPath(candidate.display_path.replace("\\", "/")).name.lower()
            if basename:
                candidates_by_basename[basename].append(candidate)

        specs: List[MeshImportSupplementalFileSpec] = []
        seen_targets: set[str] = set()
        for sidecar_candidate in selected_candidates:
            if not isinstance(sidecar_candidate, SourceMixCandidate):
                continue
            if (sidecar_candidate.role or source_mix_role_for_virtual_path(sidecar_candidate.display_path)) != "Material":
                continue
            try:
                payload = sidecar_candidate.read_payload()
            except Exception:
                continue
            sidecar_text = try_decode_text_like_archive_data(payload) or payload.decode("utf-8", errors="replace")
            try:
                bindings = parse_texture_sidecar_bindings(sidecar_text, sidecar_path=sidecar_candidate.display_path)
            except Exception:
                bindings = ()
            for binding in bindings:
                texture_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
                if not texture_path:
                    continue
                texture_candidate: Optional[SourceMixCandidate] = None
                for key in self._source_mix_lookup_keys_for_texture_path(texture_path):
                    texture_candidate = candidates_by_lookup_key.get(key)
                    if texture_candidate is not None:
                        break
                if texture_candidate is None:
                    basename = PurePosixPath(texture_path).name.lower()
                    basename_matches = candidates_by_basename.get(basename, ())
                    if len(basename_matches) == 1:
                        texture_candidate = basename_matches[0]
                if texture_candidate is None:
                    continue
                source_key = (
                    texture_candidate.layer.source_id,
                    texture_candidate.display_path.lower(),
                    str(texture_candidate.source_path or ""),
                    int(texture_candidate.size or 0),
                )
                if source_key in selected_source_keys:
                    continue
                target_path = (
                    texture_candidate.target_archive_entry.path
                    if isinstance(texture_candidate.target_archive_entry, ArchiveEntry)
                    else texture_candidate.display_path
                )
                normalized_target = normalize_source_mix_virtual_path(target_path)
                if not normalized_target or normalized_target in seen_targets:
                    continue
                seen_targets.add(normalized_target)
                payload_data = b""
                if not isinstance(texture_candidate.source_path, Path):
                    try:
                        payload_data = texture_candidate.read_payload()
                    except Exception:
                        payload_data = b""
                specs.append(
                    MeshImportSupplementalFileSpec(
                        source_path=texture_candidate.source_path
                        if isinstance(texture_candidate.source_path, Path)
                        else Path(PurePosixPath(texture_candidate.display_path).name),
                        target_path=target_path,
                        kind="texture",
                        target_entry=texture_candidate.target_archive_entry,
                        used_for_preview=False,
                        payload_data=payload_data,
                        note=f"Auto-included because selected sidecar {sidecar_candidate.display_path} references this texture.",
                    )
                )
        return tuple(specs)

    def _open_archive_source_mix_package_dialog(self, entry: ArchiveEntry) -> None:
        target_entries = self._source_mix_default_target_entries(entry)
        if not target_entries:
            self.set_status_message("No archive target files are available for source mixing.", error=True)
            return
        target_entries_by_virtual_path = self._source_mix_target_entries_by_virtual_path(target_entries)
        dialog = QDialog(self)
        dialog.setWindowTitle("Build Loose Package From Sources")
        dialog.setModal(True)
        dialog.resize(980, 520)
        source_task_controller = source_mix_task_controller_for_guard(self, dialog)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        intro = QLabel(
            "Add a loose mod folder or .pamt/.paz source, then choose replacement payloads by virtual path. "
            "No binary merge is performed; selected source bytes replace the matching archive target in a loose package."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        source_button_row = QHBoxLayout()
        add_loose_button = QPushButton("Add Loose Mod Folder")
        add_mod_archive_button = QPushButton("Add .pamt/.paz Mod")
        source_button_row.addWidget(add_loose_button)
        source_button_row.addWidget(add_mod_archive_button)
        source_button_row.addStretch(1)
        layout.addLayout(source_button_row)

        target_tree = QTreeWidget()
        target_tree.setColumnCount(5)
        target_tree.setHeaderLabels(["Target virtual path", "Current size", "Replacement source", "Package", "Status"])
        target_tree.setRootIsDecorated(False)
        target_tree.setAlternatingRowColors(True)
        target_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        target_tree.header().setStretchLastSection(True)
        target_tree.header().resizeSection(0, 360)
        target_tree.header().resizeSection(1, 96)
        target_tree.header().resizeSection(2, 300)
        target_tree.header().resizeSection(3, 120)
        layout.addWidget(target_tree, 1)

        status_label = QLabel("No replacement sources added.")
        status_label.setObjectName("HintLabel")
        status_label.setWordWrap(True)
        layout.addWidget(status_label)
        row_state_by_path: Dict[str, Dict[str, object]] = {}
        loaded_source_candidates: List[SourceMixCandidate] = []
        loaded_source_candidate_keys: set[Tuple[str, str, str, str, int]] = set()

        def _source_mix_candidate_identity(candidate: SourceMixCandidate) -> Tuple[str, str, str, str, int]:
            return (
                candidate.layer.source_id,
                candidate.display_path.lower(),
                str(candidate.source_path or ""),
                str(getattr(candidate.source_archive_entry, "pamt_path", "") or ""),
                int(getattr(candidate.source_archive_entry, "offset", -1) if candidate.source_archive_entry is not None else -1),
            )

        def _register_loaded_source_candidates(candidates: Sequence[SourceMixCandidate]) -> None:
            for candidate in candidates:
                if not isinstance(candidate, SourceMixCandidate):
                    continue
                candidate_key = _source_mix_candidate_identity(candidate)
                if candidate_key in loaded_source_candidate_keys:
                    continue
                loaded_source_candidate_keys.add(candidate_key)
                loaded_source_candidates.append(candidate)

        def _candidate_label(candidate: SourceMixCandidate) -> str:
            return f"{candidate.layer.label}: {candidate.display_path} ({candidate.size:,} bytes)"

        def _candidate_target_row_key(candidate: SourceMixCandidate) -> str:
            if isinstance(candidate.target_archive_entry, ArchiveEntry):
                return normalize_source_mix_virtual_path(candidate.target_archive_entry.path)
            return candidate.normalized_virtual_path

        def _refresh_source_mix_status() -> None:
            replacement_count = 0
            candidate_count = 0
            for state in row_state_by_path.values():
                combo = state.get("combo")
                if isinstance(combo, QComboBox):
                    candidate_count += max(0, combo.count() - 1)
                    if combo.currentIndex() > 0:
                        replacement_count += 1
            target_count = len(row_state_by_path)
            status_label.setText(
                f"{candidate_count:,} replacement candidate(s) loaded for {target_count:,} target file(s); "
                f"{replacement_count:,} replacement(s) selected."
            )

        def _add_candidate_to_row(candidate: SourceMixCandidate) -> None:
            normalized = _candidate_target_row_key(candidate)
            state = row_state_by_path.get(normalized)
            if not state:
                return
            combo = state.get("combo")
            item = state.get("item")
            if not isinstance(combo, QComboBox) or not isinstance(item, QTreeWidgetItem):
                return
            existing_keys = state.setdefault("candidate_keys", set())
            candidate_key = _source_mix_candidate_identity(candidate)
            if candidate_key in existing_keys:
                return
            existing_keys.add(candidate_key)
            combo.addItem(_candidate_label(candidate), candidate)
            item.setText(4, f"{combo.count() - 1:,} candidate(s)")
            item.setForeground(4, QBrush(QColor("#86efac")))
            _refresh_source_mix_status()

        def _add_candidates(candidates: Sequence[SourceMixCandidate]) -> None:
            _register_loaded_source_candidates(candidates)
            matched = 0
            for candidate in candidates:
                if _candidate_target_row_key(candidate) in row_state_by_path:
                    _add_candidate_to_row(candidate)
                    matched += 1
            _refresh_source_mix_status()
            if matched <= 0:
                QMessageBox.information(
                    dialog,
                    "No Matching Sources",
                    "The selected source did not contain payloads matching the target virtual path(s).",
                )

        def _set_source_scan_controls_enabled(enabled: bool) -> None:
            add_loose_button.setEnabled(enabled)
            add_mod_archive_button.setEnabled(enabled)

        def _start_source_scan(request: SourceMixScanRequest, *, title: str) -> None:
            def _completed(result: object) -> None:
                if not isinstance(result, SourceMixScanResult):
                    QMessageBox.warning(dialog, title, "Source scan returned an unexpected result.")
                    return
                _add_candidates(result.candidates)

            started = source_task_controller.start(
                request,
                run_source_mix_scan,
                status_message=f"Scanning source: {request.source_path.name}...",
                on_complete=_completed,
                on_error=lambda message: QMessageBox.warning(dialog, title, message),
                on_idle=lambda: _set_source_scan_controls_enabled(True),
            )
            if started:
                _set_source_scan_controls_enabled(False)

        for target_entry in target_entries:
            normalized = normalize_source_mix_virtual_path(target_entry.path)
            if not normalized:
                continue
            item = QTreeWidgetItem(
                [
                    target_entry.path.replace("\\", "/"),
                    f"{int(target_entry.orig_size or target_entry.comp_size or 0):,}",
                    "",
                    target_entry.package_label,
                    "Keep original",
                ]
            )
            item.setData(0, Qt.UserRole, normalized)
            combo = QComboBox()
            combo.addItem("Keep original", None)
            combo.currentIndexChanged.connect(_refresh_source_mix_status)
            target_tree.addTopLevelItem(item)
            target_tree.setItemWidget(item, 2, combo)
            row_state_by_path[normalized] = {
                "entry": target_entry,
                "item": item,
                "combo": combo,
                "candidate_keys": set(),
            }

        def _add_loose_source() -> None:
            selected_dir = QFileDialog.getExistingDirectory(
                dialog,
                "Add Loose Mod Folder",
                str(self._suggest_workspace_base_dir()),
            )
            if not selected_dir:
                return
            _start_source_scan(
                SourceMixScanRequest(
                    source_path=Path(selected_dir),
                    source_kind="loose",
                    target_entries=tuple(target_entries_by_virtual_path.items()),
                ),
                title="Add Loose Mod Folder",
            )

        def _add_mod_archive_source() -> None:
            selected_path, _selected_filter = QFileDialog.getOpenFileName(
                dialog,
                "Add .pamt/.paz Mod",
                str(self._suggest_workspace_base_dir()),
                "Archive Mod Sources (*.pamt *.paz);;All Files (*.*)",
            )
            if not selected_path:
                return
            _start_source_scan(
                SourceMixScanRequest(
                    source_path=Path(selected_path),
                    source_kind="mod_archive",
                    target_entries=tuple(target_entries_by_virtual_path.items()),
                ),
                title="Add .pamt/.paz Mod",
            )

        add_loose_button.clicked.connect(_add_loose_source)
        add_mod_archive_button.clicked.connect(_add_mod_archive_source)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        write_button = QPushButton("Write Loose Package")
        write_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(write_button)
        layout.addLayout(button_row)
        cancel_button.clicked.connect(dialog.reject)

        def _selected_source_mix_selections() -> List[SourceMixSelection]:
            selections: List[SourceMixSelection] = []
            for normalized, state in row_state_by_path.items():
                combo = state.get("combo")
                entry_obj = state.get("entry")
                if not isinstance(combo, QComboBox) or not isinstance(entry_obj, ArchiveEntry):
                    continue
                candidate = combo.currentData()
                if isinstance(candidate, SourceMixCandidate):
                    selections.append(SourceMixSelection(entry_obj.path, candidate, "replace"))
                else:
                    selections.append(SourceMixSelection(entry_obj.path, None, "keep_target"))
            return selections

        def _accept_source_mix() -> None:
            selections = [selection for selection in _selected_source_mix_selections() if selection.strategy == "replace"]
            if not selections:
                QMessageBox.information(dialog, "Build Loose Package From Sources", "Choose at least one replacement source first.")
                return
            validation = validate_source_mix_selections(selections)
            if not validation.ok:
                QMessageBox.warning(
                    dialog,
                    "Source Mix Validation",
                    "\n".join(validation.blocking_errors[:12]),
                )
                return
            dialog.accept()
            extra_payload_specs = self._source_mix_sidecar_referenced_payload_specs(
                [selection.chosen_candidate for selection in selections if isinstance(selection.chosen_candidate, SourceMixCandidate)],
                loaded_source_candidates,
            )
            export_target = self._collect_archive_mod_ready_export_target(
                browse_title="Select Mod-Ready Loose Export Root",
                prompt_for_metadata=True,
                dialog_title="Write Source Mix Loose Package",
                allow_dmm_texture_structure=False,
            )
            if export_target is None:
                return
            parent_root, package_info, create_no_encrypt, _include_related_files, export_options = export_target

            def _commit_task(log: Callable[[str], None]) -> object:
                requests: List[ArchivePatchRequest] = []
                for selection in selections:
                    candidate = selection.chosen_candidate
                    if not isinstance(candidate, SourceMixCandidate) or not isinstance(candidate.target_archive_entry, ArchiveEntry):
                        continue
                    log(f"Reading source payload for {candidate.display_path} from {candidate.layer.label}...")
                    requests.append(
                        ArchivePatchRequest(
                            entry=candidate.target_archive_entry,
                            payload_data=candidate.read_payload(),
                        )
                    )
                if not requests:
                    raise ValueError("No valid replacement payloads were selected.")
                if extra_payload_specs:
                    log(
                        f"Auto-including {len(extra_payload_specs):,} sidecar-referenced texture payload(s) from the source package."
                    )
                log(f"Writing {len(requests):,} source-mix payload(s) into a mod-ready loose package...")
                return export_archive_payloads_to_mod_ready_loose(
                    requests,
                    parent_root=parent_root,
                    package_info=package_info,
                    export_options=export_options,
                    create_no_encrypt_file=create_no_encrypt,
                    extra_payloads_to_include=extra_payload_specs,
                    on_log=log,
                )

            def _handle_complete(result: object) -> None:
                if not isinstance(result, ArchiveLooseExportResult):
                    self.set_status_message("Source mix loose export finished with an unexpected result payload.", error=True)
                    return
                QMessageBox.information(
                    self,
                    "Source Mix Loose Export Complete",
                    f"Wrote source-mix payload(s) into:\n{result.package_root}",
                )
                self.set_status_message(f"Wrote source-mix loose package: {result.package_root}")

            self._run_utility_task_when_idle(
                status_message=f"Writing source-mix loose package for {entry.basename}...",
                task=_commit_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        write_button.clicked.connect(_accept_source_mix)
        _refresh_source_mix_status()
        dialog.exec()
