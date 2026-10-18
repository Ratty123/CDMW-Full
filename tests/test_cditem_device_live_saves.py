"""Explicit live containment contracts on copied fixtures and fake OS observations.

Only the new module's native OS observation seams are replaced. The offline
public live-root refusal remains active throughout every fixture test.
"""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services import cditem_device_live_saves as live
from cdmw.services import cditem_device_saves as offline
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services import virtual_loader_receipts as receipts
from cdmw.domain.virtual_session_receipt import seal_receipt


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def reference(path):
    return {'path': str(path), 'sha256': digest(path.read_bytes())}


def json_file(root, name, value):
    return reference(put(root, name, canonical(value)))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    account = '1234567'
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    root = offline.saves.save_root()
    game, steam, evidence = tmp_path / 'game', tmp_path / 'steam', tmp_path / 'evidence'
    game_exe = put(game, 'bin64/CrimsonDesert.exe', b'exact game executable')
    steam_exe = put(steam, 'steam.exe', b'exact Steam executable')
    profile = put(game, '.cdmw/virtual-loader/profile.json', b'fixture exact profile')
    put(root, account + '/slot1/save.save', b'original progress')
    put(root, account + '/slot1/lobby.save', b'original lobby')
    put(root, account + '/steam_autocloud.vdf', ('"steam_autocloud.vdf" { "accountid" "' + account + '" }').encode())
    put(root, 'user_input.save', b'original shared input')
    (root / account / 'empty-slot').mkdir()
    test = tmp_path / 'test-input'
    shutil.copytree(root, test, copy_function=shutil.copy2)
    put(test, account + '/slot1/save.save', b'disposable save progress')
    config = put(steam, 'userdata/' + account + '/7/remote/sharedconfig.vdf',
                 b'"UserRoamingConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "3321460" { "cloudenabled" "0" } } } } } }')
    other_config = put(steam, 'userdata/7654321/7/remote/sharedconfig.vdf', b'"other" {}')
    run_id = 'cdrun-fixture-0001'
    process = {'pid': 901, 'created': 123456789, 'executable': str(steam_exe),
               'executable_sha256': digest(steam_exe.read_bytes()), 'session': 1}
    def observation(value):
        return {'format': 'cdmw_cditem_cloud_toggle_probe_v1', 'app_id': '3321460', 'records': {
            'target-sharedconfig': {'path': str(config), 'sha256': digest(config.read_bytes()),
                                    'app_subtree': {} if value is None else {'cloudenabled': value}},
            'other-sharedconfig': {'path': str(other_config), 'sha256': digest(other_config.read_bytes()),
                                   'app_subtree': {}}}}
    binding = {
        'intent': json_file(evidence, 'toggle-intent.json', {'app_id': 3321460,
                    'steam_process': process, 'original_per_game_cloud': True}),
        'before': json_file(evidence, 'toggle-before.json', observation(None)),
        'disabled': json_file(evidence, 'toggle-disabled.json', observation('0')),
        'restored': json_file(evidence, 'toggle-restored.json', observation('1'))}
    off = {'observation': json_file(evidence, 'current-off.json', observation('0')),
           'screenshot': reference(put(evidence, 'observed-off.png', b'fixture observed screenshot')),
           'config_sha256': digest(config.read_bytes())}
    shutdown = {'format': live.SHUTDOWN, 'run_id': run_id, 'method': 'normal_ui_exit',
                'observed_utc': datetime.now(timezone.utc).isoformat(),
                'steam_process': process, 'game_process': None, 'cloud_config_sha256': off['config_sha256'],
                'evidence': reference(put(evidence, 'normal-exit-observation.txt', b'fixture UI ordinary exit observation'))}
    shutdown_ref = json_file(evidence, 'shutdown.json', shutdown)
    request = {'format': live.REQUEST, 'run_id': run_id, 'game_root': str(game),
               'game_sha256': digest(game_exe.read_bytes()), 'steam_root': str(steam),
               'steam_sha256': digest(steam_exe.read_bytes()), 'profile_sha256': digest(profile.read_bytes()),
               'save_root': str(root), 'account_id': account,
               'run_manifest': json_file(evidence, 'execution.json', {'run_id': run_id, 'allowed': ['fixture']}),
               'account_binding': binding, 'cloud_off': off}
    request_ref = json_file(evidence, 'request.json', request)
    monkeypatch.setattr(live, '_known_save_root', lambda: root)
    monkeypatch.setattr(live, '_native_processes', lambda: [(os.getpid(), 4, 'fixture-runner.exe')])
    return {'root': root, 'test': test, 'run': tmp_path / 'context', 'request': request,
            'request_ref': request_ref, 'shutdown': shutdown, 'shutdown_ref': shutdown_ref,
            'evidence': evidence, 'config': config, 'process': process}


