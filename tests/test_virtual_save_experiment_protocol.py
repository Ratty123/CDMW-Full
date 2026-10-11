"""Disposable synthetic files exercise actual protocol/CLI paths, never game saves."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualLaunchPlan, VirtualLoaderError, VirtualProfile
from cdmw.domain.virtual_save_evidence import CLAIMS, STAGES, checksum, compare, encoded, seal
from cdmw.services import virtual_loader_save_evidence as evidence
from cdmw.services import virtual_save_experiment_protocol as protocol
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import generation_path, load_profile, publish_profile
from tests.test_virtual_save_evidence import files_in, inputs


@pytest.fixture
def selection(inputs, tmp_path):
    root, packages, working, slot = inputs
    second = working / 'private-account/slot1.meta'
    second.write_bytes(b'unchanged selected metadata')
    original = tmp_path / 'original-recovery'
    shutil.copytree(working, original)
    return SimpleNamespace(root=root, packages=packages, working=working, slot=slot, second=second,
        original=original, retained=tmp_path / 'post-attempt', output=tmp_path / 'experiment.json',
        provider=next(iter(load_profile(root)['items'])),
        members=sorted([slot.relative_to(working).as_posix(), second.relative_to(working).as_posix()]))


def prepare(case, **kwargs):
    return protocol.prepare_experiment(case.root, case.working, case.original, case.retained,
        case.output, provider=case.provider, slots=case.members, **kwargs)


def capture(case, value, stage, outcome=None, **kwargs):
    index = STAGES.index(stage)
    if outcome is None:
        outcome = 'prepared' if stage in ('baseline', 'absent_before_load', 'restored_before_load') else 'loaded'
    return evidence.capture(case.root, case.working, protocol.capture_path(value, stage),
        stage=stage, outcome=outcome, notes='Synthetic operator observation; no game was used.',
        protocol=case.output, previous=protocol.capture_path(value, STAGES[index - 1]) if index else None,
        **kwargs)


def through_attempt(case, value, *, effect='one', outcome='saved'):
    values = [capture(case, value, 'baseline')]
    publish_profile(prepare_profile(VirtualProfile(), case.root))
    values.append(capture(case, value, 'absent_before_load'))
    values.append(capture(case, value, 'absent_loaded'))
    if effect in ('one', 'all', 'mixed-missing'):
        case.slot.write_bytes(b'changed post-attempt selected save')
    if effect == 'all':
        case.second.write_bytes(b'changed post-attempt metadata')
    elif effect == 'mixed-missing':
        case.second.unlink()
    elif effect == 'missing':
        case.slot.unlink()
        case.second.unlink()
    values.append(capture(case, value, 'absent_saved', outcome))
    return values


def restore(case, value, values):
    publish_profile(prepare_profile(VirtualProfile(case.packages), case.root))
    values.append(capture(case, value, 'restored_before_load'))
    values.append(capture(case, value, 'restored_loaded'))
    return compare(values)


def cli(monkeypatch, capsys, argv):
    from scripts.capture_virtual_save_evidence import main
    with monkeypatch.context() as scoped:
        scoped.setattr(sys, 'argv', argv)
        main()
    return json.loads(capsys.readouterr().out)


def test_actual_prepare_cli_publishes_six_reviewable_commands_without_mutating_inputs(selection, monkeypatch, capsys):
    case = selection
    before = files_in(case.root), files_in(case.working), files_in(case.original)
    argv = ['capture_virtual_save_evidence.py', 'prepare-experiment', '--game-root', str(case.root),
        '--save-copy', str(case.working), '--original-copy', str(case.original),
        '--post-attempt-copy', str(case.retained), '--output', str(case.output), '--provider', case.provider]
    for member in case.members:
        argv += ['--slot', member]
    report = cli(monkeypatch, capsys, argv)
    value = protocol.read_protocol(case.output)
    assert report['identity'] == value['identity'] and report['checklist'] == value['commands']
    assert [row['stage'] for row in value['commands']] == list(STAGES)
    assert value['unknowns'] == protocol.UNKNOWNS and value['backup'] is None
    assert value['baseline']['claims'] == CLAIMS
    assert all('--protocol' in row['argv'] and row['powershell'].startswith('& ') for row in value['commands'])
    assert 'retain_after_capture' in value['commands'][3]
    assert (files_in(case.root), files_in(case.working), files_in(case.original)) == before
    assert not case.retained.exists()


def test_actual_generated_cli_sequence_retains_post_attempt_and_preserves_original(selection, monkeypatch, capsys):
    case = selection
    value = prepare(case)
    original = files_in(case.original)
    values = []
    for index, row in enumerate(value['commands']):
        if index == 1:
            publish_profile(prepare_profile(VirtualProfile(), case.root))
        if index == 3:
            case.slot.write_bytes(b'new copied bytes from a synthetic attempt')
        if index == 4:
            publish_profile(prepare_profile(VirtualProfile(case.packages), case.root))
        argv = row['argv'][1:]
        if index in (2, 5):
            argv[argv.index('--outcome') + 1] = 'loaded'
        elif index == 3:
            argv[argv.index('--outcome') + 1] = 'reported-saved'
        result = cli(monkeypatch, capsys, argv)
        values.append(evidence.read_capture(protocol.capture_path(value, row['stage'])))
        assert result['identity'] == values[-1]['identity']
        if index == 3:
            kept = cli(monkeypatch, capsys, row['retain_after_capture']['argv'][1:])
            assert kept['capture_identity'] == values[-1]['identity']
    report = compare(values)
    assert report['status'] == 'candidate-observation'
    assert report['save_attempt']['outcome'] == 'saved'
    assert report['save_attempt_observation']['operator_outcome'] == 'reported-saved'
    assert report['save_attempt_observation']['file_effect'] == 'partially-changed'
    assert report['save_attempt_observation']['producer'] == 'unknown'
    assert files_in(case.original) == original
    assert files_in(case.retained / 'files') == files_in(case.working)
    assert protocol._read_retained(value, values[3])['capture_identity'] == values[3]['identity']


@pytest.mark.parametrize('outcome', ['failed', 'unknown'])
@pytest.mark.parametrize('effect,expected', [
    ('unchanged', 'unchanged'), ('one', 'partially-changed'), ('all', 'changed'),
    ('mixed-missing', 'partially-changed'), ('missing', 'missing-selected-members'),
])
def test_failed_unknown_and_partial_attempts_remain_retained_observations(selection, outcome, effect, expected):
    case = selection
    value = prepare(case)
    original = files_in(case.original)
    values = through_attempt(case, value, effect=effect, outcome=outcome)
    retained = protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'))
    report = restore(case, value, values)
    observation = report['save_attempt_observation']
    assert observation['operator_outcome'] == outcome and observation['file_effect'] == expected
    assert observation['producer'] == observation['produced_context'] == observation['ancestry'] == 'unknown'
    assert retained['missing_selected_files'] == observation['missing_selected_files']
    assert report['save_attempt']['outcome'] == outcome and report['claims'] == CLAIMS
    assert report['status'] != 'candidate-observation'
    assert files_in(case.original) == original
    assert files_in(case.retained / 'files') == files_in(case.working)


@pytest.mark.parametrize('members', [
    [], ['../slot.save'], ['/slot.save'], ['a//slot.save'], ['a\\slot.save'],
    ['private-account/slot1.save', 'PRIVATE-ACCOUNT/SLOT1.SAVE'], ['private-account/slot1.save'] * 33,
])
def test_preflight_rejects_invalid_members_before_reading_context(selection, monkeypatch, members):
    case = selection
    monkeypatch.setattr(evidence, '_context', lambda *a: pytest.fail('Invalid members reached context reads'))
    with pytest.raises(VirtualLoaderError):
        protocol.prepare_experiment(case.root, case.working, case.original, case.retained, case.output,
                                    provider=case.provider, slots=members)
    assert not case.output.exists()


@pytest.mark.parametrize('role', ['same-original', 'retained-inside-working', 'report-inside-original', 'live-copy'])
def test_preflight_rejects_overlapping_or_live_roles_before_context_reads(selection, monkeypatch, role):
    case = selection
    original, retained, output = case.original, case.retained, case.output
    if role == 'same-original':
        original = case.working
    elif role == 'retained-inside-working':
        retained = case.working / 'retained'
    elif role == 'report-inside-original':
        output = case.original / 'protocol.json'
    else:
        monkeypatch.setenv('LOCALAPPDATA', str(case.working.parent))
        live = case.working.parent / 'Pearl Abyss/CD/save'
        shutil.copytree(case.working, live)
        case.working = live
    monkeypatch.setattr(evidence, '_context', lambda *a: pytest.fail('Invalid roles reached context reads'))
    with pytest.raises(VirtualLoaderError):
        protocol.prepare_experiment(case.root, case.working, original, retained, output,
                                    provider=case.provider, slots=case.members)
    assert not output.exists()


@pytest.mark.parametrize('changed', ['working', 'original', 'executable'])
def test_preflight_refuses_same_timestamp_changes_without_publishing(selection, monkeypatch, changed):
    case = selection
    real = protocol._records
    changed_once = False
    def records(folder, stop_event=None):
        nonlocal changed_once
        result = real(folder, stop_event)
        if not changed_once:
            changed_once = True
            path = (case.slot if changed == 'working' else case.original / case.members[-1]
                    if changed == 'original' else case.root / 'bin64/CrimsonDesert.exe')
            stamp = path.stat()
            path.write_bytes(b'X' * stamp.st_size)
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return result
    monkeypatch.setattr(protocol, '_records', records)
    with pytest.raises(VirtualLoaderError, match='changed|matching original'):
        prepare(case)
    assert not case.output.exists()


@pytest.mark.parametrize('change', ['format', 'identity', 'commands', 'producer', 'case-alias', 'extra'])
def test_protocol_reader_refuses_changed_or_unknown_contract(selection, change):
    case = selection
    value = deepcopy(prepare(case))
    if change == 'format':
        value['format'] += '_future'
    elif change == 'identity':
        value['identity'] = '0' * 64
    elif change == 'commands':
        value['commands'][4]['argv'][0] = 'unreviewed-command'
    elif change == 'producer':
        value['unknowns']['producer'] = 'verified'
    elif change == 'case-alias':
        value['members'].append(value['members'][0].upper())
    else:
        value['extra'] = True
    case.output.write_bytes(encoded(value))
    with pytest.raises(VirtualLoaderError):
        protocol.read_protocol(case.output)


def test_protocol_decoder_rejects_duplicate_fields_and_small_limits(selection, monkeypatch):
    case = selection
    value = prepare(case)
    raw = case.output.read_bytes()
    case.output.write_bytes(raw[:-1] + b',"format":"' + protocol.FORMAT.encode() + b'"}')
    with pytest.raises(VirtualLoaderError):
        protocol.read_protocol(case.output)
    case.output.write_bytes(encoded(value))
    monkeypatch.setattr(protocol, 'MAX_RECORD', 10)
    with pytest.raises(VirtualLoaderError, match='size limit'):
        protocol.read_protocol(case.output)


@pytest.mark.parametrize('changed', ['output', 'provider', 'members', 'working', 'previous'])
def test_actual_capture_protocol_rejects_wrong_parameters(selection, changed):
    case = selection
    value = prepare(case)
    options = {'provider': case.provider, 'slots': case.members, 'previous': None}
    output, working = protocol.capture_path(value, 'baseline'), case.working
    if changed == 'output':
        output = case.output.parent / 'unreviewed.json'
    elif changed == 'provider':
        options['provider'] = 'a' * 32
    elif changed == 'members':
        options['slots'] = case.members[:1]
    elif changed == 'working':
        working = case.original
    else:
        options['previous'] = case.output
    with pytest.raises(VirtualLoaderError, match='protocol|previous'):
        evidence.capture(case.root, working, output, stage='baseline', outcome='prepared',
            notes='fixture', protocol=case.output, **options)
    assert not output.exists()


@pytest.mark.parametrize('changed', ['baseline', 'recovery'])
def test_protocol_capture_refuses_changed_baseline_or_original_recovery(selection, changed):
    case = selection
    value = prepare(case)
    path = case.slot if changed == 'baseline' else case.original / case.members[0]
    stamp = path.stat()
    path.write_bytes(b'Y' * stamp.st_size)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(VirtualLoaderError, match='baseline changed|recovery copy changed'):
        capture(case, value, 'baseline')
    assert not protocol.capture_path(value, 'baseline').exists()


def test_preload_requires_absent_provider_but_post_action_changes_are_retained(selection):
    case = selection
    value = prepare(case)
    first = capture(case, value, 'baseline')
    with pytest.raises(VirtualLoaderError, match='pre-load'):
        capture(case, value, 'absent_before_load')
    publish_profile(prepare_profile(VirtualProfile(), case.root))
    second = capture(case, value, 'absent_before_load')
    case.slot.write_bytes(b'unexpected synthetic autosave during load')
    third = capture(case, value, 'absent_loaded', 'failed')
    report = compare([first, second, third])
    assert report['status'] == 'inconsistent'
    assert third['observation']['outcome'] == 'failed'
    assert evidence.read_capture(protocol.capture_path(value, 'absent_loaded')) == third


@pytest.mark.parametrize('change', ['working-original', 'retained-data', 'retained-manifest', 'provider-binding'])
def test_restored_input_cannot_substitute_original_or_changed_retention(selection, monkeypatch, change):
    case = selection
    value = prepare(case)
    values = through_attempt(case, value)
    protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'))
    publish_profile(prepare_profile(VirtualProfile(case.packages), case.root))
    if change == 'working-original':
        for name, data in files_in(case.original).items():
            (case.working / name).write_bytes(data)
    elif change == 'retained-data':
        (case.retained / 'files' / case.members[-1]).write_bytes(b'altered retained input')
    elif change == 'retained-manifest':
        (case.retained / 'manifest.json').write_bytes(b'{}')
    else:
        actual = evidence._context
        def context(*args):
            result = actual(*args)
            result['provider_binding']['binding_hash'] = 'f' * 64
            return result
        monkeypatch.setattr(evidence, '_context', context)
    with pytest.raises(VirtualLoaderError):
        capture(case, value, 'restored_before_load')
    assert not protocol.capture_path(value, 'restored_before_load').exists()
    assert evidence.read_capture(protocol.capture_path(value, 'absent_saved')) == values[-1]


def test_restored_load_interference_is_captured_and_inconsistent(selection):
    case = selection
    value = prepare(case)
    values = through_attempt(case, value)
    protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'))
    publish_profile(prepare_profile(VirtualProfile(case.packages), case.root))
    values.append(capture(case, value, 'restored_before_load'))
    case.slot.write_bytes(b'unexpected change after restored-provider loading')
    values.append(capture(case, value, 'restored_loaded'))
    report = compare(values)
    assert report['status'] == 'inconsistent'
    assert any(row['check'] == 'restored-load-no-save' and not row['consistent'] for row in report['checks'])


@pytest.mark.parametrize('failure', ['cancel', 'copy-io', 'source-changed'])
def test_retention_failure_preserves_captures_and_original_without_complete_output(selection, monkeypatch, failure):
    case = selection
    value = prepare(case)
    values = through_attempt(case, value)
    original = files_in(case.original)
    actual = protocol._copy
    stop = threading.Event()
    def copy(*args):
        result = actual(*args)
        if failure == 'cancel':
            stop.set()
        elif failure == 'copy-io':
            raise OSError('injected retained-copy failure')
        else:
            case.slot.write_bytes(b'changed during retention')
        return result
    monkeypatch.setattr(protocol, '_copy', copy)
    with pytest.raises((RunCancelled, OSError, VirtualLoaderError)):
        protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'), stop_event=stop)
    assert not case.retained.exists()
    assert not list(case.output.parent.glob('.cdmw-save-attempt-*'))
    assert files_in(case.original) == original
    assert evidence.read_capture(protocol.capture_path(value, 'absent_saved')) == values[-1]


@pytest.mark.parametrize('when', ['existing-directory', 'late-manifest', 'late-cancel'])
def test_retention_publication_owns_only_its_new_files_and_reports_committed_outcome(selection, monkeypatch, when):
    case = selection
    value = prepare(case)
    through_attempt(case, value)
    stop = threading.Event()
    if when == 'existing-directory':
        case.retained.mkdir()
        (case.retained / 'external').write_bytes(b'keep external file')
        with pytest.raises(VirtualLoaderError, match='never replaced'):
            protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'))
        assert files_in(case.retained) == {'external': b'keep external file'}
        return
    actual = protocol.os.link
    def link(source, destination):
        if Path(destination) == case.retained / 'manifest.json' and when == 'late-manifest':
            Path(destination).write_bytes(b'foreign manifest')
        result = actual(source, destination)
        if Path(destination) == case.retained / 'manifest.json' and when == 'late-cancel':
            stop.set()
        return result
    monkeypatch.setattr(protocol.os, 'link', link)
    if when == 'late-manifest':
        with pytest.raises(OSError):
            protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'), stop_event=stop)
        assert files_in(case.retained) == {'manifest.json': b'foreign manifest'}
    else:
        result = protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'), stop_event=stop)
        assert stop.is_set() and result['identity']
        assert files_in(case.retained / 'files') == files_in(case.working)


def test_backup_association_verifies_owned_retained_files_without_reading_live_source(selection, monkeypatch):
    from cdmw.services import virtual_loader_saves as saves
    case = selection
    profile = load_profile(case.root)
    plan = VirtualLaunchPlan(case.root, profile['generation'], case.root / 'bin64/CrimsonDesert.exe',
        checksum(b'synthetic executable fingerprint'), generation_path(case.root, profile['generation']),
        checksum(encoded(profile)))
    monkeypatch.setattr(saves, 'save_root', lambda: case.working)
    backup = saves.backup_saves(plan)
    monkeypatch.setattr(saves, 'save_root', lambda: pytest.fail('Protocol read a live save location'))
    monkeypatch.setattr(saves, 'verify_backup', lambda *a, **kw: pytest.fail('Launch backup verification was weakened or reused'))
    value = prepare(case, backup_manifest=backup.directory / 'manifest.json', backup_sha256=backup.manifest_sha256)
    assert value['backup']['association'] == 'verified-selected-copy-association'
    case.slot.write_bytes(b'future copied trial changes')
    assert protocol._recovery(value, None) == protocol._records(case.original)
    assert value['unknowns']['producer'] == 'unknown'


def test_wrong_backup_association_and_logical_file_budget_refuse_without_output(selection, monkeypatch):
    case = selection
    with pytest.raises(VirtualLoaderError, match='together'):
        prepare(case, backup_sha256='a' * 64)
    assert not case.output.exists()
    monkeypatch.setattr(protocol, 'MAX_BYTES', 1)
    with pytest.raises(VirtualLoaderError, match='bounds'):
        prepare(case)
    assert not case.output.exists()


def test_powershell_rendering_roundtrips_literal_arguments():
    values = ["path with spaces/it's.save", '$HOME; Write-Output nope', '`tick', 'plain']
    argv = [sys.executable, '-c', 'import json,sys; print(json.dumps(sys.argv[1:]))', *values]
    rendered = protocol.powershell_command(argv)
    if os.name != 'nt':
        assert "''" in rendered and rendered.startswith('& ')
        return
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', rendered],
        capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == values


def test_preflight_refuses_recovery_members_that_share_working_file_identity(selection):
    case = selection
    original = case.original / case.slot.relative_to(case.working)
    original.unlink()
    os.link(case.slot, original)
    with pytest.raises(VirtualLoaderError, match='independent copies'):
        prepare(case)
    assert not case.output.exists()


def test_actual_receipt_inspection_cli_is_file_only_and_preserves_unknown_provenance(tmp_path):
    from cdmw.domain.virtual_session_receipt import inspect_receipt, seal_receipt
    from tests.test_virtual_session_receipt import observed_payload
    receipt = seal_receipt(observed_payload())
    path = tmp_path / 'transferred-receipt.json'
    path.write_bytes(receipt.data)
    run = subprocess.run([sys.executable, 'scripts/capture_virtual_save_evidence.py',
        'inspect-receipt', str(path)], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report == json.loads(json.dumps(inspect_receipt(receipt)))
    assert report['claims']['producer'] == 'unknown'
    assert report['claims']['produced_context'] == 'unknown'
    assert report['claims']['ancestry'] == 'unknown'
    assert path.read_bytes() == receipt.data


@pytest.mark.parametrize('bad', ['witness', 'oversized'])
def test_receipt_inspection_cli_refuses_witness_import_and_oversized_records(tmp_path, monkeypatch, capsys, bad):
    from scripts.capture_virtual_save_evidence import main
    path = tmp_path / 'untrusted-receipt.json'
    path.write_bytes(b'{"witness":{"finalized":true,"events_complete":true}}')
    if bad == 'oversized':
        monkeypatch.setattr(protocol, 'MAX_RECORD', 10)
    monkeypatch.setattr(sys, 'argv', ['capture_virtual_save_evidence.py', 'inspect-receipt', str(path)])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 2 and capsys.readouterr().err


def test_late_retention_cleanup_failure_keeps_published_outcome(selection, monkeypatch):
    case = selection
    value = prepare(case)
    through_attempt(case, value)
    actual = protocol.TemporaryDirectory
    class CleanupFailure(actual):
        def __exit__(self, *args):
            super().__exit__(*args)
            raise OSError('injected temporary cleanup failure')
    monkeypatch.setattr(protocol, 'TemporaryDirectory', CleanupFailure)
    result = protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'))
    assert result['identity'] and result['diagnostics']
    assert 'published' in result['diagnostics'][0]
    assert files_in(case.retained / 'files') == files_in(case.working)


def test_retention_rejects_a_resealed_chain_with_a_different_baseline(selection):
    from tests.test_virtual_save_evidence import reseal_chain
    case = selection
    value = prepare(case)
    values = through_attempt(case, value)
    values[0]['context']['executable_sha256'] = 'e' * 64
    for row in reseal_chain(values):
        protocol.capture_path(value, row['stage']).write_bytes(encoded(row))
    with pytest.raises(VirtualLoaderError, match='reviewed experiment'):
        protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'))
    assert not case.retained.exists()


@pytest.mark.parametrize('failure', ['no-marker', 'changed-marker', 'readback-io'])
def test_retention_cannot_report_success_without_verified_final_marker(selection, monkeypatch, failure):
    case = selection
    value = prepare(case)
    through_attempt(case, value)
    actual_link, actual_read = protocol.os.link, protocol._read_json
    marker = case.retained / 'manifest.json'
    def link(source, destination):
        if Path(destination) == marker and failure == 'no-marker':
            return None
        result = actual_link(source, destination)
        if Path(destination) == marker and failure == 'changed-marker':
            marker.write_bytes(b'{}')
        return result
    def read(path):
        if Path(path) == marker and failure == 'readback-io':
            raise OSError('injected final marker readback failure')
        return actual_read(path)
    monkeypatch.setattr(protocol.os, 'link', link)
    monkeypatch.setattr(protocol, '_read_json', read)
    with pytest.raises(VirtualLoaderError, match='retained.*could not be verified'):
        protocol.retain_attempt(case.output, protocol.capture_path(value, 'absent_saved'))
    assert files_in(case.retained / 'files') == files_in(case.working)
    assert evidence.read_capture(protocol.capture_path(value, 'absent_saved'))['stage'] == 'absent_saved'
    assert marker.exists() == (failure != 'no-marker')


@pytest.mark.parametrize('location', ['manifest', 'files-tree'])
def test_optional_backup_rejects_live_overlap_before_any_manifest_read(selection, monkeypatch, location):
    case = selection
    backup = case.output.parent / 'unreviewed-backup'
    if location == 'manifest':
        local = case.output.parent / 'owned-local'
        manifest = local / 'Pearl Abyss/CD/save/manifest.json'
    else:
        local = backup / 'files/owned-local'
        manifest = backup / 'manifest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b'{}')
    monkeypatch.setenv('LOCALAPPDATA', str(local))
    monkeypatch.setattr(protocol, '_read_json', lambda *a: pytest.fail('Live-overlapping backup manifest was read'))
    with pytest.raises(VirtualLoaderError, match='outside the live save folder'):
        prepare(case, backup_manifest=manifest, backup_sha256='a' * 64)
    assert not case.output.exists()
