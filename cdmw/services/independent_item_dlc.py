"""Whether an item package depends on the DLC installed beside the game.

The DLC installs separately. Its table layers (`storeinfo.dlc_01` and so on) replace
the base rows they share a key with, including ItemGroup_Main and most shops, so a
package planned with the DLC reads those layers and would pin them. Whole-file pins
would then tie nearly every package to the DLC.

A package's change to shared tables is additive: audit_plan allows new rows and lines
or members added to existing shops and groups. Adding the same member to a group is
the same change on the base copy and on the DLC's copy. So the recipe is planned twice
from one allocation, with and without the DLC, and the two plans are compared:

- every row either plan adds is byte-identical;
- every existing row either plan changes gains the same shop lines or group members
  and keeps its other fields, whichever copy holds it;
- every other file either plan writes is byte-identical;
- every file read that is not a DLC layer has the same bytes.

When they agree, the DLC changes nothing the package makes: it keeps base-only pins
and installs on games with and without the DLC. Otherwise it keeps the DLC's pins.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from cdmw.domain.archives.overlay_merge import _table
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.independent import IdentityBindings, IndependentItemError
from cdmw.services.independent_item_package import (
    _is_dlc_folder, dlc_content, from_plan, recipe_plan, shipped_group, stock_snapshot,
)


def _written(plan):
    files = {request.entry.path.lower(): bytes(request.payload_data) for request in plan.patches}
    files.update((request.path.lower(), bytes(request.payload_data)) for request in plan.additions)
    files.update((write.path.lower(), bytes(write.payload_data)) for write in plan.meta_files)
    return files


def _read(plan):
    return {row.entry.path.lower(): row.sha256 for row in plan.source_revision.payloads}


def _pairs(plan, view):
    """Each shared table's base pair, then its DLC layers, in the order their rows apply."""
    sources = view.sources.tables if view.sources is not None else {}
    result = {}
    for name in plan.manifest["tables"]:
        stems = sorted(stem for stem in sources if stem == name or (
            stem.startswith(name + ".") and dlc_content((sources[stem][0].path.lower(),))))
        result[name] = [(sources[stem][0].path.lower(), sources[stem][1].path.lower()) for stem in stems]
    return result


def _rows(view, pairs, files):
    """The rows the game reads for each key, with `files` written over the view."""
    rows, layout = {}, None
    for body, header in pairs:
        table, records = _table(files[body] if body in files else view.payload(body),
                                files[header] if header in files else view.payload(header))
        if layout is None:
            layout = ('compact' if table.key_layout == 'named'
                      else 'current' if body.endswith('.staticinfobody') else 'legacy')
        rows.update((int.from_bytes(key, 'little'), raw) for key, raw in records)
    return rows, layout


def _store_change(before, after, layout):
    from cdmw.core.storeinfo_compact import encode_compact_stock
    from cdmw.core.storeinfo_table import encode_store_row, parse_store_row
    rows = [parse_store_row(raw, layout=layout) for raw in (before, after)]
    shapes = [encode_store_row(replace(row, entries=(), buyable_count=0, sellable_count=0)) for row in rows]
    # Stock positions and counts are rederived when lines are added, as in the merge.
    lines = [Counter(replace(e, stock_index=0, offset=-1, end=-1,
                             compact_raw=encode_compact_stock(replace(e, stock_index=0)) if e.compact_raw else b'')
                     for e in row.entries) for row in rows]
    if shapes[0] != shapes[1] or lines[0] - lines[1]:
        return None
    return lines[1] - lines[0]


def _group_change(before, after):
    from cdmw.core.itemgroupinfo_table import encode_item_group_row, parse_item_group_row
    rows = [parse_item_group_row(raw) for raw in (before, after)]
    shapes = [encode_item_group_row(replace(row, members=(), subgroups=())) if row.layout == 'compact'
              else (row.prefix, row.tail) for row in rows]
    members, subgroups = ([Counter(getattr(row, name)) for row in rows] for name in ('members', 'subgroups'))
    if shapes[0] != shapes[1] or members[0] - members[1] or subgroups[0] - subgroups[1]:
        return None
    return members[1] - members[0], subgroups[1] - subgroups[0]


