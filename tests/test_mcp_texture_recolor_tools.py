"""Textures > Recolor through the AI tools, on the real page without a workspace."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.recolor_variants_tab import RecolorVariantsTab
from tests.mcp_rail_helpers import RailClient, wait_for
from tests.test_recolor_variants import _write_mod


def _tab(tmp_path):
    QApplication.instance() or QApplication([])
    return RecolorVariantsTab(settings=QSettings(str(tmp_path / "recolor.ini"), QSettings.Format.IniFormat),
                              base_dir=tmp_path)


def _finish(tab):
    tab.request_shutdown()
    wait_for(lambda: not tab.iter_shutdown_workers())
    tab.deleteLater()


def test_recolor_analyzes_edits_the_template_and_builds_variants(tmp_path):
    tab = _tab(tmp_path)
    client = RailClient(tmp_path, widgets={"recolor_variants": tab})
    source = _write_mod(tmp_path)
    try:
        # Building before an analysis is refused with the page's own message.
        out = tmp_path / "out"
        out.mkdir()
        refused = client.call("textures.recolor_build", folder=str(out))
        assert refused["error"]["code"] == "unavailable" and "Analyze" in refused["error"]["message"]
        assert client.call("textures.recolor", action="analyze",
                           source=str(tmp_path / "missing"))["error"]["code"] == "invalid_arguments"
        client.ok("textures.recolor", action="analyze", source=str(source))
        wait_for(lambda: tab.analysis is not None and tab.worker_thread is None)
        state = client.ok("textures.recolor_state")
        targets = {row["game_path"]: row for row in state["targets"]}
        assert targets["character/texture/blade_basecolor.dds"]["editable"]
        assert not targets["character/texture/blade_n.dds"]["editable"]
        # Template fields go through the page's controls, which check them.
        edited = client.ok("textures.recolor", action="edit_template",
                           fields={"name": "Rust", "target_color": "#8A3B12", "strength": 80})
        assert edited["template"]["name"] == "Rust" and edited["template"]["strength"] == 80
        assert client.call("textures.recolor", action="edit_template",
                           fields={"target_color": "red"})["error"]["code"] == "invalid_arguments"
        assert client.call("textures.recolor", action="edit_template",
                           fields={"strength": 500})["error"]["code"] == "invalid_arguments"
        assert client.call("textures.recolor", action="edit_template",
                           fields={"colour": "#000000"})["error"]["code"] == "invalid_arguments"
        reviewed = client.ok("textures.recolor", action="review")
        assert any("Template preview" in line for line in reviewed["log"])
        assert client.call("textures.recolor", action="targets",
                           active="nope")["error"]["code"] == "not_found"
        # Build: the source is never changed, and earlier folders are never cleared.
        tab.overwrite_checkbox.setChecked(True)

        def recolor(dds_path, *_args, **_kwargs):
            dds_path.write_bytes(b"RECOLORED")

        with mock.patch("cdmw.core.recolor_variants._apply_texture_rule_to_dds", side_effect=recolor):
            built = client.ok("textures.recolor_build", folder=str(out), outputs=["dmm"])
        assert not tab.overwrite_checkbox.isChecked()
        assert built["built"] and all(path.startswith(str(out)) for path in built["built"])
        assert (source / "files" / "character" / "texture" / "blade_basecolor.dds").read_bytes() != b"RECOLORED"
        assert client.call("textures.recolor_build", folder=str(out),
                           outputs=["nope"])["error"]["code"] == "invalid_arguments"
    finally:
        _finish(tab)
