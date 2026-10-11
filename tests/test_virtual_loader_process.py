import json
from pathlib import Path
import sys
import tempfile
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualLoaderError, VirtualProfile
from cdmw.services import virtual_loader_process as owner
from cdmw.services.independent_item_package import canonical, read_package
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_virtual_loader import game_bytes, packages


def owned_temps(monkeypatch, tmp_path):
    monkeypatch.setattr(owner, 'TemporaryDirectory', lambda **kw: tempfile.TemporaryDirectory(dir=tmp_path, **kw))


def test_disabled_mods_survive_child_publication_and_reenable_with_reserved_ids(tmp_path, monkeypatch):
    from cdmw.services.virtual_loader_state import load_profile, validate_profile
    from cdmw.services.independent_item_install import load_registry
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    root, paths = packages(tmp_path)
    before = game_bytes(root)
    publish_profile(prepare_profile(VirtualProfile(paths), root))
    registry = load_registry(root)
    missing_folder = tmp_path / 'disabled-folder'
    selection = VirtualProfile(paths[:1], (), paths[1:], (missing_folder,))
    prepared = owner.prepare_profile_in_subprocess(selection, root)
    publish_profile(prepared)
    profile = load_profile(root)
    assert profile['packages'] == [str(paths[0])]
    assert profile['disabled_packages'] == [str(paths[1])]
    assert profile['disabled_mods'] == [str(missing_folder)]
    assert len(profile['items']) == 1 and load_registry(root) == registry
    assert str(paths[1]) not in dict(profile['sources'])
    for disabled in ([str(paths[0])], [str(paths[1]), str(paths[1])], ['relative.cditem'], 'invalid'):
        with pytest.raises(ValueError, match='disabled'):
            validate_profile(dict(profile, disabled_packages=disabled))
    publish_profile(prepare_profile(VirtualProfile((), (), paths), root))
    assert not load_profile(root)['items']
    publish_profile(prepare_profile(VirtualProfile(paths), root))
    assert load_registry(root) == registry and len(load_profile(root)['items']) == 2
    assert game_bytes(root) == before


@pytest.mark.parametrize('change', ['archive', 'loose', 'new_mount'])
def test_real_child_preserves_output_and_publication_guards(tmp_path, change):
    root, files = packages(tmp_path / 'fixture')
    mod = tmp_path / 'mod'
    (mod / 'files/character').mkdir(parents=True)
    loose = mod / 'files/character/foreign.txt'
    loose.write_bytes(b'foreign asset')
    from cdmw.core.papgt_format import papgt_with_directory
    mount = root / 'meta/0.papgt'
    # An absent manager directory is still a pinned part of the mounted view.
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), 'foreign', 0, first=True))
    profile = VirtualProfile(files, (mod,))
    original = prepare_profile(profile, root)
    before = game_bytes(root)
    logs, progress = [], []
    result = owner.prepare_profile_in_subprocess(profile, root, on_log=logs.append,
        on_progress=lambda n, total, detail: progress.append((n, total, detail)))
    assert logs and any('Composing' in message for message in logs)
    assert progress and progress[-1][0] == 100
    assert [n for n, _, _ in progress] == sorted(n for n, _, _ in progress)
    assert all(total == 100 and detail for _, total, detail in progress)
    assert result.files == original.files
    assert result.registry == original.registry
    assert result.observed == original.observed
    # The ZIP timestamp can change between preparations; its package content cannot.
    assert [(p, read_package(data)) for p, data in result.retained_packages] == [
        (p, read_package(data)) for p, data in original.retained_packages]
    assert result.source_revision.files == original.source_revision.files
    assert result.source_revision.payloads == original.source_revision.payloads
    assert result.source_revision.indexes == original.source_revision.indexes
    assert result.source_revision.indexes
    expected_external = original.external.capture()
    assert result.external.archives == expected_external.archives
    assert result.external.inventories == expected_external.inventories
    assert result.external.source_revision.files == expected_external.source_revision.files
    assert result.external.source_revision.payloads == expected_external.source_revision.payloads
    assert result.external.source_revision.indexes == expected_external.source_revision.indexes
    expected, actual = json.loads(original.profile), json.loads(result.profile)
    expected.pop('generation'); actual.pop('generation')
    assert expected == actual
    result.source_revision.validate()
    result.external.validate()
    assert game_bytes(root) == before and not (root / '.cdmw').exists()
    if change == 'archive':
        archive = next(path for path, _ in result.source_revision.files if path.suffix == '.paz')
        with archive.open('ab') as output:
            output.write(b'changed')
    elif change == 'loose':
        loose.write_bytes(b'changed foreign asset')
    else:
        (root / 'foreign').mkdir()
        (root / 'foreign/new.pamt').write_bytes(b'changed mount inventory')
    with pytest.raises(ValueError, match='changed'):
        publish_profile(result)
    assert not (root / '.cdmw').exists()


