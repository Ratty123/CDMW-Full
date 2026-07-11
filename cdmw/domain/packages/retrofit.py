"""Immutable package-retrofit models shared by core, workers, and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from cdmw.domain.packages.export_policy import MOD_PACKAGE_MANAGER_PROFILES
from cdmw.models import ModPackageInfo


KNOWN_RETROFIT_CONTENT_ROOTS = frozenset(
    {"character", "effect", "gamedata", "leveldata", "meta", "object", "tree", "ui", "vehicle", "world"}
)
RETROFIT_MANAGER_PROFILES = MOD_PACKAGE_MANAGER_PROFILES


@dataclass(frozen=True, slots=True)
class RetrofittableModPackage:
    root: Path
    name: str
    kind: str
    package_info: ModPackageInfo
    payload_paths: tuple[str, ...]
    existing_metadata: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    manifest: Mapping[str, object] = field(default_factory=dict)
    modinfo: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModPackageRetrofitResult:
    source_root: Path
    output_root: Path
    package_root: Path
    zip_path: Path
    manager_profile: str
    metadata_files: tuple[Path, ...]
    payload_paths: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    repaired_path_count: int = 0
    unresolved_path_count: int = 0
    ambiguous_path_count: int = 0


@dataclass(frozen=True, slots=True)
class RetrofitPayloadMapping:
    source_path: str
    target_path: str
    package_group: str = ""
    is_new: bool = False
    status: str = "unchanged"
    message: str = ""
    binary_status: str = ""
    binary_note: str = ""


@dataclass(frozen=True, slots=True)
class RetrofitPathRepairSummary:
    mappings: tuple[RetrofitPayloadMapping, ...]
    repaired_path_count: int = 0
    unresolved_path_count: int = 0
    ambiguous_path_count: int = 0
    binary_size_mismatch_count: int = 0
    binary_size_match_count: int = 0
    binary_size_unknown_count: int = 0
    binary_exact_match_count: int = 0
    binary_exact_mismatch_count: int = 0
    binary_exact_unknown_count: int = 0
    warnings: tuple[str, ...] = ()
    package_game_build: str = ""
    current_game_build: str = ""
    build_match_status: str = "unknown"


__all__ = [
    "KNOWN_RETROFIT_CONTENT_ROOTS",
    "RETROFIT_MANAGER_PROFILES",
    "ModPackageRetrofitResult",
    "RetrofitPathRepairSummary",
    "RetrofitPayloadMapping",
    "RetrofittableModPackage",
]
