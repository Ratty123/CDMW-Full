"""Startup splash and initial archive path dialogs."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.core.archive import autodetect_archive_package_roots, looks_like_archive_package_root
from cdmw.ui.shell.startup_splash import format_startup_splash_detail as _format_startup_splash_detail
from cdmw.ui.themes import UI_THEME_SCHEMES, get_theme


def _splash_resolved_theme_key(theme_key: object) -> str:
    key = str(theme_key or "").strip()
    return key if key in UI_THEME_SCHEMES else DEFAULT_UI_THEME

def _splash_theme_value(theme_key: object, role: str, fallback: str) -> str:
    theme = get_theme(_splash_resolved_theme_key(theme_key))
    return str(theme.get(role, fallback) or fallback)

def _splash_theme_color(theme_key: object, role: str, fallback: str) -> QColor:
    color = QColor(_splash_theme_value(theme_key, role, fallback))
    return color if color.isValid() else QColor(fallback)

def _splash_color_with_alpha(color: QColor, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result

def _splash_accent_block_colors(theme_key: object, alpha: int) -> Tuple[QColor, QColor, QColor, QColor, QColor, QColor]:
    accent = _splash_theme_color(theme_key, "accent", "#c56d43")
    colors = (
        accent.lighter(135),
        accent.darker(112),
        accent.lighter(165),
        accent.lighter(108),
        accent.darker(150),
        accent.darker(230),
    )
    return tuple(_splash_color_with_alpha(color, alpha) for color in colors)  # type: ignore[return-value]

class StartupSignalMark(QFrame):
    def __init__(self, parent: Optional[QWidget] = None, *, theme_key: str = DEFAULT_UI_THEME) -> None:
        super().__init__(parent)
        self.setObjectName("StartupSignalMark")
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._theme_key = _splash_resolved_theme_key(theme_key)
        self._phase = 0.0
        self._started_at = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance_phase)
        self._timer.start()

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = _splash_resolved_theme_key(theme_key)
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def _advance_phase(self) -> None:
        if not self.isVisible():
            return
        self._phase = ((time.monotonic() - self._started_at) * 0.54) % 1.0
        self.update()

    def _face_gradient(self, polygon: QPolygonF, start: QColor, end: QColor) -> QLinearGradient:
        bounds = polygon.boundingRect()
        gradient = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        gradient.setColorAt(0.0, start)
        gradient.setColorAt(1.0, end)
        return gradient

    def _draw_iso_block(
        self,
        painter: QPainter,
        center_x: float,
        top_y: float,
        half_width: float,
        half_depth: float,
        block_height: float,
        opacity: float = 1.0,
    ) -> None:
        alpha = max(0, min(255, int(255 * opacity)))
        top = QPolygonF(
            [
                QPointF(center_x, top_y - half_depth),
                QPointF(center_x + half_width, top_y),
                QPointF(center_x, top_y + half_depth),
                QPointF(center_x - half_width, top_y),
            ]
        )
        left = QPolygonF(
            [
                QPointF(center_x - half_width, top_y),
                QPointF(center_x, top_y + half_depth),
                QPointF(center_x, top_y + half_depth + block_height),
                QPointF(center_x - half_width, top_y + block_height),
            ]
        )
        right = QPolygonF(
            [
                QPointF(center_x + half_width, top_y),
                QPointF(center_x, top_y + half_depth),
                QPointF(center_x, top_y + half_depth + block_height),
                QPointF(center_x + half_width, top_y + block_height),
            ]
        )
        top_a, top_b, left_a, left_b, right_a, right_b = _splash_accent_block_colors(self._theme_key, alpha)

        painter.setPen(Qt.NoPen)
        painter.setBrush(self._face_gradient(left, left_a, left_b))
        painter.drawPolygon(left)
        painter.setBrush(self._face_gradient(right, right_a, right_b))
        painter.drawPolygon(right)
        painter.setBrush(self._face_gradient(top, top_a, top_b))
        painter.drawPolygon(top)

        edge = _splash_color_with_alpha(_splash_theme_color(self._theme_key, "accent", "#c56d43"), int(46 * opacity))
        painter.setPen(QPen(edge, 0.7))
        painter.setBrush(Qt.NoBrush)
        painter.drawPolyline(top)

    def _draw_cdmw_block_wave(self, painter: QPainter, inner, width: float, height: float) -> None:
        center_x = inner.left() + width * 0.5
        anchor_y = inner.top() + height * 0.78
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        cols = 8
        rows = 4
        half_width = min(max(width / 46.0, 6.6), 8.8)
        half_depth = half_width * 0.48
        block_height = half_width * 0.72
        phase_radians = self._phase * math.tau
        for row in range(rows):
            for col in range(cols):
                x = center_x + (col - (cols - 1) * 0.5) * half_width * 1.58 + (row - (rows - 1) * 0.5) * half_width * 0.72
                base_y = anchor_y + (row - (rows - 1) * 0.5) * half_depth * 1.86 + (col - (cols - 1) * 0.5) * half_depth * 0.08
                wave = (math.sin(phase_radians + col * 0.72 + row * 0.58) + 1.0) * 0.5
                stack_height = 1.0 + wave * 3.1
                full_blocks = int(stack_height)
                partial = stack_height - full_blocks
                for level in range(full_blocks):
                    self._draw_iso_block(
                        painter,
                        x,
                        base_y - (level + 1) * block_height,
                        half_width,
                        half_depth,
                        block_height,
                    )
                if partial > 0.12:
                    self._draw_iso_block(
                        painter,
                        x,
                        base_y - (full_blocks + 1) * block_height,
                        half_width,
                        half_depth,
                        block_height,
                        0.35 + partial * 0.65,
                    )
        painter.restore()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        rect = self.rect().adjusted(0, 0, -1, -1)
        if rect.width() <= 8 or rect.height() <= 8:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.NoBrush)
        inner = rect.adjusted(10, 4, -10, -4)
        width = max(1.0, float(inner.width()))
        height = max(1.0, float(inner.height()))

        self._draw_cdmw_block_wave(painter, inner, width, height)

class StartupProgressCard(QFrame):
    def __init__(self, parent: Optional[QWidget] = None, *, theme_key: str = DEFAULT_UI_THEME) -> None:
        super().__init__(parent)
        self.setObjectName("StartupSplashCard")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self._theme_key = _splash_resolved_theme_key(theme_key)
        self._current = 0
        self._total = 0
        self._phase = 0.0
        self._raw_progress = 0.0
        self._target_progress = 0.0
        self._display_progress = 0.0
        self._has_determinate_progress = False
        self._animation_started_at = time.monotonic()
        self._falling_blocks = tuple(
            (
                0.10 + ((index * 37) % 80) / 100.0,
                ((index * 19) % 100) / 100.0,
                0.46 + ((index * 11) % 36) / 100.0,
                2.0 + float(index % 3),
                0.18 + ((index * 7) % 12) / 100.0,
            )
            for index in range(18)
        )
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance_progress_phase)
        self._timer.start()

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = _splash_resolved_theme_key(theme_key)
        self.update()

    def set_progress(self, current: int = 0, total: int = 0) -> None:
        previous_raw_progress = self._raw_progress
        previous_total = self._total
        next_total = max(0, int(total or 0))
        self._total = next_total
        if next_total > 0:
            self._current = min(max(int(current or 0), 0), next_total)
            next_raw_progress = min(max(self._current / max(next_total, 1), 0.0), 1.0)
            stage_restarted = (
                self._has_determinate_progress
                and (
                    next_raw_progress + 0.015 < previous_raw_progress
                    or (previous_total > 0 and previous_total != next_total and next_raw_progress + 0.02 < self._target_progress)
                )
            )
            if stage_restarted:
                self._target_progress = min(0.965, max(self._target_progress, self._display_progress) + 0.045)
            elif next_raw_progress >= 0.999:
                self._target_progress = max(self._target_progress, min(0.96, self._target_progress + 0.035))
            else:
                self._target_progress = max(self._target_progress, next_raw_progress)
            self._raw_progress = next_raw_progress
            self._has_determinate_progress = True
        else:
            self._current = 0
        self.update()

    def finish_progress(self) -> None:
        self._current = 1
        self._total = 1
        self._raw_progress = 1.0
        self._target_progress = 1.0
        self._display_progress = 1.0
        self._has_determinate_progress = True
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def _advance_progress_phase(self) -> None:
        if not self.isVisible():
            return
        now = time.monotonic()
        self._phase = ((now - self._animation_started_at) * 0.34) % 1.0
        should_update = True
        if self._has_determinate_progress and self._display_progress < self._target_progress:
            delta = self._target_progress - self._display_progress
            self._display_progress = min(self._target_progress, self._display_progress + max(0.003, delta * 0.16))
        if should_update:
            self.update()

    def _draw_falling_blocks(self, painter: QPainter, rect) -> None:
        width = max(1.0, float(rect.width()))
        height = max(1.0, float(rect.height()))
        elapsed = max(0.0, time.monotonic() - self._animation_started_at)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(Qt.NoPen)
        for x_factor, seed, speed, size, alpha_factor in self._falling_blocks:
            x = rect.left() + width * x_factor
            travel = height + 28.0
            y = rect.top() - 18.0 + (((elapsed * speed) + seed) % 1.0) * travel
            alpha = int(38 * alpha_factor)
            painter.setBrush(_splash_color_with_alpha(_splash_theme_color(self._theme_key, "accent", "#c56d43"), alpha))
            painter.drawRect(QRectF(x, y, size, size))
        painter.restore()

    def _rounded_path(self, rect, radius: float = 12.0) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        return path

    def _rounded_path_length(self, rect, radius: float = 12.0) -> float:
        width = max(float(rect.width()), 1.0)
        height = max(float(rect.height()), 1.0)
        radius = min(max(float(radius), 0.0), width * 0.5, height * 0.5)
        return max(1.0, (2.0 * (width + height - (4.0 * radius))) + (2.0 * 3.141592653589793 * radius))

    def _draw_path_segment(
        self,
        painter: QPainter,
        path: QPainterPath,
        path_length: float,
        start: float,
        span: float,
        color: QColor,
        width: float,
    ) -> None:
        span = min(max(float(span), 0.0), 1.0)
        if span <= 0.0:
            return
        pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        if span < 0.995:
            dash = max(0.1, span * path_length)
            gap = max(1.0, path_length - dash)
            width_units = max(float(width), 0.1)
            pen.setDashPattern([dash / width_units, gap / width_units])
            pen.setDashOffset(-((float(start) % 1.0) * path_length) / width_units)
        painter.setPen(pen)
        painter.drawPath(path)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        card_rect = self.rect().adjusted(0, 0, -1, -1)
        if card_rect.width() <= 4 or card_rect.height() <= 4:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_splash_theme_color(self._theme_key, "surface", "#252526"))
        painter.drawRoundedRect(card_rect, 10, 10)

        rect = card_rect.adjusted(1, 1, -1, -1)
        self._draw_falling_blocks(painter, rect.adjusted(16, 10, -16, -32))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(_splash_color_with_alpha(_splash_theme_color(self._theme_key, "border_strong", "#3c3c3c"), 190), 1.0))
        painter.drawRoundedRect(rect, 10, 10)

        rail = QRectF(rect.left() + 24, rect.bottom() - 18, rect.width() - 48, 3)
        accent = _splash_theme_color(self._theme_key, "accent", "#c56d43")
        painter.setPen(Qt.NoPen)
        painter.setBrush(_splash_color_with_alpha(accent, 42))
        painter.drawRoundedRect(rail, 1.5, 1.5)
        if self._has_determinate_progress:
            progress = min(max(self._display_progress, 0.0), 1.0)
            if progress > 0.01:
                fill = QRectF(rail.left(), rail.top(), rail.width() * progress, rail.height())
                painter.setBrush(accent)
                painter.drawRoundedRect(fill, 1.5, 1.5)
        else:
            sweep_width = rail.width() * 0.24
            sweep_left = rail.left() + ((rail.width() + sweep_width) * self._phase) - sweep_width
            sweep = QRectF(sweep_left, rail.top(), sweep_width, rail.height())
            painter.setBrush(accent)
            painter.drawRoundedRect(sweep.intersected(rail), 1.5, 1.5)

class StartupSplashDialog(QDialog):
    def __init__(self, *, theme_key: str = DEFAULT_UI_THEME):
        super().__init__(None)
        self._theme_key = _splash_resolved_theme_key(theme_key)
        self.setWindowTitle("CDMW")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(False)
        self.setFixedSize(420, 210)
        self.setObjectName("StartupSplash")
        self._last_event_flush = 0.0
        self._shown_at = time.monotonic()
        self._minimum_visible_seconds = 3.0

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.progress_card = StartupProgressCard(self, theme_key=self._theme_key)
        root_layout.addWidget(self.progress_card)

        card_layout = QVBoxLayout(self.progress_card)
        card_layout.setContentsMargins(30, 24, 30, 24)
        card_layout.setSpacing(10)

        self.signal_mark = StartupSignalMark(self.progress_card, theme_key=self._theme_key)
        card_layout.addWidget(self.signal_mark)

        self.title_label = QLabel("Crimson Desert Mod Workbench")
        self.title_label.setObjectName("StartupSplashTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.title_label)

        self.detail_label = QLabel("Starting application...")
        self.detail_label.setObjectName("StartupSplashDetail")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setMinimumHeight(42)
        self.detail_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card_layout.addWidget(self.detail_label)

        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        self.setStyleSheet(
            f"""
            QDialog#StartupSplash {{
                background: transparent;
            }}
            QFrame#StartupSplashCard {{
                background: transparent;
            }}
            QFrame#StartupSignalMark {{
                background: transparent;
            }}
            QLabel#StartupSplashTitle {{
                color: {_splash_theme_value(self._theme_key, "text_strong", "#f1e8de")};
                font-size: 14px;
                font-weight: 500;
            }}
            QLabel#StartupSplashDetail {{
                color: {_splash_theme_value(self._theme_key, "text_muted", "#9f938c")};
                font-size: 10px;
                line-height: 13px;
            }}
            """
        )

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = _splash_resolved_theme_key(theme_key)
        self.progress_card.set_theme(self._theme_key)
        self.signal_mark.set_theme(self._theme_key)
        self._apply_theme_styles()
        self.update()

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def set_detail(self, detail: str, current: int = 0, total: int = 0) -> None:
        text = _format_startup_splash_detail(detail)
        self.detail_label.setText(text)
        self.progress_card.set_progress(current, total)
        if self._is_completion_detail(text, current, total):
            self.progress_card.finish_progress()
        self.pump_animation_frame()

    def _is_completion_detail(self, detail: str, current: int = 0, total: int = 0) -> bool:
        if int(total or 0) <= 0 or int(current or 0) < int(total or 0):
            return False
        normalized = str(detail or "").replace("\n", " ").strip().lower()
        return (
            normalized.startswith("loaded ")
            or normalized.startswith("archive scan complete")
            or normalized.startswith("opening workspace")
        )

    def pump_animation_frame(self) -> None:
        now = time.monotonic()
        app = QApplication.instance()
        if (
            app is not None
            and app.thread() == QThread.currentThread()
            and self.isVisible()
            and now - self._last_event_flush >= 0.016
        ):
            self._last_event_flush = now
            self.signal_mark.update()
            self.progress_card.update()
            app.processEvents()

    def remaining_minimum_visible_ms(self) -> int:
        elapsed = max(0.0, time.monotonic() - self._shown_at)
        remaining = max(0.0, self._minimum_visible_seconds - elapsed)
        return int(math.ceil(remaining * 1000.0))

    def finish(self) -> None:
        self.signal_mark.stop()
        self.progress_card.stop()
        self.hide()
        self.deleteLater()

class StartupArchivePathDialog(QDialog):
    def __init__(
        self,
        *,
        theme_key: str = DEFAULT_UI_THEME,
        initial_path: str = "",
        startup_splash: Optional[object] = None,
    ) -> None:
        super().__init__(None)
        self._theme_key = _splash_resolved_theme_key(theme_key)
        self._startup_splash = startup_splash
        self._selected_path = ""
        self._autodetect_started = False
        self._autodetect_busy = False
        self.setWindowTitle("Set Crimson Desert Path")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.setObjectName("StartupArchivePathDialog")
        self.setMinimumWidth(520)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(8)

        self.detail_label = QLabel(
            "Choose the Crimson Desert folder or package root that contains game_files or .pamt archives."
        )
        self.detail_label.setObjectName("StartupArchivePathDetail")
        self.detail_label.setWordWrap(True)
        root_layout.addWidget(self.detail_label)

        cache_note = QLabel(
            "After you continue, CDMW will build the archive cache. The first load can take a while; let it finish so future launches are fast."
        )
        cache_note.setObjectName("StartupArchivePathNote")
        cache_note.setWordWrap(True)
        root_layout.addWidget(cache_note)

        path_panel = QFrame(self)
        path_panel.setObjectName("StartupArchivePathPanel")
        path_layout = QGridLayout(path_panel)
        path_layout.setContentsMargins(10, 10, 10, 10)
        path_layout.setHorizontalSpacing(8)
        path_layout.setVerticalSpacing(6)

        path_label = QLabel("Path")
        path_label.setObjectName("StartupArchivePathFieldLabel")
        self.path_edit = QLineEdit(str(initial_path or ""))
        self.path_edit.setPlaceholderText("Crimson Desert install folder or package root")
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setMinimumWidth(92)
        self.autodetect_button = QPushButton("Auto-detect")
        self.autodetect_button.setMinimumWidth(104)
        self.candidates_combo = QComboBox()
        self.candidates_combo.setVisible(False)
        self.candidates_combo.setMinimumWidth(0)
        self.candidates_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        path_layout.addWidget(path_label, 0, 0)
        path_layout.addWidget(self.path_edit, 0, 1)
        path_layout.addWidget(self.browse_button, 0, 2)
        path_layout.addWidget(self.autodetect_button, 1, 2)
        path_layout.addWidget(self.candidates_combo, 1, 1)
        path_layout.setColumnStretch(1, 1)
        root_layout.addWidget(path_panel)

        self.status_label = QLabel("Checking known install locations...")
        self.status_label.setObjectName("StartupArchivePathStatus")
        self.status_label.setWordWrap(True)
        root_layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        self.skip_button = QPushButton("Skip")
        self.continue_button = QPushButton("Continue")
        self.continue_button.setDefault(True)
        self.continue_button.setMinimumWidth(100)
        button_row.addWidget(self.skip_button)
        button_row.addWidget(self.continue_button)
        root_layout.addLayout(button_row)

        self.browse_button.clicked.connect(self._browse_path)
        self.autodetect_button.clicked.connect(self._run_autodetect)
        self.continue_button.clicked.connect(self._accept_if_valid)
        self.skip_button.clicked.connect(self.reject)
        self.path_edit.textChanged.connect(self._validate_path_text)
        self.candidates_combo.currentTextChanged.connect(self._candidate_changed)
        self._apply_theme_styles()
        self._validate_path_text(self.path_edit.text())
        self.adjustSize()
        self.resize(max(self.width(), 520), self.sizeHint().height())
        QTimer.singleShot(80, self._run_initial_autodetect)

    def _apply_theme_styles(self) -> None:
        self.setStyleSheet(
            f"""
            QDialog#StartupArchivePathDialog {{
                background: {_splash_theme_value(self._theme_key, "window", "#1e1e1e")};
            }}
            QLabel#StartupArchivePathTitle {{
                color: {_splash_theme_value(self._theme_key, "text_strong", "#f1e8de")};
            }}
            QLabel#StartupArchivePathDetail,
            QLabel#StartupArchivePathStatus {{
                color: {_splash_theme_value(self._theme_key, "text_muted", "#9f938c")};
            }}
            QLabel#StartupArchivePathNote {{
                color: {_splash_theme_value(self._theme_key, "text_strong", "#f1e8de")};
                background: {_splash_theme_value(self._theme_key, "surface_alt", "#2a2d2e")};
                border: 1px solid {_splash_theme_value(self._theme_key, "border", "#2a2d2e")};
                border-radius: 6px;
                padding: 6px;
            }}
            QLabel#StartupArchivePathFieldLabel {{
                color: {_splash_theme_value(self._theme_key, "text_muted", "#9f938c")};
            }}
            QFrame#StartupArchivePathPanel {{
                background: {_splash_theme_value(self._theme_key, "surface", "#252526")};
                border: 1px solid {_splash_theme_value(self._theme_key, "border_strong", "#3c3c3c")};
                border-radius: 8px;
            }}
            QLineEdit,
            QComboBox {{
                color: {_splash_theme_value(self._theme_key, "text_strong", "#f1e8de")};
                background: {_splash_theme_value(self._theme_key, "input_bg", "#1e1e1e")};
                border: 1px solid {_splash_theme_value(self._theme_key, "border", "#2a2d2e")};
                border-radius: 4px;
                padding: 5px;
            }}
            QPushButton {{
                color: {_splash_theme_value(self._theme_key, "text_strong", "#f1e8de")};
                background: {_splash_theme_value(self._theme_key, "button_bg", "#2f3437")};
                border: 1px solid {_splash_theme_value(self._theme_key, "border_strong", "#3c3c3c")};
                border-radius: 4px;
                padding: 5px 10px;
            }}
            QPushButton:default {{
                background: {_splash_theme_value(self._theme_key, "accent", "#c56d43")};
                color: {_splash_theme_value(self._theme_key, "accent_text", "#ffffff")};
            }}
            QPushButton:disabled {{
                color: {_splash_theme_value(self._theme_key, "text_disabled", "#6c6c6c")};
                background: {_splash_theme_value(self._theme_key, "surface_alt", "#2a2d2e")};
            }}
            """
        )

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def selected_path(self) -> str:
        return self._selected_path

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.setText(str(text or ""))
        self.status_label.setProperty("error", bool(error))
        if error:
            self.status_label.setStyleSheet("color: #ffb4a8;")
        else:
            self.status_label.setStyleSheet("")

    def _set_busy(self, busy: bool) -> None:
        self._autodetect_busy = bool(busy)
        self.autodetect_button.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.path_edit.setEnabled(not busy)
        self.candidates_combo.setEnabled(not busy)
        self.continue_button.setEnabled(not busy and self._path_is_valid(self.path_edit.text()))

    def _path_is_valid(self, text: str) -> bool:
        path_text = str(text or "").strip()
        if not path_text:
            return False
        return looks_like_archive_package_root(Path(path_text).expanduser())

    def _validate_path_text(self, text: str) -> None:
        if self._autodetect_busy:
            return
        path_text = str(text or "").strip()
        if not path_text:
            self.continue_button.setEnabled(False)
            return
        valid = self._path_is_valid(path_text)
        self.continue_button.setEnabled(valid)
        if valid:
            self._set_status("Ready to build the archive cache for this path.")
        else:
            self._set_status("Waiting for a valid Crimson Desert folder or package root.")

    def _candidate_changed(self, text: str) -> None:
        candidate = str(text or "").strip()
        if candidate:
            self.path_edit.setText(candidate)

    def _browse_path(self) -> None:
        current_text = self.path_edit.text().strip()
        start_dir = str(Path(current_text).expanduser()) if current_text else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Select Crimson Desert Folder", start_dir)
        if selected:
            self.path_edit.setText(selected)
            if self._path_is_valid(selected):
                self._set_status("Ready to build the archive cache for this path.")
            else:
                self._set_status(
                    "That folder does not look like a Crimson Desert package root. Choose the install folder or the folder containing .pamt archives.",
                    error=True,
                )

    def _run_initial_autodetect(self) -> None:
        if self._autodetect_started or self.path_edit.text().strip():
            return
        self._run_autodetect()

    def _run_autodetect(self) -> None:
        if self._autodetect_busy:
            return
        self._autodetect_started = True
        self._set_busy(True)
        self._set_status("Checking Steam libraries and common custom install locations...")
        if self._startup_splash is not None:
            try:
                self._startup_splash.set_detail("Auto-detecting Crimson Desert path...")
            except Exception:
                pass
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        logs: List[str] = []
        candidates: List[str] = []
        error_text = ""
        try:
            candidates = [str(path) for path in autodetect_archive_package_roots(on_log=logs.append)]
        except Exception as exc:
            error_text = str(exc)
        finally:
            QApplication.restoreOverrideCursor()
            self._set_busy(False)
        self.candidates_combo.blockSignals(True)
        try:
            self.candidates_combo.clear()
            self.candidates_combo.addItems(candidates)
            self.candidates_combo.setVisible(len(candidates) > 1)
        finally:
            self.candidates_combo.blockSignals(False)
        if candidates:
            self.path_edit.setText(candidates[0])
            if len(candidates) == 1:
                self._set_status("Auto-detected a Crimson Desert package root. Continue to build the cache.")
            else:
                self._set_status("Auto-detected multiple package roots. Pick one, then continue to build the cache.")
            return
        if error_text:
            self._set_status(f"Auto-detect failed: {error_text}. Use Browse to select the folder manually.", error=True)
            return
        detail = logs[-1] if logs else "No valid Crimson Desert package root was auto-detected."
        self._set_status(f"{detail} Use Browse to select the folder manually.", error=True)

    def _accept_if_valid(self) -> None:
        path_text = self.path_edit.text().strip()
        if not path_text:
            self._set_status("Choose the Crimson Desert folder before continuing.", error=True)
            return
        package_root = Path(path_text).expanduser()
        if not looks_like_archive_package_root(package_root):
            self._set_status(
                "That folder does not look like a Crimson Desert package root. Choose the install folder or the folder containing .pamt archives.",
                error=True,
            )
            return
        try:
            package_root = package_root.resolve()
        except OSError:
            pass
        self._selected_path = str(package_root)
        self.accept()


__all__ = [
    "StartupArchivePathDialog",
    "StartupProgressCard",
    "StartupSignalMark",
    "StartupSplashDialog",
]
