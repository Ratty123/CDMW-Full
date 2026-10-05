"""Audited startup handoff. Game redirection is gated independently of preparation."""
from dataclasses import dataclass
import os
from pathlib import Path
import struct
import subprocess
import sys
from uuid import uuid4

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.virtual_loader import VirtualLaunchPlan, VirtualLoaderError, VirtualSessionStatus
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services.installation_lane import installation_lane, lock_path
from cdmw.services.virtual_loader_composition import hash_file
from cdmw.services.virtual_loader_state import target, load_profile, generation_path, decode, read_optional
from cdmw.services.application_shutdown_service import archive_write_scope

GAME_SHA256 = '57da440d72f4db974f25fef047cf84c4dadd999a88cb2a3c5af4c9bd67fde1e7'
BOOTSTRAP_SHA256 = '810111a7f6a6cef892877c9f7c4582ccde2d621d119891f700c5309c370508bf'
GAME_REDIRECTION_APPROVED = False  # Requires actual startup, handoff and save evidence.
RUNTIME_PATH = 'bin64/CDMWVirtualLoader.asi'
OWNER_PATH = '.cdmw/virtual-loader/runtime-owner.json'


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
        if hash_file(folder / name, stop_event) != expected:
            raise VirtualLoaderError('The virtual runtime does not match its build provenance.')
    return folder, evidence


def verify_snapshot(root, *, stop_event=None):
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.mod_merge_service import _inventory
    root = Path(root).resolve()
    profile = load_profile(root, registry=load_registry(root))
    if not profile:
        raise VirtualLoaderError('Prepare a virtual profile first.')
    directory = generation_path(root, profile['generation'])
    for relative, checksum in profile['files'].items():
        if hash_file(target(directory, 'files/' + relative), stop_event) != checksum:
            raise VirtualLoaderError('A prepared virtual file changed. Prepare the profile again.')
    for path, checksum in profile['sources']:
        if hash_file(Path(path), stop_event) != checksum:
            raise VirtualLoaderError('A game or mod source changed. Prepare the profile again.')
    for folder, expected in profile['inventories']:
        if canonical(_inventory(Path(folder), stop_event)) != canonical(expected):
            raise VirtualLoaderError('A mounted archive or selected mod folder changed. Prepare the profile again.')
    for relative, checksum in profile['observed']:
        data = read_optional(target(root, relative))
        if (digest(data) if data is not None else None) != checksum:
            raise VirtualLoaderError('The mounted installation changed. Prepare the profile again.')
    return profile


def runtime_status(root, *, stop_event=None):
    root = Path(root).resolve()
    if target(root, '.cdmw/virtual-loader/transaction.json').exists():
        return VirtualSessionStatus('blocked', 'Recover the interrupted virtual profile transaction first.')
    profile = load_profile(root)
    generation = profile['generation'] if profile else ''
    exe = target(root, 'bin64/CrimsonDesert.exe')
    if not exe.is_file():
        return VirtualSessionStatus('unavailable', 'Choose the installed Crimson Desert game folder.', generation)
    if hash_file(exe, stop_event) != GAME_SHA256:
        return VirtualSessionStatus('blocked', 'This executable build has not been verified for the virtual loader.', generation)
    try:
        folder, evidence = native_bundle(stop_event=stop_event)
    except ValueError as exc:
        return VirtualSessionStatus('unavailable', str(exc), generation)
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


def session_manifest(root, profile, *, mode, executable_sha256, token=None):
    """Bounded UTF-16 wire format shared with the native session/runtime harness."""
    root = Path(root).resolve()
    token = token or uuid4().hex
    data = bytearray(b'CDVFS1\0\0' + struct.pack('<III', mode, 0, 0) + bytes.fromhex(executable_sha256))
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
    data.extend(struct.pack('<I', len(guards)))
    for path, checksum in sorted(guards.items()):
        string(path)
        data.extend(struct.pack('<I', int(checksum is not None)))
        data.extend(bytes.fromhex(checksum) if checksum else bytes(32))
    return token, bytes(data)


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


