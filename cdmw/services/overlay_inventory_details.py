"""Read-only inspector data for CDMW's overlay workspace."""
from pathlib import Path
from datetime import datetime

from cdmw.core.papgt_format import parse_papgt
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.archive_overlay_manager import _load_index, _unpack_changes, overlay_journal_path


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
    for record in parse_papgt((root / 'meta/0.papgt').read_bytes()):
        raise_if_cancelled(stop_event)
        name = str(record.name)
        if name.isascii() and name.isdigit() and int(name) >= 36 and name != owned and (root / name).is_dir():
            names.append(name)
    return ('Other mounted archive folders: ' + ', '.join(names) + '. Managed externally; compatibility has not been verified.'
            if names else 'No other mounted overlay folders detected.')
