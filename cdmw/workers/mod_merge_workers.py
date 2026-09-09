"""Cancellable folder-merge tasks for the existing New Item utility lane."""
from pathlib import Path

from cdmw.services.mod_merge_service import export_merged_mod, prepare_mod_merge
from cdmw.workers.new_item_workers import list_archive_entries


def mod_merge_scan_task(folders, game_root):
    folders, game_root = tuple(map(Path, folders)), Path(game_root)
    def run(log, stop):
        entries = list_archive_entries(game_root, log, stop)
        return prepare_mod_merge(folders, game_root, entries=entries, on_log=log, stop_event=stop)
    return run


def mod_merge_export_task(plan, destination, title):
    destination, title = Path(destination), str(title)
    return lambda log, stop: export_merged_mod(plan, destination, title=title, on_log=log, stop_event=stop)
