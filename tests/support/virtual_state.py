"""Retired install code from cdmw.services.virtual_loader_state, kept for tests only (decision 39)."""

# CDMW never installs into the game. Tests use this on owned game folders made in the
# test, to build the state the live code reads. Names the app still has are read from
# cdmw.services.virtual_loader_state at call time (``_live``), so patching them there reaches this code.

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.compilation import validate_compiler_stamp, validate_compilation
from tests.support.virtual_domain import VirtualLoaderError
from cdmw.services.application_shutdown_service import archive_write_scope
from cdmw.services.independent_item_package import canonical, digest, MAX_MANIFEST, package_id
from cdmw.services.installation_lane import installation_lane

import cdmw.services.virtual_loader_state as _live


def __getattr__(name):
    return getattr(_live, name)


REGISTRY = '.cdmw/independent-items.json'


def _write_optional(path, data):
    if data is None:
        path.unlink(missing_ok=True)
    else:
        atomic_write_bytes(path, data)


def _journal_value(before, after):
    value = {'format': 'cdmw_virtual_transaction_v1', 'before': before, 'after': after}
    return canonical({'data': value, 'sha256': digest(canonical(value))})


def _verify_recovered_state(root, expected):
    """Verify both selected ledgers and the complete referenced generation."""
    from cdmw.services.independent_item_install import _validate_registry
    from tests.support.virtual_composition import hash_file
    actual = {p: _live.read_optional(_live.target(root, p)) for p in expected}
    if actual != expected:
        raise VirtualLoaderError('Virtual recovery did not establish the selected ledger bytes.')
    registry = _validate_registry(_live.decode(actual[REGISTRY])) if actual[REGISTRY] is not None else None
    if actual[_live.PROFILE_PATH] is not None:
        profile = _live.validate_profile(_live.decode(actual[_live.PROFILE_PATH]))
        if registry is None:
            raise VirtualLoaderError('Virtual recovery is missing the matching identity ledger.')
        for identity, binding in profile['items'].items():
            row = registry['items'].get(identity)
            if not row or row['layer'] is not None or any((row[key] != binding[key] for key in binding)):
                raise VirtualLoaderError('Virtual recovery ownership and identity ledgers disagree.')
        if 'links' in profile.get('compilation', {}).get('inputs', {}):
            from cdmw.domain.new_item.package_links import validate_link_bindings
            validate_link_bindings(profile['compilation']['inputs']['links'], registry['items'])
        directory = _live.generation_path(root, profile['generation'])
        if _live.read_optional(_live.target(directory, 'profile.json')) != actual[_live.PROFILE_PATH]:
            raise VirtualLoaderError('Virtual recovery does not match its retained generation manifest.')
        for relative, checksum in profile['files'].items():
            if hash_file(_live.target(directory, 'files/' + relative)) != checksum:
                raise VirtualLoaderError('Virtual recovery found a changed generation file.')
    if {p: _live.read_optional(_live.target(root, p)) for p in expected} != expected:
        raise VirtualLoaderError('Virtual recovery ledgers changed during verification.')


