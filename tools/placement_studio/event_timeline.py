"""Part-specific chart timelines for immutable Before/After preview snapshots."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .paac_events import SocketEvent, decode


@dataclass(frozen=True, slots=True)
class Timeline:
    events: tuple[SocketEvent, ...] = ()
    sources: tuple[tuple[str, str, int], ...] = ()
    limitations: tuple[str, ...] = ()

    @property
    def supported(self):
        return bool(self.events) and not self.limitations

    def at(self, seconds, duration, descriptor, *, initial_held=False):
        """Pure seek: replay from the explicit initial state, never the last render.

        The viewport owns looping. A time at the duration boundary must retain the
        final event until that common clock loops; no independent attachment clock.
        """
        if not math.isfinite(seconds) or not math.isfinite(duration) or duration < 0:
            raise ValueError('Invalid event playback clock')
        initial = ((descriptor.out_socket, descriptor.out_child_socket) if initial_held else
                   (descriptor.in_socket, descriptor.in_child_socket))
        if not self.supported:
            return initial
        state = initial
        for event in self.events:
            if event.seconds > min(max(0., seconds), duration) + 1e-7:
                break
            state = event.state(descriptor)
        return state


def resolve(charts, clip, part, duration, *, missing=()):
    candidates, sources, notes = [], [], list(missing)
    for chart in charts:
        for action in chart.actions:
            if action.clip != clip:
                continue
            sources.append((chart.path, chart.sha256, action.index))
            notes.extend(chart.limitations)
            events = tuple(replace(event, sequence=i) for i, event in enumerate(
                e for e in action.sockets if e.part == part or e.all_parts or not e.part))
            candidates.append(events)
            for event in events:
                notes.extend(event.limitations)
                if event.seconds > duration + 1e-5:
                    notes.append('An attachment event lies beyond this clip duration')
            if action.blendspace:
                notes.append('Attachment events on a chart blendspace are not simulated')
            if {24, 27, 54, 106, 168}.intersection(action.other_types):
                notes.append('This action also changes equipment or docking through unsupported events')
    if not candidates:
        notes.append('No decoded action timeline references this clip')
    elif any(candidate != candidates[0] for candidate in candidates[1:]):
        notes.append('Chart actions disagree on this part\'s attachment timeline')
    elif not candidates[0]:
        notes.append('No attachment events address this part')
    return Timeline(candidates[0] if candidates else (), tuple(sources), tuple(dict.fromkeys(notes)))


def prepare_timelines(scene, *, cancelled=lambda: False):
    """Overlay earlier/current chart edits without mutating installed relationships.

    Animation donors do not bring their charts with them. Both comparisons resolve
    events for the target resource, then independently check its current duration.
    """
    from tools.paa_motion.timing import duration_seconds
    graph = scene.relationships
    result = []
    for snapshot, clips, session in ((scene.prepared.before_files, scene.clips, scene.before),
                                     (scene.prepared.after_files, scene.after_clips, scene.after)):
        charts = dict(graph.charts) if graph else {}
        failures = {}
        for path, payload in snapshot:
            if not path.endswith('.paac'):
                continue
            if cancelled():
                raise RuntimeError('Chart inspection cancelled')
            try:
                charts[path] = decode(payload, path=path, cancelled=cancelled)
            except ValueError as error:
                charts.pop(path, None)
                failures[path] = str(error)
        timelines = {}
        for path in scene.preview_paths:
            if cancelled():
                raise RuntimeError('Chart inspection cancelled')
            missing = []
            for ref in graph.reverse.get(path, ()) if graph else ():
                if ref.source.endswith('.paac') and ref.source not in charts:
                    missing.append(f'Chart events unavailable: {ref.source}: {failures.get(ref.source, "layout unsupported")}')
            duration = duration_seconds(clips[path]) if path in clips else 0.
            timeline = resolve(charts.values(), path, scene.prepared.plan.unit.primary_part, duration, missing=missing)
            descriptor = session.descriptor_part(scene.prepared.plan.unit.primary_part)
            unresolved = []
            for event in timeline.events:
                parent, child = event.state(descriptor) if descriptor else ('', '')
                placed = session.placed(parent)
                child_exists = not child or (session.weapon and child in session.weapon.sockets)
                if (placed is None or not child_exists or
                        (placed.socket.parent_bone and not placed.anchored)):
                    unresolved.append('An event socket frame is unavailable in this preview state')
            if unresolved:
                timeline = replace(timeline, limitations=tuple(dict.fromkeys((*timeline.limitations, *unresolved))))
            timelines[path] = timeline
        result.append(timelines)
    scene.timelines = tuple(result)


def checks_for_scene(scene):
    from .prepared_move import Check
    for label, timelines in zip(('Before', 'After'), scene.timelines):
        for path, timeline in timelines.items():
            sources = '; '.join(f'{chart} action {index}; SHA-256 {sha}' for chart, sha, index in timeline.sources)
            events = '; '.join(f'{e.seconds:.3f} s: {e.part or "all parts"} → ' +
                (('Stowed', 'Held')[e.mode] if e.mode < 2 else f'{e.parent} / {e.child}') for e in timeline.events)
            detail = f'{label}: {events or "no resolved handoff"}. ' + '; '.join(timeline.limitations)
            detail += f' Sources: {sources or "none"}. Initial state is selected manually; runtime action selection is not simulated.'
            yield Check('Attachment events', 'Passed' if timeline.supported else 'Unverified', detail, path)
