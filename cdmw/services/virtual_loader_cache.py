"""Reuse a verified private generation after fresh input resolution.

The descriptor is only a lookup hint. The existing profile file-hash ledger is
prior-builder provenance, as for launch. Capturing and hashing those exact files
preserves the prior checksum chain; it does not recompute the PAZ checksum. A
reused processed span must decode to the current raw resource hash. Nothing here
writes to the installation or makes a source-file hash reusable.
"""
import hashlib
import re
import struct

from cdmw.core.archive_format import calculate_pa_checksum, parse_archive_pamt_bytes
from cdmw.core.archive_overlay import PAMT_CONSTANT, PAZ_ALIGNMENT
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, papgt_with_directory
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.domain.new_item.compilation import compiler_stamp, validate_compilation
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services.independent_item_package import canonical, digest, MAX_BLOB, MAX_FILES, MAX_MANIFEST, MAX_TOTAL


FORMAT = 'cdmw_virtual_build_cache_v1'
MAX_CACHE_BYTES = MAX_BLOB
MAX_CACHE_RESOURCES = MAX_FILES
_CHUNK = 1024 * 1024


def processing_stamp():
    # Bump the owning revision whenever its transformation or layout changes.
    # Payload flags and the filename are recorded separately for each resource.
    return {'archive': 1, 'payload': 1, 'mount': 1, 'alignment': PAZ_ALIGNMENT,
            'pamt_constant': PAMT_CONSTANT, 'mount_flags': PAPGT_DEFAULT_FLAGS}


def _input_identity(compilation):
    inputs = validate_compilation(compilation)
    return digest(canonical({key: value for key, value in inputs.items() if key != 'outputs'}))


def _guard_identity(catalogue, inventories):
    return digest(canonical({'catalogue': catalogue, 'inventories': inventories}))


def _key(record):
    return digest(canonical({key: value for key, value in record.items() if key != 'key'}))


def _hash_bytes(raw, stop_event=None):
    result = hashlib.sha256()
    view = memoryview(raw)
    for start in range(0, len(view), _CHUNK):
        raise_if_cancelled(stop_event)
        result.update(view[start:start + _CHUNK])
    raise_if_cancelled(stop_event)
    return result.hexdigest()


def _resource_path(path):
    return (isinstance(path, str) and 0 < len(path) <= 512 and path == path.lower()
            and '\\' not in path and ':' not in path and '\0' not in path
            and all(part not in ('', '.', '..') and part.rstrip(' .') == part for part in path.split('/'))
            and path.split('/')[0] not in ('meta', '.cdmw'))


def make_cache_record(compilation, *, directory, files, flags, mount, pathc,
                      catalogue=(), inventories=(), resource_digests=None, stop_event=None):
    """Describe verified inputs before processing; oversized views use a normal build."""
    if len(files) > MAX_CACHE_RESOURCES or any(not _resource_path(path) for path in files):
        return None
    resources = {}
    for path, raw in sorted(files.items()):
        raise_if_cancelled(stop_event)
        known = resource_digests.digest(raw) if resource_digests is not None else None
        resources[path] = {'sha256': known or _hash_bytes(raw, stop_event), 'size': len(raw), 'flags': flags.get(path, 0)}
    record = {'format': FORMAT, 'processing': processing_stamp(), 'directory': directory,
              'inputs': _input_identity(compilation), 'guards': _guard_identity(catalogue, inventories),
              'metadata': {'mount': _hash_bytes(mount, stop_event),
                           'pathc': _hash_bytes(pathc, stop_event) if pathc is not None else None},
              'resources': resources}
    record['key'] = _key(record)
    # Leave room for the existing compilation, ownership and source records.
    return record if len(canonical(record)) <= MAX_MANIFEST // 2 else None


