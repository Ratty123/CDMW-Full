"""Tabs the user has not opened are built on first open, and nothing else notices.

Headless construction over the synthetic placement files. The window keeps a list of which
tab creates which attribute (`window._LAZY_TAB_NAMES`), so a read of an unbuilt tab's widget
builds that tab instead of failing; these tests keep the list honest and check that the
startup path builds nothing it does not show.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from tools.placement_studio import corpus
from tests.test_placement_studio_operations import FILES

_LAZY = ("animations", "edit", "armour", "mod", "advanced")


@pytest.fixture
def window(monkeypatch, tmp_path):
    QApplication.instance() or QApplication([])
    from tools.placement_studio.window import PlacementStudioWindow

    monkeypatch.setattr(PlacementStudioWindow, "_start_armour_index", lambda self: None)
    monkeypatch.setattr(PlacementStudioWindow, "_start_archive_content_load",
                        lambda *a, **k: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(PlacementStudioWindow, "_mod_settings", lambda self: settings)
    base = tmp_path / "vanilla"
    records = {path: corpus._pin(base, path, data, "0009") for path, data in FILES.items()}
    studio = PlacementStudioWindow(corpus.Baseline(base, records), background_loading=False)
    yield studio
    studio.close()
    studio.deleteLater()


def test_only_the_carry_tab_is_built_at_startup(window) -> None:
    QApplication.processEvents()
    assert window._lazy_built == set()
    assert window._lower.currentIndex() == 0
    assert window._lower.tabText(4) == "Your mod"


def test_the_attribute_list_matches_what_each_builder_creates(window) -> None:
    from tools.placement_studio.window import _LAZY_TAB_NAMES

    for key in _LAZY:
        before = set(window.__dict__)
        window._ensure_tab(key)
        made = set(window.__dict__) - before
        declared = set(_LAZY_TAB_NAMES[key].split())
        assert declared <= made, (key, sorted(declared - made))
        # Everything else a builder creates must be state other code may not read early,
        # which is none: list it, or create it in the tab's `_init_*_state`.
        assert made <= declared, (key, sorted(made - declared))


def test_opening_a_tab_builds_it_in_place(window) -> None:
    labels = [window._lower.tabText(i) for i in range(window._lower.count())]
    placeholder = window._lower.widget(5)
    window._lower.setCurrentIndex(5)
    assert "advanced" in window._lazy_built
    assert window._lower.currentIndex() == 5
    assert window._lower.widget(5) is not placeholder
    assert window._lower.indexOf(window._advanced_tabs.parentWidget()) == 5
    assert [window._lower.tabText(i) for i in range(window._lower.count())] == labels
    assert window._lower.tabToolTip(5).startswith("Attach points")


def test_reading_an_unbuilt_widget_builds_its_tab(window) -> None:
    assert "mod" not in window._lazy_built
    page = window._mod_page
    assert "mod" in window._lazy_built
    assert window._lower.indexOf(page) == 4
    # The open tab stays open.
    assert window._lower.currentIndex() == 0
    with pytest.raises(AttributeError):
        window._no_such_attribute


def test_the_mod_count_reaches_a_closed_tab(window, monkeypatch) -> None:
    from tools.placement_studio.save_mod import ModChange

    change = ModChange(key="op", title="Moved the sword", detail=(), saveable=True)
    monkeypatch.setattr(type(window), "_mod_changes", lambda self: [change, change])
    window._refresh_mod_list()
    assert "mod" not in window._lazy_built
    assert window._lower.tabText(4) == "Your mod (2)"
    assert window._mod_summary_button.text() == "Your mod: 2 changes"
    window._lower.setCurrentIndex(4)
    assert window._lower.tabText(4) == "Your mod (2)"
    assert window._mod_list.topLevelItemCount() == 2
