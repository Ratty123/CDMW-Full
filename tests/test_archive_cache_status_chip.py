from __future__ import annotations

from types import SimpleNamespace

import cdmw.ui.shell.dashboard_controller as dashboard_controller
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


class _RootEdit:
    def __init__(self, value: str) -> None:
        self._value = value

    def text(self) -> str:
        return self._value


class _HealthOwner:
    def __init__(self, root: str, session: object | None = None) -> None:
        self.archive_package_root_edit = _RootEdit(root)
        self.archive_remote_bridge = SimpleNamespace(displays_v2=True, current_session=session)
        self._archive_cache_health_reason = ""
        self.updates: list[tuple[str, str, str]] = []

    def _set_archive_cache_health(self, state: str, reason: str, *, package_root: str = "") -> None:
        self._archive_cache_health_reason = reason
        self.updates.append((state, reason, package_root))


def test_v2_cache_health_does_not_run_legacy_shard_scan(tmp_path, monkeypatch) -> None:
    def fail_legacy_scan(*_args, **_kwargs):
        raise AssertionError("v2 cache health must not scan the legacy cache")

    monkeypatch.setattr(dashboard_controller, "archive_scan_shard_cache_health", fail_legacy_scan)
    owner = _HealthOwner(str(tmp_path))

    report = DashboardControllerMixin._check_archive_cache_health(owner, str(tmp_path))

    assert report["status"] == "unknown"
    assert owner.updates[-1][0] == "unknown"


def test_v2_cache_health_reuses_published_session_state(tmp_path, monkeypatch) -> None:
    def fail_legacy_scan(*_args, **_kwargs):
        raise AssertionError("a published v2 session must remain the cache-health authority")

    monkeypatch.setattr(dashboard_controller, "archive_scan_shard_cache_health", fail_legacy_scan)
    session = SimpleNamespace(package_root=str(tmp_path), cache_hit=True)
    owner = _HealthOwner(str(tmp_path), session)

    report = DashboardControllerMixin._check_archive_cache_health(owner, str(tmp_path))

    assert report["status"] == "healthy"
    assert "Loaded the reusable" in report["reason"]
    assert owner.updates[-1][0] == "healthy"