def prepare(setup, **kwargs):
    return live.prepare_live_context(setup['request_ref'], setup['test'], setup['run'],
                                     shutdown_receipt=setup['shutdown_ref'], **kwargs)


def owned_process(setup):
    return {**setup['process'], 'pid': 902, 'created': 987654321,
            'executable': str(Path(setup['request']['game_root']) / 'bin64/CrimsonDesert.exe'),
            'executable_sha256': setup['request']['game_sha256']}


def native_session_receipt(setup, process, *, token='a' * 32, captured_utc=None):
    """Use production receipt owners and a complete sealed chain, never fake text."""
    root = Path(setup['request']['game_root'])
    proposed = {'generation': 'b' * 32, 'profile_sha256': setup['request']['profile_sha256'],
                'compilation_identity': '1' * 64, 'compiler_sha256': '2' * 64,
                'executable_sha256': setup['request']['game_sha256'], 'game_build_sha256': None,
                'runtime': {'bootstrap': '3' * 64, 'loader': '4' * 64, 'host': None},
                'items': {}, 'physical_items': {}, 'sources_sha256': '5' * 64, 'underlay_sha256': '6' * 64}
    receipts.append_observation(root, token, 'begin', updates={'proposed': proposed})
    receipts.record_launch(root, token, 903, '7' * 64, host_sha256='8' * 64)
    report = {'state': 'running', 'error': 0, 'progress': 100, 'pid': process['pid'], 'host_pid': 903}
    status = put(root, '.cdmw/virtual-loader/session-' + token + '.json', canonical(report))
    selected, _ = receipts.record_status(root, token, SimpleNamespace(state='running'),
        host_pid=903, report=report, report_sha256=digest(status.read_bytes()))
    if captured_utc is not None:
        selected, _ = receipts.append_observation(root, token, 'runtime-status',
            updates={'captured_utc': captured_utc}, evidence=({'kind': 'runtime-status-file',
                'sha256': digest(status.read_bytes()), 'detail': 'Controlled stale historical fixture.'},))
    captured = reference(put(setup['evidence'], 'native-report-' + token + '.json', status.read_bytes()))
    outer = {'format': 'cdmw_cditem_owned_game_v1', 'run_id': setup['request']['run_id'],
             'process': process, 'session_token': token, 'native_status_evidence': reference(selected),
             'native_report': captured}
    return json_file(setup['evidence'], 'native-session-' + token + '.json', outer)


def renewal_evidence(setup, *, game_process=None, flag='0'):
    raw = setup['config'].read_bytes()
    if flag != '0':
        raw = raw.replace(b'"0"', b'"' + flag.encode() + b'"')
    setup['config'].write_bytes(raw + b'\n')
    config_sha = digest(setup['config'].read_bytes())
    observation = live._json_reference(setup['request']['cloud_off']['observation'])
    observation['run_id'] = setup['request']['run_id']
    observation['records']['target-sharedconfig']['sha256'] = config_sha
    observation['records']['target-sharedconfig']['app_subtree']['cloudenabled'] = flag
    cloud_off = {'observation': json_file(setup['evidence'], 'renewed-off.json', observation),
                 'screenshot': reference(put(setup['evidence'], 'renewed-off.png', b'new observed OFF screenshot')),
                 'config_sha256': config_sha}
    shutdown = {**setup['shutdown'], 'cloud_config_sha256': config_sha, 'game_process': game_process,
                'observed_utc': datetime.now(timezone.utc).isoformat()}
    return cloud_off, json_file(setup['evidence'], 'renewed-shutdown.json', shutdown)


def test_explicit_live_fixture_whole_tree_outputs_restore_and_offline_refusal(setup):
    root = setup['root']
    original = offline.snapshot_offline_root(root)
    with pytest.raises(VirtualLoaderError, match='live save tree'):
        offline.prepare_offline_context(root, setup['test'], setup['run'], quiescence=lambda: {})
    context = prepare(setup)
    assert live.preflight_live_context(context, shutdown_receipt=setup['shutdown_ref'])['ready_for_exchange']
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    put(root, setup['request']['account_id'] + '/slot0/save.save', b'post attempt autosave')
    put(root, 'user_input.save', b'test changed shared input')
    expected = offline.snapshot_offline_root(root)
    live.retain_live_outputs(context, expected, shutdown_receipt=setup['shutdown_ref'])
    live.restore_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    assert offline.snapshot_offline_root(root) == original
    assert offline.snapshot_offline_root(setup['run'] / 'output') == expected
    assert not os.path.samefile(root / 'user_input.save', setup['run'] / 'original/user_input.save')
    assert live.inspect_live_context(context)['phase'] == 'restored'


