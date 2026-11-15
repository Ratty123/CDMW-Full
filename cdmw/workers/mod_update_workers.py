"""Immutable requests on the existing serialized New Item utility worker."""
from pathlib import Path

from cdmw.services.mod_update_service import export_updated_mod, prepare_mod_update
from cdmw.workers.new_item_workers import list_archive_entries


def mod_update_scan_task(folder, game_root):
    folder, game_root = Path(folder), Path(game_root)
    def run(log, progress, stop):
        progress(0, 0, "Finding the game archives...")
        entries = list_archive_entries(game_root, log, stop, progress=progress)
        return prepare_mod_update(folder, game_root, entries=entries, on_log=log, stop_event=stop, progress=progress)
    return run


def mod_update_export_task(plan, destination, title):
    destination, title = Path(destination), str(title)
    return lambda log, stop: export_updated_mod(plan, destination, title=title, on_log=log, stop_event=stop)
