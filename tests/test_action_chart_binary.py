"""`.paac` action charts and the `.paacdesc` descriptor: decode, inspector and writes.

Every fixture is built here from the loader layout documented in
`cdmw/core/action_chart_binary.py`; no game file is needed except in the
`real_game` corpus test, which reads the installed archives.
"""

from __future__ import annotations

import math
import struct

import pytest

from cdmw.core.action_chart_binary import (
    ANIMATION_ARRAYS,
    LAYOUT_CHART,
    LAYOUT_COMMON_ACTION_INFO,
    LAYOUT_COMMON_ACTION_INFO_SERIALIZED,
    MODEL_ATTACHMENT_SOCKET_KIND,
    ActionChartError,
    ChartValueEdit,
    apply_chart_value_edits,
    decode_action_chart,
    decode_action_package_description,
    frame_event_at,
    replace_chart_strings,
    retarget_animation,
    retarget_chart_string,
    socket_event_payload,
)
from cdmw.core.archive_action_chart_preview import build_action_chart_preview
from cdmw.models import ArchiveEntry

CLIPS = ("1_pc/1_phm/cd_phm_sword_attack_00.paa", "1_pc/1_phm/cd_phm_sword_idle_00.paa")
TABLES = (
    ("upperaction/1_pc/1_phm/common_upper_branchset",),
    CLIPS,
    (),
    ("fx_sword_trail_a__trail1.action.effect",),
    (),
    ("character/binary/motionblending/phm_locomotion/sword_move.motionblending",),
    ("Bip01 R Hand", "RHand_Socket"),
    ("MainWeapon_Sword",),
    (),
    (),
)


def strings(values) -> bytes:
    out = struct.pack("<H", len(values))
    for value in values:
        raw = value.encode("ascii") + b"\0"
        out += bytes([len(raw)]) + raw
    return out


def frame_events() -> bytes:
    """A ModelAttachmentSocket (32 bytes) then an Effect header (16 bytes)."""

    socket = struct.pack("<5H", MODEL_ATTACHMENT_SOCKET_KIND, 0, 0, 0x102, 0xFFFF) + b"\0\0"
    socket += struct.pack("<fIHHHBBBb", 0.0, 0, 0, 1, 0, 2, 0, 0, 0) + b"\0\0"
    effect = struct.pack("<5H", 57, 0, 0, 0x102, 0xFFFF) + b"\0\0" + b"\0" * 4
    return socket + effect


def animation(index: int, *, end: float, arrays: dict, events: list) -> bytes:
    header = bytearray(0xA8)
    struct.pack_into("<ff", header, 0, 0.0, end)
    offset = 0
    body = b""
    for slot, (name, width) in enumerate(ANIMATION_ARRAYS):
        records = arrays.get(name, [])
        struct.pack_into("<HH", header, 0x70 + 4 * slot, offset, len(records))
        for record in records:
            assert len(record) == width
            body += record
        offset += len(records) * width
    struct.pack_into("<4H", header, 0x9C, index, index, 0xFFFF, 0 if index == 0 else 0xFFFF)
    instances = b"".join(struct.pack("<ffIII", begin, end_, dword, sequence, 0x1FFFF)
                         for sequence, (begin, end_, dword) in enumerate(events))
    return bytes(header) + body + bytes([len(events)]) + instances


