"""The real verifier must never run beside a user's portable settings."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.test_packaged_bundled_helper_reporting import _packaged_rust_editor_fixture

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / 'scripts/verify_packaged_startup.ps1'
POWERSHELL = shutil.which('powershell.exe')
pytestmark = pytest.mark.skipif(sys.platform != 'win32' or POWERSHELL is None, reason='Windows packaged startup verifier')


def _quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@pytest.fixture(scope='module')
def portable_probe(tmp_path_factory):
    folder = tmp_path_factory.mktemp('portable-startup-probe')
    source, executable = folder / 'Probe.cs', folder / 'Probe.exe'
    source.write_text(r'''
using System;
using System.IO;
using System.Reflection;
using System.Threading;
class Probe {
    static int Main() {
        string executable = Assembly.GetExecutingAssembly().Location;
        string home = Path.GetDirectoryName(executable);
        File.WriteAllLines(Environment.GetEnvironmentVariable("CDMW_TEST_EVIDENCE"),
            new string[] { executable, Directory.GetCurrentDirectory() });
        if (Directory.GetFiles(home, "*.cfg").Length != 0) return 21;
        if (File.Exists(Path.Combine(home, "user-data.txt"))) return 22;
        if (Environment.GetEnvironmentVariable("CDMW_TEST_RUNTIME") == "1" &&
            !File.Exists(Path.Combine(home, "_internal", "runtime.bin"))) return 23;
        File.WriteAllText(Path.Combine(home, "CrimsonDesertModWorkbench.cfg"), "probe wrote fresh settings");
        string outcome = Environment.GetEnvironmentVariable("CDMW_TEST_OUTCOME");
        if (outcome == "timeout") Thread.Sleep(20000);
        if (outcome == "nonzero") return 7;
        File.WriteAllText(Environment.GetEnvironmentVariable("CDMW_GUI_STARTUP_SMOKE_RESULT"),
            Environment.GetEnvironmentVariable("CDMW_TEST_PAYLOAD"));
        return 0;
    }
}
''', encoding='utf-8')
    result = subprocess.run(
        [POWERSHELL, '-NoProfile', '-NonInteractive', '-Command',
         f'Add-Type -Path {_quote(source)} -OutputAssembly {_quote(executable)} -OutputType ConsoleApplication'],
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


@pytest.mark.parametrize('layout,target,outcome,error', (
    ('onefile', 'default', 'passed', ''),
    ('onedir', 'mesh_builder', 'passed', ''),
    ('onefile', 'default', 'nonzero', 'exited with code 7'),
    ('onefile', 'default', 'timeout', 'timed out'),
    ('onefile', 'default', 'copy_error', 'fixture copy failure'),
    ('onefile', 'default', 'launch_error', 'fixture launch failure'),
))
def test_verifier_isolates_portable_config_and_cleans_every_outcome(
    tmp_path, portable_probe, layout, target, outcome, error,
):
    install = tmp_path / "user's portable app"
    install.mkdir()
    executable = install / 'CDMW.exe'
    shutil.copy2(portable_probe, executable)
    for name in ('CrimsonDesertModWorkbench.cfg', 'DDSRebuildApp.cfg', 'user-data.txt'):
        (install / name).write_bytes(b'preserve user data\r\n')
    if layout == 'onedir':
        (install / '_internal').mkdir()
        (install / '_internal/runtime.bin').write_bytes(b'owned runtime fixture')
    before = {p.relative_to(install): p.read_bytes() for p in install.rglob('*') if p.is_file()}
    outer_temp = tmp_path / 'outer temp'
    outer_temp.mkdir()
    evidence = tmp_path / 'launch.txt'
    sentinel = {
        'TEMP': str(outer_temp), 'TMP': str(outer_temp), 'QT_QPA_PLATFORM': 'outer-platform',
        'CDMW_GUI_STARTUP_SMOKE': 'outer-smoke', 'CDMW_GUI_STARTUP_SMOKE_RESULT': 'outer-result',
        'CDMW_GUI_STARTUP_SMOKE_TARGET': 'outer-target', 'CDMW_SINGLE_INSTANCE_SCOPE': 'outer-scope',
        'CDMW_CRASH_DIR': 'outer-crash', 'CDMW_TEMP_CACHE_ROOT': 'outer-cache',
    }
    payload = dict(ok=True, pid=42, stage='post_construction', target=target,
                   bundled_helpers=[dict(key='openimageio', status='available', source='bundled_lookup', path='owned')],
                   rust_mesh_editor=_packaged_rust_editor_fixture())
    failure_hook = ''
    if outcome == 'copy_error':
        failure_hook = f'''
function Copy-Item {{
    param($LiteralPath, $Destination, [switch]$Recurse)
    [IO.File]::WriteAllText({_quote(evidence)}, $Destination)
    throw 'fixture copy failure'
}}
'''
    elif outcome == 'launch_error':
        failure_hook = f'''
function Start-Process {{
    param($FilePath, $WorkingDirectory, [switch]$PassThru, $WindowStyle)
    [IO.File]::WriteAllText({_quote(evidence)}, $FilePath)
    throw 'fixture launch failure'
}}
'''
    environment_checks = '\n'.join(
        f"if ([Environment]::GetEnvironmentVariable({_quote(key)}, 'Process') -cne {_quote(value)}) {{ throw 'Environment changed: {key}' }}"
        for key, value in sentinel.items()
    )
    script = f'''
. {_quote(VERIFIER)} -ExecutablePath ignored
{failure_hook}
$failure = ''
try {{
    Invoke-PackagedStartupVerification -Path {_quote(executable)} -Timeout 2 -SmokeTarget {_quote(target)}
}} catch {{ $failure = $_.Exception.Message }}
if ({_quote(error)} -eq '') {{
    if ($failure) {{ throw $failure }}
}} elseif (-not $failure.Contains({_quote(error)})) {{ throw "Wrong failure: $failure" }}
{environment_checks}
'''
    result = subprocess.run(
        [POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
        env={**os.environ, **sentinel, 'CDMW_TEST_OUTCOME': outcome,
             'CDMW_TEST_EVIDENCE': str(evidence), 'CDMW_TEST_RUNTIME': '1' if layout == 'onedir' else '0',
             'CDMW_TEST_PAYLOAD': json.dumps(payload)},
        text=True, capture_output=True, timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    launched = evidence.read_text().splitlines()
    isolated = Path(launched[0])
    assert isolated.name == executable.name and isolated.parent.name == 'application'
    assert isolated != executable
    if len(launched) > 1:
        assert Path(launched[1]) == isolated.parent
    assert not isolated.parent.parent.exists(), 'Verifier left its disposable settings/runtime behind'
    assert before == {p.relative_to(install): p.read_bytes() for p in install.rglob('*') if p.is_file()}
