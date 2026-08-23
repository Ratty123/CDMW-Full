"""New Item Studio: place the effect on the item in the resident .NET viewport.

The item's mesh is the reference (drawn solid), the effect's anchor the mesh the
placement gizmo moves, turns and scales; every drag comes back as a delta the
dialog adds to the offset, rotation and scale it was opened with, and the numbers
next to the viewport are the same numbers the panel writes into the plan. Offsets
and turns are held in the item's own frame -- the frame the game's
``_offsetTransform`` applies in -- and cross into the scene's frame at the
viewport's edge (see :class:`PlacementFrame`). Nothing here touches the archives.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Sequence, Tuple

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from cdmw.services.mesh_workflow_service import ParsedMesh
from cdmw.services.effect_placement_preview import (
    ANCHOR_TINT,
    EFFECT_AXIS_TINTS,
    framing_bounds_for,
    BODY_TINT,
    ITEM_TINT,
    REACH_TINT,
    EffectPlacementPreview,
    build_effect_placement_package,
    next_scale,
)
from cdmw.services.effect_preview_model import EffectPreview
from cdmw.services.effect_placement_rotation import wrap_degrees
from cdmw.ui.new_item.effect_placement_dialog_support import (
    BACKDROP_BLACK,
    BACKDROP_DARK,
    BACKDROP_GREY,
    BACKDROPS,
    PARTICLE_TINT,
    PlacementFrame,
    describe_effect_preview,
    remember_backdrop,
    remember_orbit_inversion,
    remembered_backdrop,
    remembered_orbit_inversion,
    swatch as _swatch,
)
from cdmw.ui.new_item.effect_placement_guided import EffectPlacementGuidedMixin
from cdmw.ui.new_item.effect_placement_package import EffectPlacementPackageMixin
from cdmw.ui.new_item.effect_placement_construction import EffectPlacementConstructionMixin
from cdmw.ui.new_item.effect_placement_constants import (
    REACH_HIDDEN_ABOVE,
    ROTATION_DECIMALS,
    ROTATION_STEP,
    SCALE_DECIMALS,
    SCALE_MAXIMUM,
    SCALE_MINIMUM,
    STANDING_VIEW_ANGLES,
)
from cdmw.ui.new_item.ui_kit import DetailsToggle
from cdmw.workers.utility_workers import UtilityWorker

Vec3 = Tuple[float, float, float]

__all__ = ["EffectPlacementDialog", "EffectPlacementWorkspace", "describe_effect_preview"]


class EffectPlacementWorkspace(
    EffectPlacementGuidedMixin,
    EffectPlacementPackageMixin,
    EffectPlacementConstructionMixin,
    QWidget,
):
    """Resident placement body shared by Step 5 and the compatibility dialog."""

    apply_requested = Signal()
    transform_changed = Signal()
    look_changed = Signal()
    _standing_view_angles = STANDING_VIEW_ANGLES

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        item_mesh: ParsedMesh,
        box_min: Vec3,
        box_max: Vec3,
        offset: Vec3 = (0.0, 0.0, 0.0),
        rotation: Vec3 = (0.0, 0.0, 0.0),
        scale: float = 1.0,
        effect_label: str = "",
        item_label: str = "",  # "placed", "applied", "template", or "" for no line
        output_root: Optional[Path] = None,
        host_factory=None,
        effect_preview: Optional[EffectPreview] = None,
        texture_reader: Optional[Callable[[str], Optional[bytes]]] = None,
        # builds the game's own character, on the worker thread: reading a rig and a body
        # out of the archives is a second the dialog should not spend frozen
        character_builder: Optional[Callable[[], object]] = None,
        color: Optional[Vec3] = None,
        intensity: float = 1.0,
        particle_size: float = 1.0,
        spawn_rate: float = 1.0,
        lifetime: float = 1.0,
        compatibility_ui: bool = False,
    ) -> None:
        super().__init__(parent)
        self._item_mesh = item_mesh
        self._box = (tuple(float(v) for v in box_min), tuple(float(v) for v in box_max))
        self.offset: Vec3 = tuple(float(v) for v in offset)  # type: ignore[assignment]
        self.rotation: Vec3 = tuple(wrap_degrees(float(v)) for v in rotation)  # type: ignore[assignment]
        self.scale: float = float(scale)
        self.color: Optional[Vec3] = None if color is None else tuple(float(v) for v in color)  # type: ignore[assignment]
        self.intensity = float(intensity)
        self.particle_size = float(particle_size)
        self.spawn_rate = float(spawn_rate)
        self.lifetime = float(lifetime)
        self._compatibility_ui = bool(compatibility_ui)
        self._output_root = Path(output_root) if output_root is not None else Path(tempfile.gettempdir()) / "cdmw_effect_placement"
        self._preview: Optional[EffectPlacementPreview] = None
        self._effect_preview = effect_preview
        self._texture_reader = texture_reader
        self._character_builder = character_builder
        #: `(name, point)` for the item's own FX sockets, once the character has been read
        self._effect_sockets: tuple = ()
        # the scene is the character's frame when there is a character to stand in it, and
        # the item's own when there is not; the offsets and the turn are the item's either way
        self._frame = PlacementFrame(None)
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._package_generation = 0
        self._active_package_generation = 0
        self._pending_package: Optional[tuple] = None
        self._loading_preview: Optional[EffectPlacementPreview] = None
        self._loading_sockets: tuple = ()
        self._loading_view_state: Optional[dict[str, object]] = None
        self._retired_previews: list[EffectPlacementPreview] = []
        self._package_ack_connected = False
        self._closed = False
        self._compatibility_only_widgets: list[QWidget] = []

        layout = self._build_placement_ui(
            effect_label=effect_label,
            item_label=item_label,
            host_factory=host_factory or _default_host_factory,
            effect_preview=effect_preview,
        )

        if not self._compatibility_ui:
            self._build_guided_presentation(layout)

        if self.host is not None:
            self.host.alignment_drag_finished.connect(self._drag_finished)
            self.host.alignment_scale_finished.connect(self._scale_finished)
            # older hosts predate the rotate tool; without the signal the Rotate
            # button still switches the gizmo, its drags just report nothing
            rotated = getattr(self.host, "alignment_rotation_finished", None)
            if rotated is not None:
                rotated.connect(self._rotation_finished)
            self.host.controller.state_changed.connect(self._host_state)
            package_applied = getattr(self.host.controller, "package_applied", None)
            if package_applied is not None:
                package_applied.connect(self._package_load_applied)
                self._package_ack_connected = True
            QTimer.singleShot(0, self._start_package)
        else:
            self.status.setText("")

    def _show_caveats(self) -> None:
        """Say what the preview could not read, before the reader trusts what it shows."""

        preview = self._effect_preview
        notes = tuple(getattr(preview, "notes", ()) or ()) if preview is not None else ()
        spawn_meshes = sorted({
            note.split("spawn mesh ", 1)[1].split(" ", 1)[0]
            for note in notes if "spawn mesh " in note and "was not read" in note
        })
        if not spawn_meshes:
            self.caveat.setVisible(False)
            return
        # short by design: the detail is in the tooltip, and a paragraph here pushed the
        # controls above it off the panel
        self.caveat.setText(f"{spawn_meshes[0]} is not in the archives, so the particles scatter here. The game draws its own shape.")
        self.caveat.setToolTip(
            "An emitter can spawn its particles on the surface of a mesh. This effect names one the archives do not "
            "carry, so the preview scatters them around the anchor instead: the anchor is where the effect starts "
            "either way, but the shape around it is a stand-in."
        )
        self.caveat.setVisible(True)

    def _apply_scene_visibility(self) -> None:
        """Show or hide the reach frame and the character; the item, the anchor and the
        particles are always drawn."""

        self._refresh_legend()
        if self.host is None or self._preview is None:
            return
        hidden = []
        if not self.show_reach.isChecked():
            hidden.append(self._preview.reach_submesh_index)
        if not self.show_character.isChecked():
            hidden.extend(self._preview.body_submesh_indices)
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
        button.setCheckable(True)
        self.view_group.addButton(button)
        button.setToolTip(explanation)
        button.clicked.connect(lambda _checked=False, y=yaw, p=pitch: self._look_from(y, p))
        row.addWidget(button)
        self.view_buttons.append(button)

    def _add_place_button(self, row: QHBoxLayout, title: str, where: str, explanation: str) -> None:
        button = QPushButton(title)
        button.setToolTip(explanation)
        button.clicked.connect(lambda _checked=False, target=where: self._put_it_at(target))
        row.addWidget(button)

    def _add_legend_row(self, column, key: str, tint: Sequence[float], text: str) -> None:
        """One line of the legend: the scene's own colour, and what is drawn in it."""

        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setText(f"{_swatch(tint)} {text}")
        column.addWidget(label)
        self.legend_rows[key] = label

    def _pause_particles(self, paused: bool) -> None:
        """Hold the simulation where it is, or let it run again."""

        self.pause_button.setText("Paused" if paused else "Pause")
        host = self.host
        setter = getattr(host, "set_effect_particles_paused", None) if host is not None else None
        if callable(setter):
            try:
                setter(bool(paused))
            except Exception:  # noqa: BLE001 - a host without the call keeps running
                pass

    def _backdrop_changed(self) -> None:
        """Send the chosen clear colour; remembered for the next time the dialog opens."""

        colour = str(self.backdrop_choice.currentData() or "")
        if not colour:
            return
        remember_backdrop(colour)
        host = self.host
        setter = getattr(host, "set_viewport_backdrop", None) if host is not None else None
        if callable(setter):
            try:
                setter(colour)
            except Exception:  # noqa: BLE001 - a host without the call keeps its own
                pass

    def _apply_orbit_preferences(self, *, remember: bool = False) -> None:
        """Apply this dialog's shared X/Y orbit choice without changing other tuning."""

        invert_x = self.invert_orbit_x_checkbox.isChecked()
        invert_y = self.invert_orbit_y_checkbox.isChecked()
        if remember:
            remember_orbit_inversion(invert_x, invert_y)
        host = self.host
        bindings = getattr(host, "set_camera_drag_bindings", None) if host is not None else None
        if callable(bindings):
            try:
                # The gizmo owns a left-button hit, so the right button also orbits; an
                # empty-space left drag keeps the helper's ordinary orbit behavior.
                bindings(
                    right="orbit",
                    invert_orbit_x=invert_x,
                    invert_orbit_y=invert_y,
                )
            except Exception:  # noqa: BLE001 - a host without the call keeps its own
                pass

    def _show_particles(self, visible: bool) -> None:
        """Draw or hide the particle layer; the anchor and the reach do not depend on it."""

        self._refresh_legend()
        host = self.host
        setter = getattr(host, "set_effect_particles_visible", None) if host is not None else None
        if callable(setter):
            try:
                setter(bool(visible))
            except Exception:  # noqa: BLE001 - a host without the call keeps what it draws
                pass

    def _refresh_legend(self) -> None:
        """The legend says what is on screen, so the two rows that can be turned off
        follow their checkboxes."""

        rows = getattr(self, "legend_rows", None)
        if not rows:
            return
        rows["body"].setVisible(self.show_character.isChecked())
        rows["reach"].setVisible(self.show_reach.isChecked())
        rows["particles"].setVisible(self.show_particles.isChecked())

    def _look_from(self, yaw: float, pitch: float) -> None:
        """Turn the camera to one of the standing views and fit the subject in it again."""

        self._point_camera(yaw=float(yaw), pitch=float(pitch))

    def _point_camera(self, *, yaw: Optional[float] = None, pitch: Optional[float] = None) -> None:
        """Send the visible overlay camera, fitted from the stable item reference. The
        view fits the item and character; with the reach frame shown it has to hold that
        instead, which for a boss effect can be twenty times as wide."""

        host = self.host
        setter = getattr(host, "set_view", None) if host is not None else None
        if not callable(setter):
            return
        if yaw is None or pitch is None:
            state = {}
            snapshot = getattr(host, "view_state_snapshot", None)
            if callable(snapshot):
                try:
                    state = snapshot() or {}
                except Exception:  # noqa: BLE001 - the angles fall back to the opening view
                    state = {}
            yaw = float(state.get("yaw", STANDING_VIEW_ANGLES[-1][0])) if yaw is None else yaw
            pitch = float(state.get("pitch", STANDING_VIEW_ANGLES[-1][1])) if pitch is None else pitch
        try:
            # Overlay presentation links its visible camera to the editable role, while
            # the item and character are the stable bounds that camera must fit from.
            # Keeping those roles separate prevents a moved effect from dragging the
            # camera centre away from the item.
            setter(
                yaw=float(yaw), pitch=float(pitch), zoom_factor=self._zoom_for_the_subject(),
                fit_to_view=True, role="replacement", fit_role="reference",
            )
        except Exception:  # noqa: BLE001 - a host without the call keeps the view it has
            pass

    def _zoom_for_the_subject(self) -> float:
        """1.0 frames the item reference; less zooms out to hold the visible reach."""

        if not self.show_reach.isChecked():
            return 1.0
        low, high = framing_bounds_for(self._item_mesh)
        subject = max(high[axis] - low[axis] for axis in range(3))
        reach = max(self._box_size) * self.scale
        if subject <= 0 or reach <= subject:
            return 1.0
        return max(0.1, min(1.0, subject / reach))

    def _put_it_at(self, where: str) -> None:
        """Move the effect's origin to a named place on the item: the hand it is held by
        (the item's own origin), the middle of the item, or its far end. Three spin boxes
        and a mesh whose long axis is not obvious make that a guessing game otherwise."""

        if where == "trail":
            point = self._trail_point()
            if point is None:
                return
            self._set_numbers(point, self.scale)
            self._sync_host()
            return
        low, high = self._item_bounds()
        if where in {"hand", "origin"}:
            self._set_numbers((0.0, 0.0, 0.0), self.scale)
            self._sync_host()
            return
        centre = tuple((low[axis] + high[axis]) / 2.0 for axis in range(3))
        if where in {"middle", "center"}:
            self._set_numbers(centre, self.scale)
            self._sync_host()
            return
        # the tip: the far end of the longest axis, the other two held at the middle
        longest = max(range(3), key=lambda axis: high[axis] - low[axis])
        far = high[longest] if abs(high[longest]) >= abs(low[longest]) else low[longest]
        offset = list(centre)
        # The guided asset-neutral End anchor is the actual bound. The legacy Tip
        # compatibility button retains its historical 92% inset.
        offset[longest] = far if where == "end" else far * 0.92
        self._set_numbers(tuple(offset), self.scale)  # type: ignore[arg-type]
        self._sync_host()

    def _reach_toggled(self) -> None:
        self._apply_scene_visibility()
        self._refresh_size_label()
        self._point_camera()

    def _fit_reach_to_item(self) -> None:
        """A scale that makes the effect's reach about the item's own length: a starting
        point for effects whose reach is tens of metres around a one-metre item."""

        low, high = self._item_bounds()
        item = max(high[axis] - low[axis] for axis in range(3))
        reach = max(self._box_size) or 1.0
        if item <= 0 or reach <= 0:
            return
        self._set_numbers(self.offset, item / reach)
        # the frame is what was just fitted, so it is shown whether or not it dwarfed the
        # item a moment ago: fitting a frame and leaving it hidden answers nothing
        if not self.show_reach.isChecked():
            self.show_reach.setChecked(True)  # `_reach_toggled` re-points the camera
        else:
            # the view was framed to hold twenty metres; the reach is now the item's own
            # length, and left where it was the item sits tiny in the middle of it
            self._point_camera()
        self._sync_host()
        self._apply_scene_visibility()

    def _offer_the_trail_socket(self) -> None:
        """Show the Trail button when the item's own socket file named one.

        Only then: a borrowed or absent socket can belong to another visual prefab, which
        is a worse answer than not offering it.
        """

        point = self._trail_point()
        self.trail_button.setVisible(point is not None and self._compatibility_ui)
        anchor_choice = getattr(self, "anchor_choice", None)
        if anchor_choice is not None:
            index = anchor_choice.findData("trail")
            if point is not None and index < 0:
                anchor_choice.addItem("Trail Socket", "trail")
            elif point is None and index >= 0:
                anchor_choice.removeItem(index)
        if point is not None:
            self.trail_button.setToolTip(
                "Put the effect's origin at this item's Trail Socket "
                f"({point[0]:.2f}, {point[1]:.2f}, {point[2]:.2f} m)."
            )

    def _trail_point(self):
        """The item-space point of the item's trail socket, or None."""

        from cdmw.services.effect_character_reference import TRAIL_SOCKET

        for name, point in self._effect_sockets:
            if str(name) == TRAIL_SOCKET:
                return tuple(float(v) for v in point)
        return None

    def _say_the_character_is_the_game_s(self) -> None:
        """The stand-in's wording is a promise the real character keeps better: say so
        once it is the one on screen."""

        self.show_character.setToolTip(
            "The game's own character provides a size reference for the item and effect."
        )
        row = getattr(self, "legend_rows", {}).get("body")
        if row is not None:
            row.setText(f"{_swatch(BODY_TINT)} the game's character, for scale")

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
            translation=self._frame.to_scene_point(self.offset),
            rotation_degrees=self._frame.to_scene_euler(self.rotation),
            scale_xyz=(self.scale, self.scale, self.scale),
        )

    def _refresh_size_label(self) -> None:
        width, height, depth = self._box_size
        low, high = self._item_bounds()
        item = max(high[axis] - low[axis] for axis in range(3))
        reach = max(width, height, depth) * self.scale
        times = f"{reach / item:.1f}x the item" if item > 0 else "unknown against the item"
        text = f"Reach at {self.scale:.2f}: {width * self.scale:.1f} x {height * self.scale:.1f} x {depth * self.scale:.1f} m, {times}."
        if getattr(self, "_reach_dwarfs_the_item", False) and not self.show_reach.isChecked():
            text += " Its frame starts hidden: it dwarfs the item."
        self.size_label.setText(text)
        # what the effect is before the scale, which matters when choosing one and is a
        # line the panel does not need to carry
        self.size_label.setToolTip(
            f"The effect's own reach is {width:.2f} x {height:.2f} x {depth:.2f} m, and the item is {item:.2f} m long."
        )

    def _set_numbers(self, offset: Vec3, scale: float, rotation: Optional[Vec3] = None) -> None:
        self.offset = tuple(round(float(v), 4) for v in offset)  # type: ignore[assignment]
        if rotation is not None:
            # rounded the way the rotation boxes round, for the same reason the scale is
            self.rotation = tuple(round(wrap_degrees(float(v)), ROTATION_DECIMALS) for v in rotation)  # type: ignore[assignment]
        # rounded the way the spin box rounds it. Kept to three decimals against a box
        # showing two, the dialog and the box held different numbers, and the next edit of
        # any other field took the box's: a fit to 0.034 became 0.03 without being asked.
        self.scale = round(max(SCALE_MINIMUM, min(SCALE_MAXIMUM, float(scale))), SCALE_DECIMALS)
        for spin, value in zip(self.offset_spins, self.offset):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)
        for spin, value in zip(self.rotation_spins, self.rotation):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)
        self.scale_spin.blockSignals(True)
        self.scale_spin.setValue(self.scale)
        self.scale_spin.blockSignals(False)
        self._refresh_size_label()
        self.transform_changed.emit()

    def _numbers_edited(self, *_args) -> None:
        self.offset = tuple(float(spin.value()) for spin in self.offset_spins)  # type: ignore[assignment]
        self.rotation = tuple(wrap_degrees(float(spin.value())) for spin in self.rotation_spins)  # type: ignore[assignment]
        self.scale = float(self.scale_spin.value())
        self._refresh_size_label()
        self._sync_host()
        self.transform_changed.emit()

    def _drag_finished(self, dx: float, dy: float, dz: float) -> None:
        # the drag is in the scene the reader is looking at; the numbers are the item's own
        moved = self._frame.from_scene_point((dx, dy, dz))
        self._set_numbers(tuple(self.offset[axis] + moved[axis] for axis in range(3)), self.scale)  # type: ignore[arg-type]
        self._sync_host()

    def _rotation_finished(self, dx: float, dy: float, dz: float) -> None:
        # the ring drag reports scene-frame degree deltas; the helper composed them onto
        # the scene Euler this dialog last sent, so compose the same way and carry the
        # result back into the item's frame, where the numbers and the game live
        scene = self._frame.to_scene_euler(self.rotation)
        turned = tuple(scene[axis] + (dx, dy, dz)[axis] for axis in range(3))
        self._set_numbers(self.offset, self.scale, self._frame.from_scene_euler(turned))
        self._sync_host()

    def _scale_finished(self, dx: float, dy: float, dz: float) -> None:
        self._set_numbers(self.offset, next_scale(self.scale, (dx, dy, dz)))
        self._sync_host()

    def _choose_tool(self, tool: str) -> None:
        self.move_button.setChecked(tool == "move")
        self.rotate_button.setChecked(tool == "rotate")
        self.scale_button.setChecked(tool == "scale")
        if self.host is not None:
            self.host.set_alignment_gizmo_tool(tool)

    # ------------------------------------------------------------------ lifecycle

    def apply_deltas(
        self,
        translation: Sequence[float] = (0.0, 0.0, 0.0),
        scale_delta: Sequence[float] = (0.0, 0.0, 0.0),
        rotation_delta: Sequence[float] = (0.0, 0.0, 0.0),
    ) -> None:
        """What a gizmo drag does, callable without a viewport (tests, scripts)."""

        self._drag_finished(*(float(v) for v in tuple(translation)[:3]))
        if any(abs(float(v)) > 1e-12 for v in rotation_delta):
            self._rotation_finished(*(float(v) for v in tuple(rotation_delta)[:3]))
        if any(abs(float(v)) > 1e-12 for v in scale_delta):
            self._scale_finished(*(float(v) for v in tuple(scale_delta)[:3]))

    def iter_shutdown_workers(self):
        return (("effect placement preview", self._thread, self._worker),) if self._thread is not None else ()

    def request_shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        worker = self._worker
        if worker is not None:
            worker.stop()
        thread = self._thread
        if thread is not None:
            thread.requestInterruption()
            thread.quit()
        host = self.host
        if host is not None:
            try:
                host.controller.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self._remove_owned_package(self._preview)
        self._remove_owned_package(self._loading_preview)
        for retired in self._retired_previews:
            self._remove_owned_package(retired)
        self._loading_preview = None
        self._loading_view_state = None
        self._retired_previews = []

    def _remove_owned_package(self, preview: Optional[EffectPlacementPreview]) -> bool:
        """Remove only one package directory created directly under this workspace root."""

        if preview is None:
            return False
        root = self._output_root.resolve(strict=False)
        candidate = Path(preview.package_dir).resolve(strict=False)
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return False
        if len(relative.parts) != 1 or not relative.name.startswith("package_"):
            return False
        shutil.rmtree(candidate, ignore_errors=True)
        return True


