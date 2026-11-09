"""When a draw or sheathe hands the weapon over, and when the hand actually gets there.

The hand-off between the carry socket and the hand is not part of the clip. It is a
`ModelAttachmentSocket` frame event on the chart animation that plays the clip: mode 0 stows,
mode 1 draws, and its `begin` counts the clip's own seconds (research reference, Section 7.5).
In the game's own clips the event fires as the hand reaches the weapon. Replace a draw, or
move the weapon somewhere else, and the event still fires at the old moment, so the weapon
pops onto the body or into the hand early or late.

This module lists those events for one equipment row, measures the gap between the weapon as
the hand holds it and the weapon as the body carries it over the stretch of clip the chart
plays, and proposes the frame where the two meet. Timing belongs to each chart animation, not
to the clip: one clip can be played by several animations with different events.

What is measured is authored frames on this character's rig with its current attach points:
not mesh contact, not engine IK, not speed windows. Nothing here builds a widget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from tools.paa_motion.format import FPS

from .carry import is_draw

FRAME = 1.0 / FPS

#: A clip whose held and carried weapon never come closer than this never reaches the
#: weapon; its event keeps its time. The shipped retimes accepted 0.20 m for swords and the
#: two-hand sword and 0.35 m for axes, whose grip sits 0.24 m from the sword's.
MAX_CONTACT_GAP = 0.35

#: An event already this close to the contact frame is on time.
ON_TIME = 0.05

STATUS_ON_TIME = "on_time"
STATUS_EARLY = "early"
STATUS_LATE = "late"
STATUS_UNREACHED = "unreached"
STATUS_UNMEASURED = "unmeasured"

STATUS_LABELS: Dict[str, str] = {
    STATUS_ON_TIME: "On time",
    STATUS_EARLY: "Swaps early",
    STATUS_LATE: "Swaps late",
    STATUS_UNREACHED: "Hand never reaches it",
    STATUS_UNMEASURED: "Not measured",
}

MODE_LABELS: Dict[int, str] = {0: "Put away", 1: "Draw"}


class TimingError(ValueError):
    """A chart or clip that cannot be read for timing."""


# ── the events ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SwapEvent:
    """One `ModelAttachmentSocket` event that hands one equipment row over."""

    chart: str
    #: Index of the chart animation, and of the frame event within that animation: the
    #: address `cdmw.core.action_chart_binary.ChartValueEdit` writes `event.begin` to.
    animation: int
    event: int
    clip: str
    part: str
    #: 0 stows the part on the body, 1 puts it in the hand.
    mode: int
    begin: float
    #: The stretch of clip the animation plays, in clip seconds.
    start: float
    end: float

    @property
    def key(self) -> str:
        return event_key(self.chart, self.animation, self.event)

    @property
    def clip_name(self) -> str:
        return self.clip.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    @property
    def chart_name(self) -> str:
        return self.chart.rsplit("/", 1)[-1]

    @property
    def action(self) -> str:
        return MODE_LABELS.get(self.mode, f"mode {self.mode}")


def event_key(chart: str, animation: int, event: int) -> str:
    """`<chart path>#<animation>:<event>`, the identity an operation's scope allows."""

    return f"{chart}#{int(animation)}:{int(event)}"


def parse_event_key(key: str) -> Tuple[str, int, int]:
    chart, _sep, address = key.rpartition("#")
    animation, _sep, event = address.partition(":")
    if not chart or not animation.isdigit() or not event.isdigit():
        raise TimingError(f"Not an event address: {key!r}")
    return chart, int(animation), int(event)