def _start(root, profile, *, mode, stop_event=None):
    from cdmw.services.new_item_service import game_is_running
    from cdmw.services.process_job_service import breakaway_creation_flags
    if game_is_running():
        raise VirtualLoaderError('Close Crimson Desert before starting a virtual session.')
    folder, _evidence = native_bundle(stop_event=stop_event)
    with installation_lane(root):
        raise_if_cancelled(stop_event)
        if read_optional(target(root, '.cdmw/virtual-loader/profile.json')) != canonical(profile):
            raise VirtualLoaderError('The virtual profile changed before launch. Review it again.')
        token, data = session_manifest(root, profile, mode=mode, executable_sha256=GAME_SHA256)
        path = target(root, '.cdmw/virtual-loader/launches/' + token + '.bin')
        atomic_write_bytes(path, data)
        # A onefile application's extraction directory disappears on exit. The
        # user-owned session must run from persistent verified CDMW storage.
        host_bytes = (folder / 'cdmw_virtual_session.exe').read_bytes()
        host = target(root, '.cdmw/virtual-loader/hosts/' + digest(host_bytes) + '.exe')
        existing = read_optional(host)
        if existing is not None and existing != host_bytes:
            raise VirtualLoaderError('The retained session host changed outside CDMW.')
        if existing is None:
            atomic_write_bytes(host, host_bytes)
    # The native host acquires the same lane and pins the snapshot before it
    # starts its own game. It remains alive if CDMW closes or crashes.
    with path.with_suffix('.log').open('xb') as log:
        process = subprocess.Popen([str(host), str(path)], cwd=str(root),
            creationflags=breakaway_creation_flags() | int(getattr(subprocess, 'CREATE_NO_WINDOW', 0)),
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True)
    return VirtualSessionStatus('starting', token, profile['generation'], process.pid)


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


def session_status(root, token, *, host_pid=None):
    from cdmw.domain.new_item.independent import package_id
    package_id(token)
    path = target(root, '.cdmw/virtual-loader/session-' + token + '.json')
    raw = read_optional(path)
    if raw is None:
        if host_pid is not None and not _process_alive(host_pid):
            return VirtualSessionStatus('blocked', 'The session host exited before reporting readiness. Review the launch diagnostics.')
        return VirtualSessionStatus('starting', 'Waiting for runtime readiness.')
    value = decode(raw, limit=4096)
    state = value.get('state')
    if state not in ('starting', 'running', 'tracing', 'stopped', 'blocked'):
        raise VirtualLoaderError('Unsupported runtime session status.')
    pid = value.get('pid')
    if type(pid) is not int or pid < 0:
        raise VirtualLoaderError('Invalid runtime process identity.')
    if state in ('starting', 'running', 'tracing') and not _process_alive(pid):
        return VirtualSessionStatus('stopped', 'The game session ended.', pid=pid)
    details = {'starting': 'Waiting for runtime readiness.', 'running': 'The virtual session is running.',
               'tracing': 'Diagnostic trace running. Virtual files are not active.', 'stopped': 'The game session ended.',
               'blocked': 'The runtime refused this session. Review its diagnostics before retrying.'}
    return VirtualSessionStatus(state, value.get('detail') or details[state], pid=pid)


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
    if previous is not None and digest(previous) != checksum and (owner is None or decode(owner).get('sha256') != digest(previous)):
        raise VirtualLoaderError('A file with the runtime name is not owned by this setup. It will not be overwritten.')
    return RuntimeSetup(root, (folder / 'CDMWVirtualLoader.asi').read_bytes(), previous, owner, checksum)


@archive_write_scope()
def apply_runtime_setup(plan, *, confirmed=False, stop_event=None):
    from cdmw.services.new_item_service import game_is_running
    if not confirmed:
        raise PermissionError('Runtime setup requires review of its exact target and checksum.')
    with installation_lane(plan.root):
        if game_is_running():
            raise VirtualLoaderError('Close Crimson Desert before changing its runtime setup.')
        if digest(plan.payload) != plan.checksum or prepare_runtime_setup(plan.root, stop_event=stop_event) != plan:
            raise VirtualLoaderError('The runtime setup changed after review.')
        raise_if_cancelled(stop_event)
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