def chart_bytes(*, share_counts=(0,) * 10, tables=TABLES, trailing: bytes = b"") -> bytes:
    out = struct.pack("<I", 2)
    out += animation(0, end=1.5, arrays={
        "frameTag": [struct.pack("<ffI", 0.2, 0.4, 7)],
        "animationSpeedInfoArray": [struct.pack("<fffI", 0.0, 1.0, 1.0, 0x1F)],
        "justTimeFrameTagInfo": [struct.pack("<ffII", 0.5, 0.8, 0x30001, 4)],
    }, events=[(0.0, -1.0, 0), (0.3, -1.0, 8)])
    out += animation(1, end=2.5, arrays={}, events=[])
    out += struct.pack("<III", 0, 0, 0)
    out += b"".join(strings(values) for values in tables)
    out += struct.pack("<fIIfBB", 1.0, 0, 0, 1.0, 0, 0)
    out += strings(()) + struct.pack("<10H", *share_counts)
    out += struct.pack("<6BHH", 0, 0, 1, 0, 1, 0, 2, 0)
    out += b"\0" * 40  # DefaultSocket
    out += struct.pack("<H", 0)  # include: table 0 entry 0
    for first in (0, 1):
        node = bytearray(0x120)
        struct.pack_into("<I", node, 0x54, first)
        struct.pack_into("<H", node, 0xEE, 1)
        struct.pack_into("<H", node, 0x112, 0xFFFF)
        out += bytes(node)
    out += struct.pack("<II", 0, 0)  # conditionInstanceArray
    out += struct.pack("<I", 1) + b"\0" * 0x38 + struct.pack("<II", 0, 0)  # branchInstanceArray
    out += struct.pack("<HI", 0, 0)  # keyGuideInstanceArray
    out += struct.pack("<IB", 0, 0)  # key guide frame events
    events = frame_events()
    out += struct.pack("<I", len(events)) + events
    out += struct.pack("<BI", 0, 0)  # child frame events, contents groups
    return out + trailing


def test_chart_decodes_to_the_last_byte_with_named_sections():
    data = chart_bytes()
    chart = decode_action_chart(data, virtual_path="actionchart/bin__/upperaction/sword_upper.paac")
    assert chart.layout == LAYOUT_CHART
    at = 0
    for span in chart.spans:
        assert span.offset == at
        at += span.size
    assert at == len(data) and chart.explained_bytes == len(data) and not chart.unexplained_spans
    assert [chart.clip_name(item) for item in chart.animations] == list(CLIPS)
    assert chart.blend_name(chart.animations[0]).endswith("sword_move.motionblending")
    assert [(item.start_time, item.end_time) for item in chart.animations] == [(0.0, 1.5), (0.0, 2.5)]
    assert [(node.first_animation, node.animation_count) for node in chart.nodes] == [(0, 1), (1, 1)]
    assert chart.include_names == (0,) and chart.action_speed_rate == 1.0
    assert chart.counts["branches"] == 1 and chart.counts["frame events"] == 2
    assert chart.animations[0].array("frameTag").count == 1
    kinds = [frame_event_at(chart, data, ref).kind_name for ref in chart.animations[0].events]
    assert kinds == ["ModelAttachmentSocket", "Effect"]
    payload = socket_event_payload(data, frame_event_at(chart, data, chart.animations[0].events[0]))
    assert (chart.tables[7].value(payload.part), chart.tables[6].value(payload.parent), payload.mode) == (
        "MainWeapon_Sword", "RHand_Socket", 2)


@pytest.mark.parametrize(
    "data",
    [chart_bytes()[:-3], chart_bytes(trailing=b"\0"), chart_bytes(share_counts=(1,) + (0,) * 9)],
    ids=["truncated", "trailing", "share-values"],
)
def test_chart_refuses_bytes_outside_the_grammar(data):
    with pytest.raises(ActionChartError):
        decode_action_chart(data)


def test_animation_retarget_resizes_the_table_and_keeps_every_other_byte():
    data = chart_bytes()
    chart = decode_action_chart(data)
    table = chart.tables[1]
    new = "1_pc/1_phm/cd_phm_longsword_heavy_attack_combo_finisher_00.paa"
    patched, count = retarget_animation(data, CLIPS[0], new)
    assert count == 1
    assert len(patched) == len(data) + len(new) - len(CLIPS[0])
    assert patched[:table.offset] == data[:table.offset]
    assert patched[table.offset + table.size + len(new) - len(CLIPS[0]):] == data[table.offset + table.size:]
    again = decode_action_chart(patched)
    assert again.clip_name(again.animations[0]) == new and again.clip_name(again.animations[1]) == CLIPS[1]
    shorter, _ = retarget_animation(patched, new, "a.paa")
    assert decode_action_chart(shorter).clip_name(decode_action_chart(shorter).animations[0]) == "a.paa"
    assert retarget_animation(shorter, "a.paa", CLIPS[0])[0] == data


