from __future__ import annotations

import dataclasses
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QMessageBox

from cdmw.models import RunCancelled, default_config
from cdmw.ui.shell.profile_controller import (
    ProfileImportDocument,
    ProfileControllerMixin,
    _profile_config_from_payload,
    load_profile_import_document,
)


class _Settings:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = dict(values)

    def clear(self) -> None:
        self.values.clear()

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def sync(self) -> None:
        return


class _FailOnceSettings(_Settings):
    def __init__(self, values: dict[str, object], *, fail_key: str) -> None:
        super().__init__(values)
        self.fail_key = fail_key
        self.failed = False

    def setValue(self, key: str, value: object) -> None:
        if key == self.fail_key and not self.failed:
            self.failed = True
            raise RuntimeError("injected settings write failure")
        super().setValue(key, value)


class _Owner:
    _apply_decoded_profile_settings = ProfileControllerMixin._apply_decoded_profile_settings
    _apply_profile_import_transaction = ProfileControllerMixin._apply_profile_import_transaction

    def __init__(self, *, fail_import: bool = False) -> None:
        self.settings = _Settings({"keep": "old", "removed": "old"})
        self.current_theme_key = "graphite"
        self.previous_config = default_config()
        self.fail_import = fail_import
        self.applied_configs: list[object] = []
        self.ui_themes: list[str] = []

    def collect_config(self):
        return self.previous_config

    def _collect_profile_settings_snapshot(self) -> dict[str, object]:
        return dict(self.settings.values)

    def _apply_profile_config(self, config: object, *, theme_key: str) -> None:
        self.applied_configs.append(config)
        if self.fail_import and config is not self.previous_config:
            raise RuntimeError("injected UI conversion failure")

    def _apply_profile_settings_snapshot_to_ui(self, *, theme_key: str) -> None:
        self.ui_themes.append(theme_key)


def test_profile_config_is_fully_coerced_before_settings_mutate() -> None:
    config = _profile_config_from_payload({"dds_custom_width": "4096", "dry_run": "true"})
    assert config.dds_custom_width == 4096
    assert config.dry_run is True

    with pytest.raises(ValueError, match="dds_custom_width"):
        _profile_config_from_payload({"dds_custom_width": "not-an-integer"})


def test_profile_import_replaces_absent_settings_keys() -> None:
    owner = _Owner()
    imported = dataclasses.replace(default_config(), dds_custom_width=4096)

    restored = owner._apply_profile_import_transaction(
        imported,
        theme_key="midnight",
        decoded_settings={"keep": "new"},
    )

    assert restored == 1
    assert owner.settings.values == {"keep": "new"}
    assert owner.applied_configs == [imported]
    assert owner.ui_themes == ["midnight"]


def test_profile_import_rolls_back_settings_and_config_on_ui_failure() -> None:
    owner = _Owner(fail_import=True)
    imported = dataclasses.replace(default_config(), dds_custom_width=4096)

    with pytest.raises(RuntimeError, match="injected UI conversion failure"):
        owner._apply_profile_import_transaction(
            imported,
            theme_key="midnight",
            decoded_settings={"keep": "new"},
        )

    assert owner.settings.values == {"keep": "old", "removed": "old"}
    assert owner.applied_configs == [imported, owner.previous_config]
    assert owner.ui_themes == ["graphite"]


def test_profile_import_rolls_back_after_partial_settings_write() -> None:
    owner = _Owner()
    owner.settings = _FailOnceSettings({"keep": "old", "removed": "old"}, fail_key="explode")
    imported = dataclasses.replace(default_config(), dds_custom_width=4096)

    with pytest.raises(RuntimeError, match="injected settings write failure"):
        owner._apply_profile_import_transaction(
            imported,
            theme_key="midnight",
            decoded_settings={"keep": "new", "explode": True},
        )

    assert owner.settings.values == {"keep": "old", "removed": "old"}
    assert owner.applied_configs == [owner.previous_config]
    assert owner.ui_themes == ["graphite"]


