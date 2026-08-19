"""New Item Studio: place the effect on the item in the resident .NET viewport.

The item's mesh is the reference (drawn as its wire), the effect's bounding box the
mesh the placement gizmo moves and scales; every drag comes back as a delta the
dialog adds to the offset and scale it was opened with, and the numbers next to
the viewport are the same numbers the panel writes into the plan. Nothing here
touches the archives.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.effect_placement_preview import (
    ANCHOR_TINT,
    BODY_TINT,
    ITEM_TINT,
    REACH_TINT,
    EffectPlacementPreview,
    build_effect_placement_package,
    next_scale,
)
from cdmw.services.effect_preview_model import EffectPreview
from cdmw.ui.new_item.ui_kit import DetailsToggle
from cdmw.workers.utility_workers import UtilityWorker

Vec3 = Tuple[float, float, float]

__all__ = ["EffectPlacementDialog", "describe_effect_preview"]


def describe_effect_preview(preview: Optional[EffectPreview]) -> str:
    """The emitters as the description read them, one line each, then what it could not read."""

    if preview is None:
        return ""
    lines = []
    for emitter in preview.emitters:
        short = emitter.name.rsplit("/", 1)[-1]
        rate = emitter.burst * emitter.bursts_per_second
        colour = max(emitter.color_over_life, key=max) if emitter.color_over_life else emitter.emissive_color
        top = max(colour) or 1.0
        hex_colour = "#%02x%02x%02x" % tuple(int(round(255 * min(1.0, c / top))) for c in colour)
        texture = emitter.texture.rsplit("/", 1)[-1] if emitter.texture else "no texture"
        loop = "loops" if emitter.loop else "once"
        lines.append(f"{short}: {emitter.kind}, {rate:.0f}/s, {emitter.life[0]:.2f}-{emitter.life[1]:.2f} s, {loop}, {emitter.blend}, {texture}, {hex_colour}")
    if not lines:
        lines.append("The effect names no emitters the description could read.")
    lines.extend(preview.notes)
    return "\n".join(lines)


#: how many times the item's own length a reach may be before its frame starts hidden
REACH_HIDDEN_ABOVE = 6.0

#: The standing views, as the camera angles (yaw, pitch) in degrees the host takes, in
#: the order the buttons appear. The game holds a weapon at the origin with the blade
#: toward -z and the character facing the same way, so yaw 0 looks the character in the
#: face and yaw 90 stands to its side, which is the view that shows a blade end to end.
#: The titles and what each one is for live at the buttons, where the localizer finds them.
STANDING_VIEW_ANGLES: tuple = ((0.0, 8.0), (90.0, 8.0), (0.0, -80.0), (-35.0, 20.0))


#: the swatch for the particles themselves, which have no one colour: the warm orange
#: most of the shipped weapon effects land on
PARTICLE_TINT = (0.75, 0.25, 0.05)


def _swatch(tint: Sequence[float]) -> str:
    """One of the scene's own colours as a small square of HTML, so the legend cannot
    drift from what the viewport draws."""

    red, green, blue = (max(0, min(255, int(round(255 * float(channel) ** (1 / 2.2))))) for channel in tuple(tint)[:3])
    return f'<span style="color:#{red:02x}{green:02x}{blue:02x}">&#9632;</span>'


class EffectPlacementDialog(QDialog):
    """Move and scale the effect's box on the item; read `offset` and `scale` after accept."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        item_mesh: ParsedMesh,
        box_min: Vec3,
        box_max: Vec3,
        offset: Vec3 = (0.0, 0.0, 0.0),
        scale: float = 1.0,
        effect_label: str = "",
        item_label: str = "",  # "placed", "applied", "template", or "" for no line
        output_root: Optional[Path] = None,
        host_factory=None,
        effect_preview: Optional[EffectPreview] = None,
        texture_reader: Optional[Callable[[str], Optional[bytes]]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Place the effect on the item")
        self.setModal(True)
        self.resize(960, 640)
        self._item_mesh = item_mesh
        self._box = (tuple(float(v) for v in box_min), tuple(float(v) for v in box_max))
        self.offset: Vec3 = tuple(float(v) for v in offset)  # type: ignore[assignment]
        self.scale: float = float(scale)
        self._output_root = Path(output_root) if output_root is not None else Path(tempfile.gettempdir()) / "cdmw_effect_placement"
        self._preview: Optional[EffectPlacementPreview] = None
        self._effect_preview = effect_preview
        self._texture_reader = texture_reader
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._closed = False

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"{effect_label or 'The effect'} on the item: drag the orange anchor with the gizmo (Move / Scale) or type the numbers. "
            "The character behind the item is there for scale, and the buttons under the viewport turn it to the standing views."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        # which mesh the wire is: the studio only builds the imported model into the item
        # once Apply the placement has run, and before that the effect was judged against
        # the template's blade without saying so
        showing = QLabel("")
        if item_label == "placed":
            showing.setText("Showing your imported model, at the placement set on step 3.")
        elif item_label == "applied":
            showing.setText("Showing your imported model, as applied.")
        elif item_label == "template":
            showing.setText("Showing the template's model; import one on step 3 to place the effect on your own.")
        showing.setWordWrap(True)
        showing.setVisible(bool(showing.text()))
        layout.addWidget(showing)
        self.showing_label = showing
        body = QHBoxLayout()
        layout.addLayout(body, 1)

        self.host = None
        factory = host_factory or _default_host_factory
        try:
            self.host = factory(self)
        except Exception as exc:  # noqa: BLE001 - the viewport is optional; the numbers still work
            self.host = None
            self._host_error = str(exc)
        else:
            self._host_error = ""
        self.view_buttons: list[QPushButton] = []
        if self.host is not None:
            self.host.setMinimumSize(560, 420)
            self.host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            viewport_column = QVBoxLayout()
            viewport_column.setContentsMargins(0, 0, 0, 0)
            viewport_column.addWidget(self.host, 1)
            views = QHBoxLayout()
            views.addWidget(QLabel("View"))
            self._add_view_button(views, "Front", "Looking the character in the face, with the blade pointing at you.")
            self._add_view_button(views, "Side", "From the character's side: the blade end to end, and how far up it the effect sits.")
            self._add_view_button(views, "Top", "From above: how far in front of or behind the item the effect sits.")
            self._add_view_button(views, "Angled", "The three-quarter view the dialog opens on.")
            views.addStretch(1)
            viewport_column.addLayout(views)
            body.addLayout(viewport_column, 1)
        else:
            missing = QLabel("The resident viewport is not available here; set the numbers by hand." + (f" ({self._host_error})" if self._host_error else ""))
            missing.setWordWrap(True)
            body.addWidget(missing, 1)

        # the panel keeps to its own width: left to itself it takes half the dialog and
        # the viewport -- the thing being looked at -- gets what is left
        side_panel = QWidget()
        side_panel.setMaximumWidth(360)
        side = QVBoxLayout(side_panel)
        side.setContentsMargins(0, 0, 0, 0)
        body.addWidget(side_panel)
        tools = QHBoxLayout()
        self.move_button = QPushButton("Move")
        self.move_button.setCheckable(True)
        self.move_button.setChecked(True)
        self.scale_button = QPushButton("Scale")
        self.scale_button.setCheckable(True)
        self.move_button.clicked.connect(lambda: self._choose_tool("move"))
        self.scale_button.clicked.connect(lambda: self._choose_tool("scale"))
        tools.addWidget(self.move_button)
        tools.addWidget(self.scale_button)
        side.addLayout(tools)
        form = QFormLayout()
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 10.0)
        self.scale_spin.setDecimals(2)
        self.scale_spin.setSingleStep(0.05)
        self.scale_spin.setValue(self.scale)
        self.scale_spin.valueChanged.connect(self._numbers_edited)
        form.addRow("Scale", self.scale_spin)
        self.offset_spins: list[QDoubleSpinBox] = []
        for axis, value in zip(("Offset x (m)", "Offset y (m)", "Offset z (m)"), self.offset):
            spin = QDoubleSpinBox()
            spin.setRange(-5.0, 5.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.01)
            spin.setValue(float(value))
            spin.valueChanged.connect(self._numbers_edited)
            form.addRow(axis, spin)
            self.offset_spins.append(spin)
        side.addLayout(form)
        width, height, depth = (high - low for low, high in zip(*self._box))
        self._box_size = (width, height, depth)
        places = QHBoxLayout()
        places.addWidget(QLabel("Put it at"))
        self._add_place_button(places, "Hand", "hand", "Put the effect's origin back at the hand the item is held by.")
        self._add_place_button(places, "Middle", "middle", "Put the effect's origin at the middle of the item.")
        self._add_place_button(places, "Tip", "tip", "Put the effect's origin at the far end of the item: a blade's point.")
        places.addStretch(1)
        side.addLayout(places)
        reach_row = QHBoxLayout()
        self.show_reach = QCheckBox("Show the reach")
        self.show_reach.setToolTip("The effect's own bounding box as a thin frame, at this scale and offset: how far it can throw particles.")
        # A frame around a one-metre sword is worth seeing; a frame twenty metres across is
        # a pair of orange columns crossing the view with the item a speck between them, and
        # the camera opens on the frame rather than on the thing being placed. Effects made
        # for bosses and set pieces reach that far, so their frame starts hidden.
        low, high = self._item_bounds()
        item_length = max(high[axis] - low[axis] for axis in range(3))
        reach_length = max(width, height, depth) * self.scale
        self._reach_dwarfs_the_item = bool(item_length > 0 and reach_length > item_length * REACH_HIDDEN_ABOVE)
        self.show_reach.setChecked(not self._reach_dwarfs_the_item)
        self.show_reach.toggled.connect(lambda _checked: self._reach_toggled())
        reach_row.addWidget(self.show_reach)
        self.fit_button = QPushButton("Fit it to the item")
        self.fit_button.setToolTip("Set the scale so the effect's reach is about as long as the item; the offset is left alone.")
        self.fit_button.clicked.connect(self._fit_reach_to_item)
        reach_row.addWidget(self.fit_button)
        reach_row.addStretch(1)
        side.addLayout(reach_row)
        self.show_character = QCheckBox("Show the character")
        self.show_character.setToolTip("A figure 1.75 m tall holding the item, so the effect's size reads against something known.")
        self.show_character.setChecked(True)
        self.show_character.toggled.connect(lambda _checked: self._apply_scene_visibility())
        side.addWidget(self.show_character)
        self.size_label = QLabel("")
        self.size_label.setWordWrap(True)
        side.addWidget(self.size_label)
        # what each thing in the viewport is, in the colour it is drawn: the question a
        # reader asks first, and one the numbers beside the viewport cannot answer
        self.legend_rows: dict = {}
        self._add_legend_row(side, "anchor", ANCHOR_TINT, "the effect's origin - drag this one")
        self._add_legend_row(side, "item", ITEM_TINT, "your item")
        self._add_legend_row(side, "body", BODY_TINT, "a character, 1.75 m tall, for scale")
        self._add_legend_row(side, "reach", REACH_TINT, "how far the effect can throw particles")
        self._add_legend_row(side, "particles", PARTICLE_TINT, "the particles, read approximately")
        self._refresh_legend()
        self.emitters_toggle = DetailsToggle(describe_effect_preview(effect_preview), title="What the effect is made of")
        self.emitters_label = self.emitters_toggle.body
        self.emitters_toggle.setVisible(effect_preview is not None)
        side.addWidget(self.emitters_toggle)
        self.status = QLabel("Preparing the viewport...")
        self.status.setWordWrap(True)
        side.addWidget(self.status)
        side.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        side.addWidget(buttons)
        self._refresh_size_label()

        if self.host is not None:
            self.host.alignment_drag_finished.connect(self._drag_finished)
            self.host.alignment_scale_finished.connect(self._scale_finished)
            self.host.controller.state_changed.connect(self._host_state)
            QTimer.singleShot(0, self._start_package)
        else:
            self.status.setText("")

    # ------------------------------------------------------------------ package

    def _start_package(self) -> None:
        if self._closed:
            return
        mesh, box = self._item_mesh, self._box
        root = self._output_root
        effect_preview, texture_reader = self._effect_preview, self._texture_reader

        def task(_log, stop_event: threading.Event) -> EffectPlacementPreview:
            return build_effect_placement_package(
                mesh, box[0], box[1], output_root=root, cancelled=stop_event.is_set,
                effect_preview=effect_preview, texture_reader=texture_reader,
            )

        worker = UtilityWorker(task, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        self._thread, self._worker = thread, worker
        worker.completed.connect(self._package_ready)
        worker.error.connect(lambda message: self.status.setText(f"The placement preview could not be built: {message}"))

        def finish() -> None:
            self._thread = None
            self._worker = None
            thread.quit()
            thread.wait(5000)
            worker.deleteLater()
            thread.deleteLater()

        worker.finished.connect(finish)
        thread.started.connect(worker.run)
        thread.start()

    def _package_ready(self, result: object) -> None:
        if self._closed or not isinstance(result, EffectPlacementPreview) or self.host is None:
            return
        self._preview = result
        if self.host.load_package(result.package_dir, reset_view=True):
            self.host.set_display_mode("overlay")
            self.status.setText("Loading the viewport...")
        else:
            self.status.setText("The resident viewport rejected the placement package.")

    def _host_state(self, state: str, message: str) -> None:
        if self._closed or self.host is None:
            return
        if str(state) == "ready" and self._preview is not None:
            self.host.set_display_mode("overlay")
            self.host.set_viewport_display_mode("textured")
            self.host.set_alignment_state(enabled=True)
            # the camera frames the editable role's bounds; the anchor is a few centimetres,
            # so hand it the item's bounds instead and the view opens on the item
            remember = getattr(self.host, "remember_editable_local_bounds", None)
            if callable(remember):
                low, high = self._item_bounds()
                remember(low, high)
            self._sync_host()
            self._apply_scene_visibility()
            reset = getattr(self.host, "reset_view", None)
            if callable(reset):
                reset()
            sentences = []
            if self._preview.preview_file is not None and not self._host_draws_particles():
                sentences.append("This viewport build draws no particles yet; the anchor shows where the effect sits.")
            if self._preview.missing_textures:
                sentences.append(f"{len(self._preview.missing_textures)} sprite texture(s) could not be read from the archives.")
            self.status.setText(" ".join(sentences))
        elif str(state) == "error":
            self.status.setText(str(message or "The viewport reported an error."))

    def _apply_scene_visibility(self) -> None:
        """Show or hide the reach frame and the character; the item, the anchor and the
        particles are always drawn."""

        self._refresh_legend()
        if self.host is None or self._preview is None:
            return
        hidden = []
        if not self.show_reach.isChecked():
            hidden.append(self._preview.reach_submesh_index)
        if not self.show_character.isChecked() and self._preview.body_submesh_index >= 0:
            hidden.append(self._preview.body_submesh_index)
        setter = getattr(self.host, "set_hidden_source_submeshes", None)
        if callable(setter):
            try:
                setter(tuple(hidden))
            except Exception:  # noqa: BLE001 - a host without the call keeps what it draws
                pass

    def _add_view_button(self, row: QHBoxLayout, title: str, explanation: str) -> None:
        """One standing view, at the angles `STANDING_VIEW_ANGLES` holds for it."""

        yaw, pitch = STANDING_VIEW_ANGLES[len(self.view_buttons)]
        button = QPushButton(title)
        button.setToolTip(explanation)
        button.clicked.connect(lambda _checked=False, y=yaw, p=pitch: self._look_from(y, p))
        row.addWidget(button)
        self.view_buttons.append(button)

    def _add_place_button(self, row: QHBoxLayout, title: str, where: str, explanation: str) -> None:
        button = QPushButton(title)
        button.setToolTip(explanation)
        button.clicked.connect(lambda _checked=False, target=where: self._put_it_at(target))
        row.addWidget(button)

    def _add_legend_row(self, column: QVBoxLayout, key: str, tint: Sequence[float], text: str) -> None:
        """One line of the legend: the scene's own colour, and what is drawn in it."""

        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setText(f"{_swatch(tint)} {text}")
        column.addWidget(label)
        self.legend_rows[key] = label

    def _refresh_legend(self) -> None:
        """The legend says what is on screen, so the two rows that can be turned off
        follow their checkboxes."""

        rows = getattr(self, "legend_rows", None)
        if not rows:
            return
        rows["body"].setVisible(self.show_character.isChecked())
        rows["reach"].setVisible(self.show_reach.isChecked())

    def _look_from(self, yaw: float, pitch: float) -> None:
        """Turn the camera to one of the standing views and fit the item in it again."""

        host = self.host
        if host is None:
            return
        setter = getattr(host, "set_view", None)
        if callable(setter):
            try:
                setter(yaw=float(yaw), pitch=float(pitch), zoom_factor=1.0, fit_to_view=True)
            except Exception:  # noqa: BLE001 - a host without the call keeps the view it has
                pass

    def _put_it_at(self, where: str) -> None:
        """Move the effect's origin to a named place on the item: the hand it is held by
        (the item's own origin), the middle of the item, or its far end. Three spin boxes
        and a mesh whose long axis is not obvious make that a guessing game otherwise."""

        low, high = self._item_bounds()
        if where == "hand":
            self._set_numbers((0.0, 0.0, 0.0), self.scale)
            self._sync_host()
            return
        centre = tuple((low[axis] + high[axis]) / 2.0 for axis in range(3))
        if where == "middle":
            self._set_numbers(centre, self.scale)
            self._sync_host()
            return
        # the tip: the far end of the longest axis, the other two held at the middle
        longest = max(range(3), key=lambda axis: high[axis] - low[axis])
        far = high[longest] if abs(high[longest]) >= abs(low[longest]) else low[longest]
        offset = list(centre)
        offset[longest] = far * 0.92
        self._set_numbers(tuple(offset), self.scale)  # type: ignore[arg-type]
        self._sync_host()

    def _reach_toggled(self) -> None:
        self._apply_scene_visibility()
        self._refresh_size_label()

    def _fit_reach_to_item(self) -> None:
        """A scale that makes the effect's reach about the item's own length: a starting
        point for effects whose reach is tens of metres around a one-metre weapon."""

        low, high = self._item_bounds()
        item = max(high[axis] - low[axis] for axis in range(3))
        reach = max(self._box_size) or 1.0
        if item <= 0 or reach <= 0:
            return
        self._set_numbers(self.offset, item / reach)
        self._sync_host()

    def _item_bounds(self) -> Tuple[Vec3, Vec3]:
        mesh = self._item_mesh
        low = tuple(float(v) for v in (getattr(mesh, "bbox_min", None) or (-0.5, -0.5, -0.5)))
        high = tuple(float(v) for v in (getattr(mesh, "bbox_max", None) or (0.5, 0.5, 0.5)))
        if all(abs(h - l) < 1e-6 for l, h in zip(low, high)):
            low, high = (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)
        return low, high  # type: ignore[return-value]

    def _host_draws_particles(self) -> bool:
        """Whether the resident helper announced the particle layer (`effect_particle_preview_v1`)."""

        host = self.host
        if host is None:
            return False
        try:
            capabilities = host.controller.capabilities
        except Exception:  # noqa: BLE001 - a fake host in tests has none
            return False
        return "effect_particle_preview_v1" in (capabilities or ())

    # ------------------------------------------------------------------ edits

    def _sync_host(self) -> None:
        if self.host is None or self._preview is None:
            return
        self.host.set_alignment_preview_transform(
            translation=self.offset, rotation_degrees=(0.0, 0.0, 0.0), scale_xyz=(self.scale, self.scale, self.scale),
        )

    def _refresh_size_label(self) -> None:
        width, height, depth = self._box_size
        low, high = self._item_bounds()
        item = max(high[axis] - low[axis] for axis in range(3))
        reach = max(width, height, depth) * self.scale
        times = f"{reach / item:.1f}x the item" if item > 0 else "unknown against the item"
        text = (
            f"Reach at scale {self.scale:.2f}: {width * self.scale:.2f} x {height * self.scale:.2f} x {depth * self.scale:.2f} m, "
            f"{times} ({item:.2f} m). The effect's own reach is {width:.2f} x {height:.2f} x {depth:.2f} m."
        )
        if getattr(self, "_reach_dwarfs_the_item", False) and not self.show_reach.isChecked():
            text += " Its frame starts hidden because it is far larger than the item; tick Show the reach to see it."
        self.size_label.setText(text)

    def _set_numbers(self, offset: Vec3, scale: float) -> None:
        self.offset = tuple(round(float(v), 4) for v in offset)  # type: ignore[assignment]
        self.scale = round(max(0.01, min(10.0, float(scale))), 3)
        for spin, value in zip(self.offset_spins, self.offset):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)
        self.scale_spin.blockSignals(True)
        self.scale_spin.setValue(self.scale)
        self.scale_spin.blockSignals(False)
        self._refresh_size_label()

    def _numbers_edited(self, *_args) -> None:
        self.offset = tuple(float(spin.value()) for spin in self.offset_spins)  # type: ignore[assignment]
        self.scale = float(self.scale_spin.value())
        self._refresh_size_label()
        self._sync_host()

    def _drag_finished(self, dx: float, dy: float, dz: float) -> None:
        self._set_numbers((self.offset[0] + dx, self.offset[1] + dy, self.offset[2] + dz), self.scale)
        self._sync_host()

    def _scale_finished(self, dx: float, dy: float, dz: float) -> None:
        self._set_numbers(self.offset, next_scale(self.scale, (dx, dy, dz)))
        self._sync_host()

    def _choose_tool(self, tool: str) -> None:
        self.move_button.setChecked(tool == "move")
        self.scale_button.setChecked(tool == "scale")
        if self.host is not None:
            self.host.set_alignment_gizmo_tool(tool)

    # ------------------------------------------------------------------ lifecycle

    def apply_deltas(self, translation: Sequence[float] = (0.0, 0.0, 0.0), scale_delta: Sequence[float] = (0.0, 0.0, 0.0)) -> None:
        """What a gizmo drag does, callable without a viewport (tests, scripts)."""

        self._drag_finished(*(float(v) for v in tuple(translation)[:3]))
        if any(abs(float(v)) > 1e-12 for v in scale_delta):
            self._scale_finished(*(float(v) for v in tuple(scale_delta)[:3]))

    def done(self, result: int) -> None:  # noqa: D401 - Qt override
        self._closed = True
        worker = self._worker
        if worker is not None:
            worker.stop()
        thread = self._thread
        if thread is not None:
            thread.quit()
            thread.wait(5000)
        host = self.host
        if host is not None:
            try:
                host.controller.shutdown()
            except Exception:  # noqa: BLE001
                pass
        preview = self._preview
        if preview is not None:
            shutil.rmtree(preview.package_dir.parent, ignore_errors=True)
        super().done(result)


def _default_host_factory(parent: QWidget):
    from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame
    from cdmw.ui.preview.profile import DotNetPreviewProfile

    return DotNetPreviewHostFrame(parent, profile=DotNetPreviewProfile.PREVIEW, terminate_on_close=True)
