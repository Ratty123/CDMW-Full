"""Run read-only profile preparation outside the GUI's Python interpreter.

Only a bounded data-only result crosses this private temporary-file protocol.
The parent retains the existing publication, review and cancellation lifecycle.
"""
from pathlib import Path
import re
import signal
import sys
import threading
from tempfile import TemporaryDirectory
from uuid import uuid4

from cdmw.core.common import run_process_with_cancellation
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.domain.virtual_loader import PreparedSnapshot, VirtualLoaderError, VirtualProfile
from cdmw.services.independent_item_package import MAX_MANIFEST, MAX_TOTAL, canonical, digest, virtual_path
from cdmw.services.new_item_provenance import PayloadRevision, SourceRevision
from cdmw.services.virtual_loader_state import PROFILE_PATH, REGISTRY, decode, target, validate_profile

_SCHEMA = 2
_MAX_METADATA = 8 * MAX_MANIFEST
_ENTRY_FIELDS = ('path', 'pamt_path', 'paz_file', 'offset', 'comp_size', 'orig_size', 'flags', 'paz_index')


def _require(condition):
    if not condition:
        raise VirtualLoaderError('Virtual preparation returned an invalid or incomplete result. Prepare again.')


def _read_json(path):
    with path.open('rb') as stream:
        return decode(stream.read(_MAX_METADATA + 1), limit=_MAX_METADATA)


def _worker_command(input_path, output_path):
    command = [sys.executable]
    if not getattr(sys, 'frozen', False):
        command.append(str(Path(__file__).resolve().parents[2] / 'cdmw_app.py'))
    return [*command, '--virtual-profile-worker', '--input', str(input_path), '--output', str(output_path)]


class _Buffers:
    def __init__(self, folder, stop_event):
        self.folder, self.stop = folder, stop_event
        self.total = 0
        self.values = {}

    def _budget(self, size):
        _require(type(size) is int and 0 <= size <= MAX_TOTAL)
        self.total += size
        _require(self.total <= 3 * MAX_TOTAL)
        raise_if_cancelled(self.stop)

    def write(self, data):
        checksum = digest(data)
        if checksum not in self.values:
            self._budget(len(data))
            (self.folder / (checksum + '.bin')).write_bytes(data)
            self.values[checksum] = len(data)
        return [checksum, len(data)]

    def read(self, reference):
        _require(isinstance(reference, list) and len(reference) == 2)
        checksum, size = reference
        _require(isinstance(checksum, str) and re.fullmatch('[0-9a-f]{64}', checksum))
        if checksum not in self.values:
            self._budget(size)
            path = target(self.folder, checksum + '.bin')
            _require(path.stat().st_size == size)
            with path.open('rb') as stream:
                data = stream.read(size + 1)
            _require(len(data) == size and digest(data) == checksum)
            self.values[checksum] = data
        _require(type(size) is int and len(self.values[checksum]) == size)
        raise_if_cancelled(self.stop)
        return self.values[checksum]


def _revision_data(revision):
    rows = []
    indexes = dict(revision.indexes)
    for payload in revision.payloads:
        # These preparations read original archive entries, never prepared models.
        _require(payload.entry.prepared_path is None)
        _require(payload.entry.pamt_path in indexes)
        entry = {key: getattr(payload.entry, key) for key in _ENTRY_FIELDS}
        entry.update(pamt_path=str(entry['pamt_path']), paz_file=str(entry['paz_file']))
        rows.append([entry, payload.sha256])
    return {'files': [(str(path), stamp) for path, stamp in revision.files], 'payloads': rows,
            'indexes': [(str(path), checksum) for path, checksum in revision.indexes]}


def _source_path(value, roots):
    _require(isinstance(value, str) and 0 < len(value) < 32768 and '\0' not in value)
    path = Path(value)
    _require(path.is_absolute() and any(path.resolve().is_relative_to(root) for root in roots))
    return path


def _read_entry(entry):
    from cdmw.core.archive_extraction import read_archive_entry_data
    return read_archive_entry_data(entry)[0]


