"""Cancellable, read-only executable hashing before archive opening."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal

from cdmw.models import RunCancelled
from cdmw.services.game_executable_fingerprints import check_game_executable_fingerprints
from cdmw.workers.runnable_signals import application_owned, release


class _FingerprintSignals(QObject):
    completed = Signal(int, object)


class GameExecutableFingerprintTask(QRunnable):
    def __init__(self, generation, root, records, stop_event):
        super().__init__()
        self.generation, self.root, self.records, self.stop_event = generation, root, records, stop_event
        self.signals = application_owned(_FingerprintSignals)

    def run(self):
        try:
            try:
                result = check_game_executable_fingerprints(self.root, self.records, stop_event=self.stop_event)
            except RunCancelled:
                return
            except Exception as error:
                result = None, (f"Game update check skipped: {error}",), False
            if not self.stop_event.is_set():
                self.signals.completed.emit(self.generation, result)
        finally:
            release(self.signals)
