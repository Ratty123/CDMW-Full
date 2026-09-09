"""Three-way composition of owned overlay changes, with conflicts at record level.

The game replaces whole files. Independent installs instead own rows, shop entries,
group memberships and registry records. Rebuild their containers after merging;
never splice arbitrary byte offsets into a table that another install has grown.
"""
from collections import defaultdict
from dataclasses import replace
import re
import struct

from cdmw.core.structured_binary_editor import parse_pabgh_table


class OverlayConflict(ValueError):
    pass


def _value(before, after, current, where):
    if before == after or current == after:
        return current
    if current == before:
        return after
    raise OverlayConflict(f"Overlay conflict in {where}; both installs change the same record.")


def _indexed(records, key):
    # Some shipped collections repeat a key. Keep each occurrence independently.
    counts, result = defaultdict(int), {}
    for record in records:
        identity = key(record)
        result[(identity, counts[identity])] = record
        counts[identity] += 1
    return result


def _records(before, after, current, key, where, merge=_value):
    b, a, c = (_indexed(rows, key) for rows in (before, after, current))
    result = {}
    for identity in dict.fromkeys((*c, *a, *b)):
        value = merge(b.get(identity), a.get(identity), c.get(identity), f"{where} [{identity[0]}]")
        if value is not None:
            result[identity] = value
    return tuple(result.values())


def _store(before, after, current, where, layout):
    from cdmw.core.storeinfo_table import parse_store_row, encode_store_row
    b, a, c = (parse_store_row(raw, layout=layout) for raw in (before, after, current))
    def normalized(row):
        return tuple(replace(e, stock_index=0, offset=-1, end=-1) for e in row.entries)
    entries = _records(*map(normalized, (b, a, c)), lambda e: e.order_index, where)
    # Buyable entries precede the sell-only entries in the shipped grammar.
    entries = tuple(e for e in entries if e.is_buyable) + tuple(e for e in entries if not e.is_buyable)
    entries = tuple(replace(e, stock_index=i) for i, e in enumerate(entries))
    return encode_store_row(replace(c, prefix=_value(b.prefix, a.prefix, c.prefix, where),
        tail=_value(b.tail, a.tail, c.tail, where), store_type=_value(b.store_type, a.store_type, c.store_type, where),
        entries=entries, buyable_count=sum(e.is_buyable for e in entries), sellable_count=sum(e.is_sellable for e in entries)))


def _group(before, after, current, where):
    from cdmw.core.itemgroupinfo_table import parse_item_group_row, encode_item_group_row
    b, a, c = map(parse_item_group_row, (before, after, current))
    members = _records(b.members, a.members, c.members, lambda key: key, where)
    return encode_item_group_row(replace(c, members=members,
        prefix=_value(b.prefix, a.prefix, c.prefix, where), tail=_value(b.tail, a.tail, c.tail, where),
        subgroups=_value(b.subgroups, a.subgroups, c.subgroups, where)))


def _row(before, after, current, where, path):
    try:
        return _value(before, after, current, where)
    except OverlayConflict:
        if before is None or after is None or current is None:
            raise
        name = path.rsplit('/', 1)[-1].split('.')[0]
        if name == 'storeinfo':
            return _store(before, after, current, where, 'current' if path.endswith('.staticinfobody') else 'legacy')
        if name == 'itemgroupinfo':
            return _group(before, after, current, where)
        raise


def _table(body, header):
    table = parse_pabgh_table(header, payload=body)
    if len(header) != table.header_size + len(table.rows) * (table.key_width + 4):
        raise OverlayConflict('Unsupported table directory layout.')
    spans = table.row_spans(len(body))
    if len(spans) != len(table.rows) or (spans and spans[0][1] != 0):
        raise OverlayConflict('Incomplete table row directory.')
    records = [(row.key, body[start:end]) for row, start, end in spans]
    if len({key for key, _ in records}) != len(records):
        raise OverlayConflict('Duplicate primary keys in an overlay table.')
    return table, records


