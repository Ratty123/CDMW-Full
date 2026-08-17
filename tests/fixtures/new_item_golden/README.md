# New Item golden

The 2026-08-17 spike installed two clones of Wolf's Fang (Ziane's sword,
item 1001295) into the live game and both were verified there: item 1990001
"Wolf's Fang (Clone A)" on the shipped model, and item 1990002 "Wolf's Fang
(Clone B)" on a cloned model family `cd_phm_01_sword_9109`, each swapped into
one stock entry of `Store_Camp_Equipment` and one of `Store_Pai_Equipment`,
joined to Ziane's eleven item groups, and named in all fourteen language tables.

This fixture pins `NewItemService.plan()` to that accepted output.

- Everything except `expected/` is the pre-spike source, trimmed to what the two
  clones touch: the ItemInfo rows the template and the four swap victims
  reference, the StringInfo rows for the template's part stems and icon, the
  four part-prefab records, the two store rows, the eleven group rows,
  StatusInfo and EquipTypeInfo whole, each language table cut to the template's
  name and description entries with a neighbour either side, and the template's
  model family files (the sheath mesh is a truncated stand-in: it is borrowed and
  never copied). `tests/test_new_item_golden.py` lays this out as a synthetic
  package the same way `tests/test_new_item_service.py` does.
- `expected/` is the spike's own output: the two ItemInfo rows, the two store
  rows after both swaps, the two re-pathed prefabs, and `golden.json` with the
  StringInfo rows, part-prefab records, group memberships, localisation records,
  the new files' hashes, and the spec the spike used (keys, names, swaps).

One thing the spike got wrong, kept here on purpose: its localisation keys
(`4300529299990011` and friends) were invented, and the game derives an item's
keys from its id (`(id << 32) | 0x70` and `| 0x71`), so both clones showed up
nameless. The gate passes those keys explicitly, so it still replays the bytes
that were installed; the allocator itself now derives the shipped form
(`localization_keys()`), and `NewItemSpec` validation warns on any other.

Regenerate with the session scratch script `build_golden_fixture.py` from the
pre-spike table extracts, the archive backup `20260817_110150` and
`spike_out/loose`; the point of checking it in is that none of those need to
exist for the gate to run.
