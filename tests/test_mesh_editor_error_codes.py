"""The stable half of a Mesh Editor failure.

Messages are localized, reworded, and written for the reader. These codes are
what a diagnostic bundle, a support ticket, and a regression test key on, so the
contract they have to keep is that the values do not drift and every one of them
says what a reader could do about it.
"""

from __future__ import annotations

import pytest

from cdmw.services.mesh_editor_error_codes import (
    RECOVERY_ACTION_BY_CODE,
    MeshEditorErrorCode,
    error_payload,
    recovery_action_for,
)


def test_every_code_has_a_recovery_action() -> None:
    missing = [code.name for code in MeshEditorErrorCode if code not in RECOVERY_ACTION_BY_CODE]
    assert missing == []


def test_code_values_match_their_names() -> None:
    # The value is the wire format. Keeping it identical to the member name is
    # what stops a rename from silently changing what a bundle reports.
    mismatched = [code.name for code in MeshEditorErrorCode if code.value != code.name]
    assert mismatched == []


def test_recovery_actions_come_from_a_closed_set() -> None:
    allowed = {
        "none",
        "reresolve_imported_textures",
        "restart_resident_renderer",
        "retry_build",
        "retry_material_role",
        "reselect",
        "return_to_pre_edit_candidate",
        "wait_for_pending_commands",
    }
    assert set(RECOVERY_ACTION_BY_CODE.values()) <= allowed


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (MeshEditorErrorCode.MAT_COMPILE_FAILED, "retry_material_role"),
        ("MAT_COMPILE_FAILED", "retry_material_role"),
        ("MAT_PUBLICATION_STALE", "none"),
        ("NOT_A_CODE", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
        (17, "unknown"),
    ],
)
def test_recovery_action_resolves_codes_and_refuses_anything_else(
    value: object,
    expected: str,
) -> None:
    assert recovery_action_for(value) == expected


def test_error_payload_carries_code_hint_and_detail() -> None:
    payload = error_payload(MeshEditorErrorCode.MAT_ROLE_ACK_TIMEOUT, "Imported pane still compiling.")
    assert payload == {
        "error_code": "MAT_ROLE_ACK_TIMEOUT",
        "recovery_action": "retry_material_role",
        "error_detail": "Imported pane still compiling.",
    }


def test_error_payload_accepts_a_bare_string_and_an_empty_detail() -> None:
    assert error_payload("WRITEBACK_EXACT_WRITER_REQUIRED") == {
        "error_code": "WRITEBACK_EXACT_WRITER_REQUIRED",
        "recovery_action": "none",
        "error_detail": "",
    }


def test_error_payload_keys_are_stable_event_fields() -> None:
    # Runtime events are merged as keyword arguments, so these three names are
    # part of the event schema and cannot collide with an event's own fields.
    assert set(error_payload(MeshEditorErrorCode.MAT_COMPILE_FAILED)) == {
        "error_code",
        "recovery_action",
        "error_detail",
    }
