"""Publish an authored hairstyle as a new Damiane choice, never a donor replacement.

All archive access is read-only and belongs on the existing output worker. The
writer pins the mounted catalogue and every dependency until atomic publication.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import xml.etree.ElementTree as ET

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.dds_native import inspect_dds_native
from cdmw.core.pappt_format import parse_pappt
from cdmw.core.papgt_format import parse_papgt
from cdmw.core.pathc_format import encode_pathc, parse_pathc, register_texture
from cdmw.core.pbd_cloth import parse_pbd_config_materials
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.hair_registration import read_hair_choices
from cdmw.domain.mesh.hair import hair_state_from_payload
from cdmw.services.archive_overlay_package_service import export_archive_overlay_package
from cdmw.services.hair_registration import (
    DAMIANE_MESH_PARAM, PART_PREFAB_TABLE, HairRegistrationFile,
    prepare_damiane_hair_registration,
)
from cdmw.services.new_item_provenance import SourceTracker

PBD_CONFIG = "character/descriptors/pbd/pbdconfig.xml"


def material_texture_paths(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Hair materials must not contain XML entities.")
    root = ET.fromstring("<Root>" + data.decode("utf-8-sig") + "</Root>")
    return root, tuple(sorted({node.get("_path") for node in root.iter()
                              if node.get("_path", "").casefold().endswith(".dds")}))


def validate_hair_output(snapshot):
    state = hair_state_from_payload(snapshot.hair_state.payload, allow_unbound=False).payload
    if not state["guides"] or not state["groups"]:
        raise ValueError("Create and bind hair guides before building a hairstyle.")
    if snapshot.replacement_state is None:
        raise ValueError("Hair output has lost its donor and material mapping.")
    if state["template"]["sha256"] != hashlib.sha256(snapshot.original_data).hexdigest():
        raise ValueError("Hair donor source changed; reopen its draft against the original asset.")
    included = {part.target_index for part in snapshot.replacement_state.parts if part.included}
    active = {group["part"] for group in state["groups"]
              if any(guide["group"] == group["id"] for guide in state["guides"])}
    active.update(lock["part"] for lock in state.get("locks", []) if lock["vertices"])
    if not included.intersection(active):
        raise ValueError("No authored hair section is included in the hairstyle.")
    if not state["converted"]:
        bound = {}
        for item in state["bindings"]:
            bound.setdefault(item["part"], set()).add(item["vertex"])
        for lock in state.get("locks", []):
            if lock["kind"] == "unresolved" and lock["part"] in included:
                raise ValueError("Correct unresolved hair roots or mark scalp sections as rigid before exporting.")
            if lock["kind"] == "rigid":
                bound.setdefault(lock["part"], set()).update(lock["vertices"])
        for part in included.intersection(active):
            if bound.get(part, set()) != set(range(len(snapshot.mesh.submeshes[part].vertices))):
                raise ValueError(f"Hair part {part + 1} needs complete guide binding before export.")
    dependencies = {item.path.casefold(): item.data for item in snapshot.replacement_state.dependencies}
    dependencies.update({item.path.casefold(): item.data for item in snapshot.replacement_state.companion_files})
    material_path = state["template"]["path"].replace("character/model/", "character/modelproperty/", 1).casefold() + "_xml"
    if material_path not in dependencies:
        raise ValueError("The required hair material was not captured; reopen with its archive dependencies.")
    _, textures = material_texture_paths(dependencies[material_path])
    if not textures:
        raise ValueError("Hair requires the template's DDS texture bindings.")
    for path in textures:
        if path.casefold() not in dependencies:
            raise ValueError(f"Missing required hair texture: {path}")
        inspect_dds_native(dependencies[path.casefold()])
    return state


def prepare_authored_hair(snapshot, rebuilt, files, existing_paths, pathc_bytes):
    """Immutable geometry/material/registration plan; suitable for fixture tests."""
    from cdmw.modding.mesh_parser import parse_mesh
    state = validate_hair_output(snapshot)
    template = state["template"]
    donor_stem = PurePosixPath(template["path"].replace("\\", "/")).stem
    choices = read_hair_choices(files[DAMIANE_MESH_PARAM])
    indices = [choice.index for choice in choices if choice.prefab_stem == donor_stem]
    if len(indices) != 1:
        raise ValueError("The donor must be one unambiguous current Damiane barber choice.")
    plan = prepare_damiane_hair_registration(files, new_stem=template["target_stem"],
                                            template_index=indices[0], existing_paths=existing_paths)
    donor_path = template["path"].replace("\\", "/").casefold()
    if files[donor_path] != snapshot.original_data:
        raise ValueError("The mounted donor changed since this hair draft was created.")
    original = parse_mesh(snapshot.original_data, donor_path)
    result = parse_mesh(rebuilt.data, donor_path)
    if len(original.submeshes) != len(result.submeshes):
        raise ValueError("Hair export changed its required material section table.")
    if len(original.lod_levels) != len(result.lod_levels):
        raise ValueError("Hair export lost an affected LOD.")
    # Current Damiane hair PACs expose LOD0. Refuse a later multi-LOD donor until
    # every affected lower-level mapping is supported rather than emitting old hair.
    if len(original.lod_levels) > 1:
        raise ValueError("This donor has additional PAC LODs requiring a verified hair LOD writer.")
    registry = parse_pathc(pathc_bytes)
    if encode_pathc(registry) != pathc_bytes:
        raise ValueError("The texture registry does not round-trip exactly.")
    material_path = donor_path.replace("character/model/", "character/modelproperty/", 1) + "_xml"
    overrides = {file.path.casefold(): file.data for file in rebuilt.companion_files}
    allowed_overrides = {material_path}
    material = overrides.get(material_path, files[material_path])
    root, textures = material_texture_paths(material)
    if not textures or {node.get("_pbdSimulationMaterialName") for node in root.iter()
                        if node.get("_pbdSimulationMaterialName")} != {"Hair"}:
        raise ValueError("Required textured Hair material and game physics profile are unavailable.")
    material_additions = []
    texture_donors = {}
    for index, path in enumerate(textures):
        key = path.replace("\\", "/").casefold()
        allowed_overrides.add(key)
        data = overrides.get(key, files.get(key))
        if data is None:
            raise ValueError(f"Missing required hair texture: {path}")
        inspect_dds_native(data)
        new_path = str(PurePosixPath(key).with_name(f'{template["target_stem"]}_texture_{index:02d}.dds'))
        if new_path in existing_paths:
            raise ValueError(f"Hair texture identity already exists: {new_path}")
        registry = register_texture(registry, new_path, like=key, dds_header=data)
        material = material.replace(path.encode("utf-8"), new_path.encode("utf-8"))
        material_additions.append(HairRegistrationFile(new_path, data))
        texture_donors[new_path] = key
    if overrides.keys() - allowed_overrides:
        raise ValueError("Hair export contains an unregistered companion dependency.")
    if snapshot.texture_resources:
        raise ValueError("Apply DDS edits through Hair Appearance so every material reference is retained.")
    # Verify the XML now refers only to the copies included in this package.
    _, rewritten = material_texture_paths(material)
    if set(rewritten) != set(texture_donors):
        raise ValueError("Hair material texture references were not rewritten completely.")
    additions = tuple(replace(item, data=rebuilt.data if item.path.endswith(".pac") else material)
                      if item.path.endswith((".pac", ".pac_xml")) else item for item in plan.additions)
    icon = next(item for item in additions if item.path.endswith(".dds"))
    icon_donor = choices[indices[0]].icon_path.casefold()
    registry = register_texture(registry, icon.path, like=icon_donor, dds_header=icon.data)
    encoded = encode_pathc(registry)
    if parse_pathc(encoded) != registry:
        raise ValueError("Generated texture registry failed reparsing.")
    plan = replace(plan, additions=(*additions, *material_additions))
    texture_donors[icon.path] = icon_donor
    return plan, encoded, texture_donors


def export_hair_package(snapshot, rebuilt, entry, output, *, stop_event=None, on_log=None):
    """Build and reparse a complete DMM package outside the installed game."""
    root = Path(entry.pamt_path).resolve().parent.parent
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("Hair output must be a new folder outside the installed game.")
    state = validate_hair_output(snapshot)
    donor_path = state["template"]["path"].replace("\\", "/").casefold()
    new_stem = state["template"]["target_stem"]
    tracker = SourceTracker(lambda item: read_archive_entry_data(item, stop_event)[0])
    for name in ("0.papgt", "0.pathc", "0.paver"):
        tracker.pin_file(root / "meta" / name)
    mount_bytes = (root / "meta/0.papgt").read_bytes()
    mounts = parse_papgt(mount_bytes)
    if not mounts or len({row.name.casefold() for row in mounts}) != len(mounts):
        raise ValueError("A valid unambiguous game mount catalogue is required.")
    entries = {}
    for mount in mounts:
        raise_if_cancelled(stop_event, "Hair catalogue scan cancelled.")
        if Path(mount.name).name != mount.name or mount.name in {".", ".."}:
            raise ValueError("The game mount catalogue contains an unsafe directory.")
        for pamt in sorted((root / mount.name).glob("*.pamt")):
            tracker.pin_file(pamt)
            if on_log:
                on_log(f"Reading mounted hair dependencies: {mount.name}")
            for item in parse_archive_pamt(pamt):
                raise_if_cancelled(stop_event, "Hair catalogue scan cancelled.")
                key = item.path.replace("\\", "/").casefold()
                if ("/hair/" in key or key.startswith(("character/texture/", "ui/texture/image/customizeimage/",
                        "character/descriptors/pbd/")) or key in {DAMIANE_MESH_PARAM, PART_PREFAB_TABLE}
                        or new_stem in key):
                    entries.setdefault(key, item)
    files = {}

    def read(path):
        key = path.replace("\\", "/").casefold()
        if key not in files:
            item = entries.get(key)
            if item is None or item.orig_size > 128 * 1024 * 1024:
                raise ValueError(f"Missing or oversized hair dependency: {path}")
            files[key] = tracker.read(item)
        return files[key]

    choices = read_hair_choices(read(DAMIANE_MESH_PARAM))
    donor_stem = PurePosixPath(donor_path).stem
    choice = next((row for row in choices if row.prefab_stem == donor_stem), None)
    if choice is None:
        raise ValueError("The loaded hair is not a current Damiane barber choice.")
    record = parse_pappt(read(PART_PREFAB_TABLE)).find(donor_stem)
    if record is None:
        raise ValueError("The donor hair prefab registration is missing.")
    resources = tuple(item.text.casefold() for item in decode_prefab_binary(read(record.prefab_path)).resource_strings())
    if resources != (donor_path,):
        raise ValueError("The registered donor does not own the edited mesh.")
    read(donor_path)
    physics_path = donor_path.replace("character/model/", "character/bin__/meshphysics/", 1)[:-4] + ".hkx"
    read(physics_path)
    read(choice.icon_path)
    material_path = donor_path.replace("character/model/", "character/modelproperty/", 1) + "_xml"
    _, textures = material_texture_paths(read(material_path))
    for path in textures:
        read(path)
    config = parse_pbd_config_materials(read(PBD_CONFIG).decode("utf-8-sig"))
    if "hair" not in config:
        raise ValueError("The donor game Hair physics profile is missing.")
    read("character/descriptors/pbd/" + config["hair"].filename.replace("\\", "/"))
    pathc_bytes = (root / "meta/0.pathc").read_bytes()
    plan, pathc, texture_donors = prepare_authored_hair(snapshot, rebuilt, files, entries, pathc_bytes)
    revision = tracker.capture()
    revision.validate(stop_event)
    plan.check_sources(files)
    patches = tuple(ArchivePatchRequest(entries[item.path], item.data) for item in plan.replacements)
    additions = tuple(ArchiveAddRequest.from_template(entries[texture_donors.get(item.path,
                     item.path.replace(new_stem, donor_stem))], item.path, item.data) for item in plan.additions)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-hair-", dir=output.parent))
    try:
        shared = export_archive_overlay_package(patches, additions, package_root=stage, game_root=root,
            metadata_files=(("meta/0.pathc", pathc),), stop_event=stop_event, on_log=on_log)
        wanted = {item.path: item.data for item in (*plan.replacements, *plan.additions)}
        packaged = parse_archive_pamt(stage / shared.group / "0.pamt")
        if len(packaged) != len(wanted):
            raise ValueError("The hair archive contains an incomplete or duplicate bundle.")
        for item in packaged:
            if read_archive_entry_data(item, stop_event)[0] != wanted[item.path]:
                raise ValueError(f"Hair package payload failed reparsing: {item.path}")
        title = f"Damiane - {state['style_name']}"
        description = "An additional authored hairstyle. In-game selection, save/load and motion checks are pending."
        manifest = {"format": "v1", "schema_version": 1, "kind": "archive_override_mod", "name": title,
            "title": title, "game": "Crimson Desert", "target_game": shared.target_game, "version": "1.0",
            "description": description, "files_dir": ".", "manager_targets": ["dmm"],
            "structure": "archive_group", "archive_group": shared.group,
            "file_count": shared.file_count, "overrides": list(shared.paths)}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (stage / "modinfo.json").write_text(json.dumps({"name": title, "version": "1.0", "description": description}), encoding="utf-8")
        evidence = {"format": "cdmw_hair_output_v1", "runtime_verified": False,
            "choice_index": plan.choice_index, "hair_revision": state["revision"], "donor": state["template"],
            "source_revision": revision.manifest(), "roundtrip_files": len(wanted),
            "files": {path: hashlib.sha256(data).hexdigest() for path, data in wanted.items()}}
        (stage / "hair-authoring.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        (stage / "README.txt").write_text(
            f"{title}\n\nAdds barber choice {plan.choice_index + 1}; existing choices are retained.\n"
            "Import this complete folder with DMM. Game acceptance is pending: test selection, save/load, "
            "head movement, running, headgear and LODs on a test save.\n"
            "This package includes shared selection and texture registries; rebuild against the current mounted "
            "catalogue when combining hairstyle mods. Source archives were only read.\n", encoding="utf-8")
        revision.validate(stop_event)
        if (root / "meta/0.pathc").read_bytes() != pathc_bytes or (root / "meta/0.papgt").read_bytes() != mount_bytes:
            raise ValueError("The game registries changed while building hair.")
        raise_if_cancelled(stop_event, "Hair package cancelled before publication.")
        os.rename(stage, output)
        return output
    finally:
        if stage.exists():
            shutil.rmtree(stage)
