"""The two dialogs that put a translation model behind the Translation Studio.

`ProviderSettingsDialog` is where the key lives: pick a provider, paste a key, press
Test, and find out in two seconds whether the model id was right -- rather than at line
four hundred of a pass.

`TranslateDialog` is the pass itself. It insists on being explicit about scope, because
the difference between "the twelve lines I searched for" and "all 187,521" is the
difference between a few cents and a bill worth noticing, and a picker that defaults to
the whole table would eventually be clicked by accident. It applies each batch as it
arrives, so Stop leaves the work done so far in the table.

Neither dialog knows anything about `.paloc`: they take lines in and hand translations
back through a callback, which is what lets the tests drive the whole pass headlessly.
"""

from __future__ import annotations

import threading
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .ai_job import BatchResult, JobSummary, run_job
from .ai_provider import PRESETS, ProviderConfig, load_config, preset_for, save_config
from .ai_translate import Line, TranslationBrief

#: Offered in the target-language box. It is editable -- any language the model knows works.
_COMMON_LANGUAGES = (
    "English", "Swedish", "Norwegian", "Danish", "Finnish", "German", "French",
    "Spanish", "Italian", "Portuguese (Brazil)", "Polish", "Czech", "Hungarian",
    "Dutch", "Russian", "Ukrainian", "Turkish", "Arabic", "Hebrew", "Hindi",
    "Thai", "Vietnamese", "Indonesian", "Korean", "Japanese",
    "Chinese (Simplified)", "Chinese (Traditional)",
)

#: Past this many lines the dialog asks again before spending the user's money.
_CONFIRM_ABOVE = 2000


