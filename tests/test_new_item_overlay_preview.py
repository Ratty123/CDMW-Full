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


@pytest.mark.parametrize('owned_model', [False, True])
def test_preview_resolves_new_installed_key_with_stale_studio_snapshot_and_preserves_archives(tmp_path, monkeypatch, template_game, owned_model):
    service, snapshot, _, original = template_game
    root = tmp_path / 'game'
    choice = shop_spec('PreviewOnly')
    if owned_model:
        choice = replace(choice, template_transform=tuple(ModelPlacement(offset=(.1, 0, 0)).matrix()))
    plan = service.plan(choice, snapshot)
    service.install_overlay(plan, mutation_service=Backups(tmp_path), confirmed=True, game_running=lambda: False)
    entry = list_installed_overlays(root)[0]
    assert plan.spec.item_key not in snapshot.rows
    paths = [p for p in root.rglob('*') if p.is_file()]
    fingerprints = {p: hashlib.sha256(p.read_bytes()).digest() for p in paths}
    decoded = []

    def decode(component, **kwargs):
        decoded.append(component)
        assert kwargs['texture_entries_by_normalized_path'][component.path.lower()][0] is component
        return build_archive_preview_result(component, **kwargs)

    monkeypatch.setattr('cdmw.services.archive_preview_service.build_archive_preview_result', decode)
    models = overlay_item_preview_models(snapshot, root, entry.directory, plan.spec.item_key,
                                        stop_event=threading.Event())
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
