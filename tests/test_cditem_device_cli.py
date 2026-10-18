from copy import deepcopy
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

from cdmw.services import cditem_device_cli as cli
from cdmw.services import cditem_device_execution as execution
from cdmw.services import cditem_device_review as review
from cdmw.services import cditem_device_windows as windows
from cdmw.services.cditem_device_runner import DeviceRunError
from cdmw.services.independent_item_package import canonical, digest


def reference(path):
    return {'path': str(path), 'sha256': digest(path.read_bytes())}


@pytest.fixture
def inspected(tmp_path, monkeypatch):
    manifest = tmp_path / 'execution.json'
    manifest.write_bytes(canonical({'run_id': 'cditem-review-test'}))
    template = tmp_path / 'template.png'
    image = Image.new('RGB', (96, 64), (20, 30, 40))
    image.paste((230, 230, 230), (10, 10, 38, 22))
    image.save(template)
    frame = tmp_path / 'fresh.png'
    image.save(frame)
    value = {'format': review.FORMAT, 'execution': reference(manifest), 'sequence': 7,
             'template': reference(template), 'regions': [[8, 8, 40, 24]],
             'max_mean_error': 3, 'light_text': True,
             'classification': {'screen': 'title_keyboard', 'control': 'press_e', 'point': None,
                                'save_id': '', 'gameplay_witness': '', 'scenario': '', 'assertion': ''},
             'inspection': 'Synthetic prompt region for policy validation only.'}
    request = tmp_path / 'review.json'
    def write(value=value):
        request.write_bytes(canonical(value))
        return reference(request)
    receipt = {'run_id': 'cditem-review-test', 'sequence': 7, 'path': str(frame),
               'sha256': digest(frame.read_bytes()), 'window': {'hwnd': 123}}
    monkeypatch.setattr(windows, '_api', lambda: (None, SimpleNamespace(GetForegroundWindow=lambda: 123)))
    return SimpleNamespace(value=value, write=write, execution=reference(manifest), receipt=receipt,
                           frame=frame, image=image, template=template, request=request)


def test_review_matches_one_fresh_frame_and_derives_foreground(inspected, monkeypatch):
    s = inspected
    observer = review.ReviewedFrameObserver(s.write(), s.execution)
    value = observer(deepcopy(s.receipt))
    assert value == {**s.value['classification'], 'foreground': True}
    assert observer.evidence()['matches'][0]['mean_absolute_errors'] == [0.0]
    assert observer(deepcopy(s.receipt)) is None
    observer = review.ReviewedFrameObserver(s.write(), s.execution)
    monkeypatch.setattr(windows, '_api', lambda: (None, SimpleNamespace(GetForegroundWindow=lambda: 999)))
    assert observer(deepcopy(s.receipt))['foreground'] is False


@pytest.mark.parametrize('failure', ['pixels', 'dimensions'])
def test_unmatched_review_pauses_without_a_classification(inspected, failure):
    s = inspected
    observer = review.ReviewedFrameObserver(s.write(), s.execution)
    image = Image.new('RGB', (80, 64) if failure == 'dimensions' else (96, 64), (0, 0, 0))
    image.save(s.frame)
    s.receipt['sha256'] = digest(s.frame.read_bytes())
    assert observer(s.receipt) is None
    assert observer.evidence()['matches'][0]['matched'] is False
    assert observer(s.receipt) is None


@pytest.mark.parametrize('failure', ['review_hash', 'template_hash', 'execution_hash', 'execution_path',
                                    'sequence', 'classification', 'foreground', 'region', 'regions',
                                    'threshold', 'light_pixels', 'inspection', 'point', 'extra'])
def test_invalid_review_refuses_before_execution(inspected, failure, tmp_path):
    s = inspected
    value = deepcopy(s.value)
    if failure == 'review_hash':
        request = s.write(value)
        request['sha256'] = '0' * 64
    else:
        if failure == 'template_hash':
            value['template']['sha256'] = '0' * 64
        elif failure == 'execution_hash':
            value['execution']['sha256'] = '0' * 64
        elif failure == 'execution_path':
            path = tmp_path / 'other.json'; path.write_bytes(Path(s.execution['path']).read_bytes())
            value['execution'] = reference(path)
        elif failure == 'sequence':
            value['sequence'] = True
        elif failure == 'classification':
            value['classification']['screen'] = 'modal'
        elif failure == 'foreground':
            value['classification']['foreground'] = True
        elif failure == 'region':
            value['regions'] = [[-1, 0, 2, 2]]
        elif failure == 'regions':
            value['regions'] *= 9
        elif failure == 'threshold':
            value['max_mean_error'] = 8.01
        elif failure == 'light_pixels':
            value['regions'] = [[0, 0, 4, 4]]
        elif failure == 'inspection':
            value['inspection'] = ' '
        elif failure == 'point':
            value['classification']['point'] = [96, 0]
        elif failure == 'extra':
            value['key'] = 'E'
        request = s.write(value)
    with pytest.raises(DeviceRunError):
        review.ReviewedFrameObserver(request, s.execution)


