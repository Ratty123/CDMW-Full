"""Closed item.stats@1 overrides; existing recipe/property schemas stay frozen."""
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class StatOverride:
    kind: str
    level: int
    key: int
    value: int | None


@dataclass(frozen=True, slots=True)
class PassiveSkill:
    skill_key: int
    level: int


@dataclass(frozen=True, slots=True)
class ItemStatSettings:
    statistics: tuple[StatOverride, ...] = ()
    passive_skills: tuple[PassiveSkill, ...] | None = None


STAT_FIELDS = {
    'regeneration_max': '_maxStatList_DataDefinedRegenerate',
    'regeneration': '_regenStatList_DataDefinedRegenerate',
    'level_stat': '_statList_DataDefinedStaticLevel',
}


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Item stat value is outside its integer range.')


def decode_stat_settings(data):
    if not isinstance(data, dict) or set(data) != {'statistics', 'passive_skills'}:
        raise ValueError('Unsupported item.stats fields.')
    edits = data['statistics']
    if not isinstance(edits, list) or len(edits) > 256:
        raise ValueError('Unsupported item stat override list.')
    statistics, seen = [], set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'kind', 'level', 'key', 'value'}:
            raise ValueError('Unsupported item stat selector fields.')
        if type(edit['kind']) is not str or edit['kind'] not in STAT_FIELDS:
            raise ValueError('Unsupported item stat family.')
        _integer(edit['level'], 0, 65535)
        _integer(edit['key'], 1, 0xffffffff)
        minimum, maximum = (0, 255) if edit['kind'] == 'level_stat' else (-(1 << 63), (1 << 63) - 1)
        if edit['value'] is not None:
            _integer(edit['value'], minimum, maximum)
        identity = edit['kind'], edit['level'], edit['key']
        if identity in seen:
            raise ValueError('Duplicate item stat override.')
        seen.add(identity)
        statistics.append(StatOverride(**edit))
    skills = data['passive_skills']
    if skills is not None:
        if not isinstance(skills, list) or len(skills) > 128:
            raise ValueError('Unsupported equipment passive skill list.')
        parsed, seen = [], set()
        for skill in skills:
            if not isinstance(skill, dict) or set(skill) != {'skill_key', 'level'}:
                raise ValueError('Unsupported equipment passive skill fields.')
            _integer(skill['skill_key'], 1, 0xffffffff)
            _integer(skill['level'], 0, 0xffffffff)
            if skill['skill_key'] in seen:
                raise ValueError('Duplicate equipment passive skill.')
            seen.add(skill['skill_key'])
            parsed.append(PassiveSkill(**skill))
        skills = tuple(parsed)
    if not statistics and skills is None:
        raise ValueError('Item stats require an explicit override.')
    return ItemStatSettings(tuple(statistics), skills)


def encode_stat_settings(settings):
    if type(settings) is not ItemStatSettings or tuple(field.name for field in fields(settings)) != ('statistics', 'passive_skills'):
        raise ValueError('Unsupported item stat settings type.')
    if any(type(edit) is not StatOverride for edit in settings.statistics):
        raise ValueError('Unsupported item stat override type.')
    if settings.passive_skills is not None and any(type(skill) is not PassiveSkill for skill in settings.passive_skills):
        raise ValueError('Unsupported equipment passive skill type.')
    data = {'statistics': [{'kind': edit.kind, 'level': edit.level, 'key': edit.key, 'value': edit.value}
                           for edit in settings.statistics],
            'passive_skills': None if settings.passive_skills is None else [
                {'skill_key': skill.skill_key, 'level': skill.level} for skill in settings.passive_skills]}
    decode_stat_settings(data)
    return data
