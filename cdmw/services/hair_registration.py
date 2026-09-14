"""Prepare playable-character barber registration entirely in memory.

This clones source geometry and physics. It is not hair authoring, and successful
preparation does not establish that the game accepts or persists the new choice.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath

from cdmw.core.pappt_format import encode_pappt, insert_part_prefabs, parse_pappt
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.core.prefab_binary_edit import rewrite_prefab_paths_any_length
from cdmw.domain.hair_registration import (
    HairRegistrationError, append_hair_choice, read_hair_choices, validate_hair_stem,
)
from cdmw.domain.hair_characters import hair_character


DAMIANE_MESH_PARAM = "character/descriptors/customizationmeta/meshparam_example_damian.xml"
PART_PREFAB_TABLE = "character/bin__/partprefabtable.pappt"


@dataclass(frozen=True, slots=True)
class HairRegistrationFile:
    path: str
    data: bytes


@dataclass(frozen=True, slots=True)
class HairRegistrationPlan:
    choice_index: int
    prefab_stem: str
    replacements: tuple[HairRegistrationFile, ...]
    additions: tuple[HairRegistrationFile, ...]
    source_sha256: tuple[tuple[str, str], ...]

    def check_sources(self, files: Mapping[str, bytes]) -> None:
        current = _source_files(files)
        for path, expected in self.source_sha256:
            if path not in current or hashlib.sha256(current[path]).hexdigest() != expected:
                raise HairRegistrationError(f"Hair registration source changed: {path}")


def _path(path: str) -> str:
    normalized = str(path).replace("\\", "/").lower()
    if (not normalized or ":" in normalized or "\x00" in normalized or
            any(part in {"", ".", ".."} for part in normalized.split("/"))):
        raise HairRegistrationError(f"Invalid archive-relative path: {path}")
    return normalized


def _source_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    result = {}
    for name, payload in files.items():
        key = _path(name)
        if key in result:
            raise HairRegistrationError(f"Ambiguous source ownership: {name}")
        if not isinstance(payload, bytes) or not payload:
            raise HairRegistrationError(f"Missing prepared source bytes: {name}")
        result[key] = payload
    return result


def validate_hair_prefab_donor(prefab: bytes, mesh_path: str) -> None:
    """Gate multi-mesh and alias registrations before a hairstyle is opened."""
    resources = tuple(_path(item.text) for item in decode_prefab_binary(prefab).resource_strings())
    if len(resources) != 1:
        raise HairRegistrationError("This registered hairstyle uses multiple PAC meshes. Hair authoring currently requires a single-mesh hairstyle; choose another base.")
    if resources != (_path(mesh_path),):
        raise HairRegistrationError("This registration points to a different PAC mesh. Choose another verified base hairstyle.")


def prepare_damiane_hair_registration(
    source_files: Mapping[str, bytes], *, new_stem: str, existing_paths: Collection[str],
    template_index: int = 0,
) -> HairRegistrationPlan:
    """Compatibility entry for the original Damiane registration workflow."""
    return prepare_hair_registration(source_files, new_stem=new_stem, existing_paths=existing_paths,
                                     template_index=template_index, character="Damiane")


def prepare_hair_registration(
    source_files: Mapping[str, bytes], *, new_stem: str, existing_paths: Collection[str],
    template_index: int = 0, character: str = "Damiane",
) -> HairRegistrationPlan:
    """Use the active source snapshot and an authoritative target-path inventory.

    The caller resolves mounted precedence and supplies prepared bytes. Inactive
    archive copies must never be mixed into the snapshot. No file is written.
    """
    profile = hair_character(character)
    validate_hair_stem(new_stem)
    files = _source_files(source_files)
    used = set()

    def source(path):
        key = _path(path)
        if key not in files:
            raise HairRegistrationError(f"Missing hair registration dependency: {path}")
        used.add(key)
        return files[key]

    choices = read_hair_choices(source(profile.mesh_param_path))
    if isinstance(template_index, bool) or not isinstance(template_index, int) or not 0 <= template_index < len(choices):
        raise HairRegistrationError("The template hair choice does not exist.")
    donor = choices[template_index]
    table_bytes = source(PART_PREFAB_TABLE)
    table = parse_pappt(table_bytes)
    if encode_pappt(table) != table_bytes:
        raise HairRegistrationError("The active prefab table does not round-trip exactly.")
    donors = [row for row in table.records if row.stem.casefold() == donor.prefab_stem.casefold()]
    if len(donors) != 1 or tuple(part.name for part in donors[0].parts) != ("CD_Hair",):
        raise HairRegistrationError("The template must resolve to one CD_Hair prefab record.")
    if any(row.stem.casefold() == new_stem for row in (*table.records, *table.head_records)):
        raise HairRegistrationError("The new hair name already exists in the prefab table.")
    record = donors[0]
    prefab = source(record.prefab_path)
    resources = tuple(item.text for item in decode_prefab_binary(prefab).resource_strings())
    validate_hair_prefab_donor(prefab, profile.hair_root + donor.prefab_stem + ".pac")
    mesh_path = _path(resources[0])
    if not profile.accepts_hair(mesh_path):
        raise HairRegistrationError("The donor does not belong to the selected character's hair family.")
    material_path = mesh_path.replace("character/model/", "character/modelproperty/", 1) + "_xml"
    physics_path = mesh_path.replace("character/model/", "character/bin__/meshphysics/", 1)[:-4] + ".hkx"
    new_mesh = str(PurePosixPath(mesh_path).with_name(new_stem + ".pac"))
    new_icon = str(PurePosixPath(_path(donor.icon_path)).with_name(new_stem + ".dds"))
    rewrite = rewrite_prefab_paths_any_length(prefab, {resources[0]: new_mesh})
    if tuple(item.text for item in decode_prefab_binary(rewrite.data).resource_strings()) != (new_mesh,):
        raise HairRegistrationError("The cloned prefab did not retain the new mesh reference.")
    additions = (
        HairRegistrationFile(record.cloned(new_stem).prefab_path, rewrite.data),
        HairRegistrationFile(new_mesh, source(mesh_path)),
        HairRegistrationFile(str(PurePosixPath(material_path).with_name(new_stem + ".pac_xml")), source(material_path)),
        HairRegistrationFile(str(PurePosixPath(physics_path).with_name(new_stem + ".hkx")), source(physics_path)),
        HairRegistrationFile(new_icon, source(donor.icon_path)),
    )
    occupied = {_path(path) for path in existing_paths} | files.keys()
    for addition in additions:
        if _path(addition.path) in occupied:
            raise HairRegistrationError(f"A new hair asset would overwrite an existing path: {addition.path}")
    appended = append_hair_choice(source(profile.mesh_param_path), template_index=template_index,
                                  prefab_stem=new_stem, icon_path=new_icon)
    updated = insert_part_prefabs(table, (record.cloned(new_stem),))
    encoded = encode_pappt(updated)
    if parse_pappt(encoded) != updated or updated.records[:-1] != table.records:
        raise HairRegistrationError("The updated prefab table changed existing records.")
    replacements = (HairRegistrationFile(profile.mesh_param_path, appended.data),
                    HairRegistrationFile(PART_PREFAB_TABLE, encoded))
    return HairRegistrationPlan(appended.choice.index, new_stem, replacements, additions,
                                tuple((path, hashlib.sha256(files[path]).hexdigest()) for path in sorted(used)))