@archive_write_scope()
def recover_profile(root):
    with installation_lane(root, recovery=True):
        journal = _live.target(root, _live.JOURNAL_PATH)
        journal_data = journal.read_bytes()
        wrapper = _live.decode(journal_data, limit=MAX_MANIFEST * 8)
        value = wrapper.get('data', {})
        if wrapper.get('sha256') != digest(canonical(value)) or value.get('format') != 'cdmw_virtual_transaction_v1':
            raise VirtualLoaderError('Virtual recovery material failed validation.')
        if set(value) != {'format', 'before', 'after'} or any((set(value[key]) != {REGISTRY, _live.PROFILE_PATH} for key in ('before', 'after'))):
            raise VirtualLoaderError('Invalid virtual recovery targets.')
        from cdmw.services.independent_item_install import _validate_registry
        for side in ('before', 'after'):
            for relative, text in value[side].items():
                if text is not None:
                    obj = _live.decode(text.encode())
                    (_validate_registry if relative == REGISTRY else _live.validate_profile)(obj)
        encoded = {side: {p: text.encode() if text is not None else None for p, text in value[side].items()} for side in ('before', 'after')}
        actual = {p: _live.read_optional(_live.target(root, p)) for p in encoded['before']}
        if any((actual[p] not in (encoded['before'][p], encoded['after'][p]) for p in actual)):
            raise VirtualLoaderError('An interrupted profile was changed externally; automatic recovery is refused.')
        selected = 'after' if actual == encoded['after'] else 'before'
        for relative, data in encoded[selected].items():
            if _live.read_optional(_live.target(root, relative)) != data:
                _write_optional(_live.target(root, relative), data)
        _verify_recovered_state(root, encoded[selected])
        archive = _live.target(root, '.cdmw/virtual-loader/recovery/' + digest(journal_data) + '.json')
        atomic_write_bytes(archive, journal_data)
        if archive.read_bytes() != journal_data or journal.read_bytes() != journal_data:
            raise VirtualLoaderError('Virtual recovery journal preservation failed verification.')
        _verify_recovered_state(root, encoded[selected])
        journal.unlink()
        return selected