@pytest.mark.parametrize('change', ['cloud-on', 'cloud-config-hash', 'run-manifest', 'game', 'steam', 'profile', 'account-marker', 'receipt'])
def test_stale_binding_or_cloud_on_refuses_before_save_exchange(setup, change):
    context = prepare(setup)
    original = offline.snapshot_offline_root(setup['root'])
    request = setup['request']
    if change == 'cloud-on':
        setup['config'].write_bytes(setup['config'].read_bytes().replace(b'"0"', b'"1"'))
    elif change == 'cloud-config-hash':
        setup['config'].write_bytes(setup['config'].read_bytes() + b'\n')
    elif change == 'run-manifest':
        Path(request['run_manifest']['path']).write_bytes(b'{}')
    elif change in ('game', 'steam', 'profile'):
        path = {'game': Path(request['game_root']) / 'bin64/CrimsonDesert.exe',
                'steam': Path(request['steam_root']) / 'steam.exe',
                'profile': Path(request['game_root']) / '.cdmw/virtual-loader/profile.json'}[change]
        path.write_bytes(b'changed executable or profile')
    elif change == 'account-marker':
        (setup['run'] / 'original' / request['account_id'] / 'steam_autocloud.vdf').write_bytes(b'"steam_autocloud.vdf" { "accountid" "999" }')
    else:
        Path(setup['shutdown_ref']['path']).write_bytes(b'{}')
    with pytest.raises(VirtualLoaderError):
        live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    assert offline.snapshot_offline_root(setup['root']) == original
    assert not (setup['run'] / 'parked-original').exists()


@pytest.mark.parametrize('candidate', ['installed-steam', 'other-steam', 'unreadable', 'service', 'game', 'session'])
def test_native_candidate_is_verified_or_refused_never_inferred_absent_from_name(setup, monkeypatch, candidate):
    context = prepare(setup)
    original = offline.snapshot_offline_root(setup['root'])
    name = {'game': 'CrimsonDesert.exe', 'session': 'cdmw_virtual_session.exe', 'service': 'steamservice.exe'}.get(candidate, 'steam.exe')
    monkeypatch.setattr(live, '_native_processes', lambda: [(77, 4, name), (os.getpid(), 4, 'runner.exe')])
    def identity(pid):
        if candidate in ('unreadable', 'service'):
            raise OSError('protected candidate')
        path = (Path(setup['request']['steam_root']) / 'steam.exe' if candidate == 'installed-steam'
                else setup['evidence'] / ('foreign-' + name))
        return {**setup['process'], 'pid': pid, 'executable': str(path)}
    monkeypatch.setattr(live, '_process_identity', identity)
    with pytest.raises(VirtualLoaderError, match='unknown|still running'):
        live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    assert offline.snapshot_offline_root(setup['root']) == original


@pytest.mark.parametrize('stage', ['disabled', 'restored'])
def test_causal_toggle_must_change_one_matching_account_only(setup, stage):
    observation = live._json_reference(setup['request']['account_binding'][stage])
    observation['records']['other-sharedconfig']['app_subtree'] = {'cloudenabled': '0'}
    setup['request']['account_binding'][stage] = json_file(setup['evidence'], 'ambiguous-toggle.json', observation)
    setup['request_ref'] = json_file(setup['evidence'], 'ambiguous-request.json', setup['request'])
    before = offline.snapshot_offline_root(setup['root'])
    with pytest.raises(VirtualLoaderError, match='uniquely bind'):
        prepare(setup)
    assert offline.snapshot_offline_root(setup['root']) == before
    assert not setup['run'].exists()


@pytest.mark.parametrize('change', ['stale', 'future', 'missing', 'wrong-birth'])
def test_shutdown_evidence_requires_fresh_timestamp_and_actual_process_birth(setup, monkeypatch, change):
    context = prepare(setup)
    receipt = dict(setup['shutdown'])
    if change == 'stale':
        receipt['observed_utc'] = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    elif change == 'future':
        receipt['observed_utc'] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    elif change == 'missing':
        receipt.pop('observed_utc')
    else:
        monkeypatch.setattr(live, '_native_processes', lambda: [
            (setup['process']['pid'], 4, 'steam.exe'), (os.getpid(), 4, 'runner.exe')])
        monkeypatch.setattr(live, '_process_identity', lambda pid: {**setup['process'], 'created': setup['process']['created'] + 1})
    shutdown = json_file(setup['evidence'], 'invalid-shutdown.json', receipt)
    with pytest.raises(VirtualLoaderError, match='fresh timestamped|still running'):
        live.exchange_live_context(context, shutdown_receipt=shutdown)
    assert not (setup['run'] / 'parked-original').exists()


