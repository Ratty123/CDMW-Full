"""Typed whole-field stock replacements with exact source preconditions.

Every selector names an application-owned complete field. No byte offsets or
package-provided layouts are accepted. Existing item.fields@1 stays frozen.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_declared_fields import field_root, read_field, write_field, validate_field_value
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.iteminfo_operations import FieldAssignment, CompiledAssignment, ItemFieldConflict, MAX_OPERATIONS


ADAPTER='cd.iteminfo.declared-v1'


@dataclass(frozen=True)
class DeclaredAssignment(FieldAssignment):
    expect: object
    value: object


def decode_declared_assignment(owner,raw):
    if (not isinstance(raw,dict) or set(raw)!={'id','kind','target','field','value_type','expect','value','precondition_base','source_row'}
            or raw['kind']!='field.replace' or raw['value_type']!='declared' or raw['precondition_base']!='source'):
        raise IndependentItemError('Unsupported declared ItemInfo operation.')
    if not isinstance(owner,str) or not 1<=len(owner)<=256 or '\0' in owner: raise IndependentItemError('Invalid operation owner.')
    if type(raw['id']) is not str or not re.fullmatch('[a-z][a-z0-9_-]{0,63}',raw['id']): raise IndependentItemError('Invalid operation identity.')
    target=raw['target']; selector=raw['field']
    if (not isinstance(target,dict) or set(target)!={'adapter','table','key'} or target['adapter']!=ADAPTER
            or target['table']!='ItemInfo' or type(target['key']) is not int or not 1<=target['key']<=0xffffffff):
        raise IndependentItemError('Unsupported declared ItemInfo target.')
    if not isinstance(selector,dict) or set(selector)!={'family','name'} or any(type(v) is not str for v in selector.values()):
        raise IndependentItemError('Unsupported declared ItemInfo selector.')
    field=(selector['family'],selector['name'])
    try:
        validate_field_value(field,raw['expect']); validate_field_value(field,raw['value'])
    except (ValueError,TypeError) as exc: raise IndependentItemError(str(exc)) from exc
    if type(raw['source_row']) is not str or not re.fullmatch('[0-9a-f]{64}',raw['source_row']):
        raise IndependentItemError('Declared ItemInfo operations require an exact source digest.')
    return DeclaredAssignment(owner,raw['id'],ADAPTER,target['key'],field,raw['source_row'],deepcopy(raw['expect']),deepcopy(raw['value']))


def operation_root(operation):
    return field_root(operation.field) if isinstance(operation,DeclaredAssignment) else (
        '_maxStackCount' if operation.field==('max_stack_count',) else '_enchantDataList')


def compile_mixed_assignments(contributions,source_rows,*,protected=None,stop_event=None):
    from cdmw.domain.new_item.iteminfo_operations import _compile_legacy_assignments, decode_assignment, _row, _field
    protected=protected or {}; compiled=[]; identities=set(); legacy=[]; replacements={}
    for owner,operations in contributions:
        if not isinstance(operations,(list,tuple)) or not operations: raise IndependentItemError('Empty ItemInfo contribution.')
        old=[]
        for raw in operations:
            raise_if_cancelled(stop_event)
            operation=decode_assignment(owner,raw); identity=(owner,operation.identity)
            if identity in identities: raise IndependentItemError('Duplicate ItemInfo operation identity.')
            identities.add(identity)
            if len(identities)>MAX_OPERATIONS: raise IndependentItemError('The ItemInfo operation budget is exhausted.')
            if not isinstance(operation,DeclaredAssignment): old.append(raw); continue
            source=source_rows.get(operation.record)
            if source is None or hashlib.sha256(source).hexdigest()!=operation.source_digest: raise IndependentItemError('The declared ItemInfo source row changed.')
            layout=read_item_layout(source)
            if layout.integer('_key')!=operation.record or layout.integer('_isBlocked')!=0: raise IndependentItemError('Unsupported declared ItemInfo source identity.')
            actual=read_field(source,operation.field)
            if actual!=operation.expect: raise IndependentItemError('The declared ItemInfo source value changed.')
            output=write_field(source,operation.field,operation.value); root=field_root(operation.field)
            if operation.field in (('text','name'),('text','description')):
                # Existing table consumers require the primary text's retained
                # row namespace. Other-item aliases must not produce a package
                # that this same reader cannot reconstruct.
                from cdmw.core.iteminfo_row import parse_iteminfo_row
                parse_iteminfo_row(output,structured=True)
            data=read_item_layout(output).data(root); previous=replacements.get((operation.record,root))
            if previous and previous[1]!=data: raise ItemFieldConflict(operation,previous[0].label,'opposing complete-field replacements.')
            replacements[(operation.record,root)]=(operation,data,output)
            if operation.record in protected and output!=source:
                raise ItemFieldConflict(operation,', '.join(protected[operation.record]),'a legacy package requires this complete record unchanged.')
            compiled.append(CompiledAssignment(operation,-1,(('source','ItemInfo',operation.record,operation.source_digest),),
                (('ItemInfo',operation.record,root),),('identity retained','unassigned complete fields preserved','source-based precondition')))
        if old: legacy.append((owner,old))
    old_compiled=_compile_legacy_assignments(legacy,source_rows,protected=protected,stop_event=stop_event)
    for value in old_compiled:
        operation=value.operation; replacement=replacements.get((operation.record,operation_root(operation)))
        if replacement is not None:
            try: actual,_offset=_field(_row(replacement[2],operation.record),operation.field,operation.adapter)
            except ValueError as exc: raise ItemFieldConflict(operation,replacement[0].label,'overlapping layouts cannot be qualified.') from exc
            if actual!=operation.value: raise ItemFieldConflict(operation,replacement[0].label,'opposing legacy and declared assignments.')
    return tuple(old_compiled)+tuple(compiled)


def compose_mixed_assignments(source_rows,compiled,*,stop_event=None):
    from cdmw.domain.new_item.iteminfo_operations import _compose_legacy_assignments, _row, _field
    legacy=[value for value in compiled if not isinstance(value.operation,DeclaredAssignment)]
    result=_compose_legacy_assignments(source_rows,legacy,stop_event=stop_event)
    for value in compiled:
        raise_if_cancelled(stop_event)
        operation=value.operation
        if not isinstance(operation,DeclaredAssignment): continue
        source=source_rows.get(operation.record)
        if source is None or hashlib.sha256(source).hexdigest()!=operation.source_digest: raise IndependentItemError('The compiled declared ItemInfo source changed.')
        result[operation.record]=write_field(result[operation.record],operation.field,operation.value)
    for value in compiled:
        operation=value.operation; output=result[operation.record]
        if isinstance(operation,DeclaredAssignment):
            root=field_root(operation.field)
            expected=write_field(source_rows[operation.record],operation.field,operation.value)
            valid=read_item_layout(output).data(root)==read_item_layout(expected).data(root)
        else:
            valid=_field(_row(output,operation.record),operation.field,operation.adapter)[0]==operation.value
        if not valid: raise IndependentItemError('A composed ItemInfo assignment failed validation.')
    return result
