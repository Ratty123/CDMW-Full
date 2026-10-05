"""Private startup profiles; portable item packages keep their existing format."""
from dataclasses import dataclass
from pathlib import Path


class VirtualLoaderError(ValueError):
    pass


@dataclass(frozen=True)
class VirtualProfile:
    packages: tuple[Path, ...] = ()
    mods: tuple[Path, ...] = ()


@dataclass(frozen=True)
class PreparedSnapshot:
    root: Path
    generation: str
    files: tuple[tuple[str, bytes], ...]
    registry: bytes
    profile: bytes
    observed: tuple[tuple[str, bytes | None], ...]
    source_revision: object
    external: object
    summary: tuple[str, ...]
    retained_packages: tuple[tuple[str, bytes], ...] = ()


@dataclass(frozen=True)
class VirtualLaunchPlan:
    root: Path
    generation: str
    executable: Path
    executable_sha256: str
    snapshot: Path
    manifest_sha256: str


@dataclass(frozen=True)
class VirtualSessionStatus:
    state: str
    detail: str
    generation: str = ''
    pid: int | None = None