def test_string_edits_refuse_what_the_table_cannot_hold():
    data = chart_bytes()
    with pytest.raises(ActionChartError, match="has no entry"):
        retarget_chart_string(data, 1, "missing.paa", "x.paa")
    with pytest.raises(ActionChartError, match="printable ASCII"):
        replace_chart_strings(data, 6, {1: "Socketé"})
    with pytest.raises(ActionChartError, match="at most 254"):
        replace_chart_strings(data, 6, {1: "x" * 255})
    with pytest.raises(ActionChartError, match="does not exist"):
        replace_chart_strings(data, 10, {0: "x"})
    renamed = replace_chart_strings(data, 6, {1: "x" * 254})
    assert decode_action_chart(renamed).tables[6].values[1] == "x" * 254


def test_value_edits_write_only_the_named_floats():
    data = chart_bytes()
    edits = [
        ChartValueEdit("chart.action_speed_rate", 1.25),
        ChartValueEdit("animation.end_time", 1.2, 0),
        ChartValueEdit("speed.rate", 0.5, 0, 0),
        ChartValueEdit("frame_tag.start_time", 0.1, 0, 0),
        ChartValueEdit("just_time.end_time", 0.9, 0, 0),
        ChartValueEdit("event.begin", 0.25, 0, 1),
    ]
    patched = apply_chart_value_edits(data, edits)
    assert len(patched) == len(data)
    assert sum(left != right for left, right in zip(data, patched)) <= 4 * len(edits)
    chart = decode_action_chart(patched)
    assert math.isclose(chart.action_speed_rate, 1.25)
    assert math.isclose(chart.animations[0].end_time, 1.2, rel_tol=1e-6)
    assert math.isclose(chart.animations[0].events[1].begin, 0.25)
    speed = chart.animations[0].array("animationSpeedInfoArray")
    assert struct.unpack_from("<f", patched, speed.offset + 8)[0] == 0.5


@pytest.mark.parametrize(
    "edit, message",
    [
        (ChartValueEdit("node.first_animation", 1.0), "not an editable"),
        (ChartValueEdit("speed.rate", 0.0, 0, 0), "above 0"),
        (ChartValueEdit("animation.end_time", float("nan"), 0), "finite"),
        (ChartValueEdit("animation.start_time", 2.0, 0), "end before it starts"),
        (ChartValueEdit("event.end", 0.1, 0, 1), "end before it begins"),
        (ChartValueEdit("frame_tag.start_time", 0.1, 1, 0), "no frameTag entry"),
        (ChartValueEdit("animation.end_time", 1.0, 5), "does not exist"),
    ],
)
def test_value_edits_refuse_unproven_or_inconsistent_values(edit, message):
    with pytest.raises(ActionChartError, match=message):
        apply_chart_value_edits(chart_bytes(), [edit])


def test_common_action_info_layouts_are_picked_by_file_name():
    record = b"\0" * 0x58
    common = struct.pack("<III", 1, 7, 1) + record + struct.pack("<IHI", 1, 3, 0)
    common += struct.pack("<I", 2) + b"\1\2" + struct.pack("<II", 0, 0) + strings(("a",))
    chart = decode_action_chart(common, virtual_path="actionchart/xml/description/commonactioninfo.paac")
    assert chart.layout == LAYOUT_COMMON_ACTION_INFO and chart.explained_bytes == len(common)
    serialized = struct.pack("<II", 1, 3) + b"abc" + b"\0" * 16 + struct.pack("<IQ", 1, 9) + b"\xc6\0\0\0tail"
    chart = decode_action_chart(serialized, virtual_path="x/commonactioninfo_serialized.paac")
    assert chart.layout == LAYOUT_COMMON_ACTION_INFO_SERIALIZED
    assert [(span.offset, span.size) for span in chart.unexplained_spans] == [(len(serialized) - 8, 8)]
    with pytest.raises(ActionChartError, match="only standard"):
        apply_chart_value_edits(serialized, [ChartValueEdit("chart.action_speed_rate", 1.0)],
                                virtual_path="x/commonactioninfo_serialized.paac")


def descriptor_bytes() -> bytes:
    names = ("Player_Kliff", "upperaction/1_pc/1_phm/basic_upper", "DefaultUpperMain",
             "upperaction/1_pc/1_phm/sword_upper", "Sword")
    return strings(names) + struct.pack("<II", 1, 1) + struct.pack("<5H", 1, 0, 1, 2, 0) + struct.pack("<2H", 3, 4)