def validate_cache_record(record, profile):
    """Strict optional profile metadata; outputs remain separately authoritative."""
    def fail():
        raise VirtualLoaderError('Invalid virtual build cache record.')

    def checksum(value):
        return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None

    expected = {'format', 'processing', 'directory', 'inputs', 'guards', 'metadata', 'resources', 'key'}
    if not isinstance(record, dict) or set(record) != expected or record['format'] != FORMAT:
        fail()
    stamp = record['processing']
    if (not isinstance(stamp, dict) or set(stamp) != set(processing_stamp())
            or any(type(value) is not int or not 0 <= value <= 0xffffffff for value in stamp.values())
            or any(stamp[key] < 1 for key in ('archive', 'payload', 'mount', 'alignment'))):
        fail()
    name = record['directory']
    if not isinstance(name, str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}', name) or name.lower() == 'meta':
        fail()
    if any(not checksum(record[key]) for key in ('inputs', 'guards', 'key')):
        fail()
    metadata = record['metadata']
    if (not isinstance(metadata, dict) or set(metadata) != {'mount', 'pathc'}
            or not checksum(metadata['mount']) or metadata['pathc'] is not None and not checksum(metadata['pathc'])):
        fail()
    resources = record['resources']
    if not isinstance(resources, dict) or len(resources) > MAX_CACHE_RESOURCES:
        fail()
    total = 0
    for path, resource in resources.items():
        if (not _resource_path(path) or not isinstance(resource, dict) or set(resource) != {'sha256', 'size', 'flags'}
                or not checksum(resource['sha256']) or type(resource['size']) is not int
                or not 0 <= resource['size'] <= MAX_TOTAL or type(resource['flags']) is not int
                or not 0 <= resource['flags'] <= 0xffff):
            fail()
        total += resource['size']
    if total > MAX_TOTAL or 'compilation' not in profile:
        fail()
    outputs = {'meta/0.papgt'}
    if resources:
        outputs.update((name + '/0.pamt', name + '/0.paz'))
    if metadata['pathc'] is not None:
        outputs.add('meta/0.pathc')
    if (set(profile['files']) != outputs or profile['files'].get('meta/0.pathc') != metadata['pathc']
            or record['inputs'] != _input_identity(profile['compilation'])
            or record['guards'] != _guard_identity(profile.get('catalogue', []), profile['inventories'])
            or record['key'] != _key(record)):
        fail()
    return record


def _captured_file(path, checksum, *, limit, stop_event):
    """Hash the exact bounded bytes retained for use, never a subsequent file read."""
    before = path.stat()
    if before.st_size > limit:
        raise ValueError('Private output exceeds the reusable byte limit.')
    result = hashlib.sha256()
    raw = bytearray()
    with path.open('rb') as source:
        while chunk := source.read(min(_CHUNK, max(1, limit + 1 - len(raw)))):
            raise_if_cancelled(stop_event)
            raw.extend(chunk)
            if len(raw) > limit:
                raise ValueError('Private output grew beyond the reusable byte limit.')
            result.update(chunk)
    after = path.stat()
    if (len(raw) != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or result.hexdigest() != checksum):
        raise ValueError('Private output failed its retained integrity check.')
    raise_if_cancelled(stop_event)
    return bytes(raw)


class VerifiedBuildCache:
    """One preparation's immutable captured output and checked span inventory."""

    def __init__(self, record, output, entries, pamt_checksum):
        self.record = record
        self.output = output
        self.entries = entries
        self.pamt_checksum = pamt_checksum
        self._verified = set()

    def _span(self, path):
        entry = self.entries[path]
        return memoryview(self.output[self.record['directory'] + '/0.paz'])[entry.offset:entry.offset + entry.comp_size]

    def _verify_resource(self, path, witness, stop_event):
        raise_if_cancelled(stop_event)
        if self.record['resources'].get(path) != witness or path not in self.entries or witness['size'] > MAX_BLOB:
            return False
        if path in self._verified:
            return True
        raw = self._span(path)
        flags = witness['flags']
        try:
            if flags >> 4:
                from cdmw.core.archive_format import crypt_chacha20_filename
                raw = crypt_chacha20_filename(raw, path.rsplit('/', 1)[-1])
                raise_if_cancelled(stop_event)
            compression = flags & 15
            if compression == 2:
                from cdmw.core.archive_format import lz4_block
                if lz4_block is None:
                    return False
                raw = lz4_block.decompress(raw, uncompressed_size=witness['size'])
                raise_if_cancelled(stop_event)
            elif compression not in (0, 1):
                return False
            # The writer stores types 0 and 1 verbatim. Do not apply the game's
            # heuristic partial-DDS/PAR decoder to a full payload we generated.
            if len(raw) != witness['size'] or _hash_bytes(raw, stop_event) != witness['sha256']:
                return False
        except RunCancelled:
            raise
        except (ValueError, RuntimeError):
            return False
        self._verified.add(path)
        return True

    def resource_payload(self, path, witness, *, stop_event=None):
        if not self._verify_resource(path, witness, stop_event):
            return None
        return bytes(self._span(path))

    def whole_output(self, record, *, mount, pathc, stop_event=None):
        if record['key'] != self.record['key']:
            return None
        for path, witness in record['resources'].items():
            if not self._verify_resource(path, witness, stop_event):
                return None
        expected_mount = (papgt_with_directory(mount, record['directory'], self.pamt_checksum,
                          flags=PAPGT_DEFAULT_FLAGS, first=True) if self.entries else mount)
        if self.output['meta/0.papgt'] != expected_mount or self.output.get('meta/0.pathc') != pathc:
            return None
        raise_if_cancelled(stop_event)
        return dict(self.output)