@archive_write_scope()
def publish_profile(prepared, *, stop_event=None, on_log=None):
    from cdmw.services.independent_item_install import _validate_registry
    from cdmw.services.archive_overlay_manager import _verify_observed_state
    from cdmw.services.new_item_service import game_is_running
    root = prepared.root
    with installation_lane(root):
        if game_is_running():
            raise VirtualLoaderError('Close Crimson Desert before publishing a virtual profile.')
        prepared.source_revision.validate(stop_event)
        prepared.external.validate(stop_event)
        _verify_observed_state(root, prepared.observed, 'after virtual preparation')
        profile = _live.validate_profile(_live.decode(prepared.profile))
        registry = _validate_registry(_live.decode(prepared.registry))
        if 'links' in profile.get('compilation', {}).get('inputs', {}):
            from cdmw.domain.new_item.package_links import validate_link_bindings
            validate_link_bindings(profile['compilation']['inputs']['links'], registry['items'])
        if prepared.generation != profile['generation'] or len(prepared.files) != len(dict(prepared.files)):
            raise VirtualLoaderError('Prepared generation or file identities disagree.')
        for identity, binding in profile['items'].items():
            row = registry['items'].get(identity)
            if not row or row['layer'] is not None or any((row[key] != binding[key] for key in binding)):
                raise VirtualLoaderError('Prepared ownership does not match its identity reservations.')
        if set(profile['files']) != set(dict(prepared.files)) or any((digest(data) != profile['files'][p] for p, data in prepared.files)):
            raise VirtualLoaderError('Prepared virtual files failed validation.')
        directory = _live.generation_path(root, prepared.generation)
        if directory.exists():
            raise VirtualLoaderError('The prepared generation already exists; prepare a fresh profile.')
        directory.mkdir(parents=True)
        for relative, data in prepared.files:
            raise_if_cancelled(stop_event)
            atomic_write_bytes(_live.target(directory, 'files/' + relative), data)
            from tests.support.virtual_composition import hash_file
            if hash_file(_live.target(directory, 'files/' + relative), stop_event) != profile['files'][relative]:
                raise VirtualLoaderError('A staged snapshot file failed readback.')
        for name, data in prepared.retained_packages:
            if not re.fullmatch('[0-9a-f]{32}-[0-9a-f]{64}\\.cditem', name):
                raise VirtualLoaderError('Invalid retained virtual package name.')
            raise_if_cancelled(stop_event)
            atomic_write_bytes(_live.target(directory, 'packages/' + name), data)
        atomic_write_bytes(directory / 'profile.json', prepared.profile)
        prepared.source_revision.validate(stop_event)
        prepared.external.validate(stop_event)
        _verify_observed_state(root, prepared.observed, 'before virtual publication')
        raise_if_cancelled(stop_event)
        after = {REGISTRY: prepared.registry.decode(), _live.PROFILE_PATH: prepared.profile.decode()}
        before = {p: data.decode() if data is not None else None for p in after for data in (_live.read_optional(_live.target(root, p)),)}
        recovery_data = _journal_value(before, after)
        backup = _live.target(root, '.cdmw/virtual-loader/recovery/' + prepared.generation + '.json')
        atomic_write_bytes(backup, recovery_data)
        if backup.read_bytes() != recovery_data:
            raise VirtualLoaderError('Virtual recovery material failed readback.')
        atomic_write_bytes(_live.target(root, _live.JOURNAL_PATH), recovery_data)
        try:
            for relative, data in after.items():
                atomic_write_bytes(_live.target(root, relative), data.encode())
            _live.target(root, _live.JOURNAL_PATH).unlink()
        except Exception as publication_error:
            cleanup_error = None
            encoded = {side: {p: text.encode() if text is not None else None for p, text in values.items()} for side, values in (('before', before), ('after', after))}
            try:
                try:
                    selected = recover_profile(root)
                except OSError as error:
                    if _live.target(root, _live.JOURNAL_PATH).exists() or _live.read_optional(backup) != recovery_data:
                        raise
                    actual = {p: _live.read_optional(_live.target(root, p)) for p in after}
                    selected = next((side for side in ('after', 'before') if actual == encoded[side]), None)
                    cleanup_error = error
                if selected not in ('before', 'after'):
                    raise VirtualLoaderError('Virtual recovery did not select a verified state.')
                _verify_recovered_state(root, encoded[selected])
                if _live.target(root, _live.JOURNAL_PATH).exists():
                    raise VirtualLoaderError('Virtual recovery still has an active transaction journal.')
                if cleanup_error is not None and _live.read_optional(backup) != recovery_data:
                    raise VirtualLoaderError('Retained virtual recovery evidence changed during verification.')
            except Exception as recovery_error:
                raise VirtualLoaderError(f'Virtual profile recovery is required. Publication: {publication_error}. Recovery: {recovery_error}. Recovery material: {backup}') from recovery_error
            if selected == 'before':
                if cleanup_error is not None:
                    logging.getLogger(__name__).warning('Virtual profile restored and verified after journal cleanup reported: %s', cleanup_error)
                raise
            diagnostic = f'Virtual profile committed after verified recovery: {publication_error}'
            if cleanup_error is not None:
                diagnostic += f'. Journal cleanup: {cleanup_error}'
            logging.getLogger(__name__).warning(diagnostic)
            if on_log is not None:
                try:
                    on_log(diagnostic)
                except Exception:
                    logging.getLogger(__name__).exception('Committed profile diagnostic delivery failed.')
        return profile


# A test that patches a name the app still has (``monkeypatch.setattr(this_module,
# "resolve_items", ...)``) means the live function: the code above reads it from
# ``_live`` at call time, so the patch is forwarded there. pytest undoes a patch of
# a name it did not find in this module's own namespace by deleting it; that puts
# the live module's original value back.
_LIVE_ORIGINALS = {}


class _ForwardLiveNames(type(_live)):
    def __setattr__(self, name, value):
        shared = name in self.__dict__ and hasattr(_live, name) and self.__dict__[name] is getattr(_live, name)
        if shared or (name not in self.__dict__ and hasattr(_live, name)):
            # Also a name both modules import from the same place: patch both bindings.
            _LIVE_ORIGINALS.setdefault(name, getattr(_live, name))
            setattr(_live, name, value)
            if not shared:
                return
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name not in self.__dict__ and hasattr(_live, name):
            if name in _LIVE_ORIGINALS:  # a second undo of the same name has nothing left to restore
                setattr(_live, name, _LIVE_ORIGINALS.pop(name))
        else:
            super().__delattr__(name)


import sys as _sys  # noqa: E402

_sys.modules[__name__].__class__ = _ForwardLiveNames