def test_shared_input_addition_is_refused_and_native_census_error_is_not_absence(setup, monkeypatch):
    put(setup['test'], 'unexpected-shared.save', b'not part of target account')
    with pytest.raises(VirtualLoaderError, match='preserve the exact account marker and shared'):
        prepare(setup)
    (setup['test'] / 'unexpected-shared.save').unlink()
    def failed_census():
        raise VirtualLoaderError('incomplete native census')
    monkeypatch.setattr(live, '_native_processes', failed_census)
    with pytest.raises(VirtualLoaderError, match='incomplete native census'):
        prepare(setup)
    assert not setup['run'].exists()


@pytest.mark.parametrize('phase', ['exchange-first', 'exchange-second', 'restore-first', 'restore-second'])
def test_live_fixture_interrupted_rename_recovery_uses_fresh_native_guard(setup, monkeypatch, phase):
    original = offline.snapshot_offline_root(setup['root'])
    context = prepare(setup)
    if phase.startswith('restore'):
        live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    rename = Path.rename
    count = 0
    def fail_after_rename(path, destination):
        nonlocal count
        result = rename(path, destination)
        count += 1
        if count == (1 if phase.endswith('first') else 2):
            raise RuntimeError('fixture interpreter interruption')
        return result
    monkeypatch.setattr(Path, 'rename', fail_after_rename)
    action = live.restore_live_context if phase.startswith('restore') else live.exchange_live_context
    with pytest.raises(RuntimeError, match='interpreter interruption'):
        action(context, shutdown_receipt=setup['shutdown_ref'])
    monkeypatch.setattr(Path, 'rename', rename)
    restarted = live.LiveSaveContext(setup['run'], context.manifest_sha256)
    live.recover_live_context(restarted, shutdown_receipt=setup['shutdown_ref'])
    assert offline.snapshot_offline_root(setup['root']) == original


def test_recreated_root_between_renames_is_preserved_with_parked_original(setup, monkeypatch):
    context = prepare(setup)
    original = offline.snapshot_offline_root(setup['root'])
    rename = Path.rename
    def recreate(path, destination):
        result = rename(path, destination)
        if path == setup['root']:
            put(setup['root'], 'unexpected.save', b'concurrent unknown writer')
        return result
    monkeypatch.setattr(Path, 'rename', recreate)
    with pytest.raises(VirtualLoaderError, match='Unexpected'):
        live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    assert (setup['root'] / 'unexpected.save').read_bytes() == b'concurrent unknown writer'
    assert offline.snapshot_offline_root(setup['run'] / 'parked-original') == original
    assert offline.snapshot_offline_root(setup['run'] / 'original') == original
    with pytest.raises(VirtualLoaderError, match='Unknown concurrent'):
        live.recover_live_context(context, shutdown_receipt=setup['shutdown_ref'])


def test_new_writer_between_renames_stops_and_fresh_recovery_restores(setup, monkeypatch):
    context = prepare(setup)
    original = offline.snapshot_offline_root(setup['root'])
    monkeypatch.setattr(live, '_native_processes', lambda: (
        [(77, 4, 'steam.exe'), (os.getpid(), 4, 'runner.exe')]
        if (setup['run'] / 'parked-original').exists() else [(os.getpid(), 4, 'runner.exe')]))
    monkeypatch.setattr(live, '_process_identity', lambda pid: {**setup['process'], 'pid': pid})
    with pytest.raises(VirtualLoaderError, match='still running'):
        live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    assert not setup['root'].exists()
    assert offline.snapshot_offline_root(setup['run'] / 'parked-original') == original
    monkeypatch.setattr(live, '_native_processes', lambda: [(os.getpid(), 4, 'runner.exe')])
    live.recover_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    assert offline.snapshot_offline_root(setup['root']) == original


