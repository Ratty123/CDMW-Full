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

from .playback import Playback, PlaybackError, PREVIEW_TICK_MS, frame_interval_ms


class PlaybackMixin:
    """Animation playback controls. Mixed into `PlacementStudioWindow`."""

    def _build_playback_row(self) -> QWidget:
        self._playback = Playback()
        self._playback_timer = QTimer(self)
        self._playback_timer.setTimerType(Qt.PreciseTimer)
        self._playback_timer.setSingleShot(True)
        self._playback_timer.setInterval(PREVIEW_TICK_MS)
        self._playback_timer.timeout.connect(self._on_playback_tick)
        self._playback_last_tick = 0.0
        self._playback_update_seconds = 0.0
        self._playback_paint_pending = False
        self._viewport.frame_painted.connect(self._on_playback_painted)
        self._scrub_timer = QTimer(self)
        self._scrub_timer.setSingleShot(True)
        self._scrub_timer.setTimerType(Qt.PreciseTimer)
        self._scrub_timer.setInterval(PREVIEW_TICK_MS)
        self._scrub_timer.timeout.connect(self._apply_playback_frame)

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
        self._playback_slider.sliderPressed.connect(self._on_scrub_started)
        self._playback_slider.sliderReleased.connect(self._on_scrub_finished)
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
        from .clips import ClipEntry
        source = Path(path)
        self._play_clip_entry(ClipEntry(source.as_posix(), "", "", False, source))

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
        self._scrub_timer.stop()
        self._playback_paint_pending = False
        self._playback_update_seconds = 0.0
        self._playback.playing = not self._playback.playing
        self._playback_play_button.setText("Pause" if self._playback.playing else "Play")
        viewport = getattr(self, "_viewport", None)
        if viewport is not None and hasattr(viewport, "set_moving"):
            viewport.set_moving(self._playback.playing)
        if self._playback.playing:
            self._playback_last_tick = time.monotonic()
            self._playback_timer.setInterval(PREVIEW_TICK_MS)
            self._playback_timer.start()
        else:
            self._playback_timer.stop()

    def _on_playback_loop(self, checked: bool) -> None:
        self._playback.looping = bool(checked)

    def _on_playback_scrub(self, value: int) -> None:
        if not self._playback.loaded or self._playback.playing:
            return
        self._playback.seek(float(value))
        if self._playback_slider.isSliderDown():
            if not self._scrub_timer.isActive():
                self._scrub_timer.start()
        else:
            self._apply_playback_frame()

    def _on_scrub_started(self) -> None:
        self._viewport.set_moving(True)

    def _on_scrub_finished(self) -> None:
        self._scrub_timer.stop()
        self._viewport.set_moving(self._playback.playing)
        if self._playback.loaded and not self._playback.playing:
            self._apply_playback_frame()

    def _stop_playback(self) -> None:
        self._playback_timer.stop()
        self._scrub_timer.stop()
        self._playback.playing = False
        self._playback_paint_pending = False
        self._viewport.set_moving(False)
        self._playback_play_button.setText("Play")

    def _on_playback_clear(self) -> None:
        self._stop_playback()
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
        self._playback_timer.stop()
        if not self._playback.playing or not self._playback.loaded:
            self._stop_playback()
            return
        now = time.monotonic()
        elapsed = now - (self._playback_last_tick or now)
        self._playback_last_tick = now
        if not self._playback.advance(elapsed):
            self._stop_playback()
        started = time.monotonic()
        self._playback_paint_pending = self._playback.playing
        self._apply_playback_frame()
        self._pace(time.monotonic() - started)

    def _pace(self, frame_seconds: float) -> None:
        """Wait for this pose to paint before scheduling another expensive update."""
        self._playback_update_seconds = frame_seconds

    def _on_playback_painted(self, paint_seconds: float) -> None:
        if not self._playback.playing or not self._playback_paint_pending:
            return
        self._playback_paint_pending = False
        elapsed = time.monotonic() - self._playback_last_tick
        target = frame_interval_ms(self._playback_update_seconds, paint_seconds)
        # Restarting a QTimer measures from now. Deduct work already done so an
        # interval change cannot add the entire pose cost to every frame deadline.
        self._playback_timer.start(max(1, int(target - elapsed * 1000)))

    def _apply_playback_frame(self) -> None:
        """Pose the session and repaint. The single place playback touches the scene."""

        if self._session is None or not self._playback.loaded:
            return
        try:
            self._session.apply_pose(self._playback.clip, self._playback.frame)
        except PlaybackError as error:
            self._stop_playback()
            self.statusBar().showMessage(f"Playback stopped: {error}")
            return
        frame = int(round(self._playback.frame))
        if self._playback_slider.value() != frame:
            self._playback_slider.blockSignals(True)
            self._playback_slider.setValue(frame)
            self._playback_slider.blockSignals(False)
        self._playback_label.setText(self._playback.summary())
        self._refresh_scene()
