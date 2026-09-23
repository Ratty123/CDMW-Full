"""Read a selected installed item's current models without changing its archives."""
from pathlib import Path

from cdmw.domain.cancellation import raise_if_cancelled


def overlay_item_preview_models(snapshot, package_root, directory, item_key, *, stop_event=None):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.domain.archives.safety import safe_archive_output_path
    from cdmw.services.archive_preview_service import build_archive_preview_result
    from cdmw.services.new_item_snapshot import build_snapshot

    raise_if_cancelled(stop_event)
    root = Path(package_root).resolve()
    folder = safe_archive_output_path(root, directory, single_component=True,
                                     error_message='The overlay folder is outside the game package.')
    # The Studio snapshot predates the install. Re-read the overlay index and
    # metadata rather than accidentally showing its original template.
    installed = tuple(parse_archive_pamt(folder / '0.pamt'))
    entries = {path: entry for path, entry in snapshot.entries.items()
               if Path(entry.pamt_path).parent.resolve() != folder}
    entries.update((entry.path.replace('\\', '/').strip('/').lower(), entry) for entry in installed)
    installed_ids = {entry.identity for entry in installed}

    def read(entry):
        raise_if_cancelled(stop_event)
        if entry.identity in installed_ids:
            return read_archive_entry_data(entry, stop_event=stop_event)[0]
        return snapshot.read_entry(entry)

    current = build_snapshot(entries.values(), read_entry=read, stop_event=stop_event)
    family = current.family(item_key)
    by_path, by_basename = current.archive_index_maps()
    models = []
    for component in family.files_for('pac'):
        raise_if_cancelled(stop_event)
        if not component.exists:
            continue
        result = build_archive_preview_result(
            current.entry(component.path),
            texture_entries_by_normalized_path=by_path,
            texture_entries_by_basename=by_basename,
            enable_hkx_visual_preview=False,
            stop_event=stop_event,
        )
        model = getattr(result, 'preview_model', None)
        if model is not None and getattr(model, 'meshes', None):
            models.append(model)
    if not models:
        raise ValueError(f'Installed item {item_key} has no previewable model.')
    return tuple(models)
