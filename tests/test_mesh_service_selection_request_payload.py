"""The combined selection-request builder must stay equivalent to the pair it fused.

`_native_editor_selection_request_for_apply` exists so a native apply builds its
selection payload once and derives the reuse signature from that same object.
Before it, the payload was serialized twice per apply (once frozen inside the
signature, once for the wire payload), which on a stroke begin after a topology
change was the full remapped selection built twice on the interactive hot path.
"""

from __future__ import annotations

import cdmw.services.mesh_service_payloads as payloads
from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_service_payloads import (
    _native_editor_selection_payload_for_apply,
    _native_editor_selection_request_for_apply,
    _native_editor_selection_signature_for_apply,
)


_SELECTION = MeshEditSelection.from_maps(
    vertices_by_submesh={0: (0, 2, 3)},
    faces_by_submesh={1: (4,)},
)

_PARAM_SHAPES = (
    {},
    {"_native_selection_payload": {"vertices_by_submesh": [{"index": 0, "indices": [1, 2]}]}},
    {
        "_native_screen_selection_payload": {"screen_brush": {"x": 4, "y": 5, "radius_pixels": 10}},
        "_native_selection_payload": {"vertices_by_submesh": [{"index": 0, "indices": [1]}]},
    },
)


def test_request_matches_the_standalone_payload_and_signature_builders() -> None:
    for params in _PARAM_SHAPES:
        payload, signature = _native_editor_selection_request_for_apply(_SELECTION, params)
        assert payload == _native_editor_selection_payload_for_apply(_SELECTION, params)
        assert signature == _native_editor_selection_signature_for_apply(_SELECTION, params)


def test_signature_tags_follow_the_param_shape() -> None:
    tags = [
        _native_editor_selection_request_for_apply(_SELECTION, params)[1][0]
        for params in _PARAM_SHAPES
    ]
    assert tags == ["selection", "native", "native-screen"]


def test_request_builds_the_payload_exactly_once(monkeypatch) -> None:
    calls: list[object] = []
    real = payloads._native_editor_selection_payload_for_apply

    def counted(selection: MeshEditSelection, params: object) -> dict[str, object]:
        calls.append(params)
        return real(selection, params)

    monkeypatch.setattr(payloads, "_native_editor_selection_payload_for_apply", counted)
    for params in _PARAM_SHAPES:
        calls.clear()
        payloads._native_editor_selection_request_for_apply(_SELECTION, params)
        assert len(calls) == 1
