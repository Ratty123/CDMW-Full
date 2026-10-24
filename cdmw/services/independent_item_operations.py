"""Lower field intent through the existing journal and whole-file compositor."""
from cdmw.domain.archives.iteminfo_composition import rows_of, replace_rows_with_header
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.iteminfo_operations import compile_assignments, compose_assignments
from cdmw.services.independent_mod_package import package_operations
from cdmw.services.independent_item_package import digest


def stock_item_operations(snapshot, spec, *, stop_event=None):
    """Compile the studio's item settings against the actual stock identity.

    Reuse the row editor without invoking allocation, cloning, placement or
    resource authoring. Appearance and new-item names are outside this action.
    """
    from copy import deepcopy
    from dataclasses import replace
    from cdmw.core.item_layout import read_item_layout
    from cdmw.core.iteminfo_declared_fields import FIELDS, DEFINITION_ROOTS, read_field, field_root
    from cdmw.services.new_item_planning import _Planner
    from cdmw.services.new_item_behavior import apply_behavior
    from cdmw.domain.new_item.iteminfo_overrides import ADAPTER
    from cdmw.domain.cancellation import raise_if_cancelled
    source=snapshot.row(spec.template_key)
    if source.is_blocked: raise IndependentItemError('Choose an unblocked stock item.')
    if (spec.max_stack_count is not None and spec.inventory_settings is not None
            and spec.inventory_settings.max_stack_count is not None):
        raise IndependentItemError('Stack count cannot be edited through both legacy and inventory settings.')
    if (spec.behavior_settings is not None and 'drop_defaults' in spec.behavior_settings.fields
            and (spec.socket_items is not None or spec.socket_slots is not None)):
        raise IndependentItemError('Choose either complete drop defaults or the separate socket controls.')
    text=spec.definition_settings.secondary_description if spec.definition_settings is not None else None
    if text is not None and text['texts']:
        raise IndependentItemError('Stock overrides can select existing localization references or clear the secondary description. New localized text requires an independent new item.')
    # These are the existing stock IDs, not temporary new-item allocations.
    editor=_Planner(replace(spec,item_key=source.key),snapshot,None,None,None,stop_event)
    output=editor._apply_row_edits(source.raw)
    if spec.behavior_settings is not None: output=apply_behavior(output,spec.behavior_settings,snapshot,stop_event=stop_event)
    before,after=read_item_layout(source.raw),read_item_layout(output)
    operations=[]; represented=set()
    for selector in (*FIELDS,*(('definition',name) for name in DEFINITION_ROOTS)):
        raise_if_cancelled(stop_event)
        root=field_root(selector)
        if before.data(root)==after.data(root): continue
        represented.add(root)
        operations.append({'id':'edit_'+str(len(operations)), 'kind':'field.replace',
            'target':{'table':'ItemInfo','adapter':ADAPTER,'key':source.key},
            'field':dict(zip(('family','name'),selector)), 'value_type':'declared',
            'expect':deepcopy(read_field(source.raw,selector)), 'value':deepcopy(read_field(output,selector)),
            'precondition_base':'source','source_row':digest(source.raw)})
    if any(before.data(name)!=after.data(name) for name in before.fields if name not in represented):
        raise IndependentItemError('The stock editor changed an unsupported ItemInfo field.')
    if not operations: raise IndependentItemError('Change at least one combat or item setting before writing a stock package.')
    return operations


def lower_field_operations(package, snapshot, changes, *, stop_event=None, _authoring=False):
    contributions = package_operations(package)
    if not contributions:
        return changes
    pair = snapshot.iteminfo
    body, header = pair.payload_entry.path.lower(), pair.header_entry.path.lower()
    original = {path: snapshot.payload(path) for path in (body, header)}
    if any(package.dependencies.get(path) != digest(data) for path, data in original.items()):
        raise IndependentItemError('Typed ItemInfo edits require exact table-body and header dependencies.')
    rows = rows_of(original[body], original[header])
    compiled = compile_assignments([(row['owner'], row['operations']) for row in contributions], rows, stop_event=stop_event)
    changed = compose_assignments(rows, compiled, stop_event=stop_event)
    touched = {item.operation.record for item in compiled}
    declared=[item.operation for item in compiled if item.operation.adapter=='cd.iteminfo.declared-v1']
    if declared:
        # A shared preparation may already have read another package's inputs.
        # Qualify this contribution with its own receipts, then retain its reads
        # on the publication tracker. Never require unrelated package inputs.
        view=snapshot.discovery_view()
        _validate_declared_dependencies(view,changed,declared,stop_event=stop_event)
        revision=view.provenance.capture()
        for witness in revision.payloads:
            path=witness.entry.path.lower()
            if not _authoring and package.dependencies.get(path)!=witness.sha256:
                raise IndependentItemError('The stock override package has an incomplete or changed dependency graph.')
            if digest(snapshot.payload(path))!=witness.sha256:
                raise IndependentItemError('A stock dependency changed during validation.')
        revision.validate(stop_event)
        snapshot.provenance.record_reference_closure(False)
    result = dict(changes)
    for path, entry in ((body, pair.payload_entry), (header, pair.header_entry)):
        result.setdefault(path, {'before': original[path], 'after': original[path], 'flags': entry.flags, 'meta': False})
    payload,directory=replace_rows_with_header(result[body]['after'],result[header]['after'],{key:changed[key] for key in touched})
    result[body]=dict(result[body],after=payload)
    result[header]=dict(result[header],after=directory)
    return result


