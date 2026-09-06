"""Synthetic chart records exercise decoded events, not filename heuristics."""
from dataclasses import replace
import struct
from types import SimpleNamespace

import pytest

from tools.placement_studio.paac_events import decode
from tools.placement_studio.paac_layout import ChartError
from tools.placement_studio.event_timeline import resolve, prepare_timelines
from tools.placement_studio.relationships import from_files

CLIP = 'character/motion/1_pc/1_phm/arbitrary_name.paa'
PART = 'CD_MainWeapon_Sword_R'


def payload(*, mode=1, part=0, parent=0xffff, child=0xffff, condition=0, blend=0., all_parts=0):
    return struct.pack('<4HfIHHHBBBbH', 60, condition, 0, 2, blend, 0,
                       part, parent, child, mode, all_parts, 0, 0, 0)


def chart_bytes(events=None, *, clip=CLIP, duplicate=False, condition_tables=False):
    events = events if events is not None else ((.625, payload()),)
    header = bytearray(156)
    struct.pack_into('<f', header, 4, 2.)
    struct.pack_into('<6H', header, 144, 0, 0, 0xffff, 0xffff, 0xffff, 1)
    blob = bytearray(8)  # Ensure a DWORD offset cannot be mistaken for an opcode or byte offset.
    refs = bytearray([len(events)])
    for index, (when, event) in enumerate(events):
        refs.extend(struct.pack('<ffIII', when, -1., len(blob)//4, index, 0xffffffff))
        blob.extend(event)
    record = bytes(header) + bytes(8) + refs + b'\0'
    result = bytearray(struct.pack('<I', 2 if duplicate else 1) + record * (2 if duplicate else 1) + bytes(12))
    for table in ((), (clip.removeprefix('character/motion/'),), (), (), (), (),
                  ('ExplicitParent', 'ExplicitChild'), (PART, 'OtherPart'), (), ()):
        result.extend(struct.pack('<H', len(table)))
        for value in table:
            raw = value.encode() + b'\0'; result.extend(bytes([len(raw)]) + raw)
    result.extend(bytes(18 + 2))
    result.extend(struct.pack('<10H', int(condition_tables), *([0]*9)))
    result.extend(bytes(10 + 4 + 4 + 12 + 2 + 4 + 4 + 1))
    result.extend(struct.pack('<I', len(blob)) + blob + b'\0')
    return bytes(result)


def descriptor():
    return SimpleNamespace(in_socket='Back', in_child_socket='BackChild',
                           out_socket='Hand', out_child_socket='Grip')


def test_decoded_timing_and_dword_offsets_drive_exact_seek_and_reset():
    data = chart_bytes(((.625, payload()), (1.5, payload(mode=0))))
    chart = decode(data, path='test.paac')
    timeline = resolve((chart,), CLIP, PART, 2.)
    assert timeline.supported and timeline.events[0].seconds == .625
    assert len(chart.sha256) == 64 and chart.actions[0].clip == CLIP
    for seconds, expected in ((0., 'Back'), (.624, 'Back'), (.625, 'Hand'),
                              (1.49, 'Hand'), (2., 'Back'), (.8, 'Hand'), (0., 'Back')):
        assert timeline.at(seconds, 2., descriptor())[0] == expected
    assert timeline.at(0., 2., descriptor(), initial_held=True) == ('Hand', 'Grip')
    assert data == chart_bytes(((.625, payload()), (1.5, payload(mode=0))))


def test_part_filter_all_parts_and_explicit_socket_mode():
    chart = decode(chart_bytes(((0., payload(mode=0, part=0xffff, all_parts=1)),
                                (.4, payload(part=1)), (.8, payload(mode=2, parent=0, child=1)))))
    timeline = resolve((chart,), CLIP, PART, 2.)
    assert timeline.supported and len(timeline.events) == 2
    assert timeline.at(.6, 2., descriptor(), initial_held=True)[0] == 'Back'
    assert timeline.at(1., 2., descriptor()) == ('ExplicitParent', 'ExplicitChild')


@pytest.mark.parametrize('event,reason', [(payload(condition=1), 'conditions'),
    (payload(blend=.2), 'interpolation'), (payload(part=0xffff), 'Equipment-slot')])
def test_unsupported_event_behaviour_stays_inspectable_and_uses_manual_state(event, reason):
    timeline = resolve((decode(chart_bytes(((.1, event),))),), CLIP, PART, 2.)
    assert not timeline.supported and timeline.events
    assert any(reason in note for note in timeline.limitations)
    assert timeline.at(1., 2., descriptor())[0] == 'Back'


def test_duplicate_actions_agree_but_different_or_absent_timelines_do_not():
    chart = decode(chart_bytes(duplicate=True))
    assert resolve((chart,), CLIP, PART, 2.).supported
    conflict = decode(chart_bytes(((.9, payload()),)), path='other.paac')
    empty = decode(chart_bytes(()))
    for other in (conflict, empty):
        timeline = resolve((chart, other), CLIP, PART, 2.)
        assert not timeline.supported and any('disagree' in n for n in timeline.limitations)
    assert not resolve((chart,), CLIP, PART, .3).supported


def test_truncations_trailing_bytes_indices_and_unknown_variable_sections_fail():
    good = chart_bytes()
    for end in range(len(good)):
        with pytest.raises(ChartError): decode(good[:end])
    with pytest.raises(ChartError, match='Unconsumed'): decode(good+b'\0')
    with pytest.raises(ChartError, match='condition tables'): decode(chart_bytes(condition_tables=True))
    with pytest.raises(ChartError, match='out of range'): decode(chart_bytes(((.1, payload(part=4)),)))
    broken = bytearray(good); struct.pack_into('<I', broken, 4+156+8+1+8, 0xffffffff)
    with pytest.raises(ChartError, match='offset'): decode(broken)
    with pytest.raises(RuntimeError, match='cancelled'): decode(good, cancelled=lambda: True)


def test_relationships_expose_actions_and_snapshot_chart_edits_are_isolated():
    from tools.paa_motion.format import MotionClip
    chart_path = 'actionchart/bin__/test.paac'
    data = chart_bytes(); changed = chart_bytes(((1.25, payload()),))
    graph = from_files({chart_path:data}, paths=(CLIP,))
    assert any(r.kind == 'Decoded chart action' for r in graph.reverse[CLIP])
    clip = MotionClip((2,3),0,'',1,'',2.,0,1.,0,())
    unit = SimpleNamespace(primary_part=PART)
    session = SimpleNamespace(descriptor_part=lambda _: descriptor(),
        placed=lambda _: SimpleNamespace(socket=SimpleNamespace(parent_bone=''),anchored=True),
        weapon=SimpleNamespace(sockets={'BackChild':None,'Grip':None}))
    scene = SimpleNamespace(relationships=graph, preview_paths=(CLIP,), clips={CLIP:clip},after_clips={CLIP:clip},
        before=session,after=session, prepared=SimpleNamespace(plan=SimpleNamespace(unit=unit),
        before_files=((chart_path,changed),), after_files=((chart_path,data),)))
    prepare_timelines(scene)
    assert scene.timelines[0][CLIP].events[0].seconds == 1.25
    assert scene.timelines[1][CLIP].events[0].seconds == .625
    assert graph.charts[chart_path].actions[0].sockets[0].seconds == .625
    session.weapon.sockets.clear(); prepare_timelines(scene)
    assert not scene.timelines[1][CLIP].supported
