"""Verified reference boundaries for resources an independent item adds.

Unchanged game resources remain dependencies. Owned opaque physics and partially
decoded reflection objects are deliberately outside the experimental format.
"""
import xml.etree.ElementTree as ET
import struct

from cdmw.domain.new_item.independent import IndependentItemError


def rename_effect_references(data, renames):
    """Rename complete reflected values and declared header strings only."""
    from cdmw.core.effect_binary import decode_effect_binary, write_value, KIND_STRING
    document = decode_effect_binary(data)
    if not document.walk_complete:
        raise IndependentItemError('The effect reference graph did not decode completely.')
    prefixes = ('emitter/', '/effect/binary__/emitter/', 'effect/binary__/emitter/',
                'fx/materialfx/', 'effect/binary__/releasebin/')
    def changed(text):
        for old, new in renames.items():
            if len(old.encode()) != len(new.encode()):
                raise IndependentItemError('An effect reference requires a fixed-length name.')
            for prefix in prefixes:
                if text == prefix + old:
                    return prefix + new
        return text
    output = bytes(data)
    for value in document.root.all_values():
        if value.kind == KIND_STRING:
            before = str(value.value)
            after = changed(before)
            if after != before:
                output = write_value(output, value, after.encode('utf-8'))
    # Reflection type names and the string pool use declared length-prefixed
    # strings before blob_offset. Check every occurrence against that inventory.
    header_strings = [row.type_name for row in document.types] + list(document.string_pool)
    for before in dict.fromkeys(header_strings):
        after = changed(before)
        if after == before:
            continue
        token = before.encode('utf-8')
        needle = struct.pack('<I', len(token)) + token
        header = data[document.container_offset:document.blob_offset]
        positions, start = [], 0
        while (found := header.find(needle, start)) >= 0:
            positions.append(document.container_offset + found + 4)
            start = found + len(needle)
        if len(positions) != header_strings.count(before):
            raise IndependentItemError('An effect type-name boundary is ambiguous.')
        for offset in positions:
            output = output[:offset] + after.encode('utf-8') + output[offset + len(token):]
    if not decode_effect_binary(output).walk_complete:
        raise IndependentItemError('The renamed effect failed its structural check.')
    return output


def audit_references(plan, snapshot, *, stop_event=None):
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services.independent_item_package import virtual_path
    outputs = {request.path.lower(): bytes(request.payload_data) for request in plan.additions}
    pending, visited = dict(outputs), set()

    def require(raw):
        raise_if_cancelled(stop_event)
        path = str(raw).replace('\\', '/').lower()
        if not path:
            return
        if path.endswith('.effect') and '/' not in path:
            path = 'effect/binary__/releasebin/' + path.split('.')[0] + '.pae'
        path = virtual_path(path)
        if path in outputs or path in visited or path in pending:
            return
        if not snapshot.has_entry(path):
            raise IndependentItemError(f'Unresolved item dependency: {path}')
        # Reading pins the dependency to the exported package's compatibility
        # graph, so another machine cannot silently borrow a modded resource.
        pending[path] = snapshot.payload(path)
        if len(pending) + len(visited) > 4096:
            raise IndependentItemError('The item dependency graph exceeds the supported size.')

    family = snapshot.family(plan.spec.template_key)
    for resource in family.files:
        if resource.exists:
            require(resource.path)
    for part in family.parts:
        if part.record is None:
            raise IndependentItemError(f'The template has an unresolved part binding: {part.stem}')
        require(part.prefab_path)
        if part.record.sockets_path:
            require(part.record.sockets_path)

    from cdmw.core.pappt_format import parse_pappt
    pappt_path = snapshot.pappt_entry.path.lower()
    if pappt_path in plan.loose_files:
        original = snapshot.pappt.index()
        for record in parse_pappt(plan.loose_files[pappt_path]).records:
            if record.stem not in original:
                require(record.prefab_path)
                if record.sockets_path:
                    require(record.sockets_path)

    while pending:
        raise_if_cancelled(stop_event)
        path, data = pending.popitem()
        visited.add(path)
        owned = path in outputs
        if path.endswith('.hkx'):
            if owned:
                raise IndependentItemError('Owned physics files are not yet verified for independent packages. Turn off inherited template physics for the imported model.')
            continue
        if path.endswith('.prefab'):
            from cdmw.core.prefab_binary import decode_prefab_binary
            document = decode_prefab_binary(data)
            if not document.walk_complete or document.inferred_objects or document.blob_offset + document.blob_length != len(data):
                raise IndependentItemError(f'The complete prefab reference layout is unverified: {path}')
            for resource in document.resource_strings():
                require(resource.text)
        elif path.endswith('.pac_xml'):
            try:
                text = data.decode('utf-8-sig')
                if '<!DOCTYPE' in text or '<!ENTITY' in text:
                    raise ValueError('XML entities are unsupported')
                tree = ET.fromstring('<IndependentModel>' + text.lstrip('\ufeff') + '</IndependentModel>')
                if not len(tree) or any(child.tag not in {'SkinnedMeshPropertyCommon', 'ModelPropertyList'} for child in tree):
                    raise ValueError('Unknown model property root')
            except (UnicodeError, ET.ParseError, ValueError) as exc:
                raise IndependentItemError(f'Unverified model property layout: {path}') from exc
            for node in tree.iter():
                if node.tag.startswith('ResourceReferencePath'):
                    if set(node.attrib) - {'Name', '_path'}:
                        raise IndependentItemError(f'Unknown model resource boundary: {path}')
                    require(node.attrib.get('_path', ''))
        elif path.endswith(('.pae', '.paem', '.parg', '.pasg')):
            from cdmw.core.effect_binary import decode_effect_binary
            from cdmw.core.effect_edit import emitter_paths_of, preset_names_of, preset_path
            document = decode_effect_binary(data)
            if not document.walk_complete or document.blob_offset + document.blob_length != len(data):
                raise IndependentItemError(f'The complete effect reference layout is unverified: {path}')
            for resource in (*document.resources(), *emitter_paths_of(document), *(preset_path(kind, name) for kind, name in preset_names_of(document))):
                require(resource)
        elif path.endswith('.pac'):
            if owned:
                from cdmw.modding.mesh_parser import parse_pac
                mesh = parse_pac(data, path)
                if not mesh.submeshes:
                    raise IndependentItemError(f'The owned mesh format is unverified: {path}')
            from cdmw.services.new_item_variants import xml_path
            sidecar = xml_path(path)
            if sidecar in outputs or snapshot.has_entry(sidecar):
                require(sidecar)
        elif path.endswith('.dds'):
            if not data.startswith(b'DDS ') or len(data) < 128:
                raise IndependentItemError(f'The owned texture format is unverified: {path}')
        elif owned:
            raise IndependentItemError(f'Unsupported independent resource format: {path}')
