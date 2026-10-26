"""Smoke-test verdicts from simulated launches; never starts a process."""
import json
import struct

import pytest

from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services import virtual_loader_smoke as smoke
from cdmw.services import virtual_loader_standalone as standalone
from tests.test_virtual_loader_standalone import published


class FakeGame:
    """Plays the runtime's part: writes its report and trace, then waits to be closed."""

    def __init__(self, root, generation, *, state='ready', detail='', opened=None, report=True, change=None):
        self.root, self.generation, self.state, self.detail = root, generation, state, detail
        self.opened = opened if opened is not None else ['meta\\0.papgt', '0036\\0.pamt']
        self.report, self.change = report, change
        self.pid, self.live, self.now, self.closed = 4242, False, 0.0, []
        self.image_path = str(root / 'bin64/CrimsonDesert.exe')

    def launch(self):
        self.live = True
        if self.change:
            (self.root / self.change).write_bytes(b'changed by the launch')
        if not self.report:
            return
        folder = self.root / '.cdmw/virtual-loader'
        (folder / 'standalone-status.json').write_text(json.dumps({
            'state': self.state, 'pid': self.pid, 'generation': self.generation, 'error': 0,
            'elapsed_ms': 40, 'detail': self.detail}))
        rows = [struct.pack('<IIIIq1024s', 13, 1, 0, 0, 1, b'')]
        rows += [struct.pack('<IIIIq1024s', 1, 1, 1, 0, 2, ('C:\\game\\' + path).encode('utf-16le')) for path in self.opened]
        (folder / 'trace-standalone.bin').write_bytes(b''.join(rows))

    def hooks(self):
        def close(pid, timeout):
            self.closed.append(pid)
            self.live = False
            return 'closed'
        def sleep(seconds):
            self.now += seconds
        return smoke.SmokeHooks(launch=self.launch, alive=lambda pid: self.live and pid == self.pid,
                                image=lambda pid: self.image_path, close=close,
                                running=lambda: [self.pid] if self.live else [], sleep=sleep, clock=lambda: self.now)


def prepared(tmp_path, monkeypatch):
    root, _files, profile = published(tmp_path, monkeypatch)
    standalone.publish_standalone(root)
    return root, profile


def test_ready_launch_with_expected_opens_passes_and_closes_only_the_reported_game(tmp_path, monkeypatch):
    root, profile = prepared(tmp_path, monkeypatch)
    game = FakeGame(root, profile['generation'])
    report = smoke.run_smoke(root, hooks=game.hooks(), hold=5)
    assert report['verdict'] == 'passed', report['reasons']
    assert report['trace']['expected'] == {'meta/0.papgt': True, '0036/0.pamt': True}
    assert report['trace']['hooks_ready'] and report['close'] == 'closed' and game.closed == [4242]
    assert report['changed_files'] == [] and 'meta/0.pathc' in smoke.protected_files(root)


def test_refused_profile_fails_with_the_runtime_reason_and_still_closes(tmp_path, monkeypatch):
    root, profile = prepared(tmp_path, monkeypatch)
    game = FakeGame(root, profile['generation'], state='refused', detail='A game or mod archive changed after the profile was published', opened=[])
    report = smoke.run_smoke(root, hooks=game.hooks(), hold=5)
    assert report['verdict'] == 'failed' and game.closed == [4242]
    assert any('archive changed' in reason for reason in report['reasons'])


def test_missing_redirect_and_changed_index_file_fail(tmp_path, monkeypatch):
    root, profile = prepared(tmp_path, monkeypatch)
    game = FakeGame(root, profile['generation'], opened=['meta\\0.papgt'], change='meta/0.papgt')
    report = smoke.run_smoke(root, hooks=game.hooks(), hold=5, evidence_timeout=3)
    assert report['verdict'] == 'failed'
    assert report['trace']['expected']['0036/0.pamt'] is False
    assert report['changed_files'] == ['meta/0.papgt']


def test_no_runtime_report_closes_a_verified_game_and_leaves_a_foreign_one(tmp_path, monkeypatch):
    root, profile = prepared(tmp_path, monkeypatch)
    game = FakeGame(root, profile['generation'], report=False)
    report = smoke.run_smoke(root, hooks=game.hooks(), start_timeout=3)
    assert report['verdict'] == 'failed' and report['status'] is None and game.closed == [4242]
    other = FakeGame(root, profile['generation'], report=False)
    other.image_path = str(tmp_path / 'elsewhere/CrimsonDesert.exe')
    report = smoke.run_smoke(root, hooks=other.hooks(), start_timeout=3)
    assert report['close'] == 'left running' and other.closed == []


def test_preflight_requires_a_closed_game_and_a_published_profile(tmp_path, monkeypatch):
    root, profile = prepared(tmp_path, monkeypatch)
    game = FakeGame(root, profile['generation'])
    game.live = True
    with pytest.raises(VirtualLoaderError, match='Close Crimson Desert'):
        smoke.run_smoke(root, hooks=game.hooks())
    standalone.withdraw_standalone(root)
    with pytest.raises(VirtualLoaderError, match='Publish the launcher profile'):
        smoke.run_smoke(root, hooks=FakeGame(root, profile['generation']).hooks())
