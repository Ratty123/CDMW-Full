"""Typed assignments to existing ItemInfo fields; offsets are adapter-owned.

Source preconditions read the pristine row. Composition writes named fields and
preserves every other byte. Game, save and arbitrary row-layout support are not
implied by successful binary composition.
"""
from dataclasses import dataclass
import hashlib
import re
import struct

from cdmw.core.iteminfo_row import parse_iteminfo_row, set_max_stack_count, set_stat_value
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.cancellation import raise_if_cancelled


ADAPTER = 'cd.iteminfo.prefix-stat-11-v1'
CURRENT_ADAPTER = 'cd.iteminfo.prefix-stat-12-v1'
ADAPTER_MARKERS = {ADAPTER: 0x11, CURRENT_ADAPTER: 0x12}
MAX_OPERATIONS = 4096
MAX_ROW_BYTES = 65536


@dataclass(frozen=True)
class FieldAssignment:
    owner: str
    identity: str
    adapter: str
    record: int
    field: tuple
    source_digest: str
    expect: int
    value: int

    @property
    def label(self):
        return f'{self.owner}/{self.identity}'

    @property
    def target(self):
        return f'ItemInfo record {self.record} field {self.field}'


@dataclass(frozen=True)
class CompiledAssignment:
    operation: FieldAssignment
    offset: int
    source_reads: tuple
    writes: tuple
    invariants: tuple[str, ...]


class ItemFieldConflict(IndependentItemError):
    def __init__(self, operation, other, detail):
        self.record = operation.record
        self.field = operation.field
        self.owners = (operation.label, other)
        super().__init__(f'{operation.target}: {operation.label}; {other}: {detail}')


