"""HKX Physics Editor: plain-language view and proven edits of one HKX file.

The dialog only collects edits. Reading, building and saving run in the
archive browser's utility worker (``hkx_physics_editor_actions``); the dialog
receives results through ``set_replacement`` and ``show_saved`` and ignores
them once it has been closed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Dict, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.archive_hkx_joint_limits import (
    HINGE_CLASS,
    RAGDOLL_CLASS,
    HkxJoint,
    HkxJointField,
)
from cdmw.services.active_ui_translation import translate_active_ui_text
from cdmw.services.hkx_physics_editor_service import (
    KIND_COLLISION,
    KIND_PHYSICS_SYSTEM,
    KIND_RAGDOLL,
    HkxPhysicsEditResult,
    HkxPhysicsEdits,
    HkxPhysicsSession,
    joint_display_name,
)
from cdmw.ui.display_scaling import fit_window_to_screen

_ORIGINAL_ROLE = int(Qt.ItemDataRole.UserRole)


def joint_type_text(joint: HkxJoint) -> str:
    labels = {
        RAGDOLL_CLASS: translate_active_ui_text("Ragdoll joint"),
        HINGE_CLASS: translate_active_ui_text("Hinge"),
        "hknpHingeConstraintData": translate_active_ui_text("Free hinge"),
        "hknpBallAndSocketConstraintData": translate_active_ui_text("Ball joint"),
        "hknpFixedConstraintData": translate_active_ui_text("Fixed joint"),
        "hknpWheelConstraintData": translate_active_ui_text("Wheel"),
    }
    text = labels.get(joint.class_name, joint.class_name or translate_active_ui_text("Unknown joint"))
    return translate_active_ui_text(f"{text} (breakable)") if joint.breakable else text


def joint_field_text(key: str) -> str:
    return {
        "bend_min": translate_active_ui_text("Bend minimum"),
        "bend_max": translate_active_ui_text("Bend maximum"),
        "twist_min": translate_active_ui_text("Twist minimum"),
        "twist_max": translate_active_ui_text("Twist maximum"),
        "cone_max": translate_active_ui_text("Swing"),
        "plane_min": translate_active_ui_text("Side swing minimum"),
        "plane_max": translate_active_ui_text("Side swing maximum"),
        "friction": translate_active_ui_text("Stiffness (friction)"),
    }.get(key, key)


def joint_field_help(key: str) -> str:
    if key.startswith("bend"):
        return translate_active_ui_text("How far this hinge bends, in degrees. A knee or elbow moves between the minimum and the maximum.")
    if key.startswith("twist"):
        return translate_active_ui_text("How far the limb can twist around its own length, in degrees.")
    if key == "cone_max":
        return translate_active_ui_text("How far the limb can swing away from its rest direction, in degrees.")
    if key.startswith("plane"):
        return translate_active_ui_text("The swing range across the joint, in degrees; 90 degrees is straight.")
    return translate_active_ui_text("How strongly the joint resists moving. Higher values make the limb stiffer; 0 lets it swing freely.")


def name_role_text(role: str) -> str:
    return {
        "bone": translate_active_ui_text("Bone"),
        "body": translate_active_ui_text("Body"),
        "joint": translate_active_ui_text("Joint"),
        "material": translate_active_ui_text("Material"),
        "section": translate_active_ui_text("File section"),
        "skeleton": translate_active_ui_text("Skeleton"),
        "ragdoll": translate_active_ui_text("Ragdoll"),
        "shape": translate_active_ui_text("Shape"),
    }.get(role, translate_active_ui_text("Other"))


def shape_class_text(class_name: str) -> str:
    return {
        "hknpConvexShape": translate_active_ui_text("Convex hulls"),
        "hknpBoxShape": translate_active_ui_text("Boxes"),
        "hknpCapsuleShape": translate_active_ui_text("Capsules"),
        "hknpSphereShape": translate_active_ui_text("Spheres"),
        "hknpCylinderShape": translate_active_ui_text("Cylinders"),
        "hknpTriangleShape": translate_active_ui_text("Triangles"),
        "hknpMeshShape": translate_active_ui_text("Triangle meshes"),
    }.get(class_name, class_name)


def overview_text(session: HkxPhysicsSession) -> str:
    if session.codec_status != "exact":
        return translate_active_ui_text(
            f"CDMW cannot rebuild this file safely, so it opens read-only. Reason: {session.codec_message}"
        )
    joints = len(session.joints)
    editable = session.editable_joint_count
    if session.kind == KIND_RAGDOLL:
        lead = translate_active_ui_text(
            f"Ragdoll physics for a character, with {joints} joints ({editable} adjustable). Use Joints to change how far each joint bends, twists and swings, and how stiff it is."
        )
    elif session.kind == KIND_PHYSICS_SYSTEM:
        lead = translate_active_ui_text(
            f"A physics system such as a rope, chain or moving part, with {joints} joints ({editable} adjustable). Use Joints to change their limits and stiffness."
        )
    elif session.kind == KIND_COLLISION:
        lead = translate_active_ui_text(
            "Collision shapes for an item or world object. Use Collision to give it the collision of another file. Changing the shapes themselves is not supported yet."
        )
    else:
        lead = translate_active_ui_text("This HKX file has no physics that CDMW can edit.")
    tail = translate_active_ui_text(
        "Saving writes a separate HKX file or a DMM mod folder; the game archives are never changed. Edited physics has not been tested in game, so keep a copy of the original mod and test one change at a time."
    )
    return f"{lead}\n\n{tail}"


class HkxPhysicsEditorDialog(QDialog):
    """Collects joint, name and collision edits for one HKX file."""

    def __init__(
        self,
        parent: Optional[QWidget],
        session: HkxPhysicsSession,
        *,
        on_save_mod: Callable[["HkxPhysicsEditorDialog", HkxPhysicsEdits], None],
        on_save_file: Callable[["HkxPhysicsEditorDialog", HkxPhysicsEdits], None],
        on_pick_replacement: Optional[Callable[["HkxPhysicsEditorDialog"], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.closed = False
        self._on_save_mod = on_save_mod
        self._on_save_file = on_save_file
        self._on_pick_replacement = on_pick_replacement
        self._joint_values: Dict[Tuple[int, str], float] = {}
        self._renames: Dict[int, str] = {}
        self._replacement: Optional[Tuple[str, bytes]] = None
        self._joint_spins: Dict[str, QDoubleSpinBox] = {}
        self._current_joint: Optional[HkxJoint] = None
        self._loading_form = False
        self.setWindowTitle(f"HKX Physics Editor - {session.path.rsplit('/', 1)[-1]}")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(980, 680)

        layout = QVBoxLayout(self)
        path_label = QLabel(session.path)
        path_label.setObjectName("HintLabel")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path_label)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_overview_tab()
        if session.editable and session.joints:
            self._build_joints_tab()
        if session.editable and session.names:
            self._build_names_tab()
        if session.editable and session.kind == KIND_COLLISION:
            self._build_collision_tab()

        footer = QHBoxLayout()
        self.changes_label = QLabel()
        footer.addWidget(self.changes_label, 1)
        self.reset_button = QPushButton("Reset All Changes")
        self.reset_button.clicked.connect(self._reset_all)
        self.save_file_button = QPushButton("Save HKX File...")
        self.save_file_button.setToolTip("Write the edited file to a folder you choose.")
        self.save_file_button.clicked.connect(lambda: self._request_save(self._on_save_file))
        self.save_mod_button = QPushButton("Save as DMM Mod...")
        self.save_mod_button.setToolTip("Write a DMM mod folder that replaces this file in game.")
        self.save_mod_button.clicked.connect(lambda: self._request_save(self._on_save_mod))
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        for button in (self.reset_button, self.save_file_button, self.save_mod_button, close_button):
            footer.addWidget(button)
        layout.addLayout(footer)
        self._refresh_changes()
        fit_window_to_screen(self)

    # Tabs -------------------------------------------------------------------------------

    def _build_overview_tab(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        self.overview_label = QLabel(overview_text(self.session))
        self.overview_label.setWordWrap(True)
        self.overview_label.setTextFormat(Qt.TextFormat.PlainText)
        page_layout.addWidget(self.overview_label)
        if self.session.editable:
            steps = QLabel(
                "How to make a mod:\n"
                "1. Change values on the other tabs. The shipped value is shown next to each one.\n"
                "2. Click Save as DMM Mod and choose a folder and a mod name.\n"
                "3. In DMM, enable the mod and click Mount, then test it in game.\n"
                "4. To undo it, disable the mod in DMM."
            )
            steps.setWordWrap(True)
            steps.setTextFormat(Qt.TextFormat.PlainText)
            page_layout.addWidget(steps)
        facts = QFormLayout()
        facts.addRow(QLabel("Joints:"), QLabel(str(len(self.session.joints))))
        facts.addRow(QLabel("Renameable names:"), QLabel(str(len(self.session.names))))
        if self.session.collision is not None:
            pieces = ", ".join(f"{shape_class_text(name)}: {count}" for name, count in self.session.collision.pieces)
            facts.addRow(QLabel("Collision pieces:"), QLabel(pieces or "-"))
        page_layout.addLayout(facts)
        page_layout.addStretch(1)
        self.tabs.addTab(page, "Overview")

    def _build_joints_tab(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        intro = QLabel(
            "Pick a joint to see its limits. Angles are in degrees. Changed joints are marked with an asterisk."
        )
        intro.setWordWrap(True)
        page_layout.addWidget(intro)
        bulk = QHBoxLayout()
        bulk.addWidget(QLabel("Stiffness of every joint:"))
        self.stiffness_factor = QDoubleSpinBox()
        self.stiffness_factor.setRange(0.0, 20.0)
        self.stiffness_factor.setSingleStep(0.25)
        self.stiffness_factor.setDecimals(2)
        self.stiffness_factor.setValue(1.0)
        self.stiffness_factor.setPrefix("x ")
        self.stiffness_factor.setToolTip("Multiplies each joint's shipped friction. Below 1 makes the ragdoll looser, above 1 stiffer.")
        bulk.addWidget(self.stiffness_factor)
        apply_stiffness = QPushButton("Apply to All Joints")
        apply_stiffness.clicked.connect(lambda: self.apply_stiffness_factor(self.stiffness_factor.value()))
        bulk.addWidget(apply_stiffness)
        bulk.addStretch(1)
        page_layout.addLayout(bulk)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.joint_filter = QLineEdit()
        self.joint_filter.setPlaceholderText("Filter joints")
        self.joint_filter.textChanged.connect(self._filter_joints)
        left_layout.addWidget(self.joint_filter)
        self.joint_tree = QTreeWidget()
        self.joint_tree.setHeaderLabels(["Joint", "Type"])
        self.joint_tree.setRootIsDecorated(False)
        self.joint_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for joint in self.session.joints:
            item = QTreeWidgetItem([joint_display_name(joint), joint_type_text(joint)])
            item.setData(0, _ORIGINAL_ROLE, joint.index)
            item.setToolTip(0, f"{joint.child_body}\n{joint.parent_body}\n{joint.name}".strip())
            self.joint_tree.addTopLevelItem(item)
        self.joint_tree.currentItemChanged.connect(lambda current, _previous: self._show_joint(current))
        left_layout.addWidget(self.joint_tree, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.joint_title = QLabel()
        self.joint_title.setObjectName("SectionTitle")
        self.joint_title.setWordWrap(True)
        right_layout.addWidget(self.joint_title)
        self.joint_note = QLabel()
        self.joint_note.setObjectName("HintLabel")
        self.joint_note.setWordWrap(True)
        right_layout.addWidget(self.joint_note)
        self.joint_form = QFormLayout()
        right_layout.addLayout(self.joint_form)
        self.reset_joint_button = QPushButton("Reset This Joint")
        self.reset_joint_button.clicked.connect(self._reset_current_joint)
        right_layout.addWidget(self.reset_joint_button, 0, Qt.AlignmentFlag.AlignLeft)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        page_layout.addWidget(splitter, 1)
        self.tabs.addTab(page, "Joints")
        if self.joint_tree.topLevelItemCount():
            self.joint_tree.setCurrentItem(self.joint_tree.topLevelItem(0))

    def _build_names_tab(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        warning = QLabel(
            "Type a new name in the right-hand column. The game looks some of these names up, so a renamed file section, "
            "skeleton or bone can stop the file from working. Rename only to match a bone you renamed elsewhere."
        )
        warning.setWordWrap(True)
        page_layout.addWidget(warning)
        self.names_table = QTableWidget(len(self.session.names), 3)
        self.names_table.setHorizontalHeaderLabels(["Used for", "Name", "New name"])
        self.names_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.names_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.names_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for row, name in enumerate(self.session.names):
            role = QTableWidgetItem(name_role_text(name.role))
            role.setFlags(role.flags() & ~Qt.ItemFlag.ItemIsEditable)
            current = QTableWidgetItem(name.text)
            current.setFlags(current.flags() & ~Qt.ItemFlag.ItemIsEditable)
            new = QTableWidgetItem(name.text)
            new.setData(_ORIGINAL_ROLE, name.item)
            for column, cell in enumerate((role, current, new)):
                self.names_table.setItem(row, column, cell)
        self.names_table.itemChanged.connect(self._name_changed)
        page_layout.addWidget(self.names_table, 1)
        self.tabs.addTab(page, "Names")

    def _build_collision_tab(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        intro = QLabel(
            "To give this item or object the collision of another one, choose a collision file of the same kind. "
            "The whole file is copied as shipped, so its shapes stay valid; the copy keeps the other file's outline."
        )
        intro.setWordWrap(True)
        page_layout.addWidget(intro)
        collision = self.session.collision
        if collision is not None:
            pieces = ", ".join(f"{shape_class_text(name)}: {count}" for name, count in collision.pieces) or "-"
            summary = QLabel(translate_active_ui_text(f"This file holds: {pieces}."))
            summary.setWordWrap(True)
            page_layout.addWidget(summary)
        row = QHBoxLayout()
        self.pick_replacement_button = QPushButton("Use Another File's Collision...")
        self.pick_replacement_button.setEnabled(self._on_pick_replacement is not None)
        self.pick_replacement_button.clicked.connect(lambda: self._on_pick_replacement(self) if self._on_pick_replacement else None)
        self.clear_replacement_button = QPushButton("Keep Original Collision")
        self.clear_replacement_button.clicked.connect(lambda: self.set_replacement(None, None))
        row.addWidget(self.pick_replacement_button)
        row.addWidget(self.clear_replacement_button)
        row.addStretch(1)
        page_layout.addLayout(row)
        self.replacement_label = QLabel()
        self.replacement_label.setWordWrap(True)
        page_layout.addWidget(self.replacement_label)
        page_layout.addStretch(1)
        self.tabs.addTab(page, "Collision")
        self._refresh_replacement()

    # Joints -----------------------------------------------------------------------------

    def _joint_by_index(self, index: int) -> Optional[HkxJoint]:
        return next((joint for joint in self.session.joints if joint.index == index), None)

    def _filter_joints(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self.joint_tree.topLevelItemCount()):
            item = self.joint_tree.topLevelItem(row)
            haystack = f"{item.text(0)} {item.text(1)} {item.toolTip(0)}".casefold()
            item.setHidden(bool(needle) and needle not in haystack)

    def _field_value(self, joint: HkxJoint, field: HkxJointField) -> float:
        return self._joint_values.get((joint.data_item, field.key), field.value)

    def _show_joint(self, item: Optional[QTreeWidgetItem]) -> None:
        joint = self._joint_by_index(int(item.data(0, _ORIGINAL_ROLE))) if item is not None else None
        self._current_joint = joint
        self._loading_form = True
        while self.joint_form.rowCount():
            self.joint_form.removeRow(0)
        self._joint_spins.clear()
        if joint is None:
            self.joint_title.setText("")
            self.joint_note.setText("")
            self._loading_form = False
            return
        self.joint_title.setText(f"{joint_display_name(joint)} ({joint_type_text(joint)})")
        if joint.note or not joint.fields:
            self.joint_note.setText(translate_active_ui_text("This joint type has no adjustable limits."))
        elif joint.name:
            self.joint_note.setText(translate_active_ui_text(f"Name in file: {joint.name}"))
        else:
            self.joint_note.setText("")
        for field in joint.fields:
            spin = QDoubleSpinBox()
            spin.setDecimals(1 if field.key != "friction" else 2)
            spin.setRange(field.minimum, field.maximum)
            if field.key != "friction":
                spin.setSuffix("°")
            spin.setValue(self._field_value(joint, field))
            spin.setEnabled(field.editable)
            spin.setToolTip(joint_field_help(field.key) if field.editable else field.reason)
            spin.valueChanged.connect(lambda value, key=field.key: self._joint_value_changed(key, value))
            shipped = QLabel(translate_active_ui_text(f"Shipped: {self._format(field.key, field.value)}"))
            shipped.setObjectName("HintLabel")
            row = QHBoxLayout()
            row.addWidget(spin)
            row.addWidget(shipped)
            row.addStretch(1)
            label = QLabel(joint_field_text(field.key))
            label.setToolTip(joint_field_help(field.key))
            self.joint_form.addRow(label, row)
            self._joint_spins[field.key] = spin
        self.reset_joint_button.setEnabled(any(field.editable for field in joint.fields))
        self._loading_form = False

    @staticmethod
    def _format(key: str, value: float) -> str:
        return f"{value:g}" if key == "friction" else f"{value:.1f}°"

    def _joint_value_changed(self, key: str, value: float) -> None:
        joint = self._current_joint
        if self._loading_form or joint is None:
            return
        field = next(item for item in joint.fields if item.key == key)
        if abs(value - round(field.value, 1 if key != "friction" else 2)) < 1e-9:
            self._joint_values.pop((joint.data_item, key), None)
        else:
            self._joint_values[(joint.data_item, key)] = float(value)
        self._mark_joint_items()
        self._refresh_changes()

    def apply_stiffness_factor(self, factor: float) -> int:
        """Set every editable friction to shipped x ``factor``; returns how many joints changed."""

        changed = 0
        for joint in self.session.joints:
            field = next((item for item in joint.fields if item.key == "friction" and item.editable), None)
            if field is None:
                continue
            value = min(field.maximum, max(field.minimum, round(field.value * factor, 2)))
            if abs(value - round(field.value, 2)) < 1e-9:
                self._joint_values.pop((joint.data_item, "friction"), None)
            else:
                self._joint_values[(joint.data_item, "friction")] = value
                changed += 1
        self._show_joint(self.joint_tree.currentItem())
        self._mark_joint_items()
        self._refresh_changes()
        return changed

    def _mark_joint_items(self) -> None:
        changed = {item for item, _key in self._joint_values}
        for row in range(self.joint_tree.topLevelItemCount()):
            item = self.joint_tree.topLevelItem(row)
            joint = self._joint_by_index(int(item.data(0, _ORIGINAL_ROLE)))
            base = joint_display_name(joint) if joint else item.text(0)
            item.setText(0, f"* {base}" if joint is not None and joint.data_item in changed else base)

    def _reset_current_joint(self) -> None:
        joint = self._current_joint
        if joint is None:
            return
        for key in [key for item, key in self._joint_values if item == joint.data_item]:
            self._joint_values.pop((joint.data_item, key), None)
        self._show_joint(self.joint_tree.currentItem())
        self._mark_joint_items()
        self._refresh_changes()

    # Names and collision ----------------------------------------------------------------

    def _name_changed(self, cell: QTableWidgetItem) -> None:
        if cell.column() != 2:
            return
        item = int(cell.data(_ORIGINAL_ROLE))
        original = next(name.text for name in self.session.names if name.item == item)
        text = cell.text()
        if text == original or not text.strip():
            self._renames.pop(item, None)
        else:
            self._renames[item] = text
        self._refresh_changes()

    def set_replacement(self, path: Optional[str], data: Optional[bytes]) -> None:
        """Called by the worker once a chosen replacement passed its checks (or None to undo)."""

        if self.closed:
            return
        self._replacement = (path, data) if path and data else None
        self._refresh_replacement()
        self._refresh_changes()

    def _refresh_replacement(self) -> None:
        if not hasattr(self, "replacement_label"):
            return
        if self._replacement is None:
            self.replacement_label.setText(translate_active_ui_text("The original collision is kept."))
        else:
            self.replacement_label.setText(translate_active_ui_text(f"Saving uses the collision of {self._replacement[0]}."))
        self.clear_replacement_button.setEnabled(self._replacement is not None)

    # State ------------------------------------------------------------------------------

    def range_problem(self) -> str:
        """Name the first joint whose edited minimum ends up above its maximum, or return ''."""

        for joint in self.session.joints:
            values = {field.key: self._field_value(joint, field) for field in joint.fields}
            for low, high in (("bend_min", "bend_max"), ("twist_min", "twist_max"), ("plane_min", "plane_max")):
                if low in values and high in values and values[low] > values[high] + 1e-6:
                    if (joint.data_item, low) in self._joint_values or (joint.data_item, high) in self._joint_values:
                        return f"{joint_display_name(joint)}: {joint_field_text(low)} > {joint_field_text(high)}"
        return ""

    def _request_save(self, callback: Callable[["HkxPhysicsEditorDialog", HkxPhysicsEdits], None]) -> None:
        problem = self.range_problem()
        if problem:
            QMessageBox.warning(
                self,
                "HKX Physics Editor",
                translate_active_ui_text(f"A minimum is above its maximum. Fix it before saving: {problem}"),
            )
            return
        callback(self, self.collect_edits())

    def collect_edits(self) -> HkxPhysicsEdits:
        if self._replacement is not None:
            return HkxPhysicsEdits(replacement=self._replacement[1], replacement_path=self._replacement[0])
        return HkxPhysicsEdits(joint_values=dict(self._joint_values), renames=dict(self._renames))

    def change_count(self) -> int:
        return 1 if self._replacement is not None else len(self._joint_values) + len(self._renames)

    def _refresh_changes(self) -> None:
        count = self.change_count()
        self.changes_label.setText(
            translate_active_ui_text("No changes yet.") if count == 0 else translate_active_ui_text(f"{count} change(s) ready to save.")
        )
        for button in (self.save_file_button, self.save_mod_button, self.reset_button):
            button.setEnabled(count > 0)
        replacing = self._replacement is not None
        for name in ("joint_tree", "names_table"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(not replacing)

    def _reset_all(self) -> None:
        self._joint_values.clear()
        self._renames.clear()
        self._replacement = None
        if hasattr(self, "names_table"):
            self.names_table.blockSignals(True)
            for row, name in enumerate(self.session.names):
                self.names_table.item(row, 2).setText(name.text)
            self.names_table.blockSignals(False)
        if hasattr(self, "joint_tree"):
            self._show_joint(self.joint_tree.currentItem())
            self._mark_joint_items()
        self._refresh_replacement()
        self._refresh_changes()

    def show_saved(self, result: HkxPhysicsEditResult, destination: str) -> str:
        """Return the summary text for a finished save (the caller shows it)."""

        lines = [translate_active_ui_text(f"Saved to {destination}"), ""]
        for change in result.joint_changes:
            lines.append(
                f"{joint_display_name(change.joint)}: {joint_field_text(change.key)} "
                f"{self._format(change.key, change.old)} -> {self._format(change.key, change.new)}"
            )
        for old, new in result.renames:
            lines.append(f"'{old}' -> '{new}'")
        if result.replaced_with:
            lines.append(translate_active_ui_text(f"Collision copied from {result.replaced_with}"))
        lines.append("")
        lines.append(translate_active_ui_text("The game archives were not changed. Test the result in game before sharing it."))
        return "\n".join(lines)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.closed = True
        super().closeEvent(event)


__all__ = ["HkxPhysicsEditorDialog", "overview_text"]
