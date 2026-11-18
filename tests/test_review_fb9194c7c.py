"""Review of fb9194c7c: the tab's one item-set preparation hands each open its own unticked parts.

The tab keeps a single ItemSetEditorPreparation. Opening one file of a set
(prepare_item_set_for_editor) and opening the ticked parts (_open_members) each
create it when it is missing, and each connects its own ready handler; only the
second hands over the parts the preparation holds. Whichever runs first in a
tab's life decides what every later open does:

- a member open first: a later set open stores its unticked parts on the
  preparation and nothing hands them over, so the set opens with every part shown;
- a set open first: a later member open's ready goes through _open_prepared_set,
  which replaces the parts that open took (shell_bridge's
  _take_pending_hidden_parts_for_open) with the preparation's None.

Only the preparation's background reads are stood in for; the module's own
functions run as the app runs them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cdmw.ui.mesh_editor import item_set_preparation

if not hasattr(item_set_preparation, "_open_prepared_set"):
    pytest.skip("astra/next-parity's fb9194c7c is not merged here", allow_module_level=True)

SWORD = "character/weapon/cd_phm_02_sword_0015.pac"
SHEATH = "character/weapon/cd_phm_02_sword_0015_in.pac"


class _Signal:
    def __init__(self) -> None:
        self.slots = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def emit(self, *args) -> None:
        for slot in tuple(self.slots):
            slot(*args)


class _Preparation:
    """The files are read in the background; the test says when they are ready."""

    def __init__(self, _service, _tab) -> None:
        self.ready = _Signal()
        self.failed = _Signal()
        self.edit_set = False

    def start(self, _selected, _members, **_item_scope) -> bool:
        return True

    def cancel(self, *_args) -> None:
        pass


@pytest.fixture
def shell(monkeypatch):
    opened = []
    monkeypatch.setattr(item_set_preparation, "ItemSetEditorPreparation", _Preparation)
    monkeypatch.setattr(item_set_preparation.ArchiveCatalogueService, "compatibility_entry",
                        staticmethod(lambda member: member))
    monkeypatch.setattr("cdmw.ui.mesh_editor.tab_rust_editor.hold_warmups_for_mesh_editor_open",
                        lambda *_args: None)
    monkeypatch.setattr(item_set_preparation, "open_prepared_item_piece",
                        lambda target, contexts, *, edit_set=False: opened.append(
                            (target._mesh_editor_hidden_parts_for_open, edit_set)))
    bridge = SimpleNamespace(item_set_contains=lambda _entry: True, item_set_members=("sword", "sheath"))
    value = SimpleNamespace(
        archive=SimpleNamespace(archive_remote_bridge=bridge, archive_catalogue_service=object()),
        mesh_editor_tab=SimpleNamespace(item_set_preparation=None),
        _mesh_editor_pending_hidden_parts=None,
        _mesh_editor_hidden_parts_for_open=None,
        set_status_message=lambda *_args, **_kwargs: None,
        opened=opened,
    )
    return value


def _ready(shell) -> None:
    shell.mesh_editor_tab.item_set_preparation.ready.emit(("context",))


def test_a_set_open_after_a_member_open_keeps_its_unticked_parts(shell) -> None:
    item_set_preparation.prepare_item_set_for_editor(shell, "sword")
    _ready(shell)
    item_set_preparation._open_members(shell, ("sword", "sheath"), ((SWORD, (1,)), (SHEATH, ())))
    _ready(shell)
    assert shell.opened[-1] == ({SWORD: (1,), SHEATH: ()}, True)


def test_a_member_open_after_a_set_open_keeps_the_parts_it_took(shell) -> None:
    item_set_preparation._open_members(shell, ("sword", "sheath"), ((SWORD, (1,)), (SHEATH, ())))
    _ready(shell)
    # The member open takes the Scene panel's parts first, as shell_bridge does
    # (_take_pending_hidden_parts_for_open), then starts the set's preparation.
    shell._mesh_editor_hidden_parts_for_open = {SWORD: (2,)}
    item_set_preparation.prepare_item_set_for_editor(shell, "sword")
    _ready(shell)
    assert shell.opened[-1] == ({SWORD: (2,)}, False)
