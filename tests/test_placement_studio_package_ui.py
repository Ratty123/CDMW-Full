"""Headless checks through the real Build packages action and confirmation dialogs."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from tests.test_placement_studio_loading import studio  # noqa: F401 - shared headless fixture
from tools.placement_studio import packaging


@pytest.fixture
def package_ui(studio, monkeypatch, tmp_path):
    studio._edits = Mock()
    studio._edits.modified_paths.return_value = ["character/test.xml"]
    monkeypatch.setattr(studio, '_select_package_operations', lambda: ['op'])
    monkeypatch.setattr(studio, '_packaged_units', lambda _: {})
    monkeypatch.setattr(studio, '_shared_socket_users', lambda: {})
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *_: str(tmp_path))
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('Review mod', True))
    verdict = SimpleNamespace(
        blocked=False, needs_confirmation=False,
        summary=SimpleNamespace(render=lambda: 'Selected operation'),
    )
    build = Mock(return_value=([], verdict))
    monkeypatch.setattr(packaging, 'build_for_operations', build)
    warning = Mock()
    monkeypatch.setattr(QMessageBox, 'warning', warning)
    monkeypatch.setattr(QMessageBox, 'exec', lambda _: QMessageBox.Yes)
    return studio, build, verdict, warning


def test_cancelled_replacement_never_starts_build(package_ui, monkeypatch, tmp_path):
    studio, build, _, _ = package_ui
    destination = tmp_path / 'Review mod - DMM'
    destination.mkdir()
    (destination / 'notes.txt').write_bytes(b'keep')
    question = Mock(return_value=QMessageBox.Cancel)
    monkeypatch.setattr(QMessageBox, 'question', question)
    studio._build_packages()
    build.assert_not_called()
    args = question.call_args.args
    assert str(destination) in args[2]
    assert 'entire contents' in args[2] and '.bak' in args[2]
    assert args[-1] == QMessageBox.Cancel
    assert (destination / 'notes.txt').read_bytes() == b'keep'


def test_confirmed_replacement_is_preserved_through_scope_confirmation(package_ui, monkeypatch, tmp_path):
    studio, build, verdict, warning = package_ui
    (tmp_path / 'Review mod - DMM').mkdir()
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.Yes)
    verdict.needs_confirmation = True
    verdict.warnings = [SimpleNamespace(describe=lambda: 'Shared socket warning')]
    verdict.render = lambda: 'Selected scope'
    studio._build_packages()
    assert build.call_count == 2
    assert all(call.kwargs['replace_existing'] for call in build.call_args_list)
    assert build.call_args.kwargs['accept_warnings'] is True
    warning.assert_not_called()


def test_new_output_does_not_authorize_replacing_a_later_collision(package_ui, monkeypatch):
    studio, build, _, _ = package_ui
    question = Mock()
    monkeypatch.setattr(QMessageBox, 'question', question)
    studio._build_packages()
    question.assert_not_called()
    assert build.call_args.kwargs['replace_existing'] is False


def test_invalid_name_is_reported_without_starting_build(package_ui, monkeypatch):
    studio, build, _, warning = package_ui
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('../Outside/Mod', True))
    studio._build_packages()
    build.assert_not_called()
    assert 'folder name' in warning.call_args.args[-1]


def test_destination_failure_after_scope_confirmation_is_reported(package_ui):
    studio, build, verdict, warning = package_ui
    verdict.needs_confirmation = True
    verdict.warnings = [SimpleNamespace(describe=lambda: 'Shared socket warning')]
    verdict.render = lambda: 'Selected scope'
    build.side_effect = [([], verdict), packaging.PackagingError('Destination already exists')]
    studio._build_packages()
    assert warning.call_args.args[-1] == 'Destination already exists'
