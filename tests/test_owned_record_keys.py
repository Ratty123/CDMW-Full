"""New records an item adds (drop sets, transitions, item uses) come from its own key block."""
import pytest

from cdmw.domain.new_item.allocation import (
    OWNED_RECORD_BLOCK_BASE, OWNED_RECORD_BLOCK_SIZE, AllocationError, allocate_owned_record_keys,
    owned_record_block,
)


def test_each_item_owns_a_distinct_block_above_the_shipped_keys():
    first, second = owned_record_block(1990000), owned_record_block(1990017)
    assert first.start == OWNED_RECORD_BLOCK_BASE + 1990000 * OWNED_RECORD_BLOCK_SIZE
    assert len(first) == OWNED_RECORD_BLOCK_SIZE and not set(first) & set(second)
    # Shipped DropSetInfo tops out near 20,250,408; every block stays a u32 key.
    assert first.start > 20_250_408
    assert owned_record_block(2_139_742_131).stop - 1 <= 0xFFFFFFFF


def test_two_separately_built_items_never_take_the_same_record():
    shipped = {100000, 20250408}
    armor = allocate_owned_record_keys(shipped, 14, 1990000)
    gloves = allocate_owned_record_keys(shipped, 14, 1990017)
    assert not set(armor) & set(gloves)
    assert armor == tuple(owned_record_block(1990000)[:14])


def test_taken_keys_are_skipped_and_a_full_block_falls_back():
    block = owned_record_block(1990005)
    assert allocate_owned_record_keys({block.start}, 1, 1990005) == (block.start + 1,)
    keys = allocate_owned_record_keys(set(block), 2, 1990005, fallback=range(1_990_000, 1_990_010))
    assert keys == (1_990_000, 1_990_001)
    with pytest.raises(AllocationError):
        allocate_owned_record_keys(set(block), 1, 1990005, fallback=range(0))
