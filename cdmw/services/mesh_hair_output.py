"""Publish an authored hairstyle as a new playable-character choice.

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
import struct
import tempfile
import xml.etree.ElementTree as ET

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.dds_native import inspect_dds_native
from cdmw.core.pappt_format import parse_pappt
from cdmw.core.papgt_format import read_papgt_directories
from cdmw.core.pathc_format import (
    dds_shape, encode_pathc, parse_pathc, register_dds, register_texture, with_stored_mip_sizes,
)
from cdmw.core.pbd_cloth import parse_pbd_config_materials
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.hair_registration import (
    build_hair_choice_xml_patch, icon_donor_for, read_hair_choices, validate_hair_stem,
)
from cdmw.domain.mesh.hair import hair_state_from_payload
from cdmw.domain.mesh.replacement import bound_part_indices
from cdmw.services.archive_overlay_package_service import export_archive_overlay_package
from cdmw.services.hair_registration import (
    PART_PREFAB_TABLE, HairRegistrationFile,
    prepare_hair_registration, validate_hair_prefab_donor,
)
from cdmw.services.new_item_provenance import SourceTracker

PBD_CONFIG = "character/descriptors/pbd/pbdconfig.xml"


def apply_hair_physics_paint(data, snapshot):
    """Disable retained cloth on painted rows and on all new hair in the rebuilt PAC.

    The rebuild clones the nearest donor record for every new vertex, cloth
    binding included. CDMW never authors cloth guides, so drawn, generated and
    imported hair would follow the donor hairstyle's old guide geometry. Those
    vertices are made static; original donor hair keeps its binding unless it
    is painted Static. Skeletal weights, geometry and materials are unchanged.
    """
    hair = getattr(snapshot, "hair_state", None)
    if hair is None:
        return data
    state = hair.payload
    output = snapshot.replacement_state
    indices = bound_part_indices(snapshot.mesh, output)
    targets = {indices[part.part_id]: part.target_index for part in output.parts if part.included}
    fixed = {}
    if state.get("converted"):
        # Every vertex of an imported part is new geometry.
        for part in output.parts:
            source = indices[part.part_id]
            if part.included and part.import_positions and source in targets:
                fixed[targets[source]] = None  # all vertices, at every LOD
    else:
        painted = {i: guide for i, guide in enumerate(state["guides"]) if guide.get("pinned")}
        for binding in state["bindings"]:
            guide = painted.get(binding["guide"])
            target = targets.get(binding["part"])
            if guide is None or target is None:
                continue
            row = binding["segment"] + int(binding["t"] >= .5)
            if row == 0 or guide["pinned"][row]:
                fixed.setdefault(target, set()).add(binding["vertex"])
        for lock in state.get("locks", ()):
            target = targets.get(lock["part"])
            if lock["kind"] == "generated" and target is not None:
                fixed.setdefault(target, set()).update(lock["vertices"])
    if not fixed:
        return data
    from cdmw.modding.pac_cloth import pac_cloth_lods
    from cdmw.modding.mesh_builder_common import _build_spatial_hash, _nearest_point_index
    levels = pac_cloth_lods(data)
    result = bytearray(data)
    for target, vertices in fixed.items():
        part = levels[0].submeshes[target]
        if vertices is None:
            for level in levels:
                for offset in level.submeshes[target].source_vertex_offsets:
                    _make_static(data, result, offset)
            continue
        source = next(index for index, mapped in targets.items() if mapped == target)
        if (len(part.vertices) != len(snapshot.mesh.submeshes[source].vertices)
                or any(not 0 <= vertex < len(part.vertices) for vertex in vertices)):
            raise ValueError("Hair physics paint lost its output vertex mapping.")
        cell, grid = _build_spatial_hash(part.vertices)
        for lod, level in enumerate(levels):
            current = level.submeshes[target]
            # LOD0 has exact authored indices. Reduced LODs inherit the mask
            # from their nearest LOD0 vertex, using the mesh transfer index.
            selected = vertices if lod == 0 else {
                i for i, point in enumerate(current.vertices)
                if _nearest_point_index(point, part.vertices, cell, grid) in vertices}
            for vertex in selected:
                _make_static(data, result, current.source_vertex_offsets[vertex])
    return bytes(result)


def _make_static(data, result, offset):
    """Clear one PAC record's cloth guide binding, keeping its skeletal skin."""
    from cdmw.modding.pac_cloth import pac_cloth_binding
    from cdmw.modding.mesh_parser import PAC_SKIN_EXTRA_INDEX_SENTINEL
    if pac_cloth_binding(data, offset) is None:
        return
    group = struct.unpack_from("<I", data, offset + 24)[0]
    struct.pack_into("<I", result, offset + 24, group & 0xC00003FF)
    result[offset + 12:offset + 16] = PAC_SKIN_EXTRA_INDEX_SENTINEL
    result[offset + 32:offset + 36] = bytes(4)
    result[offset + 39] = (data[offset + 39] & 0xC0) | 63


def material_texture_paths(data):
    from cdmw.core.archive_model_texture_semantics import _is_placeholder_model_texture
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Hair materials must not contain XML entities.")
    root = ET.fromstring("<Root>" + data.decode("utf-8-sig") + "</Root>")
    return root, tuple(sorted({node.get("_path") for node in root.iter()
                              if node.get("_path", "").casefold().endswith(".dds")
                              and not _is_placeholder_model_texture(node.get("_path", ""))}))


