"""Measure synthetic .cditem preparation in isolated, disposable child processes.

No game directory is accepted. The harness uses this checkout's owned test
fixtures, and its report is machine-local evidence rather than a support claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from time import perf_counter
from uuid import UUID, uuid5

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


def peak_resident_bytes():
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('peak_rss', 'rss', 'peak_paged', 'paged',
                                                   'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
        kernel, psapi = ctypes.WinDLL('kernel32', use_last_error=True), ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.peak_rss
    if sys.platform == 'linux':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    raise RuntimeError('Peak resident memory is implemented for Windows and Linux only.')


def storage(root):
    files = [path for path in root.rglob('*') if path.is_file()]
    unique = {}
    total = 0
    for path in files:
        size = path.stat().st_size
        total += size
        unique.setdefault((size, file_hash(path)), size)
    # Logical equality is a sharing opportunity, never permission to delete a
    # retained generation/recovery file or a measurement of allocated disk blocks.
    return {'bytes': total, 'files': len(files), 'unique_content_bytes': sum(unique.values()),
            'duplicate_content_bytes': total - sum(unique.values()),
            'duplicate_content_files': len(files) - len(unique)}


def file_hash(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(64 * 1024):
            result.update(chunk)
    return result.hexdigest()


def texture_plan(service, snapshot, seed):
    """A complete imported BC3 texture through the real authoring/compiler path."""
    from dataclasses import replace
    import random
    import struct
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.new_item_planning import ModelFiles
    from tests.test_archive_overlay_manager import shop_spec
    from tests.test_new_item_service import PAC_XML, STEM, imported_pac, _fake_dds
    header = bytearray(_fake_dds(4, 4)[:128])
    struct.pack_into('<II', header, 12, 4096, 4096)
    texture = bytes(header) + random.Random(seed).randbytes(4096 * 4096)
    model = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML),
                       f'character/texture/1_pc/{STEM}_d.dds': texture})
    return service.plan(replace(shop_spec('ScaleTexture'), model_source=ModelSource.IMPORTED),
                        snapshot, model=model, capture_independent=True)


def run_case(route, kind, count, generations):
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.domain.virtual_loader import VirtualProfile
    from cdmw.services import archive_overlay_manager as overlays
    from cdmw.services.independent_item_install import prepare_install, load_registry
    from cdmw.services.independent_item_package import from_plan, package_bytes, package_metadata, canonical
    from cdmw.services.virtual_loader_composition import prepare_profile
    from cdmw.services.virtual_loader_state import publish_profile, load_profile
    from tests.test_archive_overlay_manager import Backups, shop_spec
    from tests.test_independent_items import setup_game
    from tests.test_independent_package_links import linked
    from tests.test_virtual_loader import game_bytes

    result = {'route': route, 'kind': kind, 'packages': count, 'generations_requested': generations,
              'baseline_peak_resident_bytes': peak_resident_bytes(), 'runs': []}
    with tempfile.TemporaryDirectory(prefix='cdmw-scale-') as directory:
        base = Path(directory).resolve()
        if base.parent != Path(tempfile.gettempdir()).resolve() or not base.name.startswith('cdmw-scale-'):
            raise RuntimeError('The disposable fixture directory is outside the expected temporary root.')
        service, snapshot, _ = setup_game(base)
        root = base / 'game'
        original = game_bytes(root)
        spec, icon = shop_spec('ScaleFixture'), None
        if kind == 'icon':
            from dataclasses import replace
            import random
            from cdmw.domain.new_item.spec import IconSource
            from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
            from cdmw.core.stringinfo_table import stringinfo_key
            from tests.test_new_item_service import _fake_dds
            spec = replace(spec, icon=IconSource.GENERATED)
            name = icon_string_for_stem(service.allocate(spec, snapshot).stem)
            header = _fake_dds(256, 256)[:128]
            payload = header + random.Random(0).randbytes(256 * 256)
            icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), payload, None, None)
        plan = (texture_plan(service, snapshot, 0) if kind.startswith('texture-') else
                service.plan(spec, snapshot, icon=icon, capture_independent=True))
        packages = []
        for index in range(count):
            if kind == 'texture-distinct' and index:
                plan = texture_plan(service, snapshot, index)
            package = from_plan(plan, uuid5(UUID(int=1), str(index)).hex)
            if kind == 'links':
                package = linked(package, packages[-1:])
            packages.append(package)
        sources = []
        for index, package in enumerate(packages):
            path = base / f'{index}.cditem'
            path.write_bytes(package_bytes(package))
            sources.append(path)
        result['input_zip_bytes'] = sum(path.stat().st_size for path in sources)
        result['input_expanded_bytes'] = sum(len(canonical(package_metadata(p))) + sum(map(len, p.blobs.values())) for p in packages)
        result['fixture_game_bytes'] = sum(map(len, original.values()))
        result['input_setup_peak_resident_bytes'] = peak_resident_bytes()
        # The preparation worker reads its source files; benchmark setup must not
        # keep a second, unrelated set of authoring payloads live through that work.
        del packages, package, plan, icon
        backups = Backups(base)
        try:
            for generation in range(generations):
                started = perf_counter()
                prepared = (prepare_install(sources, root, rebuild=bool(generation)).preparation if route == 'physical'
                            else prepare_profile(VirtualProfile(tuple(sources)), root))
                prepared_at = perf_counter()
                if generation == 0 and game_bytes(root) != original:
                    raise AssertionError('Preparation changed the synthetic game.')
                if route == 'physical':
                    backups.apply(prepared)
                else:
                    publish_profile(prepared)
                published_at = perf_counter()
                run = {'generation': generation + 1, 'prepare_seconds': prepared_at - started,
                       'publish_seconds': published_at - prepared_at,
                       'operation_peak_resident_bytes': peak_resident_bytes(),
                       'bookkeeping': storage(root / '.cdmw')}
                result['runs'].append(run)
                # Publication must never produce an inventory its reader refuses.
                registry = load_registry(root)
                if len(registry['items']) != count:
                    raise AssertionError('A retained identity is missing.')
                if route == 'physical':
                    run['active_inventory_bytes'] = (root / overlays.INDEX_PATH).stat().st_size
                    run['compiled_files'] = {path.relative_to(root).as_posix(): file_hash(path)
                                             for path in root.rglob('*') if path.is_file() and '.cdmw' not in path.parts}
                else:
                    run['active_profile_bytes'] = (root / '.cdmw/virtual-loader/profile.json').stat().st_size
                    profile = load_profile(root)
                    run['compiled_files'] = profile['files']
                    if len(profile['items']) != count or game_bytes(root) != original:
                        raise AssertionError('Virtual publication changed game files or lost ownership.')
                run['readback'] = 'passed'
                del prepared  # Completed generations are on disk, not overlapping live jobs.
            stop, cancellation = threading.Event(), []
            def cancel_at_composition(message):
                if message.startswith('Composing ') and not stop.is_set():
                    cancellation.append(perf_counter())
                    stop.set()
            try:
                if route == 'physical':
                    prepare_install(sources, root, rebuild=True, stop_event=stop, on_log=cancel_at_composition)
                else:
                    prepare_profile(VirtualProfile(tuple(sources)), root, stop_event=stop, on_log=cancel_at_composition)
            except RunCancelled:
                result['composition_cancel_seconds'] = perf_counter() - cancellation[0] if cancellation else None
            else:
                raise AssertionError('The composition cancellation did not stop preparation.')
            result['status'] = 'passed'
        except Exception as exc:
            result.update(status='refused-or-failed', error=f'{type(exc).__name__}: {exc}')
        try:
            load_registry(root)
            result['final_inventory_readable'] = True
        except ValueError:
            result['final_inventory_readable'] = False
        if (root / overlays.INDEX_PATH).is_file():
            result['final_inventory_bytes'] = (root / overlays.INDEX_PATH).stat().st_size
        result['peak_resident_bytes'] = peak_resident_bytes()
        result['retained_bookkeeping'] = storage(root / '.cdmw')
        result['backup_storage'] = {'bytes': sum(storage(path)['bytes'] for path in base.glob('backup-*'))}
        result['stock_archives_unchanged'] = all((root / name).read_bytes() == data
                                               for name, data in original.items() if name.startswith('0009/'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--counts', nargs='+', type=int, default=[1, 8, 32, 128])
    parser.add_argument('--routes', nargs='+', choices=['physical', 'virtual'], default=['physical', 'virtual'])
    kinds = ['legacy', 'links', 'icon', 'texture-shared', 'texture-distinct']
    parser.add_argument('--kinds', nargs='+', choices=kinds, default=['legacy', 'links'])
    parser.add_argument('--generations', type=int, default=3)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--case', nargs=4, metavar=('ROUTE', 'KIND', 'COUNT', 'GENERATIONS'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.case:
        route, kind, count, generations = args.case
        limit = 8 if kind.startswith('texture-') else 32 if kind == 'icon' else 128
        if (route not in ('physical', 'virtual') or kind not in kinds
                or not 1 <= int(count) <= limit or not 1 <= int(generations) <= 5):
            parser.error('Invalid isolated case.')
        print(json.dumps(run_case(route, kind, int(count), int(generations))))
        return
    if not args.output or args.output.exists() or any(not 1 <= count <= 128 for count in args.counts) or not 1 <= args.generations <= 5:
        parser.error('Choose a new output file, counts 1..128 and generations 1..5.')
    if 'icon' in args.kinds and max(args.counts) > 32:
        parser.error('The bounded icon measurement permits at most 32 packages.')
    if any(kind.startswith('texture-') for kind in args.kinds) and max(args.counts) > 8:
        parser.error('The bounded imported-texture measurement permits at most 8 packages.')
    git = lambda *parts: subprocess.check_output(['git', *parts], cwd=REPOSITORY, text=True).strip()
    report = {'format': 'cdmw_synthetic_scale_v1', 'utc': datetime.now(timezone.utc).isoformat(),
              'revision': git('rev-parse', 'HEAD'), 'dirty': bool(git('status', '--porcelain')),
              'python': sys.version, 'platform': sys.platform,
              'scope': 'Synthetic equipment recipes. Icon cases add complete 256x256 BC3 DDS data. Imported-texture cases use one 4096x4096 BC3 DDS per package, with shared or distinct deterministic incompressible pixels. '
                       'Each case runs in a fresh process; peak includes setup, separately recorded before authoring payloads are released. Completed preparations are released between generations. '
                       'Storage counts logical file bytes and equal full-file content, not allocated disk blocks or safe deletion candidates. No licensed data, real game, native build, large mesh, 1-GiB capacity or worst-case cancellation proof.',
              'cases': []}
    for route in args.routes:
        for kind in args.kinds:
            for count in args.counts:
                command = [sys.executable, str(Path(__file__).resolve()), '--case', route, kind, str(count), str(args.generations)]
                try:
                    child = subprocess.run(command, cwd=REPOSITORY, text=True, capture_output=True, timeout=240, check=True,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    result = json.loads(child.stdout)
                except (subprocess.SubprocessError, ValueError) as exc:
                    detail = getattr(exc, 'stderr', None) or str(exc)
                    if isinstance(detail, bytes):
                        detail = detail.decode('utf-8', errors='replace')
                    result = {'route': route, 'kind': kind, 'packages': count, 'status': 'harness-failed', 'error': detail[-4000:]}
                report['cases'].append(result)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
                print(json.dumps({key: result.get(key) for key in ('route', 'kind', 'packages', 'status', 'error', 'peak_resident_bytes')}), flush=True)


if __name__ == '__main__':
    main()
