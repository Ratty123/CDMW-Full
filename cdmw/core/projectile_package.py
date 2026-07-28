"""Reader and writer for `.paprojdesc`, the projectile package description.

One file ships: `actionchart/bin__/description/projectilepackagedescription.paprojdesc`,
139 bytes. It is the index that says which projectile-info modules each package loads, and
it is the compiled form of `actionchart/xml/description/projectilepackagedescription.xml`,
which ships alongside it and is what confirmed every field here.

    u16 count                       strings in the table
    count x string                  u8 (length + 1), ASCII, then a NUL
    u32 package_count
    u32 module_total                across every package
    package_count x package
    module_total x u16              index into the string table

    package:
        u8  module_count
        u8  flag                    1 in the shipped file
        u16 first_module            slot in the module list below
        u16 name                    index into the string table

Strings use the `.paac` convention -- the length byte counts a trailing NUL -- which is
what these files share with the rest of `actionchart/`, and not the `u16 length, no
terminator` shape `.papr` uses.

The shipped file decodes to exactly what the XML says: `ProjectileInfoPackage` and
`GimmickPackage`, each loading `ProjectileInfo`, `Gimmick_ProjectileInfo` and
`Sequencer_ProjectileInfo`. All 139 bytes are accounted for, and `encode_projectile_package`
reproduces them.

## What this is next to

`.paproj` is the payload these packages name -- nine files, 2.1 MB, holding the projectile
definitions themselves (speed, gravity, lifetime, collision). Those are *not* decoded:
they carry no strings at all, and the obvious `u32 count` framings do not survive contact
with the corpus. `cdmw/core/projectile_package.py` deliberately stops at the index.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Tuple

#: Extension of the description file this module reads.
PACKAGE_DESCRIPTION_PATH = (
    "actionchart/bin__/description/projectilepackagedescription.paprojdesc"
)
_MAX_STRING = 255
_PRINTABLE = frozenset(range(0x20, 0x7F))


class ProjectilePackageError(ValueError):
    """Raised when a buffer is not a projectile package description."""


@dataclass(frozen=True)
class ProjectilePackage:
    """One package and the modules it loads, by name."""

    name: str
    modules: Tuple[str, ...]
    #: The second header byte. 1 in the shipped file; carried so a write round-trips.
    flag: int = 1


@dataclass(frozen=True)
class ProjectilePackageDescription:
    """The whole index: the string table, and the packages built over it."""

    strings: Tuple[str, ...]
    packages: Tuple[ProjectilePackage, ...]

    def module_names(self) -> Tuple[str, ...]:
        """Every module any package loads, deduplicated, in first-seen order."""

        seen: dict[str, None] = {}
        for package in self.packages:
            for module in package.modules:
                seen.setdefault(module, None)
        return tuple(seen)


def _read_string(data: bytes, at: int) -> tuple[str, int]:
    """`u8 (length + 1)`, ASCII, then a NUL -- the `.paac` convention."""

    if at >= len(data):
        raise ProjectilePackageError("string length runs past the file")
    stated = data[at]
    if stated < 2:
        raise ProjectilePackageError(f"implausible string length byte {stated}")
    end = at + stated
    if end >= len(data):
        raise ProjectilePackageError("string runs past the file")
    body = data[at + 1: end]
    if data[end] != 0:
        raise ProjectilePackageError("string is not NUL terminated")
    if not all(byte in _PRINTABLE for byte in body):
        raise ProjectilePackageError("string is not printable ASCII")
    return body.decode("ascii"), end + 1


def parse_projectile_package(data: bytes) -> ProjectilePackageDescription:
    """Read the description. Raises rather than returning a partial answer."""

    if len(data) < 2:
        raise ProjectilePackageError("too short to be a package description")
    count = struct.unpack_from("<H", data, 0)[0]
    at = 2
    strings: list[str] = []
    for _ in range(count):
        text, at = _read_string(data, at)
        strings.append(text)

    if at + 8 > len(data):
        raise ProjectilePackageError("package counts run past the file")
    package_count, module_total = struct.unpack_from("<II", data, at)
    at += 8

    rows = []
    for _ in range(package_count):
        if at + 6 > len(data):
            raise ProjectilePackageError("package row runs past the file")
        modules, flag, first, name_index = struct.unpack_from("<BBHH", data, at)
        at += 6
        rows.append((modules, flag, first, name_index))

    if at + 2 * module_total > len(data):
        raise ProjectilePackageError("module list runs past the file")
    slots = [
        struct.unpack_from("<H", data, at + 2 * index)[0] for index in range(module_total)
    ]
    at += 2 * module_total

    if at != len(data):
        raise ProjectilePackageError(
            f"{len(data) - at} bytes left over after the module list"
        )

    packages = []
    for modules, flag, first, name_index in rows:
        if name_index >= len(strings):
            raise ProjectilePackageError(f"package name index {name_index} is out of range")
        if first + modules > len(slots):
            raise ProjectilePackageError("package module range is out of bounds")
        names = []
        for slot in slots[first: first + modules]:
            if slot >= len(strings):
                raise ProjectilePackageError(f"module index {slot} is out of range")
            names.append(strings[slot])
        packages.append(
            ProjectilePackage(name=strings[name_index], modules=tuple(names), flag=flag)
        )
    return ProjectilePackageDescription(strings=tuple(strings), packages=tuple(packages))


def encode_projectile_package(description: ProjectilePackageDescription) -> bytes:
    """Rebuild the file. Byte-exact for the shipped description.

    The string table is written back as it was read rather than regenerated from the
    packages: the shipped file lists `ProjectileInfoPackage` first and `GimmickPackage`
    last with the three module names between them, and that order is not derivable from
    the packages themselves.
    """

    index = {text: position for position, text in enumerate(description.strings)}
    out = bytearray(struct.pack("<H", len(description.strings)))
    for text in description.strings:
        raw = text.encode("ascii", "strict")
        if not 1 <= len(raw) <= _MAX_STRING - 1:
            raise ProjectilePackageError(f"string {text!r} is not 1..{_MAX_STRING - 1} bytes")
        out += bytes((len(raw) + 1,)) + raw + b"\x00"

    slots: list[int] = []
    rows = bytearray()
    for package in description.packages:
        if package.name not in index:
            raise ProjectilePackageError(f"package name {package.name!r} is not in the table")
        rows += struct.pack(
            "<BBHH", len(package.modules), package.flag, len(slots), index[package.name]
        )
        for module in package.modules:
            if module not in index:
                raise ProjectilePackageError(f"module {module!r} is not in the table")
            slots.append(index[module])

    out += struct.pack("<II", len(description.packages), len(slots))
    out += rows
    for slot in slots:
        out += struct.pack("<H", slot)
    return bytes(out)


def rebuild_is_exact(data: bytes) -> bool:
    """Does this file survive a parse and a write unchanged?"""

    try:
        return encode_projectile_package(parse_projectile_package(data)) == data
    except ProjectilePackageError:
        return False