def _preserved_hair_vertices(snapshot, state, required):
    """Prove unprepared vertices still use their original PAC geometry/skin.

    Guide inference is not game skinning. Compare against immutable donor bytes,
    in the displayed coordinate frame, including retained-triangle lineage.
    Neither an unresolved label nor a draft's vertex map is proof on its own.
    """
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TOPOLOGY

    output = snapshot.replacement_state
    donor = parse_mesh(snapshot.original_data, output.target_path)
    if donor.format.lower() != "pac":
        return {}
    if output.neutral_coordinates:
        if output.neutral_appearance is None:
            raise ValueError("Experimental replacement is missing its neutral coordinate transform.")
        donor = output.neutral_appearance.to_neutral(donor)
    indices = bound_part_indices(snapshot.mesh, output)
    targets = {indices[part.part_id]: part.target_index for part in output.parts}
    existing = {group["part"] for group in state["groups"] if group["mode"] == "existing"}
    preserved = {}
    for index, vertices in required.items():
        if index not in existing or index not in targets or not 0 <= targets[index] < len(donor.submeshes):
            continue
        original, part = donor.submeshes[targets[index]], snapshot.mesh.submeshes[index]
        sources = part.source_vertex_map
        gen_lock_verts = {
            v for lock in state.get("locks", ())
            if lock["part"] == index and lock["kind"] == "generated"
            for v in lock["vertices"]
        }
        is_hybrid = bool(gen_lock_verts) and any(i == -1 for i in sources)
        # Saved drafts retain record offsets/maps but may omit the PAC layout.
        # The parsed immutable donor owns the layout check, never draft geometry.
        if (original.source_vertex_stride != 40 or part.source_vertex_stride not in (0, 40)
                or (part.source_vertex_map_authority == SOURCE_VERTEX_MAP_TOPOLOGY and not is_hybrid)
                or len(sources) != len(part.vertices)
                or any(type(i) is not int or (not (is_hybrid and i == -1) and not 0 <= i < len(original.vertices)) for i in sources)
                or (is_hybrid and not {v for v, i in enumerate(sources) if i == -1}.issubset(gen_lock_verts))
                or len([i for i in sources if i >= 0]) != len({i for i in sources if i >= 0})
                or (part.source_descriptor_offset >= 0 and part.source_descriptor_offset != original.source_descriptor_offset)
                or (str(index) in state["vertex_sources"] and state["vertex_sources"][str(index)] != sources)):
            continue
        if is_hybrid and state["vertex_sources"].get(str(index)) != sources:
            continue
        # A cut may remove original triangles; it cannot invent connections.
        original_faces = set(original.faces)
        invalid = set()
        for face in part.faces:
            if any(type(v) is not int or not 0 <= v < len(sources) for v in face):
                invalid.update(vertices)
                break
            mapped = tuple(sources[v] for v in face)
            if is_hybrid and all(m == -1 for m in mapped):
                continue
            if any(m < 0 for m in mapped) or mapped not in original_faces:
                invalid.update(face)
        retained = set()
        for vertex in vertices - invalid:
            if not 0 <= vertex < len(sources):
                continue
            source = sources[vertex]
            if source < 0:
                continue
            unchanged = True
            for channel in ("vertices", "normals", "uvs", "bone_indices", "bone_weights", "source_vertex_offsets"):
                before, after = getattr(original, channel), getattr(part, channel)
                if len(before) != len(original.vertices) or len(after) != len(part.vertices):
                    unchanged = False
                    break
                a, b = before[source], after[vertex]
                if channel in {"vertices", "normals", "uvs"}:
                    # Rust publishes f32. Do not invent edits from JSON rounding;
                    # a one-ULP geometry change must still fail this check.
                    a, b = struct.pack(f"<{len(a)}f", *a), struct.pack(f"<{len(b)}f", *b)
                if a != b:
                    unchanged = False
                    break
            if unchanged:
                retained.add(vertex)
        preserved[index] = retained
    return preserved


