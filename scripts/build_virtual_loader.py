"""Build the source-auditable Windows prototype and record exact provenance."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'native/cdmw_virtual_loader'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    build = SOURCE / 'build'
    subprocess.run(['cmake', '-S', str(SOURCE), '-B', str(build), '-A', 'x64'], check=True)
    subprocess.run(['cmake', '--build', str(build), '--config', 'Release'], check=True)
    subprocess.run(['ctest', '--test-dir', str(build), '-C', 'Release', '--output-on-failure'], check=True)
    files = ('CDMWVirtualLoader.asi', 'cdmw_virtual_session.exe')
    sources = tuple(sorted(p for p in SOURCE.iterdir() if p.suffix in ('.cpp', '.hpp') or p.name == 'CMakeLists.txt'))
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    result = {'format': 'cdmw_virtual_runtime_v1', 'revision': revision,
              'sources': {p.name: sha(p) for p in sources},
              'files': {name: sha(build / 'Release' / name) for name in files},
              'game_redirection_approved': False,
              'evidence': 'Compiled source and synthetic checks; game startup and save compatibility remain unverified.'}
    (build / 'Release/provenance.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'artifact': str(build / 'Release'), 'files': result['files']}, indent=2))


if __name__ == '__main__':
    main()
