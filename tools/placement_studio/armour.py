"""Armour pieces available for a character, read straight from the archives.

The pinned baseline holds only the two body meshes — every helmet, glove, cloak and vest
lives in the packages. Enumerating them reads the archive tables only, so it costs a few
seconds once and no decompression; a piece's geometry is pulled the moment it is chosen.

Slots are the game's own directory names, kept in wearing order rather than the numeric
order they sort into, so the picker reads head-down like a character sheet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

#: Directory name -> label, in the order they should appear.
SLOTS: tuple[tuple[str, str], ...] = (
    ("13_hel", "Helmet"),
    ("20_mask", "Mask"),
    ("40_glasses", "Glasses"),
    ("14_sho", "Shoulders"),
    ("15_vest", "Vest"),
    ("16_jacket", "Jacket"),
    ("9_upperbody", "Upper body"),
    ("17_belt", "Belt"),
    ("10_lowerbody", "Lower body"),
    ("11_hand", "Hands"),
    ("12_foot", "Feet"),
    ("19_cloak", "Cloak"),
    ("18_acc", "Accessory"),
    ("38_underwear", "Underwear"),
)
SLOT_KEYS = tuple(key for key, _label in SLOTS)
NONE_LABEL = "(none)"

_ARMOUR = re.compile(r"^character/model/([^/]+)/([^/]+)/armor/([^/]+)/([^/]+)\.pac$")
# The bare figure. `nude` is the whole anatomy — torso, arms, hands with fingers, legs, feet
# with toes — but its head is a blank scalp, so the face comes from `head/head` separately.
# Neither lives under `armor/`, which is why the pattern above never found them and the
# character stood there in a coat with no hands, no feet and no face.
_NUDE = re.compile(r"^character/model/([^/]+)/([^/]+)/nude/([^/]+)\.pac$")
_FACE = re.compile(r"^character/model/([^/]+)/([^/]+)/head/head/([^/]+)\.pac$")

#: Indexed like armour so the same cache carries them, but never offered as a slot to pick:
#: they are the body every other choice is worn *on*.
NUDE_SLOT = "nude"
FACE_SLOT = "head"

#: Action charts, indexed here for the same reason the anatomy is: the pinned baseline holds
#: only Kliff's, so Damian was being shown another character's charts and the socket list that
#: reads them came out empty. Carried as a slot so the existing cache round-trips them.
CHART_SLOT = "chart"
_CHART = re.compile(r"^actionchart/.+/1_pc/([^/]+)/([^/]+)\.paac$")
# Weapon *socket* files, which are what make a weapon placeable rather than merely drawable.
_WEAPON_SOCKETS = re.compile(
    r"^character/descriptors/socketbonedata/([^/]+)/([^/]+)/weapon/.+\.sockets\.xml$"
)
# Weapon geometry, kept so a chosen weapon can be read without rescanning the packages.
_WEAPON_MESH = re.compile(r"^character/model/([^/]+)/([^/]+)/weapon/([^/]+)/([^/]+)\.pac$")


@dataclass(frozen=True, slots=True)
class ArmourPiece:
    path: str
    slot: str
    model: str
    #: The archive entry, kept so reading a piece does not re-scan the package tables.
    source: object = None

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1][: -len(".pac")]


class ArmourIndex:
    """Every armour `.pac` in the install, grouped by model and slot."""

    __slots__ = ("_by_model", "_by_path")

    def __init__(self, pieces: Sequence[ArmourPiece] = ()) -> None:
        self._by_model: Dict[str, Dict[str, List[ArmourPiece]]] = {}
        self._by_path: Dict[str, ArmourPiece] = {p.path: p for p in pieces}
        for piece in pieces:
            self._by_model.setdefault(piece.model, {}).setdefault(piece.slot, []).append(piece)
        for slots in self._by_model.values():
            for items in slots.values():
                items.sort(key=lambda p: p.name)

    def __len__(self) -> int:
        return sum(len(i) for s in self._by_model.values() for i in s.values())

    def models(self) -> List[str]:
        return sorted(self._by_model)

    def pieces(self, model: str, slot: str) -> List[ArmourPiece]:
        return list(self._by_model.get(model, {}).get(slot, ()))

    def piece(self, path: str) -> Optional[ArmourPiece]:
        return self._by_path.get(path)

    def all_pieces(self) -> List[ArmourPiece]:
        """Every piece, flat — what the on-disk cache round-trips."""

        return list(self._by_path.values())

    def base_body(self, model: str) -> List[str]:
        """The bare figure to start from: the nude body, and the head that gives it a face.

        Returns paths in draw order, or an empty list when this model has no anatomy indexed —
        in which case the caller falls back to whatever the baseline pinned.
        """

        return [
            path
            for path in (self._plainest(model, NUDE_SLOT), self._plainest(model, FACE_SLOT))
            if path
        ]

    def _plainest(self, model: str, slot: str) -> str:
        """The default variant of a slot.

        A model carries several bodies and heads — damage states, story variants, one named
        after a character. They all skin to the same rig, so any of them *works*; the plain
        `..._00_0001` is the one that looks like the character at rest, and the shortest name
        is what distinguishes it from `..._0001_custom` and friends.
        """

        pieces = self.pieces(model, slot)
        if not pieces:
            return ""
        return min(pieces, key=lambda p: (0 if "_00_0001" in p.name else 1, len(p.name), p.name)).path


def index_armour(game_root, *, should_stop=None) -> ArmourIndex:
    index, _sockets, _meshes = index_wearables(game_root, should_stop=should_stop)
    return index


def index_wearables(game_root, *, should_stop=None, cache: bool = True):
    """One pass for armour, weapon socket files and weapon meshes.

    They come from the same package tables, so scanning three times would cost three times
    as long for no benefit. Returns `(armour index, {socket path: entry}, {mesh path: entry})`.

    The result is cached on disk. Parsing all 33 package tables costs about four seconds,
    and one of them (0009, 419,660 entries) is a single uninterruptible 1.2-second call that
    the UI thread cannot paint through. Reading it back takes milliseconds, so the stall
    happens once per game install rather than once per launch.
    """

    if cache:
        cached = _read_index_cache(game_root)
        if cached is not None:
            return cached
    result = _scan_wearables(game_root, should_stop=should_stop)
    if cache and (should_stop is None or not should_stop()):
        _write_index_cache(game_root, result)
    return result


def _scan_wearables(game_root, *, should_stop=None):
    """The uncached scan: every package table, once."""

    from .corpus import _iter_archive_entries, normalize_game_path

    pieces: List[ArmourPiece] = []
    sockets: Dict[str, object] = {}
    meshes: Dict[str, object] = {}
    for _package, entry in _iter_archive_entries(Path(game_root)):
        if should_stop is not None and should_stop():
            return ArmourIndex(), {}, {}
        path = normalize_game_path(entry.path)
        match = _ARMOUR.match(path)
        if match:
            pieces.append(
                ArmourPiece(path=path, slot=match.group(3), model=match.group(2), source=entry)
            )
            continue
        chart = _CHART.match(path)
        if chart is not None:
            pieces.append(ArmourPiece(
                path=path, slot=CHART_SLOT, model=chart.group(1), source=entry,
            ))
            continue
        body = _NUDE.match(path) or _FACE.match(path)
        if body is not None:
            pieces.append(ArmourPiece(
                path=path,
                slot=NUDE_SLOT if body.re is _NUDE else FACE_SLOT,
                model=body.group(2),
                source=entry,
            ))
            continue
        if _WEAPON_SOCKETS.match(path):
            sockets[path] = entry
        elif _WEAPON_MESH.match(path):
            meshes[path] = entry
    return ArmourIndex(pieces), sockets, meshes


# Bump when the shape below changes, so a stale file is ignored rather than misread.
# 2: the bare body and the head joined the index, so a v1 file has no anatomy in it.
# 3: action charts joined it, so a v2 file has none of Damian's.
_CACHE_VERSION = 3


def _cache_file(game_root) -> Path:
    from .corpus import work_root

    return Path(work_root()) / "wearables-index.json"


def _cache_signature(game_root) -> List[list]:
    """What the cache was built from: every package table, by name, size and mtime.

    Cheap to compute — it stats 33 files — and it catches a game update, which is the only
    thing that can invalidate the index.
    """

    from cdmw.core.archive_format import discover_pamt_files

    signature = []
    for pamt in sorted(discover_pamt_files(Path(game_root))):
        try:
            stat = pamt.stat()
        except OSError:
            continue
        signature.append([str(pamt), stat.st_size, int(stat.st_mtime)])
    return signature


def _entry_fields() -> Sequence[str]:
    import dataclasses

    from cdmw.core.archive_format import ArchiveEntry

    return [field.name for field in dataclasses.fields(ArchiveEntry)]


def _entry_to_json(entry) -> dict:
    out = {}
    for name in _entry_fields():
        value = getattr(entry, name, None)
        out[name] = str(value) if isinstance(value, Path) else value
    return out


def _entry_from_json(raw: dict):
    from cdmw.core.archive_format import ArchiveEntry

    kwargs = {}
    for name in _entry_fields():
        value = raw.get(name)
        # The two path fields have to go back as `Path`, or reading the entry fails deep
        # inside the extractor rather than here.
        if name in ("pamt_path", "paz_file") and isinstance(value, str):
            value = Path(value)
        kwargs[name] = value
    return ArchiveEntry(**kwargs)


def _read_index_cache(game_root):
    """The cached index, or `None` when there is no usable one."""

    import json

    path = _cache_file(game_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if raw.get("version") != _CACHE_VERSION:
        return None
    if raw.get("signature") != _cache_signature(game_root):
        return None
    try:
        pieces = [
            ArmourPiece(
                path=item["path"],
                slot=item["slot"],
                model=item["model"],
                source=_entry_from_json(item["source"]),
            )
            for item in raw["armour"]
        ]
        sockets = {key: _entry_from_json(value) for key, value in raw["sockets"].items()}
        meshes = {key: _entry_from_json(value) for key, value in raw["meshes"].items()}
    except (KeyError, TypeError):
        return None
    return ArmourIndex(pieces), sockets, meshes


def _write_index_cache(game_root, result) -> None:
    """Store the index. A failure here costs a rescan next launch, nothing more."""

    import json

    index, sockets, meshes = result
    payload = {
        "version": _CACHE_VERSION,
        "signature": _cache_signature(game_root),
        "armour": [
            {
                "path": piece.path,
                "slot": piece.slot,
                "model": piece.model,
                "source": _entry_to_json(piece.source),
            }
            for piece in index.all_pieces()
        ],
        "sockets": {key: _entry_to_json(value) for key, value in sockets.items()},
        "meshes": {key: _entry_to_json(value) for key, value in meshes.items()},
    }
    path = _cache_file(game_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass


def read_entry(entry) -> bytes:
    """Read one indexed archive entry."""

    from cdmw.core.archive_extraction import read_archive_entry_data

    data, _decoded, message = read_archive_entry_data(entry)
    if not data:
        raise ValueError(f"archive read returned nothing ({message})")
    return data


def read_armour(piece_or_path, index: Optional[ArmourIndex] = None) -> bytes:
    """Pull one armour mesh out of the archives.

    Takes the indexed piece so the read is a direct seek. Re-scanning the package tables per
    piece cost five seconds to dress a character; the entry was already in hand.
    """

    from cdmw.core.archive_extraction import read_archive_entry_data

    piece = piece_or_path
    if isinstance(piece_or_path, str):
        piece = index.piece(piece_or_path) if index is not None else None
        if piece is None:
            raise ValueError(f"{piece_or_path}: not in the armour index")
    if piece.source is None:
        raise ValueError(f"{piece.path}: no archive entry to read")
    data, _decoded, message = read_archive_entry_data(piece.source)
    if not data:
        raise ValueError(f"{piece.path}: archive read returned nothing ({message})")
    return data
