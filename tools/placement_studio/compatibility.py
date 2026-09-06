"""Destination-aware measurements with explicit limits on what they prove."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from tools.paa_motion.format import FPS
from tools.paa_motion.timing import duration_seconds

from .prepared_move import Check


@dataclass(frozen=True)
class Fit:
    destination: str
    nearest_grip: float | None
    orientation_degrees: float | None
    sample_seconds: float | None
    duration: float
    hand: str
    contact_state: str = 'Unverified'


def proportion_difference(target, donor):
    """Actual local offsets remain distinguishable even when all hashes match."""
    other = {b.name_hash: b for b in donor.bones}
    differences = []
    for bone in target.bones:
        match = other.get(bone.name_hash)
        if match:
            differences.append(math.dist(bone.position, match.position))
    return len(differences), max(differences, default=0.), sum(differences) / max(1, len(differences))


def measure_fit(session, clip, unit, *, cancelled=lambda: False, samples=17):
    """Distance between the declared held grip frame and its stowed frame.

    Measures authored frames, not mesh contact or engine IK. Uniform sampling is
    an estimate of minimum distance; event timing and contact remain Unverified.
    """
    import numpy as np
    from .skeleton import matrix_from, multiply
    part = session.descriptor_part(unit.primary_part)
    duration = duration_seconds(clip)
    if part is None or not session.has_skeleton:
        return Fit('', None, None, None, duration, '')
    child = session._weapon.sockets.get(part.out_child_socket) if session._weapon else None
    best = None
    for index in range(samples):
        if cancelled():
            raise RuntimeError('Compatibility analysis cancelled')
        when = duration * index / max(1, samples - 1)
        session.apply_pose(clip, when * FPS)
        stowed = session.attachment_matrix(part.in_socket, part.in_child_socket)
        held = session.placed(part.out_socket)
        if stowed is None or held is None or child is None:
            continue
        grip = multiply(matrix_from(child.rotation, child.translation), stowed)
        distance = math.dist(grip[12:15], held.world_matrix[12:15])
        a, b = np.array(grip).reshape(4,4)[:3,:3], np.array(held.world_matrix).reshape(4,4)[:3,:3]
        a = a / np.linalg.norm(a,axis=1)[:,None]
        b = b / np.linalg.norm(b,axis=1)[:,None]
        angle = math.degrees(math.acos(max(-1.,min(1.,float((np.trace(a @ b.T)-1)/2)))))
        if best is None or distance < best[0]:
            best = distance, angle, when
    session.clear_pose()
    return Fit(part.in_socket, *(best if best else (None,None,None)), duration, part.out_socket)


def assess_scene(scene, *, cancelled=lambda: False, read_asset=None):
    from .playback import coverage, travel_extent
    prepared = scene.prepared
    files = {f.path:f for f in prepared.files}
    checks = []
    event_checks = ()
    if getattr(scene, 'timelines', ()):
        from .event_timeline import checks_for_scene
        event_checks = tuple(checks_for_scene(scene))
        checks.extend(event_checks)
    skeletons = {}
    if read_asset is not None and scene.relationships is not None:
        from cdmw.modding.skeleton_parser import parse_pab
        from .clips import rig_of
        from .relationships import resource_path
        for row in prepared.plan.request.replacements:
            rig = rig_of(row.donor.path)
            key = row.donor.path
            if key in skeletons:
                continue
            clip = scene.after_clips.get(row.target_path)
            declared = resource_path(clip.skeleton_path) if clip and clip.skeleton_path else ''
            candidates = [declared] if declared else [p for p in scene.relationships.paths if p.startswith('character/model/' + rig + '/') and p.endswith('.pab')]
            if len(candidates) == 1:
                try:
                    skeletons[key] = (candidates[0], parse_pab(read_asset(candidates[0])))
                except (ValueError, OSError, KeyError):
                    skeletons[key] = None
            else:
                skeletons[key] = None
        from .equipment_rules import SHRINK_PATH, RETARGET_PATH, shrink_rules, alignment_bones
        try:
            rules = shrink_rules(read_asset(SHRINK_PATH))
            part = scene.after.descriptor_part(prepared.plan.unit.primary_part)
            for state, socket in (('Stowed', part.in_socket), ('Held', part.out_socket)) if part else ():
                tag, bias, custom, receivers = rules.setting(prepared.plan.unit.shrink_tag, socket)
                bias_text = f'{bias:g} m' if bias is not None else 'unresolved'
                checks.append(Check('Part-shrink settings', 'Unverified',
                    f'{state}: {socket} → {tag or "unresolved tag"}; stored bias {bias_text}, custom volume {custom}; receivers: {", ".join(receivers) or "none"}. '
                    'Conditional bone weights and custom volumes are not simulated; this is not a clearance guarantee', SHRINK_PATH))
        except (ValueError, OSError, KeyError) as error:
            checks.append(Check('Part-shrink settings', 'Unverified', str(error), SHRINK_PATH))
        try:
            names = alignment_bones(read_asset(RETARGET_PATH))
            have = {b.name for b in scene.after.hierarchy.parsed.bones} if scene.after.has_skeleton else set()
            checks.append(Check('Retarget alignment', 'Unverified',
                f'{len(set(names) & have)}/{len(names)} explicit alignment bones resolve; engine alignment is not applied to copied payloads', RETARGET_PATH))
        except (ValueError, OSError, KeyError) as error:
            checks.append(Check('Retarget alignment', 'Unverified', str(error), RETARGET_PATH))
    for row in prepared.plan.request.replacements:
        if cancelled():
            raise RuntimeError('Compatibility analysis cancelled')
        before, after = scene.clips.get(row.target_path), scene.after_clips.get(row.target_path)
        current = []
        if after is None or not scene.after.has_skeleton:
            current.append(Check('Movement compatibility','Unverified','A clip or parsed character skeleton is unavailable',row.target_path))
        else:
            match = coverage(scene.after.hierarchy,after)
            current.append(Check('Bone mapping','Passed' if match == 1 else 'Warning',
                                 f'{match:.1%} of animated track hashes resolve; this does not establish movement suitability',row.target_path))
            if before is not None:
                delta = duration_seconds(after) - duration_seconds(before)
                travel = travel_extent(after) - travel_extent(before)
                current.append(Check('Motion differences','Warning' if abs(delta)>1e-4 or abs(travel)>1e-4 else 'Passed',
                                     f'Duration {delta:+.3f} s; root-travel extent {travel:+.3f} m',row.target_path))
                if abs(after.unit_scale-before.unit_scale) > 1e-5:
                    current.append(Check('Animation scale metadata','Unverified',
                        f'Stored rig unit scale {before.unit_scale:g} → {after.unit_scale:g}; engine adjustment is not simulated', row.target_path))
            # Draw/stow fits are useful; an attack's closest incidental pass is not a draw.
            from .carry import is_draw
            if is_draw(row.target.name):
                fit = measure_fit(scene.after, after, prepared.plan.unit, cancelled=cancelled)
                if fit.nearest_grip is not None:
                    detail = (f'{fit.destination} → {fit.hand}: sampled grip gap {fit.nearest_grip:.3f} m, '
                              f'orientation {fit.orientation_degrees:.1f}°, at {fit.sample_seconds:.3f} s; '
                              'declared socket frames; contact and event timing not simulated')
                else:
                    detail = 'A declared held grip or socket frame is unavailable'
                current.append(Check('Destination fit','Unverified',detail,row.target_path))
            donor_skeleton = skeletons.get(row.donor.path)
            if donor_skeleton:
                path, skeleton = donor_skeleton
                count, maximum, mean = proportion_difference(scene.after.hierarchy.parsed, skeleton)
                current.append(Check('Character proportions', 'Warning' if maximum > .001 else 'Passed',
                    f'{count} matching bones; local offset difference max {maximum:.4f} m, mean {mean:.4f} m against {path}; '
                    'bind geometry measurement, not movement validation', row.target_path))
            else:
                current.append(Check('Character proportions','Unverified','No unique installed donor skeleton; matching hashes do not validate limb lengths or retarget alignment',row.target_path))
        current.append(Check('Clearance','Unverified',
                             'Body skinning, attachment contact and engine part-shrink behavior are not fully simulated',row.target_path))
        original=files.get(row.target_path)
        if original:
            files[row.target_path]=replace(original,checks=original.checks+tuple(current)+
                                          tuple(c for c in event_checks if c.path == row.target_path))
        checks.extend(current)
    if scene.equipment and scene.equipment[0]:
        binding=scene.equipment[0]
        checks.append(Check('Attachment binding','Passed',
                            f'Embedded hierarchy and palette reconstructed; maximum bind error {binding.bind_error:.3g}'))
        for track in binding.unused_tracks:
            checks.append(Check('Attachment track','Passed',
                f'{track.name} (0x{track.name_hash:08x}) is an optional leaf absent from this mesh; '
                f'no target bone descends from it. Witness: {track.source}; SHA-256 {track.sha256}',
                scene.equipment[1]))
    elif getattr(scene, 'binding_issue', ''):
        checks.append(Check('Attachment binding', 'Unverified', scene.binding_issue, scene.equipment[1]))
    return replace(prepared,files=tuple(files[f.path] for f in prepared.files),checks=prepared.checks+tuple(checks))
