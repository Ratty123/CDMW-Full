"""Templates the game ships without any display name (TestSword and other leftovers)."""
from dataclasses import replace

import pytest

from cdmw.services.new_item_planning import NewItemPlanError
from cdmw.services.new_item_snapshot import NewItemSnapshot
from tests.test_archive_overlay_manager import shop_spec
from tests.test_independent_items import imported_game


def _without(monkeypatch, key, languages):
    original = NewItemSnapshot.paloc_table

    def paloc_table(self, language):
        table = original(self, language)
        if language in languages:
            table = replace(table, entries=tuple(entry for entry in table.entries if entry.key != key))
        return table

    monkeypatch.setattr(NewItemSnapshot, 'paloc_table', paloc_table)


def _name_key(service, snapshot, spec):
    allocated = service.allocate(spec, snapshot)
    return snapshot.rows[allocated.template_key].name_key


def test_a_template_without_a_name_in_any_language_says_so(tmp_path, monkeypatch):
    service, snapshot = imported_game(tmp_path)
    spec = shop_spec('Nameless')
    key = _name_key(service, snapshot, spec)
    _without(monkeypatch, key, set(snapshot.languages))
    with pytest.raises(NewItemPlanError, match="has no display name in the game's text tables") as raised:
        service.plan(spec, snapshot)
    assert 'ara table' not in str(raised.value)


def test_one_missing_language_still_names_that_language(tmp_path, monkeypatch):
    service, snapshot = imported_game(tmp_path)
    languages = tuple(snapshot.languages)
    if len(languages) < 2:
        pytest.skip('the fixture game has one language')
    spec = shop_spec('HalfNamed')
    key = _name_key(service, snapshot, spec)
    _without(monkeypatch, key, {languages[0]})
    with pytest.raises(NewItemPlanError, match=f'the {languages[0]} table has no entry'):
        service.plan(spec, snapshot)