def decode_assignment(owner, raw):
    if isinstance(raw,dict) and raw.get('kind')=='field.replace':
        from cdmw.domain.new_item.iteminfo_overrides import decode_declared_assignment
        return decode_declared_assignment(owner,raw)
    fields = {'id', 'kind', 'target', 'field', 'value_type', 'expect', 'value', 'precondition_base', 'source_row'}
    if not isinstance(raw, dict) or set(raw) != fields or raw['kind'] != 'field.assign':
        raise IndependentItemError('Unsupported ItemInfo operation fields or kind.')
    if not isinstance(owner, str) or not 1 <= len(owner) <= 256 or '\0' in owner:
        raise IndependentItemError('Invalid ItemInfo operation owner.')
    if not isinstance(raw['id'], str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', raw['id']):
        raise IndependentItemError('Invalid ItemInfo operation identity.')
    target = raw['target']
    if (not isinstance(target, dict) or set(target) != {'adapter', 'table', 'key'}
            or not isinstance(target['adapter'], str) or target['adapter'] not in ADAPTER_MARKERS or target['table'] != 'ItemInfo'
            or type(target['key']) is not int or not 1 <= target['key'] <= 0xffffffff):
        raise IndependentItemError('Unsupported ItemInfo target or adapter.')
    field = raw['field']
    if not isinstance(field, dict):
        raise IndependentItemError('Invalid ItemInfo field selector.')
    if field == {'name': 'max_stack_count'}:
        selector, value_type, minimum, maximum = ('max_stack_count',), 'u32', 1, 0xffffffff
    elif set(field) == {'name', 'enchant_level', 'status_key'} and field['name'] == 'stat_value':
        if (type(field['enchant_level']) is not int or not 0 <= field['enchant_level'] < 40
                or type(field['status_key']) is not int or not 1 <= field['status_key'] <= 0xffffffff):
            raise IndependentItemError('Invalid ItemInfo stat selector.')
        selector = ('stat_value', field['enchant_level'], field['status_key'])
        value_type, minimum, maximum = 'i32', -0x80000000, 0x7fffffff
    else:
        raise IndependentItemError('Unsupported ItemInfo field; arbitrary offsets are not accepted.')
    if (raw['value_type'] != value_type or any(type(raw[key]) is not int or not minimum <= raw[key] <= maximum
                                             for key in ('expect', 'value'))):
        raise IndependentItemError(f'{selector}: expected {value_type} values in {minimum}..{maximum}.')
    if raw['precondition_base'] != 'source':
        raise IndependentItemError('ItemInfo assignments require source-based preconditions.')
    if not isinstance(raw['source_row'], str) or not re.fullmatch('[0-9a-f]{64}', raw['source_row']):
        raise IndependentItemError('ItemInfo assignments require an exact source-row digest.')
    return FieldAssignment(owner, raw['id'], target['adapter'], target['key'], selector, raw['source_row'], raw['expect'], raw['value'])


def _row(raw, record):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_ROW_BYTES:
        raise IndependentItemError(f'ItemInfo record {record} is missing or exceeds the adapter row limit.')
    try:
        row = parse_iteminfo_row(raw)
    except (ValueError, struct.error) as exc:
        raise IndependentItemError(f'ItemInfo record {record} has an unsupported row layout.') from exc
    offset = row.max_stack_count_offset
    if (row.key != record or row.is_blocked != 0 or row.desc_offset is None or row.category_info is None
            or row.prefix_end > len(raw) or row.max_stack_count < 1
            or raw[offset + 4:offset + 8] != b'\0' * 4):
        raise IndependentItemError(f'ItemInfo record {record} has an unsupported prefix layout.')
    return row


def _field(row, selector, adapter):
    if selector == ('max_stack_count',):
        return row.max_stack_count, row.max_stack_count_offset
    if row.stat_block_marker != ADAPTER_MARKERS[adapter] or row.stat_block_flags != (len(row.socket_items), int(bool(row.add_socket_materials))):
        raise IndependentItemError(f'ItemInfo record {row.key} has an unsupported stat-block layout.')
    matches = [stat for level in row.enchant_levels if level.level == selector[1]
               for stat in level.stats if stat.status_key == selector[2]]
    if len(matches) != 1:
        raise IndependentItemError(f'ItemInfo record {row.key} has a missing or ambiguous stat {selector[1:]}.')
    return matches[0].value, matches[0].offset


def _compile_legacy_assignments(contributions, source_rows, *, protected=None, stop_event=None):
    """Validate every source precondition before producing a write plan.

`protected` contains complete-row requirements of every active legacy package,
including ones compiled later. Its caller must collect the whole profile first.
"""
    protected = protected or {}
    compiled, seen, writes = [], set(), {}
    for owner, operations in contributions:
        if not isinstance(operations, (tuple, list)) or not operations:
            raise IndependentItemError('ItemInfo modules require at least one operation.')
        for raw in operations:
            raise_if_cancelled(stop_event)
            if len(compiled) >= MAX_OPERATIONS:
                raise IndependentItemError('The ItemInfo operation budget is exhausted.')
            operation = decode_assignment(owner, raw)
            identity = (owner, operation.identity)
            if identity in seen:
                raise IndependentItemError(f'Duplicate ItemInfo operation: {operation.label}.')
            seen.add(identity)
            source = source_rows.get(operation.record)
            row = _row(source, operation.record)
            if hashlib.sha256(source).hexdigest() != operation.source_digest:
                raise IndependentItemError(f'{operation.target}: the source row changed.')
            value, offset = _field(row, operation.field, operation.adapter)
            if value != operation.expect:
                raise IndependentItemError(f'{operation.target}: expected {operation.expect}, found {value} in the source.')
            if operation.record in protected and operation.value != value:
                raise ItemFieldConflict(operation, ', '.join(protected[operation.record]), 'a legacy package requires this complete record unchanged.')
            key = (operation.record, operation.field)
            if key in writes and writes[key].value != operation.value:
                other = writes[key]
                raise ItemFieldConflict(operation, other.label, f'opposing assignments {operation.value} and {other.value}.')
            writes[key] = operation
            compiled.append(CompiledAssignment(operation, offset,
                (('source', 'ItemInfo', operation.record, operation.source_digest),),
                (('ItemInfo', operation.record, operation.field),),
                ('unchanged row length, identity and layout', 'all unassigned bytes preserved', 'assigned typed values present')))
    return tuple(compiled)


def _compose_legacy_assignments(source_rows, compiled, *, stop_event=None):
    """Recompose solely from source plus active typed contributions; no undo deltas."""
    result = dict(source_rows)
    grouped = {}
    for value in compiled:
        raise_if_cancelled(stop_event)
        operation = value.operation
        key = (operation.record, operation.field)
        if key in grouped and grouped[key].operation.value != operation.value:
            raise ItemFieldConflict(operation, grouped[key].operation.label, 'opposing assignments in the compiled plan.')
        grouped[key] = value
    allowed = {}
    for (record, selector), value in sorted(grouped.items()):
        raise_if_cancelled(stop_event)
        operation = value.operation
        source = source_rows.get(record)
        if source is None or hashlib.sha256(source).hexdigest() != operation.source_digest:
            raise IndependentItemError(f'{operation.target}: compiled source changed.')
        row = _row(result[record], record)
        _, offset = _field(row, selector, operation.adapter)
        if offset != value.offset or not 0 <= offset <= len(source) - 4:
            raise IndependentItemError(f'{operation.target}: compiled layout changed.')
        result[record] = (set_max_stack_count(row, operation.value) if selector == ('max_stack_count',)
                          else set_stat_value(row, selector[1], selector[2], operation.value))
        allowed.setdefault(record, set()).update(range(offset, offset + 4))
    for record, offsets in allowed.items():
        raise_if_cancelled(stop_event)
        source, output = source_rows[record], result[record]
        if len(source) != len(output) or any(a != b and index not in offsets for index, (a, b) in enumerate(zip(source, output))):
            raise IndependentItemError(f'ItemInfo record {record}: a write changed unassigned data.')
        row = _row(output, record)
        for (key, selector), value in grouped.items():
            if key == record and _field(row, selector, value.operation.adapter) != (value.operation.value, value.offset):
                raise IndependentItemError(f'ItemInfo record {record}: an assigned value failed round-trip validation.')
    return result


def compile_assignments(contributions,source_rows,*,protected=None,stop_event=None):
    contributions=tuple(contributions)
    if any(isinstance(raw,dict) and raw.get('kind')=='field.replace' for _owner,operations in contributions
           if isinstance(operations,(list,tuple)) for raw in operations):
        from cdmw.domain.new_item.iteminfo_overrides import compile_mixed_assignments
        return compile_mixed_assignments(contributions,source_rows,protected=protected,stop_event=stop_event)
    return _compile_legacy_assignments(contributions,source_rows,protected=protected,stop_event=stop_event)


def compose_assignments(source_rows,compiled,*,stop_event=None):
    compiled=tuple(compiled)
    if any(value.operation.adapter=='cd.iteminfo.declared-v1' for value in compiled):
        from cdmw.domain.new_item.iteminfo_overrides import compose_mixed_assignments
        return compose_mixed_assignments(source_rows,compiled,stop_event=stop_event)
    return _compose_legacy_assignments(source_rows,compiled,stop_event=stop_event)
