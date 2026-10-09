"""Synthetic policy fixtures; no actual save producer or game protocol is verified."""
from dataclasses import replace

import pytest

from cdmw.domain.virtual_save_lineage import (
    SaveCommitWitness, SaveContextContract, SaveProviderRequirement, SaveSetSnapshot, assess_lineage,
)


@pytest.fixture
def known():
    snapshot = SaveSetSnapshot((('a' * 64, 13, 'b' * 64),), 'c' * 64, True)
    provider = SaveProviderRequirement('a' * 32, 'd' * 64, 'e' * 64, 'f' * 64)
    context = SaveContextContract('1' * 64, '2' * 64, '3' * 64, '4' * 64, (provider,))
    witness = SaveCommitWitness(snapshot.identity, context, '5' * 64, '6' * 64, 12, '7' * 64,
                                context.executable_sha256, '8' * 32, finalized=True, events_complete=True,
                                parent_origin='root', requirements_coverage='complete')
    return snapshot, context, witness


def with_fixture_verification(snapshot, target, witness):
    # The policy receives an independently trusted fixture. No production
    # verifier exists, and the CLI never accepts a verifier or a witness file.
    return assess_lineage(snapshot, target, witness,
                          verify_commit=lambda actual, proposed: (actual, proposed) == (snapshot, witness))


def test_origin_never_follows_from_structurally_complete_metadata_alone(known):
    snapshot, context, witness = known
    assert assess_lineage(snapshot, context).producer_evidence == 'unknown'
    decision = assess_lineage(snapshot, context, witness)
    assert decision.status == 'unknown' and decision.reasons == ('unverified-save-commit',)
    admitted = with_fixture_verification(*known)
    assert (admitted.status, admitted.producer_evidence, admitted.context) == ('context-match', 'verified-commit', 'match')


@pytest.mark.parametrize('answer', [False, None, 1, 'verified'])
def test_commit_verifier_requires_explicit_success(known, answer):
    snapshot, context, witness = known
    result = assess_lineage(snapshot, context, witness, verify_commit=lambda *args: answer)
    assert result.status == 'unknown' and result.producer_evidence == 'unknown'


def test_verifier_failure_cannot_return_clearance(known):
    def broken(*args):
        raise OSError('owned witness verification failed')
    with pytest.raises(OSError, match='verification failed'):
        assess_lineage(*known, verify_commit=broken)


@pytest.mark.parametrize('change,reason', [
    ({'finalized': False}, 'unfinalized-save-commit'),
    ({'events_complete': False}, 'incomplete-save-events'),
    ({'foreign_writer': True}, 'foreign-save-writer'),
    ({'interrupted': True}, 'interrupted-save-commit'),
    ({'save_set_sha256': '9' * 64}, 'commit-does-not-match-save-set'),
    ({'writer_image_sha256': '9' * 64}, 'writer-image-mismatch'),
])
def test_partial_commit_cloud_replacement_or_wrong_writer_stays_unknown(known, change, reason):
    snapshot, context, witness = known
    result = with_fixture_verification(snapshot, context, replace(witness, **change))
    assert result.status == 'unknown' and result.producer_evidence == 'unknown'
    assert reason in result.reasons


@pytest.mark.parametrize('change', ['content', 'size', 'name', 'membership', 'layout'])
def test_witness_is_bound_to_exact_save_set_and_layout(known, change):
    snapshot, context, witness = known
    name, size, content = snapshot.files[0]
    if change == 'membership':
        snapshot = replace(snapshot, membership_complete=False)
    elif change == 'layout':
        snapshot = replace(snapshot, slot_layout_sha256=None)
    else:
        snapshot = replace(snapshot, files=((('9' * 64 if change == 'name' else name),
                                             size + (change == 'size'),
                                             '9' * 64 if change == 'content' else content),))
    result = with_fixture_verification(snapshot, context, witness)
    assert result.status == 'unknown' and result.producer_evidence == 'unknown'