class ProviderSettingsDialog(QDialog):
    """Which model translates, and on whose key."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Translation model")
        self.config = load_config()
        self._test_thread: Optional[QThread] = None
        self._test_worker: Optional[QObject] = None
        self._build()
        self._load_into_widgets()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        blurb = QLabel(
            "Bring your own API key. Nothing is sent anywhere until you start a "
            "translation, and the key is stored only on this machine."
        )
        blurb.setWordWrap(True)
        outer.addWidget(blurb)

        form = QFormLayout()
        self.preset_box = QComboBox()
        for preset in PRESETS:
            self.preset_box.addItem(preset.label, preset.key)
        self.preset_box.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("Provider", self.preset_box)

        self.base_url = QLineEdit()
        form.addRow("Base URL", self.base_url)

        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        form.addRow("Model", self.model_box)

        key_row = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("Paste your API key")
        key_row.addWidget(self.api_key, 1)
        self.show_key = QCheckBox("Show")
        self.show_key.toggled.connect(
            lambda on: self.api_key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        key_row.addWidget(self.show_key)
        key_holder = QWidget()
        key_holder.setLayout(key_row)
        form.addRow("API key", key_holder)
        outer.addLayout(form)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        outer.addWidget(self.note)

        outer.addWidget(self._build_tuning())

        test_row = QHBoxLayout()
        self.test_button = QPushButton("Test connection")
        self.test_button.setToolTip("Translate one short line, and report exactly what came back.")
        self.test_button.clicked.connect(self._on_test)
        test_row.addWidget(self.test_button)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_result, 1)
        outer.addLayout(test_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _build_tuning(self) -> QWidget:
        box = QGroupBox("How hard to push the provider")
        form = QFormLayout(box)
        self.batch_size = QSpinBox()
        self.batch_size.setRange(1, 200)
        self.batch_size.setToolTip("Lines per request. Fewer is more reliable; more is cheaper.")
        form.addRow("Lines per request", self.batch_size)
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 16)
        self.parallel.setToolTip("Requests in flight. Raise it until the provider starts rate-limiting.")
        form.addRow("Requests at once", self.parallel)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 900)
        self.timeout.setSuffix(" s")
        form.addRow("Request timeout", self.timeout)
        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(256, 128_000)
        self.max_tokens.setSingleStep(1024)
        form.addRow("Max reply tokens", self.max_tokens)
        self.disable_thinking = QCheckBox(
            "Turn off extended thinking (Claude 4.6 and later: cheaper, and translation "
            "rarely needs it)"
        )
        form.addRow("", self.disable_thinking)
        return box

    # --------------------------------------------------------------- widget state

    def _load_into_widgets(self) -> None:
        index = self.preset_box.findData(self.config.preset)
        self.preset_box.blockSignals(True)
        self.preset_box.setCurrentIndex(index if index >= 0 else 0)
        self.preset_box.blockSignals(False)
        self._refresh_preset(keep_values=True)
        self.base_url.setText(self.config.base_url or preset_for(self.config.preset).base_url)
        self.model_box.setCurrentText(self.config.model)
        self.api_key.setText(self.config.api_key)
        self.batch_size.setValue(self.config.batch_size)
        self.parallel.setValue(self.config.parallel)
        self.timeout.setValue(self.config.timeout)
        self.max_tokens.setValue(self.config.max_tokens)
        self.disable_thinking.setChecked(self.config.disable_thinking)

    def _on_preset_changed(self) -> None:
        self._refresh_preset(keep_values=False)

    def _refresh_preset(self, *, keep_values: bool) -> None:
        preset = preset_for(self.preset_box.currentData())
        self.note.setText(preset.note)
        current_model = self.model_box.currentText()
        self.model_box.clear()
        self.model_box.addItems(list(preset.models))
        self.model_box.setCurrentText(current_model if keep_values else preset.model)
        self.model_box.lineEdit().setPlaceholderText(preset.model_hint)
        if not keep_values:
            self.base_url.setText(preset.base_url)
        self.base_url.setPlaceholderText(preset.base_url or "https://your-endpoint")
        self.api_key.setEnabled(preset.needs_key)
        self.api_key.setPlaceholderText(
            "Paste your API key" if preset.needs_key else "not needed for a local model"
        )

    def collect(self) -> ProviderConfig:
        return ProviderConfig(
            preset=str(self.preset_box.currentData() or ""),
            base_url=self.base_url.text().strip(),
            model=self.model_box.currentText().strip(),
            api_key=self.api_key.text().strip(),
            batch_size=self.batch_size.value(),
            parallel=self.parallel.value(),
            timeout=self.timeout.value(),
            max_tokens=self.max_tokens.value(),
            disable_thinking=self.disable_thinking.isChecked(),
        )

    # ---------------------------------------------------------------- test / save

    def _on_test(self) -> None:
        config = self.collect()
        problems = config.problems()
        if problems:
            self.test_result.setText("Not ready: " + ", ".join(problems) + ".")
            return
        self.test_button.setEnabled(False)
        self.test_result.setText("Asking the provider...")
        self._test_thread = QThread(self)
        self._test_worker = _TestWorker(config)
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.done.connect(self._on_tested)
        self._test_worker.done.connect(self._test_thread.quit)
        self._test_thread.finished.connect(self._test_worker.deleteLater)
        self._test_thread.start()

    def _on_tested(self, ok: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        self.test_result.setText(("Works. " if ok else "Failed. ") + message)

    def _on_save(self) -> None:
        config = self.collect()
        self.config = save_config(config)
        if config.api_key and not self.config.key_is_encrypted:
            QMessageBox.warning(
                self,
                "Key stored unencrypted",
                "Windows account encryption was unavailable, so the API key is stored as "
                "plain text in the app's workspace folder. Anyone who can read that file "
                "can read the key.",
            )
        self.accept()


class _TestWorker(QObject):
    done = Signal(bool, str)

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__()
        self._config = config

    def run(self) -> None:
        from .ai_job import http_transport, send_once
        from .ai_translate import parse_translations

        # One real line with real markup in it, so the test exercises the thing that
        # actually goes wrong: a model that rewrites `{Key:Key_Roll}`.
        brief = TranslationBrief(target_language="French", source_language="English")
        batch = (Line(index=0, text="Take the sword.<br/>{Key:Key_Roll}"),)
        try:
            text = send_once(
                self._config,
                brief.system_prompt(),
                brief.user_prompt(batch),
                transport=http_transport,
            )
        except Exception as error:  # noqa: BLE001 - the message is the whole point here
            self.done.emit(False, str(error))
            return
        try:
            answer = parse_translations(text).get(0, "") if text else ""
        except Exception:  # noqa: BLE001 - a reply without JSON is a failed test, not a crash
            answer = ""
        if not answer:
            self.done.emit(False, "the model replied, but not with a translation: " + text[:160])
            return
        self.done.emit(True, f"Test line came back as: {answer}")


class _JobWorker(QObject):
    """Runs a whole pass off the UI thread and reports each batch as it lands."""

    progress = Signal(int, int)
    batch = Signal(object)
    finished = Signal(object)

    def __init__(
        self,
        config: ProviderConfig,
        brief: TranslationBrief,
        lines: Sequence[Line],
        *,
        skip_on_mismatch: bool,
        stop_event: threading.Event,
        transport=None,
    ) -> None:
        super().__init__()
        self._config = config
        self._brief = brief
        self._lines = list(lines)
        self._skip = skip_on_mismatch
        self._stop = stop_event
        self._transport = transport

    def run(self) -> None:
        try:
            summary = run_job(
                config=self._config,
                brief=self._brief,
                lines=self._lines,
                transport=self._transport,
                skip_on_mismatch=self._skip,
                on_result=self.batch.emit,
                on_progress=self.progress.emit,
                should_stop=self._stop.is_set,
            )
        except Exception as error:  # noqa: BLE001 - report, never take the window down
            summary = JobSummary(lines=len(self._lines), errors=(str(error),))
        self.finished.emit(summary)


class TranslateDialog(QDialog):
    """Pick a scope and a target language, then watch the pass land line by line."""

    def __init__(
        self,
        *,
        scopes: Sequence[tuple[str, Sequence[Line]]],
        working_language: str,
        apply_translations: Callable[[Mapping[int, str]], None],
        parent: Optional[QWidget] = None,
        transport=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Translate with AI")
        self.setMinimumWidth(560)
        self._scopes = list(scopes)
        self._apply = apply_translations
        self._working_language = working_language
        self._transport = transport
        self._stop = threading.Event()
        self._thread: Optional[QThread] = None
        self._worker: Optional[_JobWorker] = None
        self._rejected_examples: list[str] = []
        self.summary: Optional[JobSummary] = None
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)

        scope_box = QGroupBox("What to translate")
        scope_layout = QVBoxLayout(scope_box)
        self._scope_buttons: list[QRadioButton] = []
        for position, (label, lines) in enumerate(self._scopes):
            button = QRadioButton(f"{label} ({len(lines):,} line(s))")
            button.setChecked(position == 0)
            button.setEnabled(bool(lines))
            scope_layout.addWidget(button)
            self._scope_buttons.append(button)
        outer.addWidget(scope_box)

        form = QFormLayout()
        self.target_box = QComboBox()
        self.target_box.setEditable(True)
        self.target_box.addItems(list(_COMMON_LANGUAGES))
        self.target_box.setCurrentText("Swedish")
        form.addRow("Translate into", self.target_box)
        self.source_box = QLineEdit()
        self.source_box.setPlaceholderText("leave blank to let the model work it out")
        form.addRow("Source language", self.source_box)
        self.instructions = QLineEdit()
        self.instructions.setPlaceholderText(
            "optional: tone, glossary, how to render names, e.g. keep place names in English"
        )
        form.addRow("Extra instruction", self.instructions)
        outer.addLayout(form)

        self.skip_mismatch = QCheckBox(
            "Leave a line alone when its markup comes back changed (recommended)"
        )
        self.skip_mismatch.setChecked(True)
        outer.addWidget(self.skip_mismatch)

        slot = QLabel(
            f"The mod replaces the <b>{self._working_language}</b> table, so set the game to "
            f"that language to see the result — whatever you translate into."
        )
        slot.setWordWrap(True)
        outer.addWidget(slot)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        self.log.setVisible(False)
        outer.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self._on_start)
        row.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop)
        row.addWidget(self.stop_button)
        row.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        outer.addLayout(row)

    # ------------------------------------------------------------------ running

    def selected_lines(self) -> Sequence[Line]:
        for button, (_label, lines) in zip(self._scope_buttons, self._scopes):
            if button.isChecked():
                return lines
        return ()

    def _on_start(self) -> None:
        lines = self.selected_lines()
        target = self.target_box.currentText().strip()
        if not lines or not target:
            self._note("Pick a scope and a target language first.")
            return
        config = load_config()
        problems = config.problems()
        if problems:
            self._note(
                "The translation model is not set up: " + ", ".join(problems)
                + ". Use 'AI settings' first."
            )
            return
        if len(lines) > _CONFIRM_ABOVE:
            answer = QMessageBox.question(
                self,
                "That is a lot of lines",
                f"{len(lines):,} lines will be sent to {preset_for(config.preset).label} in "
                f"about {max(1, len(lines) // max(1, config.batch_size)):,} requests, billed "
                "to your own account. Continue?",
            )
            if answer != QMessageBox.Yes:
                return

        self._stop.clear()
        self._rejected_examples.clear()
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.log.setVisible(True)
        self.log.clear()
        self._note(f"Translating {len(lines):,} line(s) into {target}...")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.close_button.setEnabled(False)

        brief = TranslationBrief(
            target_language=target,
            source_language=self.source_box.text().strip(),
            instructions=self.instructions.text().strip(),
        )
        self._thread = QThread(self)
        self._worker = _JobWorker(
            config,
            brief,
            lines,
            skip_on_mismatch=self.skip_mismatch.isChecked(),
            stop_event=self._stop,
            transport=self._transport,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.batch.connect(self._on_batch)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def _on_stop(self) -> None:
        self._stop.set()
        self.stop_button.setEnabled(False)
        self._note("Stopping after the requests already in flight...")

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)

    def _on_batch(self, result: BatchResult) -> None:
        if result.error:
            self._note(f"Request {result.number} failed: {result.error}")
            return
        if result.accepted:
            self._apply(dict(result.accepted))
        for index, reason in result.rejected:
            if len(self._rejected_examples) < 20:
                self._rejected_examples.append(f"line {index}: {reason}")
        self._note(
            f"Request {result.number}: {len(result.accepted)} applied"
            + (f", {len(result.rejected)} left alone" if result.rejected else "")
        )

    def _on_finished(self, summary: JobSummary) -> None:
        self.summary = summary
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self._note(summary.describe())
        for example in self._rejected_examples[:10]:
            self._note("  " + example)
        for error in summary.errors:
            self._note("  " + error)

    def _note(self, message: str) -> None:
        self.log.setVisible(True)
        self.log.appendPlainText(message)

    def reject(self) -> None:  # noqa: D102 - Qt override
        self._stop.set()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)
        super().reject()


__all__ = ["ProviderSettingsDialog", "TranslateDialog"]