def test_package_description_names_each_slot_chart():
    description = decode_action_package_description(descriptor_bytes())
    package = description.packages[0]
    assert (package.name, package.main_slot, package.main_chart) == (
        "Player_Kliff", "DefaultUpperMain", "upperaction/1_pc/1_phm/basic_upper")
    assert package.sub_packages == (("Sword", "upperaction/1_pc/1_phm/sword_upper"),)
    with pytest.raises(ActionChartError):
        decode_action_package_description(descriptor_bytes() + b"\0")


def test_inspector_lists_animations_events_and_edit_scope():
    preview = build_action_chart_preview(chart_bytes(), "actionchart/bin__/upperaction/sword_upper.paac", extension=".paac")
    text = preview.preview_text
    assert "Animations: 2 in 2 nodes" in text
    assert "0.000-1.500  1_pc/1_phm/cd_phm_sword_attack_00.paa" in text
    assert "ModelAttachmentSocket" in text and "Included charts: upperaction/1_pc/1_phm/common_upper_branchset" in text
    assert "speed.rate" in text and preview.metadata_label == "Action Chart (2 animations)"
    description = build_action_chart_preview(descriptor_bytes(), "a.paacdesc", extension=".paacdesc")
    assert "Sword = upperaction/1_pc/1_phm/sword_upper" in description.preview_text


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))

    def make(path: str, payload: bytes) -> ArchiveEntry:
        folder = tmp_path / "0008"
        folder.mkdir(parents=True, exist_ok=True)
        paz = folder / f"{len(list(folder.glob('*.paz')))}.paz"
        paz.write_bytes(payload)
        return ArchiveEntry(path, folder / "0.pamt", paz, 0, len(payload), len(payload), 0, 0)

    return make


def test_archive_browser_shows_the_chart_inspector(stored):
    from cdmw.core.archive_preview_result_builder import build_archive_preview_result

    result = build_archive_preview_result(stored("actionchart/bin__/upperaction/1_pc/1_phm/sword_upper.paac", chart_bytes()))
    assert result.preferred_view == "text"
    assert "Action chart inspector" in result.preview_text and "Action Chart (2 animations)" in result.metadata_summary
    broken = build_archive_preview_result(stored("actionchart/bin__/upperaction/broken.paac", chart_bytes()[:-3]))
    assert "The action chart could not be decoded" in broken.detail_text


def test_placement_studio_reads_socket_events_from_the_current_layout():
    from tools.placement_studio.paac_events import decode

    events = decode(chart_bytes(), path="actionchart/bin__/upperaction/sword_upper.paac")
    first = events.actions[0]
    assert first.clip == "character/motion/" + CLIPS[0] and first.duration == 1.5
    assert first.blendspace.endswith("sword_move.motionblending")
    assert [(event.part, event.mode, event.parent, event.child) for event in first.sockets] == [
        ("MainWeapon_Sword", 2, "RHand_Socket", "Bip01 R Hand")]
    assert first.other_types == (57,)


@pytest.mark.real_game
def test_every_shipped_chart_decodes_and_round_trips_a_rename():
    from tools.placement_studio import corpus
    from cdmw.core.archive_extraction import read_archive_entry_data

    if not corpus.game_root().is_dir():
        pytest.skip("needs the installed game")
    seen = {".paac": 0, ".paacdesc": 0}
    for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
        path = corpus.normalize_game_path(entry.path)
        suffix = path[path.rfind("."):]
        if suffix not in seen:
            continue
        data = read_archive_entry_data(entry)[0]
        seen[suffix] += 1
        if suffix == ".paacdesc":
            assert decode_action_package_description(data).packages
            continue
        chart = decode_action_chart(data, virtual_path=path)
        assert sum(span.size for span in chart.spans) == len(data), path
        if chart.layout == LAYOUT_CHART and chart.tables[1].raw:
            old = chart.tables[1].values[0]
            longer = replace_chart_strings(data, 1, {0: old + "_longer"})
            assert replace_chart_strings(longer, 1, {0: old}) == data, path
        elif chart.layout != LAYOUT_CHART:
            assert all(span.name.startswith("reflection") for span in chart.unexplained_spans), path
    assert seen[".paac"] >= 560 and seen[".paacdesc"] == 1
