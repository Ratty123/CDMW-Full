"""Selecting must not be rejected for failing a geometry-change contract.

Four captured sessions all ended the same way::

    mesh_edit_dotnet_commit_failed  action=select
    mesh_edit_dotnet_commit_failed  action=clear_selection
    "native select result did not include submesh counts;
     Python working mesh hydration is disabled"

Every action the reader took in Edit Mesh was rejected, and Finish Edit Mesh
then had nothing to commit and left the session open. The cause was a guard in
the static replacement adapter that demanded submesh counts from *every*
result. A selection changes no geometry, so the native editor has no counts to
report and correctly reports none, and the guard turned that into a fatal
error.

Only a result that says it changed the mesh owes counts. These tests hold both
halves of that: a selection passes through with the counts unchanged, and a
result that claims a topology change while omitting them still fails loudly,
because that one really is a broken hydration contract.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from cdmw.domain.mesh import MeshEditResult, MeshEditSelection
from cdmw.ui.mesh_editor import static_replacement_adapter as adapter_module
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession

BEFORE_COUNTS = ((120, 60), (40, 20))


class _StubController:
    """The smallest controller the adapter needs, returning a chosen result."""

    def __init__(self, result: MeshEditResult) -> None:
        self._result = result
        self.applied: list[str] = []

    def apply(self, action: str, **_kwargs: object) -> MeshEditResult:
        self.applied.append(action)
        return self._result

    def native_update_for_result(self, _result: MeshEditResult) -> object:
        return None

    def session_view(self) -> object:
        raise AssertionError("not needed for these tests")


def _session(result: MeshEditResult, monkeypatch: pytest.MonkeyPatch) -> StaticReplacementMeshEditSession:
    session = StaticReplacementMeshEditSession.__new__(StaticReplacementMeshEditSession)
    session.controller = _StubController(result)  # type: ignore[attr-defined]
    session.mesh = object()  # type: ignore[attr-defined]
    session.submesh_counts = BEFORE_COUNTS  # type: ignore[attr-defined]
    # The result builder needs a real mesh only to derive fallback counts, and
    # these tests always supply them.
    monkeypatch.setattr(
        adapter_module,
        "_static_result",
        lambda mesh, edit_result, native_update, *, before, after=None, selection: {
            "before": before,
            "after": after,
            "action": edit_result.action,
        },
    )
    return session


def _result(action: str, **overrides: object) -> MeshEditResult:
    payload: dict[str, object] = {
        "action": action,
        "status": "ok",
        "revision": 3,
        "submesh_counts": (),
        "topology_changed": False,
        "submesh_count_delta": 0,
    }
    payload.update(overrides)
    return MeshEditResult(**payload)  # type: ignore[arg-type]


@pytest.mark.parametrize("action", ["select", "clear_selection"])
def test_a_selection_commits_without_submesh_counts(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(_result(action), monkeypatch)

    outcome = session._result(
        session.controller.apply(action),
        before=BEFORE_COUNTS,
        selection=MeshEditSelection(),
    )

    assert outcome["after"] == BEFORE_COUNTS, (
        "a selection changes no geometry, so the counts must carry forward "
        "unchanged rather than the action being rejected"
    )
    assert session.submesh_counts == BEFORE_COUNTS


def test_a_result_that_changed_topology_still_must_report_counts(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard's real purpose survives: a broken contract still fails loudly."""

    session = _session(_result("subdivide", topology_changed=True), monkeypatch)

    with pytest.raises(RuntimeError, match="did not include submesh counts"):
        session._result(
            session.controller.apply("subdivide"),
            before=BEFORE_COUNTS,
            selection=MeshEditSelection(),
        )


def test_a_transform_that_omits_counts_still_fails(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transform moves vertices without changing topology or submesh count.

    It has the same flags as a selection, which is why the discriminator is the
    action rather than those flags: a transform that omits its counts is the
    broken hydration contract the guard exists to catch.
    """

    session = _session(_result("transform", affected_submesh_indices=(0,)), monkeypatch)

    with pytest.raises(RuntimeError, match="did not include submesh counts"):
        session._result(
            session.controller.apply("transform"),
            before=BEFORE_COUNTS,
            selection=MeshEditSelection(),
        )


def test_reported_counts_are_still_preferred_when_present(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Carrying `before` forward is the empty case only, never an override."""

    reported = ((130, 65), (40, 20))
    session = _session(
        _result("smooth", submesh_counts=reported, topology_changed=True), monkeypatch
    )

    outcome = session._result(
        session.controller.apply("smooth"),
        before=BEFORE_COUNTS,
        selection=MeshEditSelection(),
    )

    assert outcome["after"] == reported
    assert session.submesh_counts == reported
