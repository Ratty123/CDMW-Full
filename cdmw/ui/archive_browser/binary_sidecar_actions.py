"""Archive binary sidecar and HKX corpus actions."""

from __future__ import annotations

import dataclasses
import json
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from cdmw.core.archive import (
    build_binary_sidecar_analysis_json,
    build_binary_sidecar_corpus_json,
    ensure_archive_preview_source,
    read_archive_entry_data,
)
from cdmw.core.archive_modding import build_hkx_converter_corpus_csv, build_hkx_converter_corpus_json
from cdmw.core.structured_binary_editor import (
    parse_length_prefixed_string_fields,
    parse_pabgh_table,
    patch_length_prefixed_string,
    rebuild_pabgh_table,
)
from cdmw.models import ArchiveEntry


class ArchiveBinarySidecarActionsMixin:
    """Binary sidecar decode, safe edit, and corpus report actions."""
    def _default_archive_hkx_json_path(self, entry: ArchiveEntry) -> Path:
        default_dir = self.settings_file_path.parent / "hkx_geometry_json"
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "archive_hkx"
        return default_dir / f"{stem}.geometry.json"

    def _default_archive_hkx_xml_path(self, entry: ArchiveEntry) -> Path:
        default_dir = self.settings_file_path.parent / "hkx_geometry_xml"
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "archive_hkx"
        return default_dir / f"{stem}.geometry.xml"

    def _default_archive_hkx_havok_xml_view_path(self, entry: ArchiveEntry) -> Path:
        default_dir = self.settings_file_path.parent / "hkx_havok_xml_view"
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "archive_hkx"
        return default_dir / f"{stem}.havok-view.xml"

    def _default_hkx_corpus_report_path(self, source_dir: Path) -> Path:
        default_dir = self.settings_file_path.parent / "hkx_corpus_reports"
        source_name = source_dir.name or "hkx_corpus"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_name).strip("_") or "hkx_corpus"
        return default_dir / f"{safe_name}.hkx-corpus.json"

    def _default_hkx_corpus_report_path_for_sources(self, source_paths: Sequence[Path]) -> Path:
        default_dir = self.settings_file_path.parent / "hkx_corpus_reports"
        if len(source_paths) == 1:
            source = source_paths[0]
            source_name = source.name or "hkx_corpus"
            if source.is_file() and source.suffix.lower() == ".hkx":
                source_name = source.stem or source_name
        else:
            source_name = f"selected_{len(source_paths)}_hkx_files"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_name).strip("_") or "hkx_corpus"
        return default_dir / f"{safe_name}.hkx-corpus.json"

    def _default_archive_binary_sidecar_json_path(self, entry: ArchiveEntry) -> Path:
        default_dir = self.settings_file_path.parent / "binary_sidecar_decode"
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "archive_sidecar"
        extension_label = str(entry.extension or "").strip(".").lower() or "sidecar"
        return default_dir / f"{stem}.{extension_label}.sidecar.json"

    def _default_binary_sidecar_corpus_report_path_for_sources(self, source_paths: Sequence[Path]) -> Path:
        default_dir = self.settings_file_path.parent / "binary_sidecar_decode"
        if len(source_paths) == 1:
            source = source_paths[0]
            source_name = source.name or "sidecar_corpus"
            if source.is_file() and source.suffix.lower() in {".meshinfo", ".motionblending", ".paa_metabin", ".prefab", ".pappt", ".pamhc", ".seqmt"}:
                source_name = source.stem or source_name
        else:
            source_name = f"selected_{len(source_paths)}_sidecar_files"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_name).strip("_") or "sidecar_corpus"
        return default_dir / f"{safe_name}.sidecar-corpus.json"

    def _build_archive_binary_sidecar_json_document(
        self,
        entry: ArchiveEntry,
        *,
        log: Optional[Callable[[str], None]] = None,
        ) -> str:
        if log is not None:
            log(f"Decoding {entry.path} as an experimental read-only binary sidecar document...")
        source_path, _note = ensure_archive_preview_source(entry)
        return build_binary_sidecar_analysis_json(
            source_path.read_bytes(),
            entry.path,
            extension=entry.extension,
            source_entry=entry,
            archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
            archive_entries_by_basename=self.archive_entries_by_basename,
        )

    def _export_current_archive_binary_sidecar_json(self) -> None:
        entry = self._current_archive_binary_sidecar_entry()
        if entry is None:
            self.set_status_message("Select a structured metadata/animation archive entry to export a sidecar decode JSON.", error=True)
            return
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Binary Sidecar Decode JSON",
            str(self._default_archive_binary_sidecar_json_path(entry)),
            "Sidecar Decode JSON (*.sidecar.json *.json);;JSON (*.json)",
        )
        if not selected:
            return
        output_path = Path(selected)
        if not output_path.suffix:
            output_path = output_path.with_name(f"{output_path.name}.sidecar.json")

        def _task(log: Callable[[str], None]) -> Path:
            document_text = self._build_archive_binary_sidecar_json_document(entry, log=log)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(document_text, encoding="utf-8")
            return output_path

        def _handle_complete(result: object) -> None:
            exported_path = result if isinstance(result, Path) else output_path
            QMessageBox.information(
                self,
                "Sidecar Decode Export Complete",
                (
                    f"Exported read-only sidecar decode JSON:\n{exported_path}\n\n"
                    "This is schema-recovery data. Direct import/editing is disabled until field layouts and no-edit rebuilds are proven."
                ),
            )
            self.set_status_message(f"Exported sidecar decode JSON for {entry.basename}.")

        self._run_utility_task(
            status_message=f"Exporting sidecar decode JSON for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _edit_selected_archive_hkx_reference(self) -> None:
        selected_entries = self._resolved_archive_reference_entries(self._selected_archive_texture_references())
        entry = selected_entries[0] if len(selected_entries) == 1 else None
        if not isinstance(entry, ArchiveEntry) or str(entry.extension or "").lower() not in {".hkx", ".hkt"}:
            self.set_status_message("Select one resolved HKX/HKT reference first.", error=True)
            return
        self._edit_archive_hkx_entry(entry)

    def _open_archive_binary_sidecar_inspector_dialog(self, entry: ArchiveEntry, document_text: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Inspect Sidecar - {entry.basename}")
        dialog.resize(940, 680)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        guidance = QLabel(
            "Experimental read-only decode. Strings, references, offsets, count/table candidates, and numeric rows are shown for schema recovery; writing is disabled until safe rebuilds are proven."
        )
        guidance.setObjectName("HintLabel")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor.setPlainText(document_text)
        editor.setFont(QFont("Consolas", 9))
        layout.addWidget(editor, stretch=1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        export_button = QPushButton("Export JSON...")
        close_button = QPushButton("Close")
        button_row.addStretch(1)
        button_row.addWidget(export_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        def _export_dialog_json() -> None:
            selected, _selected_filter = QFileDialog.getSaveFileName(
                dialog,
                "Export Binary Sidecar Decode JSON",
                str(self._default_archive_binary_sidecar_json_path(entry)),
                "Sidecar Decode JSON (*.sidecar.json *.json);;JSON (*.json)",
            )
            if not selected:
                return
            output_path = Path(selected)
            if not output_path.suffix:
                output_path = output_path.with_name(f"{output_path.name}.sidecar.json")
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(editor.toPlainText(), encoding="utf-8")
            except Exception as exc:
                QMessageBox.warning(dialog, "Sidecar Decode Export", str(exc))
                return
            self.set_status_message(f"Exported sidecar decode JSON for {entry.basename}.")

        export_button.clicked.connect(_export_dialog_json)
        close_button.clicked.connect(dialog.accept)
        dialog.exec()

    def _inspect_current_archive_binary_sidecar(self) -> None:
        entry = self._current_archive_binary_sidecar_entry()
        if entry is None:
            self.set_status_message("Select a structured metadata/animation archive entry to inspect.", error=True)
            return

        def _task(log: Callable[[str], None]) -> str:
            return self._build_archive_binary_sidecar_json_document(entry, log=log)

        def _handle_complete(result: object) -> None:
            if not isinstance(result, str):
                self.set_status_message("Sidecar inspection finished with an unexpected result payload.", error=True)
                return
            self._open_archive_binary_sidecar_inspector_dialog(entry, result)

        self._run_utility_task(
            status_message=f"Inspecting sidecar structure for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _edit_archive_structured_binary_sidecar(self, entry: ArchiveEntry) -> None:
        extension = str(entry.extension or "").lower()
        if extension not in {".paseq", ".paseqc", ".pastage", ".pabgh"}:
            self.set_status_message("This archive entry does not have a safe structured editor.", error=True)
            return
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
        except Exception as exc:
            QMessageBox.warning(self, "Edit Structured Data Safely", f"Could not read archive entry:\n{exc}")
            return

        edited_data = bytes(data)
        proof_lines: Tuple[str, ...] = ()
        if extension == ".pabgh":
            try:
                table = parse_pabgh_table(data)
            except Exception as exc:
                QMessageBox.warning(self, "Edit PABGH Table", str(exc))
                return
            labels = [
                f"{row.index}: id={row.row_id} offset=0x{row.offset:X}"
                for row in table.rows
            ]
            if not labels:
                QMessageBox.information(self, "Edit PABGH Table", "No rows were detected in this PABGH table.")
                return
            selected, accepted = QInputDialog.getItem(
                self,
                "Edit PABGH Row",
                f"Detected {len(labels):,} row(s), {table.row_size}-byte row flavor. Choose a row to edit:",
                labels,
                0,
                False,
            )
            if not accepted or not selected:
                return
            selected_index = int(str(selected).split(":", 1)[0])
            row = table.rows[selected_index]
            new_offset, offset_ok = QInputDialog.getInt(
                self,
                "Edit PABGH Row Offset",
                "Target offset:",
                int(row.offset),
                0,
                max(0, len(data)),
                1,
            )
            if not offset_ok:
                return
            rows = list(table.rows)
            rows[selected_index] = dataclasses.replace(row, offset=int(new_offset))
            try:
                edited_data = rebuild_pabgh_table(data, rows, row_size=table.row_size)
            except Exception as exc:
                QMessageBox.warning(self, "Edit PABGH Table", str(exc))
                return
            proof_lines = (*table.proof_lines, f"Edited row {selected_index} offset to 0x{int(new_offset):X}.")
        else:
            fields = parse_length_prefixed_string_fields(data)
            if not fields:
                QMessageBox.information(
                    self,
                    "Edit Structured Data Safely",
                    "No validated length-prefixed string fields were detected for fixed-size editing.",
                )
                return
            labels = [
                f"{field.index}: 0x{field.offset:X} len={field.length} [{field.kind}] {field.text[:96]}"
                for field in fields[:500]
            ]
            selected, accepted = QInputDialog.getItem(
                self,
                "Edit Structured String",
                "Choose a fixed-size string field to edit:",
                labels,
                0,
                False,
            )
            if not accepted or not selected:
                return
            selected_index = int(str(selected).split(":", 1)[0])
            field = fields[selected_index]
            replacement, text_ok = QInputDialog.getText(
                self,
                "Edit Structured String",
                f"Replacement text, maximum {field.length:,} UTF-8 byte(s):",
                text=field.text,
            )
            if not text_ok:
                return
            try:
                result = patch_length_prefixed_string(data, field, str(replacement), allow_size_change=False)
            except Exception as exc:
                QMessageBox.warning(self, "Edit Structured String", str(exc))
                return
            edited_data = result.data
            proof_lines = result.proof_lines

        default_path = self.settings_file_path.parent / "structured_edits" / PurePosixPath(entry.path.replace("\\", "/")).name
        selected_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Edited Structured Sidecar Copy",
            str(default_path),
            "Binary Sidecar (*)",
        )
        if not selected_path:
            return
        output_path = Path(selected_path)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(edited_data)
        except Exception as exc:
            QMessageBox.warning(self, "Edit Structured Data Safely", f"Could not save edited copy:\n{exc}")
            return
        self.append_log(
            f"Saved safe structured sidecar edit for {entry.path} to {output_path}. "
            + " ".join(proof_lines[:3])
        )
        self.set_status_message(f"Saved structured sidecar edit: {output_path}")

    def _export_hkx_converter_corpus_report(self) -> None:
        source_mode, source_ok = QInputDialog.getItem(
            self,
            "HKX Corpus Source",
            "Scan a folder recursively, or scan specific .hkx files?",
            ("Folder", "Files"),
            0,
            False,
        )
        if not source_ok:
            return
        source_paths: Tuple[Path, ...]
        if str(source_mode).lower().startswith("file"):
            selected_files, _selected_filter = QFileDialog.getOpenFileNames(
                self,
                "Select HKX Corpus Files",
                str(self._suggest_workspace_base_dir()),
                "HKX Files (*.hkx);;All Files (*)",
            )
            source_paths = tuple(Path(path) for path in selected_files if str(path).strip())
        else:
            source_dir_text = QFileDialog.getExistingDirectory(
                self,
                "Select HKX Corpus Folder",
                str(self._suggest_workspace_base_dir()),
            )
            source_paths = (Path(source_dir_text),) if source_dir_text else ()
        if not source_paths:
            return
        scan_limit, limit_ok = QInputDialog.getInt(
            self,
            "HKX Corpus Scan Limit",
            (
                "Maximum HKX files to discover and scan in detail.\n"
                "Use 1,000 for the normal quick corpus report, or 0 for no limit."
            ),
            1000,
            0,
            1_000_000,
            100,
        )
        if not limit_ok:
            return
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export HKX Corpus Report",
            str(self._default_hkx_corpus_report_path_for_sources(source_paths)),
            "HKX Corpus JSON (*.hkx-corpus.json *.json);;HKX Corpus CSV (*.hkx-corpus.csv *.csv)",
        )
        if not selected:
            return
        output_path = Path(selected)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".hkx-corpus.json")
        source_label = (
            str(source_paths[0])
            if len(source_paths) == 1
            else f"{len(source_paths):,} selected HKX file(s)"
        )
        selected_scan_limit = int(scan_limit)
        discovery_limit = selected_scan_limit if selected_scan_limit > 0 else None
        detail_scan_limit = selected_scan_limit

        def _task(
            log: Callable[[str], None],
            progress: Callable[[int, int, str], None],
            stop_event: threading.Event,
        ) -> Dict[str, object]:
            log(f"Scanning HKX corpus source: {source_label}")
            if selected_scan_limit > 0:
                log(f"HKX corpus scan limit: {selected_scan_limit:,} file(s).")
            else:
                log("HKX corpus scan limit: none.")
            parsed_report: Mapping[str, object] = {}
            if output_path.suffix.lower() == ".csv":
                report_text = build_hkx_converter_corpus_csv(
                    source_paths,
                    discovery_limit=discovery_limit,
                    detail_scan_limit=detail_scan_limit,
                    stop_event=stop_event,
                    progress_callback=progress,
                )
                output_kind = "CSV"
                native_fast_scan = None
            else:
                report_text = build_hkx_converter_corpus_json(
                    source_paths,
                    discovery_limit=discovery_limit,
                    detail_scan_limit=detail_scan_limit,
                    stop_event=stop_event,
                    progress_callback=progress,
                )
                output_kind = "JSON"
                try:
                    parsed_report = json.loads(report_text)
                except json.JSONDecodeError:
                    parsed_report = {}
                native_fast_scan = parsed_report.get("native_fast_scan") if isinstance(parsed_report, Mapping) else None
            proof_summary_lines: List[str] = []
            if isinstance(parsed_report, Mapping):
                real_plan = parsed_report.get("representative_real_hkx_corpus_plan")
                if isinstance(real_plan, Mapping):
                    missing_roles = [
                        str(role)
                        for role in real_plan.get("missing_roles", [])
                        if str(role)
                    ]
                    proof_summary_lines.append(
                        "Representative real HKX corpus: "
                        f"{real_plan.get('status') or 'unknown'}"
                        + (f" | missing: {', '.join(missing_roles[:6])}" if missing_roles else "")
                    )
                ptch_proof = parsed_report.get("ptch_semantics_proof")
                if isinstance(ptch_proof, Mapping):
                    missing_observations = [
                        str(observation)
                        for observation in ptch_proof.get("missing_observations", [])
                        if str(observation)
                    ]
                    proof_summary_lines.append(
                        "PTCH/fixup proof: "
                        f"{ptch_proof.get('status') or 'unknown'}"
                        + (
                            f" | missing: {', '.join(missing_observations[:6])}"
                            if missing_observations
                            else ""
                        )
                    )
                hard_proof = parsed_report.get("hard_decoder_corpus_proof")
                if isinstance(hard_proof, Mapping):
                    missing_hard_targets = [
                        str(target)
                        for target in hard_proof.get("missing_observations", [])
                        if str(target)
                    ]
                    proof_summary_lines.append(
                        "Hard decoder corpus proof: "
                        f"{hard_proof.get('status') or 'unknown'}"
                        + (
                            f" | missing: {', '.join(missing_hard_targets[:6])}"
                            if missing_hard_targets
                            else ""
                        )
                    )
                corpus_evidence = parsed_report.get("corpus_evidence")
                if isinstance(corpus_evidence, Mapping):
                    priority_targets = corpus_evidence.get("priority_decoder_targets")
                    roundtrip_required = corpus_evidence.get("roundtrip_required_files")
                    native_status = corpus_evidence.get("native_scan_status")
                    target_names: List[str] = []
                    if isinstance(priority_targets, list):
                        for target in priority_targets[:5]:
                            if isinstance(target, Mapping) and str(target.get("target") or ""):
                                target_names.append(str(target.get("target") or ""))
                    evidence_line = "Corpus evidence: "
                    evidence_line += f"{len(priority_targets) if isinstance(priority_targets, list) else 0} decoder target(s)"
                    if target_names:
                        evidence_line += f" | top: {', '.join(target_names)}"
                    if isinstance(roundtrip_required, list) and roundtrip_required:
                        evidence_line += f" | roundtrip gaps: {len(roundtrip_required)} role(s)"
                    if isinstance(native_status, Mapping) and native_status.get("available") is not True:
                        evidence_line += " | native scan unavailable"
                    proof_summary_lines.append(evidence_line)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report_text, encoding="utf-8", newline="")
            return {
                "path": output_path,
                "kind": output_kind,
                "file_count": report_text.count(".hkx") if output_kind == "CSV" else None,
                "native_fast_scan": native_fast_scan,
                "detail_scan_truncated": parsed_report.get("detail_scan_truncated") if output_kind == "JSON" and isinstance(parsed_report, Mapping) else None,
                "discovered_file_count": parsed_report.get("discovered_file_count") if output_kind == "JSON" and isinstance(parsed_report, Mapping) else None,
                "discovery_scan_limited": parsed_report.get("discovery_scan_limited") if output_kind == "JSON" and isinstance(parsed_report, Mapping) else None,
                "discovery_file_limit": parsed_report.get("discovery_file_limit") if output_kind == "JSON" and isinstance(parsed_report, Mapping) else None,
                "detail_file_limit": parsed_report.get("detail_file_limit") if output_kind == "JSON" and isinstance(parsed_report, Mapping) else None,
                "roundtrip_scan_limited": parsed_report.get("roundtrip_scan_limited") if output_kind == "JSON" and isinstance(parsed_report, Mapping) else None,
                "roundtrip_file_limit": parsed_report.get("roundtrip_file_limit") if output_kind == "JSON" and isinstance(parsed_report, Mapping) else None,
                "roundtrip_skipped_file_count": parsed_report.get("roundtrip_skipped_file_count") if output_kind == "JSON" and isinstance(parsed_report, Mapping) else None,
                "proof_summary": "\n".join(proof_summary_lines),
            }

        def _handle_complete(result: object) -> None:
            exported_path = output_path
            output_kind = "report"
            native_summary = ""
            detail_summary = ""
            proof_summary = ""
            if isinstance(result, Mapping):
                exported_path = result.get("path") if isinstance(result.get("path"), Path) else output_path
                output_kind = str(result.get("kind") or "report")
                native_scan = result.get("native_fast_scan")
                if isinstance(native_scan, Mapping):
                    native_summary = (
                        "\n\nNative Rust preflight: "
                        f"{native_scan.get('ok_count') or 0}/{native_scan.get('file_count') or 0} parsed, "
                        f"{native_scan.get('total_item_records') or 0} ITEM record(s), "
                        f"{native_scan.get('total_physics_tuning_slots') or 0} tuning slot(s)."
                    )
                if result.get("discovery_scan_limited") is True:
                    detail_summary = (
                        "\n\nHKX discovery was capped at "
                        f"{result.get('discovery_file_limit') or 'the selected limit'} file(s). "
                        "Run again with a higher limit or 0 for no limit if you want a deeper report."
                    )
                if result.get("detail_scan_truncated") is True:
                    detail_summary += (
                        "\n\nDetailed Python converter rows were capped at "
                        f"{result.get('detail_file_limit') or 'the configured limit'} of "
                        f"{result.get('discovered_file_count') or 'the discovered'} HKX file(s). "
                        "Run again with a higher limit or 0 for no limit if you want an uncapped deep scan. "
                        "Advanced launch-time override CDMW_HKX_CORPUS_DETAIL_LIMIT is still supported."
                    )
                if result.get("roundtrip_scan_limited") is True:
                    detail_summary += (
                        "\n\nNo-edit JSON/XML roundtrip verification was capped at "
                        f"{result.get('roundtrip_file_limit') or 'the configured limit'} detailed file(s); "
                        f"{result.get('roundtrip_skipped_file_count') or 0} later file(s) were decoded without "
                        "the expensive import verification. Set CDMW_HKX_CORPUS_ROUNDTRIP_LIMIT=0 before launching "
                        "the app for a full proof scan."
                    )
                proof_text = str(result.get("proof_summary") or "").strip()
                if proof_text:
                    proof_summary = f"\n\n{proof_text}"
            QMessageBox.information(
                self,
                "HKX Corpus Report Complete",
                (
                    f"Exported HKX corpus {output_kind} report:\n{exported_path}\n\n"
                    "This is a local converter coverage report only. Game files and archives were not modified."
                    f"{native_summary}{detail_summary}{proof_summary}"
                ),
            )
            self.set_status_message(f"Exported HKX corpus report to {exported_path}.")

        self._run_utility_task(
            status_message=f"Scanning HKX corpus source {source_label}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
            task_accepts_progress=True,
            task_accepts_cancel=True,
        )

    def _export_binary_sidecar_corpus_report(self) -> None:
        source_mode, source_ok = QInputDialog.getItem(
            self,
            "Sidecar Corpus Source",
            "Scan a folder recursively, or scan specific .meshinfo/.motionblending/.paa_metabin/.prefab/.pappt/.pamhc/.seqmt files?",
            ("Folder", "Files"),
            0,
            False,
        )
        if not source_ok:
            return
        source_paths: Tuple[Path, ...]
        if str(source_mode).lower().startswith("file"):
            selected_files, _selected_filter = QFileDialog.getOpenFileNames(
                self,
                "Select Sidecar Corpus Files",
                str(self._suggest_workspace_base_dir()),
                "Binary Sidecars (*.meshinfo *.motionblending *.paa_metabin *.prefab *.pappt *.pamhc *.seqmt);;All Files (*)",
            )
            source_paths = tuple(Path(path) for path in selected_files if str(path).strip())
        else:
            source_dir_text = QFileDialog.getExistingDirectory(
                self,
                "Select Sidecar Corpus Folder",
                str(self._suggest_workspace_base_dir()),
            )
            source_paths = (Path(source_dir_text),) if source_dir_text else ()
        if not source_paths:
            return
        scan_limit, limit_ok = QInputDialog.getInt(
            self,
            "Sidecar Corpus Scan Limit",
            (
                "Maximum .meshinfo/.motionblending/.paa_metabin/.prefab/.pappt/.pamhc/.seqmt files to discover and scan in detail.\n"
                "Use 1,000 for a quick report, or 0 for no limit."
            ),
            1000,
            0,
            1_000_000,
            100,
        )
        if not limit_ok:
            return
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Sidecar Corpus Report",
            str(self._default_binary_sidecar_corpus_report_path_for_sources(source_paths)),
            "Sidecar Corpus JSON (*.sidecar-corpus.json *.json);;JSON (*.json)",
        )
        if not selected:
            return
        output_path = Path(selected)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".sidecar-corpus.json")
        source_label = (
            str(source_paths[0])
            if len(source_paths) == 1
            else f"{len(source_paths):,} selected sidecar file(s)"
        )
        selected_scan_limit = int(scan_limit)
        scan_limit_value = selected_scan_limit if selected_scan_limit > 0 else None

        def _task(
            log: Callable[[str], None],
            progress: Callable[[int, int, str], None],
            stop_event: threading.Event,
        ) -> Dict[str, object]:
            log(f"Scanning binary sidecar corpus source: {source_label}")
            if scan_limit_value is None:
                log("Sidecar corpus scan limit: none.")
            else:
                log(f"Sidecar corpus scan limit: {scan_limit_value:,} file(s).")
            report_text = build_binary_sidecar_corpus_json(
                source_paths,
                discovery_limit=scan_limit_value,
                detail_scan_limit=scan_limit_value,
                stop_event=stop_event,
                progress_callback=progress,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report_text, encoding="utf-8")
            try:
                parsed_report = json.loads(report_text)
            except json.JSONDecodeError:
                parsed_report = {}
            return {
                "path": output_path,
                "summary": parsed_report.get("summary") if isinstance(parsed_report, Mapping) else {},
            }

        def _handle_complete(result: object) -> None:
            exported_path = output_path
            summary = {}
            if isinstance(result, Mapping):
                exported_path = result.get("path") if isinstance(result.get("path"), Path) else output_path
                if isinstance(result.get("summary"), Mapping):
                    summary = dict(result.get("summary") or {})
            detail = (
                "\n\n"
                f"Scanned {summary.get('files_scanned') or 0:,} / {summary.get('files_discovered') or 0:,} discovered sidecar file(s): "
                f"{summary.get('meshinfo_files_scanned') or 0:,} .meshinfo, "
                f"{summary.get('motionblending_files_scanned') or 0:,} .motionblending, "
                f"{summary.get('paa_metabin_files_scanned') or 0:,} .paa_metabin, "
                f"{summary.get('prefab_files_scanned') or 0:,} .prefab, "
                f"{summary.get('seqmt_files_scanned') or 0:,} .seqmt."
                if summary
                else ""
            )
            QMessageBox.information(
                self,
                "Sidecar Corpus Report Complete",
                (
                    f"Exported sidecar corpus JSON report:\n{exported_path}\n\n"
                    "This is a read-only schema/layout ranking report. Game files and archives were not modified."
                    f"{detail}"
                ),
            )
            self.set_status_message(f"Exported sidecar corpus report to {exported_path}.")

        self._run_utility_task(
            status_message=f"Scanning sidecar corpus source {source_label}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
            task_accepts_progress=True,
            task_accepts_cancel=True,
        )

__all__ = ["ArchiveBinarySidecarActionsMixin"]
