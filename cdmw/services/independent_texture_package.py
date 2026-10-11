"""Witnessed existing-texture replacement; no registry edits or item allocation."""
from __future__ import annotations

import io
from pathlib import Path
import re
import struct

from cdmw.core.dds_native import inspect_dds_native
from cdmw.core.dds_resource_limits import DDS_MAX_DECODED_BYTES, checked_allocation_size
from cdmw.core.pathc_format import dds_shape, encode_pathc, validate_dds_payload
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import IndependentItemError, IndependentItemPackage

MAX_TEXTURE_REPLACEMENTS = 128
_HASH = re.compile(r'[0-9a-f]{64}\Z')


def validated_texture(data, *, expected_header_digest=None, stop_event=None):
    """Validate the complete raw layout and actually decode every supported mip."""
    from PIL import Image
    from cdmw.services.independent_item_package import MAX_BLOB, digest
    if not isinstance(data, bytes) or len(data) > MAX_BLOB:
        raise IndependentItemError('A texture resource exceeds the package size limit.')
    raise_if_cancelled(stop_event)
    try:
        descriptor = validate_dds_payload(data)
        if expected_header_digest is not None and digest(descriptor.header) != expected_header_digest:
            raise ValueError('The replacement texture descriptor differs from its witnessed source.')
        info = inspect_dds_native(data)
        if not info.supported_compressed or len(info.mip_levels) != len(descriptor.mip_bytes):
            raise ValueError('The texture codec or mip layout is unsupported.')
        decoded_total = sum(checked_allocation_size(mip.width, mip.height, 4,
            max_bytes=DDS_MAX_DECODED_BYTES, label='Decoded texture') for mip in info.mip_levels)
        if decoded_total > DDS_MAX_DECODED_BYTES:
            raise ValueError('The decoded texture mip chain exceeds its resource limit.')
        for mip in info.mip_levels:
            raise_if_cancelled(stop_event)
            # A one-mip view lets the existing decoder inspect every original
            # surface. These temporary header values never become game output.
            header = bytearray(descriptor.header)
            struct.pack_into('<II', header, 12, mip.height, mip.width)
            struct.pack_into('<I', header, 20, mip.byte_count)
            struct.pack_into('<I', header, 28, 1)
            with Image.open(io.BytesIO(bytes(header) + data[mip.offset:mip.offset + mip.byte_count])) as image:
                if image.size != (mip.width, mip.height):
                    raise ValueError('The decoded texture dimensions disagree with its descriptor.')
                image.load()
            raise_if_cancelled(stop_event)
    except (ValueError, OSError, NotImplementedError, struct.error) as exc:
        raise IndependentItemError(f'The complete DDS texture could not be decoded: {exc}') from exc
    return descriptor


def texture_modules(package):
    if isinstance(package, IndependentItemPackage):
        return ()
    return tuple(module for module in package.manifest['modules'] if module['type'] == 'texture.replace')


def texture_resource_keys(package):
    return {row['replacement'] for module in texture_modules(package)
            for row in module['data']['replacements']}


