from __future__ import annotations

from cdmw.ui.archive_browser.progress import ArchiveProgressMixin
from cdmw.ui.shell.dashboard_controller import DashboardControllerMixin


class _Style:
    def unpolish(self, _widget: object) -> None:
        pass

    def polish(self, _widget: object) -> None:
        pass


class _Label:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""
        self.properties: dict[str, object] = {}

    def property(self, name: str) -> object:
        return self.properties.get(name)

    def setProperty(self, name: str, value: object) -> None:
        self.properties[name] = value

    def setText(self, text: str) -> None:
        self.text = text

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def style(self) -> _Style:
        return _Style()

    def update(self) -> None:
        pass


class _Owner(ArchiveProgressMixin, DashboardControllerMixin):
    def __init__(self, health_state: str, health_reason: str) -> None:
        self.archive_cache_status_chip = _Label()
        self._archive_cache_health_state = health_state
        self._archive_cache_health_reason = health_reason
        self._archive_load_progress_active = False
        self._archive_load_progress_percent = 100
        self._archive_load_progress_detail = "Archive ready."


def test_filter_progress_does_not_replace_healthy_cache_state() -> None:
    owner = _Owner("healthy", "Loaded cached archive indexes.")

    owner._set_archive_load_progress("Filtering archive entries...", phase="Filtering", percent=1)

    assert owner.archive_cache_status_chip.text == "Cache: Healthy"
    assert owner.archive_cache_status_chip.tooltip == "Loaded cached archive indexes."
    assert owner.archive_cache_status_chip.property("healthState") == "healthy"


def test_actual_cache_build_still_reports_building() -> None:
    owner = _Owner("building", "Archive cache build is running.")

    owner._set_archive_load_progress("Scanning archive packages...", phase="Scanning", percent=38)

    assert owner.archive_cache_status_chip.text == "Cache: Building"
    assert owner.archive_cache_status_chip.property("healthState") == "building"


def test_stale_filter_result_does_not_replace_healthy_cache_state() -> None:
    owner = _Owner("healthy", "Loaded cached archive indexes.")

    owner._set_archive_load_progress("Stale filter result ignored.", phase="Stale", percent=0)

    assert owner.archive_cache_status_chip.text == "Cache: Healthy"
    assert owner.archive_cache_status_chip.property("healthState") == "healthy"
