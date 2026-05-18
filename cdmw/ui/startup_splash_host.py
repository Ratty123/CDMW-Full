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


def run_startup_splash_host(command_file: Path, *, parent_pid: int = 0) -> int:
    try:
        from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
        from PySide6.QtGui import QColor, QFont, QPainter, QPen
        from PySide6.QtWidgets import QApplication, QDialog, QLabel, QSizePolicy, QVBoxLayout
    except ImportError:
        return 1

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
            layout.setContentsMargins(30, 90, 30, 24)
            layout.setSpacing(8)
            layout.addStretch(1)

            self.title_label = QLabel("Crimson Desert Mod Workbench")
            self.title_label.setAlignment(Qt.AlignCenter)
            self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            title_font = QFont()
            title_font.setPointSize(14)
            title_font.setWeight(QFont.Medium)
            self.title_label.setFont(title_font)
            layout.addWidget(self.title_label)

            self.detail_label = QLabel(self._detail)
            self.detail_label.setAlignment(Qt.AlignCenter)
            self.detail_label.setWordWrap(True)
            detail_font = QFont()
            detail_font.setPointSize(8)
            self.detail_label.setFont(detail_font)
            self.detail_label.setMinimumHeight(42)
            layout.addWidget(self.detail_label)
            layout.addSpacing(24)

            self.setStyleSheet(
                """
                QLabel {
                    background: transparent;
                }
                QLabel {
                    color: #f1e8de;
                }
                """
            )
            self.detail_label.setStyleSheet("color: #9f938c;")

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
            try:
                payload = json.loads(command_file.read_text(encoding="utf-8"))
            except FileNotFoundError:
                self.close()
                return
            except Exception:
                return
            if isinstance(payload, dict):
                if payload.get("closed"):
                    self.close()
                    return
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
                painter.setBrush(QColor(197, 109, 67, int(38 * alpha_factor)))
                painter.drawRect(QRectF(x, y, size, size))
            painter.restore()

        def paintEvent(self, event) -> None:  # type: ignore[override]
            del event
            card = self.rect().adjusted(0, 0, -1, -1)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#11100f"))
            painter.drawRoundedRect(card, 10, 10)

            rect = QRectF(card.adjusted(1, 1, -1, -1))
            self._draw_falling_blocks(painter, rect.adjusted(16, 10, -16, -32))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(62, 52, 47, 190), 1.0))
            painter.drawRoundedRect(rect, 10, 10)

            mark_size = 34.0
            center_x = rect.left() + rect.width() * 0.5
            center_y = rect.top() + 68.0
            mark_rect = QRectF(center_x - mark_size * 0.5, center_y - mark_size * 0.5, mark_size, mark_size)
            painter.setPen(QPen(QColor(71, 54, 46, 220), 1.0))
            painter.setBrush(QColor("#181412"))
            painter.drawRoundedRect(mark_rect, 8, 8)
            painter.setPen(QPen(QColor(197, 109, 67, 64), 1.2))
            painter.drawRoundedRect(mark_rect.adjusted(3, 3, -3, -3), 5, 5)
            sweep_angle = int(((self._phase * 360.0) - 90.0) * 16.0)
            painter.setPen(QPen(QColor("#c56d43"), 2.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(mark_rect.adjusted(7, 7, -7, -7), sweep_angle, int(112 * 16))
            dot_angle = (self._phase * math.tau) - (math.pi * 0.5)
            dot_radius = mark_size * 0.26
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(240, 210, 184, 220))
            painter.drawEllipse(
                QPoint(
                    int(center_x + math.cos(dot_angle) * dot_radius),
                    int(center_y + math.sin(dot_angle) * dot_radius),
                ),
                2,
                2,
            )

            rail = QRectF(rect.left() + 72, rect.bottom() - 42, rect.width() - 144, 3)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(197, 109, 67, 42))
            painter.drawRoundedRect(rail, 1.5, 1.5)
            painter.setBrush(QColor("#c56d43"))
            if self._has_determinate_progress:
                progress = min(max(self._display_progress, 0.0), 1.0)
                if progress > 0.01:
                    painter.drawRoundedRect(QRectF(rail.left(), rail.top(), rail.width() * progress, rail.height()), 1.5, 1.5)
                progress_text = f"{self._current:,} / {self._total:,}" if self._total > 1 else f"{int(progress * 100):d}%"
                painter.setPen(QPen(QColor(159, 147, 140, 210), 1.0))
                painter.drawText(QRectF(rail.left(), rail.top() - 20, rail.width(), 14), Qt.AlignCenter, progress_text)
            else:
                sweep_width = rail.width() * 0.24
                sweep_left = rail.left() + ((rail.width() + sweep_width) * self._phase) - sweep_width
                painter.drawRoundedRect(QRectF(sweep_left, rail.top(), sweep_width, rail.height()).intersected(rail), 1.5, 1.5)

    app = QApplication(sys.argv[:1])
    dialog = StartupSplashHost()
    dialog.center_on_screen()
    dialog.show()
    try:
        command_file.with_suffix(".ready").write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    return int(app.exec())


__all__ = ["run_startup_splash_host"]