def read_texture_modules(meta, blobs, *, stop_event=None):
    """Validate closed module fields and the resources they actually own."""
    from cdmw.services.independent_item_package import MAX_BLOB, MAX_TOTAL, digest, virtual_path
    paths, used, descriptors, registry_hashes = set(), set(), {}, set()
    logical_size = 0
    for module in meta['modules']:
        if module['type'] != 'texture.replace':
            continue
        data = module['data']
        if (not isinstance(data, dict) or set(data) != {'registry_sha256', 'replacements'}
                or not isinstance(data['registry_sha256'], str) or not _HASH.fullmatch(data['registry_sha256'])
                or not isinstance(data['replacements'], list) or not data['replacements']):
            raise IndependentItemError('Invalid existing-texture replacement module.')
        registry_hashes.add(data['registry_sha256'])
        if len(registry_hashes) != 1:
            raise IndependentItemError('Texture modules require contradictory registry witnesses.')
        for row in data['replacements']:
            raise_if_cancelled(stop_event)
            if not isinstance(row, dict) or set(row) != {
                    'path', 'source_sha256', 'source_size', 'replacement', 'descriptor_sha256'}:
                raise IndependentItemError('Invalid existing-texture replacement fields.')
            path = virtual_path(row['path'])
            if not path.endswith('.dds') or path in paths:
                raise IndependentItemError(f'A duplicate or non-DDS texture target is unsupported: {path}.')
            paths.add(path)
            if len(paths) > MAX_TEXTURE_REPLACEMENTS:
                raise IndependentItemError('The texture replacement count limit is exhausted.')
            if any(not isinstance(row[key], str) or not _HASH.fullmatch(row[key])
                   for key in ('source_sha256', 'replacement', 'descriptor_sha256')):
                raise IndependentItemError('Invalid texture source, descriptor or replacement digest.')
            if type(row['source_size']) is not int or not 128 <= row['source_size'] <= MAX_BLOB:
                raise IndependentItemError('Invalid witnessed texture source size.')
            if meta['dependencies'].get(path) != row['source_sha256']:
                raise IndependentItemError('A texture replacement requires its exact source dependency.')
            key = row['replacement']
            if key not in blobs:
                raise IndependentItemError('A required texture replacement resource is missing.')
            used.add(key)
            logical_size += len(blobs[key])
            if logical_size > MAX_TOTAL:
                raise IndependentItemError('The logical texture replacement size limit is exhausted.')
            if key not in descriptors:
                descriptors[key] = validated_texture(blobs[key],
                    expected_header_digest=row['descriptor_sha256'], stop_event=stop_event)
            if digest(descriptors[key].header) != row['descriptor_sha256']:
                raise IndependentItemError('The replacement texture descriptor differs from its witnessed source.')
    return used


def package_texture_requirements(package):
    return [{'owner': f'{package.identity}/{module["id"]}', 'path': row['path'], 'sha256': row['replacement']}
            for module in texture_modules(package) for row in module['data']['replacements']]


def _registry_witness(snapshot, stop_event):
    from cdmw.services.independent_item_package import digest
    if snapshot.pathc is None or snapshot.provenance is None or not snapshot.pathc_source_digest:
        raise IndependentItemError('Texture replacement requires a verified original texture registry.')
    root = Path(snapshot.iteminfo.payload_entry.pamt_path).resolve().parent.parent
    path = root / 'meta/0.pathc'
    if path.is_symlink() or not path.is_file():
        raise IndependentItemError('The witnessed texture registry is missing or linked.')
    snapshot.provenance.pin_index(path, snapshot.pathc_source_digest, stop_event)
    return root, digest(encode_pathc(snapshot.pathc))


def _source_texture(snapshot, path, root, stop_event):
    from cdmw.services.independent_item_package import digest
    if not snapshot.has_entry(path):
        raise IndependentItemError(f'The texture target is not an existing shipped resource: {path}.')
    entry = snapshot.entry(path)
    archive = Path(entry.pamt_path).resolve()
    group = archive.parent.name
    if (archive.parent.parent != root or len(group) != 4 or not group.isascii()
            or not group.isdigit() or int(group) >= 36):
        raise IndependentItemError(f'Texture replacement requires a witnessed shipped target: {path}.')
    original = snapshot.payload(path)
    descriptor = validated_texture(original, stop_event=stop_event)
    registered = snapshot.pathc.find(path)
    if registered is None or not registered.is_direct:
        raise IndependentItemError(f'The texture target has no supported direct registry entry: {path}.')
    if dds_shape(snapshot.pathc.dds_header_for(registered)) != dds_shape(descriptor.header):
        raise IndependentItemError(f'The source texture descriptor disagrees with its registry: {path}.')
    if registered.block_infos != descriptor.block_infos:
        raise IndependentItemError(f'The texture registry uses an unsupported mip storage layout: {path}.')
    return entry, original, descriptor, digest(original)


