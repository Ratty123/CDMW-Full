"""Launcher-independent virtual loading.

A published standalone profile lets the CDMW runtime activate the applied virtual
profile whenever the game starts, including from Steam or DMM, without a CDMW
session host. The runtime checks every guard itself before hooking any import and
stays inert on a mismatch, so the game then starts unmodded.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import struct

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services.installation_lane import installation_lane
from cdmw.services.new_item_provenance import _stamp
from cdmw.services.virtual_loader_state import target, decode, read_optional

STANDALONE_PATH = '.cdmw/virtual-loader/standalone.bin'
STATUS_PATH = '.cdmw/virtual-loader/standalone-status.json'
TRACE_PATH = '.cdmw/virtual-loader/trace-standalone.bin'
STANDALONE_MODE = 4
# Index files and sources up to this size are hashed by the runtime at every
# launch, so a launcher that rewrites identical indexes keeps the profile valid.
# Larger carriers are checked by size and last-write time, after publication
# hashed their full content once.
HASHED_SOURCE_LIMIT = 1 << 20
ALWAYS_HASHED = ('.papgt', '.pathc', '.pamt')
_TRACE_ROW = struct.Struct('<IIIIq1024s')
# Same event names as scripts/probe_virtual_loader.py.
TRACE_OPERATIONS = {0: 'initialize', 1: 'CreateFileW', 2: 'CreateFile2', 3: 'CreateFileA', 4: 'GetFileAttributesW',
                    5: 'GetFileAttributesExW', 6: 'GetFileAttributesA', 7: 'FindFirstFileW', 8: 'FindFirstFileExW',
                    9: 'hook ownership changed', 10: 'verified bootstrap forwarding', 11: 'loader callout context',
                    12: 'verified startup path', 13: 'file hooks ready'}


@dataclass(frozen=True)
class StandalonePublication:
    path: Path
    generation: str
    hashed_sources: int
    catalogue_sources: int


@dataclass(frozen=True)
class StandaloneStatus:
    state: str
    pid: int
    generation: str
    detail: str
    elapsed_ms: int


@dataclass(frozen=True)
class TraceRow:
    operation: str
    thread: int
    redirected: bool
    last_error: int
    ticks: int
    path: str


def standalone_manifest(root, profile, *, executable_sha256):
    """Serialize the applied profile for runtime-only activation.

    Uses the shared session wire format with mode 4 and no host, process or
    launcher. Indexes and small sources keep content guards; large carriers
    become size/write-time guards from their current, already verified state.
    """
    from cdmw.services.virtual_loader_runtime import session_manifest
    hashed, catalogue = [], [tuple(row) for row in profile.get('catalogue', ())]
    for path, checksum in profile['sources']:
        stamp = _stamp(Path(path))
        if stamp is None:
            raise VirtualLoaderError(f'A game or mod source is missing: {path}. Apply changes again.')
        if stamp[0] <= HASHED_SOURCE_LIMIT or Path(path).suffix.lower() in ALWAYS_HASHED:
            hashed.append((path, checksum))
        else:
            catalogue.append((path, stamp))
    view = dict(profile, sources=hashed, catalogue=sorted(catalogue))
    _token, data = session_manifest(root, view, mode=STANDALONE_MODE, executable_sha256=executable_sha256)
    return data, len(hashed), len(catalogue)


def publish_standalone(root, *, stop_event=None, on_progress=None):
    """Let any launcher use the applied profile. Hashes every source once first."""
    from cdmw.services.new_item_service import game_is_running
    from cdmw.services.virtual_loader_runtime import GAME_SHA256, runtime_status, _verify_snapshot
    root = Path(root).resolve()
    with installation_lane(root):
        if game_is_running():
            raise VirtualLoaderError('Close Crimson Desert before publishing the launcher profile.')
        status = runtime_status(root, experimental=True, stop_event=stop_event)
        if status.state != 'ready':
            raise VirtualLoaderError(status.detail)
        profile = _verify_snapshot(root, stop_event=stop_event, all_sources=True, on_progress=on_progress)
        data, hashed, catalogue = standalone_manifest(root, profile, executable_sha256=GAME_SHA256)
        path = target(root, STANDALONE_PATH)
        atomic_write_bytes(path, data)
        stale = target(root, STATUS_PATH)
        if stale.exists():
            stale.unlink()
        return StandalonePublication(path, profile['generation'], hashed, catalogue)


def withdraw_standalone(root):
    """Stop launcher-independent loading. The applied profile itself is kept."""
    root = Path(root).resolve()
    with installation_lane(root):
        path = target(root, STANDALONE_PATH)
        existed = path.exists()
        if existed:
            path.unlink()
        return existed


def standalone_published(root):
    return target(Path(root).resolve(), STANDALONE_PATH).is_file()


def read_standalone_status(root):
    """The runtime's report from the most recent launch, or None."""
    raw = read_optional(target(Path(root).resolve(), STATUS_PATH))
    if raw is None:
        return None
    value = decode(raw, limit=16384)
    if not isinstance(value, dict) or value.get('state') not in ('ready', 'refused'):
        raise VirtualLoaderError('Unsupported launcher profile status.')
    pid, elapsed = value.get('pid'), value.get('elapsed_ms')
    if type(pid) is not int or pid <= 0 or type(elapsed) is not int or elapsed < 0:
        raise VirtualLoaderError('Invalid launcher profile status.')
    return StandaloneStatus(value['state'], pid, str(value.get('generation', '')), str(value.get('detail', '')), elapsed)


def read_standalone_trace(root):
    """Decode the bounded runtime trace written during the most recent launch."""
    raw = read_optional(target(Path(root).resolve(), TRACE_PATH)) or b''
    rows = []
    for offset in range(0, len(raw) - len(raw) % _TRACE_ROW.size, _TRACE_ROW.size):
        api, thread, redirected, error, ticks, path = _TRACE_ROW.unpack_from(raw, offset)
        text = path.decode('utf-16le', errors='replace').split('\0', 1)[0]
        rows.append(TraceRow(TRACE_OPERATIONS.get(api, f'api {api}'), thread, bool(redirected), error, ticks, text))
    return rows


def status_text(status):
    return json.dumps(status.__dict__, sort_keys=True) if status else 'null'
