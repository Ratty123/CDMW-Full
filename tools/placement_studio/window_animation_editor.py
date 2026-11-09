"""The Edit animation tab: change an animation, or make a new one, and put it in the mod.

Everything here drives `tools.paa_motion.edit`. The tab holds one `ClipEdit` -- a base
clip and the layers on top of it -- and re-renders it in the background after every
change, swapping the result into playback so the character shows it at once. Nothing is
written until the animator chooses Add to Your mod (which replaces one game animation, as
one change in the mod) or exports a file.

Where the base comes from:

* **Edit the animation that is playing** -- whatever the Animations tab last played.
* **Start from this pose** -- a new animation that holds the pose on screen, to key from.
* **Import from Blender** -- a `.glb`/`.gltf` exported here, animated in Blender, and
  exported again (`tools.paa_motion.gltf_import`).

The key timeline above the sections shows the selected bone's pose keys and the selected
hand or foot's reach keys; dragging a key retimes it. While the tab is open, clicking near a
joint in the view picks that bone.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.active_ui_translation import translate_active_ui_text

from .key_timeline import Band, KeyTimeline, Lane
from .model import Quat

#: How long the editor waits after the last change before baking a new preview.
_RENDER_DELAY_MS = 120


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("HintLabel")
    label.setWordWrap(True)
    return label


def _region_label(name: str) -> str:
    """A body region from `tools.paa_motion.edit.body_regions`, in the user's language.

    That module sits outside the localization scan, so its names are spelled out here where
    they are shown.
    """

    labels = {
        "Left arm": translate_active_ui_text("Left arm"),
        "Right arm": translate_active_ui_text("Right arm"),
        "Left leg": translate_active_ui_text("Left leg"),
        "Right leg": translate_active_ui_text("Right leg"),
        "Head and neck": translate_active_ui_text("Head and neck"),
        "Upper body": translate_active_ui_text("Upper body"),
        "Lower body": translate_active_ui_text("Lower body"),
        "Whole body": translate_active_ui_text("Whole body"),
    }
    return labels.get(name, name)


def _limb_label(name: str) -> str:
    """A hand or foot from `tools.paa_motion.edit.limb_ends`, in the user's language."""

    labels = {
        "Left hand": translate_active_ui_text("Left hand"),
        "Right hand": translate_active_ui_text("Right hand"),
        "Left foot": translate_active_ui_text("Left foot"),
        "Right foot": translate_active_ui_text("Right foot"),
    }
    return labels.get(name, name)


def _retimed_keys(keys, frame: int, to: int):
    """`keys` with the one at `frame` moved to `to`, replacing any key already there."""

    from dataclasses import replace

    moved = [replace(key, frame=to) if key.frame == frame else key
             for key in keys if key.frame != to or key.frame == frame]
    return tuple(sorted(moved, key=lambda key: key.frame))


def _explain(message: str) -> str:
    """The motion library's refusals a modder can actually meet, in the user's language."""

    if "distance (LOD) copy" in message:
        return translate_active_ui_text(
            "This is a distance (LOD) copy of an animation. Edit the full animation instead; "
            "the game uses the full one up close.")
    if "matches a bone of this character" in message:
        return translate_active_ui_text(
            "No animated node in the file matches a bone of this character. Export from "
            "Placement & Animations first, and keep the bone names Blender shows.")
    if "has no animation" in message:
        return translate_active_ui_text("The file has no animation in it.")
    return message


def _spin(minimum: float, maximum: float, step: float, decimals: int, suffix: str = "") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setKeyboardTracking(False)
    if suffix:
        box.setSuffix(suffix)
    return box


