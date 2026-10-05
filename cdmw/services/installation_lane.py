"""One cross-process writer/session per installation, independent of Qt lifetime."""
from contextlib import contextmanager, ExitStack
from functools import wraps
import hashlib
import os
from pathlib import Path
import tempfile
import threading

from cdmw.domain.virtual_loader import VirtualLoaderError

_local = threading.local()


def lock_path(root):
    key = hashlib.sha256(str(Path(root).resolve()).casefold().encode('utf-8')).hexdigest()
    return Path(tempfile.gettempdir()) / ('cdmw-installation-' + key + '.lock')


@contextmanager
def installation_lane(root, *, recovery=False):
    root = Path(root).resolve()
    key = str(root).casefold()
    held = getattr(_local, 'held', {})
    if key in held:
        yield
        return
    path = lock_path(root)
    handle = path.open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 2)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise VirtualLoaderError('This installation is in use by another CDMW operation or virtual game session.') from exc
    held[key] = handle
    _local.held = held
    try:
        if not recovery and (root / '.cdmw/virtual-loader/transaction.json').exists():
            raise VirtualLoaderError('Recover the interrupted virtual profile transaction before changing this installation.')
        yield
    finally:
        del held[key]
        handle.close()


def serialized_installation(root_of):
    def decorate(function):
        @wraps(function)
        def guarded(*args, **kwargs):
            root = root_of(*args, **kwargs)
            if root is None:
                return function(*args, **kwargs)
            with installation_lane(root):
                return function(*args, **kwargs)
        return guarded
    return decorate


@contextmanager
def backup_installation_lanes(backup):
    """Restore uses the same lane for every install named by its existing manifest."""
    import json
    manifest = Path(backup) / 'backup_manifest.json'
    roots = set()
    if manifest.is_file():
        if manifest.stat().st_size > 16 * 1024 * 1024:
            raise VirtualLoaderError('The recovery manifest exceeds its supported size.')
        for row in json.loads(manifest.read_bytes()).get('files', ()):
            original = Path(str(row.get('original_path', ''))).resolve()
            if original.suffix.lower() in ('.pamt', '.paz', '.papgt', '.pathc'):
                roots.add(original.parent.parent)
            for parent in original.parents:
                if parent.name == '.cdmw':
                    roots.add(parent.parent)
                    break
    with ExitStack() as stack:
        for root in sorted(roots):
            stack.enter_context(installation_lane(root))
        yield