@pytest.mark.parametrize('failure', ['run', 'sequence', 'frame_hash'])
def test_stale_or_changed_capture_cannot_use_review(inspected, failure):
    s = inspected
    observer = review.ReviewedFrameObserver(s.write(), s.execution)
    receipt = deepcopy(s.receipt)
    if failure == 'run':
        receipt['run_id'] = 'another-run'
    elif failure == 'sequence':
        receipt['sequence'] += 1
    else:
        s.frame.write_bytes(b'changed frame')
    with pytest.raises(DeviceRunError):
        observer(receipt)
    assert observer(s.receipt) is None


def test_review_freezes_inspected_pixels_and_classification(inspected):
    s = inspected
    observer = review.ReviewedFrameObserver(s.write(), s.execution)
    s.value['classification']['control'] = 'open_load'
    s.request.write_bytes(b'changed after immutable read')
    s.template.write_bytes(b'changed after immutable read')
    assert observer(s.receipt)['control'] == 'press_e'
    evidence = observer.evidence()
    evidence['matches'].clear()
    assert len(observer.evidence()['matches']) == 1


def test_cli_review_runs_one_action_then_fresh_capture(inspected, monkeypatch, tmp_path):
    s = inspected
    calls = []
    def execute(ref, *, resume, observer, steps):
        calls.append((ref, resume, steps))
        assert observer(s.receipt)['control'] == 'press_e'
        assert observer(s.receipt) is None
        return {'status': 'paused', 'actions_recorded': 1, 'acceptance': 'not_established'}
    monkeypatch.setattr(execution, 'execute_execution', execute)
    output = tmp_path / 'result.json'
    request = s.write()
    assert cli.main(['--output', str(output), 'resume', s.execution['path'], '--manifest-sha256',
                     s.execution['sha256'], '--review', request['path'], '--review-sha256', request['sha256']]) == 0
    assert calls == [(s.execution, True, 2)]
    assert json.loads(output.read_bytes())['frame_review']['matches'][0]['matched']
    assert not list(tmp_path.glob('*.pending'))


def test_cli_retains_review_evidence_after_action_failure(inspected, monkeypatch, tmp_path):
    s = inspected
    def execute(ref, *, resume, observer, steps):
        assert observer(s.receipt)
        raise DeviceRunError('The foreground changed before input.')
    monkeypatch.setattr(execution, 'execute_execution', execute)
    output = tmp_path / 'failed.json'
    request = s.write()
    assert cli.main(['--output', str(output), 'execute', s.execution['path'], '--manifest-sha256',
                     s.execution['sha256'], '--review', request['path'], '--review-sha256', request['sha256']]) == 2
    result = json.loads(output.read_bytes())
    assert result['frame_review']['matches'][0]['matched']
    assert result['error'] == 'The foreground changed before input.'
    assert result['acceptance'] == 'not_established'