def _table_pair(before, after, current, path, head):
    tables = [_table(values[path], values[head]) for values in (before, after, current)]
    b, a, c = tables
    if len({(t.key_width, t.header_size) for t, _ in tables}) != 1:
        raise OverlayConflict(f'Table layout changed in {path}.')
    def merge(old, new, present, where):
        key = next(value[0] for value in (new, present, old) if value is not None)
        raw = _row(old[1] if old else None, new[1] if new else None, present[1] if present else None, where, path)
        return (key, raw) if raw is not None else None
    rows = _records(b[1], a[1], c[1], lambda r: r[0], path, merge)
    offsets, payload = {}, bytearray()
    for key, raw in rows:
        offsets[key] = len(payload)
        payload.extend(raw)
    # Keep the directory's own order, independent of payload order.
    ordered = list(dict.fromkeys([r.key for t, _ in (c, a) for r in t.rows]))
    ordered = [key for key in ordered if key in offsets]
    count_width = c[0].header_size
    header = len(rows).to_bytes(count_width, 'little') + b''.join(key + struct.pack('<I', offsets[key]) for key in ordered)
    _table(bytes(payload), header)
    return bytes(payload), header


def _paloc(before, after, current, where):
    from cdmw.core.paloc_format import parse_paloc, encode_paloc, add_localization_entries
    b, a, c = map(parse_paloc, (before, after, current))
    entries = _records(b.entries, a.entries, c.entries, lambda e: e.key, where)
    existing = {e.key for e in c.entries}
    kept = replace(c, entries=tuple(e for e in entries if e.key in existing))
    return encode_paloc(add_localization_entries(kept, tuple(e for e in entries if e.key not in existing)))


def _pappt(before, after, current, where):
    from cdmw.core.pappt_format import parse_pappt, encode_pappt
    b, a, c = map(parse_pappt, (before, after, current))
    return encode_pappt(replace(c,
        records=_records(b.records, a.records, c.records, lambda r: r.stem, where),
        head_records=_records(b.head_records, a.head_records, c.head_records, lambda r: r.stem, where),
        reserved=_value(b.reserved, a.reserved, c.reserved, where),
        tag_prefix=_value(b.tag_prefix, a.tag_prefix, c.tag_prefix, where)))


def _pathc(before, after, current, where):
    from cdmw.core.pathc_format import parse_pathc, encode_pathc, PathcEntry
    b, a, c = map(parse_pathc, (before, after, current))
    def records(table):
        return tuple((e.checksum, table.headers[e.header_index] if e.is_direct else None,
                      e.collision_start, e.collision_end, e.block_infos) for e in table.entries)
    merged = _records(*map(records, (b, a, c)), lambda r: r[0], where)
    headers, entries = list(c.headers), []
    for checksum, header, start, end, blocks in sorted(merged):
        if header is not None and header not in headers:
            headers.append(header)
        entries.append(PathcEntry(checksum, headers.index(header) if header is not None else 0xFFFF, start, end, blocks))
    return encode_pathc(replace(c, headers=tuple(headers), entries=tuple(entries),
        reserved=_value(b.reserved, a.reserved, c.reserved, where),
        header_size=_value(b.header_size, a.header_size, c.header_size, where),
        collisions=_value(b.collisions, a.collisions, c.collisions, where),
        filenames=_value(b.filenames, a.filenames, c.filenames, where)))


def legacy_texture_baseline(original, current, textures):
    """Undo only registrations proven to belong to the legacy archive's DDS files."""
    from cdmw.core.pathc_format import parse_pathc, encode_pathc, pathc_checksum, dds_shape, block_infos_for

    old, live = map(parse_pathc, (original, current))
    old_entries = {e.checksum: e for e in old.entries}
    entries, headers = {e.checksum: e for e in live.entries}, list(live.headers)

    def signature(table, entry):
        if entry is None:
            return None
        header = table.headers[entry.header_index] if entry.is_direct else None
        return header, entry.collision_start, entry.collision_end, entry.block_infos

    def matches(table, entry, payload):
        if entry is None or not entry.is_direct or payload is None:
            return False
        try:
            return (dds_shape(table.dds_header_for(entry)) == dds_shape(payload)
                    and entry.block_infos == block_infos_for(payload))
        except (ValueError, struct.error):
            return False

    for texture, (before, after) in textures.items():
        checksum = pathc_checksum(texture)
        previous, present = old_entries.get(checksum), entries.get(checksum)
        if signature(old, previous) == signature(live, present):
            continue
        # A collision, changed registration, or mismatching underlay has no
        # trustworthy ownership boundary. Refuse instead of restoring that row.
        if (old.header_size != live.header_size or not matches(live, present, after)
                or (previous is None and before is not None)
                or (previous is not None and not matches(old, previous, before))):
            path = 'meta/0.pathc'
            raise OverlayConflict(f'Overlay conflict in {path}; overlapping file edits cannot be separated safely.')
        if previous is None:
            entries.pop(checksum)
        else:
            header = old.headers[previous.header_index]
            if header not in headers:
                headers.append(header)
            entries[checksum] = replace(previous, header_index=headers.index(header))
    # Keep live header/collision tables: unrelated registrations may reference
    # records added after the legacy install, including shared DDS headers.
    return encode_pathc(replace(live, headers=tuple(headers), entries=tuple(entries[key] for key in sorted(entries))))


