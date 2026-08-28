"""Archive path and mutation safety rules owned outside UI widgets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "aux",
        "clock$",
        "con",
        "conin$",
        "conout$",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
        *(f"com{index}" for index in "¹²³"),
        *(f"lpt{index}" for index in "¹²³"),
    }
)
_WINDOWS_INVALID_CHARACTERS = frozenset('<>:"|?*')


@dataclass(frozen=True, slots=True)
class ArchiveMutationSafety:
    """Safety contract required before an archive mutation may run."""

    description: str
    requires_confirmation: bool = True
    requires_backup: bool = True
    recoverable: bool = True


def require_explicit_archive_mutation(description: str) -> ArchiveMutationSafety:
    """Return the default safety contract for destructive archive work."""

    return ArchiveMutationSafety(description=str(description or "archive mutation").strip())


def safe_archive_output_path(
    root: Path,
    relative_path: str | Path,
    *,
    error_message: str,
    single_component: bool = False,
) -> Path:
    """Return a filesystem target only when an archive-owned path stays below ``root``."""

    raw_path = str(relative_path or "")
    normalized = raw_path.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(normalized)
    parts = tuple(part for part in normalized.split("/") if part)
    invalid_component = any(
        part in {".", ".."}
        or part.endswith((" ", "."))
        or any(character in _WINDOWS_INVALID_CHARACTERS or ord(character) < 32 for character in part)
        or part.rstrip(" .").split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        for part in parts
    )
    if (
        not parts
        or posix_path.is_absolute()
        or bool(windows_path.drive)
        or bool(windows_path.root)
        or invalid_component
        or (single_component and (len(parts) != 1 or normalized != parts[0]))
    ):
        raise ValueError(error_message)

    root_path = Path(root)
    target = root_path.joinpath(*parts)
    try:
        target.resolve(strict=False).relative_to(root_path.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(error_message) from exc
    return target


__all__ = [
    "ArchiveMutationSafety",
    "require_explicit_archive_mutation",
    "safe_archive_output_path",
]