def test_restore_recreated_root_is_preserved_after_test_tree_is_parked(setup, monkeypatch):
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    expected = offline.snapshot_offline_root(setup['root'])
    original = offline.snapshot_offline_root(setup['run'] / 'original')
    rename = Path.rename
    def recreate(path, destination):
        result = rename(path, destination)
        if path == setup['root']:
            put(setup['root'], 'new-unexpected.save', b'new writer during restoration')
        return result
    monkeypatch.setattr(Path, 'rename', recreate)
    with pytest.raises(VirtualLoaderError, match='Unexpected'):
        live.restore_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    assert (setup['root'] / 'new-unexpected.save').read_bytes() == b'new writer during restoration'
    assert offline.snapshot_offline_root(setup['run'] / 'parked-test') == expected
    assert offline.snapshot_offline_root(setup['run'] / 'parked-original') == original


@pytest.mark.parametrize('failure', ['copy', 'after-publish'])
def test_interrupted_output_retention_can_resume_without_replacing_unknown_output(setup, monkeypatch, failure):
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    put(setup['root'], setup['request']['account_id'] + '/slot0/save.save', b'post attempt output')
    expected = offline.snapshot_offline_root(setup['root'])
    copy, rename = offline.saves._copy, Path.rename
    def broken_copy(*args):
        result = copy(*args)
        raise RuntimeError('interrupted copied output')
    def broken_rename(path, destination):
        result = rename(path, destination)
        if Path(destination) == setup['run'] / 'output':
            raise RuntimeError('interrupted after output publication')
        return result
    if failure == 'copy':
        monkeypatch.setattr(offline.saves, '_copy', broken_copy)
    else:
        monkeypatch.setattr(Path, 'rename', broken_rename)
    with pytest.raises(RuntimeError, match='interrupted'):
        live.retain_live_outputs(context, expected, shutdown_receipt=setup['shutdown_ref'])
    monkeypatch.setattr(offline.saves, '_copy', copy)
    monkeypatch.setattr(Path, 'rename', rename)
    assert offline.snapshot_offline_root(setup['root']) == expected
    live.retain_live_outputs(context, expected, shutdown_receipt=setup['shutdown_ref'])
    assert offline.snapshot_offline_root(setup['run'] / 'output') == expected
    live.restore_live_context(context, shutdown_receipt=setup['shutdown_ref'])


def test_owned_game_binding_and_shutdown_require_exact_birth_and_session(setup, monkeypatch):
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    process = owned_process(setup)
    session = native_session_receipt(setup, process)
    monkeypatch.setattr(live, '_process_identity', lambda pid: {**process, 'created': process['created'] + 1})
    with pytest.raises(VirtualLoaderError, match='process changed'):
        live.bind_live_game(context, process, session_receipt=session)
    monkeypatch.setattr(live, '_process_identity', lambda pid: process)
    live.bind_live_game(context, process, session_receipt=session)
    with pytest.raises(VirtualLoaderError, match='ordinary Steam/game shutdown'):
        live.restore_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    receipt = json_file(setup['evidence'], 'game-exited.json', {**setup['shutdown'], 'game_process': process})
    live.restore_live_context(context, shutdown_receipt=receipt)


@pytest.mark.parametrize('fault', ['failed-json', 'wrong-token', 'wrong-profile', 'wrong-pid', 'wrong-host',
                                   'report-digest', 'not-chain-member', 'incomplete-chain', 'current-status',
                                   'mutable-report', 'historical-pid', 'terminal-chain', 'chain-host'])