def test_cancel_child_is_reaped_before_temporary_files_are_removed(tmp_path, monkeypatch):
    from cdmw.core import common
    owned_temps(monkeypatch, tmp_path)
    stop = threading.Event()
    ready = tmp_path / 'ready'
    finished = tmp_path / 'finished'
    script = (
        'from pathlib import Path; import time; '
        f'Path({str(ready)!r}).touch(); time.sleep(30); Path({str(finished)!r}).touch()'
    )
    monkeypatch.setattr(owner, '_worker_command', lambda *_: [sys.executable, '-c', script])
    processes, popen = [], common.subprocess.Popen
    def start(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(common.subprocess, 'Popen', start)
    run = owner.run_process_with_cancellation
    def cancel(command, **kwargs):
        poll = kwargs['on_poll']
        def tick():
            poll()
            if ready.exists():
                stop.set()
        return run(command, **dict(kwargs, on_poll=tick, timeout_seconds=10))
    monkeypatch.setattr(owner, 'run_process_with_cancellation', cancel)
    with pytest.raises(RunCancelled):
        owner.prepare_profile_in_subprocess(VirtualProfile(), tmp_path, stop_event=stop)
    assert len(processes) == 1 and processes[0].poll() is not None
    assert ready.exists() and not finished.exists()
    assert not tuple(tmp_path.glob('cdmw_virtual_prepare_*'))


@pytest.mark.parametrize('mounted', [False, True])
def test_external_archive_guards_survive_child_result(tmp_path, mounted):
    from cdmw.core.papgt_format import papgt_with_directory
    from tests.test_new_item_service import build_package
    root, files = packages(tmp_path / 'fixture', 1)
    folder = root / 'foreign' if mounted else tmp_path / 'mod'
    pamt = build_package(folder, {'character/foreign.txt': b'foreign asset'})
    archive_folder = pamt.parent
    # The inspector accepts non-numeric, mixed-case PAMT basenames too.
    renamed = pamt.with_name('Extra.PAMT')
    pamt.rename(renamed)
    if mounted:
        import shutil
        # build_package creates a shipped-layout child directory for fixtures.
        if archive_folder != folder:
            for path in tuple(archive_folder.iterdir()):
                shutil.move(str(path), folder / path.name)
            renamed = folder / renamed.name
        mount = root / 'meta/0.papgt'
        mount.write_bytes(papgt_with_directory(mount.read_bytes(), 'foreign', int.from_bytes(renamed.read_bytes()[:4], 'little'), first=True))
    profile = VirtualProfile(files, () if mounted else (archive_folder,))
    before = game_bytes(root)
    result = owner.prepare_profile_in_subprocess(profile, root)
    result.external.validate()
    assert game_bytes(root) == before
    with renamed.open('ab') as output:
        output.write(b'changed')
    with pytest.raises(ValueError, match='changed'):
        publish_profile(result)
    assert not (root / '.cdmw').exists()


@pytest.mark.parametrize('failure', ['exit', 'missing', 'request', 'blob', 'path', 'schema', 'legacy_schema',
                                  'missing_indexes', 'unwitnessed_payload', 'index_digest', 'duplicate_index',
                                  'different_index_digest',
                                  'size', 'duplicate', 'guard', 'late_cancel'])
def test_invalid_or_cancelled_result_is_never_delivered(tmp_path, monkeypatch, failure):
    root, files = packages(tmp_path / 'fixture', 1)
    before = game_bytes(root)
    owned_temps(monkeypatch, tmp_path)
    stop = threading.Event()
    def run(command, **kwargs):
        output = Path(command[command.index('--output') + 1])
        source = Path(command[command.index('--input') + 1])
        if failure == 'exit':
            return 1, '', 'specific preparation refusal'
        if failure != 'missing':
            assert owner.run_virtual_profile_worker(source, output) == 0
            data = json.loads(output.read_bytes())
            if failure == 'request':
                data['request'] = 'f' * 64
            elif failure == 'blob':
                blob = output.parent / (data['files'][0][1][0] + '.bin')
                blob.write_bytes(b'corrupt')
            elif failure == 'path':
                data['files'][0][0] = '../outside'
            elif failure == 'schema':
                data['schema'] = owner._SCHEMA + 1
            elif failure == 'legacy_schema':
                data['schema'] = 1
            elif failure == 'missing_indexes':
                data['source'].pop('indexes')
            elif failure == 'unwitnessed_payload':
                data['source']['indexes'] = []
            elif failure == 'index_digest':
                data['source']['indexes'][0][1] = 'not-a-digest'
            elif failure == 'duplicate_index':
                data['source']['indexes'].append(data['source']['indexes'][0])
            elif failure == 'different_index_digest':
                data['source']['indexes'][0][1] = '0' * 64
            elif failure == 'size':
                data['files'][0][1][1] = owner.MAX_TOTAL + 1
            elif failure == 'duplicate':
                data['files'].append(data['files'][0])
            elif failure == 'guard':
                data['source']['files'] = []
            else:
                stop.set()
            output.write_bytes(canonical(data))
        return 0, '', ''
    monkeypatch.setattr(owner, 'run_process_with_cancellation', run)
    with pytest.raises(RunCancelled if failure == 'late_cancel' else VirtualLoaderError):
        owner.prepare_profile_in_subprocess(VirtualProfile(files), root, stop_event=stop)
    assert game_bytes(root) == before and not (root / '.cdmw').exists()
    assert not tuple(tmp_path.glob('cdmw_virtual_prepare_*'))


def test_already_cancelled_request_never_starts_child(tmp_path, monkeypatch):
    stop = threading.Event(); stop.set()
    monkeypatch.setattr(owner, 'run_process_with_cancellation', lambda *_a, **_k: pytest.fail('Started cancelled work'))
    with pytest.raises(RunCancelled):
        owner.prepare_profile_in_subprocess(VirtualProfile(), tmp_path, stop_event=stop)


@pytest.mark.parametrize('frozen', [False, True])
def test_helper_routes_before_gui_and_single_instance_startup(tmp_path, monkeypatch, frozen):
    from cdmw.app import bootstrap
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    source, output = tmp_path / 'request.json', tmp_path / 'result.json'
    command = owner._worker_command(source, output)
    assert command[0] == sys.executable
    assert ('cdmw_app.py' in ' '.join(command)) is not frozen
    calls = []
    monkeypatch.setattr(owner, 'run_virtual_profile_worker', lambda *args: calls.append(args) or 0)
    monkeypatch.setattr(bootstrap, 'bind_process_tree_to_app_lifetime', lambda: pytest.fail('Worker entered app startup'))
    assert bootstrap.main(command[command.index('--virtual-profile-worker'):]) == 0
    assert calls == [(source, output)]