def _revision(value, roots):
    from cdmw.models import ArchiveEntry
    _require(isinstance(value, dict) and set(value) == {'files', 'payloads', 'indexes'})
    _require(all(isinstance(value[key], list) and len(value[key]) <= 65536 for key in value))
    files, payloads = [], []
    for row in value['files']:
        _require(isinstance(row, list) and len(row) == 2)
        path, stamp = row
        _require(stamp is None or (isinstance(stamp, list) and len(stamp) == 3
                                  and all(type(n) is int and n >= 0 for n in stamp)))
        files.append((_source_path(path, roots), tuple(stamp) if stamp is not None else None))
    pinned_files = dict(files)
    _require(len(pinned_files) == len(files))
    indexes = {}
    for row in value['indexes']:
        _require(isinstance(row, list) and len(row) == 2)
        path, checksum = row
        path = _source_path(path, roots)
        _require(path.suffix.lower() == '.pamt' and path not in indexes and pinned_files.get(path) is not None)
        _require(isinstance(checksum, str) and re.fullmatch('[0-9a-f]{64}', checksum))
        indexes[path] = checksum
    _require(set(indexes) == {path for path in pinned_files if path.suffix.lower() == '.pamt'})
    for row in value['payloads']:
        _require(isinstance(row, list) and len(row) == 2)
        entry, checksum = row
        _require(isinstance(entry, dict) and set(entry) == set(_ENTRY_FIELDS))
        _require(isinstance(checksum, str) and re.fullmatch('[0-9a-f]{64}', checksum))
        virtual_path(entry['path'])
        _require(all(type(entry[key]) is int and 0 <= entry[key] < 2**63 for key in _ENTRY_FIELDS[3:]))
        entry = dict(entry, pamt_path=_source_path(entry['pamt_path'], roots), paz_file=_source_path(entry['paz_file'], roots))
        _require(entry['pamt_path'] in pinned_files and entry['paz_file'] in pinned_files)
        _require(entry['pamt_path'] in indexes)
        payloads.append(PayloadRevision(ArchiveEntry(**entry), checksum))
    return SourceRevision(tuple(payloads), tuple(files), _read_entry, tuple(indexes.items()))


def _write_result(prepared, request, folder, output_path, stop_event):
    buffers = _Buffers(folder, stop_event)
    external = prepared.external.capture()
    result = {'schema': _SCHEMA, 'request': digest(canonical(request)),
              'files': [(p, buffers.write(data)) for p, data in prepared.files],
              'registry': buffers.write(prepared.registry), 'profile': buffers.write(prepared.profile),
              'observed': [(p, None if data is None else buffers.write(data)) for p, data in prepared.observed],
              'source': _revision_data(prepared.source_revision), 'external_source': _revision_data(external.source_revision),
              'archives': external.archives, 'summary': prepared.summary,
              'retained': [(p, buffers.write(data)) for p, data in prepared.retained_packages]}
    data = canonical(result)
    _require(len(data) <= _MAX_METADATA)
    raise_if_cancelled(stop_event)
    # The result marker is the last write. No result is consumed before child exit.
    output_path.write_bytes(data)


def _read_result(request, folder, output_path, stop_event):
    from cdmw.services.independent_item_install import _validate_registry
    from cdmw.services.independent_item_compatibility import ExternalModRevision
    result = _read_json(output_path)
    _require(isinstance(result, dict) and set(result) == {
        'schema', 'request', 'files', 'registry', 'profile', 'observed', 'source', 'external_source', 'archives', 'summary', 'retained'})
    _require(result['schema'] == _SCHEMA and result['request'] == digest(canonical(request)))
    buffers = _Buffers(folder, stop_event)
    registry, profile_bytes = buffers.read(result['registry']), buffers.read(result['profile'])
    _validate_registry(decode(registry))
    profile = validate_profile(decode(profile_bytes))
    _require(profile['packages'] == request['packages'] and profile['mods'] == request['mods'])
    root = Path(request['root'])
    roots = (root, *(Path(path) for path in request['mods']))

    def pairs(rows, limit, nullable=False):
        _require(isinstance(rows, list) and len(rows) <= limit)
        values = []
        for row in rows:
            _require(isinstance(row, list) and len(row) == 2 and isinstance(row[0], str))
            target(folder, row[0])
            values.append((row[0], None if nullable and row[1] is None else buffers.read(row[1])))
        if nullable:
            # Composition pins the active profile both before and during resolve.
            pinned = dict(values)
            _require(all(data == pinned[p] for p, data in values))
        else:
            _require(len({p.casefold() for p, _ in values}) == len(values))
        return tuple(values)

    files = pairs(result['files'], 256)
    _require({p: digest(data) for p, data in files} == profile['files'])
    observed = pairs(result['observed'], 6, nullable=True)
    _require({p for p, _ in observed} == {REGISTRY, PROFILE_PATH, '.cdmw/overlays.json', 'meta/0.papgt', 'meta/0.pathc'})
    retained = pairs(result['retained'], 128)
    _require(all(re.fullmatch(r'[0-9a-f]{32}-[0-9a-f]{64}\.cditem', p) for p, _ in retained))
    archives = result['archives']
    _require(isinstance(archives, list) and len(archives) <= 65536)
    for row in archives:
        _require(isinstance(row, list) and len(row) == 2 and isinstance(row[0], str)
                 and re.fullmatch('[A-Za-z0-9_-]+', row[0]) and isinstance(row[1], list))
        for name in row[1]:
            _require(isinstance(name, str) and Path(name).name == name and name.lower().endswith('.pamt'))
            target(root / row[0], name)
    inventories = tuple((_source_path(p, roots), tuple(tuple(row) for row in rows)) for p, rows in profile['inventories'])
    external = ExternalModRevision(root, _revision(result['external_source'], roots),
                                   tuple((p, tuple(names)) for p, names in archives), inventories)
    revision = _revision(result['source'], roots)
    source_hashes = dict(profile['sources'])
    _require(all(source_hashes.get(str(path)) == checksum
                 for path, checksum in (*revision.indexes, *external.source_revision.indexes)))
    _require(isinstance(result['summary'], list) and len(result['summary']) <= 65536
             and all(isinstance(s, str) for s in result['summary']))
    return PreparedSnapshot(root, profile['generation'], files, registry, profile_bytes, observed,
                            revision, external, tuple(result['summary']), retained)