def test_native_binding_rejects_unrelated_failed_or_historical_evidence(setup, monkeypatch, fault):
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    process = owned_process(setup)
    if fault == 'historical-pid':
        now = datetime.now(timezone.utc) - datetime(1601, 1, 1, tzinfo=timezone.utc)
        process['created'] = (now.days * 86400 + now.seconds) * 10_000_000
    session = native_session_receipt(setup, process,
        captured_utc='2020-01-01T00:00:00Z' if fault == 'historical-pid' else None)
    outer = live._json_reference(session)
    value = live.decode_receipt(live._reference(outer['native_status_evidence'])).to_dict()
    root = Path(setup['request']['game_root'])
    if fault == 'failed-json':
        outer['native_status_evidence'] = json_file(setup['evidence'], 'failed-native.json', {
            'native_status': 'failed', 'run_id': 'different-run', 'session_token': 'b' * 32,
            'pid': 999, 'profile_sha256': 'f' * 64})
    elif fault == 'wrong-token':
        outer['session_token'] = 'b' * 32
    elif fault in ('wrong-profile', 'not-chain-member'):
        value.pop('identity')
        if fault == 'wrong-profile':
            value['proposed']['profile_sha256'] = 'f' * 64
        else:
            value['diagnostics'].append('Sealed but never published as this chain member.')
        bad = seal_receipt(value)
        outer['native_status_evidence'] = reference(put(setup['evidence'], 'unrelated-sealed.json', bad.data))
    elif fault in ('wrong-pid', 'wrong-host', 'report-digest'):
        report = live._json_reference(outer['native_report'])
        if fault == 'wrong-pid':
            report['pid'] = 999
        elif fault == 'wrong-host':
            report['host_pid'] = 999
        else:
            report['detail'] = 'Different captured bytes with the same apparent success.'
        outer['native_report'] = json_file(setup['evidence'], 'wrong-report.json', report)
    elif fault == 'incomplete-chain':
        (root / receipts.RECEIPT_PATH / ('a' * 32) / '0000.json').unlink()
    elif fault == 'current-status':
        (root / '.cdmw/virtual-loader' / ('session-' + 'a' * 32 + '.json')).write_bytes(canonical({'state': 'stopped'}))
    elif fault == 'mutable-report':
        outer['native_report'] = reference(root / '.cdmw/virtual-loader' / ('session-' + 'a' * 32 + '.json'))
    elif fault == 'terminal-chain':
        stopped = {'state': 'stopped', 'pid': process['pid'], 'host_pid': 903, 'error': 0, 'progress': 100}
        receipts.record_status(root, 'a' * 32, SimpleNamespace(state='stopped'), host_pid=903,
                               report=stopped, report_sha256=digest(canonical(stopped)))
    elif fault == 'chain-host':
        receipts.append_observation(root, 'a' * 32, 'operator-capture',
            updates={'process': {**value['process'], 'host_pid': 999}})
    session = json_file(setup['evidence'], 'rejected-native.json', outer)
    monkeypatch.setattr(live, '_process_identity', lambda pid: process)
    before = (setup['run'] / 'journal.json').read_bytes()
    with pytest.raises(VirtualLoaderError):
        live.bind_live_game(context, process, session_receipt=session)
    assert (setup['run'] / 'journal.json').read_bytes() == before
    assert live.inspect_live_context(context)['owned_game'] is None


@pytest.mark.parametrize('fault', ['orphan', 'different-process', 'different-run', 'different-token', 'missing-chain'])
def test_bound_context_revalidates_immutable_session_semantics_on_load(setup, monkeypatch, fault):
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    process = owned_process(setup)
    session = native_session_receipt(setup, process)
    monkeypatch.setattr(live, '_process_identity', lambda pid: process)
    live.bind_live_game(context, process, session_receipt=session)
    journal = json.loads((setup['run'] / 'journal.json').read_bytes())
    if fault == 'orphan':
        journal['owned_game'] = None
    elif fault == 'different-process':
        journal['owned_game']['created'] += 1
    elif fault in ('different-run', 'different-token'):
        outer = live._json_reference(session)
        outer['run_id' if fault == 'different-run' else 'session_token'] = 'other-run' if fault == 'different-run' else 'b' * 32
        journal['session_receipt'] = json_file(setup['evidence'], 'mismatched-session.json', outer)
    else:
        root = Path(setup['request']['game_root'])
        (root / receipts.RECEIPT_PATH / ('a' * 32) / '0000.json').unlink()
    (setup['run'] / 'journal.json').write_bytes(canonical(journal))
    before = offline.snapshot_offline_root(setup['root'])
    with pytest.raises(VirtualLoaderError):
        live.inspect_live_context(context)
    with pytest.raises(VirtualLoaderError):
        live.restore_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    assert offline.snapshot_offline_root(setup['root']) == before


def test_bound_receipt_remains_valid_after_ordinary_exit_changes_mutable_status(setup, monkeypatch):
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    process = owned_process(setup)
    session = native_session_receipt(setup, process)
    monkeypatch.setattr(live, '_process_identity', lambda pid: process)
    live.bind_live_game(context, process, session_receipt=session)
    root = Path(setup['request']['game_root'])
    report = {'state': 'stopped', 'pid': process['pid'], 'host_pid': 903, 'error': 0, 'progress': 100}
    status = root / '.cdmw/virtual-loader' / ('session-' + 'a' * 32 + '.json')
    status.write_bytes(canonical(report))
    receipts.record_status(root, 'a' * 32, SimpleNamespace(state='stopped'), host_pid=903,
                           report=report, report_sha256=digest(status.read_bytes()))
    assert live.inspect_live_context(context)['owned_game'] == process
    shutdown = json_file(setup['evidence'], 'bound-game-exited.json', {**setup['shutdown'], 'game_process': process})
    live.restore_live_context(context, shutdown_receipt=shutdown)