@pytest.mark.parametrize('field', ['executable_sha256', 'runtime_sha256', 'compilation_sha256', 'persistence_sha256'])
def test_unproven_build_runtime_compiler_or_schema_transition_refuses(known, field):
    snapshot, context, witness = known
    result = with_fixture_verification(snapshot, replace(context, **{field: '9' * 64}), witness)
    assert result.status == 'refused' and result.context == 'mismatch'
    assert 'context-mismatch:' + field in result.reasons


@pytest.mark.parametrize('change', ['missing', 'added', 'content', 'bindings', 'persistence'])
def test_provider_requirements_cannot_be_reallocated_or_silently_changed(known, change):
    snapshot, context, witness = known
    provider = context.providers[0]
    if change == 'missing':
        providers = ()
    elif change == 'added':
        providers = (provider, replace(provider, identity='b' * 32))
    else:
        providers = (replace(provider, **{change + '_sha256': '9' * 64}),)
    result = with_fixture_verification(snapshot, replace(context, providers=providers), witness)
    assert result.status == 'refused' and result.producer_evidence == 'verified-commit'
    assert result.reasons


@pytest.mark.parametrize('change,reason', [
    ({'parent_origin': 'unknown'}, 'unknown-parent-origin'),
    ({'requirements_coverage': 'unknown'}, 'incomplete-requirements-coverage'),
])
def test_managed_write_does_not_erase_unknown_ancestry_or_inherited_state(known, change, reason):
    snapshot, context, witness = known
    result = with_fixture_verification(snapshot, context, replace(witness, **change))
    assert result.status == 'unknown' and result.context == 'match'
    assert reason in result.reasons


def test_inherited_missing_provider_refuses_and_restoring_it_does_not_recreate_lost_state(known):
    snapshot, context, witness = known
    inherited = replace(context.providers[0], identity='b' * 32)
    witness = replace(witness, parent_origin='verified', parent_save_set_sha256='0' * 64,
                      inherited_requirements=(inherited,))
    result = with_fixture_verification(snapshot, context, witness)
    assert result.status == 'refused' and 'missing-required-provider:' + inherited.identity in result.reasons
    restored = replace(context, providers=(*context.providers, inherited))
    result = with_fixture_verification(snapshot, restored, witness)
    assert result.status == 'refused' and 'unproven-added-provider:' + inherited.identity in result.reasons


def test_inherited_binding_conflict_cannot_be_resolved_by_dropping_a_requirement(known):
    snapshot, context, witness = known
    witness = replace(witness, inherited_requirements=(replace(context.providers[0], bindings_sha256='9' * 64),))
    result = with_fixture_verification(snapshot, context, witness)
    assert result.status == 'refused'
    assert 'contradictory-provider-requirement:' + context.providers[0].identity in result.reasons


def test_identical_unknown_persistence_contracts_are_not_positive_evidence(known):
    snapshot, context, witness = known
    context = replace(context, persistence_sha256=None,
                      providers=(replace(context.providers[0], persistence_sha256=None),))
    result = with_fixture_verification(snapshot, context, replace(witness, context=context))
    assert result.status == 'unknown' and 'unknown-persistence-contract' in result.reasons


def test_save_set_identity_is_order_independent_but_does_not_ignore_members(known):
    snapshot, _, _ = known
    extra = ('d' * 64, 20, 'e' * 64)
    first = replace(snapshot, files=(*snapshot.files, extra))
    assert first.identity == replace(first, files=tuple(reversed(first.files))).identity
    assert first.identity != snapshot.identity


def test_identical_parent_bytes_can_have_a_distinct_proven_commit(known):
    snapshot, context, witness = known
    witness = replace(witness, parent_origin='verified', parent_save_set_sha256=snapshot.identity)
    assert with_fixture_verification(snapshot, context, witness).status == 'context-match'