def validate_hair_output(snapshot):
    state = hair_state_from_payload(snapshot.hair_state.payload, allow_unbound=False).payload
    if not state["groups"] or (not state["converted"] and not state["guides"] and not any(g["mode"] == "existing" for g in state["groups"])):
        raise ValueError("Create and bind hair guides before building a hairstyle.")
    if snapshot.replacement_state is None:
        raise ValueError("Hair output has lost its donor and material mapping.")
    if state["template"]["sha256"] != hashlib.sha256(snapshot.original_data).hexdigest():
        raise ValueError("Hair donor source changed; reopen its draft against the original asset.")
    indices = bound_part_indices(snapshot.mesh, snapshot.replacement_state)
    included = {indices[part.part_id] for part in snapshot.replacement_state.parts if part.included}
    active = {group["part"] for group in state["groups"]
              if any(guide["group"] == group["id"] for guide in state["guides"])}
    active.update(lock["part"] for lock in state.get("locks", []) if lock["vertices"])
    active.update(group["part"] for group in state["groups"]
                  if group["mode"] == "existing" and group["part"] not in state["prepared_parts"])
    if not (included if state["converted"] else included.intersection(active)):
        raise ValueError("No authored hair section is included in the hairstyle.")
    if not state["converted"]:
        bound = {}
        for item in state["bindings"]:
            bound.setdefault(item["part"], set()).add(item["vertex"])
        unresolved = {}
        for lock in state.get("locks", []):
            if lock["kind"] == "unresolved":
                unresolved.setdefault(lock["part"], set()).update(lock["vertices"])
            if lock["kind"] == "rigid":
                bound.setdefault(lock["part"], set()).update(lock["vertices"])
        required = {}
        for part in included.intersection(active):
            vertices = set(range(len(snapshot.mesh.submeshes[part].vertices)))
            if bound.get(part, set()) - vertices:
                raise ValueError(f"Hair part {part + 1} needs complete guide binding before export.")
            missing = (vertices - bound.get(part, set())) | unresolved.get(part, set())
            if missing:
                required[part] = missing
        preserved = _preserved_hair_vertices(snapshot, state, required) if required else {}
        for part, vertices in required.items():
            if vertices != preserved.get(part, set()):
                raise ValueError(f"Hair part {part + 1} has changed sections without grooming guides. Set their roots or restore the original hair before exporting.")
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


def encode_hair_icon_dds(source_path: Path | str, donor_icon_dds: bytes, stop_event=None) -> bytes:
    """Convert a custom image or DDS into a barber icon matching the donor DDS shape and mip count."""
    return encode_dds_like(source_path, donor_icon_dds, stop_event=stop_event)


#: Image files that Hair Tools re-encodes into a donor's DDS layout.
DDS_SOURCE_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def encode_dds_like(source_path: Path | str, donor_dds: bytes, *, stop_event=None) -> bytes:
    """Convert an image or DDS into ``donor_dds``'s size, format and mip count.

    A DDS that already has that layout is used unchanged. Anything else is
    decoded, resized to the donor's size and encoded in the donor's format, so
    the game reads it exactly like the file it replaces.
    """
    from PIL import Image
    from cdmw.core.texture_native import decode_dds_preview_with_directxtex, encode_dds_with_directxtex

    source = Path(source_path)
    if not source.is_file() or not 1 <= source.stat().st_size <= 128 * 1024 * 1024:
        raise ValueError("Choose an existing image or DDS file smaller than 128 MiB.")
    donor_info = inspect_dds_native(donor_dds)
    if donor_info.reason or not donor_info.mip_levels or not donor_info.format_name:
        raise ValueError("The original DDS format could not be inspected.")
    width, height = int(donor_info.width), int(donor_info.height)
    mip_count = max(1, len(donor_info.mip_levels))
    suffix = source.suffix.lower()
    if suffix == ".dds":
        raw = source.read_bytes()
        src_info = inspect_dds_native(raw)
        if src_info.reason or not src_info.mip_levels:
            raise ValueError(f"Invalid DDS file: {src_info.reason or source.name}")
        if dds_shape(raw) == dds_shape(donor_dds):
            return with_stored_mip_sizes(raw)
    elif suffix not in DDS_SOURCE_IMAGE_SUFFIXES:
        raise ValueError("Choose a PNG, JPG, WEBP, BMP, or DDS file.")

    with tempfile.TemporaryDirectory(prefix="cdmw-hair-dds-") as directory:
        root = Path(directory)
        png_path = root / "source_rgba.png"
        if suffix == ".dds":
            raw_png = root / "decoded.png"
            raise_if_cancelled(stop_event, "Hair texture encoding cancelled.")
            if not decode_dds_preview_with_directxtex(source, raw_png, max_dimension=0,
                                                      requested_mip=0, stop_event=stop_event):
                raise ValueError("The native DDS decoder could not read this DDS file.")
            source_image_path = raw_png
        else:
            source_image_path = source
        with Image.open(source_image_path) as image:
            rgba = image.convert("RGBA")
            if rgba.size != (width, height):
                rgba = rgba.resize((width, height), Image.Resampling.LANCZOS)
            rgba.save(png_path, format="PNG")
        raise_if_cancelled(stop_event, "Hair texture encoding cancelled.")
        out_dds = root / "encoded.dds"
        if not encode_dds_with_directxtex(
            png_path, out_dds, dds_format=donor_info.format_name,
            width=width, height=height, mip_count=mip_count, stop_event=stop_event,
        ):
            raise ValueError("The native DDS encoder could not encode this image.")
        encoded = out_dds.read_bytes()
    encoded_info = inspect_dds_native(encoded)
    if (
        not encoded_info.reason
        and encoded_info.format_name == donor_info.format_name
        and [m.byte_count for m in encoded_info.mip_levels] == [m.byte_count for m in donor_info.mip_levels]
    ):
        encoded = bytes(donor_dds[:donor_info.data_offset]) + bytes(encoded[encoded_info.data_offset:])
    inspect_dds_native(encoded)
    if dds_shape(encoded) != dds_shape(donor_dds):
        raise ValueError("The encoded DDS does not match the original layout.")
    return with_stored_mip_sizes(encoded)


