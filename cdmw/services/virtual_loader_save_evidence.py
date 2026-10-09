"""Read-only virtual-profile/save-copy captures, with separate new report output."""
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import tempfile
from uuid import uuid4

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import package_id
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.domain.virtual_save_evidence import (
    CLAIMS, FORMAT, MAX_RECORD, OUTCOMES, STAGES, checksum, decode, encoded, seal, validate,
)
from cdmw.services.virtual_loader_composition import hash_file
from cdmw.services.virtual_loader_saves import _plain, _records
from cdmw.services.virtual_loader_state import target


def read_capture(path):
    path = Path(path)
    _plain(path)
    with path.open('rb') as reader:
        return decode(reader.read(MAX_RECORD + 1))


def inspect_capture_lineage(value):
    """Inspect recorded copies only; capture links are not save ancestry."""
    from dataclasses import asdict
    from cdmw.domain.virtual_save_lineage import SaveSetSnapshot, assess_lineage

    value = validate(value)
    selected = {name: dict(value['files'][name]) for name in value['selected'] if name in value['files']}
    snapshot = SaveSetSnapshot(tuple((name, row['size'], row['sha256']) for name, row in selected.items()))
    # A current profile, operator outcome or capture parent cannot mint a commit
    # witness, slot-layout adapter, complete requirements or producing context.
    decision = assess_lineage(snapshot, target=None)
    return {'format': 'cdmw_virtual_save_lineage_inspection_v1', 'capture_identity': value['identity'],
            'observed_file_set': {'sha256': snapshot.identity, 'files': selected,
                                  'missing_selected_files': sorted(set(value['selected']) - set(selected)),
                                  'slot_layout_sha256': None, 'membership_complete': False},
            'producer_witness': None, 'parent_save_set_sha256': None,
            'requirements_coverage': 'unknown', 'decision': asdict(decision), 'claims': dict(CLAIMS)}


def _context(root, provider, stop_event):
    from cdmw.services.archive_overlay_manager import _load_index
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.virtual_loader_runtime import _snapshot_preflight
    # This is evidence of the prepared selection, never launch authority. The
    # native host's full source verification and activation are separate gates.
    profile = _snapshot_preflight(root, stop_event=stop_event)
    registry = load_registry(root)
    def file_hash(relative, required=False):
        path = target(root, relative)
        if not path.exists() and not required:
            return None
        if not stat.S_ISREG(_plain(path).st_mode):
            raise VirtualLoaderError('A captured runtime file is not a regular file.')
        return hash_file(path, stop_event)
    binding = registry['items'].get(provider)
    layers = (_load_index(root) or {}).get('layers', ())
    physical = {row['independent_identity']: {'digest': row['independent_digest'],
                'binding_hash': row['independent_bindings']}
                for row in layers if row['active'] and row.get('independent_identity')}
    return {'profile_sha256': checksum(encoded(profile)), 'generation': profile['generation'],
            'executable_sha256': file_hash('bin64/CrimsonDesert.exe', required=True),
            'runtime': {'bootstrap': file_hash('bin64/winmm.dll'), 'loader': file_hash('bin64/CDMWVirtualLoader.asi')},
            'compiler_sha256': checksum(encoded(profile['compiler'])),
            'compilation_identity': profile['compilation']['identity'],
            'items': profile['items'], 'physical_items': physical, 'outputs': profile['files'],
            'provider_binding': {key: binding[key] for key in ('binding_hash', 'values')} if binding else None,
            'sources_sha256': checksum(encoded(profile['sources'])),
            'underlay_sha256': checksum(encoded(profile['observed']))}


def _paths(root, save_copy, output):
    root, save_copy, output = (Path(p).absolute() for p in (root, save_copy, output))
    for path in (root, save_copy, output.parent):
        for part in (path, *path.parents):
            _plain(part)
        if not path.is_dir():
            raise VirtualLoaderError('Capture inputs and the output parent must be existing directories.')
    root, save_copy, output = root.resolve(), save_copy.resolve(), target(output.parent.resolve(), output.name)
    if (output.is_relative_to(root) or output.is_relative_to(save_copy)
            or save_copy.is_relative_to(root) or root.is_relative_to(save_copy)):
        raise VirtualLoaderError('Use a separate save copy and put the report outside both input folders.')
    if output.exists() or output.is_symlink():
        raise VirtualLoaderError('Choose a new capture path; existing reports are never replaced.')
    return root, save_copy, output


def _publish(path, value, stop_event):
    # An exclusive hard link publishes complete bytes without replacing a file
    # created by someone else after review. Unsupported filesystems fail closed.
    descriptor, name = tempfile.mkstemp(prefix='.cdmw-save-evidence-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as writer:
            writer.write(encoded(value))
            writer.flush()
            os.fsync(writer.fileno())
        raise_if_cancelled(stop_event)
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def capture(root, save_copy, output, *, stage, outcome, notes, provider=None,
            slots=(), previous=None, stop_event=None):
    """Read explicitly named input copies. Never launches, restores or edits saves."""
    from cdmw.services.new_item_service import game_is_running
    root, save_copy, output = _paths(root, save_copy, output)
    if game_is_running():
        raise VirtualLoaderError('Close the game before capturing a save experiment.')
    parent = read_capture(previous) if previous is not None else None
    if stage not in STAGES or (parent is None and stage != 'baseline') or (parent is not None
            and (STAGES.index(parent['stage']) + 1 >= len(STAGES)
                 or stage != STAGES[STAGES.index(parent['stage']) + 1])):
        raise VirtualLoaderError('Capture each experiment stage in order, starting at baseline.')
    if parent is not None:
        if provider is not None and provider != parent['provider']:
            raise VirtualLoaderError('The experiment provider changed.')
        provider = parent['provider']
    package_id(provider)
    if (outcome not in OUTCOMES[stage] or not isinstance(notes, str)
            or not 1 <= len(notes) <= 4096 or '\0' in notes or len(slots) > 32):
        raise VirtualLoaderError('Choose an outcome for this stage, bounded notes and at most 32 save files.')
    # Checking the paths prevents alternate spellings from masking a different
    # selection; hashed relative names omit account/slot names from the report.
    selected = sorted(checksum(target(save_copy, name).relative_to(save_copy).as_posix().encode()) for name in slots)
    if parent is not None:
        if selected and selected != parent['selected']:
            raise VirtualLoaderError('The selected save files changed between experiment stages.')
        selected = parent['selected']
    if not selected or len(set(selected)) != len(selected):
        raise VirtualLoaderError('Select one or more distinct save files for the baseline.')
    raise_if_cancelled(stop_event)
    before = _context(root, provider, stop_event)
    files = _records(save_copy, stop_event)
    if _records(save_copy, stop_event) != files or _context(root, provider, stop_event) != before:
        raise VirtualLoaderError('The save copy or prepared context changed during capture. Try again with stable inputs.')
    if game_is_running():
        raise VirtualLoaderError('Close the game before capturing a save experiment.')
    value = seal({'format': FORMAT, 'experiment': parent['experiment'] if parent else uuid4().hex,
        'parent': parent['identity'] if parent else None, 'stage': stage, 'provider': provider,
        'captured_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'context': before, 'files': {checksum(name.encode()): row for name, row in files.items()},
        'selected': selected, 'observation': {'outcome': outcome, 'notes': notes}, 'claims': dict(CLAIMS)})
    validate(value)
    if parent is None and (provider not in before['items'] or any(key not in value['files'] for key in selected)):
        raise VirtualLoaderError('The baseline must select the virtual provider and existing save files.')
    _publish(output, value, stop_event)
    return value