def owned_item_references(changes):
    """Item references in changed rows, excluding inherited whole-table contents."""
    from cdmw.core.iteminfo_row import parse_iteminfo_row
    from cdmw.core.item_recipe_table import parse_item_recipe
    from cdmw.core.item_reward_table import parse_item_reward_set

    references = set()
    for body, change in changes.items():
        name = body.rsplit('/', 1)[-1]
        if name not in ('iteminfo.staticinfobody', 'iteminfo.pabgb',
                        'multichangeinfo.staticinfobody', 'dropsetinfo.staticinfobody') or change['after'] is None:
            continue
        head = body.replace('.staticinfobody', '.staticinfoheader').replace('.pabgb', '.pabgh')
        if head not in changes:
            raise OverlayConflict(f'Both table files are required to compose {body}.')
        old = dict(_table(change['before'], changes[head]['before'])[1]) if change['before'] is not None else {}
        for key, raw in _table(change['after'], changes[head]['after'])[1]:
            if old.get(key) == raw:
                continue
            if name.startswith('iteminfo.'):
                row = parse_iteminfo_row(raw)
                references.update(row.socket_items)
                references.update(item for item, _count, _extra in row.add_socket_materials)
                references.update(p.item_key for p in row.price_list)
                references.update(p.item_key for level in row.enchant_levels for p in level.buy_prices)
            elif name.startswith('multichangeinfo.'):
                references.update(i.item_key for i in parse_item_recipe(raw).ingredients)
            else:
                references.update(i.item_key for i in parse_item_reward_set(raw).entries)
    return references


_ICON = re.compile(rb'<Texture\s+Name="([^"]*)"\s+Filename="[^"]*"[^>]*/>')


def _icons(before, after, current, where):
    def parts(data):
        matches = list(_ICON.finditer(data))
        if not matches:
            raise OverlayConflict(f'Unsupported icon registry in {where}.')
        # The writer appends Texture elements to a flat document. Retain its BOM
        # and reject any other content changing under the merge.
        remainder = _ICON.sub(b'', data).strip(b'\r\n\t ')
        return remainder, tuple((m.group(1).lower(), m.group(0)) for m in matches)
    b, a, c = map(parts, (before, after, current))
    prefix = _value(b[0], a[0], c[0], where)
    records = _records(b[1], a[1], c[1], lambda r: r[0], where)
    newline = b'\r\n' if b'\r\n' in current else b'\n'
    return prefix + newline.join(raw for _key, raw in records) + newline


def merge_overlay_files(before, after, current):
    """Apply one owned change onto current files. Missing values mean no file."""
    result = dict(current)
    done = set()
    for path in dict.fromkeys((*before, *after)):
        if path in done:
            continue
        b, a, c = before.get(path), after.get(path), current.get(path)
        try:
            result[path] = _value(b, a, c, path)
            continue
        except OverlayConflict:
            if b is None or a is None or c is None:
                raise
        if path.endswith(('.staticinfoheader', '.pabgh')):
            body = path.replace('.staticinfoheader', '.staticinfobody').replace('.pabgh', '.pabgb')
        elif path.endswith(('.staticinfobody', '.pabgb')):
            body = path
        else:
            body = ''
        if body:
            head = body.replace('.staticinfobody', '.staticinfoheader').replace('.pabgb', '.pabgh')
            if any(values.get(body) is None or values.get(head) is None for values in (before, after, current)):
                raise OverlayConflict(f'Both table files are required to compose {body}.')
            result[body], result[head] = _table_pair(before, after, current, body, head)
            done.update((body, head))
        elif path.endswith('.paloc'):
            result[path] = _paloc(b, a, c, path)
        elif path.endswith('.pappt'):
            result[path] = _pappt(b, a, c, path)
        elif path == 'meta/0.pathc':
            result[path] = _pathc(b, a, c, path)
        elif path == 'ui/xml/texture/cd_item_icon.xml':
            result[path] = _icons(b, a, c, path)
        else:
            raise OverlayConflict(f'Overlay conflict in {path}; overlapping file edits cannot be separated safely.')
    return result
