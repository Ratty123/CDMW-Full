"""Bounds-checked reader for the installed action-chart layout.

The grammar lives in `cdmw.core.action_chart_binary`, which follows the game's chart
loader (exe 1.0.0.3479, game 2.04.03). This module keeps the placement studio's
older tuple shape on top of it. The 2.04 update widened the per-action header to
0xA8 bytes with an eleventh array and moved the per-action condition arrays out, so
the layout this file used to carry stopped reading any shipped chart.
This is not the commonactioninfo layout. No writer is provided here.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from cdmw.core.action_chart_binary import ActionChartError, decode_action_chart

ChartError = ActionChartError


@dataclass(frozen=True, slots=True)
class TimedReference:
    begin: float
    end: float
    word_offset: int
    sequence: int
    condition: int


@dataclass(frozen=True, slots=True)
class ActionRecord:
    index: int
    duration: float
    clip_index: int
    blend_index: int
    events: tuple[TimedReference, ...]


def _timed(refs):
    result = []
    for ref in refs:
        if not math.isfinite(ref.begin) or not math.isfinite(ref.end):
            raise ChartError('Non-finite event time')
        result.append(TimedReference(ref.begin, ref.end, ref.dword_offset, ref.sequence, ref.condition))
    return tuple(result)


def read_layout(data, *, cancelled=lambda: False):
    if cancelled():
        raise RuntimeError('Chart inspection cancelled')
    data = bytes(data)
    chart = decode_action_chart(data)
    actions = []
    for animation in chart.animations:
        if not math.isfinite(animation.end_time) or animation.end_time < 0:
            raise ChartError('Invalid chart action duration')
        actions.append(ActionRecord(animation.index, animation.end_time, animation.clip_index,
                                    animation.blend_index, _timed(animation.events)))
    if cancelled():
        raise RuntimeError('Chart inspection cancelled')
    tables = tuple(table.values for table in chart.tables)
    event, key = chart.frame_event_buffer, chart.key_guide_event_buffer
    event_blob = data[event.offset:event.offset + event.size]
    initial_blob = data[key.offset:key.offset + key.size]
    return (tuple(actions), tables, event_blob, initial_blob,
            _timed(chart.key_guide_events), _timed(chart.child_events))
