"""Prepare one installed model with its declared textures and proven source rig."""
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
import re

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry
from cdmw.services.dmm_character_mods import DmmCharacterLibrary, _read, normalized
from cdmw.services.new_item_provenance import SourceRevision, StaleNewItemSource


@dataclass(frozen=True)
class InstalledCharacterModel:
    library: DmmCharacterLibrary
    identifier: str
    path: str


class _Sources:
    def __init__(self, request, snapshot):
        self.snapshot = snapshot
        self.files = request.library.sources(request.identifier)
        self.pins = dict(request.library.revision.files)
        self.hashes = dict(request.library.revision.indexes)

    def payload(self, path):
        path = normalized(path)
        if path in self.files:
            return _read(self.files[path], self.pins, self.hashes, limit=256 * 1024 * 1024)
        return self.snapshot.payload(path)

    def entry(self, path):
        path = normalized(path)
        if path not in self.files:
            return self.snapshot.entry(path)
        file = self.files[path]
        size = self.pins[file][0]
        return ArchiveEntry(path, file, file, 0, size, size, 0, 0)

    def archive_index_maps(self):
        # Only skeletons and their descriptors participate in rig resolution.
        extensions = (".pab", ".xml", ".prefabdata_xml")
        paths = set(self.snapshot.entry_paths_with_extensions(extensions))
        paths.update(path for path in self.files if path.endswith(extensions))
        by_path = {path: (self.entry(path),) for path in paths}
        by_name = defaultdict(list)
        for path, entries in by_path.items():
            by_name[path.rsplit("/", 1)[-1]].extend(entries)
        return by_path, by_name

    def revision(self):
        return SourceRevision((), tuple(sorted(self.pins.items())), lambda _entry: b"",
                              tuple(sorted(self.hashes.items())))


def prepare_installed_character_model(request, snapshot, root, *, stop_event=None):
    """Stage an immutable import; retain the installed source's update witnesses.

    The staging directory belongs to the caller. No archive or installed mod is
    changed. Missing declared textures or an unresolved rig stop the import.
    """
    from cdmw.core.upscale_profiles import parse_texture_sidecar_bindings
    from cdmw.modding.mesh_parser import parse_pac, resolve_pac_bone_palette
    from cdmw.modding.mesh_glb_interchange import _source_slot_skins
    from cdmw.services.mesh_skinning_preflight import has_authored_skin, template_skeleton
    from cdmw.services.new_item_variants import xml_path

    request.library.revision.validate(stop_event)
    sources = _Sources(request, snapshot)
    path = normalized(request.path)
    if not path.startswith("character/model/") or not path.endswith(".pac"):
        raise ValueError("Choose a PAC from the installed character-model list.")
    raise_if_cancelled(stop_event)
    data = sources.payload(path)
    mesh = parse_pac(data, path)
    skins = ()
    if has_authored_skin(mesh):
        skeleton, _, _, _ = template_skeleton(sources, path)
        palette = resolve_pac_bone_palette(data, skeleton)
        skins = tuple(_source_slot_skins(mesh, skeleton, palette))
        if any(part.bone_indices and not skin for part, skin in zip(mesh.submeshes, skins, strict=True)):
            raise ValueError("The installed model's bone identity could not be resolved.")
    sidecar_path = xml_path(path)
    sidecar = sources.payload(sidecar_path)
    text = sidecar.decode("utf-8-sig")
    bindings = parse_texture_sidecar_bindings(text, sidecar_path=sidecar_path)
    textures = {normalized(row.texture_path) for row in bindings if row.texture_path}
    declared = {normalized(value) for value in re.findall(r'_path=["\x27]([^"\x27]+\.dds)["\x27]', text, re.I)}
    # Sidecars can retain additional layers/LOD wrappers beyond the importer's
    # promoted slots. Keep their declared dependencies available as well.
    textures.update(declared)
    destination = Path(root) / "files"
    staged = destination / path
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(data)
    # The external model importer discovers adjacent sidecars. Texture references
    # keep their game-relative paths under its recognized 'files' package root.
    staged.with_suffix(".pac_xml").write_bytes(sidecar)
    for texture in sorted(textures):
        raise_if_cancelled(stop_event)
        target = destination / texture
        payload = sources.payload(texture)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    revision = sources.revision()
    revision.validate(stop_event)
    return staged, skins, revision, bindings


def bind_installed_materials(mesh, root, bindings):
    """Use exact sidecar slots, including shared texture names with no mesh prefix."""
    from cdmw.core.upscale_profiles import _semantic_hint_from_sidecar_parameter
    from cdmw.modding.scene_material_audit import SceneMaterialTextureSlot, _apply_scene_material_slots_to_submesh

    for part in mesh.submeshes:
        slots = []
        for binding in bindings:
            if binding.submesh_name.casefold() != part.name.casefold():
                continue
            hint = _semantic_hint_from_sidecar_parameter(binding.parameter_name)
            semantic, subtype, _, _, channels = hint or ('unknown', 'unknown', 0, (), ())
            slot = {'color': 'base', 'normal': 'normal', 'emissive': 'emissive'}.get(semantic, 'material')
            if binding.layer_role not in {'', 'base'}:
                slot = 'material'
            slots.append(SceneMaterialTextureSlot(
                slot, str(Path(root) / 'files' / normalized(binding.texture_path)),
                binding.parameter_name, semantic, subtype, channels,
                binding.shader_family, binding.srgb_mode, source='installed_pac_xml',
                reference_path=binding.texture_path,
            ))
        if slots:
            _apply_scene_material_slots_to_submesh(part, slots, confidence='authoritative')


def validate_installed_sources(owners, stop_event=None):
    for owner in owners:
        revision = getattr(owner, "dmm_source_revision", None)
        if revision is not None:
            try:
                revision.validate(stop_event)
            except StaleNewItemSource as exc:
                raise StaleNewItemSource("Installed files changed. Load the model again before building or exporting.") from exc


def retain_installed_sources(plan, owners, stop_event=None):
    """Carry the same checks into every existing export/install boundary."""
    validate_installed_sources(owners, stop_event)
    revisions = [source.dmm_source_revision for source in owners
                 if getattr(source, "dmm_source_revision", None) is not None]
    if not revisions:
        return plan
    original = plan.source_revision
    if original is None:
        raise ValueError("An installed character model requires a witnessed game snapshot.")
    files, hashes = dict(original.files), dict(original.indexes)
    for revision in revisions:
        for target, source in ((files, revision.files), (hashes, revision.indexes)):
            for path, stamp in source:
                if target.setdefault(path, stamp) != stamp:
                    raise StaleNewItemSource("Models from different DMM revisions cannot be exported together. Load them again.")
    return replace(plan, source_revision=replace(original, files=tuple(files.items()), indexes=tuple(hashes.items())))
