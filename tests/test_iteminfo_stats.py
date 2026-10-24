from dataclasses import replace

import pytest

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_stats import read_item_stats, set_item_stats
from cdmw.domain.new_item.item_stats import (ItemStatSettings, StatOverride, PassiveSkill,
                                            encode_stat_settings, decode_stat_settings)
from tests.item_stat_fixtures import stat_item, enchant_stats


@pytest.mark.parametrize('current', (False, True))
def test_nonempty_stat_families_and_passive_edits_preserve_every_other_byte(current):
    raw = stat_item(current=current)
    entries, skills = read_item_stats(raw)
    assert [(row.kind, row.level, row.key, row.value) for row in entries] == [
        ('regeneration_max', 0, 1000002, 100), ('regeneration', 0, 1000003, -2),
        ('regeneration_max', 1, 1000002, 200), ('regeneration', 1, 1000003, 5),
        ('level_stat', 0, 1000003, 3), ('level_stat', 1, 1000003, 9)]
    assert skills == (PassiveSkill(600001, 4),)
    settings = ItemStatSettings((StatOverride('regeneration', 0, 1000003, -(1 << 63)),
                                StatOverride('regeneration_max', 1, 1000002, (1 << 63) - 1),
                                StatOverride('level_stat', 1, 1000003, 255)))
    expected = bytearray(raw)
    for edit in settings.statistics:
        row = next(row for row in entries if (row.kind, row.level, row.key) == (edit.kind, edit.level, edit.key))
        expected[row.span.start:row.span.end] = edit.value.to_bytes(row.span.size, 'little', signed=row.kind != 'level_stat')
    assert set_item_stats(raw, settings) == bytes(expected)
    edited = read_item_layout(set_item_stats(raw, replace(settings, passive_skills=(PassiveSkill(600002, 0xffffffff),))))
    before = read_item_layout(raw)
    assert all(edited.data(field) == before.data(field) for field in before.fields
               if field not in {'_enchantDataList', '_equipPassiveSkillList'})
    assert read_item_stats(edited.raw)[1] == (PassiveSkill(600002, 0xffffffff),)
    assert read_item_stats(set_item_stats(edited.raw, ItemStatSettings(passive_skills=())))[1] == ()


@pytest.mark.parametrize('settings', (
    ItemStatSettings((StatOverride('regeneration', 2, 1000003, 1),)),
    ItemStatSettings((StatOverride('level_stat', 0, 999999, None),)),
))
def test_missing_selectors_refuse(settings):
    with pytest.raises(ValueError, match='missing or ambiguous'):
        set_item_stats(stat_item(), settings)


def test_repeated_level_stat_selectors_refuse_instead_of_editing_a_guessed_row():
    raw = stat_item(levels=(enchant_stats(0), enchant_stats(0)))
    with pytest.raises(ValueError, match='missing or ambiguous'):
        set_item_stats(raw, ItemStatSettings((StatOverride('level_stat', 0, 1000003, 1),)))


@pytest.mark.parametrize('settings', (
    ItemStatSettings(), ItemStatSettings((StatOverride('stat', 0, 1, 2),)),
    ItemStatSettings((StatOverride('level_stat', 0, 1, 256),)),
    ItemStatSettings((StatOverride('level_stat', 0, 1, -1),)),
    ItemStatSettings((StatOverride('regeneration', True, 1, 0),)),
    ItemStatSettings((StatOverride('regeneration', 0, 1, 1 << 63),)),
    ItemStatSettings((StatOverride('regeneration', 0, 1, 0),) * 2),
    ItemStatSettings(passive_skills=(PassiveSkill(1, True),)),
    ItemStatSettings(passive_skills=(PassiveSkill(0, 1),)),
    ItemStatSettings(passive_skills=(PassiveSkill(1, 1 << 32),)),
    ItemStatSettings(passive_skills=(PassiveSkill(1, 1), PassiveSkill(1, 2))),
))
def test_closed_settings_refuse_invalid_ranges_types_and_duplicates(settings):
    with pytest.raises(ValueError):encode_stat_settings(settings)


def test_zero_parameters_and_empty_passive_lists_survive_the_closed_wire():
    settings = ItemStatSettings((StatOverride('level_stat', 0, 1000003, 0),), ())
    encoded = encode_stat_settings(settings)
    assert decode_stat_settings(encoded) == settings
    encoded['future_field'] = 0
    with pytest.raises(ValueError, match='fields'):decode_stat_settings(encoded)


def test_adding_and_removing_stat_entries_preserves_other_lists_and_levels():
    raw = stat_item()
    settings = ItemStatSettings((StatOverride('regeneration', 0, 1000002, 123),
        StatOverride('regeneration', 0, 1000003, None), StatOverride('level_stat', 1, 1000002, 7)))
    edited = read_item_layout(set_item_stats(raw, settings))
    values = {(row.kind, row.level, row.key):row.value for row in read_item_stats(edited.raw)[0]}
    assert ('regeneration', 0, 1000003) not in values
    assert values['regeneration', 0, 1000002] == 123
    assert values['level_stat', 1, 1000002] == 7
    before = read_item_layout(raw)
    assert all(before.data(field) == edited.data(field) for field in before.fields if field != '_enchantDataList')
    from cdmw.core.iteminfo_settings import item_quantities
    assert [(row.kind,row.level,row.key,row.value) for row in item_quantities(before)] == [
        (row.kind,row.level,row.key,row.value) for row in item_quantities(edited)]
    def buffers(layout):
        return [layout.raw[row.span.start:row.span.end] for row in layout.members
                if row.owner == 'EnchantData' and row.name.startswith('_equipBuffs')]
    assert buffers(before) == buffers(edited)
    assert encode_stat_settings(settings)['statistics'][1]['value'] is None


def test_empty_template_stat_families_can_receive_entries():
    from tests.item_layout_fixtures import full_item
    settings = ItemStatSettings((StatOverride('regeneration', 0, 1000003, 100),
                                StatOverride('level_stat', 1, 1000002, 0)))
    stats, _skills = read_item_stats(set_item_stats(full_item(), settings))
    assert {(row.kind,row.level,row.key):row.value for row in stats} == {
        ('regeneration',0,1000003):100,('level_stat',1,1000002):0}