def test_profile_document_load_is_cancellable_and_coerces_before_apply(tmp_path: Path) -> None:
    source = tmp_path / "profile.json"
    source.write_text(
        json.dumps(
            {
                "theme": "midnight_ember",
                "config": {"dds_custom_width": "4096"},
                "settings": {"appearance/theme": "midnight_ember", "keep": "new"},
            }
        ),
        encoding="utf-8",
    )

    document = load_profile_import_document(source, current_theme_key="graphite")

    assert document.config.dds_custom_width == 4096
    assert document.theme_key == "midnight_ember"
    assert dict(document.decoded_settings or ()) == {
        "appearance/theme": "midnight_ember",
        "keep": "new",
    }

    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(RunCancelled):
        load_profile_import_document(
            source,
            current_theme_key="graphite",
            stop_event=cancelled,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"settings": {}},
        {"config": {}},
        {"config": {}, "settings": {}},
        {"app": "Crimson Desert Mod Workbench", "profile_format": 4, "theme": "midnight_ember"},
    ],
    ids=["empty", "empty-settings", "empty-config", "empty-both", "envelope-only"],
)
def test_profile_document_load_rejects_documents_with_nothing_to_restore(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    """A degenerate document must not pass as a profile.

    Importing one used to succeed and report "Profile imported", while actually
    resetting every workflow path to defaults -- and, for an empty ``settings``
    snapshot, clearing the whole app settings store on the replace pass.
    """

    source = tmp_path / "profile.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="no profile data to import"):
        load_profile_import_document(source, current_theme_key="graphite")


def test_profile_document_load_accepts_legacy_bare_config_mapping(tmp_path: Path) -> None:
    source = tmp_path / "legacy.ctfprofile.json"
    source.write_text(json.dumps({"output_root": "D:/output"}), encoding="utf-8")

    document = load_profile_import_document(source, current_theme_key="graphite")

    assert document.config.output_root == "D:/output"
    assert document.decoded_settings is None


def test_profile_document_load_accepts_settings_only_profile(tmp_path: Path) -> None:
    source = tmp_path / "settings-only.cdmwprofile.json"
    source.write_text(
        json.dumps({"config": {}, "settings": {"appearance/theme": "midnight_ember"}}),
        encoding="utf-8",
    )

    document = load_profile_import_document(source, current_theme_key="graphite")

    assert document.decoded_settings == (("appearance/theme", "midnight_ember"),)
    assert document.theme_key == "midnight_ember"


def test_profile_document_load_keeps_stored_settings_when_snapshot_is_empty(tmp_path: Path) -> None:
    source = tmp_path / "config-only.cdmwprofile.json"
    source.write_text(
        json.dumps({"config": {"output_root": "D:/output"}, "settings": {}}),
        encoding="utf-8",
    )

    document = load_profile_import_document(source, current_theme_key="graphite")

    assert document.config.output_root == "D:/output"
    assert document.decoded_settings is None


def test_profile_import_handler_only_selects_confirms_and_dispatches(tmp_path: Path) -> None:
    source = tmp_path / "profile.json"
    source.write_text("{}", encoding="utf-8")

    class Owner:
        import_profile = ProfileControllerMixin.import_profile

        def __init__(self) -> None:
            self.settings_file_path = tmp_path / "settings.ini"
            self.current_theme_key = "graphite"
            self._profile_import_request_id = 0
            self.dispatched: dict[str, object] | None = None
            self.status: list[tuple[str, bool]] = []
            self.logs: list[str] = []

        def _run_utility_task(self, **kwargs: object) -> None:
            self.dispatched = kwargs

        def _handle_profile_import_document(self, _request_id: int, _result: object) -> None:
            return

        def set_status_message(self, message: str, *, error: bool = False) -> None:
            self.status.append((message, error))

        def append_log(self, message: str) -> None:
            self.logs.append(message)

    owner = Owner()
    with (
        patch(
            "cdmw.ui.shell.profile_controller.QFileDialog.getOpenFileName",
            return_value=(str(source), "JSON"),
        ),
        patch(
            "cdmw.ui.shell.profile_controller.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ),
    ):
        started = time.perf_counter()
        owner.import_profile()
        elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert owner.dispatched is not None
    assert owner.dispatched["task_accepts_cancel"] is True
    assert callable(owner.dispatched["task"])
    assert source.read_text(encoding="utf-8") == "{}"


def test_stale_profile_import_result_is_ignored() -> None:
    class Owner:
        _handle_profile_import_document = ProfileControllerMixin._handle_profile_import_document

        def __init__(self) -> None:
            self._profile_import_request_id = 2
            self.applied = 0
            self.status: list[str] = []
            self.logs: list[str] = []

        def _apply_profile_import_transaction(self, *_args: object, **_kwargs: object) -> int:
            self.applied += 1
            return 0

        def set_status_message(self, message: str, *, error: bool = False) -> None:
            self.status.append(message)

        def append_log(self, message: str) -> None:
            self.logs.append(message)

    owner = Owner()
    document = ProfileImportDocument(Path("profile.json"), default_config(), None, "graphite")
    owner._handle_profile_import_document(1, document)
    assert owner.applied == 0

    owner._handle_profile_import_document(2, document)
    assert owner.applied == 1
