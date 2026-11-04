"""Item components through the real Rust UI dispatch path, in a child process.

A row selection used to rebuild the tree while the dispatcher still held the
selected QModelIndex (setCurrentIndex, then scrollTo): an access violation that
killed the app. A native crash would also kill pytest, so the scenario runs in a
subprocess and the parent asserts its exit status and recorded results.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHILD = textwrap.dedent(r'''
    import json, os, sys, faulthandler
    from pathlib import Path
    root = Path(sys.argv[1])
    sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "tests"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    faulthandler.enable()
    from unittest.mock import patch
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    import test_new_item_studio_tab as support
    from test_new_item_rust_ui import _input
    from cdmw.services.new_item_rust_protocol import PresentationProtocolError
    from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge

    support.TabTests.setUpClass()
    fixture = support.TabTests("runTest"); fixture.setUp()
    tab = fixture._tab(); tab.prefill_template(support.TEMPLATE)
    tab.resize(1440, 960); tab.show(); QApplication.processEvents()
    bridge = NewItemPresentationBridge(tab)
    tab.show_step(2); QApplication.processEvents()
    panel, controller = tab.model_panel, tab.controller
    tree = panel.components.tree
    out = {}

    def component_rows():
        return [i for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0, Qt.UserRole) is not None]

    def send(action, value, revision=None):
        message = _input(bridge, tree, action, value, revision=revision)
        bridge.dispatch(message)
        QApplication.processEvents()

    reloads = []
    real_show, real_place = panel.preview.show, panel.preview.show_placement
    with patch.object(panel.preview, "show", lambda *a, **k: (reloads.append("show"), real_show(*a, **k))), \
            patch.object(panel.preview, "show_placement", lambda *a, **k: (reloads.append("placement"), real_place(*a, **k))):
        rows = component_rows()
        # Repeated clicks, including back and forth, as the user did.
        for row in rows[1:] + rows[:1] + rows[1:] + rows:
            send("select", {"path": [row], "column": 0, "mode": "click"})
        last = rows[-1]
        out["active_is_last_clicked"] = controller.current_variant_identity() == tree.topLevelItem(last).data(0, Qt.UserRole)
        out["reloads_after_selection"] = len(reloads)
        out["stale_after_selection"] = panel._preview_stale
        # Untick a row that is NOT selected: only that binding changes.
        target_row = rows[0]
        target = tree.topLevelItem(target_row).data(0, Qt.UserRole)
        active_before = controller.current_variant_identity()
        send("check_cell", {"path": [target_row], "column": 0, "check": 0})
        out["target_excluded"] = target in controller.draft.excluded_bindings
        out["active_unchanged_by_check"] = controller.current_variant_identity() == active_before
        out["spec_marks_target_custom"] = any(v.identity == target and v.custom_model for v in controller.current_spec().variants or ())
        # Rapid toggles on other rows without processing events in between.
        for row in rows[1:]:
            bridge.dispatch(_input(bridge, tree, "check_cell", {"path": [row], "column": 0, "check": 0}))
        QApplication.processEvents()
        out["excluded_count"] = len(controller.draft.excluded_bindings)
        out["reloads_after_checks"] = len(reloads)
        # A stale event (old revision) is refused, never applied to whatever row is there now.
        bridge.snapshot()
        identifier = bridge.document.registry.identify(tree)
        old_revision = bridge.document.registry.current[identifier]["revision"]
        send("check_cell", {"path": [target_row], "column": 0, "check": 2})
        try:
            send("check_cell", {"path": [rows[1]], "column": 0, "check": 2}, revision=old_revision)
            out["stale_rejected"] = False
        except PresentationProtocolError:
            out["stale_rejected"] = True
        out["target_included_again"] = target not in controller.draft.excluded_bindings
        # The explicit refresh rebuilds the viewport once and clears the flag.
        panel.refresh_preview_button.click(); QApplication.processEvents()
        out["reloads_after_refresh"] = len(reloads)
        out["stale_after_refresh"] = panel._preview_stale
    # Template reselection replaces every row; clicks afterwards still land safely.
    controller.set_template(None); QApplication.processEvents()
    controller.set_template(support.TEMPLATE); QApplication.processEvents()
    QApplication.processEvents()
    rows = component_rows()
    out["rows_after_reselect"] = len(rows)
    for row in rows:
        send("select", {"path": [row], "column": 0, "mode": "click"})
        send("check_cell", {"path": [row], "column": 0, "check": 0})
    out["excluded_after_reselect"] = len(controller.draft.excluded_bindings)
    print("RESULT " + json.dumps(out), flush=True)
    fixture.tearDown()
''')


def test_component_rows_survive_rust_dispatch_selection_checks_and_stale_events(tmp_path):
    script = tmp_path / "component_dispatch_child.py"
    script.write_text(CHILD, encoding="utf-8")
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    completed = subprocess.run([sys.executable, str(script), str(ROOT)], cwd=ROOT, env=environment,
                               capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, (completed.returncode, completed.stdout[-3000:], completed.stderr[-3000:])
    line = next(line for line in completed.stdout.splitlines() if line.startswith("RESULT "))
    result = json.loads(line[len("RESULT "):])
    assert result["active_is_last_clicked"]
    assert result["reloads_after_selection"] == 0, "selecting rows must not rebuild the viewport"
    assert result["stale_after_selection"]
    assert result["target_excluded"] and result["active_unchanged_by_check"] and result["spec_marks_target_custom"]
    assert result["excluded_count"] == 3
    assert result["reloads_after_checks"] == 0, "ticking rows must not rebuild the viewport"
    assert result["stale_rejected"]
    assert result["target_included_again"]
    assert result["reloads_after_refresh"] == 1 and not result["stale_after_refresh"]
    assert result["rows_after_reselect"] == 3
    assert result["excluded_after_reselect"] == 3
