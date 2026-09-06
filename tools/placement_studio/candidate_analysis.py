"""Donor measurements against one proposed destination, run on the preparation worker."""
from dataclasses import dataclass
import math

from tools.paa_motion.format import parse_paa
from tools.paa_motion.timing import duration_seconds
from .carry import clip_motion, family_of, is_draw
from .compatibility import measure_fit
from .playback import coverage, travel_extent


@dataclass(frozen=True)
class Candidate:
    target: str
    donor: str
    rank: tuple
    detail: str


def analyse_candidates(scene, *, read, cancelled=lambda: False, progress=lambda *_: None):
    """Read each donor once; retain measurements rather than decompressed payloads.

    The single worker bounds concurrency and cancels between files and samples.
    Recommendations never silently change a manual selection.
    """
    rows = scene.prepared.plan.request.replacements
    entries = {e.path:e for r in rows for e in (r.options or (r.donor,))}
    measured = {}
    for i,(path,entry) in enumerate(entries.items()):
        if cancelled():
            raise RuntimeError('Donor analysis cancelled')
        try:
            clip = parse_paa(read(entry), name=path)
            duration = duration_seconds(clip)
            match = coverage(scene.after.hierarchy,clip) if scene.after.has_skeleton else 0.
            fit = measure_fit(scene.after,clip,scene.prepared.plan.unit,cancelled=cancelled) if is_draw(entry.name) else None
            gap = fit.nearest_grip if fit is not None and fit.nearest_grip is not None else math.inf
            orientation = fit.orientation_degrees if fit is not None and fit.orientation_degrees is not None else math.inf
            measured[path] = (0, 1-match, gap, orientation, duration, travel_extent(clip), '')
        except (ValueError, OSError, KeyError, RuntimeError) as error:
            if cancelled():
                raise RuntimeError('Donor analysis cancelled') from error
            measured[path] = (1,1.,math.inf,math.inf,0.,0.,str(error))
        progress(i+1,len(entries))
    out=[]
    for row in rows:
        for entry in row.options or (row.donor,):
            invalid,missing,gap,angle,duration,travel,error = measured[entry.path]
            action = int(clip_motion(row.target.name) != clip_motion(entry.name))
            role = int(family_of(entry.name) not in scene.prepared.plan.unit.donor_animation_families)
            rank = (invalid,missing,action,role,gap,angle,entry.path)
            fit_text = f'grip gap {gap:.3f} m, orientation {angle:.1f} degrees' if math.isfinite(gap) else 'destination fit unavailable'
            detail = error or (f'Bone coverage {1-missing:.1%}; action {"matches" if not action else "differs"}; '
                f'donor family {family_of(entry.name)}; {fit_text}; duration {duration:.3f} s, root travel {travel:.3f} m. '
                'Sampled socket fit; contact and engine retargeting Unverified.')
            out.append(Candidate(row.target_path,entry.path,rank,detail))
    return tuple(out)
