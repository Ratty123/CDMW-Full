"""Refuse a packaged CDMW that carries a path from the machine that built it.

Compilers and packagers record where things were on disk: Rust panic locations name the
cargo registry under the user profile, MSVC and .NET write the PDB path into every binary,
and provenance files can name the build folder. A release built on a developer's PC then
publishes that PC's user name and folder layout. This scanner unpacks the package (the
PyInstaller archive, and the compressed module archive inside it) and searches every file
for this machine's own paths in the encodings binaries use.

The needles come from the build machine itself, not from a hardcoded list: the user
profile, the user name as a path segment, the repository and build roots, the Python,
cargo and rustup homes, and the temp folder. A bare user name is not a needle on its own:
it may legitimately be a public publisher name.

Usage: python scripts/check_package_privacy.py <onefile exe or onedir folder> [--root DIR]...
Exit status 1 lists every hit with its file and context.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence


@dataclass(frozen=True)
class Hit:
    member: str
    needle: str
    context: str


def _variants(path: str) -> set[str]:
    """A Windows path as binaries spell it: either slash, JSON-escaped, any case."""

    path = path.rstrip("\\/")
    if len(path) == 2 and path[1] == ":":
        # A bare drive, as when the build runs from a `subst` drive. "W:\" alone occurs by
        # chance in binary data, so look for the folders actually at its root instead.
        drive = Path(path + "\\")
        children = [child.name for child in drive.iterdir()] if drive.is_dir() else []
        return set().union(*(_variants(f"{path}\\{name}") for name in children)) if children else set()
    if len(path) < 4:
        return set()
    back = path.replace("/", "\\")
    forward = path.replace("\\", "/")
    return {back, forward, back.replace("\\", "\\\\")}


def machine_needles(extra_roots: Sequence[str] = ()) -> list[str]:
    """This machine's own paths, which must not appear in a package built here."""

    paths: list[str] = []
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    paths.append(profile)
    for name in ("CARGO_HOME", "RUSTUP_HOME", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA",
                 "VCPKG_ROOT"):
        if os.environ.get(name):
            paths.append(os.environ[name])
    paths.append(sys.base_prefix)
    paths.append(sys.prefix)
    paths.extend(extra_roots)
    needles: set[str] = set()
    for path in paths:
        needles |= _variants(str(path))
    user = os.environ.get("USERNAME") or Path(profile).name
    if user:
        # The user name only as part of a profile path, wherever the profile drive is.
        for sep in ("\\", "/", "\\\\"):
            needles.add(f"{sep}Users{sep}{user}{sep}")
    return sorted(needles, key=len, reverse=True)


def _encodings(needle: str) -> Iterator[bytes]:
    lowered = needle.lower()
    yield lowered.encode("utf-8")
    yield lowered.encode("utf-16-le")


def scan_bytes(member: str, data: bytes, needles: Sequence[str]) -> list[Hit]:
    haystack = data.lower()
    hits: list[Hit] = []
    for needle in needles:
        for encoded in _encodings(needle):
            at = haystack.find(encoded)
            if at < 0:
                continue
            start, end = max(0, at - 40), min(len(data), at + len(encoded) + 60)
            snippet = data[start:end]
            if b"\x00" in encoded:
                snippet = snippet.replace(b"\x00", b"")
            hits.append(Hit(member, needle, snippet.decode("latin-1", "replace")
                            .replace("\n", " ").replace("\r", " ")))
            break
    return hits


def _pyinstaller_members(exe: Path, scratch: Path) -> Iterator[tuple[str, bytes]]:
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    archive = CArchiveReader(str(exe))
    for name, entry in archive.toc.items():
        typecode = entry[-1]
        if typecode == "z":
            # The module archive: write it out once and decompress every module.
            data = archive.extract(name)
            path = scratch / "embedded.pyz"
            path.write_bytes(data)
            modules = ZlibArchiveReader(str(path))
            for module in modules.toc:
                code = modules.extract(module, raw=True)
                if code is not None:
                    yield f"{name}/{module}", code
            continue
        data = archive.extract(name)
        if data is not None:
            yield name, data


def package_members(target: Path) -> Iterator[tuple[str, bytes]]:
    with tempfile.TemporaryDirectory(prefix="cdmw-privacy-") as scratch:
        if target.is_file():
            yield target.name, target.read_bytes()
            yield from _pyinstaller_members(target, Path(scratch))
            return
        for path in sorted(p for p in target.rglob("*") if p.is_file()):
            relative = path.relative_to(target).as_posix()
            yield relative, path.read_bytes()
            if path.suffix.lower() == ".pyz":
                from PyInstaller.archive.readers import ZlibArchiveReader
                modules = ZlibArchiveReader(str(path))
                for module in modules.toc:
                    code = modules.extract(module, raw=True)
                    if code is not None:
                        yield f"{relative}/{module}", code


def scan_package(target: Path, needles: Sequence[str]) -> list[Hit]:
    hits: list[Hit] = []
    for member, data in package_members(target):
        hits.extend(scan_bytes(member, data, needles))
    return hits


def _summary(hits: Iterable[Hit]) -> str:
    lines = []
    for hit in hits:
        lines.append(f"  {hit.member}: {hit.needle!r}  ...{hit.context}...")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", type=Path, help="Onefile exe or onedir package folder.")
    parser.add_argument("--root", action="append", default=[],
                        help="Another local folder that must not appear (repository, build root).")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    needles = machine_needles(args.root)
    hits = scan_package(args.target, needles)
    if hits:
        members = len({hit.member for hit in hits})
        print(f"Local build paths found in {members} packaged file(s):\n{_summary(hits)}")
        return 1
    print(f"No local build paths in {args.target.name} ({len(needles)} path forms checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
