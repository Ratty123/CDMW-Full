from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_preview_limits import (
    alignment_preview_background_source_face_limit_for_total,
    alignment_preview_requested_source_indices,
    alignment_preview_selected_source_face_limit_for_total,
    alignment_preview_source_face_total,
)


def test_alignment_preview_requested_source_indices_filters_to_existing_submeshes() -> None:
    mesh = SimpleNamespace(submeshes=[object(), object(), object()])

    assert alignment_preview_requested_source_indices(mesh, (0, "2", 3, -1, "bad")) == (0, 2)
    assert alignment_preview_requested_source_indices(SimpleNamespace(submeshes=[]), (0,)) == ()


def test_alignment_preview_source_face_total_counts_requested_submeshes() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(faces=[1, 2]),
            SimpleNamespace(faces=[]),
            SimpleNamespace(faces=[1, 2, 3]),
        ]
    )

    assert alignment_preview_source_face_total(mesh, (0, 2, 9, "bad")) == 5


def test_alignment_preview_selected_source_face_limit_thresholds() -> None:
    assert alignment_preview_selected_source_face_limit_for_total(
        130_000,
        selected_requested=True,
        interactive=True,
        fallback_limit=7,
    ) == 18_000
    assert alignment_preview_selected_source_face_limit_for_total(
        130_000,
        selected_requested=False,
        interactive=True,
        fallback_limit=7,
    ) == 8_000
    assert alignment_preview_selected_source_face_limit_for_total(
        10_000,
        selected_requested=False,
        interactive=False,
        fallback_limit=7,
    ) == 7


def test_alignment_preview_background_source_face_limit_thresholds() -> None:
    assert alignment_preview_background_source_face_limit_for_total(
        130_000,
        interactive=True,
        fallback_limit=7,
    ) == 2_000
    assert alignment_preview_background_source_face_limit_for_total(
        45_000,
        interactive=False,
        fallback_limit=7,
    ) == 5_000
    assert alignment_preview_background_source_face_limit_for_total(
        10_000,
        interactive=False,
        fallback_limit=7,
    ) == 7