def test_cloud_evidence_renewal_preserves_all_save_game_and_request_state_then_restores(setup):
    context = prepare(setup)
    original = offline.snapshot_offline_root(setup['root'])
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    before_journal = json.loads((setup['run'] / 'journal.json').read_bytes())
    request_before = Path(setup['request_ref']['path']).read_bytes()
    root_before = offline.snapshot_offline_root(setup['root'])
    cloud_off, shutdown = renewal_evidence(setup)
    with pytest.raises(VirtualLoaderError, match='exact persisted'):
        live.restore_live_context(context, shutdown_receipt=shutdown)
    result = live.refresh_live_cloud_evidence(context, cloud_off, shutdown_receipt=shutdown)
    after_journal = json.loads((setup['run'] / 'journal.json').read_bytes())
    assert {key: value for key, value in after_journal.items() if key != 'cloud_renewals'} == before_journal
    assert after_journal['cloud_renewals'][0]['previous'] == digest(canonical(setup['request']['cloud_off']))
    assert after_journal['cloud_renewals'][0]['identity'] == result['renewal_identity']
    assert Path(setup['request_ref']['path']).read_bytes() == request_before
    assert offline.snapshot_offline_root(setup['root']) == root_before
    assert offline.snapshot_offline_root(setup['run'] / 'original') == original
    live.restore_live_context(context, shutdown_receipt=shutdown)
    assert offline.snapshot_offline_root(setup['root']) == original


def test_cloud_renewal_preserves_existing_owned_game_and_sealed_session_binding(setup, monkeypatch):
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    process = owned_process(setup)
    session = native_session_receipt(setup, process)
    monkeypatch.setattr(live, '_process_identity', lambda pid: process)
    live.bind_live_game(context, process, session_receipt=session)
    journal_before = json.loads((setup['run'] / 'journal.json').read_bytes())
    cloud_off, shutdown = renewal_evidence(setup, game_process=process)
    live.refresh_live_cloud_evidence(context, cloud_off, shutdown_receipt=shutdown)
    journal_after = json.loads((setup['run'] / 'journal.json').read_bytes())
    assert journal_after['owned_game'] == journal_before['owned_game'] == process
    assert journal_after['session_receipt'] == journal_before['session_receipt'] == session
    live.restore_live_context(context, shutdown_receipt=shutdown)


@pytest.mark.parametrize('phase', ['exchange', 'restore'])
def test_cloud_renewal_permits_fresh_recovery_of_recognized_interrupted_rename(setup, monkeypatch, phase):
    context = prepare(setup)
    original = offline.snapshot_offline_root(setup['root'])
    if phase == 'restore':
        live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    rename = Path.rename
    def interrupt(path, destination):
        result = rename(path, destination)
        if path == setup['root']:
            raise RuntimeError('interrupted after first rename')
        return result
    monkeypatch.setattr(Path, 'rename', interrupt)
    with pytest.raises(RuntimeError, match='interrupted'):
        (live.exchange_live_context if phase == 'exchange' else live.restore_live_context)(context, shutdown_receipt=setup['shutdown_ref'])
    monkeypatch.setattr(Path, 'rename', rename)
    cloud_off, shutdown = renewal_evidence(setup)
    live.refresh_live_cloud_evidence(context, cloud_off, shutdown_receipt=shutdown)
    live.recover_live_context(context, shutdown_receipt=shutdown)
    assert offline.snapshot_offline_root(setup['root']) == original


@pytest.mark.parametrize('fault', ['on', 'account', 'run', 'profile', 'tampered', 'writer', 'game'])
def test_cloud_renewal_refuses_unrelated_or_unverified_evidence_without_journal_changes(setup, monkeypatch, fault):
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    cloud_off, shutdown = renewal_evidence(setup, flag='1' if fault == 'on' else '0')
    if fault == 'account':
        observation = live._json_reference(cloud_off['observation'])
        observation['records'].pop('target-sharedconfig')
        cloud_off['observation'] = json_file(setup['evidence'], 'wrong-account-off.json', observation)
    elif fault == 'run':
        value = live._json_reference(shutdown)
        value['run_id'] = 'different-run'
        shutdown = json_file(setup['evidence'], 'wrong-run-shutdown.json', value)
    elif fault == 'profile':
        (Path(setup['request']['game_root']) / '.cdmw/virtual-loader/profile.json').write_bytes(b'new unrelated profile')
    elif fault == 'tampered':
        Path(cloud_off['screenshot']['path']).write_bytes(b'changed screenshot')
    elif fault == 'writer':
        monkeypatch.setattr(live, '_native_processes', lambda: [(77, 4, 'steamservice.exe')])
        monkeypatch.setattr(live, '_process_identity', lambda pid: (_ for _ in ()).throw(OSError('unreadable writer')))
    elif fault == 'game':
        value = live._json_reference(shutdown)
        value['game_process'] = owned_process(setup)
        shutdown = json_file(setup['evidence'], 'wrong-game-shutdown.json', value)
    journal = (setup['run'] / 'journal.json').read_bytes()
    before = offline.snapshot_offline_root(setup['root'])
    with pytest.raises(VirtualLoaderError):
        live.refresh_live_cloud_evidence(context, cloud_off, shutdown_receipt=shutdown)
    assert (setup['run'] / 'journal.json').read_bytes() == journal
    assert offline.snapshot_offline_root(setup['root']) == before


