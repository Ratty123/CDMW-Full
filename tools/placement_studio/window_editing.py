"""The edit panel and every mutating action behind it.

Split from `window.py` to stay under the owner file-size ceiling. The division is by role: this
module *changes* the plan (nudge, rotate, roll, revert, undo, export, package), while `window.py`
builds the shell and *shows* the result.

Two conventions worth keeping in mind when editing here:

* Socket translation and rotation are stored in **parent-bone space**, so a world-space axis
  from the viewport must be converted before it is applied.
* Rotation is composed as quaternions and only ever *displayed* as euler degrees — the child
  sockets sit at pitch 90, where euler deltas silently read zero.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from .editing import NUDGE_STEPS, EditError
from .glossary import AIM_LABEL, tip
from .report_style import inspector_html
from .new_socket import NewSocketDialog, keyboard_hint
from .skeleton import world_to_bone
from .model import Vec3
from .session import PlacementSession


class EditPanelMixin:
    """The edit controls and the actions they drive. Mixed into `PlacementStudioWindow`."""

    def _build_edit_panel(self) -> QWidget:
        from .window import fit_popup  # local: `window` imports this module

        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        # Clusters on two rows, not one nine-column grid. A grid ties every row to the same
        # column widths, so `Undo my changes to this point` in column 4 made column 4 that wide
        # on every row — which is why `Step:` sat a hand's width from the nudge buttons above
        # it and the bar spent most of itself on gaps. Each group is its own box now, so a wide
        # button widens only its own group.
        rows = QVBoxLayout(panel)
        rows.setContentsMargins(8, 5, 8, 5)
        rows.setSpacing(4)
        top, bottom = QHBoxLayout(), QHBoxLayout()
        for line in (top, bottom):
            line.setSpacing(6)
        rows.addLayout(top)
        rows.addLayout(bottom)

        def group(*widgets):
            """One cluster of controls, spaced tightly and separated from its neighbours."""

            box = QHBoxLayout()
            box.setSpacing(4)
            for widget in widgets:
                box.addWidget(widget)
            return box

        # Short labels, with the explanation on each row's own tooltip. The long form did not
        # fit the dropdown and Qt elided it down the middle, so "New attach point (click the
        # body)" read as "New attach poi...lick the body)".
        self._mode_box = QComboBox()
        for label, value, hint in (
            ("Look around", "off", "Drag to orbit. Nothing is edited in this mode."),
            ("Move", "move", "Drag the selected point to reposition it."),
            ("Rotate", "rotate", "Drag to twist the selected point."),
            ("Tilt", "tilt", "Drag to roll the item along its own length."),
            ("Send to socket", "route",
             "Click a socket in the viewport to hang the selected item there."),
            ("New attach point", "pick",
             "Click anywhere on the body to create a socket at that spot."),
        ):
            self._mode_box.addItem(label, value)
            self._mode_box.setItemData(
                self._mode_box.count() - 1, hint, Qt.ToolTipRole
            )
        self._mode_box.setToolTip(
            "What a click and drag in the viewport does.\n\n"
            "Move / Rotate / Tilt adjust the selected point. Route sends the selected item to "
            "a socket you click. New attach point creates a socket where you click on the body."
        )
        fit_popup(self._mode_box)
        self._mode_box.currentIndexChanged.connect(self._on_mode_changed)

        self._angle_box = QComboBox()
        for degrees in (1.0, 5.0, 15.0, 45.0):
            self._angle_box.addItem(f"{degrees:.0f}°", degrees)
        self._angle_box.setToolTip("How far each turn moves it. Only used by Rotate and Tilt.")
        self._angle_box.setCurrentIndex(1)  # 5° — fine enough to aim, coarse enough to feel
        self._angle_box.currentIndexChanged.connect(
            lambda _i: self._viewport.set_angle_snap(float(self._angle_box.currentData() or 5.0))
        )

        self._step_box = QComboBox()
        for label, value, risky in NUDGE_STEPS:
            # The guide flags 0.100 as a risky jump; say so rather than offering it plainly.
            self._step_box.addItem(f"{value:.3f}  {label}{'  (risky)' if risky else ''}", value)
        self._step_box.setToolTip(
            "How far each nudge moves it, in metres. 0.020 is a normal adjustment; 0.100 is "
            "flagged as risky because it is large enough to push an item through the body."
        )
        fit_popup(self._step_box)
        self._step_box.setCurrentIndex(1)  # 0.020 — the guide's "normal nudge"
        self._step_box.currentIndexChanged.connect(
            lambda _i: self._viewport.set_snap(self._snap_step())
        )

        self._edit_target = QLabel("(no socket selected)")
        self._edit_target.setStyleSheet("font-weight: bold;")

        top.addLayout(group(QLabel("Editing:"), self._edit_target))
        top.addStretch(1)
        top.addLayout(group(QLabel("Step:"), self._step_box))
        top.addSpacing(10)
        top.addLayout(group(QLabel("Mode:"), self._mode_box, self._angle_box))

        # Translation nudges along each axis.
        # Socket translation is in *parent-bone* space, so these axes follow the bone's
        # orientation, not the world. Saying so prevents "-X should move it left" confusion.
        translate_label = QLabel("Nudge:")
        translate_label.setToolTip(
            "Move the selected point one step at a time.\n\n"
            "The axes follow the bone this point is attached to, not the screen — so on a "
            "rotated bone, +X may not be the direction you expect. Watch the viewport."
        )
        nudges = group(translate_label)
        bottom.addLayout(nudges)
        self._nudge_buttons: List[QPushButton] = []
        for axis, index in (("X", 0), ("Y", 1), ("Z", 2)):
            for sign, glyph in ((-1.0, "-"), (1.0, "+")):
                button = QPushButton(f"{glyph}{axis}")
                button.setToolTip(
                    "Follows the bone's own direction, not the screen's — watch the viewport"
                )
                button.setFixedWidth(42)
                button.clicked.connect(
                    lambda _checked=False, i=index, s=sign: self._nudge_axis(i, s)
                )
                nudges.addWidget(button)
                self._nudge_buttons.append(button)

        # Rotation is authored in degrees; the guide forbids hand-editing quaternions.
        rotate_label = QLabel("Angle:")
        rotate_label.setToolTip(
            "The exact angle the item sits at, in degrees. Type a value to set it precisely, "
            "or use Rotate and Tilt in the viewport to aim it by eye."
        )
        bottom.addSpacing(10)
        angles = group(rotate_label)
        bottom.addLayout(angles)
        self._euler: List[QDoubleSpinBox] = []
        for position, name in enumerate(("roll", "pitch", "yaw")):
            box = QDoubleSpinBox()
            box.setRange(-180.0, 180.0)
            box.setSingleStep(1.0)
            box.setDecimals(2)
            box.setPrefix(f"{name} ")
            box.setFixedWidth(96)
            box.editingFinished.connect(self._apply_euler)
            angles.addWidget(box)
            self._euler.append(box)

        # Short labels; every one of these carries a tooltip saying the rest. Spelled out,
        # these five buttons wanted 1,052 px between them and the bar asked for 2,262 in a
        # 1,500 px window — so Qt clipped them and `Undo my changes to this point` became
        # unreadable anyway. A name that fits beats a sentence that does not.
        self._revert_button = QPushButton("Revert point")
        self._revert_button.setToolTip(
            "Undo every change made to the selected attach point, back to how the game ships "
            "it. Other points are left alone."
        )
        self._revert_button.clicked.connect(self._revert_socket)


        self._new_socket_button = QPushButton("New point…")
        self._new_socket_button.setToolTip(tip("Attach point", keyboard_hint()))
        self._new_socket_button.clicked.connect(lambda: self._create_socket())


        # The step that makes a *newly created* child socket actually do something. Routing the
        # body socket moves where an item sits; the child socket is what aims it, and a socket
        # the user just invented has no vanilla pairing for the tool to infer.
        self._use_orientation_button = QPushButton(AIM_LABEL)
        self._use_orientation_button.setToolTip(
            "Aim the selected item using the selected point.\n\n"
            "Use this when an item hangs at a strange angle after being moved — it means the "
            "game had no matching angle defined for its new spot."
        )
        self._use_orientation_button.clicked.connect(self._use_selected_as_orientation)


        self._undo_button = QPushButton("Undo")
        self._undo_button.setShortcut("Ctrl+Z")
        self._undo_button.clicked.connect(self._undo)
        self._redo_button = QPushButton("Redo")
        self._redo_button.setShortcut("Ctrl+Y")
        self._redo_button.clicked.connect(self._redo)
        self._export_button = QPushButton("Export…")
        self._export_button.setToolTip("Write the changed files out as loose files.")
        self._export_button.clicked.connect(self._export)
        self._package_button = QPushButton("Packages…")
        self._package_button.setToolTip(
            "Write installable mod packages (CDUMM, DMM and JMM) from these changes."
        )
        self._package_button.clicked.connect(self._build_packages)

        # Grouped by what they are for: make a point, take a change back, write it out.
        bottom.addStretch(1)
        bottom.addLayout(group(self._new_socket_button, self._use_orientation_button))
        bottom.addSpacing(10)
        bottom.addLayout(group(self._revert_button, self._undo_button, self._redo_button))
        # Writing the mod out is not an editing control, and the top row had the room the
        # bottom one did not. Both rows now fit a 1,500 px window instead of one overflowing.
        top.addSpacing(10)
        top.addLayout(group(self._export_button, self._package_button))

        self._viewport.socket_dragged.connect(self._on_socket_dragged)
        self._viewport.socket_rotated.connect(self._on_socket_rotated)
        self._viewport.weapon_clicked.connect(self._on_weapon_clicked)
        self._viewport.socket_rolled.connect(self._on_socket_rolled)
        self._viewport.set_snap(0.020)
        self._viewport.set_angle_snap(5.0)
        return panel

    # ── edit actions ────────────────────────────────────────────────

    def _nudge_axis(self, axis: int, sign: float) -> None:
        step = self._snap_step() * sign
        deltas = [0.0, 0.0, 0.0]
        deltas[axis] = step
        self._nudge(*deltas)

    def _nudge(self, dx: float, dy: float, dz: float) -> None:
        if self._edits is None or not self._selected_socket:
            return
        path = self._socket_file_of(self._selected_socket)
        if not path:
            self.statusBar().showMessage(f"No file defines {self._selected_socket}")
            return
        try:
            self._edits.nudge(path, self._selected_socket, dx, dy, dz)
        except EditError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self._after_edit()

    def _on_socket_dragged(self, socket_name: str, dx: float, dy: float, dz: float) -> None:
        if socket_name != self._selected_socket:
            self._select_socket(socket_name)
        self._nudge(dx, dy, dz)

    def _bindable_chart_sockets(self, socket_name: str):
        """Chart sockets this new socket could stand in for.

        A `.paac` reference may only be swapped for a name of the *same length*, so the set
        of charts a new socket can serve is decided the moment it is named. Reporting it here
        turns "why is my socket ignored by the draw" into something visible.
        """

        from .animation_sets import AnimationSetIndex

        if self._edits is None or len(socket_name) == 0:
            return []
        index = AnimationSetIndex.from_files(
            {path: self._edits.chart_bytes(path) or b"" for path in self._edits.charts()}
        )
        out = []
        for chart_socket in index.sockets():
            if chart_socket == socket_name or len(chart_socket) != len(socket_name):
                continue
            clips = index.clips_for_socket(chart_socket)
            draws = [c for c in clips if "weapon_out" in c or "weapon_in" in c]
            out.append((chart_socket, len(clips), len(draws)))
        out.sort(key=lambda row: -row[2])
        return out

    def _offer_animation_binding(self, socket_name: str) -> None:
        """After creating an attach point, offer to point the draw/sheathe charts at it."""

        candidates = self._bindable_chart_sockets(socket_name)
        usable = [row for row in candidates if row[2] > 0] or candidates
        if not usable:
            self.statusBar().showMessage(
                f"Created {socket_name}. No chart socket shares its {len(socket_name)}-character "
                f"length, so no animation can be retargeted to it yet."
            )
            return
        chart_socket, clips, draws = usable[0]
        answer = QMessageBox.question(
            self,
            "Use this attach point for the animations?",
            f"{socket_name} is the same length as {chart_socket}, which {clips} clip(s) run "
            f"through — {draws} of them draw or sheathe.\n\n"
            f"Retarget those charts from {chart_socket} to {socket_name}?\n\n"
            f"This is the same-length swap the manual workflow uses, and it lands as a "
            f"pending change you can review before exporting.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.statusBar().showMessage(
                f"Created {socket_name} — bind it later from the Animation tab"
            )
            return
        self._retarget_between(chart_socket, socket_name)

    def _retarget_between(self, old_name: str, new_name: str) -> None:
        """Swap one chart socket for another across every chart that names it."""

        if self._edits is None:
            return
        index = self._chart_index()
        model = self._session.model if self._session else ""
        applied = 0
        for chart in index.charts_referencing(old_name, model=model):
            try:
                self._edits.retarget(chart.game_path, old_name, new_name)
                applied += 1
            except EditError as exc:
                self.statusBar().showMessage(str(exc))
                return
        self._after_edit()
        self.statusBar().showMessage(
            f"{new_name} now drives {applied} chart(s) that used {old_name}"
        )

    def _nearest_bone(self, point):
        """The bone a picked point should hang off — the closest one in world space."""

        session = self._session
        if session is None or session.hierarchy is None:
            return None
        best = None
        best_distance = None
        for bone in session.hierarchy:
            if not any(bone.bind_matrix):
                continue
            distance = bone.world_position.distance_to(point)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best = bone
        return best

    def _on_surface_picked(self, x: float, y: float, z: float) -> None:
        """A click in pick mode: open the dialog already aimed at that spot."""

        point = Vec3(float(x), float(y), float(z))
        bone = self._nearest_bone(point)
        if bone is None:
            self.statusBar().showMessage("No bone to attach that point to")
            return
        self.statusBar().showMessage(
            f"Picked a point on {bone.name} — naming the attach point"
        )
        self._create_socket(picked=point)
        # One pick per arming: leaving the mode live means the next orbit drag creates
        # another socket.
        position = self._mode_box.findData("off")
        if position >= 0:
            self._mode_box.setCurrentIndex(position)

    def _on_mode_changed(self, _index: int) -> None:
        mode = str(self._mode_box.currentData() or "off")
        self._viewport.set_edit_mode(mode)
        # Rotation snap only means anything in rotate mode; the step box only in move mode.
        self._angle_box.setEnabled(mode in ("rotate", "tilt"))
        self._step_box.setEnabled(mode == "move")
        if mode == "route":
            self.statusBar().showMessage(self._route_hint())
        elif mode == "pick":
            self.statusBar().showMessage(
                "Click the body where the attach point should sit — it will be parented to "
                "the nearest bone. Needs Meshes on."
            )
            self._ensure_meshes_visible()

    # ── new attach point (Tier A2) ──────────────────────────────────

    def _socket_files(self):
        """The socket files a new socket may be defined in, labelled for the dialog.

        Body sockets and item child sockets live in different files and mean different things —
        a body socket is a place on the character, a child socket is a frame on the item — so the
        choice is explicit rather than inferred.
        """

        session = self._session
        if session is None:
            return []
        files = []
        seen = set()
        for placed in session.placed_sockets():
            path = placed.socket.source_file
            if path and path not in seen:
                seen.add(path)
                files.append((f"{session.label} body sockets  ({path.rsplit('/', 1)[-1]})", path))
        weapon = session.weapon
        if weapon is not None and weapon.game_path not in seen:
            files.append(
                (f"{weapon.weapon_id} child sockets  (on the item)", weapon.game_path)
            )
        return files

    def _retarget_length_target(self):
        """The name length that would let the selected chart socket be retargeted.

        Surfaced because it is otherwise invisible: the Animation tab simply offers no candidates
        for `Spine2_B_SubWeapon_Socket`, and nothing tells the user that 25 characters is the way
        out of that.
        """

        chart_socket = str(getattr(self, "_chart_socket_box", None) and
                           self._chart_socket_box.currentData() or "")
        if not chart_socket or self._edits is None:
            return 0, ""
        from .animation import retarget_candidates

        if retarget_candidates(chart_socket, defined_sockets=self._edits.defined_sockets()):
            return 0, ""  # already retargetable; no need to steer the name
        return len(chart_socket), (
            f"No defined socket matches the {len(chart_socket)} characters of "
            f"{chart_socket!r}, so the draw animation cannot be retargeted yet. A socket of "
            "exactly that length unblocks it."
        )

    def _create_socket(self, picked=None) -> None:
        session = self._session
        if session is None or self._edits is None:
            return

        files = self._socket_files()
        if not files:
            self.statusBar().showMessage("No socket file to define a socket in")
            return

        # A picked point arrives in world space; a socket is stored relative to its parent
        # bone, so it has to be taken into that bone's frame or it lands at the origin.
        start_translation = None
        parent_hint = ""
        picked_hint = ""
        if picked is not None and session.hierarchy is not None:
            bone = self._nearest_bone(picked)
            if bone is not None:
                parent_hint = bone.name
                start_translation = world_to_bone(picked, bone)
                picked_hint = (
                    f"picked on {bone.name}, "
                    f"{start_translation.distance_to(Vec3()):.3f} m from the bone"
                )

        sockets_by_file: dict = {}
        for _label, path in files:
            document_sockets = {}
            for placed in session.placed_sockets():
                if placed.socket.source_file == path:
                    document_sockets[placed.name] = placed.socket
            weapon = session.weapon
            if weapon is not None and weapon.game_path == path:
                document_sockets = dict(weapon.sockets)
            sockets_by_file[path] = document_sockets

        preferred = self._socket_file_of(self._selected_socket) if self._selected_socket else ""
        length, reason = self._retarget_length_target()
        dialog = NewSocketDialog(
            self,
            files=files,
            sockets_by_file=sockets_by_file,
            bones=[bone.name for bone in session.hierarchy] if session.hierarchy else [],
            preferred_file=preferred,
            copy_from=self._selected_socket,
            target_length=length,
            target_length_reason=reason,
            start_translation=start_translation,
            preferred_parent=parent_hint,
            picked_hint=picked_hint,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        socket = dialog.socket()
        try:
            self._edits.add_socket(dialog.game_path, socket)
        except EditError as exc:
            QMessageBox.warning(self, "Could not create the socket", str(exc))
            return

        self._after_edit()
        self._populate_parts()
        # Select it so the very next thing the user does — nudge, rotate, route — lands on it.
        self._select_socket(socket.name)
        self._offer_animation_binding(socket.name)
        where = "on the item" if socket.parent_bone == "" else f"on {socket.parent_bone}"
        self.statusBar().showMessage(
            f"Created {socket.name} {where} — route a part to it, or retarget an animation to it"
        )

    def _use_selected_as_orientation(self) -> None:
        """Route the selected part's child socket to the selected socket, for the current role."""

        session = self._session
        if session is None or self._edits is None:
            return
        weapon = session.weapon
        target = self._selected_socket
        if weapon is None or target not in weapon.sockets:
            self.statusBar().showMessage(
                "Select a child socket on the item first — that is what carries orientation"
            )
            return
        binding = next(
            (b for b in session.bindings() if b.part_name == self._selected_part), None
        )
        if binding is None or not binding.part.source_file:
            self.statusBar().showMessage("Select a part to give an orientation to")
            return

        role = self._mesh_role_box.currentData() or "stowed"
        held = role == "held"
        field = "out_child_socket" if held else "in_child_socket"
        previous = (
            binding.part.out_child_socket if held else binding.part.in_child_socket
        ) or "(none)"
        if previous == target:
            self.statusBar().showMessage(f"{binding.part_name} already uses {target} when {role}")
            return
        try:
            self._edits.set_route(binding.part.source_file, binding.part_name, field, target)
        except EditError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self._after_edit()
        self._populate_parts()
        self.statusBar().showMessage(
            f"{binding.part_name} ({role}) now aimed by {target} (was {previous})"
        )

    def _route_hint(self) -> str:
        part = self._selected_part or "(no part selected)"
        role = self._mesh_role_box.currentData() or "stowed"
        return f"Route mode: click a socket to carry {part} when {role}"

    def _on_socket_clicked(self, socket_name: str) -> None:
        """A viewport socket click means *select*, except in route mode, where it means *use*."""

        if str(self._mode_box.currentData() or "off") == "route":
            self._route_selected_part_to(socket_name)
            return
        self._select_socket(socket_name)

    def _route_selected_part_to(self, socket_name: str) -> None:
        """Point the selected part's socket for the current role at the clicked socket.

        This is the hip-to-back edit, and it is Tier B: only the descriptor's routing attribute
        changes, so no socket definition and no geometry is touched. `set_route` refuses a socket
        nothing defines, which is the failure that used to produce a mod that crashed on load.
        """

        session = self._session
        if session is None or self._edits is None:
            return
        part_name = self._selected_part
        if not part_name:
            self.statusBar().showMessage("Select a part first — then click a socket to route it")
            return
        binding = next((b for b in session.bindings() if b.part_name == part_name), None)
        if binding is None or not binding.part.source_file:
            self.statusBar().showMessage(f"No descriptor row to re-route for {part_name}")
            return

        role = self._mesh_role_box.currentData() or "stowed"
        field = "in_socket" if role == "stowed" else "out_socket"
        previous = getattr(binding.part, field, "") or "(none)"
        if previous == socket_name:
            self.statusBar().showMessage(f"{part_name} already uses {socket_name} when {role}")
            return
        try:
            self._edits.set_route(binding.part.source_file, part_name, field, socket_name)
        except EditError as exc:
            self.statusBar().showMessage(str(exc))
            return
        note = self._follow_child_socket(binding, socket_name, role)
        self._after_edit()
        # Re-label the dropdown so the new route is visible where the target was chosen.
        self._populate_parts()
        if role == "stowed":
            note += self._ensure_blade_hangs_down(socket_name)
            note += self._warn_if_angle_is_wrong(socket_name)
        self.statusBar().showMessage(
            f"Routed {part_name} ({role}): {previous} -> {socket_name}{note}"
        )

    def _follow_child_socket(self, binding, socket_name: str, role: str) -> str:
        """Move the child socket to match the new body socket, when the item defines one.

        The two are a pair in every vanilla row, and the child socket is what holds the item's
        *orientation* — so routing the body socket alone leaves a back-slung sword hanging at the
        hip's angle. Where the item has no matching child socket (a one-hand sword has no back
        one) the orientation is inherited and the user is told to fix it with Rotate or Tilt,
        rather than the tool silently routing to something undefined.
        """

        session = self._session
        if session is None or self._edits is None:
            return ""
        held = role == "held"
        wanted = session.conventional_child_socket(socket_name, held=held)
        if not wanted and not held:
            # The live bindings resolve against the selected weapon, so the pairing this move
            # needs may simply not be among them.
            from . import carry as _carry

            wanted = _carry.FALLBACK_CHILD_SOCKETS.get(socket_name, "")
        part = binding.part
        current = part.out_child_socket if held else part.in_child_socket
        if not wanted or wanted == current:
            return ""

        weapon = session.weapon
        if weapon is None:
            return ""
        note = ""
        if wanted not in weapon.sockets:
            note = self._borrow_child_socket(weapon, wanted, current)
            if not note:
                return (
                    f"  —  orientation still from {current or '(none)'}: this item has no "
                    f"{wanted} and no other item defines one, so use Rotate or Tilt to aim it"
                )
        field = "out_child_socket" if held else "in_child_socket"
        try:
            self._edits.set_route(part.source_file, part.part_name, field, wanted)
        except EditError:
            # A child socket the item lists but no loaded file defines: keep the body route,
            # which is valid on its own, and leave the orientation for the user to adjust.
            return f"  —  orientation still from {current or '(none)'}"
        return f"  (orientation {current or '(none)'} -> {wanted}){note}"

    def _blade_points_up(self, socket_name: str) -> bool:
        """Does the stowed weapon stick upward out of its attachment point?

        A stowed weapon always hangs *down* from where it is fixed — off the hip, or down the
        back from the shoulder. So the far end of the mesh should sit below the socket, and
        when it does not the item is upside down. Measured on the placed geometry, which is
        the only thing that cannot disagree with what is on screen: every lookup-based check
        so far has passed while the sword hung inverted.
        """

        session = self._session
        if session is None:
            return False
        placed = {p.name: p.world_position for p in session.placed_sockets()}
        anchor = placed.get(socket_name)
        mesh = getattr(self._viewport, "_weapon", None)
        if anchor is None or mesh is None or not getattr(mesh, "vertices", ()):
            return False
        far = max(mesh.vertices, key=lambda v: anchor.distance_to(v))
        # A hand's-breadth of slack, so a horizontal item is not called inverted.
        return far.y > anchor.y + 0.05

    def _ensure_blade_hangs_down(self, socket_name: str) -> str:
        """Flip the item if it ended up pointing the wrong way, and say so.

        The stand-in angle is looked up by name, and every path that can fail — no descriptor
        row pairs the socket, the item's file is not loaded, another item defines it
        differently — fails by leaving the old angle in place. Rather than add a fourth guess,
        this checks the result and corrects it: a half turn about Y is exactly the difference
        between the hip angle and the back one.
        """

        from . import carry as _carry

        session = self._session
        if session is None or self._edits is None:
            return ""
        if _carry.zone_of(socket_name) not in ("hip", "back"):
            return ""
        refresh = getattr(self, "_refresh_meshes", None)
        if refresh is None:
            return ""  # no viewport: nothing placed to measure
        refresh()
        if not self._blade_points_up(socket_name):
            return ""

        binding = next(
            (b for b in session.bindings() if b.part_name == self._selected_part), None
        )
        weapon = session.weapon
        child = getattr(getattr(binding, "part", None), "in_child_socket", "") or ""
        if weapon is None or not child or child not in weapon.sockets:
            return "  —  it is upside down and there is no angle on the item to correct"
        current = weapon.sockets[child]
        try:
            self._edits.set_rotation_euler(
                weapon.game_path, child, *self._flipped_euler(current)
            )
        except EditError:
            return "  —  it is upside down and the correction could not be applied"
        self._after_edit()
        self._refresh_meshes()
        if self._blade_points_up(socket_name):
            return "  —  it is still upside down; aim it by hand with Rotate or Tilt"
        return "  (turned it the right way up)"

    @staticmethod
    def _flipped_euler(socket):
        """The socket's angle with a half turn about Y added, in degrees.

        A half turn about Y is exactly what separates the hip child socket (identity) from the
        back one (0, 1, 0, 0) on every weapon in the corpus, so it is the correction an
        upside-down stow needs.
        """

        from .model import Quat

        a = socket.rotation
        # Composing with (0, 1, 0, 0): the closed form is short enough to spell out, and
        # avoids a general multiply this module has no other use for.
        turned = Quat(-a.z, a.w, a.x, -a.y).normalized()
        return turned.to_euler_degrees()

    def _warn_if_angle_is_wrong(self, socket_name: str) -> str:
        """Say so when an item is left aimed for a different part of the body.

        Silence here is what produced a sword hanging upside down on the back: the child
        socket still said `Pelvis_L_ChildSocket`, which is an identity rotation, while the
        back needs a half turn. The check is cheap and the name carries the answer, so there
        is no reason for the tool to leave it to the eye.
        """

        from . import carry as _carry

        session = self._session
        binding = next(
            (b for b in (session.bindings() if session else [])
             if b.part_name == self._selected_part),
            None,
        )
        if binding is None:
            return ""
        child = binding.part.in_child_socket or ""
        want_zone = _carry.zone_of(socket_name)
        # The child socket is named for the body socket it belongs with, so its zone is
        # readable the same way.
        have_zone = _carry.zone_of(child.replace("ChildSocket", "Socket"))
        if not child or not want_zone or not have_zone or want_zone == have_zone:
            return ""
        return (
            f"  —  WARNING: it is still aimed by {child}, which belongs to the "
            f"{_carry.ZONE_LABELS.get(have_zone, have_zone).lower()}, so it will hang at the "
            f"wrong angle. Select the socket you want and press {AIM_LABEL}."
        )

    def _borrow_child_socket(self, weapon, wanted: str, current: str) -> str:
        """Give the item the child socket it lacks, using vanilla's angle for that spot.

        A one-hand sword defines only hip child sockets, because the game never slings it on
        the back. Routing it there left it on the hip's identity rotation, and the back socket
        is a 180-degree turn about Y — which is precisely why the blade came out upside down.

        The angle is copied from whichever item does define that child socket. That is safe
        because every weapon shares one local axis convention: all of them, one-hand and
        two-hand alike, put `Basic_ChildSocket` at the same translation and rotation. The
        translation is *not* copied — it is the grip offset along the blade, and a two-hand
        sword's -0.470 would slide a shorter weapon far off its own handle, so the item keeps
        the offset it already had.
        """

        session = self._session
        game_path = getattr(weapon, "game_path", "")
        lookup = getattr(session, "borrowed_child_socket", None)
        if session is None or self._edits is None or not game_path or lookup is None:
            return ""
        source = lookup(wanted)
        if source is None:
            return ""
        # Keep the offset the item was already hanging by, not its grip: `Basic_ChildSocket`
        # is where the hand holds it, which is a different point along the blade from where it
        # rests against the body.
        existing = weapon.sockets.get(current)
        borrowed = replace(
            source,
            name=wanted,
            source_file=game_path,
            translation=existing.translation if existing is not None else source.translation,
        )
        try:
            self._edits.add_socket(game_path, borrowed)
        except EditError:
            return ""
        return f", angle borrowed from vanilla's {wanted}"

    def _on_weapon_clicked(self) -> None:
        """Clicking the item selects the socket that positions it, for the current role.

        The *child* socket is chosen, not the body socket: it is per-item, so editing it cannot
        disturb the other parts routed through the same body socket (RHand_Socket carries 42).
        """

        session = self._session
        if session is None:
            return
        binding = next(
            (b for b in session.bindings() if b.part_name == (self._selected_part or "")), None
        )
        if binding is None:
            binding = next(
                (b for b in session.bindings() if b.part_name == "CD_MainWeapon_Sword_R"), None
            )
        if binding is None:
            return
        role = self._mesh_role_box.currentData() or "stowed"
        child = (
            binding.part.in_child_socket if role == "stowed" else binding.part.out_child_socket
        )
        target = child or (
            binding.part.in_socket if role == "stowed" else binding.part.out_socket
        )
        if not target:
            return
        self._select_socket(target)
        self.statusBar().showMessage(
            f"Selected {target} — the {role} offset for {binding.part_name}"
        )

    def _on_socket_rolled(self, socket_name: str, degrees: float) -> None:
        """Tilt: roll the item about its own long axis, in the item's *local* space.

        Passing the world blade axis through the bone-space conversion looked right and was not:
        the child socket is composed as its inverse, so the rotation lands in a different frame
        and the blade drifted off its own direction. Rotating about the local long axis is a
        true roll — measured drift 0.18 degrees, which is float noise.
        """

        if self._edits is None or self._session is None:
            return
        if socket_name != self._selected_socket:
            self._select_socket(socket_name)
        path = self._socket_file_of(self._selected_socket)
        axis = self._local_blade_axis
        if not path or axis is None:
            self.statusBar().showMessage("Select a weapon to roll along its blade")
            return
        try:
            self._edits.rotate_by(path, self._selected_socket, axis, degrees)
        except EditError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self._after_edit()

    def _on_socket_rotated(
        self, socket_name: str, ax: float, ay: float, az: float, degrees: float
    ) -> None:
        """Apply a gizmo twist. The axis arrives in world space and must be converted."""

        if self._edits is None or self._session is None:
            return
        if socket_name != self._selected_socket:
            self._select_socket(socket_name)
        path = self._socket_file_of(self._selected_socket)
        if not path:
            self.statusBar().showMessage(f"No file defines {self._selected_socket}")
            return
        # A socket's rotation is stored in its parent bone's space, so a world axis would
        # otherwise twist about the wrong direction entirely.
        axis = self._session.world_axis_for_socket(self._selected_socket, Vec3(ax, ay, az))
        try:
            self._edits.rotate_by(path, self._selected_socket, axis, degrees)
        except EditError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self._after_edit()

    def _apply_euler(self) -> None:
        if self._edits is None or not self._selected_socket:
            return
        path = self._socket_file_of(self._selected_socket)
        if not path:
            return
        roll, pitch, yaw = (box.value() for box in self._euler)
        try:
            self._edits.set_rotation_euler(path, self._selected_socket, roll, pitch, yaw)
        except EditError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self._after_edit()

    def _revert_socket(self) -> None:
        """Restore one socket to vanilla by re-applying its original values."""

        if self._edits is None or not self._selected_socket:
            return
        path = self._socket_file_of(self._selected_socket)
        state = self._edits.state(path, self._selected_socket) if path else None
        if state is None:
            return
        try:
            if state.translation_changed:
                self._edits.set_translation(path, state.name, state.original.translation)
            if state.rotation_changed:
                self._edits.set_rotation_quaternion(path, state.name, state.original.rotation)
        except EditError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self._after_edit()

    def _undo(self) -> None:
        if self._edits is not None and self._edits.undo():
            self._after_edit()

    def _redo(self) -> None:
        if self._edits is not None and self._edits.redo():
            self._after_edit()

    def _after_edit(self) -> None:
        """Re-resolve, re-render, and refresh every dependent pane after an edit."""

        self._rebuild_session_from_edits()
        self._refresh_scene()
        self._refresh_diff()
        self._refresh_edit_panel()
        self._refresh_animation()
        self._populate_tree()
        if self._selected_socket:
            self._inspector.setHtml(inspector_html(self._describe_socket(self._selected_socket)))
        self._report_status()

    def _rebuild_session_from_edits(self) -> None:
        """Feed edited bytes back into the resolver so the view reflects pending changes."""

        session = self._session
        if session is None or self._edits is None:
            return
        weapon_id = session.weapon.weapon_id if session.weapon else ""
        overrides = self._edits.preview()
        if not overrides:
            rebuilt = PlacementSession.from_baseline(self._baseline, session.model)
        else:
            from .resolver import PlacementResolver

            resolver = PlacementResolver()
            for path in self._baseline.paths():
                from .documents import is_descriptor_file, is_socket_file

                if not (is_socket_file(path) or is_descriptor_file(path)):
                    continue
                resolver.add_files({path: overrides.get(path, self._baseline.read(path))})
            rebuilt = PlacementSession(session.model, session.hierarchy, resolver)
        for weapon in rebuilt.weapons():
            if weapon.weapon_id == weapon_id:
                rebuilt.select_weapon(weapon)
                break
        self._session = rebuilt
        self._bindings = rebuilt.bindings()

    def _refresh_diff(self) -> None:
        from .report_style import pending_changes_html

        if self._edits is None:
            self._diff_view.setHtml(pending_changes_html([], []))
            return
        lines = self._edits.diff()
        plan = self._edits.to_plan()
        header = [
            f"{len(self._edits.commands())} edit(s), "
            f"{len(plan.operations)} operation(s), "
            f"{len(self._edits.modified_paths())} file(s)",
            f"tiers: {plan.tier_counts() or '{}'}",
            "",
        ]
        self._diff_view.setHtml(pending_changes_html(header, lines))
        # Address the tab by its widget: a hardcoded index silently renamed the wrong tab
        # the moment Animation was inserted ahead of it.
        self._lower.setTabText(
            self._lower.indexOf(self._diff_view), f"Pending changes ({len(plan.operations)})"
        )

    def _refresh_edit_panel(self) -> None:
        editable = bool(self._selected_socket) and bool(self._socket_file_of(self._selected_socket))
        for button in self._nudge_buttons:
            button.setEnabled(editable)
        for box in self._euler:
            box.setEnabled(editable)
        self._revert_button.setEnabled(editable)
        self._undo_button.setEnabled(self._edits is not None and self._edits.can_undo)
        self._redo_button.setEnabled(self._edits is not None and self._edits.can_redo)
        has_changes = bool(self._edits and self._edits.modified_paths())
        self._export_button.setEnabled(has_changes)
        self._package_button.setEnabled(has_changes)
        self._new_socket_button.setEnabled(self._session is not None and self._edits is not None)
        # Only a child socket on the item can aim it, so the control is live only for those.
        weapon = self._session.weapon if self._session is not None else None
        self._use_orientation_button.setEnabled(
            bool(self._selected_part)
            and weapon is not None
            and self._selected_socket in weapon.sockets
        )

        if not self._selected_socket:
            self._edit_target.setText("(no socket selected)")
            return

        path = self._socket_file_of(self._selected_socket)
        state = self._edits.state(path, self._selected_socket) if (self._edits and path) else None
        # Report whichever fields actually changed. Showing only a translation delta made a
        # rotation-only edit read as "modified  Δ +0.000 +0.000 +0.000", which looks like a bug.
        suffix = ""
        if state is not None and state.modified:
            parts: List[str] = []
            if state.translation_changed:
                delta = state.translation_delta()
                parts.append(f"move Δ {delta.x:+.3f} {delta.y:+.3f} {delta.z:+.3f}")
            if state.rotation_changed:
                # Angle between quaternions, not a euler difference: at pitch +/-90 the euler
                # triples are identical for rotations 35 degrees apart, so the delta read zero.
                parts.append(
                    f"rotated {state.current.rotation.angle_to(state.original.rotation):.1f}°"
                )
            if state.parent_changed:
                parts.append(f"reparented -> {state.current.parent_bone}")
            suffix = f"   [modified: {', '.join(parts)}]"
        elif not path:
            suffix = "   [no defining file — not editable]"
        self._edit_target.setText(self._selected_socket + suffix)

        if state is not None:
            roll, pitch, yaw = state.current.rotation.to_euler_degrees()
            for box, value in zip(self._euler, (roll, pitch, yaw)):
                box.blockSignals(True)
                box.setValue(value)
                box.blockSignals(False)

    def _build_packages(self) -> None:
        """Emit every manager layout from the current plan — one plan, three packages."""

        from .packaging import PackageMetadata, PackagingError, build_all

        if self._edits is None or not self._edits.modified_paths():
            return
        target = QFileDialog.getExistingDirectory(self, "Build packages into")
        if not target:
            return

        name, ok = QInputDialog.getText(
            self, "Package name", "Mod name:", text="Placement Studio Mod"
        )
        if not ok or not name.strip():
            return

        metadata = PackageMetadata(
            name=name.strip(),
            version="1.0.0",
            author="",
            description="Placement and animation changes built with Placement Studio.",
        )
        try:
            results = build_all(
                self._edits.to_plan(),
                self._edits.preview(),
                metadata,
                out_root=Path(target),
                baseline=self._baseline,
            )
        except PackagingError as exc:
            QMessageBox.warning(self, "Packaging failed", str(exc))
            return

        QMessageBox.information(
            self,
            "Packages built",
            "\n".join(result.describe() for result in results),
        )
        self.statusBar().showMessage(f"Built {len(results)} package(s) in {target}")

    def _export(self) -> None:
        if self._edits is None or not self._edits.modified_paths():
            return
        target = QFileDialog.getExistingDirectory(self, "Export edited files to")
        if not target:
            return
        written = self._edits.write(target)
        QMessageBox.information(
            self,
            "Exported",
            f"Wrote {len(written)} file(s) under:\n{target}\n\n" + "\n".join(written[:12]),
        )
