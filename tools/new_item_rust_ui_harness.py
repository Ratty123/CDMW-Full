"""Synthetic New Item documents and real Rust headless layout/capture evidence.

Uses the existing owned test archive. It neither discovers nor reads a game install.
Run from source with the project virtualenv; output belongs in a temporary directory.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--renderer", type=Path)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--width", default=1440, type=int)
    parser.add_argument("--height", default=960, type=int)
    parser.add_argument("--nested", action="store_true")
    parser.add_argument("--expanded", action="store_true")
    parser.add_argument("--step", type=int, choices=range(7))
    parser.add_argument("--theme", choices=("graphite", "light", "high_contrast"), default="graphite")
    parser.add_argument("--font-pixels", type=int, default=14)
    parser.add_argument("--language", default="en")
    parser.add_argument("--authored", action="store_true")
    parser.add_argument("--icon-crop-image", type=Path, help="Render the original icon crop dialog using an owned capture")
    args = parser.parse_args()
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QGroupBox, QTabWidget, QToolButton, QWidget
    from shiboken6 import isValid
    from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
    import test_new_item_studio_tab as support

    args.output_root.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,str(args.output_root / "owned-settings"))
    support.TabTests.setUpClass()
    from cdmw.ui.themes import build_app_palette, build_app_stylesheet
    from cdmw.ui.localization import UiLocalizer
    app = QApplication.instance()
    app.setPalette(build_app_palette(args.theme))
    app.setStyleSheet(build_app_stylesheet(args.theme, base_font_size=args.font_pixels))
    font = app.font()
    font.setPixelSize(args.font_pixels)
    app.setFont(font)
    localizer = UiLocalizer(language_dir=args.output_root / "owned-languages", language_code=args.language)
    app.setProperty("_cdmw_ui_localizer", localizer)
    fixture = support.TabTests("runTest")
    fixture.setUp()
    evidence = []
    owned_dialogs = []

    def settle():
        until = time.monotonic() + 0.1
        while time.monotonic() < until:
            QApplication.processEvents()

    def emit(name):
        settle()
        localizer.apply(tab)
        for dialog in owned_dialogs:
            localizer.apply(dialog)
        state = bridge.snapshot()
        state["theme"]["font_pixels"] = args.font_pixels
        if state["unsupported"]:
            raise RuntimeError(f"{name}: unsupported controls: {state['unsupported']}")
        document = args.output_root / f"{name}.json"
        document.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        row = {"name": name, "document": str(document), "controls": len(bridge.document.registry.current)}
        if args.renderer:
            report = args.output_root / f"{name}.layout.json"
            command = [str(args.renderer), "--new-item-ui-document", str(document),
                       "--new-item-ui-report", str(report), "--width", str(args.width), "--height", str(args.height)]
            if args.capture:
                command += ["--capture-new-item-ui", str(args.output_root / f"{name}.png")]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                raise RuntimeError(f"{name}: renderer failed: {result.stderr[-6000:]}")
            layout = json.loads(report.read_text(encoding="utf-8"))
            if layout["errors"] or layout["unsupported"]:
                raise RuntimeError(f"{name}: renderer coverage: {layout['errors']} {layout['unsupported']}")
            row["rendered_controls"] = len(layout["controls"])
            row["report"] = str(report)
        evidence.append(row)
        print(json.dumps(row), flush=True)

    def expand(root):
        changed = []
        # Only disclosure controls and checkable sections; operation buttons
        # (load/import/build/install/etc.) are never activated by a layout sweep.
        for _ in range(4):
            found = False
            for widget in root.findChildren(QWidget):
                if (isinstance(widget, (QToolButton, QGroupBox)) and isValid(widget) and widget.isVisibleTo(tab) and widget.isEnabled()
                        and widget.isCheckable() and not widget.isChecked()):
                    widget.setChecked(True)
                    changed.append(widget)
                    found = True
            if not found:
                break
            settle()
        return changed

    def nested(root, name):
        outer = []
        for tabs in root.findChildren(QTabWidget):
            ancestor = tabs.parentWidget()
            while ancestor is not None and ancestor is not root and not isinstance(ancestor,QTabWidget):
                ancestor = ancestor.parentWidget()
            if ancestor is root and tabs.isVisibleTo(tab):
                outer.append(tabs)
        for number,tabs in enumerate(outer):
            selected = tabs.currentIndex()
            for index in range(tabs.count()):
                if not tabs.isTabVisible(index) or not tabs.isTabEnabled(index):
                    continue
                tabs.setCurrentIndex(index)
                settle()
                label = f"{name}-tabs-{number}-{index}"
                emit(label)
                expanded = expand(tabs.currentWidget()) if args.expanded else []
                if expanded:
                    emit(label+"-expanded")
                nested(tabs.currentWidget(),label)
                for widget in reversed(expanded):
                    if isValid(widget):
                        widget.setChecked(False)
            tabs.setCurrentIndex(selected)

    try:
        tab = fixture._tab()
        tab.prefill_template(support.TEMPLATE)
        if args.authored:
            tab.identity_panel.display_name.setText("Owned fixture blade")
            tab.identity_panel.description.setPlainText("A synthetic item used to verify the complete authoring interface.")
        tab.resize(args.width, args.height)
        tab.show()
        tab._effect_dirty_prompt = lambda: "discard"
        bridge = NewItemPresentationBridge(tab, dialogs=lambda: owned_dialogs)
        for step in range(7) if args.step is None else (args.step,):
            tab.show_step(step)
            if args.authored and step == 6:
                tab.controller.start_plan()
            emit(f"step-{step + 1}")
            expanded = expand(tab.pages.currentWidget()) if args.expanded else []
            if expanded:
                emit(f"step-{step+1}-expanded")
            if args.nested:
                nested(tab.pages.currentWidget(),f"step-{step+1}")
                if step == 1:
                    tab.identity_panel.identifiers_toggle.setChecked(True)
                    emit("step-2-identifiers")
                if step == 4:
                    tab._perks_panel.effects_workspace.library_toggle.setChecked(True)
                    emit("step-5-effect-library")
            for widget in reversed(expanded):
                if isValid(widget):
                    widget.setChecked(False)
        if args.icon_crop_image:
            from PySide6.QtCore import QRect
            from PySide6.QtGui import QImage
            from cdmw.ui.archive_browser.static_replacement_icon_selection import AlignmentIconSelectionDialog
            image = QImage(str(args.icon_crop_image))
            if image.isNull():
                raise ValueError("The owned icon-crop image could not be read.")
            dialog = AlignmentIconSelectionDialog(image, tab)
            dialog.selector._set_selection(QRect(image.width() // 4, image.height() // 4,
                                                  image.width() // 2, image.height() // 2))
            owned_dialogs.append(dialog)
            dialog.show()
            emit("icon-crop")
            dialog.reject()
            owned_dialogs.clear()
        (args.output_root / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
