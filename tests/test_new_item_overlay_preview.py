"""Installed preview resolution reads the actual overlay, without writing it."""
import hashlib
import threading
from dataclasses import replace

import numpy as np
import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.archive_overlay_manager import list_installed_overlays
from cdmw.services.new_item_overlay_preview import overlay_item_preview_models
from cdmw.services.archive_preview_service import build_archive_preview_result
from cdmw.ui.new_item.item_preview_materials import as_parsed_mesh
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_new_item_template_authoring import template_game
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_resident_index import ResidentArchiveIndex
from tests.archive_resident_index_fixtures import write_resident_index


@pytest.mark.parametrize('owned_model', [False, True])
@pytest.mark.parametrize('snapshot_loaded', [False, True])
def test_preview_resolves_new_installed_key_with_stale_studio_snapshot_and_preserves_archives(tmp_path, monkeypatch, template_game, owned_model, snapshot_loaded):
    service, snapshot, _, original = template_game
    root = tmp_path / 'game'
    stale_source = write_resident_index(root, tuple(snapshot.entries.values()), tmp_path / 'old-generation')
    stale_source.open()
    choice = shop_spec('PreviewOnly')
    if owned_model:
        choice = replace(choice, template_transform=tuple(ModelPlacement(offset=(.1, 0, 0)).matrix()))
    plan = service.plan(choice, snapshot)
    service.install_overlay(plan, mutation_service=Backups(tmp_path), confirmed=True, game_running=lambda: False)
    entry = list_installed_overlays(root)[0]
    assert plan.spec.item_key not in snapshot.rows
    # Neither unmounted groups nor nested recovery copies are preview sources.
    for relative in ('9999/0.pamt', 'backups/0009/0.pamt'):
        inactive = root / relative
        inactive.parent.mkdir(parents=True, exist_ok=True)
        inactive.write_bytes(b'not an active archive index')
    paths = [p for p in root.rglob('*') if p.is_file()]
    fingerprints = {p: hashlib.sha256(p.read_bytes()).digest() for p in paths}
    decoded = []

    def decode(component, **kwargs):
        decoded.append(component)
        assert kwargs['texture_entries_by_normalized_path'][component.path.lower()][0] == component
        return build_archive_preview_result(component, **kwargs)

    monkeypatch.setattr('cdmw.services.archive_preview_service.build_archive_preview_result', decode)
    models = overlay_item_preview_models(snapshot if snapshot_loaded else None, root, entry.directory, plan.spec.item_key,
                                        stop_event=threading.Event(), resident_source=stale_source)
    mesh = as_parsed_mesh(models[0])
    expected = np.asarray(original.submeshes[0].vertices) + ((.1, 0, 0) if owned_model else (0, 0, 0))
    np.testing.assert_allclose(mesh.submeshes[0].vertices, expected, atol=2e-4)
    assert decoded
    assert all((entry.directory in str(component.pamt_path)) == owned_model for component in decoded)
    assert {p: hashlib.sha256(p.read_bytes()).digest() for p in paths} == fingerprints
    assert plan.spec.item_key not in snapshot.rows
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(RunCancelled):
        overlay_item_preview_models(snapshot, root, entry.directory, plan.spec.item_key, stop_event=stopped)


@pytest.mark.parametrize('snapshot_loaded', [False, True])
def test_preview_reuses_current_catalogue_without_materializing_unrelated_entries(
        tmp_path, monkeypatch, template_game, snapshot_loaded):
    service, before_install, _, original = template_game
    root = tmp_path / 'game'
    plan = service.plan(shop_spec('BoundedPreview'), before_install)
    service.install_overlay(plan, mutation_service=Backups(tmp_path), confirmed=True, game_running=lambda: False)
    overlay = list_installed_overlays(root)[0]
    entries = [entry for pamt in root.glob('*/*.pamt') for entry in parse_archive_pamt(pamt)]
    entries.extend(replace(entries[0], path=f'unrelated/texture_{i}.dds') for i in range(10000))
    source = write_resident_index(root, entries, tmp_path / 'generation')
    index = source.open()
    snapshot = service.build_snapshot((), resident_catalogue=index) if snapshot_loaded else None
    materialized = []
    get_entry = ResidentArchiveIndex.__getitem__

    def tracked(index, row):
        entry = get_entry(index, row)
        materialized.append(entry.path)
        assert not entry.path.startswith('unrelated/'), 'preview decoded an unrelated archive record'
        return entry

    monkeypatch.setattr(ResidentArchiveIndex, '__getitem__', tracked)
    monkeypatch.setattr('cdmw.core.archive_format.parse_archive_pamt',
                        lambda path: tuple(entry for entry in entries if entry.pamt_path == path)
                        if path == root / overlay.directory / '0.pamt'
                        else pytest.fail('preview reparsed an underlay archive'))
    models = overlay_item_preview_models(snapshot, root, overlay.directory, plan.spec.item_key,
                                        resident_source=source, stop_event=threading.Event())
    np.testing.assert_allclose(as_parsed_mesh(models[0]).submeshes[0].vertices,
                               original.submeshes[0].vertices, atol=2e-4)
    assert len(materialized) < 200