def swap_events(chart_path: str, data: bytes, parts: Iterable[str]) -> List[SwapEvent]:
    """Every draw or sheathe hand-off in one chart for the named equipment rows.

    Only animations whose clip is a draw or a sheathe are read. Skipped, because their timing
    cannot be judged from one row's sockets: events that name no part and pick an equipment
    slot instead (dual-wield draws), explicit socket pairs (mode 2), events with an interval,
    and disabled events.
    """

    from cdmw.core.action_chart_binary import (
        ANIMATION_TABLE,
        MODEL_ATTACHMENT_SOCKET_KIND,
        NO_INDEX,
        ActionChartError,
        decode_action_chart,
        frame_event_at,
        socket_event_payload,
    )
    from .relationships import resource_path

    wanted = set(parts)
    try:
        chart = decode_action_chart(data, virtual_path=chart_path)
    except (ActionChartError, ValueError, IndexError) as exc:
        raise TimingError(f"{chart_path}: {exc}") from exc
    if chart.frame_event_buffer is None or len(chart.tables) <= _PART_TABLE:
        return []
    out: List[SwapEvent] = []
    for animation in chart.animations:
        clip = chart.tables[ANIMATION_TABLE].value(animation.clip_index)
        if not clip or not is_draw(clip.rsplit("/", 1)[-1]):
            continue
        for position, ref in enumerate(animation.events):
            event = frame_event_at(chart, data, ref)
            if event.kind != MODEL_ATTACHMENT_SOCKET_KIND:
                continue
            payload = socket_event_payload(data, event)
            if payload.mode not in (0, 1) or payload.disabled or payload.part == NO_INDEX:
                continue
            if ref.end != -1 or ref.begin < 0:
                continue
            part = chart.tables[_PART_TABLE].value(payload.part)
            if part not in wanted:
                continue
            out.append(SwapEvent(chart_path, animation.index, position, resource_path(clip),
                                 part, payload.mode, float(ref.begin),
                                 float(animation.start_time), float(animation.end_time)))
    return out


#: The chart table that names equipment rows (`equipment types`); sockets are table 6.
_PART_TABLE = 7


# ── the gap ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GapCurve:
    """Distance between the held and the carried weapon, frame by frame over the clip."""

    clip: str
    part: str
    times: Tuple[float, ...]
    gaps: Tuple[float, ...]
    #: Why the measure is weaker than it looks, such as a missing child socket.
    limitations: Tuple[str, ...] = ()

    @property
    def duration(self) -> float:
        return self.times[-1] if self.times else 0.0

    def window(self, start: float, end: float) -> List[Tuple[float, float]]:
        return [(t, g) for t, g in zip(self.times, self.gaps)
                if start - 1e-6 <= t <= end + 1e-6]

    def at(self, seconds: float) -> Optional[float]:
        if not self.times:
            return None
        nearest = min(range(len(self.times)), key=lambda i: abs(self.times[i] - seconds))
        return self.gaps[nearest]

    def closest(self, start: float = 0.0, end: float = math.inf) -> Optional[Tuple[float, float]]:
        """`(time, gap)` where the two are nearest inside the window, earliest on a tie."""

        rows = self.window(start, end)
        if not rows:
            return None
        return min(rows, key=lambda row: (row[1], row[0]))


def gap_curve(session, clip, part, *, clip_path: str = "") -> GapCurve:
    """Pose `session` on every frame of `clip` and measure `part`'s hand-to-carry gap.

    The held weapon is `inverse(out child socket) * out socket * hand bone` and the carried
    one `inverse(in child socket) * in socket * its bone`, both from the session's selected
    weapon file. The session is left unposed.
    """

    from tools.paa_motion.format import MotionClip
    from tools.paa_motion.timing import timeline_end

    limitations: List[str] = []
    weapon = getattr(session, "weapon", None)
    child_sockets = getattr(weapon, "sockets", {}) if weapon is not None else {}
    for label, name in (("put-away", part.in_child_socket), ("held", part.out_child_socket)):
        if name and name not in child_sockets:
            limitations.append(f"The weapon file has no {name}, so the {label} weapon is "
                               f"measured from the attach point itself")
    if not part.in_socket or not part.out_socket:
        raise TimingError(f"{part.part_name} has no put-away or held attach point to measure")
    last = int(round(timeline_end(clip) if isinstance(clip, MotionClip)
                     else max(0, clip.frame_count - 1)))
    times: List[float] = []
    gaps: List[float] = []
    try:
        for frame in range(last + 1):
            session.apply_pose(clip, float(frame))
            stowed = session.attachment_point(part.in_socket, part.in_child_socket)
            held = session.attachment_point(part.out_socket, part.out_child_socket)
            if stowed is None or held is None:
                missing = part.in_socket if stowed is None else part.out_socket
                raise TimingError(f"This character has no {missing}")
            times.append(frame / FPS)
            gaps.append(math.dist((stowed.x, stowed.y, stowed.z), (held.x, held.y, held.z)))
    finally:
        session.clear_pose()
    return GapCurve(clip_path, part.part_name, tuple(times), tuple(gaps), tuple(limitations))


