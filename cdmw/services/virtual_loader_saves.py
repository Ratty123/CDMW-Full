"""Verified copies of saves for experimental launches; never edits live saves."""
import hashlib
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from uuid import uuid4

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.virtual_loader import VirtualLoaderError, VirtualSaveBackup
from cdmw.services.independent_item_package import canonical, digest
from cdmw.services.virtual_loader_composition import hash_file
from cdmw.services.virtual_loader_state import decode, target

BACKUP_PATH = '.cdmw/virtual-loader/save-backups'
MAX_FILES = 4096
MAX_BYTES = 4 * 1024 * 1024 * 1024
CHUNK = 1024 * 1024


def save_root():
    local = os.environ.get('LOCALAPPDATA', '')
    if not local or not Path(local).is_absolute():
        raise VirtualLoaderError('The game save folder could not be found. Start the game normally and create a save first.')
    return Path(local) / 'Pearl Abyss/CD/save'


def _plain(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise VirtualLoaderError('Save backups do not support linked folders or files.')
    return info


def _inventory(root, stop_event=None):
    for path in (root, *root.parents):
        _plain(path)
    result, total, directories = {}, 0, [root]
    visited = 0
    while directories:
        raise_if_cancelled(stop_event)
        directory = directories.pop()
        for path in directory.iterdir():
            raise_if_cancelled(stop_event)
            info = _plain(path)
            visited += 1
            if visited > MAX_FILES * 2:
                raise VirtualLoaderError('The save folder exceeds the supported backup size or file count.')
            if stat.S_ISDIR(info.st_mode):
                directories.append(path)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if len(result) >= MAX_FILES or total > MAX_BYTES:
                    raise VirtualLoaderError('The save folder exceeds the supported backup size or file count.')
                result[path.relative_to(root).as_posix()] = info.st_size
            else:
                raise VirtualLoaderError('Save backups do not support linked folders or files.')
    return result


def _copy(source, destination, expected_size, stop_event):
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied, checksum = 0, hashlib.sha256()
    _plain(source)
    with source.open('rb') as reader, destination.open('xb') as writer:
        while block := reader.read(CHUNK):
            raise_if_cancelled(stop_event)
            copied += len(block)
            if copied > expected_size:
                raise VirtualLoaderError('The save files changed during backup. Close the game and try again.')
            writer.write(block)
            checksum.update(block)
        writer.flush()
        os.fsync(writer.fileno())
    if copied != expected_size or hash_file(destination, stop_event) != checksum.hexdigest():
        raise VirtualLoaderError('The save backup could not be verified. Prepare the launch again.')
    return checksum.hexdigest()


def _records(root, stop_event=None):
    before = _inventory(root, stop_event)
    records = {name: {'size': size, 'sha256': hash_file(target(root, name), stop_event)}
               for name, size in sorted(before.items())}
    if _inventory(root, stop_event) != before:
        raise VirtualLoaderError('The save files changed during backup. Close the game and try again.')
    return records


def backup_saves(plan, *, stop_event=None):
    """Caller holds the installation lane and has verified that the game is closed."""
    source = save_root()
    if not source.is_dir():
        raise VirtualLoaderError('The game save folder could not be found. Start the game normally and create a save first.')
    inventory = _inventory(source, stop_event)
    if not inventory:
        raise VirtualLoaderError('The game save folder could not be found. Start the game normally and create a save first.')
    base = target(plan.root, BACKUP_PATH)
    base.mkdir(parents=True, exist_ok=True)
    destination = target(plan.root, BACKUP_PATH + '/' + uuid4().hex)
    # TemporaryDirectory owns only this new child, never the live save tree or
    # previous backups. A backup becomes visible as complete in one rename.
    with TemporaryDirectory(prefix='.pending-', dir=base) as temporary:
        staged, records = Path(temporary), {}
        for name, size in sorted(inventory.items()):
            checksum = _copy(target(source, name), target(staged, 'files/' + name), size, stop_event)
            records[name] = {'size': size, 'sha256': checksum}
        if _records(source, stop_event) != records:
            raise VirtualLoaderError('The save files changed during backup. Close the game and try again.')
        manifest = canonical({'format': 'cdmw_virtual_save_backup_v1', 'source': str(source),
                              'game_root': str(plan.root), 'generation': plan.generation,
                              'profile_sha256': plan.manifest_sha256, 'files': records})
        with (staged / 'manifest.json').open('xb') as writer:
            writer.write(manifest)
            writer.flush()
            os.fsync(writer.fileno())
        raise_if_cancelled(stop_event)
        staged.rename(destination)
    return VirtualSaveBackup(destination, source, digest(manifest))


def verify_backup(review, *, stop_event=None):
    plan, backup = review.plan, review.backup
    base = target(plan.root, BACKUP_PATH)
    if backup.directory.parent != base or not backup.directory.name.isalnum():
        raise VirtualLoaderError('The save backup could not be verified. Prepare the launch again.')
    directory = target(plan.root, BACKUP_PATH + '/' + backup.directory.name)
    manifest_path = target(directory, 'manifest.json')
    if manifest_path.stat().st_size > 4 * 1024 * 1024:
        raise VirtualLoaderError('The save backup could not be verified. Prepare the launch again.')
    raw = manifest_path.read_bytes()
    if digest(raw) != backup.manifest_sha256:
        raise VirtualLoaderError('The save backup could not be verified. Prepare the launch again.')
    value = decode(raw, limit=4 * 1024 * 1024)
    if not isinstance(value, dict) or value != {'format': 'cdmw_virtual_save_backup_v1', 'source': str(backup.source),
                 'game_root': str(plan.root), 'generation': plan.generation,
                 'profile_sha256': plan.manifest_sha256, 'files': value.get('files')}:
        raise VirtualLoaderError('The save backup could not be verified. Prepare the launch again.')
    if save_root() != backup.source:
        raise VirtualLoaderError('The game save folder changed. Prepare the launch again.')
    if _records(directory / 'files', stop_event) != value['files']:
        raise VirtualLoaderError('The save backup could not be verified. Prepare the launch again.')
    if _records(backup.source, stop_event) != value['files']:
        raise VirtualLoaderError('The saved game changed after backup. Prepare the launch again.')
    return ((str(manifest_path), backup.manifest_sha256),) + tuple(
        (str(base / name), row['sha256']) for base in (backup.source, directory / 'files')
        for name, row in sorted(value['files'].items()))
