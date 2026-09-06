"""Complete, immutable replacement preparation shared by review, preview and apply.

Only reads input assets. Publication remains a single existing EditSession operation;
package evidence describes its isolated payload, while A/B retains earlier scene edits.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
from typing import Callable

from tools.paa_motion.format import parse_paa
from tools.paa_motion.timing import TimingError, validate_timing

from .move_operation import MoveBlocked, MovePlan, apply_move


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    path: str = ""

    def as_dict(self):
        return dict(name=self.name, status=self.status, detail=self.detail, path=self.path)


@dataclass(frozen=True)
class EditSnapshot:
    base: tuple
    originals: tuple
    commands: tuple
    records: tuple


@dataclass(frozen=True)
class PreparedFile:
    path: str
    data: bytes
    before_hash: str
    donor_path: str = ""
    kind: str = "Placement"
    changed: bool = True
    checks: tuple[Check, ...] = ()

    def as_dict(self):
        return dict(target=self.path, donor=self.donor_path, sha256=digest(self.data),
                    before_sha256=self.before_hash, kind=self.kind, changed=self.changed,
                    checks=[check.as_dict() for check in self.checks])


@dataclass(frozen=True)
class PreparedMove:
    plan: MovePlan
    effective_plan: MovePlan
    snapshot: EditSnapshot
    files: tuple[PreparedFile, ...]
    originals: tuple
    before_files: tuple
    after_files: tuple
    checks: tuple[Check, ...]
    source_identity: tuple = ()
    shared_impact: tuple = ()
    source_root: str = ""
    root_identity: tuple = ()
    companion_decisions: tuple = ()

    @property
    def blocked(self) -> bool:
        return self.plan.blocked or any(c.status == "Blocked" for c in self.checks)

    @property
    def changed_files(self):
        return tuple(f for f in self.files if f.changed)

    def evidence(self):
        return dict(version=1, files=[f.as_dict() for f in self.files],
                    checks=[c.as_dict() for c in self.checks],
                    source_identity=self.source_identity, shared_impact=self.shared_impact,
                    source_root=self.source_root, archive_identity=self.root_identity,
                    companion_decisions=self.companion_decisions,
                    equipment=dict(unit_id=self.plan.unit.unit_id, mesh=self.plan.unit.mesh_path,
                                   prefab=self.plan.unit.prefab_path, socket_template=self.plan.unit.weapon_path),
                    in_game="Unverified")

    def apply(self, session, edits):
        if self.blocked:
            raise MoveBlocked("; ".join(self.plan.blockers) or "Preparation has blocked checks")
        if edits.capture() != self.snapshot:
            raise MoveBlocked("The session changed after preparation; prepare this selection again")
        if self.source_root:
            from .corpus import package_signature
            if tuple(tuple(r) for r in package_signature(Path(self.source_root))) != self.root_identity:
                raise MoveBlocked("The installation changed after preparation; refresh and prepare again")
        for path, size, stamp in self.source_identity:
            try:
                stat = Path(path).stat()
            except OSError as error:
                raise MoveBlocked(f"Source disappeared after preparation: {path}") from error
            if (stat.st_size, stat.st_mtime_ns) != (size, stamp):
                raise MoveBlocked(f"Source changed after preparation: {path}")
        if not self.changed_files:
            raise MoveBlocked("No effective file changes")
        return apply_move(session, edits, self.effective_plan,
                          clip_bytes={f.path: f.data for f in self.files if f.changed and f.donor_path},
                          originals=dict(self.originals),
                          preparation_json=json.dumps(self.evidence(), sort_keys=True))


def file_identity(entries) -> tuple:
    """Stat selected loose sources and archive payloads without reading them on the UI thread."""
    paths = set()
    for entry in entries:
        source = getattr(entry, "source", None)
        if isinstance(source, Path):
            paths.add(source)
        else:
            for key in ("paz_file", "pamt_path"):
                path = getattr(source, key, None)
                if path:
                    paths.add(Path(path))
    out = []
    for path in sorted(paths):
        stat = path.stat()
        out.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    return tuple(out)


def prepare_move(session, snapshot: EditSnapshot, plan: MovePlan, *,
                 read: Callable | None = None, cancelled=lambda: False,
                 identity: Callable[[], tuple] | None = None, progress=lambda _a, _b: None,
                 relationships=None) -> PreparedMove:
    from .clips import read_clip
    from .editing import EditSession
    from .documents import is_socket_file, is_descriptor_file

    read = read or read_clip
    identity = identity or (lambda: file_identity(
        [entry for row in plan.request.replacements for entry in (row.target, row.donor)]))
    initial_identity = identity()
    shadow = EditSession.from_snapshot(snapshot)
    before = shadow.current_files()
    loaded = {}
    files = []
    originals = {}
    effective = []
    checks = [Check("Scope", "Blocked", reason) for reason in plan.blockers]
    selected = [row.target_path for row in plan.request.replacements]
    if len(set(selected)) != len(selected):
        raise MoveBlocked("An animation target was selected more than once")

    def read_once(entry):
        if cancelled():
            raise MoveBlocked("Preparation cancelled")
        key = entry.path
        if key not in loaded:
            data = bytes(read(entry))
            clip = parse_paa(data, name=key)
            if not math.isfinite(clip.duration) or clip.duration < 0:
                raise ValueError('Invalid declared duration')
            if any(not math.isfinite(v) for track in clip.tracks for channel in
                   (track.translation, track.rotation, track.scale) for _, values in channel for v in values):
                raise ValueError('Non-finite animation channel values')
            loaded[key] = data
        return loaded[key]

    for index, row in enumerate(plan.request.replacements):
        try:
            target = read_once(row.target)
            donor = read_once(row.donor)
        except Exception as error:
            raise MoveBlocked(f"Cannot prepare {row.target_path} from {row.donor.path}: {error}") from error
        originals[row.target_path] = target
        current = before.get(row.target_path, target)
        before[row.target_path] = current
        row_checks = [Check("Payload", "Passed", "Target and donor PAA structures decoded", row.target_path)]
        try:
            validate_timing(parse_paa(donor))
            row_checks.append(Check("Timing", "Passed", "Supported channel clocks", row.target_path))
        except TimingError as error:
            row_checks.append(Check("Timing", "Unverified", str(error), row.target_path))
        changed = current != donor
        files.append(PreparedFile(row.target_path, donor, digest(current), row.donor.path,
                                  "LOD animation" if getattr(row.target, "is_lod", False) else "Animation",
                                  changed, tuple(row_checks)))
        if changed:
            effective.append(row)
        checks.extend(row_checks)
        progress(index + 1, len(plan.request.replacements))

    effective_plan = replace(plan, request=replace(plan.request, replacements=tuple(effective)))
    # Review can inspect a proposed orientation before acknowledging it. The original
    # blockers stay on the preparation and are enforced on publication.
    if effective_plan.changes_anything:
        operation = apply_move(session, shadow, replace(effective_plan, blockers=()),
                               clip_bytes={f.path: f.data for f in files if f.changed}, originals=originals)
        isolated = shadow.preview_for_operations([operation.operation_id])
        for path, data in sorted(isolated.items()):
            if path in originals:
                continue
            kind = "Sockets" if is_socket_file(path) else "Descriptor" if is_descriptor_file(path) else "Dependency"
            files.append(PreparedFile(path, data, digest(before.get(path, b"")), kind=kind))
    if cancelled():
        raise MoveBlocked("Preparation cancelled")
    if identity() != initial_identity:
        raise MoveBlocked("Source files changed during preparation; refresh the asset index")
    checks.extend((Check("File set", "Passed", f"All {len(selected)} selected animations prepared"),
                   Check("Contact", "Unverified", "Grip and clearance require preview measurements"),
                   Check("Transitions", "Unverified", "Runtime action selection, conditions and inherited attachment state are not simulated"),
                   Check("In game", "Unverified", "No game test has been run")))
    impact = tuple(relationships.impact(f.path for f in files)) if relationships else ()
    companions = []
    if relationships:
        if relationships.errors:
            checks.append(Check('Relationship coverage', 'Unverified', '\n'.join(relationships.errors)))
        from .clips import companion_path
        by_target = {r.target_path:r for r in plan.request.replacements}
        for row in plan.request.replacements:
            companion = companion_path(row.target_path)
            donor_companion = companion_path(row.donor.path)
            other = by_target.get(companion)
            included = other is not None and other.donor.path == donor_companion
            exists = companion in relationships.paths
            status = "Unverified"
            detail = "No installed companion found"
            if included:
                from tools.paa_motion.timing import duration_seconds
                try:
                    difference = abs(duration_seconds(parse_paa(loaded[row.donor.path])) - duration_seconds(parse_paa(loaded[donor_companion])))
                    status = "Passed" if difference <= 1/30 + 1e-5 else "Warning"
                    detail = f"Both donor variants selected; declared duration difference {difference:.5f} s"
                except TimingError as error:
                    detail = str(error)
            elif exists:
                status, detail = "Warning", "Companion retained or uses a different donor; Full/LOD appearance may differ"
            companions.append((row.target_path, companion, donor_companion, included, status, detail))
            checks.append(Check("Full/LOD companion",status,detail,row.target_path))
        files = [replace(file, checks=file.checks + tuple(c for c in checks
                 if c.path == file.path and c.name == 'Full/LOD companion')) for file in files]
    return PreparedMove(plan, effective_plan, snapshot, tuple(files), tuple(originals.items()),
                        tuple(before.items()), tuple({**before, **shadow.current_files()}.items()), tuple(checks),
                        initial_identity, impact, companion_decisions=tuple(companions))


def preview_session(source, files, unit):
    """Private resolver and pose state, sharing only immutable bind data with the source."""
    from .resolver import PlacementResolver
    from .session import PlacementSession
    from .documents import is_socket_file, is_descriptor_file
    resolver = PlacementResolver()
    resolver.add_files({p: b for p, b in files if is_socket_file(p) or is_descriptor_file(p)})
    hierarchy = source._bind_hierarchy or source.hierarchy
    result = PlacementSession(source.model, hierarchy, resolver, skeleton_path=source.skeleton_path)
    result._equipment_models = getattr(source, '_equipment_models', ())
    weapon_id = unit.weapon_id
    weapon = next((w for w in result.weapons() if w.weapon_id == weapon_id), None)
    if weapon is None:
        from dataclasses import replace
        template = next((w for w in resolver.weapons(model=source.model) if w.game_path == unit.weapon_path), None)
        if template is not None:
            weapon = replace(template, weapon_id=weapon_id, mesh_path=unit.mesh_path, prefab_path=unit.prefab_path, shrink_tag=unit.shrink_tag)
    result.select_weapon(weapon)
    return result
