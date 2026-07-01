from __future__ import annotations

import ctypes
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional


def _format_startup_splash_detail(detail: str, *, max_chars: int = 88, split_at: int = 44) -> str:
    text = " ".join(str(detail or "Starting application...").split()) or "Starting application..."
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 3)].rstrip() + "..."
    if len(text) > split_at:
        break_at = text.rfind(" ", 0, split_at)
        if break_at < max(18, split_at // 2):
            break_at = split_at
        text = f"{text[:break_at].rstrip()}\n{text[break_at:].strip()}"
    return text


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return int(exit_code.value) == 259
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def _apply_windows_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        from cdmw.constants import APP_NAME, APP_ORGANIZATION

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ORGANIZATION}.{APP_NAME}")
    except Exception:
        pass


def run_startup_splash_host(command_file: Path, *, parent_pid: int = 0) -> int:
    try:
        from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
        from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPolygonF
        from PySide6.QtWidgets import QApplication, QDialog, QLabel, QSizePolicy, QVBoxLayout
    except ImportError:
        return 1
    try:
        from cdmw.constants import APP_NAME, APP_ORGANIZATION, DEFAULT_UI_THEME
        from cdmw.ui.app_icon import resolve_app_icon_path
        from cdmw.ui.themes import UI_THEME_SCHEMES
    except Exception:
        APP_NAME = "CrimsonDesertModWorkbench"
        APP_ORGANIZATION = "Ratrider"
        DEFAULT_UI_THEME = "graphite"
        UI_THEME_SCHEMES = {
            "graphite": {
                "window": "#1e1e1e",
                "surface": "#252526",
                "border": "#2a2d2e",
                "border_strong": "#3c3c3c",
                "text_strong": "#f3f3f3",
                "text_muted": "#9da0a6",
                "accent": "#007acc",
            }
        }
        resolve_app_icon_path = None  # type: ignore[assignment]

    def _command_payload() -> dict:
        try:
            payload = json.loads(command_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"closed": True}
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _resolved_theme_key(theme_key: object) -> str:
        key = str(theme_key or "").strip()
        return key if key in UI_THEME_SCHEMES else DEFAULT_UI_THEME

    def _theme_value(theme_key: str, role: str, fallback: str) -> str:
        theme = UI_THEME_SCHEMES.get(_resolved_theme_key(theme_key), UI_THEME_SCHEMES.get(DEFAULT_UI_THEME, {}))
        return str(theme.get(role, fallback) or fallback)

    def _theme_color(theme_key: str, role: str, fallback: str) -> QColor:
        color = QColor(_theme_value(theme_key, role, fallback))
        return color if color.isValid() else QColor(fallback)

    def _with_alpha(color: QColor, alpha: int) -> QColor:
        result = QColor(color)
        result.setAlpha(max(0, min(255, int(alpha))))
        return result

    def _accent_block_colors(theme_key: str, alpha: int) -> tuple[QColor, QColor, QColor, QColor, QColor, QColor]:
        accent = _theme_color(theme_key, "accent", "#c56d43")
        colors = (
            accent.lighter(135),
            accent.darker(112),
            accent.lighter(165),
            accent.lighter(108),
            accent.darker(150),
            accent.darker(230),
        )
        return tuple(_with_alpha(color, alpha) for color in colors)  # type: ignore[return-value]

    class StartupSplashHost(QDialog):
        def __init__(self) -> None:
            super().__init__(None)
            self.setWindowTitle("CDMW")
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setModal(False)
            self.setFixedSize(420, 210)
            self._started_at = time.monotonic()
            self._phase = 0.0
            self._detail = "Starting application..."
            self._current = 0
            self._total = 0
            self._theme_key = _resolved_theme_key(_command_payload().get("theme_key", DEFAULT_UI_THEME))
            self._display_progress = 0.0
            self._target_progress = 0.0
            self._has_determinate_progress = False
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

            layout = QVBoxLayout(self)
            layout.setContentsMargins(30, 82, 30, 18)
            layout.setSpacing(6)
            layout.addStretch(1)

            self.title_label = QLabel("Crimson Desert Mod Workbench")
            self.title_label.setAlignment(Qt.AlignCenter)
            self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            title_font = QFont(self.font())
            title_font.setPointSize(max(1, title_font.pointSize() + 4))
            title_font.setWeight(QFont.Medium)
            self.title_label.setFont(title_font)
            layout.addWidget(self.title_label)

            self.detail_label = QLabel(self._detail)
            self.detail_label.setAlignment(Qt.AlignCenter)
            self.detail_label.setWordWrap(True)
            detail_font = QFont(self.font())
            detail_font.setPointSize(max(1, detail_font.pointSize() - 2))
            self.detail_label.setFont(detail_font)
            self.detail_label.setMinimumHeight(32)
            self.detail_label.setMaximumHeight(34)
            layout.addWidget(self.detail_label)

            layout.addSpacing(30)

            self._apply_theme_styles()

            self._frame_timer = QTimer(self)
            self._frame_timer.setTimerType(Qt.PreciseTimer)
            self._frame_timer.setInterval(16)
            self._frame_timer.timeout.connect(self._advance_frame)
            self._frame_timer.start()

            self._command_timer = QTimer(self)
            self._command_timer.setInterval(50)
            self._command_timer.timeout.connect(self._poll_command_file)
            self._command_timer.start()

        def center_on_screen(self) -> None:
            screen = QApplication.primaryScreen()
            if screen is None:
                return
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())

        def _apply_theme_styles(self) -> None:
            self.setStyleSheet(
                f"""
                QLabel {{
                    background: transparent;
                    color: {_theme_value(self._theme_key, "text_strong", "#f1e8de")};
                }}
                """
            )
            self.detail_label.setStyleSheet(f"color: {_theme_value(self._theme_key, 'text_muted', '#9f938c')};")

        def _set_theme(self, theme_key: object) -> None:
            resolved_theme_key = _resolved_theme_key(theme_key)
            if resolved_theme_key == self._theme_key:
                return
            self._theme_key = resolved_theme_key
            if resolve_app_icon_path is not None:
                try:
                    icon_path = resolve_app_icon_path(resolved_theme_key)
                    if icon_path is not None:
                        icon = QIcon(str(icon_path))
                        if not icon.isNull():
                            QApplication.instance().setWindowIcon(icon)
                            self.setWindowIcon(icon)
                except Exception:
                    pass
            self._apply_theme_styles()
            self.update()

        def _set_detail(self, detail: str) -> None:
            text = _format_startup_splash_detail(detail)
            if text != self._detail:
                self._detail = text
                self.detail_label.setText(text)

        def _set_progress(self, current: int = 0, total: int = 0) -> None:
            previous_target = self._target_progress
            next_total = max(0, int(total or 0))
            self._total = next_total
            if next_total > 0:
                self._current = min(max(int(current or 0), 0), next_total)
                raw_progress = min(max(self._current / max(next_total, 1), 0.0), 1.0)
                if self._is_completion_detail() and raw_progress >= 0.999:
                    self._target_progress = 1.0
                    self._display_progress = 1.0
                elif raw_progress + 0.015 < previous_target:
                    self._target_progress = min(0.965, max(previous_target, self._display_progress) + 0.045)
                elif raw_progress >= 0.999:
                    self._target_progress = max(previous_target, min(0.965, previous_target + 0.035))
                else:
                    self._target_progress = max(previous_target, min(raw_progress, 0.965))
                self._has_determinate_progress = True
            else:
                self._current = 0
                self._total = 0

        def _payload_int(self, payload: dict, key: str) -> int:
            try:
                return int(payload.get(key, 0) or 0)
            except Exception:
                return 0

        def _is_completion_detail(self) -> bool:
            detail = self._detail.replace("\n", " ").strip().lower()
            return (
                detail.startswith("loaded ")
                or detail.startswith("archive scan complete")
                or detail.startswith("opening workspace")
            )

        def _poll_command_file(self) -> None:
            if parent_pid and not _pid_is_alive(parent_pid):
                self.close()
                return
            payload = _command_payload()
            if payload.get("closed"):
                self.close()
                return
            if not payload:
                return
            if isinstance(payload, dict):
                self._set_theme(payload.get("theme_key", self._theme_key))
                self._set_detail(str(payload.get("detail", "") or "Starting application..."))
                self._set_progress(
                    self._payload_int(payload, "current"),
                    self._payload_int(payload, "total"),
                )

        def _advance_frame(self) -> None:
            self._phase = ((time.monotonic() - self._started_at) * 0.72) % 1.0
            if self._has_determinate_progress and self._display_progress < self._target_progress:
                delta = self._target_progress - self._display_progress
                self._display_progress = min(self._target_progress, self._display_progress + max(0.003, delta * 0.16))
            self.update()

        def _draw_falling_blocks(self, painter: QPainter, rect: QRectF) -> None:
            elapsed = max(0.0, time.monotonic() - self._started_at)
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.setPen(Qt.NoPen)
            for x_factor, seed, speed, size, alpha_factor in self._falling_blocks:
                x = rect.left() + rect.width() * x_factor
                travel = rect.height() + 28.0
                y = rect.top() - 18.0 + (((elapsed * speed) + seed) % 1.0) * travel
                painter.setBrush(_with_alpha(_theme_color(self._theme_key, "accent", "#c56d43"), int(38 * alpha_factor)))
                painter.drawRect(QRectF(x, y, size, size))
            painter.restore()

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
            top_a, top_b, left_a, left_b, right_a, right_b = _accent_block_colors(self._theme_key, alpha)

            painter.setPen(Qt.NoPen)
            painter.setBrush(self._face_gradient(left, left_a, left_b))
            painter.drawPolygon(left)
            painter.setBrush(self._face_gradient(right, right_a, right_b))
            painter.drawPolygon(right)
            painter.setBrush(self._face_gradient(top, top_a, top_b))
            painter.drawPolygon(top)
            painter.setPen(QPen(_with_alpha(_theme_color(self._theme_key, "accent", "#c56d43"), int(46 * opacity)), 0.7))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolyline(top)

        def _draw_block_wave_mark(self, painter: QPainter, rect: QRectF) -> None:
            width = max(1.0, float(rect.width()))
            height = max(1.0, float(rect.height()))
            center_x = rect.left() + width * 0.5
            anchor_y = rect.top() + height * 0.78
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
                        self._draw_iso_block(painter, x, base_y - (level + 1) * block_height, half_width, half_depth, block_height)
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
            del event
            card = self.rect().adjusted(0, 0, -1, -1)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(_theme_color(self._theme_key, "surface", "#252526"))
            painter.drawRoundedRect(card, 10, 10)

            rect = QRectF(card.adjusted(1, 1, -1, -1))
            self._draw_falling_blocks(painter, rect.adjusted(16, 10, -16, -32))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(_with_alpha(_theme_color(self._theme_key, "border_strong", "#3c3c3c"), 190), 1.0))
            painter.drawRoundedRect(rect, 10, 10)

            self._draw_block_wave_mark(painter, QRectF(rect.left() + 52, rect.top() + 14, rect.width() - 104, 70))

            rail = QRectF(rect.left() + 72, rect.bottom() - 42, rect.width() - 144, 3)
            painter.setPen(Qt.NoPen)
            painter.setBrush(_with_alpha(_theme_color(self._theme_key, "accent", "#c56d43"), 42))
            painter.drawRoundedRect(rail, 1.5, 1.5)
            painter.setBrush(_theme_color(self._theme_key, "accent", "#c56d43"))
            if self._has_determinate_progress:
                progress = min(max(self._display_progress, 0.0), 1.0)
                if progress > 0.01:
                    painter.drawRoundedRect(QRectF(rail.left(), rail.top(), rail.width() * progress, rail.height()), 1.5, 1.5)
            else:
                sweep_width = rail.width() * 0.24
                sweep_left = rail.left() + ((rail.width() + sweep_width) * self._phase) - sweep_width
                painter.drawRoundedRect(QRectF(sweep_left, rail.top(), sweep_width, rail.height()).intersected(rail), 1.5, 1.5)

    _apply_windows_app_user_model_id()
    app = QApplication(sys.argv[:1])
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationName(APP_NAME)
    app_icon = QIcon()
    initial_theme_key = _resolved_theme_key(_command_payload().get("theme_key", DEFAULT_UI_THEME))
    if resolve_app_icon_path is not None:
        try:
            icon_path = resolve_app_icon_path(initial_theme_key)
            if icon_path is not None:
                app_icon = QIcon(str(icon_path))
                if not app_icon.isNull():
                    app.setWindowIcon(app_icon)
        except Exception:
            app_icon = QIcon()
    dialog = StartupSplashHost()
    if not app_icon.isNull():
        dialog.setWindowIcon(app_icon)
    dialog.center_on_screen()
    dialog.show()
    try:
        command_file.with_suffix(".ready").write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    return int(app.exec())


__all__ = ["run_startup_splash_host"]