class AnimationEditorMixin:
    """The Edit animation tab. Mixed into `PlacementStudioWindow`."""

    # ── construction ────────────────────────────────────────────────

    def _build_animation_editor_tab(self) -> QWidget:
        self._clip_edit = None
        self._clip_edit_entry = None
        self._clip_edit_label = ""
        self._clip_edit_target = ""
        self._clip_edit_undo: List[object] = []
        self._clip_edit_rendered = None
        self._clip_edit_rendered_for = None
        self._clip_edit_from_game = False
        self._clip_edit_pending = None
        self._clip_edit_syncing = False
        self._clip_edit_ops: dict = {}
        self._clip_edit_timer = QTimer(self)
        self._clip_edit_timer.setSingleShot(True)
        self._clip_edit_timer.setInterval(_RENDER_DELAY_MS)
        self._clip_edit_timer.timeout.connect(self._render_clip_edit)

        from . import ui_kit as kit

        self._clip_edit_title = QLabel("Nothing to edit yet: play an animation, then start from "
                                       "it here.")
        self._clip_edit_title.setWordWrap(True)
        self._clip_edit_title.setStyleSheet("font-weight: bold;")
        self._edit_playing_button = QPushButton("Playing animation")
        self._edit_playing_button.setToolTip("Edit the animation playing on the character.")
        self._edit_playing_button.clicked.connect(self._start_clip_edit)
        self._new_from_pose_button = QPushButton("This pose")
        self._new_from_pose_button.setToolTip(
            "A new animation that holds the pose on screen. Key the bones that should move.")
        self._new_from_pose_button.clicked.connect(self._start_from_pose)
        self._new_length = _spin(0.1, 60.0, 0.5, 2, " s")
        self._new_length.setValue(2.0)
        self._new_length.setToolTip("How long a new animation is.")
        self._import_blender_button = QPushButton("Import…")
        self._import_blender_button.setToolTip(
            "Read a .glb or .gltf animated in Blender. Export it from here first, so the bone "
            "names match.")
        self._import_blender_button.clicked.connect(self._import_from_blender)
        self._export_blender_button = QPushButton("Export…")
        self._export_blender_button.setToolTip(
            "Write the animation as a .glb. In Blender: File > Import > glTF 2.0, animate the "
            "joints, then File > Export > glTF 2.0 with animation, and import it here.")
        self._export_blender_button.clicked.connect(self._export_for_blender)
        page = kit.InspectorPage()
        start = kit.Form()
        start.add_wide(self._clip_edit_title)
        start.add("Start from", kit.row(self._edit_playing_button, self._new_from_pose_button,
                                        self._new_length))
        start.add("Blender", kit.row(self._import_blender_button, self._export_blender_button))
        page.add(kit.Section("Animation", start))

        self._clip_edit_body = QWidget()
        body = QVBoxLayout(self._clip_edit_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(2)
        # Under the view, on the playback bar's time scale, while this tab is open.
        self._key_timeline = KeyTimeline()
        self._key_timeline.seek_requested.connect(self._seek_from_timeline)
        self._key_timeline.key_moved.connect(self._move_key_on_timeline)
        self._key_timeline.key_removed.connect(self._remove_key_on_timeline)
        self._key_timeline.setVisible(False)
        self._view_footer.addWidget(self._key_timeline)
        body.addWidget(kit.section_from_group(self._build_timing_box(), "Timing and mirror"))
        body.addWidget(kit.section_from_group(self._build_pose_box(), expanded=False))
        body.addWidget(kit.section_from_group(self._build_reach_box(), expanded=False))
        body.addWidget(kit.section_from_group(self._build_splice_box(), "Borrow body parts",
                                              expanded=False))
        body.addWidget(kit.section_from_group(self._build_join_box(), "Join another animation",
                                              expanded=False))
        page.add(self._clip_edit_body)

        self._clip_edit_target_label = QLabel("")
        self._clip_edit_target_label.setWordWrap(True)
        self._clip_edit_target_button = QPushButton("Use the selected animation")
        self._clip_edit_target_button.setToolTip(
            "Replace the animation selected in the Animations tab's list instead. The game keeps "
            "asking for that file and gets this motion.")
        self._clip_edit_target_button.clicked.connect(self._choose_clip_edit_target)
        self._clip_edit_add_button = QPushButton("Add to Your mod")
        self._clip_edit_add_button.setDefault(True)
        self._clip_edit_add_button.clicked.connect(self._add_clip_edit_to_mod)
        self._clip_edit_export_button = QPushButton("Export .paa…")
        self._clip_edit_export_button.setToolTip("Write the animation file on its own.")
        self._clip_edit_export_button.clicked.connect(self._export_clip_edit)
        self._clip_edit_undo_button = QPushButton("Undo edit")
        self._clip_edit_undo_button.clicked.connect(self._undo_clip_edit)
        self._clip_edit_reset_button = QPushButton("Reset edits")
        self._clip_edit_reset_button.setToolTip("Back to the animation you started from.")
        self._clip_edit_reset_button.clicked.connect(self._reset_clip_edit)
        self._clip_edit_status = _hint("")
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(4)
        footer_layout.addWidget(kit.row(kit.caption("Replaces"), self._clip_edit_target_label,
                                        None, self._clip_edit_target_button, stretch=False))
        footer_layout.addWidget(kit.row(self._clip_edit_undo_button, self._clip_edit_reset_button,
                                        self._clip_edit_export_button, None,
                                        self._clip_edit_add_button, stretch=False))
        footer_layout.addWidget(self._clip_edit_status)
        self._clip_edit_target_label.setWordWrap(True)
        self._clip_edit_add_button.setObjectName("EditorPrimaryButton")
        page.set_footer(footer)
        self._animation_editor_page = page
        self._refresh_clip_edit_controls()
        return page

    def _build_pose_box(self) -> QGroupBox:
        box = QGroupBox("2. Pose a bone")
        layout = QVBoxLayout(box)
        box.setToolTip((
            "Pick a bone here or click its joint in the view, move the playhead on the timeline "
            "above to a moment, and turn or move the bone. That sets a key there, on top of what "
            "the animation already does. Between keys the bone eases from one to the next; "
            "before the first and after the last it holds."
        ))
        row = QHBoxLayout()
        row.addWidget(QLabel("Bone:"))
        self._pose_bone_box = QComboBox()
        self._pose_bone_box.setEditable(True)
        self._pose_bone_box.setInsertPolicy(QComboBox.NoInsert)
        completer = QCompleter(self._pose_bone_box.model(), self._pose_bone_box)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._pose_bone_box.setCompleter(completer)
        self._pose_bone_box.setMinimumContentsLength(18)
        self._pose_bone_box.currentIndexChanged.connect(self._on_pose_bone_changed)
        row.addWidget(self._pose_bone_box, 1)
        self._pose_smooth = QCheckBox("Ease between keys")
        self._pose_smooth.setChecked(True)
        self._pose_smooth.toggled.connect(self._on_pose_smooth_toggled)
        row.addWidget(self._pose_smooth)
        layout.addLayout(row)

        form = QFormLayout()
        turns = QHBoxLayout()
        self._pose_turn = []
        for axis in ("X", "Y", "Z"):
            spin = _spin(-180.0, 180.0, 1.0, 1, "°")
            spin.setPrefix(f"{axis} ")
            spin.valueChanged.connect(self._on_pose_value_changed)
            turns.addWidget(spin)
            self._pose_turn.append(spin)
        turns.addStretch(1)
        form.addRow("Turn:", turns)
        moves = QHBoxLayout()
        self._pose_move = []
        for axis in ("X", "Y", "Z"):
            spin = _spin(-100.0, 100.0, 0.5, 1, " cm")
            spin.setPrefix(f"{axis} ")
            spin.valueChanged.connect(self._on_pose_value_changed)
            moves.addWidget(spin)
            self._pose_move.append(spin)
        moves.addStretch(1)
        form.addRow("Move:", moves)
        layout.addLayout(form)

        row = QHBoxLayout()
        row.addWidget(QLabel("Keys:"))
        self._pose_keys = QListWidget()
        self._pose_keys.setMaximumHeight(90)
        self._pose_keys.setSelectionMode(QAbstractItemView.SingleSelection)
        self._pose_keys.itemDoubleClicked.connect(self._jump_to_pose_key)
        row.addWidget(self._pose_keys, 1)
        buttons = QVBoxLayout()
        self._pose_remove_key = QPushButton("Remove key here")
        self._pose_remove_key.clicked.connect(self._remove_pose_key)
        buttons.addWidget(self._pose_remove_key)
        self._pose_clear_bone = QPushButton("Clear this bone")
        self._pose_clear_bone.clicked.connect(self._clear_pose_bone)
        buttons.addWidget(self._pose_clear_bone)
        buttons.addStretch(1)
        row.addLayout(buttons)
        layout.addLayout(row)
        return box

    def _build_reach_box(self) -> QGroupBox:
        box = QGroupBox("3. Reach with a hand or foot")
        layout = QVBoxLayout(box)
        box.setToolTip((
            "Move a hand or foot and the arm or leg bends to get it there. Plant it to keep it "
            "where it is while the body moves, such as a foot on the ground or a hand on a hilt; "
            "Let go gives it back to the animation."
        ))
        row = QHBoxLayout()
        row.addWidget(QLabel("Hand or foot:"))
        self._reach_end_box = QComboBox()
        self._reach_end_box.currentIndexChanged.connect(self._on_reach_end_changed)
        row.addWidget(self._reach_end_box, 1)
        self._reach_keep_angle = QCheckBox("Keep its angle")
        self._reach_keep_angle.setChecked(True)
        self._reach_keep_angle.setToolTip(
            "Keep the hand or foot turned the way the animation has it while the arm or leg moves.")
        self._reach_keep_angle.toggled.connect(self._on_reach_angle_toggled)
        row.addWidget(self._reach_keep_angle)
        layout.addLayout(row)

        form = QFormLayout()
        moves = QHBoxLayout()
        self._reach_move = []
        for prefix in (translate_active_ui_text("Leftward"), translate_active_ui_text("Upward"),
                       translate_active_ui_text("Ahead")):
            spin = _spin(-150.0, 150.0, 1.0, 1, " cm")
            spin.setPrefix(f"{prefix} ")
            spin.valueChanged.connect(self._on_reach_value_changed)
            moves.addWidget(spin)
            self._reach_move.append(spin)
        moves.addStretch(1)
        form.addRow("Move:", moves)
        self._reach_weight = _spin(0.0, 100.0, 5.0, 0, " %")
        self._reach_weight.setValue(100.0)
        self._reach_weight.setMaximumWidth(self._reach_weight.fontMetrics().horizontalAdvance("100 %") + 48)
        self._reach_weight.setToolTip(
            "How far it reaches: 0 % leaves the arm or leg as the animation has it.")
        self._reach_weight.valueChanged.connect(self._on_reach_value_changed)
        form.addRow("Strength:", self._reach_weight)
        layout.addLayout(form)

        row = QHBoxLayout()
        self._reach_plant = QPushButton("Plant here")
        self._reach_plant.setToolTip(
            "Hold it where it is at this moment. Plant again later to keep it there until then.")
        self._reach_plant.clicked.connect(self._plant_reach)
        row.addWidget(self._reach_plant)
        self._reach_release = QPushButton("Let go here")
        self._reach_release.setToolTip("From this moment the animation moves it again.")
        self._reach_release.clicked.connect(self._release_reach)
        row.addWidget(self._reach_release)
        row.addStretch(1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Keys:"))
        self._reach_keys = QListWidget()
        self._reach_keys.setMaximumHeight(80)
        self._reach_keys.setSelectionMode(QAbstractItemView.SingleSelection)
        self._reach_keys.itemDoubleClicked.connect(self._jump_to_pose_key)
        row.addWidget(self._reach_keys, 1)
        buttons = QVBoxLayout()
        self._reach_remove_key = QPushButton("Remove key here")
        self._reach_remove_key.clicked.connect(self._remove_reach_key)
        buttons.addWidget(self._reach_remove_key)
        self._reach_clear = QPushButton("Clear this hand or foot")
        self._reach_clear.clicked.connect(self._clear_reach)
        buttons.addWidget(self._reach_clear)
        buttons.addStretch(1)
        row.addLayout(buttons)
        layout.addLayout(row)
        return box

    def _build_join_box(self) -> QGroupBox:
        box = QGroupBox("6. Join another animation after this one")
        layout = QVBoxLayout(box)
        box.setToolTip((
            "Play the animation selected in the Animations tab's list straight after this one. "
            "The two blend over the fade, and the character carries on from where this one "
            "stops, facing the way it faces."
        ))
        row = QHBoxLayout()
        row.addWidget(QLabel("Fade:"))
        self._join_blend = _spin(0.0, 3.0, 0.05, 2, " s")
        self._join_blend.setValue(0.25)
        self._join_blend.setToolTip("How long the two animations blend into each other.")
        row.addWidget(self._join_blend)
        self._join_add = QPushButton("Join the selected animation")
        self._join_add.clicked.connect(self._add_join)
        row.addWidget(self._join_add)
        row.addStretch(1)
        layout.addLayout(row)
        row = QHBoxLayout()
        self._join_list = QListWidget()
        self._join_list.setMaximumHeight(70)
        row.addWidget(self._join_list, 1)
        self._join_remove = QPushButton("Remove")
        self._join_remove.clicked.connect(self._remove_join)
        row.addWidget(self._join_remove, 0, Qt.AlignTop)
        layout.addLayout(row)
        return box

    def _build_timing_box(self) -> QGroupBox:
        box = QGroupBox("4. Timing, travel and mirror")
        form = QFormLayout(box)
        self._edit_speed = _spin(0.1, 5.0, 0.05, 2, "×")
        self._edit_speed.setValue(1.0)
        self._edit_speed.setToolTip("Above 1 plays faster, below 1 slower.")
        form.addRow("Speed:", self._edit_speed)
        trim = QHBoxLayout()
        self._edit_trim_start = _spin(0.0, 600.0, 0.05, 3, " s")
        self._edit_trim_end = _spin(0.0, 600.0, 0.05, 3, " s")
        trim.addWidget(QLabel("from"))
        trim.addWidget(self._edit_trim_start)
        trim.addWidget(QLabel("to"))
        trim.addWidget(self._edit_trim_end)
        trim.addStretch(1)
        form.addRow("Use the part:", trim)
        self._edit_reverse = QCheckBox("Play it backwards")
        form.addRow("", self._edit_reverse)
        self._edit_hold = _spin(0.0, 60.0, 0.1, 2, " s")
        self._edit_hold.setToolTip("Keep the last pose this long before the animation ends.")
        form.addRow("Hold the end:", self._edit_hold)
        self._edit_distance = _spin(0.0, 300.0, 5.0, 0, " %")
        self._edit_distance.setValue(100.0)
        self._edit_distance.setToolTip(
            "How far the character travels while it plays. 0 % keeps it in place; height, such "
            "as the bob of a run, is kept.")
        form.addRow("Distance travelled:", self._edit_distance)
        self._edit_mirror = QCheckBox("Mirror left and right")
        self._edit_mirror.setToolTip(
            "Swap the two sides: a right-handed draw becomes a left-handed one.")
        form.addRow("", self._edit_mirror)
        for spin in (self._edit_speed, self._edit_trim_start, self._edit_trim_end,
                     self._edit_hold, self._edit_distance):
            spin.setMaximumWidth(spin.fontMetrics().horizontalAdvance("000.00 s") + 40)
            spin.valueChanged.connect(self._on_timing_changed)
        for check in (self._edit_reverse, self._edit_mirror):
            check.toggled.connect(self._on_timing_changed)
        return box

    def _build_splice_box(self) -> QGroupBox:
        box = QGroupBox("5. Borrow body parts from another animation")
        layout = QVBoxLayout(box)
        box.setToolTip((
            "Take one part of the body from the animation selected in the Animations tab's "
            "list, for example the arms of a two-hand draw on a one-hand weapon's legs."
        ))
        row = QHBoxLayout()
        row.addWidget(QLabel("Part:"))
        self._splice_region = QComboBox()
        row.addWidget(self._splice_region, 1)
        row.addWidget(QLabel("Mix:"))
        self._splice_weight = _spin(0.0, 100.0, 5.0, 0, " %")
        self._splice_weight.setValue(100.0)
        row.addWidget(self._splice_weight)
        self._splice_add = QPushButton("Borrow from the selected animation")
        self._splice_add.clicked.connect(self._add_splice)
        row.addWidget(self._splice_add)
        layout.addLayout(row)
        row = QHBoxLayout()
        self._splice_list = QListWidget()
        self._splice_list.setMaximumHeight(70)
        row.addWidget(self._splice_list, 1)
        self._splice_remove = QPushButton("Remove")
        self._splice_remove.clicked.connect(self._remove_splice)
        row.addWidget(self._splice_remove, 0, Qt.AlignTop)
        layout.addLayout(row)
        return box

    # ── state ───────────────────────────────────────────────────────

    def _editor_skeleton(self):
        session = self._session
        hierarchy = getattr(session, "hierarchy", None) if session is not None else None
        return getattr(hierarchy, "parsed", None)

    def _editor_frame(self) -> int:
        return int(round(self._playback.frame)) if self._playback.loaded else 0

    def _begin_clip_edit(self, base, label: str, entry=None, target: str = "", *,
                         from_game: bool = False) -> None:
        from tools.paa_motion.edit import ClipEdit, body_regions

        self._clip_edit = ClipEdit(base)
        session = getattr(self, "_session", None)
        self._clip_edit_model = getattr(session, "model", "") if session is not None else ""
        # Only a base read straight from the game file it replaces is that file's original;
        # a held pose or an import compared against itself would look like no change at all.
        self._clip_edit_from_game = from_game
        self._clip_edit_rendered = None
        self._clip_edit_rendered_for = None
        self._clip_edit_pending = None
        self._clip_edit_label = label
        self._clip_edit_entry = entry
        self._clip_edit_target = target
        self._clip_edit_undo = []
        skeleton = self._editor_skeleton()
        self._pose_bone_box.blockSignals(True)
        self._pose_bone_box.clear()
        animated = {track.name_hash for track in base.tracks if track.animated}
        bones = sorted(getattr(skeleton, "bones", ()) or (),
                       key=lambda bone: (bone.name_hash not in animated, bone.index))
        for bone in bones:
            self._pose_bone_box.addItem(bone.name, bone.name_hash)
        hand = self._pose_bone_box.findText("Bip01 R Hand")
        self._pose_bone_box.setCurrentIndex(max(0, hand))
        self._pose_bone_box.blockSignals(False)
        self._splice_region.clear()
        for name in body_regions(skeleton) if skeleton is not None else {}:
            self._splice_region.addItem(_region_label(name), name)
        from tools.paa_motion.edit import limb_ends

        self._reach_end_box.blockSignals(True)
        self._reach_end_box.clear()
        for name, name_hash in (limb_ends(skeleton) if skeleton is not None else {}).items():
            self._reach_end_box.addItem(_limb_label(name), name_hash)
        self._reach_end_box.blockSignals(False)
        self._render_clip_edit()
        self._refresh_clip_edit_controls()
        self._sync_bone_picking()

    def _editor_follow_character(self) -> None:
        """Close the edit when the character changes: its bones belong to the old rig.

        Called after every character or weapon load. A different weapon on the same character
        keeps the edit; a different character ends it, as Driven bones and Rig behaviour do,
        and says so rather than re-targeting a clip at a skeleton it was not made for.
        """

        if getattr(self, "_clip_edit", None) is None:
            return
        session = getattr(self, "_session", None)
        model = getattr(session, "model", "") if session is not None else ""
        if model == self._clip_edit_model:
            return
        changed = not self._clip_edit.is_identity
        # Cancel, not `_stop_animation_editor`: that shuts the tasks for good, and a shut task
        # ignores every later submit, so the next edit would never render.
        self._clip_edit_timer.stop()
        self._clip_edit_pending = None
        for name in ("_clip_edit_task", "_splice_task", "_join_task", "_import_task"):
            task = getattr(self, name, None)
            if task is not None:
                task.cancel()
        self._clip_edit = None
        self._clip_edit_undo = []
        self._clip_edit_rendered = self._clip_edit_rendered_for = None
        # The replace target and its entry belong to the old character too: Start a new one
        # from this pose and Import from Blender reuse them, and would put this character's
        # motion over the other character's animation.
        self._clip_edit_target = ""
        self._clip_edit_entry = None
        self._clip_edit_label = ""
        for box in (self._pose_bone_box, self._reach_end_box, self._splice_region):
            box.blockSignals(True)
            box.clear()
            box.blockSignals(False)
        self._clip_edit_title.setText(translate_active_ui_text(
            "Nothing to edit yet. Play an animation on the Animations tab, then choose Edit the "
            "animation that is playing."))
        self._refresh_clip_edit_controls()
        self._sync_bone_picking()
        if changed:
            self.statusBar().showMessage(translate_active_ui_text(
                "The animation edit was closed because the character changed. Anything already "
                "added to Your mod is kept."))

    def _current_model(self) -> str:
        session = getattr(self, "_session", None)
        return getattr(session, "model", "") if session is not None else ""

    def _kept_target(self):
        """The entry and replace target a new edit may keep: only this character's."""

        if self._clip_edit_target and getattr(self, "_clip_edit_model", "") == self._current_model():
            return self._clip_edit_entry, self._clip_edit_target
        return None, ""

    def _init_animation_editor(self) -> None:
        """Wire the tab to the window once both exist: bone picking follows the open tab."""

        self._lower.currentChanged.connect(lambda _index: self._sync_bone_picking())
        self._viewport.bone_clicked.connect(self._on_bone_clicked)

    def _sync_bone_picking(self) -> None:
        from .layout_util import is_current_page

        viewport = getattr(self, "_viewport", None)
        if viewport is None:
            return
        on = (getattr(self, "_clip_edit", None) is not None
              and is_current_page(getattr(self, "_animation_editor_page", None)))
        viewport.set_bone_picking(on)
        if on:
            viewport.set_picked_bone(self._pose_bone_box.currentText())
            self._show_edited_bone()

    def _on_bone_clicked(self, name: str) -> None:
        """A joint clicked in the view: pose that bone, and reach with it if it is a hand or foot."""

        index = self._pose_bone_box.findText(name)
        if index >= 0:
            self._pose_bone_box.setCurrentIndex(index)
        skeleton = self._editor_skeleton()
        bone = next((b for b in getattr(skeleton, "bones", ()) or () if b.name == name), None)
        if bone is not None:
            reach = self._reach_end_box.findData(bone.name_hash)
            if reach >= 0:
                self._reach_end_box.setCurrentIndex(reach)

    def _set_clip_edit(self, edit, *, record: bool = True) -> None:
        if self._clip_edit is None or edit == self._clip_edit:
            return
        if record:
            self._clip_edit_undo.append(self._clip_edit)
            del self._clip_edit_undo[:-200]
        self._clip_edit = edit
        self._clip_edit_timer.start()
        self._refresh_clip_edit_controls()

    def _stop_animation_editor(self) -> None:
        """Called by the window's close: no render, read or import outlives it."""

        timer = getattr(self, "_clip_edit_timer", None)
        if timer is not None:
            timer.stop()
        self._clip_edit_pending = None
        for name in ("_clip_edit_task", "_splice_task", "_join_task", "_import_task"):
            task = getattr(self, name, None)
            if task is not None:
                task.shutdown()

    def _undo_clip_edit(self) -> None:
        if self._clip_edit_undo:
            self._clip_edit = self._clip_edit_undo.pop()
            self._clip_edit_timer.start()
            self._refresh_clip_edit_controls()

    def _reset_clip_edit(self) -> None:
        if self._clip_edit is not None and not self._clip_edit.is_identity:
            from tools.paa_motion.edit import ClipEdit

            self._set_clip_edit(ClipEdit(self._clip_edit.base))

    # ── starting points ─────────────────────────────────────────────

    def _start_clip_edit(self) -> None:
        if not self._playback.loaded:
            self.statusBar().showMessage(
                "Play an animation on the Animations tab first, then edit it here.")
            return
        if not self._confirm_replace_edit():
            return
        entry = getattr(self, "_playback_entry", None)
        clip = self._playback.clip
        if self._clip_edit_rendered is not None and clip is self._clip_edit_rendered:
            clip = self._clip_edit.base
        target = entry.path if entry is not None and entry.path.startswith("character/") else ""
        self._begin_clip_edit(clip, self._playback.label, entry, target, from_game=bool(target))

    def _confirm_replace_edit(self) -> bool:
        """True when there is no unsaved edit, or the animator agrees to replace it."""

        if self._clip_edit is None or self._clip_edit.is_identity:
            return True
        return QMessageBox.question(
            self, "Edit animation",
            "Start over? The edits so far are lost unless you added them to your mod.",
        ) == QMessageBox.Yes

    def _start_from_pose(self) -> None:
        from tools.paa_motion.edit import hold_pose

        if not self._confirm_replace_edit():
            return
        if not self._playback.loaded:
            self.statusBar().showMessage(
                "Play an animation first; its pose on screen is where the new one starts.")
            return
        from tools.paa_motion.edit import EditError

        seconds = self._playback.frame / 30.0
        try:
            base = hold_pose(self._playback.clip, seconds, length=self._new_length.value(),
                             skeleton=self._editor_skeleton())
        except EditError as exc:
            QMessageBox.warning(self, "Edit animation", _explain(str(exc)))
            return
        label = translate_active_ui_text(f"New animation from {self._playback.label}")
        _entry, target = self._kept_target()
        self._begin_clip_edit(base, label, getattr(self, "_playback_entry", None), target)

    def _import_from_blender(self) -> None:
        from tools.paa_motion.gltf_import import GltfImportError, import_animation

        skeleton = self._editor_skeleton()
        template = self._clip_edit.base if self._clip_edit is not None else (
            self._playback.clip if self._playback.loaded else None)
        if skeleton is None or template is None:
            self.statusBar().showMessage(
                "Play the animation the file was made from first, so its settings can be kept.")
            return
        if not self._confirm_replace_edit():
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import an animation from Blender", "", "glTF (*.glb *.gltf)")
        if not path:
            return
        from .background import LatestTask

        if getattr(self, "_import_task", None) is None:
            self._import_task = LatestTask(self)
            self._import_task.setObjectName("animation_import")
            self._import_task.ready.connect(self._blender_imported)

        def work(cancelled, _progress):
            try:
                return path, import_animation(path, skeleton, template, should_stop=cancelled)
            except (GltfImportError, OSError, ValueError, KeyError, IndexError) as exc:
                return path, exc

        self._clip_edit_status.setText(translate_active_ui_text("Reading the Blender file…"))
        self._import_task.submit(work)

    def _blender_imported(self, value, error) -> None:
        if error or value is None:
            if error:
                QMessageBox.warning(self, "Import from Blender", _explain(error))
            return
        path, report = value
        if isinstance(report, Exception):
            QMessageBox.warning(self, "Import from Blender", _explain(str(report)))
            return
        label = report.animation or path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        self._begin_clip_edit(report.clip, label, *self._kept_target())
        note = translate_active_ui_text(
            f"Imported {len(report.matched)} animated bone(s), {report.seconds:.2f} s.")
        if report.unmatched:
            note += " " + translate_active_ui_text(
                f"Not on this character, so left out: {', '.join(report.unmatched[:6])}")
        self._clip_edit_status.setText(note)

    def _export_for_blender(self) -> None:
        from tools.paa_motion.gltf import write_glb

        clip = self._clip_edit_rendered or (self._playback.clip if self._playback.loaded else None)
        skeleton = self._editor_skeleton()
        if clip is None or skeleton is None:
            self.statusBar().showMessage("Play or edit an animation first.")
            return
        name = (self._clip_edit_label or self._playback.label or "animation").replace(" ", "_")
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export for Blender", f"{name}.glb", "glTF binary (*.glb)")
        if not path:
            return
        try:
            write_glb(path, skeleton, clip, name=name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Export for Blender", str(exc))
            return
        self.statusBar().showMessage(f"Wrote {path}")

    # ── layer controls ──────────────────────────────────────────────

    def _selected_bone_hash(self) -> int:
        return int(self._pose_bone_box.currentData() or 0)

    def _on_pose_bone_changed(self, _index: int) -> None:
        self._refresh_clip_edit_controls()
        self._show_edited_bone()
        viewport = getattr(self, "_viewport", None)
        if viewport is not None:
            viewport.set_picked_bone(self._pose_bone_box.currentText())

    def _on_pose_smooth_toggled(self, checked: bool) -> None:
        from dataclasses import replace

        edit, name_hash = self._clip_edit, self._selected_bone_hash()
        track = edit.pose_track(name_hash) if edit is not None else None
        if track is not None:
            self._set_clip_edit(edit._with_pose(replace(track, smooth=bool(checked))))

    def _on_pose_value_changed(self, _value: float) -> None:
        from tools.paa_motion.edit import PoseKey

        if self._clip_edit_syncing or self._clip_edit is None:
            return
        name_hash = self._selected_bone_hash()
        if not name_hash:
            return
        roll, pitch, yaw = (spin.value() for spin in self._pose_turn)
        quat = Quat.from_euler_degrees(roll, pitch, yaw)
        key = PoseKey(
            frame=self._editor_frame(),
            rotation=(quat.x, quat.y, quat.z, quat.w),
            translation=tuple(spin.value() / 100.0 for spin in self._pose_move),
        )
        edit = self._clip_edit.with_pose_key(name_hash, key)
        track = edit.pose_track(name_hash)
        if track is not None and track.smooth != self._pose_smooth.isChecked():
            from dataclasses import replace

            edit = edit._with_pose(replace(track, smooth=self._pose_smooth.isChecked()))
        self._set_clip_edit(edit)

    def _remove_pose_key(self) -> None:
        if self._clip_edit is not None:
            self._set_clip_edit(self._clip_edit.without_pose_key(self._selected_bone_hash(),
                                                                 self._editor_frame()))

    def _clear_pose_bone(self) -> None:
        from tools.paa_motion.edit import PoseTrack

        if self._clip_edit is not None:
            self._set_clip_edit(self._clip_edit._with_pose(PoseTrack(self._selected_bone_hash())))

    def _jump_to_pose_key(self, item) -> None:
        frame = item.data(Qt.UserRole)
        if frame is None or not self._playback.loaded:
            return
        self._stop_playback()
        self._playback.seek(float(frame))
        self._apply_playback_frame()

    # Reach

    def _selected_reach_end(self) -> int:
        return int(self._reach_end_box.currentData() or 0)

    def _reach_axes(self):
        from tools.paa_motion.edit import character_axes

        skeleton = self._editor_skeleton()
        if skeleton is None:
            return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)
        return character_axes(skeleton)

    def _reach_offset_from_controls(self):
        left, up, forward = self._reach_axes()
        amounts = [spin.value() / 100.0 for spin in self._reach_move]
        return tuple(amounts[0] * left[i] + amounts[1] * up[i] + amounts[2] * forward[i]
                     for i in range(3))

    def _set_reach_key(self, *, pinned: Optional[bool] = None, offset=None,
                       weight: Optional[float] = None) -> None:
        from dataclasses import replace

        from tools.paa_motion.edit import ReachKey, reach_offset

        edit, end = self._clip_edit, self._selected_reach_end()
        if edit is None or not end:
            return
        frame = self._editor_frame()
        track = edit.reach_track(end)
        here = next((k for k in track.keys if k.frame == frame), None) if track is not None else None
        if pinned is None:
            pinned = here.pinned if here is not None else (
                reach_offset(track, frame)[2] if track is not None else False)
        key = ReachKey(
            frame=frame,
            offset=self._reach_offset_from_controls() if offset is None else offset,
            pinned=bool(pinned),
            weight=self._reach_weight.value() / 100.0 if weight is None else weight,
        )
        edit = edit.with_reach_key(end, key)
        track = edit.reach_track(end)
        if track is not None and track.keep_angle != self._reach_keep_angle.isChecked():
            edit = edit.with_reach(replace(track, keep_angle=self._reach_keep_angle.isChecked()))
        self._set_clip_edit(edit)

    def _on_reach_value_changed(self, _value: float) -> None:
        if not self._clip_edit_syncing:
            self._set_reach_key()

    def _plant_reach(self) -> None:
        self._set_reach_key(pinned=True, weight=1.0)

    def _release_reach(self) -> None:
        # Full strength and no offset: the animation's own position. A strength of 0 looked the
        # same here, but the Strength box reads it back, so the next Plant copied the 0 and did
        # nothing.
        self._set_reach_key(pinned=False, offset=(0.0, 0.0, 0.0), weight=1.0)

    def _remove_reach_key(self) -> None:
        if self._clip_edit is not None:
            self._set_clip_edit(self._clip_edit.without_reach_key(self._selected_reach_end(),
                                                                  self._editor_frame()))

    def _clear_reach(self) -> None:
        from tools.paa_motion.edit import ReachTrack

        if self._clip_edit is not None and self._selected_reach_end():
            self._set_clip_edit(self._clip_edit.with_reach(ReachTrack(self._selected_reach_end())))

    def _on_reach_angle_toggled(self, checked: bool) -> None:
        from dataclasses import replace

        edit, end = self._clip_edit, self._selected_reach_end()
        track = edit.reach_track(end) if edit is not None and end else None
        if track is not None and not self._clip_edit_syncing:
            self._set_clip_edit(edit.with_reach(replace(track, keep_angle=bool(checked))))

    def _on_reach_end_changed(self, _index: int) -> None:
        self._refresh_clip_edit_controls()

    # Join

    def _add_join(self) -> None:
        from .clips import read_clip
        from .playback import load_clip

        if self._clip_edit is None:
            return
        item = self._clip_list.currentItem() if hasattr(self, "_clip_list") else None
        entry = item.data(Qt.UserRole) if item is not None else None
        if entry is None:
            self.statusBar().showMessage(
                "Select the animation to join in the Animations tab's list first.")
            return
        blend = self._join_blend.value()
        from .background import LatestTask

        if getattr(self, "_join_task", None) is None:
            self._join_task = LatestTask(self)
            self._join_task.setObjectName("animation_join_read")
            self._join_task.ready.connect(self._join_read)

        base = self._clip_edit.base

        def work(cancelled, _progress):
            data = read_clip(entry)
            return None if cancelled() else (entry, blend, load_clip(data, entry.name), base)

        self.statusBar().showMessage(f"Reading {entry.name}…")
        self._join_task.submit(work)

    def _join_read(self, value, error) -> None:
        from dataclasses import replace

        from tools.paa_motion.edit import Join
        from tools.paa_motion.format import FLAG_PACKED

        if error or value is None or self._clip_edit is None:
            if error:
                self.statusBar().showMessage(error)
            return
        entry, blend, clip, base = value
        if base is not self._clip_edit.base:
            return  # a new edit started while the file was read
        if clip.flags & FLAG_PACKED or any(track.packed for track in clip.tracks):
            QMessageBox.warning(self, "Edit animation", _explain("distance (LOD) copy"))
            return
        join = Join(clip, blend, label=entry.name)
        self._set_retimed_edit(replace(self._clip_edit, joins=self._clip_edit.joins + (join,)))

    def _remove_join(self) -> None:
        from dataclasses import replace

        row = self._join_list.currentRow()
        if self._clip_edit is None or row < 0:
            return
        joins = list(self._clip_edit.joins)
        if row < len(joins):
            del joins[row]
            self._set_retimed_edit(replace(self._clip_edit, joins=tuple(joins)))

    def _set_retimed_edit(self, edit) -> None:
        """`edit` with its keys moved along, so each stays on the moment of motion it was on."""

        from tools.paa_motion.edit import remap_keys

        self._set_clip_edit(remap_keys(self._clip_edit, edit))

    # The key timeline

    def _seek_from_timeline(self, frame: float) -> None:
        if not self._playback.loaded:
            return
        self._stop_playback()
        self._playback.seek(float(frame))
        self._apply_playback_frame()

    def _move_key_on_timeline(self, lane: str, frame: int, to: int) -> None:
        from dataclasses import replace

        edit = self._clip_edit
        if edit is None:
            return
        if lane == "pose":
            track = edit.pose_track(self._selected_bone_hash())
            if track is not None:
                edit = edit._with_pose(replace(track, keys=_retimed_keys(track.keys, frame, to)))
        elif lane == "reach":
            track = edit.reach_track(self._selected_reach_end())
            if track is not None:
                edit = edit.with_reach(replace(track, keys=_retimed_keys(track.keys, frame, to)))
        self._set_clip_edit(edit)
        self._seek_from_timeline(float(to))

    def _remove_key_on_timeline(self, lane: str, frame: int) -> None:
        edit = self._clip_edit
        if edit is None:
            return
        if lane == "pose":
            edit = edit.without_pose_key(self._selected_bone_hash(), frame)
        elif lane == "reach":
            edit = edit.without_reach_key(self._selected_reach_end(), frame)
        self._set_clip_edit(edit)

    def _refresh_timeline(self) -> None:
        edit = self._clip_edit
        timeline = self._key_timeline
        if edit is None:
            timeline.set_lanes(())
            timeline.set_bands(())
            timeline.set_length(0)
            return
        lanes = []
        bone = self._pose_bone_box.currentText()
        if bone:
            track = edit.pose_track(self._selected_bone_hash())
            lanes.append(Lane("pose", bone, tuple(k.frame for k in track.keys) if track else ()))
        end = self._selected_reach_end()
        if end:
            track = edit.reach_track(end)
            keys = track.keys if track is not None else ()
            lanes.append(Lane("reach", self._reach_end_box.currentText(),
                              tuple(k.frame for k in keys),
                              tuple(k.frame for k in keys if k.pinned)))
        timeline.set_lanes(lanes)
        timeline.set_bands([
            Band(start * 30.0, blend * 30.0, (start + length) * 30.0, join.label)
            for join, (start, length, blend) in zip(edit.joins, edit.join_spans())
        ])
        timeline.set_length(edit.last_frame)
        timeline.set_playhead(self._playback.frame if self._playback.loaded else 0.0)

    def _on_timing_changed(self, *_args) -> None:
        from dataclasses import replace

        if self._clip_edit_syncing or self._clip_edit is None:
            return
        end = self._edit_trim_end.value()
        # The spin rounds its maximum to its decimals, so "at the maximum" means the whole
        # clip; comparing with the exact length read a rounded end as a trim.
        whole = end >= self._edit_trim_end.maximum() - 0.0005
        start = self._edit_trim_start.value()
        self._set_retimed_edit(replace(
            self._clip_edit,
            speed=self._edit_speed.value(),
            trim_start=0.0 if start <= 0.0005 else start,
            trim_end=None if whole else end,
            reverse=self._edit_reverse.isChecked(),
            hold_end=self._edit_hold.value(),
            root_distance=self._edit_distance.value() / 100.0,
            mirror=self._edit_mirror.isChecked(),
        ))

    def _add_splice(self) -> None:
        from .clips import read_clip
        from .playback import load_clip

        if self._clip_edit is None:
            return
        item = self._clip_list.currentItem() if hasattr(self, "_clip_list") else None
        entry = item.data(Qt.UserRole) if item is not None else None
        if entry is None:
            self.statusBar().showMessage(
                "Select the animation to borrow from in the Animations tab's list first.")
            return
        region = str(self._splice_region.currentData() or "")
        weight = self._splice_weight.value() / 100.0
        from .background import LatestTask

        if getattr(self, "_splice_task", None) is None:
            self._splice_task = LatestTask(self)
            self._splice_task.setObjectName("animation_splice_read")
            self._splice_task.ready.connect(self._splice_read)

        base = self._clip_edit.base

        def work(cancelled, _progress):
            data = read_clip(entry)
            return None if cancelled() else (entry, region, weight, load_clip(data, entry.name), base)

        self.statusBar().showMessage(f"Reading {entry.name}…")
        self._splice_task.submit(work)

    def _splice_read(self, value, error) -> None:
        from dataclasses import replace

        from tools.paa_motion.edit import Splice, body_regions

        if error or value is None or self._clip_edit is None:
            if error:
                self.statusBar().showMessage(error)
            return
        entry, region, weight, clip, base = value
        if base is not self._clip_edit.base:
            return  # a new edit started while the file was read
        regions = body_regions(self._editor_skeleton())
        if region not in regions:
            return
        splice = Splice(clip, regions[region], weight,
                        label=translate_active_ui_text(
                            f"{_region_label(region)} from {entry.name}"))
        self._set_clip_edit(replace(self._clip_edit, splices=self._clip_edit.splices + (splice,)))

    def _remove_splice(self) -> None:
        from dataclasses import replace

        row = self._splice_list.currentRow()
        if self._clip_edit is None or row < 0:
            return
        splices = list(self._clip_edit.splices)
        if row < len(splices):
            del splices[row]
            self._set_clip_edit(replace(self._clip_edit, splices=tuple(splices)))

    # ── rendering and preview ───────────────────────────────────────

    def _render_clip_edit(self) -> None:
        from .background import LatestTask
        from tools.paa_motion.edit import render

        edit, skeleton = self._clip_edit, self._editor_skeleton()
        if edit is None:
            return
        if getattr(self, "_clip_edit_task", None) is None:
            self._clip_edit_task = LatestTask(self)
            self._clip_edit_task.setObjectName("animation_edit_render")
            self._clip_edit_task.ready.connect(self._clip_edit_ready)
        self._clip_edit_status.setText(translate_active_ui_text("Updating the preview…"))
        self._clip_edit_task.submit(
            lambda cancelled, _progress: (edit, render(edit, skeleton, should_stop=cancelled)))

    def _clip_edit_ready(self, value, error) -> None:
        if error:
            self._clip_edit_pending = None
            if "replaced by a newer edit" not in error:
                self._clip_edit_status.setText(_explain(error))
            return
        if value is None:
            return
        edit, clip = value
        if edit is not self._clip_edit:
            return  # a newer change is already on its way
        self._clip_edit_rendered = clip
        self._clip_edit_rendered_for = edit
        frame = self._playback.frame if self._playback.loaded else 0.0
        playing = self._playback.playing
        self._playback.load(clip, translate_active_ui_text(f"Edited: {self._clip_edit_label}"))
        self._playback.looping = self._playback_loop_box.isChecked()
        self._playback.seek(frame)
        self._playback_slider.setMaximum(max(self._playback.last_frame, 0))
        self._playback_slider.setEnabled(self._playback.last_frame > 0)
        self._playback_play_button.setEnabled(self._playback.last_frame > 0)
        self._playback_rest_button.setEnabled(True)
        if playing:
            self._playback.playing = True
        self._apply_playback_frame()
        bones = sum(1 for track in clip.tracks if track.animated)
        self._clip_edit_status.setText(translate_active_ui_text(
            f"Showing the edited animation: {clip.duration:.2f} s, {bones} animated bone(s)."))
        self._refresh_clip_edit_controls()
        pending, self._clip_edit_pending = self._clip_edit_pending, None
        if pending is not None:
            pending()

    def _on_editor_frame(self) -> None:
        """The playhead moved: show the selected bone's offset at the new moment."""

        if getattr(self, "_clip_edit", None) is not None:
            self._sync_pose_values()
            self._sync_reach_values()
            self._show_edited_bone()
            self._key_timeline.set_playhead(self._playback.frame if self._playback.loaded else 0.0)

    def _show_edited_bone(self) -> None:
        from .model import Vec3

        session, skeleton = self._session, self._editor_skeleton()
        name_hash = self._selected_bone_hash()
        if session is None or skeleton is None or not name_hash:
            return
        from .layout_util import is_current_page

        if not is_current_page(getattr(self, "_animation_editor_page", None)):
            return
        bone = next((b for b in skeleton.bones if b.name_hash == name_hash), None)
        if bone is None:
            return
        matrices = getattr(session, "pose_matrices", None)
        matrix = matrices[bone.index] if matrices and bone.index < len(matrices) else bone.bind_matrix
        if matrix and len(matrix) >= 15:
            self._viewport.set_gizmo_anchor(Vec3(matrix[12], matrix[13], matrix[14]))

    # ── keeping the controls honest ─────────────────────────────────

    def _sync_pose_values(self) -> None:
        from tools.paa_motion.edit import pose_offset

        edit = self._clip_edit
        track = edit.pose_track(self._selected_bone_hash()) if edit is not None else None
        if track is not None and track.keys:
            rotation, translation = pose_offset(track, self._editor_frame())
        else:
            rotation, translation = (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0)
        euler = Quat(*rotation).to_euler_degrees()
        self._clip_edit_syncing = True
        for spin, value in zip(self._pose_turn, euler):
            spin.setValue(round(value, 1))
        for spin, value in zip(self._pose_move, translation):
            spin.setValue(round(value * 100.0, 1))
        self._clip_edit_syncing = False

    def _sync_reach_values(self) -> None:
        from tools.paa_motion.edit import reach_offset

        edit = self._clip_edit
        end = self._selected_reach_end()
        track = edit.reach_track(end) if edit is not None and end else None
        if track is not None:
            offset, weight, _pinned = reach_offset(track, self._editor_frame())
        else:
            offset, weight = (0.0, 0.0, 0.0), 1.0
        axes = self._reach_axes()
        self._clip_edit_syncing = True
        for spin, axis in zip(self._reach_move, axes):
            spin.setValue(round(sum(o * a for o, a in zip(offset, axis)) * 100.0, 1))
        self._reach_weight.setValue(round(weight * 100.0))
        self._reach_keep_angle.setChecked(track.keep_angle if track is not None else True)
        self._clip_edit_syncing = False

    def _refresh_clip_edit_controls(self) -> None:
        edit = getattr(self, "_clip_edit", None)
        active = edit is not None
        self._clip_edit_body.setEnabled(active)
        for widget in (self._clip_edit_add_button, self._clip_edit_export_button,
                       self._clip_edit_reset_button, self._clip_edit_target_button):
            widget.setEnabled(active)
        self._clip_edit_undo_button.setEnabled(active and bool(self._clip_edit_undo))
        if not active:
            self._refresh_timeline()
            return
        changed = translate_active_ui_text("edited") if not edit.is_identity else ""
        self._clip_edit_title.setText(
            f"{self._clip_edit_label}  ({edit.duration:.2f} s{', ' + changed if changed else ''})")
        self._clip_edit_target_label.setText(
            self._clip_edit_target or translate_active_ui_text(
                "Not chosen yet: select an animation in the Animations tab's list, then Use "
                "the selected animation."))
        self._clip_edit_add_button.setEnabled(bool(self._clip_edit_target))

        self._clip_edit_syncing = True
        self._edit_speed.setValue(edit.speed)
        self._edit_trim_start.setMaximum(edit.base_length)
        self._edit_trim_end.setMaximum(edit.base_length)
        start, end = edit.span
        self._edit_trim_start.setValue(start)
        self._edit_trim_end.setValue(end)
        self._edit_reverse.setChecked(edit.reverse)
        self._edit_hold.setValue(edit.hold_end)
        self._edit_distance.setValue(edit.root_distance * 100.0)
        self._edit_mirror.setChecked(edit.mirror)
        track = edit.pose_track(self._selected_bone_hash())
        self._pose_smooth.setChecked(track.smooth if track is not None else True)
        self._clip_edit_syncing = False
        self._sync_pose_values()

        self._pose_keys.clear()
        for key in (track.keys if track is not None else ()):
            roll, pitch, yaw = Quat(*key.rotation).to_euler_degrees()
            self._pose_keys.addItem(translate_active_ui_text(
                f"{key.frame / 30.0:.2f} s  (frame {key.frame}): turn {roll:.0f}°, {pitch:.0f}°, "
                f"{yaw:.0f}°"))
            self._pose_keys.item(self._pose_keys.count() - 1).setData(Qt.UserRole, key.frame)
        self._splice_list.clear()
        for splice in edit.splices:
            self._splice_list.addItem(f"{splice.label}  ({splice.weight:.0%})")

        self._sync_reach_values()
        end = self._selected_reach_end()
        reach = edit.reach_track(end) if end else None
        self._reach_keys.clear()
        axes = self._reach_axes()
        for key in (reach.keys if reach is not None else ()):
            left, up, forward = (sum(o * a for o, a in zip(key.offset, axis)) * 100.0 for axis in axes)
            if key.pinned:
                what = translate_active_ui_text("planted")
            elif key.weight <= 0.0 or not any(abs(v) > 1e-9 for v in key.offset):
                what = translate_active_ui_text("let go")
            else:
                what = translate_active_ui_text(
                    f"leftward {left:.0f}, upward {up:.0f}, ahead {forward:.0f} cm")
            self._reach_keys.addItem(translate_active_ui_text(
                f"{key.frame / 30.0:.2f} s  (frame {key.frame}): {what}"))
            self._reach_keys.item(self._reach_keys.count() - 1).setData(Qt.UserRole, key.frame)
        has_limbs = self._reach_end_box.count() > 0
        for widget in (self._reach_plant, self._reach_release, self._reach_keep_angle,
                       self._reach_weight, *self._reach_move):
            widget.setEnabled(has_limbs)
        self._join_list.clear()
        for join, (start, _length, blend) in zip(edit.joins, edit.join_spans()):
            self._join_list.addItem(translate_active_ui_text(
                f"{join.label}  (from {start:.2f} s, fade {blend:.2f} s)"))
        self._refresh_timeline()

    # ── using the result ────────────────────────────────────────────

    def _choose_clip_edit_target(self) -> None:
        item = self._clip_list.currentItem() if hasattr(self, "_clip_list") else None
        entry = item.data(Qt.UserRole) if item is not None else None
        if entry is None or not str(entry.path).startswith("character/"):
            self.statusBar().showMessage(
                "Select the animation to replace in the Animations tab's list first.")
            return
        self._clip_edit_target = entry.path
        self._refresh_clip_edit_controls()

    def _when_rendered(self, action) -> None:
        """Run `action` once the preview matches the current edit, baking it first if needed.

        Saving used to bake the clip again on the UI thread, which on a long mirrored clip
        froze the window for seconds after the preview had already done the same work.
        """

        if self._clip_edit is None:
            return
        if self._clip_edit_rendered_for is self._clip_edit and self._clip_edit_rendered is not None:
            action()
            return
        self._clip_edit_pending = action
        self._clip_edit_timer.stop()
        self._render_clip_edit()

    def _rendered_bytes(self) -> Optional[bytes]:
        from tools.paa_motion.encode import PaaEncodeError, encode_paa

        if self._clip_edit_rendered is None:
            return None
        try:
            return encode_paa(self._clip_edit_rendered)
        except (PaaEncodeError, ValueError) as exc:
            QMessageBox.warning(self, "Edit animation", str(exc))
            return None

    def _export_clip_edit(self) -> None:
        if self._clip_edit is None:
            return
        name = (self._clip_edit_target.rsplit("/", 1)[-1] if self._clip_edit_target
                else f"{self._clip_edit_label}.paa")
        path, _filter = QFileDialog.getSaveFileName(self, "Export animation", name,
                                                    "Crimson Desert motion (*.paa)")
        if path:
            self._when_rendered(lambda: self._write_clip_edit(path))

    def _write_clip_edit(self, path: str) -> None:
        data = self._rendered_bytes()
        if data is None:
            return
        try:
            with open(path, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            QMessageBox.warning(self, "Export animation", str(exc))
            return
        self.statusBar().showMessage(f"Wrote {path}")

    def _add_clip_edit_to_mod(self) -> None:
        if self._edits is not None and self._clip_edit_target:
            self._when_rendered(self._put_clip_edit_in_mod)

    def _put_clip_edit_in_mod(self) -> None:
        from tools.paa_motion.encode import encode_paa

        from .editing import EditError, OP_EDIT_ANIMATION, OperationScope

        target = self._clip_edit_target
        if self._edits is None or not target:
            return
        if getattr(self, "_clip_edit_model", "") != self._current_model():
            self._clip_edit_status.setText(translate_active_ui_text(
                "This animation was edited on another character. Start the edit again on this "
                "one."))
            return
        data = self._rendered_bytes()
        if data is None:
            return
        original = None
        entry = self._clip_edit_entry
        if self._clip_edit_from_game and entry is not None and entry.path == target:
            try:
                original = encode_paa(self._clip_edit.base)
            except ValueError:
                original = None
        if original is not None and original == data:
            self._clip_edit_status.setText(translate_active_ui_text(
                "Nothing changed yet: edit the animation first."))
            return
        previous = self._clip_edit_ops.get(target)
        scope = OperationScope(
            kind=OP_EDIT_ANIMATION,
            model=self._session.model if self._session is not None else "",
            allowed_animation_targets=(target,),
        )
        label = translate_active_ui_text(f"Edited animation: {target.rsplit('/', 1)[-1][:-4]}")
        try:
            # Adding the same animation again replaces the earlier version in the mod, but only
            # if the new one is recorded: on a failure the earlier version stays.
            with self._edits.keep_on_failure():
                if previous and any(op.operation_id == previous for op in self._edits.operations()):
                    self._edits.discard_operation(previous)
                with self._edits.begin_operation(scope, label=label) as handle:
                    handle.replace_clip(target, data, self._clip_edit_label, original)
        except EditError as exc:
            QMessageBox.warning(self, "Edit animation", _explain(str(exc)))
            return
        operation = self._edits.latest_operation()
        if operation is not None:
            self._clip_edit_ops[target] = operation.operation_id
        self._after_edit()
        self._clip_edit_status.setText(translate_active_ui_text(
            "Added to Your mod. Save it there; edit again and add again to replace this version."))
