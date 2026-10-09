"""Isolated codec I/O measurements with disposable, opaque synthetic resources.

These bytes exercise the package container, not a valid game icon/model, game
registration, compilation, native runtime or persistence. No game path is accepted.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from time import perf_counter
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.benchmark_independent_items import peak_resident_bytes


def run_case(operation, mib, version):
    from cdmw.services import independent_item_package as owner
    from cdmw.services.independent_mod_package import migrate_v1
    template = json.loads((ROOT / 'tests/fixtures/cditem_v1_codec.json').read_text(encoding='utf-8'))['manifest']
    # Warm the normal recipe imports without allocating the measured resource.
    small = owner._package(template, {})
    if version == 2:
        small = migrate_v1(small)
    metadata = deepcopy(owner.package_metadata(small))
    if version == 2:
        metadata['provenance'] = None  # A fresh synthetic v2, not a claimed historical migration.
    with tempfile.TemporaryDirectory(prefix='cdmw-package-io-') as directory:
        base = Path(directory).resolve()
        if base.parent != Path(tempfile.gettempdir()).resolve() or not base.name.startswith('cdmw-package-io-'):
            raise RuntimeError('Unexpected temporary fixture location.')
        payload = base / 'opaque-synthetic.bin'
        generator, checksum = random.Random(0), hashlib.sha256()
        with payload.open('xb') as writer:
            for _ in range(mib):
                chunk = generator.randbytes(1024 * 1024)
                writer.write(chunk)
                checksum.update(chunk)
        del chunk
        key = checksum.hexdigest()
        recipe = metadata['recipe'] if version == 1 else metadata['modules'][0]['data']
        recipe['icon'] = key
        metadata['blobs'] = {key: payload.stat().st_size}
        metadata['title'] = 'Synthetic opaque resource; container measurement only'
        # Build the input with streaming stdlib I/O so setup does not itself
        # materialize a compressed artifact or set a misleading peak watermark.
        source = base / 'source.cditem'
        with zipfile.ZipFile(source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('item.json', owner.canonical(metadata))
            archive.write(payload, 'assets/' + key)
        old_digest = owner.digest(owner.canonical(metadata))
        selected = source
        if operation != 'read':
            if operation == 'create':
                selected = base / 'new.cditem'
            else:
                metadata['title'] = 'Updated synthetic opaque resource; container measurement only'
            package = owner._package(metadata, {key: payload.read_bytes()})
        baseline = peak_resident_bytes()
        started = perf_counter()
        if operation == 'read':
            result = owner.read_package(source)
        else:
            owner.write_package(package, selected, expected_digest=old_digest if operation == 'update' else None)
        elapsed, peak = perf_counter() - started, peak_resident_bytes()
        # Validation is deliberately outside the measured operation. A write
        # readback may temporarily hold both the authoring and imported blobs.
        if operation != 'read':
            result = owner.read_package(selected)
        assert result.digest == owner.digest(owner.canonical(metadata))
        assert result.identity == metadata['identity'] and result.blobs[key] == payload.read_bytes()
        return {'operation': operation, 'resource_mib': mib, 'version': version,
                'seconds': elapsed, 'baseline_peak_resident_bytes': baseline,
                'operation_peak_resident_bytes': peak, 'artifact_bytes': selected.stat().st_size,
                'content_sha256': result.digest, 'status': 'passed'}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mib', type=int, nargs='+', default=[16, 64, 128])
    parser.add_argument('--versions', type=int, nargs='+', choices=(1, 2), default=[1, 2])
    parser.add_argument('--operations', nargs='+', choices=('read', 'create', 'update'), default=['read', 'create', 'update'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--case', nargs=3, metavar=('OPERATION', 'MIB', 'VERSION'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.case:
        operation, mib, version = args.case
        if operation not in ('read', 'create', 'update') or not 1 <= int(mib) <= 128 or int(version) not in (1, 2):
            parser.error('Invalid isolated resource case.')
        print(json.dumps(run_case(operation, int(mib), int(version))))
        return
    if not args.output or args.output.exists() or any(not 1 <= mib <= 128 for mib in args.mib):
        parser.error('Choose a new report path and resource sizes between 1 and 128 MiB.')
    git = lambda *parts: subprocess.check_output(['git', *parts], cwd=ROOT, text=True).strip()
    report = {'format': 'cdmw_synthetic_package_io_v1', 'utc': datetime.now(timezone.utc).isoformat(),
              'revision': git('rev-parse', 'HEAD'), 'dirty': bool(git('status', '--porcelain')),
              'python': sys.version, 'platform': sys.platform,
              'scope': 'Opaque deterministic incompressible resource bytes; codec I/O only, not game-format or authoring acceptance. '
                       'Each case is a fresh process. Peak includes fixture setup; operation peak is recorded before readback validation. '
                       'This is not a whole-pipeline 1 GiB, large-mesh or worst-case cancellation test.', 'cases': []}
    for version in args.versions:
        for mib in args.mib:
            for operation in args.operations:
                command = [sys.executable, str(Path(__file__).resolve()), '--case', operation, str(mib), str(version)]
                try:
                    child = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=True, timeout=240,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    result = json.loads(child.stdout)
                except (subprocess.SubprocessError, ValueError) as exc:
                    detail = getattr(exc, 'stderr', None) or str(exc)
                    result = {'operation': operation, 'resource_mib': mib, 'version': version,
                              'status': 'harness-failed', 'error': str(detail)[-3000:]}
                report['cases'].append(result)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
                print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
