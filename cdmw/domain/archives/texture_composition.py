"""Enforce existing-texture final bytes across independently owned layers."""
import hashlib
import re

from cdmw.domain.archives.overlay_merge import OverlayConflict
from cdmw.domain.cancellation import raise_if_cancelled


def texture_requirements(layer):
    value = layer.get('independent_textures', [])
    if not isinstance(value, list) or len(value) > 128:
        raise OverlayConflict('Invalid texture contribution inventory.')
    seen = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {'owner', 'path', 'sha256'}:
            raise OverlayConflict('Invalid texture contribution.')
        owner, path, checksum = row['owner'], row['path'], row['sha256']
        if (not isinstance(owner, str) or not re.fullmatch(r'[0-9a-f]{32}/[a-z][a-z0-9_-]{0,63}', owner)
                or owner.split('/')[0] != layer.get('independent_identity')
                or not isinstance(path, str) or not path.endswith('.dds') or path != path.lower()
                or path.startswith('/') or any(c in path for c in ('\\', ':', '\0'))
                or any(part in ('', '.', '..') or part.rstrip(' .') != part for part in path.split('/'))
                or not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum)
                or (owner, path) in seen):
            raise OverlayConflict('Invalid or duplicate texture requirement.')
        seen.add((owner, path))
    return value


def prepare_textures(layers, *, stop_event=None):
    required = {}
    for layer, changes in layers:
        if not layer['active']:
            continue
        for row in texture_requirements(layer):
            raise_if_cancelled(stop_event, 'Texture composition cancelled.')
            path, checksum = row['path'], row['sha256']
            label = f'{layer["label"]} ({row["owner"]})'
            change = changes.get(path)
            if (change is None or change['before'] is None or not isinstance(change['after'], bytes)
                    or hashlib.sha256(change['after']).hexdigest() != checksum):
                raise OverlayConflict(f'{label}: texture journal differs from its declared requirement: {path}.')
            prior = required.setdefault(path, (checksum, []))
            if prior[0] != checksum:
                raise OverlayConflict(f'Texture conflict at {path}: {"; ".join(prior[1])}; {label} '
                                      'require different final bytes.')
            prior[1].append(label)
    # Untyped journals cannot override even a source-equal typed requirement.
    for layer, changes in layers:
        if not layer['active']:
            continue
        for path, (checksum, owners) in required.items():
            change = changes.get(path)
            if change is None or change['after'] == change['before']:
                continue
            raise_if_cancelled(stop_event, 'Texture composition cancelled.')
            if change['after'] is None or hashlib.sha256(change['after']).hexdigest() != checksum:
                raise OverlayConflict(f'Texture conflict at {path}: {"; ".join(owners)}; {layer["label"]} '
                                      'require different final bytes.')
    return required


def finish_textures(current, required, *, stop_event=None):
    for path, (checksum, owners) in required.items():
        raise_if_cancelled(stop_event, 'Texture composition cancelled.')
        if current.get(path) is None or hashlib.sha256(current[path]).hexdigest() != checksum:
            raise OverlayConflict(f'Texture conflict at {path}: {"; ".join(owners)}; '
                                  'the composed output differs from the required bytes.')
    return current


def required_texture_files(layers):
    """Keep explicit source-equal owners represented in every archive output."""
    return {row['path'] for layer, _ in layers if layer['active'] for row in texture_requirements(layer)}
