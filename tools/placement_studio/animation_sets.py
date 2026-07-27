"""Which animations belong to a placement.

Move a sword from the hip to the back and the draw has to change with it — the arm reaches
somewhere else. The link is already in the shipped data: an action chart names both the
socket it routes through *and* the motion clips it plays, all as the same length-prefixed
strings. So "what animates through this socket" is a lookup, not a guess.

That makes the placement -> animation question answerable in the direction the user asks it:
pick the socket a weapon hangs on, and get exactly the clips that reference it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import re

from .paac import index_strings, is_length_prefixed

#: Socket names all end this way, which is what separates them from other chart strings.
SOCKET_SUFFIX = "Socket"

# A chart names a clip by its full resource path, not by the bare `cd_...` stem, so the
# token pattern the socket indexer uses cannot see them — it stops at the first slash.
_PATH_BYTE = re.compile(rb"[A-Za-z0-9_/.\-]")
_SUFFIX = b".paa"
_MAX_PATH = 250


def chart_clips(data: bytes) -> Tuple[str, ...]:
    """Every motion clip an action chart names, as the clip stem.

    Anchored on the suffix and walked backwards rather than matched forwards: the length
    prefix is a raw byte that is frequently itself a path character — `/` is 0x2F, so a
    47-character path puts a literal slash in front of its own start — and a forward regex
    swallows it, which makes the length check fail on every well-formed reference.
    """

    seen: Dict[str, None] = {}
    position = data.find(_SUFFIX)
    while position != -1:
        end = position + len(_SUFFIX)
        start = position
        limit = max(0, position - _MAX_PATH)
        while start > limit and _PATH_BYTE.match(data[start - 1: start]):
            start -= 1
        # Several starts can look like a path; only one satisfies the length prefix.
        for candidate in range(start, position):
            if is_length_prefixed(data, candidate, end - candidate):
                text = data[candidate:end].decode("ascii", "replace")
                seen.setdefault(text.rsplit("/", 1)[-1][: -len(".paa")], None)
                break
        position = data.find(_SUFFIX, end)
    return tuple(seen)


def chart_clip_paths(data: bytes) -> Tuple[str, ...]:
    """The same references as `chart_clips`, but whole paths rather than stems.

    A swap has to be written against what the file actually stores, and what it stores is the
    full resource path inside a length prefix. The stem is only ever for display.
    """

    seen: Dict[str, None] = {}
    position = data.find(_SUFFIX)
    while position != -1:
        end = position + len(_SUFFIX)
        start = position
        limit = max(0, position - _MAX_PATH)
        while start > limit and _PATH_BYTE.match(data[start - 1: start]):
            start -= 1
        for candidate in range(start, position):
            if is_length_prefixed(data, candidate, end - candidate):
                seen.setdefault(data[candidate:end].decode("ascii", "replace"), None)
                break
        position = data.find(_SUFFIX, end)
    return tuple(seen)


def chart_sockets(data: bytes) -> Tuple[str, ...]:
    seen: Dict[str, None] = {}
    for item in index_strings(data):
        if item.value.endswith(SOCKET_SUFFIX):
            seen.setdefault(item.value, None)
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class ChartLink:
    """One action chart, and what it ties together."""

    path: str
    sockets: Tuple[str, ...] = field(default=())
    clips: Tuple[str, ...] = field(default=())


def read_chart(path: str, data: bytes) -> ChartLink:
    return ChartLink(path=path, sockets=chart_sockets(data), clips=chart_clips(data))


class AnimationSetIndex:
    """Socket -> the clips that play through it, across every chart loaded."""

    __slots__ = ("_charts",)

    def __init__(self, charts: Iterable[ChartLink] = ()) -> None:
        self._charts: Tuple[ChartLink, ...] = tuple(charts)

    @classmethod
    def from_files(cls, files: Mapping[str, bytes]) -> "AnimationSetIndex":
        return cls(read_chart(path, data) for path, data in files.items() if data)

    def __len__(self) -> int:
        return len(self._charts)

    @property
    def charts(self) -> Tuple[ChartLink, ...]:
        return self._charts

    def sockets(self) -> List[str]:
        found = {socket for chart in self._charts for socket in chart.sockets}
        return sorted(found)

    def clips_for_socket(self, socket: str) -> List[str]:
        """Clips named by any chart that also names this socket.

        A chart is the unit of association: it is what binds a socket to the actions played
        while an item sits there. Narrowing further would need the chart's own opcode graph,
        which is not decoded — so this is deliberately "clips in charts that use this
        socket", not "clips proven to move this socket".
        """

        found: Dict[str, None] = {}
        for chart in self._charts:
            if socket in chart.sockets:
                for clip in chart.clips:
                    found.setdefault(clip, None)
        return sorted(found)

    def charts_for_socket(self, socket: str) -> List[str]:
        return sorted(chart.path for chart in self._charts if socket in chart.sockets)

    def sockets_for_clip(self, clip: str) -> List[str]:
        found = {
            socket
            for chart in self._charts
            if clip in chart.clips
            for socket in chart.sockets
        }
        return sorted(found)

    def counterpart_clips(self, socket: str, replacement: str) -> Tuple[List[str], List[str]]:
        """Clips that would be left behind, and picked up, by a retarget.

        Answers the question a placement move actually raises: the sword now hangs
        somewhere else, so which animations stop applying and which ones should take over.
        """

        return self.clips_for_socket(socket), self.clips_for_socket(replacement)


def summarise(socket: str, clips: Sequence[str], charts: Sequence[str]) -> str:
    if not socket:
        return "Select a socket to see the animations routed through it"
    if not clips:
        return f"{socket}: no chart names a clip alongside it"
    return f"{socket}: {len(clips)} clip(s) across {len(charts)} chart(s)"