# ── the decision ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Retime:
    """One event, where the hand meets the weapon, and the time proposed for it."""

    event: SwapEvent
    status: str
    proposed: float
    contact: Optional[float] = None
    gap: Optional[float] = None
    gap_at_begin: Optional[float] = None
    #: Plain sentences: the animation ends before contact, a measure limitation, and so on.
    notes: Tuple[str, ...] = ()
    curve: Optional[GapCurve] = None

    @property
    def movable(self) -> bool:
        return self.status in (STATUS_EARLY, STATUS_LATE)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


def decide(event: SwapEvent, curve: Optional[GapCurve], *, problem: str = "") -> Retime:
    """Where this event should fire, by the rules the shipped retimes followed.

    The event goes to the frame inside the played stretch where the held and carried weapon
    meet best, and at least one frame before the animation ends. A clip that never brings
    them within `MAX_CONTACT_GAP` keeps its time, and so does an event already on time.
    """

    if curve is None or not curve.times:
        return Retime(event, STATUS_UNMEASURED, event.begin,
                      notes=(problem or "The clip could not be measured",), curve=curve)
    last = event.end - FRAME if event.end > event.start + FRAME else event.end
    played = curve.closest(event.start, min(event.end, curve.duration))
    if played is None:
        return Retime(event, STATUS_UNMEASURED, event.begin,
                      notes=("The chart plays none of this clip's frames",), curve=curve)
    contact, gap = played
    notes = list(curve.limitations)
    whole = curve.closest()
    if whole is not None and whole[0] > event.end + 1e-6 and whole[1] < gap - 0.02:
        notes.append(f"The hand is nearest at {whole[0]:.2f} s, after this animation ends at "
                     f"{event.end:.2f} s; a faster clip is needed to swap there")
    at_begin = curve.at(event.begin)
    if gap > MAX_CONTACT_GAP:
        notes.append(f"The held and put-away weapon never come closer than {gap:.2f} m")
        return Retime(event, STATUS_UNREACHED, event.begin, contact, gap, at_begin,
                      tuple(notes), curve)
    proposed = round(min(max(contact, event.start), last), 4)
    if abs(proposed - event.begin) < ON_TIME:
        status = STATUS_ON_TIME
        proposed = event.begin
    else:
        status = STATUS_LATE if event.begin > proposed else STATUS_EARLY
    return Retime(event, status, proposed, contact, gap, at_begin, tuple(notes), curve)


def survey(
    charts: Mapping[str, bytes],
    parts: Sequence[str],
    *,
    read_clip: Callable[[str], Optional[object]],
    measure: Callable[[str, object, str], GapCurve],
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[int, int], None] = lambda *_: None,
) -> Tuple[List[Retime], List[str]]:
    """Every hand-off of `parts` in `charts`, measured and decided.

    `read_clip(path)` returns a parsed clip or None, and `measure(path, clip, part)` its gap
    curve; both are passed in so the survey can be tested without a rig. Each clip and part
    is measured once, however many animations play it. Returns `(retimes, problems)`.
    """

    events: List[SwapEvent] = []
    problems: List[str] = []
    for path, data in sorted(charts.items()):
        try:
            events += swap_events(path, data, parts)
        except TimingError as exc:
            problems.append(str(exc))
    curves: Dict[Tuple[str, str], Tuple[Optional[GapCurve], str]] = {}
    out: List[Retime] = []
    for done, event in enumerate(events, start=1):
        if cancelled():
            raise TimingError("Timing measurement cancelled")
        key = (event.clip, event.part)
        if key not in curves:
            try:
                clip = read_clip(event.clip)
                curves[key] = ((measure(event.clip, clip, event.part), "") if clip is not None
                               else (None, f"{event.clip} is not in the indexed clips"))
            except Exception as exc:  # noqa: BLE001 - one unreadable clip leaves its rows unmeasured
                curves[key] = (None, f"{event.clip}: {exc}")
        curve, problem = curves[key]
        out.append(decide(event, curve, problem=problem))
        progress(done, len(events))
    out.sort(key=lambda row: (row.event.clip_name, row.event.chart, row.event.animation,
                              row.event.event))
    return out, problems
