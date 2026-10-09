"""Owned byte fixtures verify the research tool, never actual game save behavior."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualLoaderError, VirtualProfile
from cdmw.domain.virtual_save_evidence import CLAIMS, STAGES, compare, decode, encoded, seal
from cdmw.services import virtual_loader_save_evidence as evidence
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import load_profile, publish_profile
from tests.test_virtual_loader import packages


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    root, files = packages(tmp_path, 1)
    executable = root / 'bin64/CrimsonDesert.exe'
    executable.parent.mkdir(exist_ok=True)
    executable.write_bytes(b'synthetic executable fingerprint')
    publish_profile(prepare_profile(VirtualProfile(files), root))
    copy = tmp_path / 'save-copy'
    slot = copy / 'private-account/slot1.save'
    slot.parent.mkdir(parents=True)
    slot.write_bytes(b'original save with provider data')
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    return root, files, copy, slot


def files_in(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def initial(inputs, tmp_path, **kwargs):
    root, _, copy, slot = inputs
    output = tmp_path / 'baseline.json'
    value = evidence.capture(root, copy, output, stage='baseline', outcome='prepared',
        notes='Synthetic bytes only; no game observation.', provider=next(iter(load_profile(root)['items'])),
        slots=(slot.relative_to(copy).as_posix(),), **kwargs)
    return output, value


def sequence(inputs, tmp_path):
    root, files, copy, slot = inputs
    output, first = initial(inputs, tmp_path)
    values, paths = [first], [output]
    publish_profile(prepare_profile(VirtualProfile(), root))
    outcomes = ('prepared', 'loaded', 'saved', 'prepared', 'loaded')
    for index, (stage, outcome) in enumerate(zip(STAGES[1:], outcomes), 1):
        if stage == 'absent_saved':
            slot.write_bytes(b'new save without provider data')
        if stage == 'restored_before_load':
            publish_profile(prepare_profile(VirtualProfile(files), root))
        output = tmp_path / (stage + '.json')
        values.append(evidence.capture(root, copy, output, stage=stage, outcome=outcome,
            notes='Synthetic state for the consistency checker, not a game result.', previous=paths[-1]))
        paths.append(output)
    return values, paths


def reseal_chain(values):
    result = []
    for value in deepcopy(values):
        value.pop('identity')
        value['parent'] = result[-1]['identity'] if result else None
        result.append(seal(value))
    return result


def test_capture_is_read_only_omits_paths_and_does_not_certify_compatibility(inputs, tmp_path):
    root, _, copy, _ = inputs
    before = files_in(root), files_in(copy)
    path, value = initial(inputs, tmp_path)
    assert (files_in(root), files_in(copy)) == before
    assert evidence.read_capture(path) == value
    text = path.read_text(encoding='utf-8')
    assert str(tmp_path) not in text and 'private-account' not in text and 'slot1.save' not in text
    report = compare([value])
    assert report['status'] == 'incomplete' and report['claims'] == CLAIMS
    assert report['missing_stages'] == list(STAGES[1:])


def test_complete_fixture_sequence_stays_operator_reported_and_cli_agrees(inputs, tmp_path):
    values, paths = sequence(inputs, tmp_path)
    report = compare(values)
    assert report['status'] == 'candidate-observation', report
    assert all(check['consistent'] for check in report['checks'])
    assert report['claims']['save_origin'] == 'unknown'
    assert report['claims']['save_compatibility'] == 'unverified'
    assert values[4]['context']['generation'] != values[0]['context']['generation']
    run = subprocess.run([sys.executable, 'scripts/capture_virtual_save_evidence.py', 'compare',
                          *map(str, paths)], cwd=Path(__file__).resolve().parents[1],
                         capture_output=True, text=True, timeout=30,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == report


@pytest.mark.parametrize('change,failed', [
    ('original-restored', 'restore-new-save-input'),
    ('no-new-save', 'new-absent-save'),
    ('load-wrote-save', 'absent-load-no-save'),
    ('original-after-restored-load', 'restored-load-no-save'),
    ('restored-load-wrote-save', 'restored-load-no-save'),
    ('changed-binding', 'restored_before_load:bindings'),
    ('provider-still-active', 'absent_before_load:provider'),
    ('changed-executable', 'restored_loaded:environment'),
])
def test_comparison_finds_wrong_save_or_context_without_claiming_safety(inputs, tmp_path, change, failed):
    values, _ = sequence(inputs, tmp_path)
    if change == 'original-restored':
        values[4]['files'] = values[0]['files']
    elif change == 'no-new-save':
        values[3]['files'] = values[1]['files']
    elif change == 'load-wrote-save':
        values[2]['files'] = values[3]['files']
    elif change == 'original-after-restored-load':
        values[5]['files'] = values[0]['files']
    elif change == 'restored-load-wrote-save':
        values[5]['files'] = deepcopy(values[4]['files'])
        values[5]['files'][values[5]['selected'][0]]['sha256'] = 'd' * 64
    elif change == 'changed-binding':
        values[4]['context']['provider_binding']['binding_hash'] = 'b' * 64
    elif change == 'provider-still-active':
        values[1]['context']['physical_items'] = values[0]['context']['items']
    else:
        values[5]['context']['executable_sha256'] = 'c' * 64
    report = compare(reseal_chain(values))
    assert report['status'] == 'inconsistent'
    assert any(row['check'] == failed and not row['consistent'] for row in report['checks'])
    assert report['claims'] == CLAIMS


@pytest.mark.parametrize('change', ['tamper', 'claim', 'reorder', 'duplicate', 'oversize'])
def test_malformed_or_reordered_capture_cannot_be_used_as_evidence(inputs, tmp_path, change):
    _, value = initial(inputs, tmp_path)
    raw = encoded(value)
    if change == 'tamper':
        value['observation']['notes'] = 'Changed after capture'
        raw = encoded(value)
    elif change == 'claim':
        value['claims']['save_compatibility'] = 'verified'
        raw = encoded(reseal_chain([value])[0])
    elif change == 'duplicate':
        raw = b'{"format":"duplicate",' + raw[1:]
    elif change == 'oversize':
        raw += b' ' * (4 * 1024 * 1024)
    else:
        with pytest.raises(VirtualLoaderError, match='missing, reordered'):
            compare([value, value])
        return
    with pytest.raises(VirtualLoaderError):
        decode(raw)


@pytest.mark.parametrize('failure', ['save-change', 'context-change', 'cancel', 'collision'])
def test_changed_or_cancelled_capture_preserves_inputs_and_no_partial_report(inputs, tmp_path, monkeypatch, failure):
    root, _, copy, slot = inputs
    before = files_in(root), files_in(copy)
    output = tmp_path / 'baseline.json'
    stop = threading.Event()
    records = evidence._records
    calls = 0
    def read(*args):
        nonlocal calls
        value = records(*args)
        calls += 1
        if calls == 1:
            if failure == 'save-change':
                old = slot.stat()
                slot.write_bytes(b'X' * old.st_size)
                os.utime(slot, ns=(old.st_atime_ns, old.st_mtime_ns))
            elif failure == 'context-change':
                executable = root / 'bin64/CrimsonDesert.exe'
                old = executable.stat()
                executable.write_bytes(b'Y' * old.st_size)
                os.utime(executable, ns=(old.st_atime_ns, old.st_mtime_ns))
            elif failure == 'cancel':
                stop.set()
            else:
                output.write_bytes(b'another writer owns this report')
        return value
    monkeypatch.setattr(evidence, '_records', read)
    with pytest.raises((VirtualLoaderError, RunCancelled, FileExistsError)):
        initial(inputs, tmp_path, stop_event=stop)
    assert not list(tmp_path.glob('.cdmw-save-evidence-*.tmp'))
    if failure == 'collision':
        assert output.read_bytes() == b'another writer owns this report'
    else:
        assert not output.exists()
    if failure in ('cancel', 'collision'):
        assert (files_in(root), files_in(copy)) == before


@pytest.mark.parametrize('location', ['game', 'saves', 'existing'])
def test_capture_output_cannot_replace_input_or_previous_report(inputs, tmp_path, location):
    root, _, copy, _ = inputs
    destination = {'game': root / 'report.json', 'saves': copy / 'report.json',
                   'existing': tmp_path / 'owned.json'}[location]
    if location == 'existing':
        destination.write_bytes(b'keep this')
    before = files_in(root), files_in(copy)
    with pytest.raises(VirtualLoaderError):
        evidence.capture(root, copy, destination, stage='baseline', outcome='prepared', notes='fixture')
    assert (files_in(root), files_in(copy)) == before
    if location == 'existing':
        assert destination.read_bytes() == b'keep this'


def test_capture_command_uses_explicit_paths_and_reports_unknown_origin(inputs, tmp_path, monkeypatch, capsys):
    from scripts.capture_virtual_save_evidence import main
    root, _, copy, slot = inputs
    output = tmp_path / 'cli.json'
    provider = next(iter(load_profile(root)['items']))
    monkeypatch.setattr(sys, 'argv', ['capture_virtual_save_evidence.py', 'capture', '--game-root', str(root),
        '--save-copy', str(copy), '--output', str(output), '--stage', 'baseline', '--outcome', 'prepared',
        '--notes', 'Synthetic CLI fixture.', '--provider', provider, '--slot', slot.relative_to(copy).as_posix()])
    main()
    result = json.loads(capsys.readouterr().out)
    assert result['capture'] == str(output)
    assert result['claims'] == CLAIMS and result['identity'] == evidence.read_capture(output)['identity']


@pytest.mark.parametrize('failure', ['late-cancel', 'link-io'])
def test_report_publication_failure_leaves_no_partial_output(inputs, tmp_path, monkeypatch, failure):
    stop = threading.Event()
    if failure == 'late-cancel':
        fsync = evidence.os.fsync
        def sync(descriptor):
            fsync(descriptor)
            stop.set()
        monkeypatch.setattr(evidence.os, 'fsync', sync)
    else:
        def link(*args):
            raise OSError('injected report publication failure')
        monkeypatch.setattr(evidence.os, 'link', link)
    before = files_in(inputs[0]), files_in(inputs[2])
    with pytest.raises((RunCancelled, OSError)):
        initial(inputs, tmp_path, stop_event=stop)
    assert not (tmp_path / 'baseline.json').exists()
    assert not list(tmp_path.glob('.cdmw-save-evidence-*.tmp'))
    assert (files_in(inputs[0]), files_in(inputs[2])) == before


def test_lineage_command_does_not_promote_captures_or_capture_parents_to_save_origin(inputs, tmp_path):
    values, paths = sequence(inputs, tmp_path)
    root, _, copy, _ = inputs
    before = files_in(root), files_in(copy), [path.read_bytes() for path in paths]
    assert values[-1]['parent'] is not None
    expected = evidence.inspect_capture_lineage(values[-1])
    assert expected['claims'] == CLAIMS
    assert expected['producer_witness'] is None and expected['parent_save_set_sha256'] is None
    assert expected['requirements_coverage'] == 'unknown'
    assert expected['decision']['status'] == 'unknown'
    assert expected['observed_file_set']['membership_complete'] is False
    assert expected['observed_file_set']['slot_layout_sha256'] is None
    assert not expected['observed_file_set']['missing_selected_files']
    assert expected['observed_file_set']['sha256'] == evidence.inspect_capture_lineage(values[-2])['observed_file_set']['sha256']
    assert expected['observed_file_set']['sha256'] != evidence.inspect_capture_lineage(values[0])['observed_file_set']['sha256']
    run = subprocess.run([sys.executable, 'scripts/capture_virtual_save_evidence.py', 'lineage', str(paths[-1])],
                         cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert run.returncode == 0, run.stderr
    # JSON represents tuple reasons as arrays; compare the complete rendered report.
    assert json.loads(run.stdout) == json.loads(json.dumps(expected))
    assert (files_in(root), files_in(copy), [path.read_bytes() for path in paths]) == before


def test_lineage_inspection_names_missing_selected_files_and_keeps_origin_unknown(inputs, tmp_path):
    values, _ = sequence(inputs, tmp_path)
    values[-1]['files'] = {}
    final = reseal_chain(values)[-1]
    report = evidence.inspect_capture_lineage(final)
    assert report['observed_file_set']['files'] == {}
    assert report['observed_file_set']['missing_selected_files'] == sorted(final['selected'])
    assert report['decision']['status'] == 'unknown'
    assert 'empty-save-set' in report['decision']['reasons']
    assert report['claims'] == CLAIMS


def test_linked_copy_refuses_before_reading_its_files(inputs, tmp_path, monkeypatch):
    root, _, copy, _ = inputs
    linked = tmp_path / 'linked-copy'
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(linked), str(copy)], capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0, result.stderr
    else:
        linked.symlink_to(copy, target_is_directory=True)
    monkeypatch.setattr(evidence, '_records', lambda *a: pytest.fail('A linked copy was read'))
    with pytest.raises(VirtualLoaderError, match='linked'):
        evidence.capture(root, linked, tmp_path / 'linked.json', stage='baseline', outcome='prepared', notes='fixture')
    assert not (tmp_path / 'linked.json').exists()


def test_running_game_refuses_before_context_or_save_reads(inputs, tmp_path, monkeypatch):
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: True)
    monkeypatch.setattr(evidence, '_context', lambda *a: pytest.fail('Context read while game was running'))
    monkeypatch.setattr(evidence, '_records', lambda *a: pytest.fail('Save read while game was running'))
    with pytest.raises(VirtualLoaderError, match='Close the game'):
        initial(inputs, tmp_path)
    assert not (tmp_path / 'baseline.json').exists()


@pytest.mark.parametrize('outcome,status', [('failed', 'reported-failure'), ('unknown', 'unverified-outcome')])
def test_consistent_hashes_never_override_a_failed_or_unknown_observation(inputs, tmp_path, outcome, status):
    values, _ = sequence(inputs, tmp_path)
    values[-1]['observation']['outcome'] = outcome
    result = compare(reseal_chain(values))
    assert all(check['consistent'] for check in result['checks'])
    assert result['status'] == status and result['claims'] == CLAIMS
