"""Bounded, cached dependency metadata for effect discovery."""
from dataclasses import dataclass, replace

from cdmw.core.effect_binary import EffectBinaryError, decode_effect_binary
from cdmw.core.effect_edit import emitter_paths_of, preset_names_of, preset_path


def effect_binary_entries(snapshot):
    return sorted((path, entry) for path, entry in snapshot.entries.items()
                  if path.startswith('effect/binary__/') and path.endswith(('.pae', '.paem', '.parg', '.pasg')))


@dataclass(frozen=True)
class Dependency:
    paths: tuple = ()
    textures: tuple = ()
    meshes: tuple = ()
    names: tuple = ()
    loops: bool = False
    note: str = ''


def describe(document):
    paths = (*emitter_paths_of(document), *(preset_path(kind, name) for kind, name in preset_names_of(document)))
    resources = document.resources()
    return Dependency(tuple(dict.fromkeys(paths)),
                      tuple(p for p in resources if p.endswith('.dds') and 'nonetexture' not in p.casefold()),
                      tuple(p for p in resources if p.endswith(('.pam', '.pac'))),
                      tuple(name for _kind, name in preset_names_of(document)),
                      any(v.name == '_loopCount' and v.value == -1 for v in document.root.all_values()),
                      '' if document.walk_complete else document.walk_note)


class DependencyIndex:
    def __init__(self, snapshot, check_cancelled):
        self.snapshot = snapshot
        self.check_cancelled = check_cancelled
        self.cache = {}

    def enrich(self, facts, document):
        root = describe(document)
        queue = list(root.paths)
        seen, missing, notes = set(), set(), set()
        textures, meshes, names = set(facts.textures), set(facts.meshes), set(root.names)
        loops = facts.infinite_emitter
        while queue:
            self.check_cancelled()
            path = queue.pop()
            if path in seen:
                continue
            seen.add(path)
            if len(seen) > 1024:
                notes.add('Dependency traversal exceeded 1024 definitions.')
                break
            if not self.snapshot.has_entry(path):
                missing.add(path)
                continue
            if path not in self.cache:
                try:
                    raw = self.snapshot.read_entry(self.snapshot.entry(path))
                    self.cache[path] = describe(decode_effect_binary(bytes(raw), metadata_only=True))
                except (EffectBinaryError, ValueError, OSError) as exc:
                    self.cache[path] = Dependency(note=str(exc))
            row = self.cache[path]
            queue.extend(row.paths)
            textures.update(row.textures)
            meshes.update(row.meshes)
            names.update(row.names)
            loops = loops or row.loops
            if row.note:
                notes.add(f'{path}: {row.note}')
        return replace(facts, textures=tuple(sorted(textures)), meshes=tuple(sorted(meshes)),
                       presets=tuple(sorted(names)), dependencies=tuple(sorted(seen)),
                       missing_dependencies=tuple(sorted(missing)), dependency_notes=tuple(sorted(notes)), infinite_emitter=loops)
