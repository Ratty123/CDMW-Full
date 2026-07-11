"""Dependency-free archive and mesh-extension policy constants."""

from __future__ import annotations

from typing import Tuple

ARCHIVE_MESH_EXTENSIONS = {".pam", ".pamlod", ".pac"}
ARCHIVE_AUDIO_PATCH_EXTENSIONS = {".wem", ".wav"}
ARCHIVE_AUDIO_EXPORT_EXTENSIONS = {".wem", ".wav", ".ogg", ".mp3", ".bnk"}
_MESH_IMPORT_ASSET_ROOT_MARKERS = {
    "animation",
    "character",
    "effect",
    "gamedata",
    "leveldata",
    "movie",
    "object",
    "sound",
    "ui",
}
MESH_IMPORT_SIDECAR_EXTENSIONS = {
    ".xml",
    ".pami",
    ".pac_xml",
    ".pam_xml",
    ".pamlod_xml",
    ".app_xml",
    ".prefabdata_xml",
}
MESH_IMPORT_COMPANION_EXTENSIONS = {
    ".prefab",
    ".hkx",
    ".hkt",
    ".meshinfo",
    ".material",
    ".paa_metabin",
}
_MESH_IMPORT_AUTOCOPY_COMPANION_EXTENSIONS = {
    ".pac_xml",
    ".pam_xml",
    ".pamlod_xml",
    ".pami",
    ".xml",
    ".hkx",
    ".hkt",
    ".meshinfo",
}
_MESH_IMPORT_RUNTIME_MESH_EXTENSIONS = {".pac", ".pam", ".pamlod"}
_MESH_IMPORT_TEXTURE_SUFFIXES = ("_basecolor", "_diffuse", "_normal", "_disp", "_height", "_roughness")
_MESH_IMPORT_SHORT_TEXTURE_SUFFIXES = ("_ma", "_mg", "_sp", "_n", "_m", "_o")

_JMM_DESCRIPTOR_ALIAS_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        "character/phm_description_player_kliff.xml",
        "character/descriptors/characterdescription/phm_description_player_kliff.xml",
    ),
)
