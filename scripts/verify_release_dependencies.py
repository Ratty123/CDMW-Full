from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONSTRAINTS = REPO_ROOT / "constraints-release.txt"
SUPPORTED_PYTHON_RELEASES = ((3, 11), (3, 14))
_EXACT_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^;\s]+)$")


def canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value).strip()).lower()


def read_exact_constraints(path: Path) -> dict[str, tuple[str, str]]:
    pins: dict[str, tuple[str, str]] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = _EXACT_PIN.fullmatch(line)
        if match is None:
            raise ValueError(f"{path}:{line_number}: release constraints require exact name==version pins")
        display_name, expected_version = match.groups()
        key = canonical_distribution_name(display_name)
        if key in pins:
            raise ValueError(f"{path}:{line_number}: duplicate release constraint for {display_name}")
        pins[key] = (display_name, expected_version)
    if not pins:
        raise ValueError(f"{path}: no release dependency pins were found")
    return pins


def release_dependency_mismatches(
    pins: Mapping[str, tuple[str, str]],
    *,
    version_getter: Callable[[str], str] = metadata.version,
) -> tuple[str, ...]:
    mismatches: list[str] = []
    for _key, (display_name, expected_version) in sorted(pins.items()):
        try:
            actual_version = version_getter(display_name)
        except metadata.PackageNotFoundError:
            mismatches.append(f"{display_name}: missing (expected {expected_version})")
            continue
        if actual_version != expected_version:
            mismatches.append(f"{display_name}: installed {actual_version}, expected {expected_version}")
    return tuple(mismatches)


def verify_release_environment(constraints_path: Path) -> tuple[str, ...]:
    release = sys.version_info[:2]
    errors: list[str] = []
    if release not in SUPPORTED_PYTHON_RELEASES:
        supported = ", ".join(f"{major}.{minor}" for major, minor in SUPPORTED_PYTHON_RELEASES)
        errors.append(f"Python {release[0]}.{release[1]} is not a tested release interpreter; expected {supported}")
    errors.extend(release_dependency_mismatches(read_exact_constraints(constraints_path)))
    return tuple(errors)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the exact Python environment used for release packaging.")
    parser.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        errors = verify_release_environment(args.constraints.expanduser().resolve())
    except (OSError, ValueError) as exc:
        print(f"Release dependency verification failed: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("Release dependency verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        print(
            f"Install with: python -m pip install -c {args.constraints} -r requirements-build.txt",
            file=sys.stderr,
        )
        return 1
    release = sys.version_info[:2]
    print(
        f"Verified {len(read_exact_constraints(args.constraints))} release pins on Python "
        f"{release[0]}.{release[1]}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
