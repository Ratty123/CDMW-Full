"""Why each Mesh Editor action is hidden, pinned so the two reasons stay apart.

Fourteen action keys never reach the tool rail, for two unrelated reasons, and
the set alone does not say which is which. Eleven change topology and have no
exact-writer route, so they are blocked and the capability matrix says why in
words. Three are the legacy per-element Select actions, superseded by the single
Select tool, carrying no authoring limit at all.

Keeping them hidden rather than showing them greyed out was asked as a product
question and answered: eleven permanently disabled buttons cost the reader more
attention than they return, because nothing the reader can do makes one
available. These tests hold that answer in place and, more usefully, hold the
*reasons* current while the actions stay hidden -- a reason nothing renders is
exactly the kind of text that rots.
"""

from __future__ import annotations

import pytest

from cdmw.domain.mesh.authoring_capability import (
    AuthoringSupport,
    action_authoring_capability,
)
from cdmw.ui.mesh_editor.actions import (
    LEGACY_PART_SELECTION_ACTION_KEYS,
    MESH_EDITOR_ACTIONS,
    _UNAUTHORABLE_TOPOLOGY_ACTION_KEYS,
    _USER_HIDDEN_ACTION_KEYS,
    MESH_EDITOR_VISIBLE_ACTIONS,
    mesh_editor_action_authoring_blocker,
    mesh_editor_actions_by_key,
)


def test_the_hidden_set_is_exactly_the_two_groups() -> None:
    assert _USER_HIDDEN_ACTION_KEYS == (
        LEGACY_PART_SELECTION_ACTION_KEYS | _UNAUTHORABLE_TOPOLOGY_ACTION_KEYS
    )
    assert not (LEGACY_PART_SELECTION_ACTION_KEYS & _UNAUTHORABLE_TOPOLOGY_ACTION_KEYS)


def test_every_hidden_key_is_a_real_action() -> None:
    known = set(mesh_editor_actions_by_key())
    assert _USER_HIDDEN_ACTION_KEYS <= known, sorted(_USER_HIDDEN_ACTION_KEYS - known)


def test_no_hidden_action_reaches_the_rail() -> None:
    visible = {action.key for action in MESH_EDITOR_VISIBLE_ACTIONS}
    assert not (visible & _USER_HIDDEN_ACTION_KEYS)


@pytest.mark.parametrize("key", sorted(_UNAUTHORABLE_TOPOLOGY_ACTION_KEYS))
def test_every_hidden_topology_action_still_has_a_written_reason(key: str) -> None:
    # The reason is not rendered anywhere today. It is kept current for a
    # capability panel, a diagnostics snapshot, and any future decision to
    # surface these -- none of which can use text that has gone stale.
    capability = action_authoring_capability(key)

    assert capability is not None, key
    assert not capability.authorable, key
    assert capability.reason.strip(), key
    assert capability.detail.strip(), key


def test_loop_cut_is_unproven_where_the_others_are_blocked() -> None:
    # Not the same claim, and the matrix is right to separate them. Loop Cut has
    # an exact route that almost never applies -- a derived vertex needs every
    # parent to agree on every protected byte, measured at 0.0072% of LOD0
    # edges -- while the other ten have no exact route at all. Flattening the
    # two would lose the only one that a byte-derivation result could reopen.
    assert action_authoring_capability("loop_cut").support is AuthoringSupport.UNPROVEN
    for key in sorted(_UNAUTHORABLE_TOPOLOGY_ACTION_KEYS - {"loop_cut"}):
        assert action_authoring_capability(key).support is AuthoringSupport.BLOCKED, key


def test_every_topology_capable_palette_action_has_an_explicit_answer() -> None:
    keys = {
        action.key
        for action in MESH_EDITOR_ACTIONS
        if action.category in {"topology", "cleanup"}
    } | {"uv_auto_unwrap"}

    for key in sorted(keys):
        assert action_authoring_capability(key) is not None, key


def test_a_read_only_loaded_format_blocks_same_count_mutations_too() -> None:
    blocker = mesh_editor_action_authoring_blocker(
        "transform_move",
        mesh_format="meshinfo",
    )

    assert "read-only" in blocker


@pytest.mark.parametrize("key", sorted(LEGACY_PART_SELECTION_ACTION_KEYS))
def test_a_superseded_action_carries_no_authoring_limit(key: str) -> None:
    # The distinction that matters: these are hidden because the single Select
    # tool replaced them, not because the writer refuses them. Giving one an
    # authoring reason would mean the two groups had been conflated.
    assert action_authoring_capability(key) is None, key
