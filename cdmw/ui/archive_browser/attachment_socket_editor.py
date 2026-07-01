"""Archive browser socket XML editor helpers."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.archive import read_archive_entry_data
from cdmw.core.archive_modding import (
    ArchiveLooseExportResult,
    ArchivePatchRequest,
    export_archive_payloads_to_mod_ready_loose,
)
from cdmw.core.xml_text import decode_xml_text_payload, encode_xml_text_like_source
from cdmw.models import ArchiveEntry, AttachmentSocketInfo
from cdmw.ui.shell.theme_controller import build_monospace_font
from cdmw.ui.widgets import PreviewSyntaxHighlighter


class ArchiveAttachmentSocketEditorMixin:
    """Socket XML dialog, compare picker, and loose export helpers."""

    @staticmethod
    def _attachment_socket_xml_text(root: ET.Element, *, include_declaration: bool) -> str:
        try:
            ET.indent(root, space="  ")
        except Exception:
            pass
        document_text = ET.tostring(root, encoding="unicode")
        if include_declaration:
            document_text = '<?xml version="1.0" encoding="utf-8"?>\n' + document_text
        return document_text.rstrip() + "\n"

    def _attachment_socket_xml_numbered_text(self, root: ET.Element, *, include_declaration: bool) -> str:
        lines = self._attachment_socket_xml_text(root, include_declaration=include_declaration).splitlines()
        line_width = max(2, len(str(len(lines))))
        return "\n".join(f"{index:>{line_width}} | {line}" for index, line in enumerate(lines, start=1)) + "\n"

    def _open_archive_socket_xml_editor_dialog(
        self,
        socket_entry: ArchiveEntry,
        *,
        owner: Optional[QWidget] = None,
    ) -> None:
        try:
            data, _decompressed, _note = read_archive_entry_data(socket_entry)
        except Exception as exc:
            QMessageBox.warning(owner or self, "Socket XML Editor", f"Could not read socket XML:\n{exc}")
            return
        decoded_socket_xml = decode_xml_text_payload(data)
        original_text = decoded_socket_xml.text
        try:
            root = ET.fromstring(original_text)
        except Exception as exc:
            QMessageBox.warning(owner or self, "Socket XML Editor", f"Could not parse socket XML:\n{exc}")
            return

        socket_elements: List[ET.Element] = []
        for element in root.iter():
            local_name = str(element.tag).rsplit("}", 1)[-1]
            if local_name == "Socket" and (
                "Name" in element.attrib or "Translation" in element.attrib or "Rotation" in element.attrib
            ):
                socket_elements.append(element)
        if not socket_elements:
            QMessageBox.information(
                owner or self,
                "Socket XML Editor",
                "No editable Socket rows were found in this XML descriptor.",
            )
            return

        dialog = QDialog(owner or self)
        dialog.setWindowTitle(f"Edit Socket Values - {socket_entry.basename}")
        dialog.resize(1180, 700)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Edit socket descriptor transforms and write them as a mod-ready loose package. "
            "This edits XML only; binary prefab, HKX, and PAA writes remain disabled."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        splitter = QSplitter(Qt.Vertical)
        socket_tree = QTreeWidget()
        socket_tree.setColumnCount(10)
        socket_tree.setHeaderLabels(["#", "Socket", "Parent", "T X", "T Y", "T Z", "R X", "R Y", "R Z", "R W"])
        socket_tree.setRootIsDecorated(False)
        socket_tree.setAlternatingRowColors(True)
        socket_tree.setUniformRowHeights(True)
        socket_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        socket_tree.setMinimumHeight(220)
        socket_tree.header().setStretchLastSection(False)
        splitter.addWidget(socket_tree)

        editor_tabs = QTabWidget()
        socket_values_page = QWidget()
        socket_values_layout = QVBoxLayout(socket_values_page)
        socket_values_layout.setContentsMargins(0, 0, 0, 0)
        socket_values_layout.setSpacing(8)
        edit_grid = QGridLayout()
        edit_grid.setHorizontalSpacing(10)
        edit_grid.setVerticalSpacing(8)
        selected_name_label = QLabel("-")
        selected_name_label.setObjectName("HintLabel")
        selected_parent_label = QLabel("-")
        selected_parent_label.setObjectName("HintLabel")
        edit_grid.addWidget(QLabel("Selected socket"), 0, 0)
        edit_grid.addWidget(selected_name_label, 0, 1, 1, 4)
        edit_grid.addWidget(QLabel("Parent"), 1, 0)
        edit_grid.addWidget(selected_parent_label, 1, 1, 1, 4)

        def _spin(minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
            spin = QDoubleSpinBox()
            spin.setRange(minimum, maximum)
            spin.setDecimals(6)
            spin.setSingleStep(step)
            spin.setKeyboardTracking(False)
            return spin

        translation_spins = [_spin(-1000.0, 1000.0, 0.01) for _index in range(3)]
        rotation_spins = [_spin(-10.0, 10.0, 0.001) for _index in range(4)]
        for column, axis in enumerate(("X", "Y", "Z"), start=1):
            edit_grid.addWidget(QLabel(axis), 2, column)
        edit_grid.addWidget(QLabel("Translation offset"), 3, 0)
        for column, spin in enumerate(translation_spins, start=1):
            spin.setToolTip(f"{('X', 'Y', 'Z')[column - 1]} offset for the selected socket.")
            edit_grid.addWidget(spin, 3, column)
        for column, axis in enumerate(("X", "Y", "Z", "W"), start=1):
            edit_grid.addWidget(QLabel(axis), 4, column)
        edit_grid.addWidget(QLabel("Rotation quaternion"), 5, 0)
        for column, spin in enumerate(rotation_spins, start=1):
            spin.setToolTip(f"{('X', 'Y', 'Z', 'W')[column - 1]} quaternion component for the selected socket.")
            edit_grid.addWidget(spin, 5, column)
        socket_values_layout.addLayout(edit_grid)
        socket_values_hint = QLabel(
            "Edit only the selected socket values here. Use the numbered XML tab for review; the export still writes the full socket descriptor."
        )
        socket_values_hint.setObjectName("HintLabel")
        socket_values_hint.setWordWrap(True)
        socket_values_layout.addWidget(socket_values_hint)
        editor_tabs.addTab(socket_values_page, "Socket Values")

        xml_page = QWidget()
        xml_layout = QVBoxLayout(xml_page)
        xml_layout.setContentsMargins(0, 0, 0, 0)
        xml_layout.setSpacing(6)
        preview_label = QLabel("Numbered XML preview")
        preview_label.setObjectName("HintLabel")
        preview_editor = QPlainTextEdit()
        preview_editor.setReadOnly(True)
        preview_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        preview_editor.setFont(build_monospace_font(self.settings))
        preview_highlighter = PreviewSyntaxHighlighter(preview_editor.document(), self.current_theme_key)
        preview_highlighter.set_language_for_extension(".xml")
        xml_layout.addWidget(preview_label)
        xml_layout.addWidget(preview_editor, 1)
        editor_tabs.addTab(xml_page, "Numbered XML")

        compare_page = QWidget()
        compare_layout = QVBoxLayout(compare_page)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_layout.setSpacing(6)
        compare_hint = QLabel(
            "Load another socket XML to compare actual socket values. Copy keeps the current socket name; parent copy is optional."
        )
        compare_hint.setObjectName("HintLabel")
        compare_hint.setWordWrap(True)
        compare_layout.addWidget(compare_hint)
        compare_source_label = QLabel("Compare source: none loaded")
        compare_source_label.setObjectName("HintLabel")
        compare_source_label.setWordWrap(True)
        compare_layout.addWidget(compare_source_label)
        compare_tree = QTreeWidget()
        compare_tree.setColumnCount(9)
        compare_tree.setHeaderLabels(
            [
                "Socket",
                "Current Parent",
                "Compare Parent",
                "Current T",
                "Compare T",
                "Current R",
                "Compare R",
                "Status",
                "Source",
            ]
        )
        compare_tree.setRootIsDecorated(False)
        compare_tree.setAlternatingRowColors(True)
        compare_tree.setUniformRowHeights(True)
        compare_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        compare_tree.header().setStretchLastSection(False)
        compare_layout.addWidget(compare_tree, 1)
        compare_controls = QHBoxLayout()
        compare_controls.setSpacing(8)
        compare_archive_button = QPushButton("Load Archive Socket XML...")
        compare_loose_button = QPushButton("Open Loose Socket XML...")
        compare_copy_matching_button = QPushButton("Copy To Matching Socket")
        compare_copy_selected_button = QPushButton("Copy To Selected Socket")
        compare_include_parent_checkbox = QCheckBox("Include parent")
        compare_copy_matching_button.setEnabled(False)
        compare_copy_selected_button.setEnabled(False)
        compare_controls.addWidget(compare_archive_button)
        compare_controls.addWidget(compare_loose_button)
        compare_controls.addStretch(1)
        compare_controls.addWidget(compare_include_parent_checkbox)
        compare_controls.addWidget(compare_copy_matching_button)
        compare_controls.addWidget(compare_copy_selected_button)
        compare_layout.addLayout(compare_controls)
        editor_tabs.addTab(compare_page, "Compare Socket XML")

        splitter.addWidget(editor_tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([330, 270])
        layout.addWidget(splitter, 1)

        include_declaration = original_text.lstrip().startswith("<?xml")
        dirty = {"value": False}

        def _socket_transform_values(element: ET.Element) -> Tuple[Tuple[float, float, float], Tuple[float, float, float, float]]:
            translation = self._parse_attachment_transform_values(str(element.attrib.get("Translation", "") or ""), 3) or (0.0, 0.0, 0.0)
            rotation = self._parse_attachment_transform_values(str(element.attrib.get("Rotation", "") or ""), 4) or (0.0, 0.0, 0.0, 1.0)
            return (
                (float(translation[0]), float(translation[1]), float(translation[2])),
                (float(rotation[0]), float(rotation[1]), float(rotation[2]), float(rotation[3])),
            )

        def _component_text(value: float) -> str:
            return f"{float(value):.6f}".rstrip("0").rstrip(".") or "0"

        def _refresh_item_text(item: QTreeWidgetItem, element: ET.Element) -> None:
            index = item.data(0, Qt.UserRole)
            translation, rotation = _socket_transform_values(element)
            values = (
                str(int(index) + 1) if isinstance(index, int) else "-",
                str(element.attrib.get("Name", "") or "-"),
                str(element.attrib.get("Parent", "") or "-"),
                *(_component_text(value) for value in translation),
                *(_component_text(value) for value in rotation),
            )
            for column, value in enumerate(values):
                item.setText(column, value)

        def _refresh_preview() -> None:
            preview_editor.setPlainText(self._attachment_socket_xml_numbered_text(root, include_declaration=include_declaration))

        for index, element in enumerate(socket_elements):
            item = QTreeWidgetItem()
            item.setData(0, Qt.UserRole, index)
            _refresh_item_text(item, element)
            socket_tree.addTopLevelItem(item)
        for column in range(socket_tree.columnCount()):
            socket_tree.resizeColumnToContents(column)

        def _selected_element() -> Tuple[Optional[QTreeWidgetItem], Optional[ET.Element]]:
            item = socket_tree.currentItem()
            if item is None:
                return None, None
            index = item.data(0, Qt.UserRole)
            if not isinstance(index, int) or index < 0 or index >= len(socket_elements):
                return item, None
            return item, socket_elements[index]

        loading_selection = {"value": False}

        def _load_selected_socket() -> None:
            item, element = _selected_element()
            loading_selection["value"] = True
            try:
                for spin in translation_spins + rotation_spins:
                    spin.setEnabled(element is not None)
                if element is None:
                    selected_name_label.setText("-")
                    selected_parent_label.setText("-")
                    return
                selected_name_label.setText(str(element.attrib.get("Name", "") or "-"))
                selected_parent_label.setText(str(element.attrib.get("Parent", "") or "-"))
                translation, rotation = _socket_transform_values(element)
                for spin, value in zip(translation_spins, translation):
                    spin.setValue(float(value))
                for spin, value in zip(rotation_spins, rotation):
                    spin.setValue(float(value))
            finally:
                loading_selection["value"] = False

        def _apply_selected_values() -> None:
            if loading_selection["value"]:
                return
            item, element = _selected_element()
            if item is None or element is None:
                return
            translation = tuple(spin.value() for spin in translation_spins)
            rotation = tuple(spin.value() for spin in rotation_spins)
            element.set("Translation", self._format_attachment_transform_values(translation))
            element.set("Rotation", self._format_attachment_transform_values(rotation))
            _refresh_item_text(item, element)
            dirty["value"] = True
            _refresh_preview()
            if compare_state.get("sockets"):
                _refresh_compare_tree()

        for spin in translation_spins + rotation_spins:
            spin.valueChanged.connect(lambda _value: _apply_selected_values())
        socket_tree.currentItemChanged.connect(lambda _current, _previous: _load_selected_socket())

        compare_state: Dict[str, object] = {"source": "", "sockets": (), "entry": None}
        socket_xml_candidate_cache: Dict[str, object] = {"entries": None}

        def _parse_compare_socket_xml(text: str, source_path: str) -> Tuple[AttachmentSocketInfo, ...]:
            try:
                compare_root = ET.fromstring(str(text or ""))
            except Exception:
                return ()
            sockets: List[AttachmentSocketInfo] = []
            for element in compare_root.iter():
                local_name = str(element.tag).rsplit("}", 1)[-1]
                if local_name != "Socket":
                    continue
                if not ("Name" in element.attrib or "Translation" in element.attrib or "Rotation" in element.attrib):
                    continue
                sockets.append(
                    AttachmentSocketInfo(
                        name=str(element.attrib.get("Name", "") or "").strip(),
                        parent=str(element.attrib.get("Parent", "") or "").strip(),
                        translation=self._parse_attachment_transform_values(str(element.attrib.get("Translation", "") or ""), 3),
                        rotation=self._parse_attachment_transform_values(str(element.attrib.get("Rotation", "") or ""), 4),
                        source_path=source_path,
                    )
                )
            return tuple(sockets)

        def _format_transform_display(values: Sequence[float], expected_count: int) -> str:
            if len(tuple(values or ())) != expected_count:
                return "-"
            return " ".join(_component_text(float(value)) for value in tuple(values or ()))

        def _current_socket_index_by_name() -> Dict[str, Tuple[int, ET.Element]]:
            result: Dict[str, Tuple[int, ET.Element]] = {}
            for index, element in enumerate(socket_elements):
                name = str(element.attrib.get("Name", "") or "").strip()
                if name:
                    result[name.casefold()] = (index, element)
            return result

        def _socket_item_for_index(target_index: int) -> Optional[QTreeWidgetItem]:
            for row in range(socket_tree.topLevelItemCount()):
                item = socket_tree.topLevelItem(row)
                if item is not None and item.data(0, Qt.UserRole) == target_index:
                    return item
            return None

        def _values_close(first: Sequence[float], second: Sequence[float]) -> bool:
            first_values = tuple(first or ())
            second_values = tuple(second or ())
            if len(first_values) != len(second_values):
                return False
            return all(abs(float(left) - float(right)) <= 0.00001 for left, right in zip(first_values, second_values))

        def _refresh_compare_copy_buttons() -> None:
            item = compare_tree.currentItem()
            other_socket = item.data(0, Qt.UserRole) if item is not None else None
            target_index = item.data(1, Qt.UserRole) if item is not None else None
            has_other_socket = isinstance(other_socket, AttachmentSocketInfo)
            compare_copy_matching_button.setEnabled(has_other_socket and isinstance(target_index, int))
            compare_copy_selected_button.setEnabled(has_other_socket and _selected_element()[1] is not None)

        def _refresh_compare_tree() -> None:
            compare_tree.clear()
            compare_sockets = tuple(compare_state.get("sockets") or ())
            source_label = str(compare_state.get("source") or "").strip()
            if not compare_sockets:
                compare_source_label.setText("Compare source: none loaded")
                _refresh_compare_copy_buttons()
                return
            compare_source_label.setText(
                f"Compare source: {source_label or 'loaded XML'} ({len(compare_sockets)} socket row(s))"
            )
            current_by_name = _current_socket_index_by_name()
            compare_by_name: Dict[str, AttachmentSocketInfo] = {}
            ordered_names: List[str] = []
            ordered_keys: set[str] = set()
            for element in socket_elements:
                name = str(element.attrib.get("Name", "") or "").strip()
                key = name.casefold()
                if name and key not in ordered_keys:
                    ordered_names.append(name)
                    ordered_keys.add(key)
            for socket in compare_sockets:
                if not isinstance(socket, AttachmentSocketInfo):
                    continue
                name = str(socket.name or "").strip()
                if not name:
                    continue
                key = name.casefold()
                compare_by_name[key] = socket
                if key not in ordered_keys:
                    ordered_names.append(name)
                    ordered_keys.add(key)
            for name in ordered_names:
                key = name.casefold()
                current_pair = current_by_name.get(key)
                other_socket = compare_by_name.get(key)
                current_index: object = None
                current_parent_raw = ""
                current_parent = "-"
                current_translation_text = "-"
                current_rotation_text = "-"
                if current_pair is not None:
                    current_index, current_element = current_pair
                    current_parent_raw = str(current_element.attrib.get("Parent", "") or "").strip()
                    current_parent = current_parent_raw or "-"
                    current_translation, current_rotation = _socket_transform_values(current_element)
                    current_translation_text = _format_transform_display(current_translation, 3)
                    current_rotation_text = _format_transform_display(current_rotation, 4)
                compare_parent_raw = (
                    str(getattr(other_socket, "parent", "") or "").strip()
                    if isinstance(other_socket, AttachmentSocketInfo)
                    else ""
                )
                compare_parent = compare_parent_raw or "-"
                compare_translation = getattr(other_socket, "translation", ()) if isinstance(other_socket, AttachmentSocketInfo) else ()
                compare_rotation = getattr(other_socket, "rotation", ()) if isinstance(other_socket, AttachmentSocketInfo) else ()
                compare_translation_text = _format_transform_display(compare_translation, 3)
                compare_rotation_text = _format_transform_display(compare_rotation, 4)
                if current_pair is None:
                    status = "Only in compare XML"
                elif other_socket is None:
                    status = "Only in current XML"
                else:
                    differences: List[str] = []
                    if current_parent_raw != compare_parent_raw:
                        differences.append("parent")
                    if not _values_close(current_translation, compare_translation):
                        differences.append("translation")
                    if not _values_close(current_rotation, compare_rotation):
                        differences.append("rotation")
                    status = "Same" if not differences else "Different: " + ", ".join(differences)
                item = QTreeWidgetItem(
                    [
                        name,
                        current_parent,
                        compare_parent,
                        current_translation_text,
                        compare_translation_text,
                        current_rotation_text,
                        compare_rotation_text,
                        status,
                        source_label,
                    ]
                )
                item.setData(0, Qt.UserRole, other_socket)
                item.setData(1, Qt.UserRole, current_index)
                if status == "Same":
                    item.setForeground(7, QBrush(QColor("#86efac")))
                elif status.startswith("Different"):
                    item.setForeground(7, QBrush(QColor("#fde68a")))
                else:
                    item.setForeground(7, QBrush(QColor("#67e8f9")))
                for column in range(compare_tree.columnCount()):
                    item.setToolTip(column, item.text(column))
                compare_tree.addTopLevelItem(item)
            for column in range(compare_tree.columnCount()):
                compare_tree.resizeColumnToContents(column)
            _refresh_compare_copy_buttons()

        def _archive_socket_xml_candidates() -> Tuple[ArchiveEntry, ...]:
            cached = socket_xml_candidate_cache.get("entries")
            if isinstance(cached, tuple):
                return cached
            candidates: List[ArchiveEntry] = []
            seen: set[Tuple[str, str, int]] = set()
            for basename, entries in self.archive_entries_by_basename.items():
                normalized_basename = str(basename or "").casefold()
                if not (
                    normalized_basename.endswith(".sockets.xml")
                    or (normalized_basename.endswith(".xml") and "socket" in normalized_basename)
                ):
                    continue
                for candidate in entries or ():
                    if not isinstance(candidate, ArchiveEntry) or self._same_archive_entry(candidate, socket_entry):
                        continue
                    candidate_path = str(candidate.path or "").replace("\\", "/")
                    path_key = candidate_path.casefold()
                    if not (path_key.endswith(".sockets.xml") or ("socketbonedata" in path_key and path_key.endswith(".xml"))):
                        continue
                    key = (
                        path_key,
                        str(candidate.pamt_path).strip().casefold(),
                        int(candidate.offset),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(candidate)
            candidates.sort(key=lambda entry: str(entry.path or "").casefold())
            cached_candidates = tuple(candidates)
            socket_xml_candidate_cache["entries"] = cached_candidates
            return cached_candidates

        def _load_compare_sockets(source_text: str, source_path: str, entry: Optional[ArchiveEntry] = None) -> None:
            sockets = _parse_compare_socket_xml(source_text, source_path)
            if not sockets:
                QMessageBox.warning(dialog, "Compare Socket XML", "No socket rows were found in the selected XML.")
                return
            compare_state["source"] = source_path
            compare_state["sockets"] = sockets
            compare_state["entry"] = entry
            _refresh_compare_tree()
            editor_tabs.setCurrentWidget(compare_page)

        def _load_compare_archive_entry(entry: ArchiveEntry) -> None:
            try:
                data, _decompressed, _note = read_archive_entry_data(entry)
            except Exception as exc:
                QMessageBox.warning(dialog, "Compare Socket XML", f"Could not read compare socket XML:\n{exc}")
                return
            _load_compare_sockets(decode_xml_text_payload(data).text, entry.path, entry)

        def _open_archive_socket_compare_picker() -> None:
            picker = QDialog(dialog)
            picker.setWindowTitle("Load Archive Socket XML To Compare")
            picker.resize(920, 520)
            picker_layout = QVBoxLayout(picker)
            picker_layout.setContentsMargins(10, 10, 10, 10)
            picker_layout.setSpacing(8)
            picker_hint = QLabel(
                "Search uses the cached Archive Browser basename index. Pick a .sockets.xml descriptor to compare against the current file."
            )
            picker_hint.setObjectName("HintLabel")
            picker_hint.setWordWrap(True)
            picker_layout.addWidget(picker_hint)
            picker_search = QLineEdit()
            picker_search.setPlaceholderText("Search socket XML by weapon name, folder, or full archive path...")
            picker_layout.addWidget(picker_search)
            picker_tree = QTreeWidget()
            picker_tree.setColumnCount(4)
            picker_tree.setHeaderLabels(["Socket XML", "Folder", "Package", "Path"])
            picker_tree.setRootIsDecorated(False)
            picker_tree.setAlternatingRowColors(True)
            picker_tree.setUniformRowHeights(True)
            picker_tree.setSelectionMode(QAbstractItemView.SingleSelection)
            picker_layout.addWidget(picker_tree, 1)
            picker_status = QLabel("")
            picker_status.setObjectName("HintLabel")
            picker_layout.addWidget(picker_status)
            picker_buttons = QHBoxLayout()
            picker_load_button = QPushButton("Load Compare XML")
            picker_cancel_button = QPushButton("Cancel")
            picker_load_button.setEnabled(False)
            picker_buttons.addStretch(1)
            picker_buttons.addWidget(picker_load_button)
            picker_buttons.addWidget(picker_cancel_button)
            picker_layout.addLayout(picker_buttons)
            selected: Dict[str, object] = {}
            target_folder = PurePosixPath(socket_entry.path.replace("\\", "/")).parent.as_posix().casefold()

            def _candidate_score(candidate: ArchiveEntry, terms: Sequence[str]) -> int:
                path = str(candidate.path or "").replace("\\", "/").casefold()
                basename = PurePosixPath(path).name
                score = 0
                if target_folder and PurePosixPath(path).parent.as_posix().casefold() == target_folder:
                    score += 120
                if "/weapon/" in path:
                    score += 40
                if basename.endswith(".sockets.xml"):
                    score += 25
                if terms and all(term in path for term in terms):
                    score += 30
                return score

            def _refresh_picker() -> None:
                picker_tree.clear()
                raw_query = picker_search.text().strip().casefold()
                terms = tuple(term for term in re.split(r"[\s/\\]+", raw_query) if term)
                matches: List[Tuple[int, ArchiveEntry]] = []
                for candidate in _archive_socket_xml_candidates():
                    path = str(candidate.path or "").replace("\\", "/")
                    haystack = " ".join((candidate.basename, path, str(candidate.package_label or ""))).casefold()
                    if terms and not all(term in haystack for term in terms):
                        continue
                    matches.append((_candidate_score(candidate, terms), candidate))
                matches.sort(key=lambda pair: (-pair[0], str(pair[1].path or "").casefold()))
                for _score, candidate in matches[:500]:
                    path = str(candidate.path or "").replace("\\", "/")
                    folder = PurePosixPath(path).parent.as_posix()
                    item = QTreeWidgetItem([candidate.basename, folder, str(candidate.package_label or ""), path])
                    item.setData(0, Qt.UserRole, candidate)
                    for column in range(picker_tree.columnCount()):
                        item.setToolTip(column, item.text(column))
                    picker_tree.addTopLevelItem(item)
                for column in range(picker_tree.columnCount()):
                    picker_tree.resizeColumnToContents(column)
                total = len(matches)
                shown = min(total, 500)
                picker_status.setText(f"{shown:,} shown, {total:,} matched from cached socket XML candidates.")
                if picker_tree.topLevelItemCount() > 0:
                    picker_tree.setCurrentItem(picker_tree.topLevelItem(0))

            def _update_picker_load_button() -> None:
                item = picker_tree.currentItem()
                picker_load_button.setEnabled(isinstance(item.data(0, Qt.UserRole), ArchiveEntry) if item is not None else False)

            def _accept_picker() -> None:
                item = picker_tree.currentItem()
                entry = item.data(0, Qt.UserRole) if item is not None else None
                if isinstance(entry, ArchiveEntry):
                    selected["entry"] = entry
                    picker.accept()

            picker_tree.currentItemChanged.connect(lambda _current, _previous: _update_picker_load_button())
            picker_tree.itemDoubleClicked.connect(lambda _item, _column: _accept_picker())
            picker_search.textChanged.connect(lambda _text: _refresh_picker())
            picker_load_button.clicked.connect(_accept_picker)
            picker_cancel_button.clicked.connect(picker.reject)
            _refresh_picker()
            if picker.exec() == QDialog.Accepted:
                entry = selected.get("entry")
                if isinstance(entry, ArchiveEntry):
                    _load_compare_archive_entry(entry)

        def _open_loose_socket_compare_file() -> None:
            selected_path, _selected_filter = QFileDialog.getOpenFileName(
                dialog,
                "Open Loose Socket XML To Compare",
                str(Path.home()),
                "Socket XML (*.sockets.xml *.xml);;All Files (*)",
            )
            if not selected_path:
                return
            source_path = Path(selected_path)
            try:
                text = decode_xml_text_payload(source_path.read_bytes()).text
            except Exception as exc:
                QMessageBox.warning(dialog, "Compare Socket XML", f"Could not read socket XML:\n{exc}")
                return
            _load_compare_sockets(text, str(source_path), None)

        def _copy_compare_values(*, use_selected_socket: bool) -> None:
            item = compare_tree.currentItem()
            other_socket = item.data(0, Qt.UserRole) if item is not None else None
            if not isinstance(other_socket, AttachmentSocketInfo):
                QMessageBox.information(dialog, "Compare Socket XML", "Select a compare row that exists in the loaded XML.")
                return
            target_item: Optional[QTreeWidgetItem]
            target_element: Optional[ET.Element]
            if use_selected_socket:
                target_item, target_element = _selected_element()
            else:
                target_index = item.data(1, Qt.UserRole)
                if not isinstance(target_index, int):
                    QMessageBox.information(
                        dialog,
                        "Compare Socket XML",
                        "This socket name does not exist in the current XML. Select a target socket and use Copy To Selected Socket.",
                    )
                    return
                target_item = _socket_item_for_index(target_index)
                target_element = socket_elements[target_index] if 0 <= target_index < len(socket_elements) else None
            if target_item is None or target_element is None:
                QMessageBox.information(dialog, "Compare Socket XML", "Select a current socket to receive the copied values.")
                return
            copied: List[str] = []
            if len(tuple(other_socket.translation or ())) == 3:
                target_element.set("Translation", self._format_attachment_transform_values(other_socket.translation))
                copied.append("translation")
            if len(tuple(other_socket.rotation or ())) == 4:
                target_element.set("Rotation", self._format_attachment_transform_values(other_socket.rotation))
                copied.append("rotation")
            if compare_include_parent_checkbox.isChecked():
                target_element.set("Parent", str(other_socket.parent or ""))
                copied.append("parent")
            if not copied:
                QMessageBox.information(dialog, "Compare Socket XML", "The compare row has no usable transform values to copy.")
                return
            dirty["value"] = True
            _refresh_item_text(target_item, target_element)
            socket_tree.setCurrentItem(target_item)
            _load_selected_socket()
            _refresh_preview()
            _refresh_compare_tree()
            self.set_status_message(
                f"Copied {', '.join(copied)} from {other_socket.name or 'compare socket'} into {target_element.attrib.get('Name', '') or 'selected socket'}."
            )

        compare_archive_button.clicked.connect(_open_archive_socket_compare_picker)
        compare_loose_button.clicked.connect(_open_loose_socket_compare_file)
        compare_copy_matching_button.clicked.connect(lambda _checked=False: _copy_compare_values(use_selected_socket=False))
        compare_copy_selected_button.clicked.connect(lambda _checked=False: _copy_compare_values(use_selected_socket=True))
        compare_tree.currentItemChanged.connect(lambda _current, _previous: _refresh_compare_copy_buttons())
        socket_tree.currentItemChanged.connect(lambda _current, _previous: _refresh_compare_copy_buttons())

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        write_button = QPushButton("Write Loose Socket XML...")
        close_button = QPushButton("Close")
        button_row.addStretch(1)
        button_row.addWidget(write_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        def _write_loose_socket_xml() -> None:
            _apply_selected_values()
            payload_text = self._attachment_socket_xml_text(root, include_declaration=include_declaration)
            if not dirty["value"]:
                QMessageBox.information(dialog, "Socket XML Editor", "No socket changes have been made.")
                return
            target_settings = self._collect_archive_mod_ready_export_target(
                browse_title="Choose Socket XML Loose Mod Export Root",
                prompt_for_metadata=True,
                dialog_title="Write Loose Socket XML",
                allow_dmm_texture_structure=False,
            )
            if target_settings is None:
                return
            export_root, package_info, create_no_encrypt_file, _include_related, export_options = target_settings
            request = ArchivePatchRequest(socket_entry, encode_xml_text_like_source(payload_text, decoded_socket_xml))

            def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
                log(f"Writing edited socket XML for {socket_entry.path}...")
                return export_archive_payloads_to_mod_ready_loose(
                    (request,),
                    parent_root=export_root,
                    package_info=package_info,
                    export_options=export_options,
                    create_no_encrypt_file=create_no_encrypt_file,
                    on_log=log,
                )

            def _handle_complete(result: object) -> None:
                if isinstance(result, ArchiveLooseExportResult):
                    QMessageBox.information(
                        dialog,
                        "Socket XML Export Complete",
                        f"Wrote edited socket XML loose package:\n{result.package_root}",
                    )
                    self.set_status_message(f"Wrote loose socket XML package for {socket_entry.basename}.")
                    dialog.accept()
                else:
                    self.set_status_message("Socket XML export finished with an unexpected result payload.", error=True)

            self._run_utility_task(
                status_message=f"Writing loose socket XML for {socket_entry.basename}...",
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        write_button.clicked.connect(_write_loose_socket_xml)
        close_button.clicked.connect(dialog.accept)
        _refresh_preview()
        if socket_tree.topLevelItemCount() > 0:
            socket_tree.setCurrentItem(socket_tree.topLevelItem(0))
            _load_selected_socket()
        dialog.exec()
