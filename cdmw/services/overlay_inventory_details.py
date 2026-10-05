"""Read-only inspector data for CDMW's overlay workspace."""
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

from cdmw.core.papgt_format import parse_papgt
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.archive_overlay_manager import _load_index, _unpack_changes, overlay_journal_path


@dataclass(frozen=True)
class MountedArchive:
    name: str
    game: bool
    present: bool
    optional: bool


def mounted_archive_status(package_root, *, stop_event=None):
    """Inspect the mount list and folder presence without reading game payloads."""
    root = Path(package_root).resolve()
    path = root / 'meta/0.papgt'
    if not str(package_root).strip() or not path.is_file():
        raise ValueError('Choose a game archive folder to read installed overlays.')
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Archive mount table is unexpectedly large.')
    rows = []
    for record in parse_papgt(path.read_bytes()):
        raise_if_cancelled(stop_event)
        directory = (root / record.name).resolve()
        if directory.parent != root:
            raise ValueError(f'Mounted archive is outside the game folder: {record.name}')
        game = len(record.name) == 4 and record.name.isascii() and record.name.isdigit() and int(record.name) < 36
        rows.append(MountedArchive(record.name, game, (directory / '0.pamt').is_file(), bool(record.flags & 0xff)))
    return tuple(rows)


def overlay_details(package_root, overlay_id, *, stop_event=None):
    root = Path(package_root).resolve()
    state = _load_index(root)
    layer = next((row for row in state['layers'] if row['id'] == overlay_id), None) if state else None
    if layer is None:
        return 'This earlier overlay is managed as one bundle. Individual ownership history is unavailable.'
    changes = _unpack_changes(root, layer, {}, stop_event)
    dependencies = [row['label'] for row in state['layers'] if row['id'] in layer['dependencies']]
    lines = [layer['label'], f"Archive folder: {state['directory']}",
             'Installed: ' + datetime.fromtimestamp(layer['created_at']).strftime('%Y-%m-%d %H:%M'),
             'Dependencies: ' + (', '.join(dependencies) or 'None'),
             'Ownership journal: ' + overlay_journal_path(layer), '', 'Owned changes:']
    for path, change in sorted(changes.items()):
        raise_if_cancelled(stop_event)
        lines.append(('Added: ' if change['before'] is None else 'Changed: ') + path)
    return '\n'.join(lines)


def external_overlay_summary(package_root, *, stop_event=None):
    root = Path(package_root).resolve()
    if not str(package_root).strip() or not (root / 'meta/0.papgt').is_file():
        return 'Choose a game archive folder to read installed overlays.'
    state = _load_index(root)
    owned = state['directory'] if state else None
    names = []
    for record in mounted_archive_status(root, stop_event=stop_event):
        if not record.game and record.name != owned and record.present:
            names.append(record.name)
    return ('Other mounted archive folders: ' + ', '.join(names) + '. Managed externally; compatibility has not been verified.'
            if names else 'No other mounted overlay folders detected.')