def _validate_declared_dependencies(snapshot,rows,operations,*,stop_event=None):
    from cdmw.services.new_item_definition import _localization_reference
    from cdmw.services.iteminfo_dependency_graph import validate_item_graph
    from cdmw.core.iteminfo_declared_fields import read_field
    grouped={}
    for operation in operations: grouped.setdefault(operation.record,set()).add(operation.field[0])
    for key,families in grouped.items():
        raw=rows[key]
        if families & {'text','definition'}:
            for name in ('name','description','secondary_description'):
                _localization_reference(snapshot,read_field(raw,('text',name)),stop_event=stop_event)
        validate_item_graph(raw,snapshot,stop_event=stop_event)


def from_iteminfo_operations(snapshot, identity, title, operations, *, release='1', stop_event=None):
    """Author a data-only field package against a verified shipped snapshot."""
    from pathlib import Path
    from cdmw.services.independent_item_package import FORMAT
    from cdmw.services.independent_mod_package import read_v2
    pair = snapshot.iteminfo
    dependencies = {}
    for entry in (pair.payload_entry, pair.header_entry):
        directory = Path(entry.pamt_path).parent.name
        if len(directory) != 4 or not directory.isascii() or not directory.isdigit() or int(directory) >= 36:
            raise IndependentItemError('Field packages must be authored against shipped game tables.')
        dependencies[entry.path.lower()] = digest(snapshot.payload(entry.path))
    package = read_v2({'format': FORMAT, 'version': 2, 'identity': identity, 'title': title, 'release': release,
        'requires': {'item.fields': 1}, 'modules': [{'id': 'edits', 'type': 'item.fields', 'version': 1,
            'required': True, 'data': {'operations': list(operations)}}],
        'dependencies': dependencies, 'blobs': {}, 'provenance': None, 'metadata': {}}, {})
    lower_field_operations(package, snapshot, {}, stop_event=stop_event)
    snapshot.provenance.capture().validate(stop_event)
    return package


def from_declared_iteminfo_operations(snapshot,identity,title,operations,*,release='1',stop_event=None):
    """Author item.overrides@1; preserve v1 field-package bytes and contracts."""
    from pathlib import Path
    from cdmw.services.independent_item_package import FORMAT
    from cdmw.services.independent_mod_package import read_v2
    pair=snapshot.iteminfo
    dependencies={entry.path.lower():digest(snapshot.payload(entry.path)) for entry in (pair.payload_entry,pair.header_entry)}
    manifest={'format':FORMAT,'version':2,'identity':identity,'title':title,'release':release,
        'requires':{'item.overrides':1},'modules':[{'id':'edits','type':'item.overrides','version':1,'required':True,
        'data':{'operations':list(operations)}}],'dependencies':dependencies,'blobs':{},'provenance':None,'metadata':{}}
    package=read_v2(manifest,{})
    lower_field_operations(package,snapshot,{},stop_event=stop_event,_authoring=True)
    revision=snapshot.provenance.capture()
    for witness in revision.payloads:
        folder=Path(witness.entry.pamt_path).parent.name
        if len(folder)!=4 or not folder.isascii() or not folder.isdigit() or int(folder)>=36:
            raise IndependentItemError('Stock overrides require shipped source resources.')
        dependencies[witness.entry.path.lower()]=witness.sha256
    revision.validate(stop_event)
    package=read_v2(manifest,{})
    lower_field_operations(package,snapshot,{},stop_event=stop_event)
    return package
