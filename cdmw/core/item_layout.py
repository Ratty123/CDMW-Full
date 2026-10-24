"""Read-only, bounded layouts for ItemInfo and discriminated ItemUseInfo rows.

The closed grammar contains byte counts, local branch indexes and reader IDs.
It cannot execute code, resolve runtime locations or accept a package-supplied
grammar. Editors must separately qualify each field they intend to change.
"""
from dataclasses import dataclass
from types import MappingProxyType

from cdmw.core._item_layout_schema import ITEMINFO_FIELDS, ITEMINFO_LAYOUT, ITEMUSE_FIELDS, ITEMUSE_LAYOUT
from cdmw.core.new_item_record import Cursor, RecordError

MAX_RECORD = 65536
MAX_ELEMENTS = 4096
MAX_STEPS = 200000


@dataclass(frozen=True)
class Span:
    start: int
    end: int

    @property
    def size(self):
        return self.end - self.start


@dataclass(frozen=True)
class Member:
    owner: str
    name: str
    path: tuple
    span: Span


@dataclass(frozen=True)
class ItemLayout:
    raw: bytes
    kind: str
    generation: str
    fields: object
    members: tuple[Member, ...]
    variants: tuple[str, ...]

    def data(self, field):
        span = self.fields[field]
        return self.raw[span.start:span.end]

    def integer(self, field, *, width=None, signed=False):
        data = self.data(field)
        if width is not None and len(data) != width:
            raise RecordError(f'Unsupported {field} width.')
        return int.from_bytes(data, 'little', signed=signed)


class _Walker:
    def __init__(self, raw, grammar, generation, stop_at=None):
        if not isinstance(raw, (bytes, bytearray)) or not 1 <= len(raw) <= MAX_RECORD:
            raise RecordError('Static item row exceeds the layout limit.')
        self.cursor = Cursor(raw)
        self.grammar = grammar
        self.generation = generation
        self.steps = 0
        self.fields = {}
        self.members = []
        self.variants = []
        self.stop_at = stop_at

    def run(self, program, path=(), depth=0, root=False):
        if depth > 40:
            raise RecordError('Static item layout recursion limit.')
        values, slots = {}, {}
        width = None
        pc = 0
        while pc < len(program):
            self.steps += 1
            if self.steps > MAX_STEPS:
                raise RecordError('Static item layout instruction limit.')
            op = program[pc]
            code, start = op[0], self.cursor.pos
            owner = label = ''
            if code == 'read':
                _code, size, owner, label = op
                if self.generation == 'legacy' and (owner, label) in (
                        ('InspectAction', '_catchTagNameHash'), ('ItemInfo_FactionManagementData', '_tier')):
                    size = 0
                size = width if size is None else size
                if type(size) is not int or not 0 <= size <= MAX_RECORD:
                    raise RecordError('Unqualified dynamic item width.')
                values[pc] = int.from_bytes(self.cursor.take(size), 'little')
            elif code == 'bytes':
                self.cursor.take(values[op[1]])
            elif code == 'call':
                _code, reader, owner, label = op
                self.run(self.grammar[reader], path + (label or ('reader', reader, pc),), depth + 1)
            elif code == 'list':
                _code, fixed, source, body, owner, label = op
                count = values[source] if fixed is None else fixed
                if root and label == '_itemPushInventoryContentsType' and self.generation == 'legacy':
                    count = 9
                if type(count) is not int or not 0 <= count <= MAX_ELEMENTS:
                    raise RecordError('Static item list exceeds the supported bound.')
                for index in range(count):
                    self.run(body, path + (label or ('list', pc), index), depth + 1)
            elif code == 'choice':
                # Closed discriminated payloads. Bodies are application-owned;
                # package data can select a branch but cannot supply a grammar.
                selected = values[op[1]]
                if selected not in op[2]:
                    raise RecordError('Unsupported item discriminant.')
                self.run(op[2][selected], path + (('choice', selected),), depth + 1)
            elif code == 'branch':
                _code, condition, source, compare, destination = op
                value = values[source]
                if {'eq': value == compare, 'ne': value != compare,
                    'le': value <= compare, 'gt': value > compare}[condition]:
                    pc = destination
                    continue
            elif code == 'switch':
                value = values[op[1]]
                if not 0 <= value < len(op[2]):
                    raise RecordError('Unsupported static item discriminator.')
                pc = op[2][value]
                continue
            elif code == 'select':
                value = values[op[1]]
                if value not in op[2]:
                    raise RecordError('Unsupported item-use variant.')
                slots = op[2][value]
                if value in op[3]:
                    self.variants.append(op[3][value])
            elif code == 'object':
                slots = op[1]
                if op[2]:
                    self.variants.append(op[2])
            elif code == 'dispatch':
                _code, slot, owner, label = op
                if slot not in slots:
                    raise RecordError('Unqualified item-use payload reader.')
                self.run(self.grammar[slots[slot]], path + (label or ('payload', pc),), depth + 1)
            elif code == 'width':
                width = op[1]
            elif code == 'jump':
                pc = op[1]
                continue
            elif code == 'end':
                return
            else:
                raise RecordError('Unsupported static item layout branch.')
            span = Span(start, self.cursor.pos)
            if label:
                if root:
                    previous = self.fields.get(label)
                    if previous is not None and previous.end != span.start:
                        raise RecordError('Ambiguous root item field.')
                    self.fields[label] = Span(previous.start if previous else span.start, span.end)
                    if label == self.stop_at:
                        return
                else:
                    self.members.append(Member(owner, label, path, span))
            pc += 1


