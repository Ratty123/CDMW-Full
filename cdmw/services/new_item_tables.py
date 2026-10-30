"""Source-qualified base and DLC table views for Create New Item."""
from cdmw.core.structured_binary_editor import parse_pabgh_table, table_row_key
from cdmw.core.new_item_record import RecordError
from cdmw.domain.cancellation import raise_if_cancelled


def table_pairs(snapshot, name):
    from cdmw.services.new_item_snapshot import TablePair
    cached = snapshot.metadata_pairs.get(name)
    if cached is not None:
        return cached
    sources = snapshot.sources.tables if snapshot.sources is not None else {}
    stems = sorted(stem for stem in sources if stem == name or stem.startswith(name + '.'))
    pairs = tuple(TablePair(body,head,snapshot.payload(body.path),snapshot.payload(head.path))
                  for stem in stems for body,head in (sources[stem],))
    snapshot.metadata_pairs[name] = pairs
    return pairs


def table_rows(snapshot, name, *, stop_event=None, key_width=None):
    rows, origins = {}, {}
    for pair in table_pairs(snapshot,name):
        table = parse_pabgh_table(pair.header,payload=pair.payload)
        seen = set()
        width = key_width or table.key_width
        for entry,start,end in table.row_spans(len(pair.payload)):
            raise_if_cancelled(stop_event)
            raw = pair.payload[start:end]
            if int.from_bytes(table_row_key(raw,width,table.key_layout),'little') != entry.row_id or entry.row_id in seen:
                raise RecordError(f'{name} has an unqualified row identity.')
            seen.add(entry.row_id)
            if entry.row_id in rows:
                from cdmw.core.new_item_record import named_prefix
                if named_prefix(rows[entry.row_id],width)[1] != named_prefix(raw,width)[1]:
                    raise RecordError(f'{name} has conflicting base/DLC identities for key {entry.row_id}.')
            rows[entry.row_id],origins[entry.row_id] = raw,pair
    snapshot.row_sources[name] = origins
    return rows


def row_pair(snapshot, name, key):
    if name not in snapshot.row_sources:
        table_rows(snapshot,name)
    pair = snapshot.row_sources[name].get(key)
    if pair is None:
        raise RecordError(f'{name} has no source for row {key}.')
    return pair
