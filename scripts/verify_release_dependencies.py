from __future__ import annotations

import argparse
import platform
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Callable, Mapping, Sequence

from packaging.markers import InvalidMarker, Marker
from packaging.requirements import InvalidRequirement, Requirement


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONSTRAINTS = REPO_ROOT / "constraints-release.txt"
DEFAULT_RELEASE_LOCK = REPO_ROOT / "requirements-build.txt"
SUPPORTED_PYTHON_RELEASES = ((3, 11), (3, 14))
SUPPORTED_RELEASE_PLATFORM = ("Windows", "AMD64")
_EXACT_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^;\s]+)(?:\s*;\s*(.+))?$")
_SHA256_HASH = re.compile(r"(?:^|\s)--hash=sha256:([0-9a-fA-F]{64})(?=\s|$)")
_REQUIRED_LOCK_OPTIONS = frozenset({"--only-binary :all:", "--require-hashes"})


def canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value).strip()).lower()


def _marker_applies(marker_text: str) -> bool:
    if not marker_text:
        return True
    try:
        return Marker(marker_text).evaluate({"extra": ""})
    except InvalidMarker as exc:
        raise ValueError(f"invalid release environment marker: {marker_text}") from exc


def read_exact_constraints(path: Path) -> dict[str, tuple[str, str]]:
    pins: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = _EXACT_PIN.fullmatch(line)
        if match is None:
            raise ValueError(f"{path}:{line_number}: release constraints require exact name==version pins")
        display_name, expected_version, marker_text = match.groups()
        key = canonical_distribution_name(display_name)
        if key in seen:
            raise ValueError(f"{path}:{line_number}: duplicate release constraint for {display_name}")
        seen.add(key)
        if not _marker_applies(str(marker_text or "")):
            continue
        pins[key] = (display_name, expected_version)
    if not pins:
        raise ValueError(f"{path}: no release dependency pins were found")
    return pins


def read_hashed_release_lock(path: Path) -> dict[str, tuple[str, str, tuple[str, ...]]]:
    pins: dict[str, tuple[str, str, tuple[str, ...]]] = {}
    seen: set[str] = set()
    options: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("--"):
            if line not in _REQUIRED_LOCK_OPTIONS:
                raise ValueError(f"{path}:{line_number}: unsupported release lock option: {line}")
            options.add(line)
            continue
        hashes = tuple(match.lower() for match in _SHA256_HASH.findall(line))
        requirement_text = _SHA256_HASH.sub("", line).strip()
        try:
            requirement = Requirement(requirement_text)
        except InvalidRequirement as exc:
            raise ValueError(f"{path}:{line_number}: invalid locked requirement") from exc
        specifiers = tuple(requirement.specifier)
        if (
            requirement.url is not None
            or requirement.extras
            or len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
        ):
            raise ValueError(f"{path}:{line_number}: release lock requires exact name==version pins")
        if not hashes:
            raise ValueError(f"{path}:{line_number}: release lock entry has no SHA-256 hash")
        key = canonical_distribution_name(requirement.name)
        if key in seen:
            raise ValueError(f"{path}:{line_number}: duplicate release lock entry for {requirement.name}")
        seen.add(key)
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
            continue
        pins[key] = (requirement.name, specifiers[0].version, hashes)
    missing_options = sorted(_REQUIRED_LOCK_OPTIONS - options)
    if missing_options:
        raise ValueError(f"{path}: release lock is missing required option(s): {', '.join(missing_options)}")
    if not pins:
        raise ValueError(f"{path}: no active release lock entries were found")
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


def release_dependency_pin_gaps(
    pins: Mapping[str, tuple[str, str]],
    *,
    distribution_getter: Callable[[str], metadata.Distribution] = metadata.distribution,
) -> tuple[str, ...]:
    gaps: set[tuple[str, str]] = set()
    for key, (display_name, _expected_version) in sorted(pins.items()):
        try:
            requirements = distribution_getter(display_name).requires or ()
        except metadata.PackageNotFoundError:
            continue
        for raw_requirement in requirements:
            try:
                requirement = Requirement(raw_requirement)
            except InvalidRequirement as exc:
                raise ValueError(f"{display_name}: invalid installed dependency metadata") from exc
            if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
                continue
            dependency_key = canonical_distribution_name(requirement.name)
            if dependency_key not in pins:
                gaps.add((key, dependency_key))
    return tuple(
        f"{pins[parent][0]}: active dependency {dependency} is not pinned in the release lock"
        for parent, dependency in sorted(gaps)
    )


def verify_release_environment(
    constraints_path: Path,
    lock_path: Path = DEFAULT_RELEASE_LOCK,
) -> tuple[str, ...]:
    release = sys.version_info[:2]
    errors: list[str] = []
    if release not in SUPPORTED_PYTHON_RELEASES:
        supported = ", ".join(f"{major}.{minor}" for major, minor in SUPPORTED_PYTHON_RELEASES)
        errors.append(f"Python {release[0]}.{release[1]} is not a tested release interpreter; expected {supported}")
    actual_platform = (platform.system(), platform.machine())
    if tuple(value.casefold() for value in actual_platform) != tuple(
        value.casefold() for value in SUPPORTED_RELEASE_PLATFORM
    ):
        errors.append(
            f"Release lock targets {SUPPORTED_RELEASE_PLATFORM[0]} {SUPPORTED_RELEASE_PLATFORM[1]}; "
            f"current platform is {actual_platform[0]} {actual_platform[1]}"
        )
    constraints = read_exact_constraints(constraints_path)
    locked = read_hashed_release_lock(lock_path)
    lock_pins = {key: (display_name, version) for key, (display_name, version, _hashes) in locked.items()}
    for key in sorted(set(constraints) | set(lock_pins)):
        if key not in constraints:
            errors.append(f"{lock_pins[key][0]}: release lock entry has no matching constraint")
        elif key not in lock_pins:
            errors.append(f"{constraints[key][0]}: release constraint has no hashed lock entry")
        elif constraints[key][1] != lock_pins[key][1]:
            errors.append(
                f"{constraints[key][0]}: constraint {constraints[key][1]}, "
                f"release lock {lock_pins[key][1]}"
            )
    errors.extend(release_dependency_mismatches(lock_pins))
    errors.extend(release_dependency_pin_gaps(lock_pins))
    return tuple(errors)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the exact Python environment used for release packaging.")
    parser.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
    parser.add_argument("--lock", type=Path, default=DEFAULT_RELEASE_LOCK)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        errors = verify_release_environment(
            args.constraints.expanduser().resolve(),
            args.lock.expanduser().resolve(),
        )
    except (OSError, ValueError) as exc:
        print(f"Release dependency verification failed: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("Release dependency verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        print(
            f"Install with: python -m pip install -c {args.constraints} -r {args.lock}",
            file=sys.stderr,
        )
        return 1
    release = sys.version_info[:2]
    locked = read_hashed_release_lock(args.lock)
    print(
        f"Verified {len(locked)} hashed release pins on Python "
        f"{release[0]}.{release[1]}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