def prepare_authored_hair(snapshot, rebuilt, files, existing_paths, pathc_bytes, reference_tables=(), *,
                          target_stem_override: str = "", custom_icon_dds: bytes | None = None):
    """Immutable geometry/material/registration plan; suitable for fixture tests."""
    from cdmw.modding.mesh_parser import parse_mesh
    state = validate_hair_output(snapshot)
    template = dict(state["template"])
    new_stem = str(target_stem_override or "").strip() or template["target_stem"]
    validate_hair_stem(new_stem)
    from cdmw.domain.hair_characters import hair_character
    profile = hair_character(template["character"])
    donor_stem = PurePosixPath(template["path"].replace("\\", "/")).stem.lower()
    choices = read_hair_choices(files[profile.mesh_param_path])
    # Repeated slots can share a prefab. Match the chooser's first occurrence
    # and clone that slot's settings and icon without disturbing any other slot.
    choice = next((choice for choice in choices if choice.usable and choice.prefab_stem == donor_stem), None)
    if choice is None:
        raise ValueError("The donor must be a current barber choice for this character.")
    plan = prepare_hair_registration(files, new_stem=new_stem,
                                     template_index=choice.index, existing_paths=existing_paths,
                                     character=profile.name)
    donor_path = template["path"].replace("\\", "/").casefold()
    if files[donor_path] != snapshot.original_data:
        raise ValueError("The mounted donor changed since this hair draft was created.")
    original = parse_mesh(snapshot.original_data, donor_path)
    result = parse_mesh(rebuilt.data, donor_path)
    if len(original.submeshes) != len(result.submeshes):
        raise ValueError("Hair export changed its required material section table.")
    if len(original.lod_levels) != len(result.lod_levels):
        raise ValueError("Hair export lost an affected LOD.")
    # Supported hair PACs expose LOD0. Refuse a later multi-LOD donor until
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
        new_path = str(PurePosixPath(key).with_name(f"{new_stem}_texture_{index:02d}.dds"))
        if new_path in existing_paths:
            raise ValueError(f"Hair texture identity already exists: {new_path}")
        donor_bytes = files.get(key)
        registered_in_game = (registry.find(key) is not None) or any(
            other.find(key) is not None for other in reference_tables
        )
        if registered_in_game and donor_bytes is not None and dds_shape(data) == dds_shape(donor_bytes):
            registry = register_texture(registry, new_path, like=key, dds_header=data, reference_tables=reference_tables)
            texture_donors[new_path] = key
        else:
            registry = register_dds(registry, new_path, data)
            texture_donors[new_path] = None
        material = material.replace(path.encode("utf-8"), new_path.encode("utf-8"))
        material_additions.append(HairRegistrationFile(new_path, data))
    if overrides.keys() - allowed_overrides:
        raise ValueError("Hair export contains an unregistered companion dependency.")
    if snapshot.texture_resources:
        raise ValueError("Apply DDS edits through Hair Appearance so every material reference is retained.")
    # Verify the XML now refers only to the copies included in this package.
    _, rewritten = material_texture_paths(material)
    if set(rewritten) != set(texture_donors):
        raise ValueError("Hair material texture references were not rewritten completely.")
    icon_donor = plan.icon_donor
    if custom_icon_dds is not None:
        inspect_dds_native(custom_icon_dds)
        if dds_shape(custom_icon_dds) != dds_shape(files[icon_donor]):
            raise ValueError("Custom barber icon DDS format does not match this character's barber icons.")
    additions = tuple(
        replace(item, data=rebuilt.data if item.path.endswith(".pac")
                else material if item.path.endswith(".pac_xml")
                else (custom_icon_dds if (custom_icon_dds is not None and item.path.endswith(".dds")) else item.data))
        for item in plan.additions
    )
    icon = next(item for item in additions if item.path.endswith(".dds"))
    registry = register_texture(registry, icon.path, like=icon_donor, dds_header=icon.data,
                                reference_tables=reference_tables)
    encoded = encode_pathc(registry)
    if parse_pathc(encoded) != registry:
        raise ValueError("Generated texture registry failed reparsing.")
    plan = replace(plan, additions=(*additions, *material_additions))
    texture_donors[icon.path] = icon_donor
    return plan, encoded, texture_donors


_PLAIN_DDS_FLAGS = 0x201


def _normalize_hair_dds_for_dmm(data: bytes, template_entry, *, overridden: bool = False) -> tuple[bytes, int]:
    """Ensure private/edited hair DDS copies store real mip sizes and plain archive flags.

    Partially compressed game textures (flags ``0x1701``, ``compression_type == 1``)
    carry compressed mip sizes in ``dwReserved1``; once expanded for a private copy,
    leaving stale sizes or partial flags causes DMM/game noise. Uncompressed
    ``compression_type == 0`` textures (such as tiny ``0x1700`` maps) stay untouched
    unless replaced.
    """
    flags = int(template_entry.flags)
    payload = bytes(data)
    if payload[:4] == b"DDS " and (int(template_entry.compression_type) == 1 or overridden):
        from cdmw.core.pathc_format import PathcError, with_stored_mip_sizes

        if bool(getattr(template_entry, "compressed", False)) or overridden:
            try:
                payload = with_stored_mip_sizes(payload)
            except PathcError:
                pass
            flags = _PLAIN_DDS_FLAGS
        else:
            # Already stored whole; update dwReserved1 only if already non-zero and stale.
            if payload[32:48] != bytes(16):
                try:
                    fixed = with_stored_mip_sizes(payload)
                    if fixed != payload:
                        payload = fixed
                        flags = _PLAIN_DDS_FLAGS
                except PathcError:
                    pass
    return payload, flags


