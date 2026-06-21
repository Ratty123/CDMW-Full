"""Image and media preview widgets shared across UI features."""

from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:
    QAudioOutput = None
    QMediaPlayer = None
    QVideoWidget = None
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget

class PreviewLabel(QLabel):
    color_sampled = Signal(str)

    def __init__(self, title: str):
        super().__init__(title)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(280, 220)
        self.setWordWrap(True)
        self.setObjectName("PreviewLabel")
        self._source_pixmap: Optional[QPixmap] = None
        self._source_image: Optional[QImage] = None
        self._source_image_path: str = ""
        self._source_image_size = QSize()
        self._source_image_loaded_size = QSize()
        self._source_image_load_failed = False
        self._source_revision = 0
        self._scaled_pixmap_cache: Dict[Tuple[int, int, int, int], QPixmap] = {}
        self._current_render_key: Optional[Tuple[int, int, int, int]] = None
        self._current_render_size = QSize()
        self._fallback_text = title
        self._pending_render_text = title
        self._zoom_factor = 1.0
        self._fit_to_view = True
        self._fit_scale = 1.0
        self._scroll_area = None
        self._wheel_zoom_handler: Optional[Callable[[int], None]] = None
        self._color_pick_enabled = False
        self._drag_active = False
        self._drag_start_global_pos = None
        self._drag_start_h = 0
        self._drag_start_v = 0
        self._interactive_scale_timer = QTimer(self)
        self._interactive_scale_timer.setSingleShot(True)
        self._interactive_scale_timer.setInterval(16)
        self._interactive_scale_timer.timeout.connect(self._flush_interactive_scale)
        self._idle_scale_timer = QTimer(self)
        self._idle_scale_timer.setSingleShot(True)
        self._idle_scale_timer.setInterval(140)
        self._idle_scale_timer.timeout.connect(self._flush_idle_scale)

    def clear_preview(self, message: str) -> None:
        self._interactive_scale_timer.stop()
        self._idle_scale_timer.stop()
        self._source_pixmap = None
        self._source_image = None
        self._source_image_path = ""
        self._source_image_size = QSize()
        self._source_image_loaded_size = QSize()
        self._source_image_load_failed = False
        self._source_revision += 1
        self._scaled_pixmap_cache.clear()
        self._current_render_key = None
        self._current_render_size = QSize()
        self._fallback_text = message
        self._pending_render_text = message
        self._drag_active = False
        self.setPixmap(QPixmap())
        self.setText(message)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(280, 220)
        self.setMaximumSize(16777215, 16777215)
        self.unsetCursor()

    def attach_scroll_area(self, scroll_area) -> None:
        self._scroll_area = scroll_area
        scroll_area.resized.connect(self._handle_viewport_resize)

    def set_wheel_zoom_handler(self, handler: Optional[Callable[[int], None]]) -> None:
        self._wheel_zoom_handler = handler

    def set_color_pick_enabled(self, enabled: bool) -> None:
        self._color_pick_enabled = enabled
        self._update_cursor()

    def set_zoom_factor(self, zoom_factor: float) -> None:
        self._zoom_factor = max(0.1, zoom_factor)
        if self._has_source_image():
            self._interactive_scale_timer.stop()
            self._idle_scale_timer.stop()
            self._apply_scaled_pixmap(self._fallback_text)

    def set_fit_to_view(self, fit_to_view: bool) -> None:
        self._fit_to_view = fit_to_view
        if self._has_source_image():
            self._interactive_scale_timer.stop()
            self._idle_scale_timer.stop()
            self._apply_scaled_pixmap(self._fallback_text)

    def set_fit_scale(self, fit_scale: float) -> None:
        self._fit_scale = max(0.5, min(4.0, fit_scale))
        if self._has_source_image() and self._fit_to_view:
            self._interactive_scale_timer.stop()
            self._idle_scale_timer.stop()
            self._apply_scaled_pixmap(self._fallback_text)

    def set_preview_pixmap(self, pixmap: QPixmap, fallback_text: str) -> None:
        self._interactive_scale_timer.stop()
        self._idle_scale_timer.stop()
        self._source_pixmap = pixmap
        self._source_image = None
        self._source_image_path = ""
        self._source_image_size = pixmap.size()
        self._source_image_loaded_size = pixmap.size()
        self._source_image_load_failed = False
        self._source_revision += 1
        self._scaled_pixmap_cache.clear()
        self._current_render_key = None
        self._current_render_size = QSize()
        self._fallback_text = fallback_text
        self._pending_render_text = fallback_text
        self._apply_scaled_pixmap(fallback_text)

    def set_preview_image(self, image: QImage, fallback_text: str) -> None:
        self._interactive_scale_timer.stop()
        self._idle_scale_timer.stop()
        self._source_pixmap = None
        self._source_image = image
        self._source_image_path = ""
        self._source_image_size = image.size() if not image.isNull() else QSize()
        self._source_image_loaded_size = self._source_image_size
        self._source_image_load_failed = False
        self._source_revision += 1
        self._scaled_pixmap_cache.clear()
        self._current_render_key = None
        self._current_render_size = QSize()
        self._fallback_text = fallback_text
        self._pending_render_text = fallback_text
        self._apply_scaled_pixmap(fallback_text)

    def set_preview_image_path(self, image_path: str, fallback_text: str) -> None:
        self._interactive_scale_timer.stop()
        self._idle_scale_timer.stop()
        self._source_pixmap = None
        self._source_image = None
        self._source_image_path = image_path
        self._source_image_load_failed = False
        reader = QImageReader(image_path)
        size = reader.size()
        self._source_image_size = size if size.isValid() else QSize()
        self._source_image_loaded_size = QSize()
        self._source_revision += 1
        self._scaled_pixmap_cache.clear()
        self._current_render_key = None
        self._current_render_size = QSize()
        self._fallback_text = fallback_text
        self._pending_render_text = fallback_text
        self._apply_scaled_pixmap(fallback_text)

    def current_display_scale(self) -> float:
        source_width = 0
        if self._source_pixmap is not None and not self._source_pixmap.isNull():
            source_width = self._source_pixmap.width()
        elif self._source_image_size.isValid():
            source_width = self._source_image_size.width()
        if source_width <= 0:
            return 1.0
        return max(0.1, self.width() / float(source_width))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._has_source_image() and self._fit_to_view and self._scroll_area is None:
            self._schedule_fit_rescale()

    def _handle_viewport_resize(self) -> None:
        if self._has_source_image() and self._fit_to_view:
            self._schedule_fit_rescale()

    def _schedule_fit_rescale(self) -> None:
        self._pending_render_text = self._fallback_text
        self._interactive_scale_timer.start()
        self._idle_scale_timer.start()

    def _flush_interactive_scale(self) -> None:
        if self._has_source_image():
            self._apply_scaled_pixmap(self._pending_render_text, transformation_mode=Qt.FastTransformation)

    def _flush_idle_scale(self) -> None:
        if self._has_source_image():
            self._apply_scaled_pixmap(self._pending_render_text, transformation_mode=Qt.SmoothTransformation)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and self._color_pick_enabled:
            current_pixmap = self.pixmap()
            point = event.position().toPoint()
            if current_pixmap is not None and not current_pixmap.isNull():
                if 0 <= point.x() < current_pixmap.width() and 0 <= point.y() < current_pixmap.height():
                    color = current_pixmap.toImage().pixelColor(point)
                    self.color_sampled.emit(color.name().upper())
                    event.accept()
                    return
        if (
            event.button() == Qt.LeftButton
            and self._can_pan()
            and self._scroll_area is not None
        ):
            self._drag_active = True
            self._drag_start_global_pos = event.globalPosition().toPoint()
            self._drag_start_h = self._scroll_area.horizontalScrollBar().value()
            self._drag_start_v = self._scroll_area.verticalScrollBar().value()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_active and self._scroll_area is not None and self._drag_start_global_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_start_global_pos
            self._scroll_area.horizontalScrollBar().setValue(self._drag_start_h - delta.x())
            self._scroll_area.verticalScrollBar().setValue(self._drag_start_v - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_active and event.button() == Qt.LeftButton:
            self._drag_active = False
            self._drag_start_global_pos = None
            self._update_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta_y = event.angleDelta().y()
        if (
            self._wheel_zoom_handler is not None
            and self._has_source_image()
            and delta_y != 0
        ):
            step = 1 if delta_y > 0 else -1
            self._wheel_zoom_handler(step)
            event.accept()
            return
        super().wheelEvent(event)

    def _can_pan(self) -> bool:
        if not self._has_source_image() or self._scroll_area is None:
            return False
        viewport = self._scroll_area.viewport().size()
        return self.width() > viewport.width() or self.height() > viewport.height()

    def _has_source_image(self) -> bool:
        return (
            self._source_pixmap is not None and not self._source_pixmap.isNull()
        ) or (self._source_image is not None and not self._source_image.isNull()) or (
            bool(self._source_image_path) and not self._source_image_load_failed
        )

    def _update_cursor(self) -> None:
        if self._color_pick_enabled:
            self.setCursor(Qt.CrossCursor)
        elif self._drag_active:
            self.setCursor(Qt.ClosedHandCursor)
        elif self._can_pan():
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def _apply_scaled_pixmap(self, fallback_text: str, *, transformation_mode=Qt.SmoothTransformation) -> None:
        self._fallback_text = fallback_text
        has_source_pixmap = self._source_pixmap is not None and not self._source_pixmap.isNull()
        has_source_image = self._source_image is not None and not self._source_image.isNull()
        has_source_path = bool(self._source_image_path) and not self._source_image_load_failed
        if not has_source_pixmap and not has_source_image and not has_source_path:
            self.setPixmap(QPixmap())
            self.setText(fallback_text)
            self._update_cursor()
            return

        if self._fit_to_view and self._scroll_area is not None:
            viewport = self._scroll_area.maximumViewportSize()
            if not viewport.isValid() or viewport.isEmpty():
                viewport = self._scroll_area.viewport().size()
            width = max(1, int(round((viewport.width() - 6) * self._fit_scale)))
            height = max(1, int(round((viewport.height() - 6) * self._fit_scale)))
        else:
            if has_source_pixmap:
                source_size = self._source_pixmap.size()
            elif self._source_image is not None and not self._source_image.isNull():
                source_size = self._source_image.size()
            else:
                source_size = self._source_image_size
            width = max(1, int(round(source_size.width() * self._zoom_factor)))
            height = max(1, int(round(source_size.height() * self._zoom_factor)))

        transform_key = 0 if transformation_mode == Qt.FastTransformation else 1
        cache_key = (self._source_revision, width, height, transform_key)
        if self._current_render_key == cache_key:
            current_pixmap = self.pixmap()
            if current_pixmap is not None and not current_pixmap.isNull() and current_pixmap.size() == self._current_render_size:
                self._update_cursor()
                return
        cached = self._scaled_pixmap_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            scaled = cached
        elif has_source_pixmap:
            scaled = self._source_pixmap.scaled(
                width,
                height,
                Qt.KeepAspectRatio,
                transformation_mode,
            )
            self._cache_scaled_pixmap(cache_key, scaled)
        else:
            if not has_source_image:
                if not self._load_source_image_for_render(width, height):
                    self.setPixmap(QPixmap())
                    self.setText(fallback_text)
                    self._update_cursor()
                    return
            target_size = self._source_image.size().scaled(width, height, Qt.KeepAspectRatio)
            if not target_size.isValid():
                self.setPixmap(QPixmap())
                self.setText(fallback_text)
                self._update_cursor()
                return
            scaled_image = self._source_image.scaled(
                target_size,
                Qt.KeepAspectRatio,
                transformation_mode,
            )
            scaled = QPixmap.fromImage(scaled_image)
            self._cache_scaled_pixmap(cache_key, scaled)

        self.setText("")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(0, 0)
        self.resize(scaled.size())
        self.setFixedSize(scaled.size())
        self.setPixmap(scaled)
        self._current_render_key = cache_key
        self._current_render_size = scaled.size()
        self._update_cursor()

    def _cache_scaled_pixmap(self, cache_key: Tuple[int, int, int, int], pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        self._scaled_pixmap_cache[cache_key] = pixmap
        if len(self._scaled_pixmap_cache) > 12:
            oldest_key = next(iter(self._scaled_pixmap_cache))
            self._scaled_pixmap_cache.pop(oldest_key, None)

    def _load_source_image_for_render(self, target_width: int, target_height: int) -> bool:
        if self._source_image_load_failed or not self._source_image_path:
            return False
        requested_size = QSize(max(1, target_width), max(1, target_height))
        reader = QImageReader(self._source_image_path)
        reader.setAutoTransform(True)
        if not self._source_image_size.isValid():
            size = reader.size()
            if size.isValid():
                self._source_image_size = size
        source_size = self._source_image_size if self._source_image_size.isValid() else reader.size()
        decode_target_size = (
            source_size.scaled(requested_size, Qt.KeepAspectRatio)
            if source_size.isValid()
            else requested_size
        )
        if self._source_image is not None and not self._source_image.isNull():
            loaded_size = self._source_image.size()
            if loaded_size.isValid() and (
                loaded_size.width() >= decode_target_size.width()
                and loaded_size.height() >= decode_target_size.height()
            ):
                self._source_image_loaded_size = loaded_size
                return True
        use_scaled_decode = (
            source_size.isValid()
            and source_size.width() > decode_target_size.width() * 2
            and source_size.height() > decode_target_size.height() * 2
        )
        if use_scaled_decode:
            reader.setScaledSize(decode_target_size)
        image = reader.read()
        if image.isNull() and use_scaled_decode:
            reader = QImageReader(self._source_image_path)
            reader.setAutoTransform(True)
            image = reader.read()
        if image.isNull():
            self._source_image_load_failed = True
            self._source_image = None
            self._source_image_loaded_size = QSize()
            return False
        self._source_image = image
        self._source_image_loaded_size = image.size()
        if not self._source_image_size.isValid():
            self._source_image_size = image.size()
        return True

class PreviewScrollArea(QScrollArea):
    resized = Signal()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.resized.emit()

def _format_media_preview_time(value_ms: int) -> str:
    total_seconds = max(0, int(value_ms // 1000))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"

class MediaPreviewWidget(QWidget):
    def __init__(self, message: str, *, theme_key: str):
        super().__init__()
        self._message = message
        self._theme_key = theme_key
        self._media_path = ""
        self._media_kind = ""
        self._ignore_slider_update = False
        self._media_supported = bool(QMediaPlayer is not None and QAudioOutput is not None and QVideoWidget is not None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.info_label = QLabel(message)
        self.info_label.setWordWrap(True)
        self.info_label.setObjectName("HintLabel")
        layout.addWidget(self.info_label)

        if self._media_supported:
            self.video_widget = QVideoWidget()
            self.video_widget.setMinimumHeight(220)
            layout.addWidget(self.video_widget, stretch=1)

            controls_row = QHBoxLayout()
            controls_row.setSpacing(8)
            self.play_button = QPushButton("Play")
            self.stop_button = QPushButton("Stop")
            self.position_slider = QSlider(Qt.Horizontal)
            self.position_slider.setRange(0, 0)
            self.time_label = QLabel("0:00 / 0:00")
            self.time_label.setObjectName("HintLabel")
            controls_row.addWidget(self.play_button)
            controls_row.addWidget(self.stop_button)
            controls_row.addWidget(self.position_slider, stretch=1)
            controls_row.addWidget(self.time_label)
            layout.addLayout(controls_row)

            self.audio_output = QAudioOutput(self)
            self.audio_output.setVolume(1.0)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio_output)
            self.player.setVideoOutput(self.video_widget)
            self.player.positionChanged.connect(self._handle_position_changed)
            self.player.durationChanged.connect(self._handle_duration_changed)
            self.player.playbackStateChanged.connect(self._handle_playback_state_changed)
            self.player.mediaStatusChanged.connect(self._handle_media_status_changed)
            self.player.errorOccurred.connect(self._handle_error)

            self.play_button.clicked.connect(self._toggle_play_pause)
            self.stop_button.clicked.connect(self._stop_playback)
            self.position_slider.sliderPressed.connect(self._handle_slider_pressed)
            self.position_slider.sliderReleased.connect(self._handle_slider_released)
            self.position_slider.sliderMoved.connect(self._handle_slider_moved)
        else:
            self.video_widget = None
            self.play_button = QPushButton("Play")
            self.stop_button = QPushButton("Stop")
            self.position_slider = QSlider(Qt.Horizontal)
            self.time_label = QLabel("0:00 / 0:00")
            self.audio_output = None
            self.player = None

        self.clear_media(message)

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = theme_key

    def clear_media(self, message: str) -> None:
        self._message = message
        self._media_path = ""
        self._media_kind = ""
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        if self.video_widget is not None:
            self.video_widget.setVisible(False)
        self.info_label.setText(message)
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.position_slider.setEnabled(False)
        self.position_slider.setRange(0, 0)
        self.position_slider.setValue(0)
        self.time_label.setText("0:00 / 0:00")

    def shutdown(self) -> None:
        self.clear_media(self._message)

    def set_media(self, media_path: str, *, media_kind: str, detail_text: str = "") -> None:
        normalized_path = str(media_path or "").strip()
        normalized_kind = str(media_kind or "").strip().lower()
        if not normalized_path:
            self.clear_media(detail_text or "No media preview available.")
            return

        self._media_path = normalized_path
        self._media_kind = normalized_kind

        if not self._media_supported:
            self.info_label.setText(
                "Qt Multimedia is not available in this build.\n\n"
                + (detail_text or normalized_path)
            )
            self.play_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.position_slider.setEnabled(False)
            return

        self.info_label.setText(detail_text or normalized_path)
        if self.video_widget is not None:
            self.video_widget.setVisible(normalized_kind == "video")
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.position_slider.setEnabled(True)
        self.position_slider.setRange(0, 0)
        self.position_slider.setValue(0)
        self.time_label.setText("0:00 / 0:00")
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(normalized_path))
        self.player.play()

    def _toggle_play_pause(self) -> None:
        if self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _stop_playback(self) -> None:
        if self.player is None:
            return
        self.player.stop()

    def _handle_slider_pressed(self) -> None:
        self._ignore_slider_update = True

    def _handle_slider_released(self) -> None:
        if self.player is not None:
            self.player.setPosition(int(self.position_slider.value()))
        self._ignore_slider_update = False

    def _handle_slider_moved(self, value: int) -> None:
        duration = self.position_slider.maximum()
        self.time_label.setText(f"{_format_media_preview_time(value)} / {_format_media_preview_time(duration)}")

    def _handle_position_changed(self, position: int) -> None:
        if not self._ignore_slider_update:
            self.position_slider.setValue(int(position))
        duration = self.position_slider.maximum()
        self.time_label.setText(f"{_format_media_preview_time(position)} / {_format_media_preview_time(duration)}")

    def _handle_duration_changed(self, duration: int) -> None:
        self.position_slider.setRange(0, max(0, int(duration)))
        position = self.position_slider.value()
        self.time_label.setText(f"{_format_media_preview_time(position)} / {_format_media_preview_time(duration)}")

    def _handle_playback_state_changed(self, state) -> None:
        if QMediaPlayer is None:
            return
        self.play_button.setText("Pause" if state == QMediaPlayer.PlayingState else "Play")

    def _handle_media_status_changed(self, status) -> None:
        if QMediaPlayer is None:
            return
        if status == QMediaPlayer.EndOfMedia:
            self.play_button.setText("Play")

    def _handle_error(self, _error, error_text: str) -> None:
        message = str(error_text or "").strip() or "The multimedia backend could not open this file."
        if self._media_kind == "audio":
            message += "\n\nSome Wwise `.wem` variants are not supported by the local Qt Multimedia backend."
        self.info_label.setText(message + (f"\n\nSource: {self._media_path}" if self._media_path else ""))
