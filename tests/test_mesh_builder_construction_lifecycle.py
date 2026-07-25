from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QProgressDialog, QWidget

from cdmw.ui.archive_browser.mesh_builder_lifecycle import ArchiveMeshBuilderLifecycleMixin
from cdmw.ui.archive_browser import static_replacement_dialog_prompt as prompt_owner


_APPLICATION = QApplication.instance() or QApplication([])


class _BuilderOwner(ArchiveMeshBuilderLifecycleMixin, QWidget):
    def __init__(self) -> None:
        QWidget.__init__(self)
        self._modeless_alignment_dialogs: dict[str, QDialog] = {}
        self.archive_preview_refresh_deferred_by_builder = False
        self._shutting_down = False
        self.status_messages: list[tuple[str, bool]] = []
        self.runtime_events: list[tuple[str, dict[str, object]]] = []

    def _modeless_alignment_dialog_key(self, *_args: object) -> str:
        return "builder-key"

    def _activate_modeless_alignment_dialog(self, _key: str) -> bool:
        return False

    def _unregister_modeless_alignment_dialog(self, key: str, dialog: QDialog) -> None:
        if self._modeless_alignment_dialogs.get(key) is dialog:
            self._modeless_alignment_dialogs.pop(key, None)

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.status_messages.append((message, error))

    def _record_runtime_event(self, event: str, **fields: object) -> None:
        self.runtime_events.append((event, fields))


@pytest.mark.parametrize("modify_original_clone_mode", (False, True))
def test_import_and_modify_builder_shell_failure_disposes_overlay_and_dialog(
    monkeypatch: pytest.MonkeyPatch,
    modify_original_clone_mode: bool,
) -> None:
    owner = _BuilderOwner()
    created: dict[str, QWidget] = {}

    def fail_after_creating_shell(context: dict[str, object]) -> object:
        progress = QProgressDialog("Preparing", "", 0, 0, owner)
        progress.show()
        dialog = QDialog(owner)
        dialog.setObjectName("MeshReplacementAlignmentDialog")
        dialog.show()
        setattr(dialog, "_cdmw_builder_startup_progress", progress)
        setattr(dialog, "_cdmw_builder_construction_context", context)
        owner._modeless_alignment_dialogs["builder-key"] = dialog
        created.update(progress=progress, dialog=dialog)
        raise RuntimeError("injected builder construction failure")

    monkeypatch.setattr(prompt_owner, "create_static_replacement_prompt_shell", fail_after_creating_shell)
    prompt_owner.prompt_archive_static_replacement_options(
        owner,
        SimpleNamespace(path="character/model/test.pac", basename="test.pac"),
        Path("replacement.obj"),
        dialog_title="Modify Original" if modify_original_clone_mode else "Import Mesh",
        _prepared_prompt_preflight=SimpleNamespace(
            scene_import_result=None,
            original_mesh=None,
            modify_original_clone_mode=modify_original_clone_mode,
        ),
    )

    assert owner._modeless_alignment_dialogs == {}
    assert not created["progress"].isVisible()
    assert not created["dialog"].isVisible()
    assert owner.status_messages[-1] == (
        "Mesh Replacement Builder setup failed: injected builder construction failure",
        True,
    )
    assert owner.runtime_events[-1][0] == "mesh_alignment_construction_failed"
    assert owner.runtime_events[-1][1]["stage"] == "prompt_shell"
    owner.deleteLater()


# Parenting order is now covered at runtime, across both entry modes and every
# constructed widget rather than five named ones, by
# tests/test_mesh_builder_construction_invariants.py.


def test_partial_builder_disposer_is_idempotent_and_orders_worker_cleanup() -> None:
    calls: list[str] = []
    owner = _BuilderOwner()
    dialog = QDialog(owner)
    owner._modeless_alignment_dialogs["builder-key"] = dialog
    timer = SimpleNamespace(stop=lambda: calls.append("stop_timer"))
    context = {
        "material_edit_refresh_timer": timer,
        "_stop_original_reference_texture_worker": lambda: calls.append("stop_texture"),
        "_alignment_d3d11_stop_worker": lambda: calls.append("stop_package_worker"),
        "_safe_shutdown_alignment_d3d11_preview": lambda: calls.append("stop_renderer"),
        "_finish_alignment_startup_progress": lambda: calls.append("finish_progress"),
    }

    assert owner._dispose_partial_alignment_builder("builder-key", dialog, context=context)
    assert not owner._dispose_partial_alignment_builder("builder-key", dialog, context=context)
    assert calls == [
        "stop_timer",
        "stop_texture",
        "stop_package_worker",
        "stop_renderer",
        "finish_progress",
    ]
    assert owner._modeless_alignment_dialogs == {}
    owner.deleteLater()