class EffectPlacementDialog(QDialog):
    """Thin modal compatibility wrapper around :class:`EffectPlacementWorkspace`."""

    def __init__(self, parent: Optional[QWidget] = None, **kwargs) -> None:
        super().__init__(parent)
        self.setWindowTitle("Place the effect on the item")
        self.setModal(True)
        self.resize(960, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.workspace = EffectPlacementWorkspace(self, compatibility_ui=True, **kwargs)
        self.workspace.apply_button.setVisible(False)
        self.workspace.setVisible(True)
        layout.addWidget(self.workspace, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def offset(self) -> Vec3:
        return self.workspace.offset

    @property
    def rotation(self) -> Vec3:
        return self.workspace.rotation

    @property
    def scale(self) -> float:
        return self.workspace.scale

    def __getattr__(self, name: str):
        workspace = self.__dict__.get("workspace")
        if workspace is not None:
            return getattr(workspace, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value) -> None:
        workspace = self.__dict__.get("workspace")
        if workspace is not None and name != "workspace" and hasattr(workspace, name):
            setattr(workspace, name, value)
            return
        super().__setattr__(name, value)

    def apply_deltas(self, *args, **kwargs) -> None:
        self.workspace.apply_deltas(*args, **kwargs)

    def iter_shutdown_workers(self):
        return self.workspace.iter_shutdown_workers()

    def request_shutdown(self) -> None:
        self.workspace.request_shutdown()

    def done(self, result: int) -> None:  # noqa: D401 - Qt override
        self.request_shutdown()
        super().done(result)


def _default_host_factory(parent: QWidget):
    from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame
    from cdmw.ui.preview.profile import DotNetPreviewProfile

    return DotNetPreviewHostFrame(parent, profile=DotNetPreviewProfile.PREVIEW, terminate_on_close=True)
