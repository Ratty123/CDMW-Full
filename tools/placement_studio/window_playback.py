"""The playback strip: load a `.paa` and watch the rig — and its sockets — move.

Placement is judged in the bind pose today, which is the one frame where a bad placement is
least likely to show. Posing the rig from a real clip puts every socket and attachment
marker where the animation actually carries it, so clipping and orientation can be seen in
the draw rather than inferred from a rest pose.

The playhead is driven by a timer that advances by elapsed wall time, not by a fixed step
per tick, so a heavy repaint slows the render rather than the animation.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from .playback import Playback, PlaybackError, coverage, load_clip, travel_extent

#: Repaint target. The clips are 30 fps; asking for much more just burns CPU on a painter.
_TICK_MS = 33
#: Never pace slower than this, however heavy the scene.
_MAX_TICK_MS = 100


class PlaybackMixin:
    """Animation playback controls. Mixed into `PlacementStudioWindow`."""

    def _build_playback_row(self) -> QWidget:
        self._playback = Playback()
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(_TICK_MS)
        self._playback_timer.timeout.connect(self._on_playback_tick)
        self._playback_last_tick = 0.0

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        self._playback_load_button = QPushButton("Load clip…")
        self._playback_load_button.setToolTip("Open a .paa motion clip and pose the rig with it")
        self._playback_load_button.clicked.connect(self._on_playback_load)
        layout.addWidget(self._playback_load_button)

        self._playback_play_button = QPushButton("Play")
        self._playback_play_button.setEnabled(False)
        self._playback_play_button.clicked.connect(self._on_playback_toggle)
        layout.addWidget(self._playback_play_button)

        self._playback_slider = QSlider(Qt.Horizontal)
        self._playback_slider.setMinimum(0)
        self._playback_slider.setMaximum(0)
        self._playback_slider.setEnabled(False)
        self._playback_slider.valueChanged.connect(self._on_playback_scrub)
        # Measuring clipping on every dragged pixel makes the slider chug. Settle on release.
        self._playback_slider.sliderReleased.connect(self._refresh_meshes)
        layout.addWidget(self._playback_slider, 1)

        self._playback_loop_box = QCheckBox("Loop")
        self._playback_loop_box.setChecked(True)
        self._playback_loop_box.toggled.connect(self._on_playback_loop)
        layout.addWidget(self._playback_loop_box)

        self._playback_rest_button = QPushButton("Bind pose")
        self._playback_rest_button.setToolTip("Drop the clip and return the rig to its rest pose")
        self._playback_rest_button.setEnabled(False)
        self._playback_rest_button.clicked.connect(self._on_playback_clear)
        layout.addWidget(self._playback_rest_button)

        self._playback_label = QLabel("No clip loaded")
        self._playback_label.setMinimumWidth(320)
        layout.addWidget(self._playback_label)
        return row

    def _fit_ground_to_clip(self, clip) -> None:
        """No-op: the room is a fixed size now, and the camera tracks the character."""

        return

    def _playhead_moving(self) -> bool:
        """True while playing or mid-drag — when a clipping number cannot be read anyway."""

        playback = getattr(self, "_playback", None)
        if playback is not None and playback.playing:
            return True
        slider = getattr(self, "_playback_slider", None)
        return slider is not None and slider.isSliderDown()

    # ── actions ─────────────────────────────────────────────────────

    def _on_playback_load(self) -> None:
        if self._session is None or not self._session.has_skeleton:
            self.statusBar().showMessage("Load a character model before a motion clip.")
            return
        start = str(self._playback_start_dir())
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open motion clip", start, "Crimson Desert motion (*.paa);;All files (*)"
        )
        if not path:
            return
        try:
            clip = load_clip(Path(path).read_bytes(), Path(path).name)
        except (PlaybackError, OSError) as error:
            self.statusBar().showMessage(f"Could not load clip: {error}")
            return

        matched = coverage(self._session.hierarchy, clip)
        if matched <= 0.0:
            self.statusBar().showMessage(
                f"{Path(path).name} animates no bone this rig defines — it is for another character."
            )
            return
        self._playback.load(clip, Path(path).stem)
        self._playback.looping = self._playback_loop_box.isChecked()
        self._playback_slider.setMaximum(max(self._playback.last_frame, 0))
        self._playback_slider.setEnabled(self._playback.last_frame > 0)
        self._playback_play_button.setEnabled(self._playback.last_frame > 0)
        self._playback_rest_button.setEnabled(True)
        self._fit_ground_to_clip(clip)
        note = "" if matched > 0.99 else f"  ({matched:.0%} of its bones exist on this rig)"
        self.statusBar().showMessage(f"Loaded {Path(path).name}{note}")
        self._apply_playback_frame()

    def _playback_start_dir(self) -> Path:
        """Prefer the extracted vanilla motion tree; it is where the clips actually are."""

        from .corpus import baseline_root

        for candidate in (baseline_root() / "character" / "motion", baseline_root()):
            if candidate.is_dir():
                return candidate
        return Path.home()

    def _on_playback_toggle(self) -> None:
        if not self._playback.loaded:
            return
        self._playback.playing = not self._playback.playing
        self._playback_play_button.setText("Pause" if self._playback.playing else "Play")
        viewport = getattr(self, "_viewport", None)
        if viewport is not None and hasattr(viewport, "set_moving"):
            viewport.set_moving(self._playback.playing)
        if self._playback.playing:
            self._playback_last_tick = time.monotonic()
            self._playback_timer.setInterval(_TICK_MS)
            self._playback_timer.start()
        else:
            self._playback_timer.stop()

    def _on_playback_loop(self, checked: bool) -> None:
        self._playback.looping = bool(checked)

    def _on_playback_scrub(self, value: int) -> None:
        if not self._playback.loaded or self._playback.playing:
            return
        self._playback.seek(float(value))
        self._apply_playback_frame()

    def _on_playback_clear(self) -> None:
        self._playback_timer.stop()
        self._playback.clear()
        self._playback_play_button.setText("Play")
        self._playback_play_button.setEnabled(False)
        self._playback_slider.setEnabled(False)
        self._playback_slider.setValue(0)
        self._playback_rest_button.setEnabled(False)
        if self._session is not None:
            self._session.clear_pose()
        self._playback_label.setText("No clip loaded")
        self._refresh_scene()

    def _on_playback_tick(self) -> None:
        now = time.monotonic()
        elapsed = now - (self._playback_last_tick or now)
        self._playback_last_tick = now
        if not self._playback.advance(elapsed):
            self._playback_play_button.setText("Play")
            self._playback_timer.stop()
            if hasattr(self._viewport, "set_moving"):
                self._viewport.set_moving(False)
        started = time.monotonic()
        self._apply_playback_frame()
        self._pace(time.monotonic() - started)

    def _pace(self, frame_seconds: float) -> None:
        """Match the tick to what a frame actually costs.

        Asking for 30 fps from a scene that needs 40 ms does not produce 30 fps — it fills
        the event queue with timer events the paint never keeps up with, and the window
        stops answering the mouse. Pacing to the measured cost keeps input responsive; the
        playhead advances by wall time either way, so the animation still runs at speed.
        """

        target = min(_MAX_TICK_MS, max(_TICK_MS, int(frame_seconds * 1000 * 1.25)))
        if abs(target - self._playback_timer.interval()) >= 8:
            self._playback_timer.setInterval(target)

    def _apply_playback_frame(self) -> None:
        """Pose the session and repaint. The single place playback touches the scene."""

        if self._session is None or not self._playback.loaded:
            return
        try:
            self._session.apply_pose(self._playback.clip, self._playback.frame)
        except PlaybackError as error:
            self._playback_timer.stop()
            self._playback.playing = False
            self._playback_play_button.setText("Play")
            self.statusBar().showMessage(f"Playback stopped: {error}")
            return
        frame = int(round(self._playback.frame))
        if self._playback_slider.value() != frame:
            self._playback_slider.blockSignals(True)
            self._playback_slider.setValue(frame)
            self._playback_slider.blockSignals(False)
        self._playback_label.setText(self._playback.summary())
        self._refresh_scene()