def _apply_dmm_mounted_hair_sources(root: Path, entry, files: dict[str, bytes], tracker, *,
                                    donor_path: str, donor_stem: str, profile,
                                    original_data: bytes) -> None:
    """Resolve DMM-mounted hair assets when the session opened a DMM-served donor."""
    from cdmw.services.dmm_runtime_mount import (
        DmmManifestError, KEEP_GAME_EXTENSIONS, is_dmm_note, read_runtime_mount,
    )

    note = getattr(entry, "prepared_note", "")
    vanilla_donor = files.get(donor_path)
    if not is_dmm_note(note) and vanilla_donor == original_data:
        return
    try:
        mount = read_runtime_mount(root)
    except (OSError, DmmManifestError):
        mount = None
    if mount is None or not mount.serving:
        return

    def read_mounted(path: str) -> bytes | None:
        key = str(path or "").replace("\\", "/").casefold()
        if PurePosixPath(key).suffix in KEEP_GAME_EXTENSIONS:
            return None
        served = mount.files.get(key)
        if served is None or not served.source.is_file():
            return None
        tracker.pin_file(served.source)
        return served.source.read_bytes()

    mounted_donor = read_mounted(donor_path)
    if mounted_donor is not None and (is_dmm_note(note) or mounted_donor == original_data):
        files[donor_path] = mounted_donor
    material_path = donor_path.replace("character/model/", "character/modelproperty/", 1) + "_xml"
    mounted_material = read_mounted(material_path)
    if mounted_material is not None:
        files[material_path] = mounted_material
        _, textures = material_texture_paths(mounted_material)
        for tex in textures:
            tex_key = tex.replace("\\", "/").casefold()
            mounted_tex = read_mounted(tex_key)
            if mounted_tex is not None:
                files[tex_key] = mounted_tex


HAIR_REGISTRATION_DESCRIPTION = (
    "Registers the new hairstyle's part so the barber can load it. Enable it together with "
    "the hairstyle mod. Requires DMM 4.4.0 or newer.")


def hair_dmm_entries_note(title: str) -> str:
    """What an additive hairstyle needs enabled in DMM."""
    return (f'In DMM 4.4.0 or newer, enable both "{title}" and "{title} (item registrations)". '
            "Without the item registrations entry the new hairstyle does not load.")


def _barber_slot_note(profile, index: int) -> str:
    return (f"Another enabled mod already uses barber slot {index} in {profile.name}'s hairstyle list. "
            "How the game handles two hairstyles at one slot is not checked yet; until it is, enable only one "
            f"mod that adds hairstyles for {profile.name}.")


def _served_barber_slot_conflict(root: Path, profile, index: int) -> bool:
    """Whether DMM currently serves a barber list that already has a hairstyle at ``index``."""
    from cdmw.domain.hair_registration import HairRegistrationError
    from cdmw.services.dmm_runtime_mount import DmmManifestError, read_runtime_mount
    try:
        mount = read_runtime_mount(root)
    except (OSError, DmmManifestError):
        return False
    served = mount.files.get(profile.mesh_param_path) if mount is not None and mount.serving else None
    if served is None or not served.source.is_file():
        return False
    try:
        return len(read_hair_choices(served.source.read_bytes())) > index
    except (OSError, HairRegistrationError):
        # A list this tool cannot read was changed by a mod too.
        return True


def additive_hair_slot_conflicts(mods_dir: Path | str, own_folder: Path | str, patch_rel: str,
                                 index: int) -> tuple[str, ...]:
    """Other mods in DMM's folder whose barber-list patch inserts a hairstyle at ``index``."""
    mods, own = Path(mods_dir), Path(own_folder).resolve()
    depth = len(PurePosixPath(patch_rel).parts)
    found = []
    for patch in sorted(mods.glob(f"*/{patch_rel}")):
        folder = patch.parents[depth - 1]
        if folder.resolve() == own:
            continue
        try:
            data = patch.read_bytes()
            if len(data) > 1024 * 1024:
                continue
            root = ET.fromstring(data)
        except (OSError, ET.ParseError):
            continue
        if any(node.tag == "MeshSet" and node.get("Index") == str(index)
               for insert in root.iter("insert") if insert.get("into") == "ParamDesc" for node in insert):
            found.append(folder.name)
    return tuple(found)


