"""Immutable local observations, separate from save producer or ancestry evidence.

Receipt hashes link recorded observations. They do not authenticate a writer,
establish a save commit, or turn a proposed profile into a producing context.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import re

from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.domain.virtual_save_evidence import checksum, encoded
from cdmw.domain.virtual_save_lineage import SaveSetSnapshot, assess_lineage

FORMAT = 'cdmw_virtual_session_receipt_v1'
MAX_RECORD = 4 * 1024 * 1024
MAX_RECEIPTS = 512
MAX_CHAIN_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_SAVE_BYTES = 4 * 1024 * 1024 * 1024
CLAIMS = {
    'producer': 'unknown', 'produced_context': 'unknown', 'ancestry': 'unknown',
    'requirements_coverage': 'unknown', 'save_compatibility': 'unverified',
}
EVENTS = ('begin', 'backup-verified', 'launch-started', 'runtime-status',
          'terminal', 'failed', 'interrupted', 'operator-capture')
FILE_ERRORS = ('read-failed', 'changed-during-read', 'not-regular-file', 'not-observed')
INDICATORS = ('missing-events', 'second-writer', 'cloud-replaced', 'restored-input',
              'interrupted-write', 'process-identity-mismatch', 'load-failed',
              'unknown-slot-membership')
EVIDENCE_KINDS = ('cdmw-preparation', 'verified-backup', 'local-process-launch',
                  'runtime-status-file', 'local-file-observation', 'operator-report',
                  'cdmw-diagnostic')
_ERROR = 'Invalid or changed session receipt.'
_KEYS = {
    'format', 'attempt', 'sequence', 'previous', 'captured_utc', 'event',
    'proposed', 'backup', 'selected', 'slot_layout_sha256', 'membership_complete',
    'before', 'after', 'process', 'readiness', 'terminal', 'save_attempt',
    'indicators', 'evidence', 'diagnostics', 'claims',
}
_PROPOSED_KEYS = {
    'generation', 'profile_sha256', 'compilation_identity', 'compiler_sha256',
    'executable_sha256', 'game_build_sha256', 'runtime', 'items', 'physical_items',
    'sources_sha256', 'underlay_sha256',
}


def _require(condition):
    if not condition:
        raise VirtualLoaderError(_ERROR)


def _keys(value, expected):
    _require(isinstance(value, dict) and len(value) == len(expected) and set(value) == expected)


def _hash(value, *, nullable=False):
    _require((nullable and value is None)
             or isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None)


def _uuid(value, *, nullable=False):
    _require((nullable and value is None)
             or isinstance(value, str) and re.fullmatch(r'[a-f0-9]{32}', value) is not None)


def _integer(value, low, high):
    _require(type(value) is int and low <= value <= high)


def _enum(value, values):
    _require(isinstance(value, str) and value in values)


def _text(value, limit):
    _require(isinstance(value, str) and len(value) <= limit and '\0' not in value)


def _utc(value):
    _require(isinstance(value, str) and re.fullmatch(
        r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value) is not None)
    try:
        datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError as error:
        raise VirtualLoaderError(_ERROR) from error


def _members(values):
    _require(isinstance(values, list) and len(values) <= MAX_MEMBERS)
    for value in values:
        _hash(value)
    _require(len(values) == len(set(values)))
    return set(values)


def _proposed(value):
    if value is None:
        return
    _keys(value, _PROPOSED_KEYS)
    _uuid(value['generation'])
    for key in ('profile_sha256', 'compilation_identity', 'compiler_sha256',
                'executable_sha256', 'sources_sha256', 'underlay_sha256'):
        _hash(value[key])
    _hash(value['game_build_sha256'], nullable=True)
    _keys(value['runtime'], {'bootstrap', 'loader', 'host'})
    for identity in value['runtime'].values():
        _hash(identity, nullable=True)
    for key, limit in (('items', 128), ('physical_items', MAX_MEMBERS)):
        providers = value[key]
        _require(isinstance(providers, dict) and len(providers) <= limit)
        for identity, provider in providers.items():
            _uuid(identity)
            _keys(provider, {'digest', 'binding_hash'})
            _hash(provider['digest'])
            _hash(provider['binding_hash'])


def _snapshot(value, selected):
    if value is None:
        return
    _keys(value, {'observed_utc', 'inventory_complete', 'files', 'missing', 'errors'})
    _utc(value['observed_utc'])
    _require(type(value['inventory_complete']) is bool)
    files, errors = value['files'], value['errors']
    _require(isinstance(files, dict) and len(files) <= MAX_MEMBERS)
    _require(isinstance(errors, dict) and len(errors) <= MAX_MEMBERS)
    missing = _members(value['missing'])
    total = 0
    for name, row in files.items():
        _hash(name)
        _keys(row, {'size', 'sha256'})
        _integer(row['size'], 0, MAX_SAVE_BYTES)
        _hash(row['sha256'])
        total += row['size']
    _require(total <= MAX_SAVE_BYTES)
    for name, error in errors.items():
        _hash(name)
        _enum(error, FILE_ERRORS)
    observed, unreadable = set(files), set(errors)
    _require(not (observed & missing or observed & unreadable or missing & unreadable))
    _require(missing | unreadable <= selected)
    _require(selected <= observed | missing | unreadable)
    _require(len(observed | missing | unreadable) <= MAX_MEMBERS)


def _save_snapshot(snapshot, selected, layout, membership_complete):
    files = snapshot['files'] if snapshot is not None else {}
    complete = bool(selected) and snapshot is not None and all(name in files for name in selected)
    return SaveSetSnapshot(tuple((name, files[name]['size'], files[name]['sha256'])
                                 for name in selected if name in files),
                           layout, membership_complete and complete)


def snapshot_identity(snapshot, selected, layout=None, membership_complete=False):
    """Fingerprint a fully observed selection; slot knowledge is independent.

    Missing, unreadable or unobserved members return None. A verified backup of
    selected files need not establish which files form an actual game save slot.
    """
    members = _members(selected)
    _hash(layout, nullable=True)
    _require(type(membership_complete) is bool)
    _snapshot(snapshot, members)
    if snapshot is None or not members or not members <= set(snapshot['files']):
        return None
    return _save_snapshot(snapshot, members, layout, membership_complete).identity


def empty_backup():
    return {'status': 'pending', 'backup_id': None, 'manifest_sha256': None, 'save_set_sha256': None}


def empty_process(attempt):
    _uuid(attempt)
    return {'expected_session_token': attempt, 'host_pid': None, 'reported_game_pid': None,
            'reported_state': None, 'birth_sha256': None, 'image_sha256': None,
            'observed_session_token': None, 'identity_evidence_sha256': None}


def _process(value, attempt):
    _keys(value, set(empty_process(attempt)))
    _require(value['expected_session_token'] == attempt)
    for key in ('host_pid', 'reported_game_pid'):
        if value[key] is not None:
            _integer(value[key], 1, 0xffffffff)
    if value['reported_state'] is not None:
        _enum(value['reported_state'], ('starting', 'running', 'tracing', 'stopped', 'blocked'))
    for key in ('birth_sha256', 'image_sha256', 'identity_evidence_sha256'):
        _hash(value[key], nullable=True)
    _uuid(value['observed_session_token'], nullable=True)
    observed = [value[key] for key in ('birth_sha256', 'image_sha256',
                                      'observed_session_token', 'identity_evidence_sha256')]
    _require(all(item is None for item in observed)
             or all(item is not None for item in observed) and value['reported_game_pid'] is not None)
    # A complete declared process observation still supplies no trusted save
    # commit verifier. Disagreements must remain recordable for diagnostics.


def _payload(value):
    _keys(value, _KEYS)
    _require(value['format'] == FORMAT)
    _uuid(value['attempt'])
    _integer(value['sequence'], 0, MAX_RECEIPTS - 1)
    _hash(value['previous'], nullable=True)
    _require((value['sequence'] == 0) == (value['previous'] is None))
    _utc(value['captured_utc'])
    _enum(value['event'], EVENTS)
    _proposed(value['proposed'])
    selected = _members(value['selected'])
    _hash(value['slot_layout_sha256'], nullable=True)
    _require(type(value['membership_complete']) is bool)
    _snapshot(value['before'], selected)
    _snapshot(value['after'], selected)
    backup = value['backup']
    _keys(backup, set(empty_backup()))
    _enum(backup['status'], ('pending', 'verified', 'unknown', 'failed'))
    _uuid(backup['backup_id'], nullable=True)
    _hash(backup['manifest_sha256'], nullable=True)
    _hash(backup['save_set_sha256'], nullable=True)
    if backup['status'] == 'verified':
        _require(all(backup[key] is not None for key in ('backup_id', 'manifest_sha256', 'save_set_sha256')))
        observed = snapshot_identity(value['before'], value['selected'],
                                     value['slot_layout_sha256'], value['membership_complete'])
        _require(observed is not None and backup['save_set_sha256'] == observed)
    _process(value['process'], value['attempt'])
    _enum(value['readiness'], ('unknown', 'waiting', 'reported-ready', 'reported-tracing', 'reported-blocked'))
    _enum(value['terminal'], ('pending', 'stopped', 'blocked', 'failed', 'interrupted', 'unknown'))
    _enum(value['save_attempt'], ('unreported', 'reported-saved', 'reported-failed', 'reported-unknown'))
    indicators = value['indicators']
    _require(isinstance(indicators, list) and len(indicators) <= len(INDICATORS))
    for indicator in indicators:
        _enum(indicator, INDICATORS)
    _require(len(indicators) == len(set(indicators)))
    evidence = value['evidence']
    _require(isinstance(evidence, list) and len(evidence) <= 32)
    for row in evidence:
        _keys(row, {'kind', 'sha256', 'detail'})
        _enum(row['kind'], EVIDENCE_KINDS)
        _hash(row['sha256'], nullable=True)
        _text(row['detail'], 1024)
    diagnostics = value['diagnostics']
    _require(isinstance(diagnostics, list) and len(diagnostics) <= 32)
    for detail in diagnostics:
        _text(detail, 1024)
    _keys(value['claims'], set(CLAIMS))
    _require(value['claims'] == CLAIMS)


def _read_value(data):
    if not isinstance(data, bytes) or len(data) > MAX_RECORD:
        raise VirtualLoaderError('Session receipt exceeds its size limit or is not immutable bytes.')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate session receipt key.')
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=unique)
        _keys(value, _KEYS | {'identity'})
        _hash(value['identity'])
        payload = {key: content for key, content in value.items() if key != 'identity'}
        _payload(payload)
        _require(checksum(encoded(payload)) == value['identity'])
        return value
    except (TypeError, ValueError, RecursionError, OverflowError) as error:
        raise VirtualLoaderError(_ERROR) from error


@dataclass(frozen=True, slots=True)
class SessionReceipt:
    """Canonical bytes prevent mutable dictionaries from changing sealed facts."""

    data: bytes = field(repr=False)
    identity: str = field(init=False)

    def __post_init__(self):
        value = _read_value(self.data)
        object.__setattr__(self, 'data', encoded(value))
        object.__setattr__(self, 'identity', value['identity'])

    def to_dict(self):
        return json.loads(self.data)


def decode_receipt(data):
    return SessionReceipt(data)


def seal_receipt(payload):
    """Seal observations; the digest is integrity evidence, not authentication."""
    try:
        _payload(payload)
        data = encoded(payload)
        _require(len(data) <= MAX_RECORD)
        return SessionReceipt(encoded({**payload, 'identity': checksum(data)}))
    except (TypeError, ValueError, RecursionError, OverflowError) as error:
        raise VirtualLoaderError(_ERROR) from error


def _receipt(value):
    return value if isinstance(value, SessionReceipt) else decode_receipt(value)


def validate_chain(receipts):
    """Validate one complete bounded observation chain, never a save ancestry."""
    result, total, attempt = [], 0, None
    for candidate in receipts:
        _require(len(result) < MAX_RECEIPTS)
        receipt = _receipt(candidate)
        total += len(receipt.data)
        _require(total <= MAX_CHAIN_BYTES)
        value = receipt.to_dict()
        _require(value['sequence'] == len(result))
        if result:
            _require(value['attempt'] == attempt and value['previous'] == result[-1].identity)
        else:
            _require(value['previous'] is None)
            attempt = value['attempt']
        result.append(receipt)
    _require(bool(result))
    return tuple(result)


def _file_effect(value):
    selected, before, after = set(value['selected']), value['before'], value['after']
    changed, unchanged = [], []
    if before is not None and after is not None:
        known_before = set(before['files']) | set(before['missing'])
        known_after = set(after['files']) | set(after['missing'])
        for name in sorted(selected & known_before & known_after):
            destination = unchanged if before['files'].get(name) == after['files'].get(name) else changed
            destination.append(name)
    complete = lambda snapshot: (snapshot is not None and bool(selected)
                                 and selected <= set(snapshot['files']))
    if before is None or after is None or not selected:
        classification = 'unobserved'
    elif after['missing']:
        classification = 'missing'
    elif not complete(before) or not complete(after):
        classification = 'partially-changed' if changed else 'unknown'
    elif not changed:
        classification = 'unchanged'
    else:
        classification = 'changed' if len(changed) == len(selected) else 'partially-changed'
    selected_changed = True if changed else False if len(unchanged) == len(selected) and selected else None
    other_changed = None
    if before is not None and after is not None:
        old = {key: row for key, row in before['files'].items() if key not in selected}
        new = {key: row for key, row in after['files'].items() if key not in selected}
        if before['inventory_complete'] and after['inventory_complete']:
            other_changed = old != new
        elif any(old[key] != new[key] for key in old.keys() & new.keys()):
            other_changed = True
    return {
        'classification': classification, 'selected_bytes_changed': selected_changed,
        'other_files_changed': other_changed, 'changed_members': changed, 'unchanged_members': unchanged,
        'missing_before': sorted(before['missing']) if before is not None else [],
        'missing_after': sorted(after['missing']) if after is not None else [],
        'errors_before': dict(before['errors']) if before is not None else {},
        'errors_after': dict(after['errors']) if after is not None else {},
        'before_complete': complete(before), 'after_complete': complete(after),
        'before_observed_utc': before['observed_utc'] if before is not None else None,
        'after_observed_utc': after['observed_utc'] if after is not None else None,
    }


def _proposal_differences(proposed, target):
    if target is None:
        return []
    if proposed is None:
        return [{'code': 'unknown-proposed-context'}]
    differences = []
    for key in sorted(_PROPOSED_KEYS - {'items', 'physical_items', 'runtime'}):
        if proposed[key] != target[key]:
            differences.append({'code': 'changed-proposed-context', 'field': key,
                                'proposed': proposed[key], 'target': target[key]})
    for key in ('bootstrap', 'loader', 'host'):
        if proposed['runtime'][key] != target['runtime'][key]:
            differences.append({'code': 'changed-proposed-context', 'field': 'runtime.' + key,
                                'proposed': proposed['runtime'][key], 'target': target['runtime'][key]})
    for scope in ('items', 'physical_items'):
        old, new = proposed[scope], target[scope]
        for identity in sorted(old.keys() | new.keys()):
            if identity not in new:
                code = 'missing-proposed-provider'
            elif identity not in old:
                code = 'added-proposed-provider'
            elif old[identity] != new[identity]:
                code = 'changed-proposed-provider'
            else:
                continue
            differences.append({'code': code, 'scope': scope, 'provider': identity,
                                'proposed': old.get(identity), 'target': new.get(identity)})
    return differences


def inspect_receipt(receipt, target=None):
    """Inspect observations and proposal differences without a witness input.

    A trusted save-commit verifier belongs to the separate lineage policy.
    Neither receipt JSON nor this inspection API can provide one.
    """
    receipt = _receipt(receipt)
    _proposed(target)
    value = receipt.to_dict()
    selected = set(value['selected'])
    observation = value['after'] if value['after'] is not None else value['before']
    phase = 'after' if value['after'] is not None else 'before' if value['before'] is not None else 'unobserved'
    snapshot = _save_snapshot(observation, selected, value['slot_layout_sha256'], value['membership_complete'])
    files = observation['files'] if observation is not None else {}
    # The proposed context, receipt parent, backup and process observations are
    # deliberately not passed to the producer/ancestry policy.
    decision = assess_lineage(snapshot, target=None)
    return {
        'format': 'cdmw_virtual_session_receipt_inspection_v1',
        'receipt_identity': receipt.identity, 'attempt': value['attempt'],
        'sequence': value['sequence'], 'previous_receipt': value['previous'],
        'event': value['event'], 'captured_utc': value['captured_utc'],
        'proposed_context': value['proposed'], 'recorded_backup': value['backup'],
        'observed_file_set': {
            'phase': phase, 'sha256': snapshot_identity(observation, value['selected'],
                value['slot_layout_sha256'], value['membership_complete']),
            'observed_utc': observation['observed_utc'] if observation is not None else None,
            'inventory_complete': observation['inventory_complete'] if observation is not None else None,
            'files': {name: files[name] for name in sorted(selected & set(files))},
            'missing_selected_files': sorted(observation['missing']) if observation is not None else [],
            'unreadable_selected_files': dict(observation['errors']) if observation is not None else {},
            'unobserved_selected_files': sorted(selected) if observation is None else [],
            'slot_layout_sha256': snapshot.slot_layout_sha256,
            'membership_complete': snapshot.membership_complete,
        },
        'file_effect': _file_effect(value),
        'readiness': value['readiness'], 'terminal': value['terminal'],
        'save_attempt': value['save_attempt'], 'process': value['process'],
        'indicators': value['indicators'], 'evidence': value['evidence'],
        'diagnostics': value['diagnostics'],
        'proposal_differences': _proposal_differences(value['proposed'], target),
        'producer_witness': None, 'produced_context': None,
        'parent_save_set_sha256': None, 'requirements_coverage': 'unknown',
        'decision': asdict(decision), 'claims': dict(CLAIMS),
    }
