"""Audited startup handoff. Game redirection is gated independently of preparation."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import struct
import subprocess
import sys
from uuid import uuid4

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.virtual_loader import ExperimentalLaunchReview, VirtualLaunchPlan, VirtualLoaderError, VirtualSessionStatus
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services.installation_lane import installation_lane, lock_path
from cdmw.services.virtual_loader_composition import hash_file
from cdmw.services.virtual_loader_state import target, load_profile, generation_path, decode, read_optional
from cdmw.services.application_shutdown_service import archive_write_scope

GAME_SHA256 = '57da440d72f4db974f25fef047cf84c4dadd999a88cb2a3c5af4c9bd67fde1e7'
BOOTSTRAP_SHA256 = '810111a7f6a6cef892877c9f7c4582ccde2d621d119891f700c5309c370508bf'
GAME_REDIRECTION_APPROVED = False  # General redirect mode stays closed; reviewed experiments use mode 3.
RUNTIME_PATH = 'bin64/CDMWVirtualLoader.asi'
OWNER_PATH = '.cdmw/virtual-loader/runtime-owner.json'
_security_blocks = {}  # Actual Windows refusals, keyed by build hash for this app session only.


class _RuntimeSecurityBlock(VirtualLoaderError):
    pass


@contextmanager
def _runtime_file_access(path, checksum):
    """Do not retry a runtime Windows already refused, or suggest an exclusion."""
    if checksum in _security_blocks:
        raise _RuntimeSecurityBlock(_security_blocks[checksum])
    try:
        yield
    except OSError as exc:
        if getattr(exc, 'winerror', None) not in (225, 226):
            raise
        detail = (
            'Windows security software blocked a CDMW virtual-loader runtime file. '
            'The launch was stopped. Check Windows Security Protection history and '
            'have this build reviewed; CDMW cannot establish that this is a false positive. '
            'After the detection is resolved, restart CDMW to retry.\n'
            f'File: {path}\nSHA-256: {checksum}'
        )
        _security_blocks[checksum] = detail
        raise _RuntimeSecurityBlock(detail) from exc


def native_bundle(*, stop_event=None):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    folder = base / 'native/cdmw_virtual_loader'
    if not getattr(sys, 'frozen', False):
        folder /= 'build/Release'
    manifest = folder / 'provenance.json'
    if not manifest.is_file():
        raise VirtualLoaderError('Build the CDMW virtual runtime before preparing its setup.')
    evidence = decode(manifest.read_bytes())
    if evidence.get('format') != 'cdmw_virtual_runtime_v1' or set(evidence.get('files', {})) != {'CDMWVirtualLoader.asi', 'cdmw_virtual_session.exe'}:
        raise VirtualLoaderError('Unsupported virtual runtime provenance.')
    if not getattr(sys, 'frozen', False):
        source = base / 'native/cdmw_virtual_loader'
        if any(hash_file(source / name, stop_event) != expected for name, expected in evidence.get('sources', {}).items()):
            raise VirtualLoaderError('The native runtime sources changed. Rebuild the runtime before using it.')
    for name, expected in evidence['files'].items():
        with _runtime_file_access(folder / name, expected):
            if hash_file(folder / name, stop_event) != expected:
                raise VirtualLoaderError('The virtual runtime does not match its build provenance.')
    return folder, evidence


def verify_snapshot(root, *, stop_event=None):
    return _verify_snapshot(root, stop_event=stop_event, all_sources=True)


def _snapshot_preflight(root, *, stop_event=None, on_progress=None):
    """Check the saved view and selection; the host hashes every source before Steam.

    Never use this as launch authority on its own. The complete source guards
    still travel in session_manifest and the host refuses any content mismatch.
    """
    return _verify_snapshot(root, stop_event=stop_event, all_sources=False, on_progress=on_progress)


def _verify_snapshot(root, *, stop_event, all_sources, on_progress=None):
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.mod_merge_service import _inventory
    root = Path(root).resolve()
    profile = load_profile(root, registry=load_registry(root))
    if not profile:
        raise VirtualLoaderError('Prepare a virtual profile first.')
    from cdmw.domain.new_item.compilation import compiler_stamp
    if profile.get('compiler') != compiler_stamp() or 'compilation' not in profile:
        raise VirtualLoaderError('Apply changes again to rebuild this profile with the current compiler. Existing item IDs will be retained.')
    directory = generation_path(root, profile['generation'])
    selected = set(profile['packages'])
    sources = [(path, checksum) for path, checksum in profile['sources'] if all_sources or path in selected]
    total, current = len(profile['files']) + len(sources), 0
    def progress():
        raise_if_cancelled(stop_event)
        if on_progress:
            on_progress(current, total, 'Checking the saved virtual files…')
    progress()
    for relative, checksum in profile['files'].items():
        path = target(directory, 'files/' + relative)
        if not path.is_file() or (all_sources and hash_file(path, stop_event) != checksum):
            raise VirtualLoaderError(f'A prepared virtual file changed: {relative}. Apply changes again.')
        current += 1
        progress()
    for path, checksum in sources:
        if hash_file(Path(path), stop_event) != checksum:
            raise VirtualLoaderError(f'A game or mod source changed: {path}. Apply changes again.')
        current += 1
        progress()
    from cdmw.services.virtual_loader_sources import verify_catalogue
    verify_catalogue(profile.get('catalogue', ()), stop_event)
    for folder, expected in profile['inventories']:
        if canonical(_inventory(Path(folder), stop_event)) != canonical(expected):
            raise VirtualLoaderError('A mounted archive or selected mod folder changed. Prepare the profile again.')
    for relative, checksum in profile['observed']:
        data = read_optional(target(root, relative))
        if (digest(data) if data is not None else None) != checksum:
            raise VirtualLoaderError('The mounted installation changed. Prepare the profile again.')
    return profile


def runtime_status(root, *, experimental=False, stop_event=None):
    root = Path(root).resolve()
    if target(root, '.cdmw/virtual-loader/transaction.json').exists():
        return VirtualSessionStatus('blocked', 'Recover the interrupted virtual profile transaction first.')
    profile = load_profile(root)
    generation = profile['generation'] if profile else ''
    from cdmw.domain.new_item.compilation import compiler_stamp
    if profile and (profile.get('compiler') != compiler_stamp() or 'compilation' not in profile):
        return VirtualSessionStatus('blocked', 'Apply changes again to rebuild this profile with the current compiler. Existing item IDs will be retained.', generation)
    exe = target(root, 'bin64/CrimsonDesert.exe')
    if not exe.is_file():
        return VirtualSessionStatus('unavailable', 'Choose the installed Crimson Desert game folder.', generation)
    if hash_file(exe, stop_event) != GAME_SHA256:
        return VirtualSessionStatus('blocked', 'This executable build has not been verified for the virtual loader.', generation)
    try:
        folder, evidence = native_bundle(stop_event=stop_event)
    except _RuntimeSecurityBlock as exc:
        return VirtualSessionStatus('blocked', str(exc), generation)
    except ValueError as exc:
        return VirtualSessionStatus('unavailable', str(exc), generation)
    if experimental:
        from cdmw.services.new_item_service import game_is_running
        if game_is_running():
            return VirtualSessionStatus('blocked', 'Close Crimson Desert before starting a virtual session.', generation)
        try:
            setup = prepare_runtime_setup(root, stop_event=stop_event)
        except (ValueError, OSError) as exc:
            return VirtualSessionStatus('blocked', str(exc), generation)
        if not setup.owned:
            return VirtualSessionStatus('setup_required', 'Apply or launch to set up the virtual loader.', generation)
        if digest(setup.previous) != setup.checksum:
            return VirtualSessionStatus('update_required', 'The virtual loader will update automatically when you apply or launch.', generation)
        return VirtualSessionStatus('ready' if profile else 'unavailable',
            'Profile applied. Ready to launch.' if profile else 'Apply the profile to use this selection.', generation)
    installed = target(root, RUNTIME_PATH)
    if not installed.is_file() or hash_file(installed, stop_event) != evidence['files']['CDMWVirtualLoader.asi']:
        return VirtualSessionStatus('unavailable', 'The CDMW runtime needs a reviewed setup. Existing ASI loaders are not replaced.', generation)
    if not GAME_REDIRECTION_APPROVED:
        return VirtualSessionStatus('blocked', 'Profiles can be prepared. Game loading is awaiting verified startup timing, Steam handoff and save tests.', generation)
    return VirtualSessionStatus('ready' if profile else 'unavailable', 'Ready to launch.' if profile else 'Prepare a virtual profile first.', generation)


def prepare_launch(root, *, stop_event=None):
    status = runtime_status(root, stop_event=stop_event)
    if status.state != 'ready':
        raise VirtualLoaderError(status.detail)
    profile = verify_snapshot(root, stop_event=stop_event)
    root = Path(root).resolve()
    return VirtualLaunchPlan(root, profile['generation'], target(root, 'bin64/CrimsonDesert.exe'), GAME_SHA256,
                             generation_path(root, profile['generation']), digest(canonical(profile)))


def session_manifest(root, profile, *, mode, executable_sha256, token=None, launcher=None, extra_guards=()):
    """Bounded UTF-16 wire format shared with the native session/runtime harness."""
    root = Path(root).resolve()
    token = token or uuid4().hex
    data = bytearray(b'CDVFS3\0\0' + struct.pack('<III', mode, 0, 0) + bytes.fromhex(executable_sha256))
    def string(value):
        encoded = str(value).encode('utf-16le')
        if not encoded or len(encoded) >= 65536 or '\0' in str(value):
            raise VirtualLoaderError('Unsupported session path length.')
        data.extend(struct.pack('<I', len(encoded) // 2)); data.extend(encoded)
    string(root); string(profile['generation']); string(token); string(lock_path(root))
    data.extend(struct.pack('<I', len(profile['files'])))
    for logical, sha in sorted(profile['files'].items()):
        string(logical.replace('/', '\\'))
        string(target(generation_path(root, profile['generation']), 'files/' + logical))
        data.extend(bytes.fromhex(sha))
    guards = dict(profile.get('sources', ()))
    for relative, checksum in profile.get('observed', ()):
        guards[str(target(root, relative))] = checksum
    for relative in ('.cdmw/virtual-loader/profile.json', '.cdmw/independent-items.json'):
        value = read_optional(target(root, relative))
        guards[str(target(root, relative))] = digest(value) if value is not None else None
    if mode != 2:
        for relative in (RUNTIME_PATH, 'bin64/winmm.dll'):
            guards[str(target(root, relative))] = hash_file(target(root, relative))
    for path, checksum in extra_guards:
        if path in guards and guards[path] != checksum:
            raise VirtualLoaderError('The launch plan changed. Review it again.')
        guards[path] = checksum
    data.extend(struct.pack('<I', len(guards)))
    for path, checksum in sorted(guards.items()):
        string(path)
        data.extend(struct.pack('<I', int(checksum is not None)))
        data.extend(bytes.fromhex(checksum) if checksum else bytes(32))
    catalogue = profile.get('catalogue', ())
    data.extend(struct.pack('<I', len(catalogue)))
    for path, stamp in catalogue:
        if path in guards:
            raise VirtualLoaderError('A catalogue witness conflicts with a required source guard.')
        string(path)
        size, modified = (stamp[0], stamp[1] // 100 + 116444736000000000) if stamp is not None else (0, 0)
        data.extend(struct.pack('<IQQ', int(stamp is not None), size, modified))
    data.extend(struct.pack('<I', int(launcher is not None)))
    if launcher is not None:
        string(Path(launcher).resolve())
        data.extend(bytes.fromhex(hash_file(Path(launcher))))
    return token, bytes(data)


def _steam_launcher():
    from cdmw.core.archive_format import discover_steam_roots
    candidates = {path.resolve() for folder in discover_steam_roots() if (path := folder / 'steam.exe').is_file()}
    if len(candidates) != 1:
        raise VirtualLoaderError('A single installed Steam client is required for the verified game launch.')
    return candidates.pop()


def launch(plan, *, stop_event=None):
    # Recheck the compiled gate and all inputs at the last possible point.
    checked = prepare_launch(plan.root, stop_event=stop_event)
    if checked != plan:
        raise VirtualLoaderError('The launch plan changed. Review it again.')
    raise_if_cancelled(stop_event)
    profile = verify_snapshot(plan.root, stop_event=stop_event)
    if digest(canonical(profile)) != plan.manifest_sha256:
        raise VirtualLoaderError('The launch plan changed. Review it again.')
    return _start(plan.root, profile, mode=1, stop_event=stop_event)


def _observe_receipt(action, *args, **kwargs):
    """Bookkeeping failures never replace a truthful operation outcome."""
    try:
        return action(*args, **kwargs), ()
    except Exception as exc:
        return None, ('Session receipt could not be recorded: ' + str(exc)[:900],)


def _start(root, profile, *, mode, stop_event=None, extra_guards=(),
           session_token=None, receipt_diagnostics=()):
    from cdmw.services import virtual_loader_receipts as receipts
    token = session_token or uuid4().hex
    diagnostics = tuple(receipt_diagnostics)
    if session_token is not None:
        prepared, notes = _observe_receipt(receipts.launch_attempt, root, profile, token, stop_event=stop_event)
        diagnostics += notes
        if prepared:
            token, _captured = prepared
        else:
            # A broken receipt cannot force reuse of a prior native launch token.
            token, session_token = uuid4().hex, None
    if session_token is None:
        begun, notes = _observe_receipt(receipts.begin_attempt, root, profile,
                                       attempt=token, stop_event=stop_event)
        diagnostics += notes
        if begun:
            diagnostics += tuple(begun[1].to_dict()['diagnostics'])
    try:
        result, launch_sha, host_sha = _start_process(root, profile, mode=mode, stop_event=stop_event,
                                           extra_guards=extra_guards, session_token=token)
    except Exception as exc:
        _observe_receipt(receipts.record_failure, root, token, exc)
        raise
    # Popen has succeeded. No late cancellation or receipt failure can turn this
    # into a reported cancellation or suggest that the host was rolled back.
    captured, notes = _observe_receipt(receipts.record_launch, root, token, result.pid, launch_sha, host_sha)
    return receipts.attach_receipt(result, captured, (*diagnostics, *notes))


def _start_process(root, profile, *, mode, stop_event=None, extra_guards=(), session_token=None):
    from cdmw.services.new_item_service import game_is_running
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.process_job_service import breakaway_creation_flags
    if game_is_running():
        raise VirtualLoaderError('Close Crimson Desert before starting a virtual session.')
    folder, evidence = native_bundle(stop_event=stop_event)
    host_checksum = evidence['files']['cdmw_virtual_session.exe']
    with installation_lane(root):
        raise_if_cancelled(stop_event)
        if read_optional(target(root, '.cdmw/virtual-loader/profile.json')) != canonical(profile):
            raise VirtualLoaderError('The virtual profile changed before launch. Review it again.')
        load_profile(root, registry=load_registry(root))
        token, data = session_manifest(root, profile, mode=mode, executable_sha256=GAME_SHA256,
                                       token=session_token, launcher=_steam_launcher(), extra_guards=extra_guards)
        path = target(root, '.cdmw/virtual-loader/launches/' + token + '.bin')
        atomic_write_bytes(path, data)
        # A onefile application's extraction directory disappears on exit. The
        # user-owned session must run from persistent verified CDMW storage.
        with _runtime_file_access(folder / 'cdmw_virtual_session.exe', host_checksum):
            host_bytes = (folder / 'cdmw_virtual_session.exe').read_bytes()
        if digest(host_bytes) != host_checksum:
            raise VirtualLoaderError('The virtual runtime does not match its build provenance.')
        host = target(root, '.cdmw/virtual-loader/hosts/' + host_checksum + '.exe')
        with _runtime_file_access(host, host_checksum):
            existing = read_optional(host)
            if existing is not None and existing != host_bytes:
                raise VirtualLoaderError('The retained session host changed outside CDMW.')
            if existing is None:
                atomic_write_bytes(host, host_bytes)
    # The native host acquires the same lane and pins the snapshot before it
    # starts its own game. It remains alive if CDMW closes or crashes.
    raise_if_cancelled(stop_event)
    with path.with_suffix('.log').open('xb') as log:
        command = [str(host), str(path)]
        if mode == 3:
            command.append('--controlled-probe')
        with _runtime_file_access(host, host_checksum):
            process = subprocess.Popen(command, cwd=str(root),
                creationflags=breakaway_creation_flags() | int(getattr(subprocess, 'CREATE_NO_WINDOW', 0)),
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True)
    return VirtualSessionStatus('starting', token, profile['generation'], process.pid), digest(data), host_checksum


def prepare_experimental_launch(root, *, stop_event=None, on_progress=None):
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.new_item_service import game_is_running
    from cdmw.services.virtual_loader_saves import backup_saves
    from cdmw.services import virtual_loader_receipts as receipts
    root = Path(root).resolve()
    with installation_lane(root):
        if on_progress:
            on_progress(0, 100, 'Checking the launch runtime…')
        status = runtime_status(root, experimental=True, stop_event=stop_event)
        if status.state != 'ready':
            raise VirtualLoaderError(status.detail)
        profile = load_profile(root, registry=load_registry(root))
        if not profile:
            raise VirtualLoaderError('The launch plan changed. Review it again.')
        plan = VirtualLaunchPlan(root, profile['generation'], target(root, 'bin64/CrimsonDesert.exe'),
                                 GAME_SHA256, generation_path(root, profile['generation']), digest(canonical(profile)))
        token = uuid4().hex
        begun, diagnostics = _observe_receipt(receipts.begin_attempt, root, profile,
                                             attempt=token, stop_event=stop_event)
        if begun:
            diagnostics += tuple(begun[1].to_dict()['diagnostics'])
        backup = None
        try:
            if on_progress:
                on_progress(45, 100, 'Backing up saved games…')
            backup = backup_saves(plan, stop_event=stop_event)
            captured, notes = _observe_receipt(receipts.record_backup, root, token, plan, backup)
            diagnostics += notes
            if captured:
                diagnostics += tuple(captured[1].to_dict()['diagnostics'])
            if game_is_running():
                raise VirtualLoaderError('Close Crimson Desert before starting a virtual session.')
            raise_if_cancelled(stop_event)
            if on_progress:
                on_progress(100, 100, 'Save backup verified. Ready for launch review.')
            return ExperimentalLaunchReview(plan, backup, token, tuple(dict.fromkeys(diagnostics)))
        except Exception as exc:
            _observe_receipt(receipts.record_failure, root, token, exc, backup_published=backup is not None)
            raise


def launch_experimental(review, *, confirmed=False, stop_event=None, on_progress=None):
    if not confirmed:
        raise PermissionError('Controlled virtual loading requires an explicitly reviewed launch plan and save backup.')
    try:
        return _launch_experimental(review, confirmed=True, stop_event=stop_event, on_progress=on_progress)
    except Exception as exc:
        if review.receipt_token and not target(review.plan.root,
                '.cdmw/virtual-loader/launches/' + review.receipt_token + '.bin').exists():
            from cdmw.services.virtual_loader_receipts import record_failure
            _observe_receipt(record_failure, review.plan.root, review.receipt_token, exc)
        raise


def _launch_experimental(review, *, confirmed=False, stop_event=None, on_progress=None):
    """User-reviewed test launch with enforced save backup and native guards."""
    from cdmw.services.new_item_service import game_is_running
    from cdmw.services.virtual_loader_saves import verify_backup
    if not confirmed:
        raise PermissionError('Controlled virtual loading requires an explicitly reviewed launch plan and save backup.')
    def progress(value, detail):
        raise_if_cancelled(stop_event)
        if on_progress:
            on_progress(value, 100, detail)
    with installation_lane(review.plan.root):
        if game_is_running():
            raise VirtualLoaderError('Close Crimson Desert before starting a virtual session.')
        progress(0, 'Checking the launch runtime…')
        setup = prepare_runtime_setup(review.plan.root, stop_event=stop_event)
        if setup.previous is None or digest(setup.previous) != setup.checksum:
            raise VirtualLoaderError('Install the reviewed diagnostic runtime before starting a trace.')
        # The host owns the complete, pinned content check under its installation
        # lease before starting Steam. Do not read the entire game a second time
        # here. Preserve immediate feedback for changed packages and snapshots.
        profile = _snapshot_preflight(review.plan.root, stop_event=stop_event,
            on_progress=lambda value, total, detail: progress(10 + 65 * value // max(1, total), detail))
        checked = VirtualLaunchPlan(review.plan.root, profile['generation'], target(review.plan.root, 'bin64/CrimsonDesert.exe'),
            GAME_SHA256, generation_path(review.plan.root, profile['generation']), digest(canonical(profile)))
        if checked != review.plan:
            raise VirtualLoaderError('The controlled launch plan changed. Review it again.')
        progress(80, 'Verifying the save backup…')
        guards = verify_backup(review, stop_event=stop_event)
        profile = load_profile(review.plan.root)
        if digest(canonical(profile)) != checked.manifest_sha256:
            raise VirtualLoaderError('The controlled launch plan changed. Review it again.')
    progress(95, 'Starting the session host…')
    return _start(review.plan.root, profile, mode=3, stop_event=stop_event, extra_guards=guards,
                  session_token=review.receipt_token or None, receipt_diagnostics=review.diagnostics)


def prepare_diagnostic_trace(root, *, stop_event=None):
    setup = prepare_runtime_setup(root, stop_event=stop_event)
    if setup.previous is None or digest(setup.previous) != setup.checksum:
        raise VirtualLoaderError('Install the reviewed diagnostic runtime before starting a trace.')
    profile = verify_snapshot(root, stop_event=stop_event)
    root = Path(root).resolve()
    return VirtualLaunchPlan(root, profile['generation'], target(root, 'bin64/CrimsonDesert.exe'), GAME_SHA256,
                             generation_path(root, profile['generation']), digest(canonical(profile)))


def start_diagnostic_trace(root, *, confirmed=False, expected_plan=None, stop_event=None):
    """An explicitly reviewed startup trace, never virtual game loading."""
    if not confirmed:
        raise PermissionError('A diagnostic game launch requires explicit review.')
    checked = prepare_diagnostic_trace(root, stop_event=stop_event)
    if expected_plan is not None and expected_plan != checked:
        raise VirtualLoaderError('The diagnostic launch plan changed. Review it again.')
    profile = load_profile(root)
    if digest(canonical(profile)) != checked.manifest_sha256:
        raise VirtualLoaderError('The diagnostic launch plan changed. Review it again.')
    return _start(Path(root).resolve(), profile, mode=0, stop_event=stop_event)


def start_controlled_probe(root, *, confirmed=False, expected_plan=None, stop_event=None):
    """Low-level acceptance run; the UI uses save-verified launch_experimental.

    The caller must retain a verified save backup and review the runtime setup.
    The native host/runtime still enforce the exact game, bootstrap, Steam
    process and early startup path. This does not open the public release gate.
    """
    if not confirmed or expected_plan is None:
        raise PermissionError('Controlled virtual loading requires an explicitly reviewed launch plan and save backup.')
    checked = prepare_diagnostic_trace(root, stop_event=stop_event)
    if expected_plan != checked:
        raise VirtualLoaderError('The controlled launch plan changed. Review it again.')
    profile = load_profile(root)
    if digest(canonical(profile)) != checked.manifest_sha256:
        raise VirtualLoaderError('The controlled launch plan changed. Review it again.')
    return _start(Path(root).resolve(), profile, mode=3, stop_event=stop_event)


def session_status(root, token, *, host_pid=None, stop_event=None):
    from cdmw.domain.new_item.independent import package_id
    from cdmw.services import virtual_loader_receipts as receipts
    package_id(token)
    try:
        status, report, report_sha = _session_observation(root, token, host_pid=host_pid)
    except Exception as exc:
        _observe_receipt(receipts.record_status_error, root, token, exc)
        raise
    captured, notes = _observe_receipt(receipts.record_status, root, token, status,
        host_pid=host_pid, report=report, report_sha256=report_sha, stop_event=stop_event)
    return receipts.attach_receipt(status, captured, notes)


def _session_observation(root, token, *, host_pid=None):
    path = target(root, '.cdmw/virtual-loader/session-' + token + '.json')
    try:
        with path.open('rb') as reader:
            raw = reader.read(4097)
    except FileNotFoundError:
        if host_pid is not None and not _process_alive(host_pid):
            return VirtualSessionStatus('blocked', 'The session host exited before reporting readiness. Review the launch diagnostics.'), None, None
        return VirtualSessionStatus('starting', 'Waiting for runtime readiness.'), None, None
    value = decode(raw, limit=4096)
    if not isinstance(value, dict):
        raise VirtualLoaderError('Unsupported runtime session status.')
    state = value.get('state')
    if state not in ('starting', 'running', 'tracing', 'stopped', 'blocked'):
        raise VirtualLoaderError('Unsupported runtime session status.')
    pid = value.get('pid')
    if type(pid) is not int or pid < 0:
        raise VirtualLoaderError('Invalid runtime process identity.')
    progress = value.get('progress')
    if progress is not None and (type(progress) is not int or not 0 <= progress <= 100):
        raise VirtualLoaderError('Invalid runtime session progress.')
    def observed(status):
        return status, value, digest(raw)
    if state == 'starting' and pid == 0:
        expected_host = value.get('host_pid', host_pid)
        if not _process_alive(expected_host):
            return observed(VirtualSessionStatus('blocked', 'The session host exited before reporting readiness. Review the launch diagnostics.'))
        return observed(VirtualSessionStatus('starting', value.get('detail') or 'Waiting for runtime readiness.', progress=progress))
    if state in ('starting', 'running', 'tracing') and not _process_alive(pid):
        return observed(VirtualSessionStatus('stopped', 'The game session ended.', pid=pid))
    details = {'starting': 'Waiting for runtime readiness.', 'running': 'The virtual session is running.',
               'tracing': 'Diagnostic trace running. Virtual files are not active.', 'stopped': 'The game session ended.',
               'blocked': 'The runtime refused this session. Review its diagnostics before retrying.'}
    return observed(VirtualSessionStatus(state, value.get('detail') or details[state], pid=pid, progress=progress))


def _process_alive(pid):
    # Query only the reported process; never enumerate or terminate other games.
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5  # An inaccessible live process is not proof of exit.
    try:
        return kernel.WaitForSingleObject(handle, 0) != 0
    finally:
        kernel.CloseHandle(handle)


@archive_write_scope()
def remove_runtime(root, *, expected_sha256, confirmed=False, stop_event=None):
    from cdmw.services.new_item_service import game_is_running
    if not confirmed:
        raise PermissionError('Runtime removal requires review of its exact target.')
    root = Path(root).resolve()
    with installation_lane(root):
        if game_is_running():
            raise VirtualLoaderError('Close Crimson Desert before removing its runtime.')
        path, owner_path = target(root, RUNTIME_PATH), target(root, OWNER_PATH)
        payload, owner = read_optional(path), read_optional(owner_path)
        if payload is None or owner is None or digest(payload) != expected_sha256 or decode(owner).get('sha256') != expected_sha256:
            raise VirtualLoaderError('The runtime changed or its ownership is unknown. Removal is refused.')
        raise_if_cancelled(stop_event)
        backup = target(root, '.cdmw/virtual-loader/runtime-backups/' + uuid4().hex)
        atomic_write_bytes(backup / 'CDMWVirtualLoader.asi', payload)
        atomic_write_bytes(backup / 'owner.json', owner)
        if (backup / 'CDMWVirtualLoader.asi').read_bytes() != payload or (backup / 'owner.json').read_bytes() != owner:
            raise VirtualLoaderError('Runtime recovery material failed verification.')
        try:
            path.unlink()
            owner_path.unlink()
        except Exception:
            atomic_write_bytes(path, payload)
            atomic_write_bytes(owner_path, owner)
            raise
        return backup


@dataclass(frozen=True)
class RuntimeSetup:
    root: Path
    payload: bytes
    previous: bytes | None
    previous_owner: bytes | None
    checksum: str

    @property
    def owned(self):
        if self.previous is None or self.previous_owner is None:
            return False
        try:
            owner = decode(self.previous_owner)
        except ValueError:
            return False
        return (isinstance(owner, dict) and owner.get('format') == 'cdmw_virtual_runtime_owner_v1'
                and owner.get('sha256') == digest(self.previous))


def prepare_runtime_setup(root, *, stop_event=None):
    root = Path(root).resolve()
    if hash_file(target(root, 'bin64/CrimsonDesert.exe'), stop_event) != GAME_SHA256:
        raise VirtualLoaderError('This executable build is not supported by the diagnostic runtime.')
    # Bootstrap behavior must be observed during the controlled diagnostic run;
    # do not install or reconfigure another loader to manufacture readiness.
    if not target(root, 'bin64/winmm.dll').is_file() or hash_file(target(root, 'bin64/winmm.dll'), stop_event) != BOOTSTRAP_SHA256:
        raise VirtualLoaderError('The existing compatible ASI bootstrap is required. Its installation is separate.')
    folder, evidence = native_bundle(stop_event=stop_event)
    previous = read_optional(target(root, RUNTIME_PATH))
    owner = read_optional(target(root, OWNER_PATH))
    checksum = evidence['files']['CDMWVirtualLoader.asi']
    plan = RuntimeSetup(root, (folder / 'CDMWVirtualLoader.asi').read_bytes(), previous, owner, checksum)
    if previous is not None and digest(previous) != checksum and not plan.owned:
        raise VirtualLoaderError('A file with the runtime name is not owned by this setup. It will not be overwritten.')
    return plan


@archive_write_scope()
def apply_runtime_setup(plan, *, confirmed=False, stop_event=None):
    from cdmw.services.new_item_service import game_is_running
    if not confirmed and not plan.owned:
        raise PermissionError('Runtime setup requires review of its exact target and checksum.')
    with installation_lane(plan.root):
        if game_is_running():
            raise VirtualLoaderError('Close Crimson Desert before changing its runtime setup.')
        if digest(plan.payload) != plan.checksum or prepare_runtime_setup(plan.root, stop_event=stop_event) != plan:
            raise VirtualLoaderError('The runtime setup changed after review.')
        raise_if_cancelled(stop_event)
        if plan.owned and digest(plan.previous) == plan.checksum:
            return plan.checksum
        recovery = target(plan.root, '.cdmw/virtual-loader/runtime-backups/' + uuid4().hex)
        recovery.mkdir(parents=True)
        for name, raw in (('CDMWVirtualLoader.asi', plan.previous), ('owner.json', plan.previous_owner)):
            if raw is not None:
                atomic_write_bytes(recovery / name, raw)
                if (recovery / name).read_bytes() != raw:
                    raise VirtualLoaderError('Runtime recovery material failed verification.')
        try:
            atomic_write_bytes(target(plan.root, RUNTIME_PATH), plan.payload)
            atomic_write_bytes(target(plan.root, OWNER_PATH), canonical({'format': 'cdmw_virtual_runtime_owner_v1', 'sha256': plan.checksum}))
        except Exception:
            from cdmw.services.virtual_loader_state import _write_optional
            _write_optional(target(plan.root, RUNTIME_PATH), plan.previous)
            _write_optional(target(plan.root, OWNER_PATH), plan.previous_owner)
            raise
        return plan.checksum