def lower_texture_operations(package, snapshot, changes, *, stop_event=None):
    modules = texture_modules(package)
    if not modules:
        return changes
    from cdmw.services.independent_item_package import digest
    root, registry_hash = _registry_witness(snapshot, stop_event)
    result = dict(changes)
    for module in modules:
        if module['data']['registry_sha256'] != registry_hash:
            raise IndependentItemError('The texture package requires a different original texture registry.')
        for row in module['data']['replacements']:
            raise_if_cancelled(stop_event)
            path = row['path']
            entry, original, descriptor, checksum = _source_texture(snapshot, path, root, stop_event)
            if checksum != row['source_sha256'] or len(original) != row['source_size']:
                raise IndependentItemError(f'The witnessed texture source changed: {path}.')
            if digest(descriptor.header) != row['descriptor_sha256']:
                raise IndependentItemError(f'The witnessed texture descriptor changed: {path}.')
            replacement = package.blobs[row['replacement']]
            if validated_texture(replacement, stop_event=stop_event).header != descriptor.header:
                raise IndependentItemError(f'The replacement must retain the complete source DDS descriptor: {path}.')
            change = {'before': original, 'after': replacement, 'flags': entry.flags, 'meta': False}
            if path in result and result[path] != change:
                raise IndependentItemError(f'The package contains contradictory writes to its texture target: {path}.')
            result[path] = change
    return result


def from_texture_replacements(snapshot, identity, replacements, *, title='Texture replacements',
                              release='1', stop_event=None):
    """Author against the witnessed baseline; the caller retains its source guard."""
    from cdmw.services.independent_item_package import FORMAT, MAX_BLOB, MAX_TOTAL, digest, virtual_path
    from cdmw.services.independent_mod_package import read_v2
    if not isinstance(replacements, dict) or not 1 <= len(replacements) <= MAX_TEXTURE_REPLACEMENTS:
        raise IndependentItemError('Select between one and 128 existing texture replacements.')
    logical_size = 0
    for path, replacement in replacements.items():
        raise_if_cancelled(stop_event)
        virtual_path(path)
        if not isinstance(replacement, (bytes, bytearray)) or len(replacement) > MAX_BLOB:
            raise IndependentItemError('A texture replacement must be bounded DDS bytes.')
        logical_size += len(replacement)
        if logical_size > MAX_TOTAL:
            raise IndependentItemError('The logical texture replacement size limit is exhausted.')
    root, registry_hash = _registry_witness(snapshot, stop_event)
    rows, blobs, dependencies = [], {}, {}
    for path, replacement in replacements.items():
        path = virtual_path(path)
        if not path.endswith('.dds'):
            raise IndependentItemError('Texture replacement targets must be existing DDS paths.')
        entry, original, descriptor, checksum = _source_texture(snapshot, path, root, stop_event)
        replacement = bytes(replacement)
        replacement_descriptor = validated_texture(replacement, stop_event=stop_event)
        if replacement_descriptor.header != descriptor.header:
            raise IndependentItemError(f'The replacement must retain the complete source DDS descriptor: {path}.')
        key = digest(replacement)
        blobs[key] = replacement
        dependencies[path] = checksum
        rows.append({'path': path, 'source_sha256': checksum, 'source_size': len(original),
                     'replacement': key, 'descriptor_sha256': digest(descriptor.header)})
    package = read_v2({'format': FORMAT, 'version': 2, 'identity': identity, 'title': title,
        'release': release, 'requires': {'texture.replace': 1},
        'modules': [{'id': 'textures', 'type': 'texture.replace', 'version': 1, 'required': True,
                     'data': {'registry_sha256': registry_hash, 'replacements': rows}}],
        'dependencies': dependencies, 'blobs': {key: len(data) for key, data in sorted(blobs.items())},
        'provenance': None, 'metadata': {}}, blobs, stop_event=stop_event)
    lower_texture_operations(package, snapshot, {}, stop_event=stop_event)
    snapshot.provenance.capture().validate(stop_event)
    return package
