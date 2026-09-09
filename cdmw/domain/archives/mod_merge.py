"""Composition of the texture registrations owned by exported New Item mods."""
from dataclasses import replace

from cdmw.core.pathc_format import block_infos_for, dds_shape, encode_pathc, parse_pathc, pathc_checksum
from cdmw.domain.archives.overlay_merge import OverlayConflict


def merge_mod_texture_registry(original, current, incoming, owned_paths, payloads):
    base, present, added = map(parse_pathc, (original, current, incoming))
    for field in ("header_size", "reserved", "collisions", "filenames"):
        if getattr(base, field) != getattr(added, field):
            raise OverlayConflict("Unsupported texture registry layout or collision-table changes.")

    def signature(table, entry):
        if entry is None:
            return None
        return (table.headers[entry.header_index] if entry.is_direct else None,
                entry.collision_start, entry.collision_end, entry.block_infos)

    keys = {}
    for path in sorted(owned_paths):
        key = pathc_checksum(path)
        if key in keys and keys[key] != path:
            raise OverlayConflict(f"Texture registry checksum collision: {keys[key]} and {path}.")
        keys[key] = path
    base_entries = {e.checksum: e for e in base.entries}
    if not base_entries.keys() <= {e.checksum for e in added.entries}:
        raise OverlayConflict("Removing existing texture registrations is not supported by mod merge.")
    entries = {e.checksum: e for e in present.entries}
    headers = list(present.headers)
    for entry in added.entries:
        key = entry.checksum
        before = base_entries.get(key)
        if key not in keys:
            if signature(added, entry) != signature(base, before):
                raise OverlayConflict(f"Unrecorded texture registry change at checksum {key:#010x}.")
            continue
        path = keys[key]
        data = payloads.get(path)
        if data is None or not entry.is_direct:
            raise OverlayConflict(f"Missing texture or unsupported collision registration: {path}.")
        if dds_shape(added.dds_header_for(entry)) != dds_shape(data) or entry.block_infos != block_infos_for(data):
            raise OverlayConflict(f"Texture registration does not match its DDS: {path}.")
        existing = entries.get(key)
        if (signature(present, existing) != signature(added, entry)
                and signature(present, existing) != signature(base, before)):
            raise OverlayConflict(f"Conflicting texture registrations: {path}.")
        header = added.headers[entry.header_index]
        if header not in headers:
            headers.append(header)
        entries[key] = replace(entry, header_index=headers.index(header))
    if any(added.find(path) is None for path in owned_paths):
        raise OverlayConflict("A declared texture is absent from the mod's registry.")
    return encode_pathc(replace(present, headers=tuple(headers),
                               entries=tuple(entries[key] for key in sorted(entries))))
