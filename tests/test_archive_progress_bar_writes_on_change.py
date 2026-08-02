"""The archive progress bar is written only when something changed.

`_set_archive_load_progress` runs at progress-callback cadence, and every
`setRange`/`setValue`/`setFormat`/`setToolTip` walks Qt's native style and
paint machinery even when the value is identical. The one recorded full
freeze wedged the main thread inside `QProgressBar.setValue` with no Python
frames below it, and the indeterminate busy bar re-armed its animation on
every callback. Redundant writes must therefore be skipped entirely.
"""

from __future__ import annotations

from cdmw.ui.archive_browser.progress import ArchiveProgressMixin


class _RecordingBar:
    def __init__(self) -> None:
        self._minimum = 0
        self._maximum = 100
        self._value = 0
        self._format = ""
        self._tooltip = ""
        self.writes: list[tuple[str, object]] = []

    def maximum(self) -> int:
        return self._maximum

    def value(self) -> int:
        return self._value

    def toolTip(self) -> str:
        return self._tooltip

    def setRange(self, minimum: int, maximum: int) -> None:
        self.writes.append(("setRange", (minimum, maximum)))
        self._minimum = minimum
        self._maximum = maximum

    def setValue(self, value: int) -> None:
        self.writes.append(("setValue", value))
        self._value = value

    def setFormat(self, fmt: str) -> None:
        self.writes.append(("setFormat", fmt))
        self._format = fmt

    def setToolTip(self, text: str) -> None:
        self.writes.append(("setToolTip", text))
        self._tooltip = text


class _Owner(ArchiveProgressMixin):
    def __init__(self) -> None:
        self.archive_scan_progress_bar = _RecordingBar()
        self._archive_load_progress_percent = 0
        self._archive_load_progress_active = True
        self._archive_load_progress_detail = ""

    def _dashboard_set_archive_progress(self, *_args: object, **_kwargs: object) -> None:
        pass


def test_a_repeated_identical_progress_report_writes_nothing() -> None:
    owner = _Owner()
    owner._set_archive_load_progress("Scanning archive packages...", phase="Scanning", percent=38)
    writes_after_first = list(owner.archive_scan_progress_bar.writes)
    assert ("setValue", 38) in writes_after_first

    owner._set_archive_load_progress("Scanning archive packages...", phase="Scanning", percent=38)

    assert owner.archive_scan_progress_bar.writes == writes_after_first


def test_a_repeated_indeterminate_report_does_not_rearm_the_busy_animation() -> None:
    owner = _Owner()
    owner._set_archive_load_progress("Working...", phase="Scanning", indeterminate=True)
    assert ("setRange", (0, 0)) in owner.archive_scan_progress_bar.writes
    writes_after_first = list(owner.archive_scan_progress_bar.writes)

    owner._set_archive_load_progress("Working...", phase="Scanning", indeterminate=True)

    assert owner.archive_scan_progress_bar.writes == writes_after_first


def test_leaving_indeterminate_always_restores_value_and_format() -> None:
    owner = _Owner()
    owner._set_archive_load_progress("Working...", phase="Scanning", indeterminate=True)
    # The bar's stored value can coincide with the next percent; the format
    # was blanked by the indeterminate switch, so both must still be written.
    owner.archive_scan_progress_bar._value = 0
    owner._archive_load_progress_percent = 0

    owner._set_archive_load_progress("Scanning archive packages...", phase="Scanning", percent=0)

    assert ("setRange", (0, 100)) in owner.archive_scan_progress_bar.writes
    assert ("setValue", 0) in owner.archive_scan_progress_bar.writes
    assert ("setFormat", "0%") in owner.archive_scan_progress_bar.writes


def test_progress_still_advances_normally() -> None:
    owner = _Owner()
    owner._set_archive_load_progress("Scanning...", phase="Scanning", percent=10)
    owner._set_archive_load_progress("Scanning...", phase="Scanning", percent=25)

    bar = owner.archive_scan_progress_bar
    assert bar._value == 25
    assert bar._format == "25%"
