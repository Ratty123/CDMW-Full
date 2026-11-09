"""`ClipIndex.filter` answers from facets worked out once, and answers as before.

The filter runs on the UI thread whenever the clip list changes, over some 177,000 clips, and
reading each clip's facets through its properties cost about 0.2 s a call. The index now keeps
the facets, lower-cased paths and clips per rig; these tests hold it to the plain reading.
"""

from __future__ import annotations

import itertools

from tools.placement_studio.clips import ANY, ClipIndex, _entry


def _paths():
    rigs = ("1_pc/1_phm", "1_pc/2_phw", "2_npc/3_ghm")
    folders = ("", "weapon/", "00_mon/", "02_mission/", "99_autofacial/")
    names = ("Run_Fast", "sword_at_draw", "idle_add_breath", "Walk_LOD", "attack_combo")
    for rig, folder, name in itertools.product(rigs, folders, names):
        stem = f"cd_{name.lower()}"
        yield f"character/motion/{rig}/{folder}{stem}.paa"
        yield f"character/motion/motion_lod__/{rig}/{folder}{stem}_lod.paa"


def _plain(index, *, rig=ANY, category=ANY, text="", include_lod=False, include_facial=True,
           include_additive=True, include_equipment=True, include_story=True, limit=None):
    needles = [part for part in text.lower().split() if part]
    found = [
        entry for entry in index.entries
        if (include_lod or not entry.is_lod) and (include_facial or not entry.facial)
        and (include_additive or not entry.additive) and (include_equipment or not entry.equipment)
        and (include_story or not entry.story) and (rig == ANY or entry.rig == rig)
        and (category == ANY or entry.category == category)
        and all(needle in entry.path.lower() for needle in needles)
    ]
    return (found if limit is None else found[:limit]), len(found)


def test_every_filter_combination_matches_the_plain_reading() -> None:
    index = ClipIndex(_entry(path, None) for path in _paths())
    assert len(index) == 150
    categories = (ANY, *sorted({entry.category for entry in index.entries}))
    for rig in (ANY, *index.rigs(), "9_none/9_none"):
        for category in categories:
            for flags in itertools.product((False, True), repeat=5):
                options = dict(zip(("include_lod", "include_facial", "include_additive",
                                    "include_equipment", "include_story"), flags))
                for text in ("", "SWORD draw", "lod"):
                    for limit in (None, 3):
                        assert index.filter(rig=rig, category=category, text=text, limit=limit,
                                            **options) == _plain(
                            index, rig=rig, category=category, text=text, limit=limit, **options)
