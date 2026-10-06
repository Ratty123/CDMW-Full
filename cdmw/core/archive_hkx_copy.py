"""Recognize the shipped mesh-collision schemas permitted for unchanged copying.

This does not deserialize/rewrite Havok objects. The caller must additionally
prove byte identity with the shipped HKX and its PAC. The two TYPE witnesses are
the 2024.2 convex/compound shape dictionaries observed in Canta equipment and
Rhett's Longsword: numeric collision geometry and internal shape references,
without resource-name or item-registration classes. Other dictionaries refuse.
"""
import hashlib
import struct

from cdmw.core.archive_hkx_parser import (
    _extract_hkx_tst1_type_names, _find_hkx_tag_items,
    _parse_hkx_item_records, _parse_hkx_tna1_type_infos,
)

_SCHEMAS = {
    '09a122f99a314f106572f6c3bfaa157f1114eac5ae3bb92560c208bfbabcb0c7': 'hknpConvexShape',
    '1246da01285c97355b4b8051e1e52a3df76c09ff346bfb241f2234a0c1862fab': 'hknpCompoundShape',
}
_CHILDREN = {
    b'TAG0': (b'SDKV', b'DATA', b'TYPE', b'INDX'),
    b'TYPE': (b'MTTP', b'TST1', b'TNA1', b'TPAD'),
    b'INDX': (b'ITEM',),
}


def validate_hkx_copy_source(data):
    """Refuse unknown dictionaries, extra sections, and invalid ITEM boundaries."""
    error = 'The template physics uses an unverified collision layout.'
    if not 32 <= len(data) <= 16 * 1024 * 1024:
        raise ValueError(error)
    sections = {}

    def section(start, end, expected):
        if start + 8 > end:
            raise ValueError(error)
        word = struct.unpack_from('>I', data, start)[0]
        size, flags = word & 0x0fffffff, word & 0xf0000000
        tag = data[start + 4:start + 8]
        if tag != expected or size < 8 or start + size > end or tag in sections:
            raise ValueError(error)
        children = _CHILDREN.get(tag)
        if flags != (0 if children else 0x40000000):
            raise ValueError(error)
        sections[tag] = (start, start + size)
        if children:
            cursor = start + 8
            for child in children:
                cursor = section(cursor, start + size, child)
            if cursor != start + size:
                raise ValueError(error)
        return start + size

    if section(0, len(data), b'TAG0') != len(data):
        raise ValueError(error)
    start, end = sections[b'SDKV']
    if data[start + 8:end] != b'20240200':
        raise ValueError(error)
    start, end = sections[b'TYPE']
    expected_root = _SCHEMAS.get(hashlib.sha256(data[start:end]).hexdigest())
    if expected_root is None:
        raise ValueError(error)
    # Reuse the HKX readers, but accept only sections reached through the exact
    # container boundaries above, never marker-shaped bytes inside geometry.
    items = [item for item in _find_hkx_tag_items(data)
             if (bounds := sections.get(item.name.encode())) is not None
             and item.offset == bounds[0] + 4]
    names = _extract_hkx_tst1_type_names(data, items)
    count, types, warnings = _parse_hkx_tna1_type_infos(data, items, names)
    if warnings or count != len(types) + 1:
        raise ValueError(error)
    records = _parse_hkx_item_records(data, items, {t.index: t.name for t in types})
    start, end = sections[b'ITEM']
    if (data[start + 8:start + 20] != bytes(12) or (end - start - 20) % 12
            or not records or records[0].type_name != expected_root or records[0].data_offset != 0):
        raise ValueError(error)
    data_size = sections[b'DATA'][1] - sections[b'DATA'][0] - 8
    if any(not record.type_name or record.flags not in (0x10000000, 0x20000000)
           or not 0 < record.count <= data_size or not 0 <= record.data_offset < data_size
           for record in records):
        raise ValueError(error)
