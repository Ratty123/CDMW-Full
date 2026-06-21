from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


def validate_choice(value: str, allowed: Sequence[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"Unsupported {label}: {value}")
    return value


def normalize_required_path(value: str, label: str) -> Path:
    raw = value.strip()
    if not raw:
        raise ValueError(f"{label} is required.")
    return Path(raw).expanduser().resolve()


def normalize_optional_path(value: str) -> Optional[Path]:
    raw = value.strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def ensure_existing_dir(path: Path, label: str) -> Path:
    if not path.exists() or not path.is_dir():
        raise ValueError(f"{label} does not exist or is not a folder: {path}")
    return path


def ensure_existing_file(path: Path, label: str) -> Path:
    if not path.exists() or not path.is_file():
        raise ValueError(f"{label} does not exist or is not a file: {path}")
    return path


def require_existing_dir(path: Optional[Path], label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} is not set.")
    return ensure_existing_dir(path, label)


def require_existing_file(path: Optional[Path], label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} is not set.")
    return ensure_existing_file(path, label)


def parse_filter_patterns(raw_text: str) -> Tuple[str, ...]:
    tokens: List[str] = []
    for line in raw_text.replace("\r", "\n").split("\n"):
        for piece in line.split(";"):
            token = piece.strip()
            if token:
                tokens.append(token)
    return tuple(tokens)


def filter_matches(relative_path: Path, patterns: Sequence[str]) -> bool:
    if not patterns:
        return True

    rel_posix = relative_path.as_posix().lower()
    basename = relative_path.name.lower()
    parent = "" if relative_path.parent == Path(".") else relative_path.parent.as_posix().lower()

    for raw_pattern in patterns:
        pattern = raw_pattern.replace("\\", "/").strip().lower()
        if not pattern:
            continue
        if fnmatch.fnmatch(rel_posix, pattern):
            return True
        if fnmatch.fnmatch(basename, pattern):
            return True
        if parent and fnmatch.fnmatch(parent, pattern):
            return True

        if not any(char in pattern for char in "*?[]"):
            clean = pattern.strip("/")
            if not clean:
                continue
            if rel_posix == clean or basename == clean or parent == clean:
                return True
            if rel_posix.startswith(f"{clean}/"):
                return True

    return False