def _change(name, before, after, layout):
    """What a plan did to one row: the added row, or what it added to an existing one."""
    if before is None:
        return 'added', after
    if before == after:
        return None
    if after is None:
        return 'removed', None
    change = (_store_change(before, after, layout) if name == 'storeinfo'
              else _group_change(before, after) if name == 'itemgroupinfo' else None)
    return ('extended', change) if change is not None else ('replaced', after)


def dlc_differences(full_plan, base_plan, full_view, base_view):
    """What the DLC changes in a plan, as short descriptions; empty when nothing.

    `full_plan` and `base_plan` plan one allocated item with and without the DLC,
    on `full_view` and `base_view`.
    """
    differences = []
    written = {'full': _written(full_plan), 'base': _written(base_plan)}
    tables = {'full': _pairs(full_plan, full_view), 'base': _pairs(base_plan, base_view)}
    table_files = {path for pairs in (*tables['full'].values(), *tables['base'].values())
                   for pair in pairs for path in pair}
    for name in sorted(set(tables['full']) | set(tables['base'])):
        changes = {}
        for side, view in (('full', full_view), ('base', base_view)):
            pairs = tables[side].get(name, ())
            before, layout = _rows(view, pairs, {})
            after, _ = _rows(view, pairs, written[side])
            changes[side] = {key: change for key in set(before) | set(after)
                             if (change := _change(name, before.get(key), after.get(key), layout)) is not None}
        for key in sorted(set(changes['full']) | set(changes['base'])):
            if changes['full'].get(key) != changes['base'].get(key):
                differences.append(f'{name} record {key}')
    for path in sorted((set(written['full']) | set(written['base'])) - table_files):
        if written['full'].get(path) != written['base'].get(path):
            differences.append(path)
    reads = _read(base_plan)
    for path, checksum in sorted(_read(full_plan).items()):
        if not dlc_content((path,)) and reads.get(path) != checksum:
            differences.append(f'{path} (read)')
    return tuple(differences)


def game_root(plan):
    """The game folder whose base groups `plan` read."""
    for row in plan.source_revision.payloads:
        group = Path(row.entry.pamt_path).parent
        if shipped_group(group / '0.pamt') and not _is_dlc_folder(group.parent):
            return group.parent
    raise IndependentItemError('The plan read no shipped game files.')


def portable_package(package, root, *, service=None, read_entry=None, stop_event=None, on_log=None):
    """`package` with base-only pins when the DLC changes nothing it makes.

    Returns the package and what the DLC changes. A package that pins no DLC file, or
    one the DLC does change, is returned as it is.
    """
    content = ', '.join(dlc_content(package.dependencies))
    if not content:
        return package, ()
    def log(message):
        if on_log is not None:
            on_log(message)
    log(f'Checking whether the item depends on {content}...')
    arguments = dict(service=service, read_entry=read_entry, stop_event=stop_event, on_log=on_log)
    bindings = IdentityBindings(package.identity)
    try:
        full = recipe_plan(package, stock_snapshot(root, **arguments), bindings=bindings, stop_event=stop_event)
        try:
            base = recipe_plan(package, stock_snapshot(root, include_dlc=False, **arguments),
                               bindings=deepcopy(bindings), allocated=full.allocated, icon=full.icon,
                               stop_event=stop_event)
        except RunCancelled:
            raise
        except Exception as error:  # A DLC template, shop or group has no base copy to plan with.
            differences = (f'the item cannot be made without it ({error})',)
        else:
            differences = dlc_differences(full.plan, base.plan, full.view, base.view)
    except IndependentItemError as error:  # Not an item recipe: its pins stay as written.
        differences = (str(error),)
    if differences:
        shown = ', '.join(differences[:4]) + (f' and {len(differences) - 4} more' if len(differences) > 4 else '')
        log(f'The package needs {content}, which changes what it makes: {shown}.')
        return package, differences
    log(f'{content} changes nothing the item makes, so the package works on games with and without it.')
    return from_plan(base.plan, package.identity, title=package.title, stop_event=stop_event), ()