def test_renewal_does_not_authorize_restoring_unknown_save_tree_and_history_is_checked(setup):
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    put(setup['root'], 'unexpected.save', b'unknown bytes stay preserved')
    before = offline.snapshot_offline_root(setup['root'])
    cloud_off, shutdown = renewal_evidence(setup)
    live.refresh_live_cloud_evidence(context, cloud_off, shutdown_receipt=shutdown)
    with pytest.raises(VirtualLoaderError, match='Unexpected'):
        live.restore_live_context(context, shutdown_receipt=shutdown)
    with pytest.raises(VirtualLoaderError, match='Unknown concurrent'):
        live.recover_live_context(context, shutdown_receipt=shutdown)
    assert offline.snapshot_offline_root(setup['root']) == before
    journal = json.loads((setup['run'] / 'journal.json').read_bytes())
    journal['cloud_renewals'][0]['previous'] = '0' * 64
    (setup['run'] / 'journal.json').write_bytes(canonical(journal))
    with pytest.raises(VirtualLoaderError, match='renewal chain changed'):
        live.inspect_live_context(context)


def test_cancelled_live_preparation_does_not_touch_live_fixture(setup):
    original = offline.snapshot_offline_root(setup['root'])
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        prepare(setup, stop_event=stop)
    assert offline.snapshot_offline_root(setup['root']) == original


def test_context_lane_serializes_game_binding_and_save_journal_operations(setup):
    from concurrent.futures import ThreadPoolExecutor
    from cdmw.services.installation_lane import installation_lane
    context = prepare(setup)
    live.exchange_live_context(context, shutdown_receipt=setup['shutdown_ref'])
    before = offline.snapshot_offline_root(setup['root'])
    with installation_lane(setup['run']):
        with ThreadPoolExecutor(max_workers=1) as executor:
            task = executor.submit(live.restore_live_context, context, shutdown_receipt=setup['shutdown_ref'])
            with pytest.raises(VirtualLoaderError, match='in use'):
                task.result(timeout=5)
    assert offline.snapshot_offline_root(setup['root']) == before
    live.restore_live_context(context, shutdown_receipt=setup['shutdown_ref'])


def test_python_installation_lane_excludes_the_native_host_byte_zero_lock(setup):
    if os.name != 'nt':
        return
    import ctypes as C
    from ctypes import wintypes as W
    from cdmw.services.installation_lane import installation_lane, lock_path
    class Overlapped(C.Structure):
        _fields_ = [('internal', C.c_size_t), ('internal_high', C.c_size_t),
                    ('offset', W.DWORD), ('offset_high', W.DWORD), ('event', W.HANDLE)]
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.LockFileEx.argtypes = [W.HANDLE, W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.POINTER(Overlapped)]
    kernel.LockFileEx.restype = W.BOOL
    kernel.UnlockFileEx.argtypes = [W.HANDLE, W.DWORD, W.DWORD, W.DWORD, C.POINTER(Overlapped)]
    kernel.UnlockFileEx.restype = W.BOOL
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    root = Path(setup['request']['game_root'])
    def native_attempt(expected):
        handle = kernel.CreateFileW(str(lock_path(root)), 0x80000000 | 0x40000000, 3, None, 4, 0x80, None)
        assert handle != C.c_void_p(-1).value
        operation = Overlapped()
        try:
            result = bool(kernel.LockFileEx(handle, 3, 0, 1, 0, C.byref(operation)))
            assert result is expected
            if result:
                assert kernel.UnlockFileEx(handle, 0, 1, 0, C.byref(operation))
            else:
                assert C.get_last_error() == 33
        finally:
            kernel.CloseHandle(handle)
    with installation_lane(root):
        native_attempt(False)
    native_attempt(True)