@pytest.mark.parametrize('failure', ['existing', 'relative', 'missing_parent', 'extension', 'no_output'])
def test_invalid_output_refuses_before_any_service_call(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(cli, '_run', lambda *a: pytest.fail('Invalid output reached execution.'))
    path = tmp_path / 'result.json'
    if failure == 'existing':
        path.write_bytes(b'keep existing evidence')
    elif failure == 'relative':
        path = Path('result.json')
    elif failure == 'missing_parent':
        path = tmp_path / 'absent/result.json'
    elif failure == 'extension':
        path = tmp_path / 'result.bin'
    if failure == 'no_output':
        monkeypatch.setattr(sys, 'stdout', None)
    args = [] if failure == 'no_output' else ['--output', str(path)]
    assert cli.main(args + ['inspect']) == 2
    if failure == 'existing':
        assert path.read_bytes() == b'keep existing evidence'


def test_output_publication_refuses_a_competing_file_without_replay(tmp_path, monkeypatch):
    path = tmp_path / 'result.json'
    calls = []
    def execute(args, evidence):
        calls.append('one execution only')
        path.write_bytes(b'competing evidence')
        return {'status': 'paused'}
    monkeypatch.setattr(cli, '_run', execute)
    assert cli.main(['--output', str(path), 'inspect']) == 2
    assert calls == ['one execution only']
    assert path.read_bytes() == b'competing evidence'
    assert not list(tmp_path.glob('*.pending'))


def test_windowed_errors_are_written_without_stdout_or_stderr(tmp_path, monkeypatch):
    path = tmp_path / 'error.json'
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    assert cli.main(['--output', str(path), 'preflight', str(tmp_path / 'absent.json'),
                     '--manifest-sha256', '0' * 64]) == 2
    assert json.loads(path.read_bytes())['acceptance'] == 'not_established'


@pytest.mark.parametrize('error', [EOFError('Capture pipe closed.'), RuntimeError('Capture process failed.')])
def test_cli_retains_pipe_and_operational_errors_without_replaying(tmp_path, monkeypatch, error):
    path, calls = tmp_path / 'failure.json', []
    def execute(args, evidence):
        calls.append('one invocation')
        evidence.update({'review': {'sha256': 'a' * 64}, 'matches': [{'matched': True}]})
        raise error
    monkeypatch.setattr(cli, '_run', execute)
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    assert cli.main(['--output', str(path), 'inspect']) == 2
    result = json.loads(path.read_bytes())
    assert result['error_type'] == type(error).__name__ and result['error'] == str(error)
    assert result['frame_review']['matches'][0]['matched']
    assert result['acceptance'] == 'not_established' and calls == ['one invocation']
    assert not list(tmp_path.glob('*.pending'))


@pytest.mark.parametrize('option', ['--review', '--review-sha256'])
def test_partial_review_reference_never_reaches_execution(tmp_path, monkeypatch, option):
    monkeypatch.setattr(execution, 'execute_execution', lambda *a, **k: pytest.fail('Unbound review executed.'))
    assert cli.main(['execute', str(tmp_path / 'manifest.json'), '--manifest-sha256', '0' * 64,
                     option, str(tmp_path / 'review.json') if option == '--review' else '0' * 64]) == 2


@pytest.mark.parametrize('frozen', [False, True])
def test_portable_device_mode_routes_before_app_job_gui_and_reaper(monkeypatch, frozen):
    from cdmw.app import bootstrap
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    def forbidden(*a, **kw):
        pytest.fail('Device mode entered normal application startup.')
    for name in ('bind_process_tree_to_app_lifetime', '_reap_stranded_helpers',
                 'acquire_single_instance_guard', 'run_gui_workflow', 'run_startup_maintenance'):
        monkeypatch.setattr(bootstrap, name, forbidden)
    calls = []
    monkeypatch.setattr(cli, 'main', lambda args: calls.append(args) or 7)
    assert bootstrap.main(['--cditem-device-tests', '--output', 'result.json', 'inspect']) == 7
    assert calls == [['--output', 'result.json', 'inspect']]


@pytest.mark.parametrize('prefix', [['--gui'], ['--cli'], ['--virtual-profile-worker'],
                                   ['--input', 'request.json'], ['--startup-splash-host', 'host']])
def test_device_mode_refuses_conflicting_application_modes(monkeypatch, prefix):
    from cdmw.app import bootstrap
    monkeypatch.setattr(cli, 'main', lambda *a: pytest.fail('Conflicting modes reached device execution.'))
    with pytest.raises(SystemExit) as raised:
        bootstrap.main(prefix + ['--cditem-device-tests', 'inspect'])
    assert raised.value.code == 2


def test_entry_dispatches_spawn_before_importing_bootstrap(monkeypatch):
    import builtins
    import multiprocessing
    class SpawnDispatched(Exception):
        pass
    original_import = builtins.__import__
    def checked_import(name, *args, **kwargs):
        assert name != 'cdmw.app.bootstrap', 'Spawn child imported application bootstrap before dispatch.'
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', checked_import)
    def dispatch():
        raise SpawnDispatched()
    monkeypatch.setattr(multiprocessing, 'freeze_support', dispatch)
    with pytest.raises(SpawnDispatched):
        runpy.run_path(str(Path(__file__).resolve().parents[1] / 'cdmw_app.py'), run_name='__main__')


def test_public_entry_main_keeps_its_callable_contract(monkeypatch):
    import cdmw_app
    from cdmw.app import bootstrap
    calls = []
    monkeypatch.setattr(bootstrap, 'main', lambda args: calls.append(args) or 8)
    assert cdmw_app.main(['--cli']) == 8
    assert calls == [['--cli']]
