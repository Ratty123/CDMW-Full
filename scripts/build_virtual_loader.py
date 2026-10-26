"""Build the source-auditable Windows prototype and record exact provenance."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'native/cdmw_virtual_loader'
sys.path.insert(0, str(ROOT))

from cdmw.build_metadata import windows_file_version_tuple
from cdmw.constants import APP_ORGANIZATION, APP_REPOSITORY_URL, APP_TITLE, APP_VERSION


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    build = SOURCE / 'build'
    metadata = {
        'CDMW_APP_VERSION': APP_VERSION,
        'CDMW_FILE_VERSION': ','.join(map(str, windows_file_version_tuple(APP_VERSION))),
        'CDMW_PRODUCT_NAME': APP_TITLE,
        'CDMW_COMPANY_NAME': APP_ORGANIZATION,
        'CDMW_REPOSITORY_URL': APP_REPOSITORY_URL,
    }
    subprocess.run(['cmake', '-S', str(SOURCE), '-B', str(build), '-A', 'x64',
                    *(f'-D{name}={value}' for name, value in metadata.items())], check=True)
    subprocess.run(['cmake', '--build', str(build), '--config', 'Release'], check=True)
    subprocess.run(['ctest', '--test-dir', str(build), '-C', 'Release', '--output-on-failure'], check=True)
    files = ('CDMWVirtualLoader.asi', 'cdmw_virtual_session.exe')
    sources = tuple(sorted(p for p in SOURCE.iterdir()
                           if p.suffix in ('.cpp', '.hpp') or p.name in ('CMakeLists.txt', 'version.rc.in')))
    source_hashes = {p.name: sha(p) for p in sources}
    for relative in ('../../scripts/build_virtual_loader.py', '../../cdmw/constants.py', '../../cdmw/build_metadata.py'):
        source_hashes[relative] = sha(SOURCE / relative)
    # The runtime links the item composer's library sources.
    composer = SOURCE.parent / 'cdmw_item_composer'
    for path in sorted([composer / 'CMakeLists.txt', *composer.glob('include/**/*.hpp'), *composer.glob('src/*.[ch]pp')]):
        source_hashes['../' + path.relative_to(SOURCE.parent).as_posix()] = sha(path)
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    result = {'format': 'cdmw_virtual_runtime_v1', 'revision': revision,
              'sources': source_hashes,
              'files': {name: sha(build / 'Release' / name) for name in files},
              'game_redirection_approved': False,
              'evidence': 'Compiled sources and synthetic checks only; controlled game validation scope is documented separately.'}
    (build / 'Release/provenance.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'artifact': str(build / 'Release'), 'files': result['files']}, indent=2))


if __name__ == '__main__':
    main()
