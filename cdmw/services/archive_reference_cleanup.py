"""Reviewed removal of absent mod indexes from the archive mount list."""
from dataclasses import dataclass
from pathlib import Path

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.core.papgt_format import parse_papgt, serialize_papgt
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.application_shutdown_service import archive_write_scope
from cdmw.services.archive_overlay_manager import _target, _verify_backup
from cdmw.services.installation_lane import serialized_installation
from cdmw.services.overlay_inventory_details import mounted_archive_status


@dataclass(frozen=True)
class ArchiveReferenceCleanup:
    package_root: Path
    before: bytes
    names: tuple[str, ...]


def prepare_missing_reference_cleanup(package_root, *, stop_event=None):
    """Capture the exact mount list and absent non-game references without writes."""
    raise_if_cancelled(stop_event)
    if not str(package_root).strip():
        raise ValueError('Choose a game archive folder first.')
    root = Path(package_root).resolve()
    target = _target(root, 'meta/0.papgt')
    if target.stat().st_size > 1024 * 1024:
        raise ValueError('Archive mount table is unexpectedly large.')
    before = target.read_bytes()
    rows = mounted_archive_status(root, stop_event=stop_event)
    names = tuple(dict.fromkeys(row.name for row in rows if not row.game and not row.present))
    if target.read_bytes() != before:
        raise ValueError('The archive list changed. Refresh and prepare cleanup again.')
    for name in names:
        # An unreadable index or an index-shaped directory is not a missing file.
        if _target(root, name + '/0.pamt').exists():
            raise ValueError(f'The archive index for {name} is not absent. Check the folder before cleanup.')
    return ArchiveReferenceCleanup(root, before, names)


@archive_write_scope()
@serialized_installation(lambda preparation, **_kwargs: getattr(preparation, 'package_root', None))
def apply_missing_reference_cleanup(preparation, *, confirmed, mutations,
                                    game_running=None, stop_event=None, on_log=None):
    """Back up, revalidate and atomically publish only meta/0.papgt; return its backup."""
    if not isinstance(preparation, ArchiveReferenceCleanup):
        raise TypeError('Archive cleanup requires a prepared change.')
    if not confirmed:
        raise PermissionError('Archive cleanup requires explicit confirmation.')
    if not preparation.names:
        raise ValueError('There are no missing mod references to clean.')
    if game_running is None:
        from cdmw.services.new_item_service import game_is_running
        game_running = game_is_running

    def validate():
        raise_if_cancelled(stop_event, 'Archive reference cleanup cancelled.')
        if game_running():
            raise RuntimeError('Close Crimson Desert before cleaning archive references.')
        current = prepare_missing_reference_cleanup(preparation.package_root, stop_event=stop_event)
        if current != preparation:
            raise ValueError('The archive list or missing folders changed. Refresh and prepare cleanup again.')

    validate()
    root = preparation.package_root
    target = _target(root, 'meta/0.papgt')
    records = parse_papgt(preparation.before)
    payload = serialize_papgt([row for row in records if row.name not in preparation.names],
                              header=preparation.before[:12])
    backup_dir = Path(mutations.backup_files((target,), description='Clean missing mod references', on_log=on_log))
    _verify_backup(backup_dir, {target: preparation.before})
    # Refuse a changed list/reappearing index without overwriting the newer state.
    validate()
    try:
        # Publication and verification form one non-interruptible unit.
        atomic_write_bytes(target, payload)
        if target.read_bytes() != payload:
            raise RuntimeError('The cleaned archive list differs from the reviewed change.')
    except BaseException as error:
        try:
            mutations.restore_backup(backup_dir, confirmed=True, on_log=on_log)
            if target.read_bytes() != preparation.before:
                raise RuntimeError('The original archive list was not restored.')
        except Exception as rollback_error:
            raise RuntimeError(f'Archive cleanup failed; restore backup {backup_dir}: {rollback_error}') from error
        raise
    if on_log:
        on_log(f'Cleaned missing references: {", ".join(preparation.names)}. Backup: {backup_dir}')
    return backup_dir
