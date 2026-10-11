"""Receipt metadata never substitutes for an independent save-commit verifier."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json

import pytest

from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.domain.virtual_save_evidence import checksum, encoded
from cdmw.domain import virtual_session_receipt as receipts

ATTEMPT = 'a' * 32
PROVIDER = 'b' * 32
FIRST, SECOND = checksum(b'first selected member'), checksum(b'second selected member')
WHEN = '2026-10-11T12:00:00Z'


def proposed_context():
    return {
        'generation': 'c' * 32, 'profile_sha256': checksum(b'profile'),
        'compilation_identity': checksum(b'compilation'), 'compiler_sha256': checksum(b'compiler'),
        'executable_sha256': checksum(b'game executable'), 'game_build_sha256': None,
        'runtime': {'bootstrap': None, 'loader': None, 'host': checksum(b'host')},
        'items': {PROVIDER: {'digest': checksum(b'package'), 'binding_hash': checksum(b'bindings')}},
        'physical_items': {}, 'sources_sha256': checksum(b'sources'), 'underlay_sha256': checksum(b'underlay'),
    }


def observation(files=None, *, missing=(), errors=None, inventory_complete=True):
    return {
        'observed_utc': WHEN, 'inventory_complete': inventory_complete,
        'files': deepcopy(files if files is not None else {
            FIRST: {'size': 3, 'sha256': checksum(b'one')},
            SECOND: {'size': 3, 'sha256': checksum(b'two')},
        }),
        'missing': list(missing), 'errors': dict(errors or {}),
    }


def receipt_payload():
    return {
        'format': receipts.FORMAT, 'attempt': ATTEMPT, 'sequence': 0, 'previous': None,
        'captured_utc': WHEN, 'event': 'begin', 'proposed': proposed_context(),
        'backup': receipts.empty_backup(), 'selected': [], 'slot_layout_sha256': None,
        'membership_complete': False, 'before': None, 'after': None,
        'process': receipts.empty_process(ATTEMPT), 'readiness': 'unknown',
        'terminal': 'pending', 'save_attempt': 'unreported', 'indicators': [],
        'evidence': [], 'diagnostics': [], 'claims': dict(receipts.CLAIMS),
    }


def observed_payload():
    value = receipt_payload()
    value.update(event='terminal', selected=sorted((FIRST, SECOND)), before=observation(), after=observation(),
                 readiness='reported-ready', terminal='stopped', save_attempt='reported-unknown')
    value['backup'] = {
        'status': 'verified', 'backup_id': 'd' * 32, 'manifest_sha256': checksum(b'verified backup manifest'),
        'save_set_sha256': receipts.snapshot_identity(value['before'], value['selected']),
    }
    value['process'].update(host_pid=101, reported_game_pid=202, reported_state='stopped')
    value['evidence'] = [{'kind': 'local-file-observation', 'sha256': checksum(b'capture protocol'),
                          'detail': 'Owned synthetic member observations.'}]
    return value


def reseal_unchecked(value):
    """Corrupt but checksum-consistent input still must pass the closed schema."""
    value = deepcopy(value)
    value.pop('identity', None)
    return encoded({**value, 'identity': checksum(encoded(value))})


def append(previous, **updates):
    value = previous.to_dict()
    value.pop('identity')
    value.update(sequence=value['sequence'] + 1, previous=previous.identity)
    value.update(updates)
    return receipts.seal_receipt(value)


def test_receipt_is_deeply_immutable_canonical_and_detached_from_callers():
    value = observed_payload()
    receipt = receipts.seal_receipt(value)
    original = receipt.data
    value['before']['files'][FIRST]['sha256'] = checksum(b'caller changes input')
    returned = receipt.to_dict()
    returned['after']['files'].clear()
    returned['claims']['producer'] = 'verified'
    assert receipt.data == original
    assert receipt.identity == json.loads(original)['identity']
    assert receipts.decode_receipt(original) == receipt
    noncanonical = json.dumps(json.loads(original), indent=2).encode()
    assert receipts.decode_receipt(noncanonical).data == original
    with pytest.raises(FrozenInstanceError):
        receipt.data = b'changed'
    with pytest.raises(VirtualLoaderError):
        receipts.decode_receipt(bytearray(original))


@pytest.mark.parametrize('change', [
    'format', 'unknown-key', 'claim', 'witness', 'ancestry', 'requirements', 'identity',
    'sequence-bool', 'sequence-limit', 'timestamp', 'selected-duplicate', 'member-count',
    'file-size-bool', 'file-size-negative', 'file-total', 'missing-overlap', 'missing-unselected',
    'missing-unaccounted', 'read-error-code', 'inventory-bool', 'membership-bool',
    'layout', 'backup-id', 'backup-hash', 'backup-missing', 'process-expected-token',
    'process-pid', 'process-partial-identity', 'process-state', 'readiness',
    'terminal', 'save-attempt', 'indicator', 'indicator-duplicate', 'evidence-kind',
    'evidence-keys', 'evidence-count', 'diagnostic-size', 'provider-shape', 'provider-id',
    'runtime-keys',
])
def test_closed_schema_rejects_forged_or_malformed_receipts_even_with_recomputed_hash(change):
    value = observed_payload()
    if change == 'format':
        value['format'] = 'cdmw_virtual_session_receipt_v2'
    elif change == 'unknown-key':
        value['approved'] = True
    elif change == 'claim':
        value['claims']['producer'] = 'verified'
    elif change == 'witness':
        value['witness'] = {'finalized': True, 'events_complete': True}
    elif change == 'ancestry':
        value['claims']['ancestry'] = 'verified'
    elif change == 'requirements':
        value['claims']['requirements_coverage'] = 'complete'
    elif change == 'identity':
        raw = json.loads(reseal_unchecked(value))
        raw['identity'] = checksum(b'wrong identity')
        with pytest.raises(VirtualLoaderError):
            receipts.decode_receipt(encoded(raw))
        return
    elif change == 'sequence-bool':
        value['sequence'] = False
    elif change == 'sequence-limit':
        value.update(sequence=receipts.MAX_RECEIPTS, previous=checksum(b'previous'))
    elif change == 'timestamp':
        value['captured_utc'] = '2026-02-30T12:00:00Z'
    elif change == 'selected-duplicate':
        value['selected'].append(FIRST)
    elif change == 'member-count':
        value['selected'] = [f'{index:064x}' for index in range(receipts.MAX_MEMBERS + 1)]
    elif change == 'file-size-bool':
        value['after']['files'][FIRST]['size'] = True
    elif change == 'file-size-negative':
        value['after']['files'][FIRST]['size'] = -1
    elif change == 'file-total':
        value['after']['files'][FIRST]['size'] = receipts.MAX_SAVE_BYTES
    elif change == 'missing-overlap':
        value['after']['missing'] = [FIRST]
    elif change == 'missing-unselected':
        value['after']['missing'] = [checksum(b'unselected')]
    elif change == 'missing-unaccounted':
        del value['after']['files'][FIRST]
    elif change == 'read-error-code':
        del value['after']['files'][FIRST]
        value['after']['errors'] = {FIRST: 'verified-missing'}
    elif change == 'inventory-bool':
        value['after']['inventory_complete'] = 1
    elif change == 'membership-bool':
        value['membership_complete'] = 1
    elif change == 'layout':
        value['slot_layout_sha256'] = 'guessed format'
    elif change == 'backup-id':
        value['backup']['backup_id'] = '../outside'
    elif change == 'backup-hash':
        value['backup']['save_set_sha256'] = checksum(b'other selected bytes')
    elif change == 'backup-missing':
        del value['before']['files'][FIRST]
        value['before']['missing'] = [FIRST]
    elif change == 'process-expected-token':
        value['process']['expected_session_token'] = 'e' * 32
    elif change == 'process-pid':
        value['process']['reported_game_pid'] = True
    elif change == 'process-partial-identity':
        value['process']['birth_sha256'] = checksum(b'unbound birth')
    elif change == 'process-state':
        value['process']['reported_state'] = 'save-committed'
    elif change == 'readiness':
        value['readiness'] = 'verified-save-ready'
    elif change == 'terminal':
        value['terminal'] = 'safe'
    elif change == 'save-attempt':
        value['save_attempt'] = 'verified-commit'
    elif change == 'indicator':
        value['indicators'] = ['no-foreign-writers-proven']
    elif change == 'indicator-duplicate':
        value['indicators'] = ['missing-events', 'missing-events']
    elif change == 'evidence-kind':
        value['evidence'][0]['kind'] = 'trusted-save-commit'
    elif change == 'evidence-keys':
        value['evidence'][0]['verifier'] = True
    elif change == 'evidence-count':
        value['evidence'] *= 33
    elif change == 'diagnostic-size':
        value['diagnostics'] = ['x' * 1025]
    elif change == 'provider-shape':
        value['proposed']['items'][PROVIDER]['persistence_verified'] = True
    elif change == 'provider-id':
        value['proposed']['items'] = {'guess': value['proposed']['items'][PROVIDER]}
    elif change == 'runtime-keys':
        value['proposed']['runtime']['verifier'] = checksum(b'not a runtime identity')
    with pytest.raises(VirtualLoaderError):
        receipts.decode_receipt(reseal_unchecked(value))
    with pytest.raises(VirtualLoaderError):
        receipts.seal_receipt(value)


def test_duplicate_keys_stale_identity_and_size_limits_cannot_be_read():
    receipt = receipts.seal_receipt(observed_payload())
    with pytest.raises(VirtualLoaderError):
        receipts.decode_receipt(b'{"format":"duplicate",' + receipt.data[1:])
    changed = receipt.to_dict()
    changed['diagnostics'] = ['Changed after sealing']
    with pytest.raises(VirtualLoaderError):
        receipts.decode_receipt(encoded(changed))
    with pytest.raises(VirtualLoaderError, match='size limit'):
        receipts.decode_receipt(receipt.data + b' ' * receipts.MAX_RECORD)


@pytest.mark.parametrize('state', ['none', 'missing', 'read-error', 'complete'])
def test_snapshot_identity_requires_observed_members_not_known_game_slot_layout(state):
    selected = [FIRST, SECOND]
    snapshot = observation()
    if state == 'none':
        snapshot = None
    elif state != 'complete':
        del snapshot['files'][FIRST]
        if state == 'missing':
            snapshot['missing'] = [FIRST]
        else:
            snapshot['errors'] = {FIRST: 'read-failed'}
    result = receipts.snapshot_identity(snapshot, selected)
    assert (result is not None) == (state == 'complete')
    if state == 'complete':
        receipt = receipts.seal_receipt(observed_payload())
        report = receipts.inspect_receipt(receipt)
        assert receipt.to_dict()['backup']['status'] == 'verified'
        assert report['observed_file_set']['membership_complete'] is False
        assert report['observed_file_set']['slot_layout_sha256'] is None
        assert report['decision']['status'] == 'unknown'
        assert 'unknown-slot-membership' in report['decision']['reasons']


@pytest.mark.parametrize('change,classification,bytes_changed', [
    ('unobserved', 'unobserved', None), ('unchanged', 'unchanged', False),
    ('partial', 'partially-changed', True), ('changed', 'changed', True),
    ('missing', 'missing', True), ('all-missing', 'missing', True),
    ('read-error', 'unknown', None), ('partial-error', 'partially-changed', True),
])
@pytest.mark.parametrize('outcome', ['unreported', 'reported-saved', 'reported-failed', 'reported-unknown'])
def test_operator_outcome_process_exit_and_file_effect_remain_separate(change, classification, bytes_changed, outcome):
    value = observed_payload()
    value['save_attempt'] = outcome
    if change == 'unobserved':
        value['after'] = None
    elif change in ('partial', 'changed', 'partial-error'):
        value['after']['files'][FIRST]['sha256'] = checksum(b'changed first')
        if change == 'changed':
            value['after']['files'][SECOND]['sha256'] = checksum(b'changed second')
        elif change == 'partial-error':
            del value['after']['files'][SECOND]
            value['after']['errors'] = {SECOND: 'changed-during-read'}
    elif change in ('missing', 'all-missing', 'read-error'):
        del value['after']['files'][FIRST]
        if change == 'read-error':
            value['after']['errors'] = {FIRST: 'read-failed'}
        else:
            value['after']['missing'] = [FIRST]
            if change == 'all-missing':
                value['after']['files'].clear()
                value['after']['missing'].append(SECOND)
    report = receipts.inspect_receipt(receipts.seal_receipt(value))
    assert report['file_effect']['classification'] == classification
    assert report['file_effect']['selected_bytes_changed'] is bytes_changed
    assert report['save_attempt'] == outcome
    assert report['readiness'] == 'reported-ready' and report['terminal'] == 'stopped'
    assert report['decision']['status'] == 'unknown'
    assert report['decision']['producer_evidence'] == 'unknown'
    assert report['claims'] == receipts.CLAIMS
    assert report['producer_witness'] is None and report['produced_context'] is None
    assert report['parent_save_set_sha256'] is None


@pytest.mark.parametrize('complete', [False, True])
def test_unselected_file_observation_does_not_become_selected_save_or_writer_proof(complete):
    value = observed_payload()
    value['before']['inventory_complete'] = complete
    value['after']['inventory_complete'] = complete
    value['after']['files'][checksum(b'autosave member')] = {'size': 9, 'sha256': checksum(b'autosave bytes')}
    report = receipts.inspect_receipt(receipts.seal_receipt(value))
    assert report['file_effect']['classification'] == 'unchanged'
    assert report['file_effect']['selected_bytes_changed'] is False
    assert report['file_effect']['other_files_changed'] is (True if complete else None)
    assert report['claims']['producer'] == 'unknown'


@pytest.mark.parametrize('indicator', receipts.INDICATORS)
@pytest.mark.parametrize('wrong_process', [False, True])
def test_complete_process_metadata_readiness_backup_and_interference_cannot_mint_producer(indicator, wrong_process):
    value = observed_payload()
    value['membership_complete'], value['slot_layout_sha256'] = True, checksum(b'claimed known slot layout')
    value['backup']['save_set_sha256'] = receipts.snapshot_identity(
        value['before'], value['selected'], value['slot_layout_sha256'], True)
    value['process'].update(
        birth_sha256=checksum(b'other birth' if wrong_process else b'claimed birth'),
        image_sha256=checksum(b'other game image') if wrong_process else value['proposed']['executable_sha256'],
        observed_session_token='f' * 32 if wrong_process else ATTEMPT,
        identity_evidence_sha256=checksum(b'declared observation, not a trusted verifier'),
    )
    value['save_attempt'] = 'reported-saved'
    value['after']['files'][FIRST]['sha256'] = checksum(b'reported managed write')
    value['indicators'] = [indicator]
    report = receipts.inspect_receipt(receipts.seal_receipt(value), target=deepcopy(value['proposed']))
    assert report['proposal_differences'] == []
    assert report['decision']['status'] == 'unknown'
    assert report['decision']['producer_evidence'] == 'unknown'
    assert 'unknown-producer' in report['decision']['reasons']
    assert report['claims']['ancestry'] == 'unknown'


@pytest.mark.parametrize('change,code', [
    ('build', 'changed-proposed-context'), ('runtime', 'changed-proposed-context'),
    ('compiler', 'changed-proposed-context'), ('profile', 'changed-proposed-context'),
    ('missing', 'missing-proposed-provider'), ('content', 'changed-proposed-provider'),
    ('bindings', 'changed-proposed-provider'), ('added', 'added-proposed-provider'),
])
def test_proposal_differences_explain_known_context_changes_without_assuming_produced_context(change, code):
    value = observed_payload()
    target = deepcopy(value['proposed'])
    if change == 'build':
        target['game_build_sha256'] = checksum(b'other build')
    elif change == 'runtime':
        target['runtime']['loader'] = checksum(b'other loader')
    elif change == 'compiler':
        target['compiler_sha256'] = checksum(b'other compiler')
    elif change == 'profile':
        target['profile_sha256'] = checksum(b'other profile')
    elif change == 'missing':
        target['items'].clear()
    elif change in ('content', 'bindings'):
        target['items'][PROVIDER]['digest' if change == 'content' else 'binding_hash'] = checksum(b'changed provider')
    else:
        target['items']['e' * 32] = {'digest': checksum(b'extra'), 'binding_hash': checksum(b'extra bindings')}
    report = receipts.inspect_receipt(receipts.seal_receipt(value), target=target)
    assert any(row['code'] == code for row in report['proposal_differences'])
    assert report['decision']['status'] == 'unknown' and report['decision']['context'] == 'unknown'
    assert report['requirements_coverage'] == 'unknown'


def test_inspection_has_no_json_witness_verifier_or_save_context_inference_parameter():
    receipt = receipts.seal_receipt(observed_payload())
    with pytest.raises(TypeError):
        receipts.inspect_receipt(receipt, witness={'finalized': True})
    with pytest.raises(TypeError):
        receipts.inspect_receipt(receipt, verify_commit=lambda *_: True)
    with pytest.raises(VirtualLoaderError):
        receipts.inspect_receipt(receipt, target={'persistence_sha256': None})
    report = receipts.inspect_receipt(receipt, target=proposed_context())
    assert report['proposal_differences'] == []
    assert report['decision']['status'] == 'unknown'


def test_complete_receipt_chain_links_observations_without_minting_parent_save_ancestry():
    first = receipts.seal_receipt(receipt_payload())
    observed = observed_payload()
    observed.update(sequence=1, previous=first.identity, event='backup-verified', after=None, terminal='pending')
    second = receipts.seal_receipt(observed)
    final = append(second, event='terminal', after=observation(), terminal='stopped', save_attempt='reported-saved')
    chain = receipts.validate_chain([first, second, final])
    assert isinstance(chain, tuple) and chain == (first, second, final)
    report = receipts.inspect_receipt(chain[-1])
    assert report['previous_receipt'] == second.identity
    assert report['parent_save_set_sha256'] is None
    assert report['decision']['status'] == 'unknown'
    assert report['claims']['ancestry'] == 'unknown'


@pytest.mark.parametrize('change', ['empty', 'missing', 'reordered', 'duplicate', 'parent', 'attempt'])
def test_missing_reordered_or_foreign_attempt_observation_chains_are_rejected(change):
    first = receipts.seal_receipt(receipt_payload())
    second = append(first, event='failed', terminal='failed')
    third = append(second, event='interrupted', terminal='interrupted')
    chain = [first, second, third]
    if change == 'empty':
        chain = []
    elif change == 'missing':
        chain = [first, third]
    elif change == 'reordered':
        chain = [second, first, third]
    elif change == 'duplicate':
        chain = [first, second, second]
    else:
        value = third.to_dict()
        value.pop('identity')
        if change == 'parent':
            value['previous'] = checksum(b'unrelated receipt')
        else:
            value['attempt'] = 'e' * 32
            value['process']['expected_session_token'] = value['attempt']
        chain[-1] = receipts.seal_receipt(value)
    with pytest.raises(VirtualLoaderError):
        receipts.validate_chain(chain)


def test_chain_count_and_logical_bytes_are_bounded(monkeypatch):
    first = receipts.seal_receipt(receipt_payload())
    second = append(first)
    monkeypatch.setattr(receipts, 'MAX_CHAIN_BYTES', len(first.data) + len(second.data) - 1)
    with pytest.raises(VirtualLoaderError):
        receipts.validate_chain([first, second])
    monkeypatch.setattr(receipts, 'MAX_CHAIN_BYTES', 32 * 1024 * 1024)
    monkeypatch.setattr(receipts, 'MAX_RECEIPTS', 1)
    with pytest.raises(VirtualLoaderError):
        receipts.validate_chain([first, second])


def test_transfer_profile_change_and_subsequent_observed_write_preserve_unknown_origin():
    original = observed_payload()
    original['after']['files'][FIRST]['sha256'] = checksum(b'first reported save')
    transferred = receipts.decode_receipt(receipts.seal_receipt(original).data)
    next_attempt = observed_payload()
    next_attempt['attempt'] = 'e' * 32
    next_attempt['process'] = receipts.empty_process(next_attempt['attempt'])
    next_attempt['proposed']['items'].clear()
    next_attempt['before'] = transferred.to_dict()['after']
    next_attempt['backup']['save_set_sha256'] = receipts.snapshot_identity(
        next_attempt['before'], next_attempt['selected'])
    next_attempt['after']['files'][FIRST]['sha256'] = checksum(b'subsequent managed write')
    next_attempt['save_attempt'] = 'reported-saved'
    result = receipts.inspect_receipt(receipts.seal_receipt(next_attempt), target=proposed_context())
    assert result['decision']['status'] == 'unknown'
    assert result['decision']['producer_evidence'] == 'unknown'
    assert result['parent_save_set_sha256'] is None
    assert result['requirements_coverage'] == 'unknown'
    assert result['claims']['ancestry'] == 'unknown'


@pytest.mark.parametrize('state', ['none', 'before-only', 'complete', 'missing', 'read-error'])
def test_inspection_preserves_timing_and_never_fingerprints_unobserved_selected_bytes(state):
    value = observed_payload()
    value['captured_utc'] = '2026-10-11T12:00:02Z'
    value['after']['observed_utc'] = '2026-10-11T12:00:01Z'
    if state == 'none':
        value.update(before=None, after=None, backup=receipts.empty_backup())
    elif state == 'before-only':
        value['after'] = None
    elif state in ('missing', 'read-error'):
        del value['after']['files'][FIRST]
        if state == 'missing':
            value['after']['missing'] = [FIRST]
        else:
            value['after']['errors'] = {FIRST: 'read-failed'}
    receipt = receipts.seal_receipt(value)
    report = receipts.inspect_receipt(receipt)
    observation = value['after'] if value['after'] is not None else value['before']
    assert report['event'] == 'terminal'
    assert report['captured_utc'] == value['captured_utc']
    assert report['observed_file_set']['sha256'] == receipts.snapshot_identity(
        observation, value['selected'])
    assert report['observed_file_set']['observed_utc'] == (
        observation['observed_utc'] if observation is not None else None)
    assert report['observed_file_set']['inventory_complete'] is (
        observation['inventory_complete'] if observation is not None else None)
    assert report['file_effect']['before_observed_utc'] == (
        value['before']['observed_utc'] if value['before'] is not None else None)
    assert report['file_effect']['after_observed_utc'] == (
        value['after']['observed_utc'] if value['after'] is not None else None)
    assert report['proposed_context'] == value['proposed']
    assert report['recorded_backup'] == value['backup']
    assert report['produced_context'] is None and report['decision']['status'] == 'unknown'
    report['proposed_context']['items'].clear()
    report['recorded_backup']['status'] = 'unknown'
    assert receipt.to_dict()['proposed']['items']
    assert receipt.to_dict()['backup'] == value['backup']
