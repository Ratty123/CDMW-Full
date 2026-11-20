"""Textures > Upscale through the AI tools, on the real window with the backend Disabled."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication

from tests.mcp_rail_helpers import RailClient
from tests.test_texture_workflow_guardrails import _fake_dds_bytes, _write_fake_png_header

NAMES = ("character/texture/blade.dds", "character/texture/hilt.dds")


def _window(tmp_path):
    from cdmw.app.events import AppEventBus
    from cdmw.services.service_container import ServiceContainer
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext

    QApplication.instance() or QApplication([])
    settings = create_settings(settings_file_path=tmp_path / "settings.ini")
    window = MainWindow(app_context=AppContext(settings=settings, services=ServiceContainer.create_default(
        settings=settings), event_bus=AppEventBus()))
    return window, settings


def _fixture(tmp_path):
    dds, png, out = tmp_path / "dds", tmp_path / "png", tmp_path / "out"
    for name in NAMES:
        path = dds / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_fake_dds_bytes(64, 64, mips=7))
        _write_fake_png_header((png / name).with_suffix(".png"), 128, 128)
    out.mkdir()
    return dds, png, out


def _fake_encode(jobs, **_kwargs):
    results = {}
    for job in jobs:
        target = Path(str(job["output_path"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_fake_dds_bytes(128, 128, mips=8))
        results[str(target.resolve())] = {"status": "encoded", "backend": "directxtex_native_0.2",
                                          "output_path": str(target), "encode_ms": 1.0}
    return results


def test_upscale_settings_profiles_rules_preview_and_start(tmp_path):
    window, settings = _window(tmp_path)
    client = RailClient(tmp_path, window=window, settings=settings)
    dds, png, out = _fixture(tmp_path)
    textures = window.textures
    try:
        client.ok("textures.upscale", action="show")
        assert textures.job.mode == "upscale"
        # Settings go through the page's controls, which check them.
        state = client.ok("textures.upscale", action="settings", fields={
            "original_dds_root": str(dds), "png_root": str(png), "include_filters": "*.dds", "backend": "none",
            "dds_size_mode": "Use final PNG size for rebuilt DDS", "write_csv_log": False})
        assert state["settings"]["original_dds_root"] == str(dds) and state["settings"]["backend"] == "none"
        assert state["settings"]["dds_size_mode"] == "png"
        for bad in ({"colour": 1}, {"ncnn_scale": 99}, {"dry_run": "yes"}, {"original_dds_root": str(tmp_path / "x")},
                    {"output_root": str(tmp_path / "missing")}):
            assert client.call("textures.upscale", action="settings", fields=bad)["error"]["code"] == (
                "invalid_arguments"), bad
        assert client.call("textures.upscale", action="settings",
                           fields={"backend": "warp"})["error"]["code"] == "not_found"

        # Profiles and rules: add, change, reorder, remove, all through the page's buttons.
        state = client.ok("textures.upscale", action="profile", op="add",
                          fields={"name": "Force Rebuild", "action": "rebuild_from_png"})
        profile = state["profiles"][-1]
        assert profile["name"] == "Force Rebuild" and profile["action"] == "rebuild_from_png"
        first = len(state["rules"])  # the page's default rules stay ahead of the new ones
        client.ok("textures.upscale", action="rule", op="add", fields={"pattern": "*_n.dds"})
        state = client.ok("textures.upscale", action="rule", op="add",
                          fields={"pattern": "*.dds", "profile": profile["id"]})
        assert [rule["pattern"] for rule in state["rules"][first:]] == ["*_n.dds", "*.dds"]
        assert state["rules"][-1]["profile"] == profile["id"]
        state = client.ok("textures.upscale", action="rule", op="move_up", index=first + 1)
        assert [rule["pattern"] for rule in state["rules"][first:]] == ["*.dds", "*_n.dds"]
        state = client.ok("textures.upscale", action="rule", op="move_down", index=first)
        state = client.ok("textures.upscale", action="rule", op="delete", index=first)
        assert [rule["pattern"] for rule in state["rules"][first:]] == ["*.dds"]
        assert client.call("textures.upscale", action="rule", op="delete", index=7)["error"]["code"] == "not_found"
        assert client.call("textures.upscale", action="profile", op="change",
                           profile="nope", fields={})["error"]["code"] == "not_found"

        state = client.ok("textures.upscale", action="refresh_matches")
        assert state["matches"]["total"] == 2
        assert {row["path"] for row in state["matches"]["rows"]} == set(NAMES)
        state = client.ok("textures.upscale", action="assign_profile", paths=[NAMES[0]], profile=profile["id"])
        assert state["rules"][-1] == {**state["rules"][-1], "match_mode": "exact", "pattern": NAMES[0],
                                      "profile": profile["id"]}
        assert state["asked"][0]["answer"] == "Force Rebuild"
        assert client.call("textures.upscale", action="assign_profile", paths=["nope.dds"],
                           profile=profile["id"])["error"]["code"] == "not_found"

        state = client.ok("textures.upscale", action="scan")
        assert state["progress"]["total_files"] == "2"
        preview = client.ok("textures.upscale", action="preview_policy")
        assert preview["total"] == 2 and {row["path"] for row in preview["rows"]} == set(NAMES)
        assert any("Matched DDS files: 2" in line for line in preview["summary"])
        summary = client.ok("textures.upscale", action="run_summary")
        assert summary["configuration"]["backend"] == "none" and summary["summary"]
        assert QApplication.activeModalWidget() is None

        # Start never replaces what is already in the output folder.
        textures.overwrite_existing_checkbox.setChecked(True)
        # The stand-in encoder's path must not outlive the test: CDMW waits for a helper it saw before.
        with (mock.patch("cdmw.core.texture_native._last_directxtex_binary_path", None),
              mock.patch("cdmw.core.texture_native.find_directxtex_texture_binary",
                         return_value=tmp_path / "cd-texture-dx.exe"),
              mock.patch("cdmw.core.texture_native.encode_dds_batch_with_directxtex", side_effect=_fake_encode)):
            built = client.ok("textures.upscale_start", output_root=str(out))
        assert not textures.overwrite_existing_checkbox.isChecked()
        assert built["summary"]["converted"] == 2 and built["summary"]["failed"] == 0, "\n".join(built["log"][-25:])
        assert all((out / name).is_file() for name in NAMES)
        assert all((dds / name).read_bytes() == _fake_dds_bytes(64, 64, mips=7) for name in NAMES)
        assert client.call("textures.upscale_start", output_root=str(tmp_path / "missing"))["error"]["code"] == (
            "invalid_arguments")
        # Review & Export names the tool that exports what its chosen page shows.
        reviewed = client.ok("textures.workflow", editor="tool", action="review_export", operation="upscale")
        assert reviewed["export_with"] == ["textures_upscale_state", "textures_upscale_start"]
        assert textures._review_dialog.isVisible() and textures.export_operation.currentData() == "upscale"
        textures._review_dialog.close()
        state = client.ok("textures.upscale_state")
        assert not state["busy"] and state["progress"]["converted"] == "2"
    finally:
        textures._workflow_match_refresh_timer.stop()
        window._finalize_close()
        window.deleteLater()
