"""Standalone Builder model queue through the real worker and Rust host API."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from cdmw.core.archive_mesh_import_scene_preview import parsed_mesh_to_preview_model
from cdmw.services.mesh_rust_contract import RUST_MESH_RENDERER, RUST_PREVIEW_PACKAGE
from cdmw.services.mesh_rust_preview_package import validate_rust_preview_package
from cdmw.ui.archive_browser.static_replacement_dialog_callbacks_d3d11_package_lifecycle_part_01 import (
    _d3d11_package_lifecycle_step_042,
)
from cdmw.ui.preview.rust_session import RustPreviewSessionController
from tests.mesh_builder_driver import APPLICATION, open_mesh_builder
from tests.test_rust_preview_production_cutover import _triangle


def _wait_for(predicate) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        APPLICATION.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), 'Builder did not hand its prepared model to the Rust host'


def test_standalone_builder_queues_rust_packages_and_accepts_new_scene_ids(monkeypatch) -> None:
    # This check owns package preparation and handoff, not a GPU/window launch.
    monkeypatch.setattr(RustPreviewSessionController, '_launch_if_needed', lambda self: None)
    with open_mesh_builder() as builder:
        host = builder.control('alignment_d3d11_preview_host')
        controller = host.controller
        controller.set_visible(False)
        queue = builder.control('_queue_alignment_d3d11_preview')
        state = builder.control('alignment_d3d11_state')
        _wait_for(lambda: bool(builder.events_named('mesh_alignment_original_texture_preview_ready'))
                  and state.get('original_texture_thread') is None)
        failures = []
        controller.package_failed.connect(lambda *args: failures.append(args))
        first_path = ''
        for index in range(2):
            mesh = _triangle()
            mesh.submeshes[0].vertices[0] = (-0.5 - index, -0.5, 0.0)
            model = parsed_mesh_to_preview_model(mesh)
            assert queue(model, label=f'Owned preview {index}', reason='geometry')
            try:
                _wait_for(lambda: bool(controller.desired_package_path)
                          and controller.desired_package_path != first_path
                          and state.get('thread') is None)
            except AssertionError as exc:
                raise AssertionError((index, builder.control('alignment_d3d11_preview_status_label').text(),
                                      controller.desired_package_path, builder.runtime_events[-5:])) from exc
            assert not failures
            package = Path(controller.desired_package_path)
            assert validate_rust_preview_package(package) == ()
            manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
            assert manifest['schema'] == RUST_PREVIEW_PACKAGE
            assert manifest['renderer'] == RUST_MESH_RENDERER
            assert manifest['interaction_profile'] == 'static_replacement'
            assert state['active_package'] == package
            assert controller._session_id == manifest['session_id']
            # An established renderer must accept the next independently built
            # preview scene; an AUTHORING profile rejects that identity change.
            controller._session_established = True
            first_path = str(package)
        assert not queue(None)
        assert not builder.events_named('mesh_alignment_preview_refresh_failed')


def test_embedded_editor_keeps_its_authoring_queue_owner() -> None:
    events = []
    state = SimpleNamespace(
        context={'embedded_alignment_builder': True},
        _record_runtime_event=lambda *args, **fields: events.append(fields),
        entry=SimpleNamespace(path='owned.pac'), dialog_title='Embedded',
        modify_original_clone_mode=False,
    )
    _d3d11_package_lifecycle_step_042(state)
    assert not state._queue_alignment_d3d11_preview(object())
    assert events[0]['reason'] == 'dotnet_authoritative'


def test_closing_builder_does_not_queue_new_work() -> None:
    state = SimpleNamespace(context={}, _alignment_dialog_widgets_live=lambda: False)
    _d3d11_package_lifecycle_step_042(state)
    assert not state._queue_alignment_d3d11_preview(object())