def _scan_hair_entries(root: Path, tracker, profile, new_stem: str, stop_event=None, on_log=None):
    """The game's own archive entries a hairstyle export reads, DLC copies first.

    Read-only. Returns ``(entries, dlc_layers, mount_bytes)``.
    """
    for name in ("0.papgt", "0.pathc", "0.paver"):
        tracker.pin_file(root / "meta" / name)
    mount_bytes = (root / "meta/0.papgt").read_bytes()
    # Read-only: the shipped mount list is the compact, signed layout since the DLC update.
    mounts = read_papgt_directories(mount_bytes)
    if not mounts or len({row.name.casefold() for row in mounts}) != len(mounts):
        raise ValueError("A valid unambiguous game mount catalogue is required.")
    entries = {}
    # A DLC ships its own copies of base group folders whose files replace the base
    # files at the same path; read those copies so the barber list and tables edited
    # here are the ones the game uses.
    dlc_layers = []
    for layer in sorted((root / "dlc").glob("dlc_*")) if (root / "dlc").is_dir() else ():
        if (layer / "meta/0.papgt").is_file():
            tracker.pin_file(layer / "meta/0.papgt")
            dlc_layers.append((layer, read_papgt_directories((layer / "meta/0.papgt").read_bytes())))
    # The first copy of a path wins, so the DLC layers are read before the base.
    for folder, mount in [(layer, row) for layer, rows in dlc_layers for row in rows] + [(root, row) for row in mounts]:
        raise_if_cancelled(stop_event, "Hair catalogue scan cancelled.")
        if Path(mount.name).name != mount.name or mount.name in {".", ".."}:
            raise ValueError("The game mount catalogue contains an unsafe directory.")
        for pamt in sorted((folder / mount.name).glob("*.pamt")):
            tracker.pin_file(pamt)
            if on_log:
                on_log(f"Reading mounted hair dependencies: {mount.name}")
            for item in parse_archive_pamt(pamt):
                raise_if_cancelled(stop_event, "Hair catalogue scan cancelled.")
                key = item.path.replace("\\", "/").casefold()
                if (key.startswith(HAIR_DEPENDENCY_PREFIXES) or "/hair/" in key
                        or key in {profile.mesh_param_path, PART_PREFAB_TABLE}
                        or (new_stem and new_stem in key)):
                    entries.setdefault(key, item)
    return entries, dlc_layers, mount_bytes


#: Besides ``/hair/`` paths, the folders a hairstyle export reads from.
HAIR_DEPENDENCY_PREFIXES = ("character/texture/", "ui/texture/", "character/descriptors/pbd/")


def _hair_reader(entries, files, tracker):
    def read(path):
        key = path.replace("\\", "/").casefold()
        if key not in files:
            item = entries.get(key)
            if item is None or item.orig_size > 128 * 1024 * 1024:
                raise ValueError(f"Missing or oversized hair dependency: {path}")
            files[key] = tracker.read(item)
        return files[key]
    return read


def _read_additive_donor(read, profile, donor_path: str):
    """Read and check everything Add New Barber Hairstyle copies from the donor.

    Shared by the export and by the check when Hair Tools opens a hairstyle, so a
    donor the export would refuse is reported before any grooming.
    """
    choices = read_hair_choices(read(profile.mesh_param_path))
    donor_stem = PurePosixPath(donor_path).stem.lower()
    choice = next((row for row in choices if row.usable and row.prefab_stem == donor_stem), None)
    if choice is None:
        raise ValueError(
            f"This hairstyle is not in the game's own barber list for {profile.name}; it may come from another mod. "
            "Add New Barber Hairstyle copies one of the game's hairstyle slots. Use Replace Existing Hairstyle "
            "to edit this one, or start from one of the game's hairstyles.")
    table = parse_pappt(read(PART_PREFAB_TABLE))
    record = table.find(donor_stem)
    if record is None:
        raise ValueError("The donor hair prefab registration is missing.")
    validate_hair_prefab_donor(read(record.prefab_path), donor_path)
    read(donor_path)
    physics_path = donor_path.replace("character/model/", "character/bin__/meshphysics/", 1)[:-4] + ".hkx"
    try:
        read(physics_path)
    except ValueError:
        raise ValueError(f"This hairstyle has no hair physics file ({physics_path}), which a new barber "
                         "hairstyle copies.") from None
    material_path = donor_path.replace("character/model/", "character/modelproperty/", 1) + "_xml"
    root, textures = material_texture_paths(read(material_path))
    if not textures or {node.get("_pbdSimulationMaterialName") for node in root.iter()
                        if node.get("_pbdSimulationMaterialName")} != {"Hair"}:
        raise ValueError("Required textured Hair material and game physics profile are unavailable.")
    for path in textures:
        read(path)
    return choices, choice


def additive_donor_problem(entry, donor_path: str, character: str, stop_event=None) -> str:
    """Why Add New Barber Hairstyle would refuse this donor, or "" when it would not.

    Read-only, for a worker. Replace Existing Hairstyle does not need these files.
    """
    from cdmw.domain.archives.filters import archive_entry_game_root
    from cdmw.domain.hair_characters import hair_character
    from cdmw.domain.hair_registration import HairRegistrationError
    try:
        root = archive_entry_game_root(entry)
        profile = hair_character(character)
        tracker = SourceTracker(lambda item: read_archive_entry_data(item, stop_event)[0])
        entries, _layers, _mounts = _scan_hair_entries(root, tracker, profile, "", stop_event)
        _read_additive_donor(_hair_reader(entries, {}, tracker), profile,
                             str(donor_path).replace("\\", "/").casefold())
    except (ValueError, OSError, HairRegistrationError, KeyError) as exc:
        return str(exc)
    return ""