def _transformed_match(previous, current):
    # Types 0/1 without encryption already return the raw bytes unchanged. A
    # previous PAZ read, hash and copy cannot save any processing for those files.
    transformed = sum(row['size'] for path, row in current['resources'].items()
                      if 0 < row['size'] <= MAX_BLOB and row == previous['resources'].get(path)
                      and (row['flags'] & 15) in (0, 1, 2)
                      and (row['flags'] >> 4 or (row['flags'] & 15) == 2))
    passthrough = sum(row['size'] for row in previous['resources'].values()
                      if not row['flags'] >> 4 and (row['flags'] & 15) in (0, 1))
    # A tiny transformed record must not trigger capture dominated by large
    # identity DDS spans. These sizes are only conservative cost hints; all
    # source, output and resource checks still run when lookup is admitted.
    return transformed > 0 and transformed >= passthrough


def load_previous_cache(root, profile_bytes, *, current_record, stop_event=None, on_log=None):
    """Read only the active private generation; a miss leaves the normal builder usable.

    The caller must freshly resolve and validate source provenance before lookup.
    A compiler or processing revision change disables even per-resource reuse.
    """
    from cdmw.services.virtual_loader_state import decode, generation_path, target, validate_profile
    if profile_bytes is None:
        return None
    raise_if_cancelled(stop_event)
    try:
        profile = validate_profile(decode(profile_bytes))
        record = profile.get('build_cache')
        if record is None or record['processing'] != processing_stamp() or profile.get('compiler') != compiler_stamp():
            return None
        validate_cache_record(record, profile)
        if record['key'] != current_record['key'] and not _transformed_match(record, current_record):
            return None
        directory = generation_path(root, profile['generation'])
        if _captured_file(target(directory, 'profile.json'), digest(profile_bytes),
                          limit=MAX_MANIFEST, stop_event=stop_event) != profile_bytes:
            return None
        paths = {name: target(directory, 'files/' + name) for name in profile['files']}
        if sum(path.stat().st_size for path in paths.values()) > MAX_CACHE_BYTES:
            return None
        output, remaining = {}, MAX_CACHE_BYTES
        for name, path in paths.items():
            raw = _captured_file(path, profile['files'][name], limit=remaining, stop_event=stop_event)
            output[name] = raw
            remaining -= len(raw)
        if not record['resources']:
            return VerifiedBuildCache(record, output, {}, 0)
        name = record['directory']
        pamt, paz = output[name + '/0.pamt'], output[name + '/0.paz']
        if not 24 <= len(pamt) <= MAX_MANIFEST:
            raise ValueError('Private archive index exceeds the reusable bounds.')
        checksum, count, constant, index, _payload_checksum, size = struct.unpack_from('<IIIIII', pamt)
        if (count != 1 or constant != PAMT_CONSTANT or index != 0 or size != len(paz)
                or checksum != calculate_pa_checksum(pamt[12:])):
            raise ValueError('Private archive index failed validation.')
        entries, end = {}, 0
        for entry in parse_archive_pamt_bytes(pamt, paths[name + '/0.pamt'], stop_event=stop_event):
            raise_if_cancelled(stop_event)
            witness = record['resources'].get(entry.path)
            aligned = (end + PAZ_ALIGNMENT - 1) // PAZ_ALIGNMENT * PAZ_ALIGNMENT
            if (entry.path in entries or witness is None or entry.orig_size != witness['size']
                    or entry.flags != witness['flags'] or entry.paz_index != 0 or entry.offset != aligned
                    or entry.offset + entry.comp_size > len(paz) or any(paz[end:aligned])):
                raise ValueError('Private resource inventory failed validation.')
            entries[entry.path] = entry
            end = entry.offset + entry.comp_size
        if (set(entries) != set(record['resources']) or len(paz) != (end + PAZ_ALIGNMENT - 1) // PAZ_ALIGNMENT * PAZ_ALIGNMENT
                or any(paz[end:])):
            raise ValueError('Private archive payload bounds failed validation.')
        raise_if_cancelled(stop_event)
        return VerifiedBuildCache(record, output, entries, checksum)
    except RunCancelled:
        raise
    except (OSError, ValueError, struct.error) as exc:
        if on_log:
            on_log(f'Prepared-output cache missed; rebuilding the private view: {exc}')
        return None
