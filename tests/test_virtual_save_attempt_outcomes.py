"""Save attempt outcomes and observed bytes are independent evidence."""
from copy import deepcopy

import pytest

from cdmw.domain.virtual_save_evidence import CLAIMS, compare
from tests.test_virtual_save_evidence import inputs, sequence, reseal_chain


@pytest.mark.parametrize('outcome,status', [('failed', 'reported-failure'), ('unknown', 'unverified-outcome')])
@pytest.mark.parametrize('change', ['unchanged', 'changed', 'missing'])
def test_unsuccessful_save_attempt_records_bytes_without_requiring_a_commit(inputs, tmp_path, outcome, status, change):
    values, _ = sequence(inputs, tmp_path)
    values = values[:4]
    values[3]['observation']['outcome'] = outcome
    selected = values[3]['selected']
    if change == 'unchanged':
        values[3]['files'] = deepcopy(values[2]['files'])
    elif change == 'missing':
        values[3]['files'].pop(selected[0])
    report = compare(reseal_chain(values))
    assert report['status'] == status, report
    assert report['claims'] == CLAIMS
    assert report['save_attempt'] == {
        'outcome': outcome,
        'selected_bytes_changed': change != 'unchanged',
        'other_files_changed': False,
        'missing_selected_files': selected if change == 'missing' else [],
    }
    assert 'new-absent-save' not in {row['check'] for row in report['checks']}


@pytest.mark.parametrize('outcome,status', [('failed', 'reported-failure'), ('unknown', 'unverified-outcome')])
def test_later_restoration_does_not_promote_an_unsuccessful_unchanged_attempt(inputs, tmp_path, outcome, status):
    values, _ = sequence(inputs, tmp_path)
    values[3]['observation']['outcome'] = outcome
    for index in (3, 4, 5):
        values[index]['files'] = deepcopy(values[2]['files'])
    report = compare(reseal_chain(values))
    assert report['status'] == status and report['claims'] == CLAIMS
    assert all(row['consistent'] for row in report['checks'])
    assert 'restore-new-save-input' not in {row['check'] for row in report['checks']}
    assert report['save_attempt']['selected_bytes_changed'] is False


def test_early_failed_load_remains_reported_failure(inputs, tmp_path):
    values, _ = sequence(inputs, tmp_path)
    values[2]['observation']['outcome'] = 'failed'
    report = compare(reseal_chain(values[:3]))
    assert report['status'] == 'reported-failure'
    assert report['save_attempt'] is None and report['claims'] == CLAIMS


def test_unselected_autosave_is_not_a_successful_selected_save(inputs, tmp_path):
    values, _ = sequence(inputs, tmp_path)
    values = values[:4]
    values[3]['files'] = deepcopy(values[2]['files'])
    values[3]['files']['e' * 64] = {'size': 13, 'sha256': 'd' * 64}
    report = compare(reseal_chain(values))
    assert report['status'] == 'inconsistent' and report['claims'] == CLAIMS
    assert report['save_attempt']['other_files_changed'] is True
    assert report['save_attempt']['selected_bytes_changed'] is False
    assert any(row['check'] == 'new-absent-save' and not row['consistent'] for row in report['checks'])


def test_failed_attempt_does_not_hide_later_selected_byte_interference(inputs, tmp_path):
    values, _ = sequence(inputs, tmp_path)
    values[3]['observation']['outcome'] = 'failed'
    values[5]['files'] = deepcopy(values[0]['files'])
    report = compare(reseal_chain(values))
    assert report['status'] == 'inconsistent'
    assert any(row['check'] == 'restored-load-no-save' and not row['consistent'] for row in report['checks'])
    assert report['claims'] == CLAIMS
