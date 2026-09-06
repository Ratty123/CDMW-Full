"""Installed motion dependencies and explicitly qualified reverse references.

This module reads archives only. A chart string establishes a file reference;
socket co-occurrence in that chart does not establish an event or action edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
import re
from types import MappingProxyType
from xml.etree import ElementTree as ET

from .corpus import normalize_game_path as normal, package_signature


def active_entries(root, *, cancelled=lambda: False):
    """Mount order comes from PAPGT; the first mounted entry wins per path.

    Fixtures without PAPGT retain discovery order. Invalid installed PAPGT files
    fail explicitly; guessing archive precedence could replace the wrong bytes.
    """
    from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt
    from cdmw.core.papgt_format import parse_papgt
    root = Path(root)
    tables = discover_pamt_files(root)
    papgt = root / 'meta/0.papgt'
    if papgt.exists():
        by_directory = {p.parent.name.lower(): p for p in tables}
        tables = []
        for directory in parse_papgt(papgt.read_bytes()):
            table = by_directory.get(directory.name.lower())
            if table is None:
                # Optional language directories may legitimately be absent.
                if directory.flags & 0xff:
                    continue
                raise ValueError(f'Mounted archive is missing: {directory.name}')
            tables.append(table)
    for table in tables:
        if cancelled():
            raise RuntimeError('Relationship inspection cancelled')
        for entry in parse_archive_pamt(table):
            yield table.parent.name, entry


def resource_path(value):
    value = normal(value)
    if value.startswith(('character/', 'actionchart/')):
        return value
    if value.endswith('.motionblending'):
        return 'character/binary/motionblending/' + value
    if value.endswith('.paa'):
        return 'character/motion/' + value
    if value.endswith('.animset.xml'):
        return 'character/descriptors/animationset/' + value
    if value.endswith(('.pac', '.pab')):
        return 'character/model/' + value
    return value


@dataclass(frozen=True)
class Reference:
    source: str
    target: str
    kind: str
    detail: str = ''


@dataclass(frozen=True)
class AnimationSet:
    path: str
    mappings: tuple[tuple[str, str], ...]
    suffix: str
    default: str

    def resolve(self, animation, existing):
        key = resource_path(animation)
        explicit = dict(self.mappings).get(key)
        if explicit and explicit in existing:
            return explicit, 'Explicit animation-set mapping'
        candidate = key.removesuffix('.paa') + self.suffix if key.endswith('.paa') else ''
        # Suffix targets live in the attachment's weapon folder; the original
        # character directory is not a valid universal expansion.
        if candidate:
            candidate = self.default.rsplit('/', 1)[0] + '/' + candidate.rsplit('/', 1)[-1]
            if candidate in existing:
                return candidate, 'Installed suffix companion'
        if self.default in existing:
            return self.default, 'Explicit default' + ('; mapped file missing' if explicit else '')
        return '', 'Missing mapped animation and default'


class Relationships:
    def __init__(self, paths=(), references=(), *, sets=(), matches=(), spaces=(), entries=(),
                 errors=(), identity=(), charts=()):
        self.paths = frozenset(paths)
        self.references = tuple(references)
        self.sets = MappingProxyType(dict(sets))
        self.matches = tuple(matches)
        self.spaces = MappingProxyType(dict(spaces))
        self.charts = MappingProxyType(dict(charts))
        self.entries = MappingProxyType(dict(entries))
        self.errors = tuple(errors)
        self.identity = tuple(identity)
        reverse, forward = {}, {}
        for ref in references:
            reverse.setdefault(ref.target, []).append(ref)
            forward.setdefault(ref.source, []).append(ref)
        self.reverse = MappingProxyType({k: tuple(v) for k, v in reverse.items()})
        self.forward = MappingProxyType({k: tuple(v) for k, v in forward.items()})

    def impact(self, selected):
        for item in selected:
            path = item if isinstance(item, str) else item.target_path
            findings, seen, pending = [], {path}, [path]
            while pending:
                target = pending.pop()
                for ref in self.reverse.get(target, ()):
                    via = f' via {target}' if target != path else ''
                    findings.append(f'{ref.kind}: {ref.source}{via}' + (f' — {ref.detail}' if ref.detail else ''))
                    if ref.source not in seen:
                        seen.add(ref.source)
                        pending.append(ref.source)
            _, problems = self.closure(path)
            findings.extend(problems)
            findings.append('Coverage: decoded resource references; chart event graph and runtime references remain Unverified')
            if self.errors:
                findings.append(f'Coverage: {len(self.errors)} relationship files have unresolved structures; see relationship checks')
            yield path, tuple(dict.fromkeys(findings))

    def closure(self, path):
        """Every dependency once, plus explicit cycle and missing-reference reports."""
        seen, active, result, problems = set(), set(), [], []
        def visit(node):
            if node in active:
                problems.append('Cycle: ' + node)
                return
            if node in seen:
                return
            seen.add(node)
            active.add(node)
            for ref in self.forward.get(node, ()):
                result.append(ref)
                if ref.target not in self.paths:
                    problems.append('Missing: ' + ref.target)
                else:
                    visit(ref.target)
            active.remove(node)
        visit(path)
        return tuple(result), tuple(dict.fromkeys(problems))

    def attachment(self, model_path, animation):
        choices = {target for pattern, target in self.matches if fnmatchcase(normal(model_path), pattern)}
        if len(choices) != 1:
            return '', 'Unverified: no unique installed attachment mapping'
        mapping = self.sets.get(next(iter(choices)))
        if mapping is None:
            return '', 'Unverified: animation set is missing'
        return mapping.resolve(animation, self.paths)


def from_files(files, *, paths=(), entries=(), identity=(), cancelled=lambda: False):
    from .animation_sets import chart_clip_paths, chart_sockets
    from .motionblending import decode
    references, sets, matches, spaces, charts, errors = [], {}, [], {}, {}, []
    known = set(paths) | set(files)
    models = tuple(p for p in known if p.endswith('.pac'))
    for path, data in files.items():
        if cancelled():
            raise RuntimeError('Relationship inspection cancelled')
        try:
            if path.endswith('.animset.xml'):
                root = ET.fromstring(data)
                mappings = tuple((resource_path(e.attrib['Name']), resource_path(e.attrib['FileName']))
                                 for e in root.iter('AnimationInfo'))
                aset = AnimationSet(path, mappings, normal(root.attrib.get('Suffix', '')),
                                    resource_path(root.attrib.get('DefaultAnimation', '')))
                sets[path] = aset
                for source, target in mappings:
                    references.extend((Reference(path, source, 'Explicit animation-set input'),
                                       Reference(path, target, 'Explicit attachment animation'),
                                       Reference(source, target, 'Attachment mapping', path)))
                if aset.default:
                    references.append(Reference(path, aset.default, 'Explicit default'))
            elif path.endswith('.xml') and 'matchingtable' in path:
                root = ET.fromstring(data)
                for row in root.iter('AnimationSet'):
                    target = resource_path(row.attrib['FilePath'])
                    references.append(Reference(path, target, 'Explicit matching table'))
                    for model in row.iter('Model'):
                        pattern = resource_path(model.attrib['FilePath'])
                        matches.append((pattern, target))
                        for candidate in models:
                            if fnmatchcase(candidate, pattern):
                                references.append(Reference(candidate, target, 'Explicit model matching pattern', path))
            elif path.endswith('.motionblending'):
                # A rejected triangulation must not erase correctly decoded file references.
                from cdmw.core.prefab_binary import decode_prefab_binary
                doc = decode_prefab_binary(data)
                if doc.walk_complete and not doc.inferred_objects:
                    references.extend(Reference(path, resource_path(v.text), 'Explicit blendspace example')
                                      for k, v in doc.root_values if k == '_animationFileNames')
                space = decode(data, path=path)
                spaces[path] = space
                if space.skeleton:
                    references.append(Reference(path, normal(space.skeleton), 'Explicit skeleton'))
            elif path.endswith('.prefab'):
                from .equipment_assets import prefab_models
                for model in prefab_models(data, path):
                    references.extend((Reference(path, model.mesh, 'Explicit equipment mesh'),
                                       Reference(path, model.sockets, 'Explicit socket template'),
                                       Reference(model.mesh, model.sockets, 'Explicit mesh socket binding', path)))
            elif path.endswith('.paac'):
                sockets = chart_sockets(data)
                for clip in chart_clip_paths(data):
                    references.append(Reference(path, resource_path(clip), 'Explicit chart resource',
                                                'Socket association only: ' + ', '.join(sockets)))
                # String boundaries are validated before accepting blend paths.
                from .paac import is_length_prefixed
                for match in re.finditer(rb'[A-Za-z0-9_/.\\-]+\.motionblending', data):
                    for start in range(match.start(), match.end()):
                        if is_length_prefixed(data, start, match.end() - start):
                            references.append(Reference(path, resource_path(data[start:match.end()].decode()), 'Explicit chart resource'))
                            break
                from .paac_events import decode as decode_events
                chart = decode_events(data, path=path, cancelled=cancelled)
                charts[path] = chart
                by_clip = {}
                for action in chart.actions:
                    for resource in (action.clip, action.blendspace):
                        if resource:
                            by_clip.setdefault(resource, []).append(str(action.index))
                references.extend(Reference(path, clip, 'Decoded chart action', 'Action indices: ' + ', '.join(indices))
                                  for clip, indices in by_clip.items())
        except (ValueError, KeyError, ET.ParseError) as error:
            errors.append(f'{path}: {error}')
    # Companion metadata is inspectable, never silently included in a write.
    for path in known:
        if path.endswith('.paa_metabin'):
            clip = path.removesuffix('_metabin')
            if clip.startswith('actionchart/bin__/animmeta/'):
                clip = 'character/motion/' + clip.removeprefix('actionchart/bin__/animmeta/')
            if clip in known:
                references.append(Reference(clip, path, 'Installed metadata companion', 'Event semantics Unverified'))
    return Relationships(known, references, sets=sets.items(), matches=matches, spaces=spaces.items(),
                         entries=entries, errors=errors, identity=identity, charts=charts.items())


def inspect_install(root, *, cancelled=lambda: False, progress=lambda *_: None, required_paths=()):
    from .armour import read_entry
    from .equipment_rules import ANALYSIS_FILES
    signature = tuple(tuple(r) for r in package_signature(root))
    required_paths = frozenset(required_paths) | frozenset(ANALYSIS_FILES)
    known, entries, errors = set(), {}, []
    for _, entry in active_entries(root, cancelled=cancelled):
        path = normal(entry.path)
        if path.endswith(('.paa', '.pac', '.pab', '.paa_metabin', '.sockets.xml')):
            known.add(path)
        equipment_prefab = path.startswith('character/bin__/prefab/1_pc/') and '/weapon/' in path and path.endswith('.prefab')
        if (path.endswith(('.motionblending', '.animset.xml', '.paac')) or
                ('/animationset/' in path and path.endswith('.xml')) or path.endswith(('.pac', '.paa', '.pab', '.sockets.xml')) or path in required_paths or equipment_prefab):
            entries.setdefault(path, entry)
    files = {}
    metadata = [(p, e) for p, e in entries.items() if p.endswith(('.motionblending', '.animset.xml', '.paac', '.prefab')) or '/animationset/' in p]
    for i, (path, entry) in enumerate(metadata):
        if cancelled():
            raise RuntimeError('Relationship inspection cancelled')
        try:
            files[path] = read_entry(entry)
        except (OSError, ValueError, RuntimeError) as error:
            errors.append(f'{path}: {error}')
        if i % 50 == 0:
            progress(i, len(metadata))
    result = from_files(files, paths=known, entries=entries.items(), identity=signature, cancelled=cancelled)
    result.errors += tuple(errors)
    if signature != tuple(tuple(r) for r in package_signature(root)):
        raise RuntimeError('Installation changed during relationship inspection; refresh required')
    return result
