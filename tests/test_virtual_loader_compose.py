"""Launch-time composition in the native runtime (milestone 2, provisional change sets).

The synthetic game below has real table formats and DMM's group mounted. A harness child
plays the game: the runtime composes the change sets in the compose folder, maps the
result, and the child reads the files back through the hooks. They must equal CDMW's own
composition, and the installation must stay untouched.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_native_composition import _effective, _game, _package, change_set, python_compose
from tests.test_virtual_loader_native import TEST_BUILD

HARNESS = TEST_BUILD / 'cdmw_virtual_loader_harness.exe'
pytestmark = pytest.mark.skipif(os.name != 'nt' or not (TEST_BUILD / 'CDMWVirtualLoaderTest.asi').exists() or not HARNESS.exists(),
                                reason='Requires the explicitly built Windows native virtual runtime')
STATUS = '.cdmw/virtual-loader/compose-status.json'
LOGICAL = ('meta/0.papgt', '0037/0.pamt', '0037/0.paz', 'meta/0.pathc')


def _install_runtime(root):
    (root / 'bin64').mkdir()
    shutil.copy2(TEST_BUILD / 'CDMWVirtualLoaderTest.asi', root / 'bin64/CDMWVirtualLoader.asi')
    shutil.copy2(HARNESS, root / 'bin64/cdmw_virtual_loader_harness.exe')
    (root / '.cdmw/virtual-loader/compose').mkdir(parents=True)


def _drop(root, packages):
    folder = root / '.cdmw/virtual-loader/compose'
    for old in folder.glob('*.cdchanges'):
        old.unlink()
    for index, changes in enumerate(packages):
        (folder / f'{index:02}.cdchanges').write_bytes(change_set(changes))


def _launch(root, *logical, blocked=False):
    shutil.rmtree(root / '.cdmw/virtual-loader/harness-out', ignore_errors=True)
    command = [str(root / 'bin64/cdmw_virtual_loader_harness.exe'), *(['--blocked'] if blocked else ['--copy-out', *logical])]
    result = subprocess.run(command, capture_output=True, timeout=120, cwd=root / 'bin64')
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    status = json.loads((root / STATUS).read_text(encoding='utf-8'))
    out = root / '.cdmw/virtual-loader/harness-out'
    return status, {path: (out / path.replace('/', '_')).read_bytes() for path in logical} if not blocked else {}


def _installation(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob('*')
            if path.is_file() and '.cdmw' not in path.parts and 'bin64' not in path.parts}


def test_change_sets_compose_at_launch_and_the_cache_is_reused(tmp_path, monkeypatch):
    root = _game(tmp_path)
    read = _effective(root, monkeypatch)
    alpha, beta = _package(read, 1990001, 'alpha'), _package(read, 1990002, 'beta')
    expected, composed = python_compose(root, [alpha, beta], '0037', read)
    _install_runtime(root)
    _drop(root, [alpha, beta])
    original = _installation(root)
    status, files = _launch(root, *LOGICAL)
    assert (status['state'], status['cache'], status['group'], status['packages'], status['composed']) == ('ready', 'composed', '0037', 2, composed)
    assert files == dict(expected)
    status, files = _launch(root, *LOGICAL)
    assert (status['state'], status['cache']) == ('ready', 'reused')
    assert files == dict(expected)
    assert _installation(root) == original
    trace = (root / '.cdmw/virtual-loader/trace-compose.bin').read_bytes()
    assert 'Reused composition'.encode('utf-16-le') in trace


def test_a_new_package_order_composes_again(tmp_path, monkeypatch):
    root = _game(tmp_path)
    read = _effective(root, monkeypatch)
    alpha, beta = _package(read, 1990001, 'alpha'), _package(read, 1990002, 'beta')
    _install_runtime(root)
    _drop(root, [alpha, beta])
    first, _ = _launch(root, *LOGICAL)
    _drop(root, [beta, alpha])
    expected, _composed = python_compose(root, [beta, alpha], '0037', read)
    status, files = _launch(root, *LOGICAL)
    assert status['cache'] == 'composed' and status['key'] != first['key']
    assert files == dict(expected)


def test_a_changed_mount_composes_again_from_the_new_tables(tmp_path, monkeypatch):
    from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
    from cdmw.core.itemgroupinfo_table import add_group_members, apply_item_group_row, parse_item_group_table
    from cdmw.services.archive_overlay_install import _processed_payload
    from tests.test_native_composition import FLAGS, GROUP
    root = _game(tmp_path)
    read = _effective(root, monkeypatch)
    alpha = _package(read, 1990001, 'alpha')
    _install_runtime(root)
    _drop(root, [alpha])
    _launch(root, *LOGICAL)
    # DMM remounts with another edit of its own: the same mount list, new group contents.
    rows = {row.key: row for row in parse_item_group_table(read(GROUP[0]), read(GROUP[1]))}
    dmm = apply_item_group_row(read(GROUP[0]), read(GROUP[1]), add_group_members(rows[17010], [778]))
    archive = build_overlay_archive([OverlayFile(path, _processed_payload(raw, compression_type=FLAGS[path] & 15, encrypted=bool(FLAGS[path] >> 4),
                                                                          basename=path.rsplit('/', 1)[-1]), len(raw), FLAGS[path])
                                     for path, raw in zip(GROUP, dmm)])
    (root / 'dmmsa/0.pamt').write_bytes(archive.pamt_bytes)
    (root / 'dmmsa/0.paz').write_bytes(archive.paz_bytes)
    read = _effective(root, monkeypatch)
    expected, _composed = python_compose(root, [alpha], '0037', read)
    status, files = _launch(root, *LOGICAL)
    assert status['state'] == 'ready' and status['cache'] == 'composed', status
    assert files == dict(expected)


@pytest.mark.parametrize('problem', ['conflict', 'malformed', 'lane'])
def test_a_refused_composition_leaves_the_game_unmodded(tmp_path, monkeypatch, problem):
    from cdmw.services.installation_lane import installation_lane
    root = _game(tmp_path)
    read = _effective(root, monkeypatch)
    _install_runtime(root)
    if problem == 'conflict':
        _drop(root, [_package(read, 1990001, 'alpha', store_count=5), _package(read, 1990002, 'beta', store_count=6)])
    else:
        _drop(root, [_package(read, 1990001, 'alpha')])
    if problem == 'malformed':
        set_path = root / '.cdmw/virtual-loader/compose/00.cdchanges'
        set_path.write_bytes(set_path.read_bytes()[:-3])
    original = _installation(root)
    if problem == 'lane':
        with installation_lane(root):
            status, _ = _launch(root, blocked=True)
    else:
        status, _ = _launch(root, blocked=True)
    expected = {'conflict': 'Packages conflict', 'malformed': 'Unreadable change set', 'lane': 'CDMW is changing this installation'}[problem]
    assert status['state'] == 'refused' and expected in status['detail'], status
    assert _installation(root) == original
    assert not (root / '.cdmw/virtual-loader/compose-cache').exists() or problem != 'lane'


def test_the_compose_folder_takes_precedence_over_a_standalone_profile(tmp_path, monkeypatch):
    root = _game(tmp_path)
    read = _effective(root, monkeypatch)
    alpha = _package(read, 1990001, 'alpha')
    expected, _composed = python_compose(root, [alpha], '0037', read)
    _install_runtime(root)
    (root / '.cdmw/virtual-loader/standalone.bin').write_bytes(b'a profile the runtime must not read')
    _drop(root, [alpha])
    status, files = _launch(root, *LOGICAL)
    assert status['state'] == 'ready' and files == dict(expected)
    assert not (root / '.cdmw/virtual-loader/standalone-status.json').exists()
