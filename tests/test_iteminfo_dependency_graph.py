from dataclasses import replace
import threading

import pytest

from cdmw.core.item_layout import read_item_layout,replace_layout_fields
from cdmw.core.iteminfo_definition import set_definition_fields
from cdmw.core.iteminfo_row import parse_iteminfo_row,clone_iteminfo_row
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.iteminfo_dependency_graph import validate_item_graph
from tests.test_independent_item_behavior import behavior_game,definition_game,extended_game
from tests.test_independent_items import setup_game
from tests.test_new_item_service import TEMPLATE


def nested_snapshot(snapshot,*,missing=False,blocked=False):
    raw=snapshot.rows[TEMPLATE].raw; child=1005300
    root=set_definition_fields(raw,{'packed_item':child})
    nested=clone_iteminfo_row(snapshot.rows[TEMPLATE],key=child,string_key='OwnedChild',
        name_key=str((child<<32)|0x70),desc_key=str((child<<32)|0x71))
    nested=replace_layout_fields(read_item_layout(nested),{'_isBlocked':bytes([blocked])}).raw
    if missing: nested=set_definition_fields(nested,{'packed_item':0xfffffff0})
    rows=dict(snapshot.rows)
    rows[child]=parse_iteminfo_row(nested,structured=True)
    return root,replace(snapshot,rows=rows,_authoring_indexes={})


def test_nested_item_graph_handles_cycles_and_records_opaque_boundaries(tmp_path,behavior_game):
    _,snapshot,_=setup_game(tmp_path)
    raw,snapshot=nested_snapshot(snapshot)
    graph=validate_item_graph(raw,snapshot)
    assert {TEMPLATE,1005300}<=graph.item_keys
    assert any(path.endswith('.prefab') for path in graph.resources)
    assert 'ui/texture/left.dds' in graph.resources
    assert any('Auxiliary' in text for text in graph.unresolved)
    assert validate_item_graph(raw,snapshot) is graph


@pytest.mark.parametrize('mode',('missing','blocked'))
def test_nested_item_failures_are_not_hidden_by_a_valid_direct_reference(tmp_path,behavior_game,mode):
    _,snapshot,_=setup_game(tmp_path)
    raw,snapshot=nested_snapshot(snapshot,**{mode:True})
    with pytest.raises(ValueError,match='dependency'): validate_item_graph(raw,snapshot)
    assert not any(isinstance(key,tuple) and key[0]=='declared-item-graph' for key in snapshot._authoring_indexes)


def test_cancelled_walk_never_publishes_an_index_and_budget_is_enforced(tmp_path,behavior_game,monkeypatch):
    import cdmw.services.new_item_behavior as behavior
    import cdmw.services.iteminfo_dependency_graph as graph
    _,snapshot,_=setup_game(tmp_path); raw,snapshot=nested_snapshot(snapshot)
    stop=threading.Event(); original=behavior.validate_behavior_dependencies
    def cancel(*args,**kwargs):
        original(*args,**kwargs); stop.set()
    monkeypatch.setattr(behavior,'validate_behavior_dependencies',cancel)
    with pytest.raises(RunCancelled): validate_item_graph(raw,snapshot,stop_event=stop)
    assert not any(isinstance(key,tuple) and key[0]=='declared-item-graph' for key in snapshot._authoring_indexes)
    monkeypatch.setattr(behavior,'validate_behavior_dependencies',original)
    monkeypatch.setattr(graph,'MAX_ITEMS',1)
    with pytest.raises(ValueError,match='item limit'): validate_item_graph(raw,snapshot)
