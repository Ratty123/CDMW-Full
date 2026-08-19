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
from cdmw.services.effect_placement_preview import EffectPlacementPreview, build_effect_placement_package, next_scale
from cdmw.services.effect_preview_model import EffectPreview
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
            f"{effect_label or 'The effect'} on the item. The wire is the item as the game holds it: its origin is the hand, the blade runs "
            "toward -z, the pommel toward +z. The particles are an approximate reading of the effect, where it will be at this scale and "
            "offset. Move or scale it with the gizmo or the numbers on the right; the numbers go into the plan when you accept. "
            "Tick Show the effect's box to see its bounding box (the reach the game reserves for it)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
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
        if self.host is not None:
            self.host.setMinimumSize(560, 420)
            self.host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            body.addWidget(self.host, 1)
        else:
            missing = QLabel("The resident viewport is not available here; set the numbers by hand." + (f" ({self._host_error})" if self._host_error else ""))
            missing.setWordWrap(True)
            body.addWidget(missing, 1)

        side = QVBoxLayout()
        body.addLayout(side)
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
        self.show_box = QCheckBox("Show the effect's box")
        self.show_box.setToolTip("The effect's bounding box at this scale and offset, drawn as a wire box. Off by default: the particles show where the effect is, and the box only gets in the way of the item.")
        self.show_box.setChecked(False)
        self.show_box.toggled.connect(lambda _checked: self._apply_box_visibility())
        side.addWidget(self.show_box)
        width, height, depth = (high - low for low, high in zip(*self._box))
        self.size_label = QLabel("")
        self.size_label.setWordWrap(True)
        self._box_size = (width, height, depth)
        side.addWidget(self.size_label)
        self.emitters_label = QLabel(describe_effect_preview(effect_preview))
        self.emitters_label.setWordWrap(True)
        self.emitters_label.setVisible(effect_preview is not None)
        side.addWidget(self.emitters_label)
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
            self.host.set_alignment_state(enabled=True, source_submesh_indices=(self._preview.box_submesh_index,))
            self._sync_host()
            self._apply_box_visibility()
            sentences = ["Drag the gizmo on the box. Move: offset along the item's axes. Scale: a uniform scale on the effect."]
            if self._preview.preview_file is not None:
                if self._host_draws_particles():
                    sentences.append("The particles are an approximate CPU reading of the effect's emitters (sprites, colours and motion from its binaries), not the game's own simulation; they follow the box.")
                else:
                    sentences.append("The effect's particle description is in the package; the viewport draws it once its particle layer lands, the box until then.")
            if self._preview.missing_textures:
                sentences.append(f"{len(self._preview.missing_textures)} sprite texture(s) could not be read from the archives.")
            self.status.setText(" ".join(sentences))
        elif str(state) == "error":
            self.status.setText(str(message or "The viewport reported an error."))

    def _apply_box_visibility(self) -> None:
        """Show or hide the box's edges: its faces are fully transparent in the package, so
        the box is only visible as the wire the viewport draws in its wire display mode.
        The gizmo, the frame the particles follow and the numbers do not depend on it."""

        if self.host is None or self._preview is None:
            return
        setter = getattr(self.host, "set_viewport_display_mode", None)
        if callable(setter):
            try:
                setter("untextured_wire" if self.show_box.isChecked() else "untextured_faces")
            except Exception:  # noqa: BLE001 - a host without display modes keeps whatever it draws
                pass

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
        self.size_label.setText(
            f"Effect box {width:.2f} x {height:.2f} x {depth:.2f} m; at scale {self.scale:.2f}: {width * self.scale:.2f} x {height * self.scale:.2f} x {depth * self.scale:.2f} m."
        )

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