def export_hair_package(snapshot, rebuilt, entry, output, *, stop_event=None, on_log=None,
                        package_info=None, create_zip: bool = False,
                        use_dmm_additive_tables: bool = True,
                        target_stem_override: str = "",
                        custom_icon_path: Path | str | None = None,
                        notes: list | None = None):
    """Build and reparse a complete DMM package outside the installed game.

    ``notes`` receives what the user must know beside the built mod.
    """
    from cdmw.domain.archives.filters import archive_entry_game_root
    from cdmw.services.mesh_mod_publish import publish_mesh_mod_output

    root = archive_entry_game_root(entry)
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("Hair output must be a new folder outside the installed game.")
    state = validate_hair_output(snapshot)
    from cdmw.domain.hair_characters import hair_character
    profile = hair_character(state["template"]["character"])
    donor_path = state["template"]["path"].replace("\\", "/").casefold()
    new_stem = str(target_stem_override or "").strip() or state["template"]["target_stem"]
    validate_hair_stem(new_stem)
    if custom_icon_path is not None and str(custom_icon_path).strip():
        icon_source = Path(custom_icon_path)
        if not icon_source.is_file():
            raise ValueError(f"Custom barber icon not found: {icon_source}")
    else:
        icon_source = None
    tracker = SourceTracker(lambda item: read_archive_entry_data(item, stop_event)[0])
    entries, dlc_layers, mount_bytes = _scan_hair_entries(root, tracker, profile, new_stem, stop_event, on_log)
    files = {}
    read = _hair_reader(entries, files, tracker)
    choices, choice = _read_additive_donor(read, profile, donor_path)
    donor_stem = PurePosixPath(donor_path).stem.lower()
    icon_donor_path = icon_donor_for(choices, choice.index)
    donor_icon_bytes = read(icon_donor_path)
    _apply_dmm_mounted_hair_sources(
        root, entry, files, tracker,
        donor_path=donor_path, donor_stem=donor_stem, profile=profile,
        original_data=snapshot.original_data,
    )
    config = parse_pbd_config_materials(read(PBD_CONFIG).decode("utf-8-sig"))
    if "hair" not in config:
        raise ValueError("The donor game Hair physics profile is missing.")
    read("character/descriptors/pbd/" + config["hair"].filename.replace("\\", "/"))
    custom_icon_dds = encode_hair_icon_dds(icon_source, donor_icon_bytes, stop_event=stop_event) if icon_source else None
    pathc_bytes = (root / "meta/0.pathc").read_bytes()
    # A DLC registers its own copies of base textures; donors it replaces take that registration.
    dlc_registries = []
    for layer, _rows in dlc_layers:
        if (layer / "meta/0.pathc").is_file():
            tracker.pin_file(layer / "meta/0.pathc")
            dlc_registries.append(parse_pathc((layer / "meta/0.pathc").read_bytes()))
    plan, pathc, texture_donors = prepare_authored_hair(
        snapshot, rebuilt, files, entries, pathc_bytes, reference_tables=tuple(dlc_registries),
        target_stem_override=new_stem, custom_icon_dds=custom_icon_dds,
    )
    revision = tracker.capture()
    revision.validate(stop_event)
    plan.check_sources(files)
    overrides = {file.path.casefold(): file.data for file in rebuilt.companion_files}

    default_title = f"{profile.name} - {state['style_name']}"
    default_description = "An additional authored hairstyle. In-game selection, save/load and motion checks are pending."
    title = (str(getattr(package_info, "title", "") or "").strip() or default_title)
    version = (str(getattr(package_info, "version", "") or "").strip() or "1.0")
    author = str(getattr(package_info, "author", "") or "").strip()
    description = (str(getattr(package_info, "description", "") or "").strip() or default_description)

    xml_patch_bytes = None
    pappt_targets = ()
    if use_dmm_additive_tables:
        from cdmw.services.dmm_part_table import part_operations
        replacement_map = {item.path: item.data for item in plan.replacements}
        pappt_payload = replacement_map[PART_PREFAB_TABLE]
        mesh_param_payload = replacement_map[profile.mesh_param_path]
        xml_patch_bytes = build_hair_choice_xml_patch(files[profile.mesh_param_path], mesh_param_payload)
        part_input = {PART_PREFAB_TABLE: pappt_payload, **{item.path: item.data for item in plan.additions}}
        _remaining, pappt_targets = part_operations(part_input, lambda p: files.get(str(p or "").replace("\\", "/").casefold()))
        if not pappt_targets:
            raise ValueError("Additive DMM registration produced no partprefabtable operations.")
        archive_replacements = tuple(
            item for item in plan.replacements if item.path not in {PART_PREFAB_TABLE, profile.mesh_param_path}
        )
    else:
        archive_replacements = plan.replacements

    patches = tuple(ArchivePatchRequest(entries[item.path], item.data) for item in archive_replacements)
    normalized_additions = []
    wanted = {item.path: item.data for item in archive_replacements}
    for item in plan.additions:
        if item.path in texture_donors:
            template_key = texture_donors[item.path]
        else:
            template_key = item.path.replace(new_stem, donor_stem)
        if template_key is None:
            payload_data = item.data
            flags = _PLAIN_DDS_FLAGS
            if item.path.casefold().endswith(".dds"):
                payload_data = with_stored_mip_sizes(payload_data)
            req = ArchiveAddRequest(Path(), item.path, payload_data, flags)
        else:
            template_entry = entries.get(template_key)
            if template_entry is None:
                raise ValueError(f"Missing template archive metadata for {item.path}")
            payload_data = item.data
            flags = int(template_entry.flags)
            if item.path.casefold().endswith(".dds"):
                was_overridden = (template_key in overrides) or (
                    custom_icon_dds is not None and template_key == plan.icon_donor.casefold()
                )
                payload_data, flags = _normalize_hair_dds_for_dmm(payload_data, template_entry, overridden=was_overridden)
            req = ArchiveAddRequest.from_template(template_entry, item.path, payload_data)
            req.flags = flags
        normalized_additions.append(req)
        wanted[item.path] = payload_data
    additions = tuple(normalized_additions)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-hair-", dir=output.parent))
    try:
        shared = export_archive_overlay_package(patches, additions, package_root=stage, game_root=root,
            metadata_files=(("meta/0.pathc", pathc),), for_dmm=True, stop_event=stop_event, on_log=on_log)
        packaged = parse_archive_pamt(stage / shared.group / "0.pamt")
        if len(packaged) != len(wanted):
            raise ValueError("The hair archive contains an incomplete or duplicate bundle.")
        for item in packaged:
            if read_archive_entry_data(item, stop_event)[0] != wanted[item.path]:
                raise ValueError(f"Hair package payload failed reparsing: {item.path}")
        patch_rel = profile.mesh_param_path + ".patch"
        if use_dmm_additive_tables:
            from cdmw.services.dmm_send import write_operations
            write_operations(stage, title, pappt_targets, description=HAIR_REGISTRATION_DESCRIPTION)
            patch_target = stage / patch_rel
            patch_target.parent.mkdir(parents=True, exist_ok=True)
            patch_target.write_bytes(xml_patch_bytes)
        manifest = {
            "format": "v1", "schema_version": 1, "kind": "archive_override_mod",
            "name": title, "title": title, "game": "Crimson Desert",
            "target_game": shared.target_game, "version": version,
            "author": author, "description": description,
            "generator": "Crimson Desert Mod Workbench",
            "table_mode": "dmm_additive" if use_dmm_additive_tables else "full_tables",
            "files_dir": ".", "manager_targets": ["dmm"],
            "structure": "archive_group", "archive_group": shared.group,
            "file_count": shared.file_count, "overrides": list(shared.paths),
        }
        if use_dmm_additive_tables:
            manifest["xml_patch"] = patch_rel
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        evidence = {"format": "cdmw_hair_output_v1", "runtime_verified": False,
            "table_mode": manifest["table_mode"],
            "target_stem": new_stem,
            "choice_index": plan.choice_index, "hair_revision": state["revision"], "donor": state["template"],
            "source_revision": revision.manifest(), "roundtrip_files": len(wanted),
            "files": {path: hashlib.sha256(data).hexdigest() for path, data in wanted.items()}}
        (stage / "hair-authoring.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        revision.validate(stop_event)
        if (root / "meta/0.pathc").read_bytes() != pathc_bytes or (root / "meta/0.papgt").read_bytes() != mount_bytes:
            raise ValueError("The game registries changed while building hair.")
        raise_if_cancelled(stop_event, "Hair package cancelled before publication.")
        publish_mesh_mod_output(stage, output, manager_profile="dmm", create_zip=bool(create_zip), stop_event=stop_event)
        if notes is not None and use_dmm_additive_tables:
            notes.append(hair_dmm_entries_note(title))
            if _served_barber_slot_conflict(root, profile, plan.choice_index):
                notes.append(_barber_slot_note(profile, plan.choice_index))
        return output
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def export_hair_to_dmm(mods_dir: Path | str, title: str, build_staged, *, stop_event=None,
                       notes: list | None = None) -> tuple[Path, bool]:
    """Build a hair mod outside DMM's mods folder and atomically publish/replace it inside.

    ``notes`` also receives a warning when another mod in the folder adds a
    hairstyle at the same barber slot.
    """
    from cdmw.services import dmm_send

    mods = Path(mods_dir)
    folder, replaced = dmm_send.destination(mods, title)
    staging_parent = mods.parent if mods.parent != mods else Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix=".cdmw-hair-send-", dir=staging_parent) as staging:
        staged = Path(staging) / folder.name
        build_staged(staged)
        raise_if_cancelled(stop_event, "Send to DMM cancelled.")
        conflicts, index, character = _staged_slot(staged, mods, folder)
        dmm_send.destination(mods, title)
        dmm_send._publish(staged, folder, Path(staging))
    if notes is not None and conflicts:
        verb = "adds" if len(conflicts) == 1 else "add"
        notes.append(f"{', '.join(conflicts)} also {verb} a hairstyle at barber slot {index} for {character}. "
                     "How the game handles two hairstyles at one slot is not checked yet; until it is, "
                     "enable only one of these mods.")
    return folder, replaced


def _staged_slot(staged: Path, mods: Path, folder: Path) -> tuple[tuple[str, ...], int, str]:
    """Other DMM mods inserting a hairstyle at the staged hairstyle's barber slot."""
    try:
        manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))
        evidence = json.loads((staged / "hair-authoring.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (), 0, ""
    patch_rel, index = manifest.get("xml_patch"), evidence.get("choice_index")
    if not isinstance(patch_rel, str) or type(index) is not int:
        return (), 0, ""
    character = str((evidence.get("donor") or {}).get("character") or "this character")
    return additive_hair_slot_conflicts(mods, folder, patch_rel, index), index, character