def _read(raw, kind, generation):
    grammar, fields = (ITEMINFO_LAYOUT, ITEMINFO_FIELDS) if kind == 'iteminfo' else (ITEMUSE_LAYOUT, ITEMUSE_FIELDS)
    walk = _Walker(raw, grammar, generation)
    try:
        walk.run(grammar[0], root=True)
        walk.cursor.finish()
        if set(walk.fields) != set(fields):
            raise RecordError('Incomplete static item field inventory.')
    except (KeyError, IndexError, TypeError, RecursionError) as exc:
        raise RecordError('Unsupported static item layout.') from exc
    return ItemLayout(bytes(raw), kind, generation, MappingProxyType(walk.fields),
                      tuple(walk.members), tuple(walk.variants))


def read_item_layout(raw, *, generation=None):
    """Qualify the entire row, including EOF; unknown/ambiguous layouts refuse."""
    if generation is not None:
        if generation not in ('legacy', 'current'):
            raise RecordError('Unknown ItemInfo generation.')
        return _read(raw, 'iteminfo', generation)
    candidates = []
    for variant in ('legacy', 'current'):
        try:
            candidates.append(_read(raw, 'iteminfo', variant))
        except RecordError:
            pass
    if len(candidates) != 1:
        raise RecordError('Unknown or ambiguous complete ItemInfo layout.')
    return candidates[0]


def read_item_use_layout(raw):
    result = _read(raw, 'itemuseinfo', 'current')
    if result.integer('_isBlocked', width=1) != 0:
        raise RecordError('Blocked item-use definition.')
    return result


def item_use_prefix(raw):
    """Cheap read-only catalogue hint; edits still require a complete layout."""
    walk = _Walker(raw, ITEMINFO_LAYOUT, 'current', stop_at='_itemUseInfoList')
    try:
        walk.run(ITEMINFO_LAYOUT[0], root=True)
        span = walk.fields['_itemUseInfoList']
        cursor = Cursor(raw[span.start:span.end])
        values = tuple(cursor.unpack('I') for _ in range(cursor.count(128)))
        cursor.finish()
        return values
    except (KeyError, IndexError, TypeError) as exc:
        raise RecordError('Unsupported ItemInfo use-list prefix.') from exc


