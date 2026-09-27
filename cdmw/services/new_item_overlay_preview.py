"""Read a selected installed item's current models without changing its archives."""
from pathlib import Path

from cdmw.domain.cancellation import raise_if_cancelled


def overlay_item_preview_models(snapshot, package_root, directory, item_key, *, stop_event=None,
                                resident_source=None):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.domain.archives.safety import safe_archive_output_path
    from cdmw.services.archive_preview_service import build_archive_preview_result

    raise_if_cancelled(stop_event)
    root = Path(package_root).resolve()
    folder = safe_archive_output_path(root, directory, single_component=True,
                                     error_message='The overlay folder is outside the game package.')
    # The Studio snapshot predates the install. Re-read the overlay index and
    # metadata rather than accidentally showing its original template.
    installed = tuple(parse_archive_pamt(folder / '0.pamt'))
    from cdmw.core.papgt_format import parse_papgt
    mounts = parse_papgt((root / 'meta/0.papgt').read_bytes())
    if folder.name.lower() not in {str(item.name).lower() for item in mounts}:
        raise ValueError('This overlay is no longer mounted. Refresh Installed overlays.')
    sources = None
    by_path = by_basename = None
    snapshot_current = (snapshot is not None and not snapshot.source_files_changed()
                        and Path(snapshot.iteminfo.payload_entry.pamt_path).resolve().parent.parent == root)
    catalogue = None
    if not snapshot_current and resident_source is not None:
        try:
            catalogue = resident_source.open(stop_event, package_root=root)
        except (OSError, ValueError):
            # A newly installed/changed overlay can invalidate the published
            # generation. Preserve the current mounted-source read below.
            pass
    if snapshot_current:
        # These are lazy shared lookups. Iterating entries.items() materializes
        # and ranks millions of unrelated archive records for every preview.
        entries = snapshot.entries
        sources = snapshot.sources
        by_path, by_basename = snapshot.archive_index_maps()
    elif catalogue is not None:
        from cdmw.core.item_sources import resolve_item_data_sources

        sources = resolve_item_data_sources(catalogue.item_metadata(), pamt_paths=(
            path for path in catalogue.source_paths if path.suffix.lower() == '.pamt'))
        entries = catalogue.selected_paths(sources)
        by_path, by_basename = catalogue.index_maps(sources)
        snapshot = None
    else:
        # Utilities can open before Create New Item has read anything. Rebuild
        # from the current mounted sources on this preview worker in that case.
        entries = {}
        for mount in mounts:
            raise_if_cancelled(stop_event)
            group = safe_archive_output_path(root, str(mount.name), single_component=True,
                                            error_message='A mounted archive is outside the game package.')
            for pamt in sorted(group.glob('*.pamt')):
                for entry in installed if pamt == folder / '0.pamt' else parse_archive_pamt(pamt):
                    entries.setdefault(entry.path.replace('\\', '/').strip('/').lower(), entry)
        snapshot = None
    installed_ids = {entry.identity for entry in installed}

    def read(entry):
        raise_if_cancelled(stop_event)
        if snapshot is None or entry.identity in installed_ids:
            return read_archive_entry_data(entry, stop_event=stop_event)[0]
        return snapshot.read_entry(entry)

    family, sources = _preview_family(entries, read, item_key, stop_event, sources=sources)
    if by_path is None:
        by_path, by_basename, accepted = {}, {}, {}
        for index, (path, entry) in enumerate(entries.items()):
            if index % 4096 == 0:
                raise_if_cancelled(stop_event)
            if entry.pamt_path not in accepted:
                accepted[entry.pamt_path] = sources.accepts(entry)
            if accepted[entry.pamt_path]:
                by_path[path] = (entry,)
                by_basename.setdefault(path.rsplit('/', 1)[-1], []).append(entry)
    models = []
    for component in family.files_for('pac'):
        raise_if_cancelled(stop_event)
        if not component.exists:
            continue
        result = build_archive_preview_result(
            entries[component.path.lower()],
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


def _preview_family(entries, read, item_key, stop_event, *, sources=None):
    """Decode only the selected row and its model references, not authoring tables."""
    from cdmw.core.item_sources import LEGACY_TABLE_ROOT, STATIC_TABLE_ROOT, resolve_item_data_sources
    from cdmw.core.iteminfo_row import parse_iteminfo_row
    from cdmw.core.item_model_family import discover_item_model_family
    from cdmw.core.pappt_format import parse_pappt
    from cdmw.core.stringinfo_table import parse_stringinfo, stringinfo_index
    from cdmw.core.structured_binary_editor import parse_pabgh_table
    from cdmw.services.new_item_snapshot import PAPPT_PATH, _table_pair

    if sources is None:
        metadata = [entries[path] for path in entries
                    if path.startswith((LEGACY_TABLE_ROOT + '/', STATIC_TABLE_ROOT + '/'))]
        sources = resolve_item_data_sources(metadata)
    pair = _table_pair(entries, read, 'iteminfo', sources=sources)
    spans = parse_pabgh_table(pair.header, payload=pair.payload).row_spans(len(pair.payload))
    keys = {row.row_id for row, _, _ in spans}
    selected = next(((start, end) for row, start, end in spans if row.row_id == int(item_key)), None)
    if selected is None:
        raise ValueError(f'Installed item {item_key} is missing from the currently mounted item table.')
    row = parse_iteminfo_row(pair.payload[selected[0]:selected[1]], item_keys=keys)
    raise_if_cancelled(stop_event)
    strings = _table_pair(entries, read, 'stringinfo', sources=sources)
    texts = stringinfo_index(parse_stringinfo(strings.payload, strings.header, name='stringinfo'))
    pappt = parse_pappt(read(entries[PAPPT_PATH]), name=PAPPT_PATH)
    family = discover_item_model_family(row, stringinfo=texts, pappt=pappt,
        read_entry=lambda path: read(entries[path.lower()]) if path.lower() in entries else None,
        path_exists=lambda path: path.lower() in entries)
    return family, sources
