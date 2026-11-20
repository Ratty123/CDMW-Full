"""Draft state problems in Create New Item (no game data needed)."""
from cdmw.core.static_table_records import TableFieldEdit
from cdmw.ui.new_item.draft_file import decode_draft, encode_draft
from cdmw.ui.new_item.state import NewItemDraft, with_template


def test_changing_the_template_clears_added_stat_columns():
    draft = NewItemDraft(template_key=1, extra_stat_keys=[1000005])
    moved = with_template(draft, 2)
    assert moved.extra_stat_keys == []
    assert moved.extra_stat_keys is not draft.extra_stat_keys


def test_a_draft_with_a_game_table_edit_can_be_saved():
    edit = TableFieldEdit(table="iteminfo", key=1, target="_itemTier", value=3)
    draft = NewItemDraft(template_key=1, table_edits=(edit,))
    assert decode_draft(encode_draft(draft)).table_edits == (edit,)
