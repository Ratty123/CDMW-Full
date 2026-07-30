"""Report what the running GUI actually draws in English, and why.

The catalogue tests prove that every key in `source_manifest.json` has a translation
in every language. They cannot prove the reverse, which is the failure users report:
text that is on screen but was never a key, or is a key the runtime never looks up.
This walks the real window instead, builds every lazy tool, and sorts each visible
string into the reason it is still English:

  unkeyed    -- no catalogue key under any spelling and no template rule matches, so
                no language can ever change it. The extractor never saw the string,
                usually because it is composed at runtime or lives in a module
                constant rather than a call the sink list recognises.
  untranslated -- a key exists and differs from English, but the drawn text did not
                reach it. A live lookup bug.

Run it from the repository root:

    .\\.venv\\Scripts\\python.exe scripts\\audit_gui_localization_coverage.py --language de

`--order after` opens the tools after the language switch, the way a user does;
`--order before` opens them first, so one apply pass covers everything. A string that
only fails under `after` is a lazily-built tree the localizer did not revisit.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Without this the shell prompts for an archive path and waits for a click.
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QTableWidget,
    QTabBar,
    QTabWidget,
    QTreeWidget,
    QWidget,
)

from cdmw.app.events import AppEventBus  # noqa: E402
from cdmw.services.service_container import ServiceContainer  # noqa: E402
from cdmw.services.settings_service import create_settings  # noqa: E402
from cdmw.ui import localization as localization_module  # noqa: E402
from cdmw.ui.localization import UiLocalizer  # noqa: E402
from cdmw.ui.main_window import MainWindow  # noqa: E402
from cdmw.ui.shell.app_context import AppContext  # noqa: E402
from cdmw.ui.shell.lazy_tool_tab import LazyToolTab  # noqa: E402

LANGUAGE_DIR = ROOT / "cdmw" / "resources" / "localization"


def _flat(entry: object) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("other") or next(iter(entry.values()), ""))
    return ""


def _owner_path(widget: object, depth: int = 6) -> str:
    names: list[str] = []
    node = widget
    while node is not None and len(names) < depth:
        names.append(type(node).__name__)
        node = node.parentWidget() if isinstance(node, QWidget) else None
    return " < ".join(names)


def _owning_tool(sites: list[tuple[str, str]]) -> str:
    generic = {"QWidget", "QStackedWidget", "QTabWidget", "QSplitter", "QFrame"}
    for _kind, path in sites:
        for name in path.split(" < "):
            if name in generic:
                continue
            if name.endswith(("Tab", "Window", "Panel")) or name.endswith("ToolWidget"):
                return name
    return "shell"


def _build_window(app: QApplication) -> tuple[MainWindow, tempfile.TemporaryDirectory]:
    temp_dir = tempfile.TemporaryDirectory()
    settings = create_settings(settings_file_path=Path(temp_dir.name) / "gui-i18n-audit.cfg")
    context = AppContext(
        settings=settings,
        services=ServiceContainer.create_default(settings=settings),
        event_bus=AppEventBus(),
    )
    window = MainWindow(app_context=context)
    app.processEvents()
    return window, temp_dir


def _build_lazy_tools(app: QApplication, window: MainWindow) -> list[str]:
    failures: list[str] = []
    for lazy in window.findChildren(LazyToolTab):
        try:
            lazy.ensure_widget()
        except Exception as exc:  # noqa: BLE001 - one broken tool must not end the audit
            failures.append(f"{type(exc).__name__}: {exc}")
        app.processEvents()
    for _ in range(10):
        app.processEvents()
    return failures


def _iter_visible_text(window: MainWindow):
    """Yield (text, widget, kind) for everything the window draws as words."""

    for widget in [window, *window.findChildren(QWidget)]:
        try:
            if isinstance(widget, QLabel):
                yield widget.text(), widget, "QLabel.text"
            if isinstance(widget, QAbstractButton):
                yield widget.text(), widget, "button.text"
            if isinstance(widget, QGroupBox):
                yield widget.title(), widget, "groupbox.title"
            if isinstance(widget, QLineEdit):
                yield widget.placeholderText(), widget, "lineedit.placeholder"
            if isinstance(widget, QComboBox):
                for index in range(widget.count()):
                    yield widget.itemText(index), widget, "combo.item"
            if isinstance(widget, QTabWidget):
                for index in range(widget.count()):
                    yield widget.tabText(index), widget, "tabwidget.tabText"
                    yield widget.tabToolTip(index), widget, "tabwidget.tabToolTip"
            if isinstance(widget, QTabBar):
                for index in range(widget.count()):
                    yield widget.tabText(index), widget, "tabbar.tabText"
            if isinstance(widget, QTreeWidget):
                header = widget.headerItem()
                if header is not None:
                    for column in range(widget.columnCount()):
                        yield header.text(column), widget, "tree.header"
            if isinstance(widget, QTableWidget):
                for column in range(widget.columnCount()):
                    item = widget.horizontalHeaderItem(column)
                    if item is not None:
                        yield item.text(), widget, "table.header"
            yield widget.toolTip(), widget, "widget.toolTip"
            yield widget.windowTitle(), widget, "widget.windowTitle"
        except RuntimeError:
            continue

    for menu in window.findChildren(QMenu):
        try:
            yield menu.title(), menu, "menu.title"
            for action in menu.actions():
                yield action.text(), menu, "menu.action"
                yield action.toolTip(), menu, "menu.actionToolTip"
        except RuntimeError:
            continue

    menu_bar = window.menuBar()
    if menu_bar is not None:
        for action in menu_bar.actions():
            yield action.text(), menu_bar, "menubar.action"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="de", help="Built-in language code to audit.")
    parser.add_argument(
        "--order",
        default="after",
        choices=("after", "before", "coverage"),
        help=(
            "after: open tools after switching language (what a user does). "
            "before: open them first. coverage: stay in English and only report "
            "strings no language can ever change."
        ),
    )
    parser.add_argument("--limit", type=int, default=40, help="Entries printed per section.")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    window, temp_dir = _build_window(app)

    probe = UiLocalizer(language_dir=LANGUAGE_DIR, language_code=args.language)
    catalog = probe.translations
    differing = {key: _flat(value) for key, value in catalog.items() if _flat(value) not in ("", key)}

    if args.order == "coverage":
        failures = _build_lazy_tools(app, window)
    elif args.order == "before":
        failures = _build_lazy_tools(app, window)
        window._handle_language_changed(args.language)
        for _ in range(6):
            app.processEvents()
        window.ui_localizer.apply(window)
    else:
        window._handle_language_changed(args.language)
        for _ in range(6):
            app.processEvents()
        failures = _build_lazy_tools(app, window)
    app.processEvents()

    untranslated: dict[str, list[tuple[str, str]]] = defaultdict(list)
    unkeyed: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for text, widget, kind in _iter_visible_text(window):
        value = str(text or "").strip()
        if not value:
            continue
        site = (kind, _owner_path(widget))
        # A tab bar or menu draws `&&` as one literal `&`, and the catalogue key was
        # recorded from the undoubled title, so both spellings have to be tried.
        spellings = {value, value.replace("&&", "&"), value.replace("&", "")}
        matched = False
        for spelling in spellings:
            spelling = spelling.strip()
            if spelling in differing:
                untranslated[spelling].append(site)
                matched = True
                break
            if spelling in catalog:
                matched = True
                break
        if matched or args.order != "coverage":
            # Outside `coverage` the window is already translated, so an unmatched
            # string is usually just the German the localizer wrote -- reporting it
            # as unkeyed would be noise. Only the English pass can prove that.
            continue
        # Ask the localizer itself, so template rules and the builtin fallback count
        # as coverage. What survives really is text no language can ever change.
        for segment in localization_module._extract_html_text_segments(value):
            if not segment or segment in catalog:
                continue
            if probe.translate_rendered(segment) != segment:
                continue
            unkeyed[segment].append(site)

    if failures:
        print(f"[{len(failures)} tool(s) failed to construct] {failures}", file=sys.stderr)

    def report(title: str, found: dict[str, list[tuple[str, str]]], expected: bool) -> None:
        print(f"\n==== {title}: {len(found)} ====")
        by_tool: dict[str, int] = defaultdict(int)
        by_kind: dict[str, int] = defaultdict(int)
        for sites in found.values():
            by_tool[_owning_tool(sites)] += 1
            for kind, _path in sites:
                by_kind[kind] += 1
        print("  by tool:", dict(sorted(by_tool.items(), key=lambda item: -item[1])))
        print("  by kind:", dict(sorted(by_kind.items(), key=lambda item: -item[1])))
        for text, sites in sorted(found.items(), key=lambda item: -len(item[1]))[: args.limit]:
            kinds = sorted({kind for kind, _path in sites})
            print(f"\n  {text[:150]!r}")
            if expected:
                print(f"     expected: {differing[text][:150]!r}")
            print(f"     {len(sites)} site(s), kinds={kinds}")
            print(f"       {sites[0][1]}")

    if args.order == "coverage":
        report(
            "UNKEYED -- no catalogue key in any language, permanently English",
            unkeyed,
            expected=False,
        )
    else:
        report(
            f"UNTRANSLATED -- a {args.language} translation exists but was not applied",
            untranslated,
            expected=True,
        )

    window.deleteLater()
    app.processEvents()
    temp_dir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
