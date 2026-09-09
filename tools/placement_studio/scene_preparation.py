"""Worker-owned preparation of isolated comparison scenes and dependencies."""
from __future__ import annotations

from dataclasses import dataclass

from tools.paa_motion.format import parse_paa
from tools.paa_motion.timing import duration_seconds, TimingError

from .prepared_move import PreparedMove, preview_session


@dataclass
class PreparedScene:
    prepared: PreparedMove
    before: object
    after: object
    clips: dict
    body: tuple = ()
    weapon: object = None
    notes: tuple = ()
    equipment: object = None
    relationships: object = None
    blendspaces: tuple = ()
    body_faces: tuple = ()
    after_clips: object = None
    preview_paths: tuple = ()
    candidates: tuple = ()
    timelines: tuple = ()
    binding_issue: str = ''


def build_scene(source, prepared, *, body=(), read_asset=None, cancelled=lambda: False, relationships=None):
    from .meshes import weapon_mesh_paths, load_mesh
    before = preview_session(source, prepared.before_files, prepared.plan.unit)
    after = preview_session(source, prepared.after_files, prepared.plan.unit)
    clips = {}
    notes = []
    files = dict(prepared.before_files)
    paths = {r.target_path for r in prepared.plan.request.replacements}
    for path in paths:
        if cancelled():
            raise RuntimeError("Preview preparation cancelled")
        if path in files:
            try:
                clip = parse_paa(files[path], name=path)
                duration_seconds(clip)
                clips[path] = clip
            except (ValueError, TimingError) as error:
                notes.append(f"Unverified preview: {path}: {error}")
    after_clips = dict(clips)
    for file in prepared.files:
        if file.donor_path:
            try:
                clip = parse_paa(file.data, name=file.donor_path)
                duration_seconds(clip)
                after_clips[file.path] = clip
            except (ValueError, TimingError) as error:
                after_clips.pop(file.path, None)
                notes.append(f"Unverified After preview: {file.path}: {error}")
    weapon = None
    binding = None
    binding_issue = ''
    weapon_path = ""
    if read_asset is not None:
        for path in ([prepared.plan.unit.mesh_path] if prepared.plan.unit.mesh_path else weapon_mesh_paths(prepared.plan.unit.weapon_id, source.model)):
            if cancelled():
                raise RuntimeError("Preview preparation cancelled")
            try:
                data = read_asset(path)
                if data:
                    weapon = load_mesh(data, source_path=path)
                    weapon_path = path
                    try:
                        from .attachment_binding import decode_binding
                        binding = decode_binding(data, path)
                        notes.append(f"Attachment bind reconstruction: Passed ({binding.skeleton.bone_count} bones)")
                    except ValueError as error:
                        binding_issue = str(error)
                        notes.append(f"Attachment deformation: Unverified — {error}")
                    break
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                notes.append(f"Weapon geometry: {error}")
    if weapon is None:
        notes.append("Weapon geometry unavailable; socket positions remain visible")
    if not body or any(not m.binding_exact or not m.influences_exact for m in body):
        notes.append("Contact: Unverified — body geometry or skinning is approximate")
    import numpy as np
    faces, base = [], 0
    for mesh in body:
        faces.extend(map(tuple, (mesh.faces.astype(np.int64, copy=False) + base).tolist()))
        base += mesh.vertex_count
    scene = PreparedScene(prepared, before, after, clips, tuple(body), weapon, tuple(notes),
                          relationships=relationships, body_faces=tuple(faces), after_clips=after_clips,
                          binding_issue=binding_issue)
    scene.equipment = (binding, weapon_path, {})
    if relationships:
        if not paths:
            from fnmatch import fnmatchcase
            from .clips import ClipEntry, rig_of
            from .carry import family_of, is_draw
            def gameplay(path):
                clip = ClipEntry(path, rig_of(path), '', '/motion_lod__/' in path)
                return (clip.rig == f'1_pc/{source.model}' and not
                        (clip.is_lod or clip.facial or clip.equipment or clip.additive or clip.story))
            mapping_paths = {target for pattern,target in relationships.matches if fnmatchcase(weapon_path, pattern)}
            if len(mapping_paths) == 1:
                mapping = relationships.sets.get(next(iter(mapping_paths)))
                if mapping:
                    paths.update(p for p,_ in mapping.mappings if p.endswith('.paa') and gameplay(p))
                    for p,_ in mapping.mappings:
                        space = relationships.spaces.get(p)
                        if space and all(gameplay(c) for c in space.clips):
                            paths.update(space.clips)
            # Draw/stow clips often use an animation set's suffix/default, so an
            # explicit-only input list omits the very handoffs being inspected.
            families = set(prepared.plan.unit.target_animation_families)
            paths.update(p for p in relationships.paths if p.endswith('.paa') and gameplay(p)
                         and is_draw(p.rsplit('/',1)[-1]) and family_of(p.rsplit('/',1)[-1]) in families)
            # Shields and bows do not belong to the sword swap families. Their
            # decoded part events provide an explicit association with handoffs.
            paths.update(action.clip for chart in relationships.charts.values() for action in chart.actions
                         if action.clip and gameplay(action.clip) and
                         any(event.part == prepared.plan.unit.primary_part for event in action.sockets))
            if not paths:
                from .clips import classify
                prefix = 'cd_' + source.model.split('_',1)[-1] + '_'
                paths.update(p for p in relationships.paths if p.endswith('.paa') and gameplay(p)
                             and p.rsplit('/',1)[-1].startswith(prefix) and classify(p.rsplit('/',1)[-1]) == 'guard')
                if paths:
                    notes.append("Manual rig inspection: guard animations; association with this equipment is Unverified")
        scene.blendspaces = tuple(s for s in relationships.spaces.values() if paths.intersection(s.clips))
        # Keep preparation self-contained: dependent clip reads also finish on the worker.
        dependent = set(p for space in scene.blendspaces for p in space.clips) | paths
        # Mapped attachment blendspaces use the same named parameter values and clock.
        equipment_spaces = []
        for space in scene.blendspaces:
            mapped, reason = relationships.attachment(weapon_path, space.path)
            if mapped in relationships.spaces:
                equipment_spaces.append(relationships.spaces[mapped])
                scene.equipment[2][space.path] = (mapped, reason)
        dependent.update(p for s in equipment_spaces for p in s.clips)
        for path in paths | dependent:
            mapped, reason = relationships.attachment(weapon_path, path)
            if mapped:
                scene.equipment[2][path] = (mapped, reason)
                if mapped.endswith('.paa'):
                    dependent.add(mapped)
        for path in dependent:
            if path in clips:
                continue
            if cancelled():
                raise RuntimeError("Preview preparation cancelled")
            entry = relationships.entries.get(path)
            if entry is not None:
                try:
                    from .armour import read_entry
                    payload = files.get(path)
                    if payload is None:
                        payload = read_asset(path) if read_asset else read_entry(entry)
                    clip = parse_paa(payload, name=path)
                    duration_seconds(clip)
                    clips[path] = clip
                    after_clips.setdefault(path, clip)
                except (OSError, ValueError, RuntimeError) as error:
                    notes.append(f"Unverified blend dependency: {path}: {error}")
        scene.notes = tuple(notes)
    from .attachment_binding import complete_scene_binding
    complete_scene_binding(scene, read_asset, cancelled=cancelled)
    from .carry import is_draw
    scene.preview_paths = tuple(r.target_path for r in prepared.plan.request.replacements) or tuple(
        sorted(paths, key=lambda p: (not is_draw(p.rsplit('/', 1)[-1]), p)))
    from .event_timeline import prepare_timelines
    prepare_timelines(scene, cancelled=cancelled)
    return scene
