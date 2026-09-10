"""Immutable requests on the existing serialized New Item utility worker."""
from pathlib import Path

from cdmw.services.mod_update_service import (
    export_updated_mod, prepare_installed_overlay_update, prepare_mod_update,
)
from cdmw.workers.new_item_workers import list_archive_entries


def mod_update_scan_task(folder, game_root, *, installed=False):
    folder, game_root, installed = Path(folder), Path(game_root), bool(installed)
    def run(log, stop):
        entries = list_archive_entries(game_root, log, stop)
        if installed:
            return prepare_installed_overlay_update(game_root, entries=entries, on_log=log, stop_event=stop)
        return prepare_mod_update(folder, game_root, entries=entries, on_log=log, stop_event=stop)
    return run


def mod_update_export_task(plan, destination, title):
    destination, title = Path(destination), str(title)
    return lambda log, stop: export_updated_mod(plan, destination, title=title, on_log=log, stop_event=stop)
