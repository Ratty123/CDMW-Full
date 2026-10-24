"""Independently serialized nonempty stat families, levels and passive skills."""
import struct

from tests.item_layout_fixtures import full_item


def enchant_stats(level, *, maximum=100, regeneration=-2, parameter=3):
    def counter(key, value):
        return struct.pack('<IIq', 1, key, value)
    return (struct.pack('<H', level) + counter(1000002, maximum) + counter(1000003, regeneration)
            + counter(1000002, 12000) + struct.pack('<IIB', 1, 1000003, parameter)
            + struct.pack('<IIQII', 1, 1, 348, 77, 1) + struct.pack('<III', 1, 440001, 19) + bytes(4))


def stat_item(raw=None, *, current=True, levels=None, passive_skills=((600001, 4),)):
    levels = (enchant_stats(0), enchant_stats(1, maximum=200, regeneration=5, parameter=9)) if levels is None else levels
    return full_item(raw, current=current, fields={
        '_enchantDataList': struct.pack('<I', len(levels)) + b''.join(levels),
        '_equipPassiveSkillList': struct.pack('<I', len(passive_skills)) + b''.join(
            struct.pack('<II', *skill) for skill in passive_skills)})
