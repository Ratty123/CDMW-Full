"""Build Mod is the user's call when the exact Material Authority preview is unconfirmed.

The resolved state can sit unconfirmed for reasons the Builder cannot resolve
from its own controls: a resolver that failed, a resident compile the original
PAC refuses, a preview that never acknowledged. Refusing the build there, or
greying the button out with the reason in a tooltip, left the user reading
about a setting they could not reach. The build now asks and proceeds on the
profile route when told to.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from cdmw.domain.textures.material_authority_state import (
    MaterialAuthoritySyncStatus,
    resolved_material_authority_state,
)
from cdmw.ui.archive_browser.static_replacement_dialog_callback_factories import (
    create_alignment_accept_build_callbacks,
)


_REASON = "The .NET preview did not acknowledge the latest resolved artifacts."


class _ProceededPastThePrompt(Exception):
    """Raised by the first hook after the gate, so a build that continues is observable."""


class _MessageBox:
    StandardButton = QMessageBox.StandardButton
    answer = QMessageBox.StandardButton.No
    questions: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []

    @classmethod
    def question(cls, _dialog, title, message, _buttons, _default):
        cls.questions.append((title, message))
        return cls.answer

    @classmethod
    def warning(cls, _dialog, title, message):
        cls.warnings.append((title, message))


def _options_builder(message_box: type[_MessageBox]):
    def _raise_proceeded() -> None:
        raise _ProceededPastThePrompt

    dialog = SimpleNamespace(
        _material_authority_resolved_state=None,
        _material_authority_sync_status=MaterialAuthoritySyncStatus.BLOCKED.value,
        _material_authority_sync_reason=_REASON,
        _mesh_editor_embedded_dotnet_active=True,
    )
    callbacks = create_alignment_accept_build_callbacks(
        {
            "QMessageBox": message_box,
            "dialog": dialog,
            "modify_original_clone_mode": False,
            "_complete_external_swap_enabled": lambda: True,
            "_mapping_table_build_complete_helper": lambda _state: True,
            "_commit_spinbox_text": lambda _spin, block_signals=False: None,
            "_update_selected_part_adjustment": lambda **_kwargs: None,
            "_save_texture_transform_controls": lambda **_kwargs: None,
            "_copied_source_texture_slot_overrides": lambda _mappings, occupied_keys=(): [],
            "_flush_source_role_overrides_for_export": _raise_proceeded,
            "texture_override_rows": [],
            "custom_icon_checkbox": SimpleNamespace(isChecked=lambda: False),
        }
    )
    return callbacks._build_static_options_from_dialog


def test_unconfirmed_material_authority_asks_and_no_cancels_the_build() -> None:
    _MessageBox.questions = []
    _MessageBox.warnings = []
    _MessageBox.answer = QMessageBox.StandardButton.No
    build_options = _options_builder(_MessageBox)

    assert build_options(show_messages=True) is None

    assert _MessageBox.warnings == []
    assert len(_MessageBox.questions) == 1
    title, message = _MessageBox.questions[0]
    assert title == "Build Mod"
    assert message.startswith(
        "The resident preview has not confirmed the exact Material Authority result:\n"
        f"{_REASON}\n\nBuild anyway?"
    )
    assert "may not match the viewport" in message
    assert "blocked" not in message.casefold()


def test_unconfirmed_material_authority_yes_lets_the_build_continue() -> None:
    _MessageBox.questions = []
    _MessageBox.answer = QMessageBox.StandardButton.Yes
    build_options = _options_builder(_MessageBox)

    with pytest.raises(_ProceededPastThePrompt):
        build_options(show_messages=True)

    assert len(_MessageBox.questions) == 1


def test_build_button_stays_clickable_after_the_preview_declines_the_state() -> None:
    from tests.mesh_builder_driver import open_mesh_builder

    pending = resolved_material_authority_state(
        profile_token="manual",
        revision=3,
        affected_submeshes=(0,),
        dds_bindings=(
            {"resource_id": "base:0", "channel": "base", "content_sha256": "a" * 64},
        ),
        residual_parameter_groups=(),
        control_states=(),
        status=MaterialAuthoritySyncStatus.FAST_PREVIEW,
    )
    with open_mesh_builder(dialog_title="Build Mod unconfirmed preview") as builder:
        dialog = builder.dialog
        build_button = getattr(dialog, "_material_authority_build_button")
        finished = getattr(dialog, "_mesh_editor_embedded_material_resources_finished")
        setattr(dialog, "_material_authority_pending_resolved_state", pending)

        finished(7, False, pending.dds_bindings, pending.fingerprint, pending.revision)
        builder.pump()

        assert getattr(dialog, "_material_authority_sync_status") == "blocked"
        assert build_button.isEnabled()
        assert "did not acknowledge" in build_button.toolTip()