def prepare_profile_in_subprocess(profile: VirtualProfile, root, *, stop_event=None, on_log=None, on_progress=None):
    """Called from the existing controller worker, with one owned child at a time."""
    raise_if_cancelled(stop_event)
    request = {'schema': _SCHEMA, 'nonce': uuid4().hex, 'root': str(Path(root).resolve()),
               'packages': [str(Path(p).resolve()) for p in profile.packages],
               'mods': [str(Path(p).resolve()) for p in profile.mods]}
    with TemporaryDirectory(prefix='cdmw_virtual_prepare_') as directory:
        folder = Path(directory)
        input_path, output_path = folder / 'request.json', folder / 'result.json'
        input_path.write_bytes(canonical(request))
        position, partial = 0, b''

        def poll():
            nonlocal position, partial
            try:
                with (folder / 'progress.jsonl').open('rb') as stream:
                    stream.seek(position)
                    data = stream.read(65536)
                    position += len(data)
                lines = (partial + data).split(b'\n')
                partial = lines.pop()
                for line in lines:
                    message = decode(line, limit=65536)
                    if on_log is not None and isinstance(message, str):
                        on_log(message)
                    elif (on_progress is not None and isinstance(message, dict)
                          and set(message) == {'current', 'total', 'detail'}
                          and type(message['current']) is int and type(message['total']) is int
                          and 0 <= message['current'] <= message['total'] == 100
                          and isinstance(message['detail'], str)):
                        on_progress(message['current'], 100, message['detail'][:16000])
            except Exception:
                # Advisory progress must never strand a running owned child.
                partial = b''

        code, stdout, stderr = run_process_with_cancellation(
            _worker_command(input_path, output_path), stop_event=stop_event,
            on_poll=poll, timeout_seconds=3600, background=True)
        raise_if_cancelled(stop_event)
        if code:
            raise VirtualLoaderError((stderr or stdout).strip()[-1200:] or f'Virtual preparation failed ({code}).')
        poll()
        if on_progress:
            on_progress(98, 100, 'Checking the prepared result…')
        try:
            result = _read_result(request, folder, output_path, stop_event)
        except (OSError, KeyError, TypeError, IndexError) as exc:
            raise VirtualLoaderError('Virtual preparation returned an incomplete result. Prepare again.') from exc
        raise_if_cancelled(stop_event)
        if on_progress:
            on_progress(100, 100, 'Virtual profile prepared.')
        return result


def run_virtual_profile_worker(input_path, output_path):
    """Internal helper mode: read inputs and private temp files; never publish."""
    from cdmw.services.virtual_loader_composition import prepare_profile
    request = _read_json(input_path)
    _require(isinstance(request, dict) and set(request) == {'schema', 'nonce', 'root', 'packages', 'mods'})
    _require(request['schema'] == _SCHEMA)
    _require(all(isinstance(request[key], list) and len(request[key]) <= 128 for key in ('packages', 'mods')))
    root = Path(request['root']).resolve()
    profile = VirtualProfile(tuple(Path(p) for p in request['packages']), tuple(Path(p) for p in request['mods']))
    stop = threading.Event()
    handlers = {}
    for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
        if hasattr(signal, name):
            number = getattr(signal, name)
            handlers[number] = signal.signal(number, lambda *_: stop.set())
    try:
        with (input_path.parent / 'progress.jsonl').open('ab', buffering=0) as progress:
            def log(message):
                progress.write(canonical(str(message)[:16000]) + b'\n')
            def update(current, total, detail):
                progress.write(canonical({'current': 96 * current // max(1, total), 'total': 100,
                                           'detail': str(detail)[:16000]}) + b'\n')
            prepared = prepare_profile(profile, root, stop_event=stop, on_log=log, on_progress=update)
            progress.write(canonical({'current': 97, 'total': 100, 'detail': 'Transferring the prepared files…'}) + b'\n')
            _write_result(prepared, request, input_path.parent, output_path, stop)
        return 0
    except RunCancelled:
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)
