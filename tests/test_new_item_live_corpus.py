"""Explicit licensed-corpus checks; unsupported shapes are counted, never written."""
from collections import Counter
import pytest

from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.core.item_recipe_table import parse_item_recipe, encode_item_recipe
from cdmw.core.item_reward_table import parse_item_reward_set, encode_item_reward_set
from cdmw.core.item_use_reward import parse_item_use_reward, encode_item_use_reward
from cdmw.core.partprefab_dye_table import parse_prefab_dye_row, encode_prefab_dye_row
from tools.new_item_corpus import read_table


@pytest.mark.real_game
@pytest.mark.parametrize("stem,parser,encoder,minimum",[
    ("multichangeinfo",parse_item_recipe,encode_item_recipe,18576),
    ("dropsetinfo",parse_item_reward_set,encode_item_reward_set,13045),
    ("itemuseinfo",parse_item_use_reward,encode_item_use_reward,160),
    ("partprefabdyeslotinfo",parse_prefab_dye_row,encode_prefab_dye_row,1600),
])
def test_supported_current_records_roundtrip(stem,parser,encoder,minimum,record_property):
    pair=read_table(stem)
    supported,unsupported=0,Counter()
    for directory,start,end in parse_pabgh_table(pair.header,payload=pair.payload).row_spans(len(pair.payload)):
        raw=pair.payload[start:end]
        try:
            row=parser(raw)
        except ValueError as error:
            unsupported[str(error)]+=1
            continue
        assert row.key==directory.row_id
        assert encoder(row)==raw
        supported+=1
    assert supported>=minimum, (stem,supported,dict(unsupported))
    if stem in ("multichangeinfo", "partprefabdyeslotinfo"):
        assert not unsupported
    record_property("supported",supported)
    record_property("unsupported",dict(unsupported))