def replace_layout_fields(layout, replacements):
    """Replace declared complete fields while preserving every other field byte."""
    if not replacements or set(replacements) - set(layout.fields):
        raise RecordError('Unknown or empty item layout field edit.')
    result = bytearray(layout.raw)
    for field in sorted(replacements, key=lambda name: layout.fields[name].start, reverse=True):
        span = layout.fields[field]
        result[span.start:span.end] = replacements[field]
    final = _read(bytes(result), layout.kind, layout.generation)
    for field in layout.fields:
        expected = replacements.get(field, layout.data(field))
        if final.data(field) != expected:
            raise RecordError('Item layout edit changed an unassigned field.')
    return final


def counted_integers(layout, field, *, width=4):
    cursor = Cursor(layout.data(field))
    values = tuple(int.from_bytes(cursor.take(width), 'little') for _ in range(cursor.count(MAX_ELEMENTS)))
    cursor.finish()
    return values


def hash_reference_spans(layout):
    """Only declared icon/prefab/animation hashes can be rebound as resources."""
    references = []
    for member in layout.members:
        if member.owner == 'ItemIconData' and member.name in ('_iconPath', '_highlightIconPath'):
            if member.span.size != 4:
                raise RecordError('Unqualified icon reference width.')
            references.append(('icon', member.span))
        elif member.owner == 'PrefabData' and member.name in ('_prefabNames', '_animationPathList'):
            cursor = Cursor(layout.raw[member.span.start:member.span.end])
            count = cursor.count(MAX_ELEMENTS)
            for _ in range(count):
                start = member.span.start + cursor.pos
                cursor.take(4)
                references.append(('prefab' if member.name == '_prefabNames' else 'animation', Span(start, start + 4)))
            cursor.finish()
    return tuple(references)


def rebind_item_hashes(layout, replacements):
    output = bytearray(layout.raw)
    found = set()
    for _role, span in hash_reference_spans(layout):
        value = int.from_bytes(layout.raw[span.start:span.end], 'little')
        if value in replacements:
            target = replacements[value]
            if type(target) is not int or not 1 <= target <= 0xffffffff:
                raise RecordError('Invalid owned item resource hash.')
            output[span.start:span.end] = target.to_bytes(4, 'little')
            found.add(value)
    if set(replacements) != found:
        raise RecordError('An owned hash has no declared icon, prefab or animation reference.')
    final = _read(bytes(output), 'iteminfo', layout.generation)
    for name in layout.fields:
        if name not in ('_itemIconList', '_prefabDataList') and final.data(name) != layout.data(name):
            raise RecordError('Resource rebinding changed an unrelated ItemInfo field.')
    return final


def clone_layout_item(layout, *, key, string_key, name_key, desc_key, hashes, recipes=None):
    """Clone identities and resource references using declared field locations."""
    import struct
    from cdmw.core.new_item_record import text_bytes
    if hashes:
        layout = rebind_item_hashes(layout, hashes)
    if recipes:
        old = counted_integers(layout, '_multiChangeInfoList')
        if set(recipes) - set(old):
            raise RecordError('An owned recipe has no declared ItemInfo reference.')
        entries = tuple(recipes.get(value, value) for value in old)
        data = struct.pack('<I', len(entries)) + b''.join(struct.pack('<I', value) for value in entries)
        layout = replace_layout_fields(layout, {'_multiChangeInfoList': data})
    name = layout.data('_itemName')
    description = layout.data('_itemDesc')
    if len(name) < 13 or name[:5] != b'\x07\x70\0\0\0':
        raise RecordError('Unsupported item-name localization layout.')
    edits = {'_key': struct.pack('<I', key), '_stringKey': text_bytes(string_key),
             '_itemName': name[:5] + struct.pack('<I', key) + text_bytes(name_key)}
    if description[:5] == b'\x07\x71\0\0\0':
        if desc_key is None:
            raise RecordError('The template needs its owned description key.')
        edits['_itemDesc'] = description[:5] + struct.pack('<I', key) + text_bytes(desc_key)
    return replace_layout_fields(layout, edits).raw
