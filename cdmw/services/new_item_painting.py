"""Create New Item's painting template: a user's picture as a new painting in a DMM mod.

A new painting is a copy of a shipped painting that uses the chosen frame, with every
record it owns made new: an ItemInfo, GimmickInfo and HousingObjectInfo row with new
keys, the housing key added to `HousingGroup_Collection_Picture`, a gimmick prefab and
`.pami` at new paths that name the same frame mesh and a new picture texture, an icon,
and its texts in `item.paloc` and `gimmick.paloc`. Nothing is written into the game: the
plan becomes a DMM mod folder through Create New Item's own export.

Choices made where the study (`DESIGN-paintings.md`, "Built") left a question open:

* **Base tables only.** DMM ignores a mod's copy of a DLC table, so every row goes into
  the base table. The gimmick is cloned from the base layer's row. The DLC replaces all
  78 painting gimmicks with rows that differ only in `_managementStatDataList` (one
  "Service" stat); a base-shaped row is the shape the base table is known to hold.
* **Name and key both.** The item, gimmick and housing rows name each other by key in
  every shipped painting and also share one `_stringKey`; the clone keeps both ties.
* **Knowledge, item groups and price stay the source painting's.** The new item points
  at the source painting's KnowledgeInfo row (two shipped paintings already share one)
  and is not added to any item group's member list.
* **One mod holds every painting.** Each mod carries whole table copies, so a second
  painting is built into the same folder; the planner reads the folder's tables first.

None of this has been loaded by the game. It is untested in game.
"""

from __future__ import annotations

import re
import struct
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.compact_static import field_payload, read_compact_layout
from cdmw.core.new_item_record import RecordError, named_prefix
from cdmw.core.painting_picture import (
    FIT_FILL,
    FIT_WHOLE,
    CanvasMapping,
    PaintingPictureError,
    PicturePlan,
    compose_picture,
    dds_size,
    find_canvas,
    load_picture,
    plan_picture_texture,
)
from cdmw.core.painting_records import (
    PAINTING_NAME_PREFIX,
    PaintingKeys,
    PaintingPaths,
    PaintingRecordError,
    add_housing_group_member,
    allocate_painting_keys,
    clone_painting_gimmick,
    clone_painting_housing,
    clone_painting_item,
    gimmick_prefab_file,
    gimmick_text_key,
    housing_group_members,
    painting_paths,
    retarget_pami_picture,
)
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest
from cdmw.domain.cancellation import raise_if_cancelled

__all__ = [
    "FIT_FILL",
    "FIT_WHOLE",
    "PICTURE_GROUP_NAME",
    "PaintingFrame",
    "PaintingBuild",
    "PaintingFrameCatalogue",
    "PaintingPlanError",
    "PaintingRequest",
    "PaintingSource",
    "PaintingSourceRow",
    "build_painting_mod",
    "discover_painting_frames",
    "export_painting_mod",
    "frame_thumbnails",
    "plan_paintings",
    "read_painting_mod",
]

#: The housing group every shipped painting is listed in.
PICTURE_GROUP_NAME = "HousingGroup_Collection_Picture"
#: The kind recorded in a painting mod's `new-item.json`.
PAINTING_MOD_KIND = "paintings"
ICON_REGISTRY_PATH = "ui/xml/texture/cd_item_icon.xml"
_ICON_FOLDER = "ui/texture/icon"
_PAMI_REFERENCE = re.compile(rb"object/[\x21-\x7e]*?\.pami")
_STATIC_MESH = re.compile(r'<StaticMesh\s+Path="([^"]+)"')
#: `gimmick.paloc` -> `gimmick.dlc_01.paloc`, where the DLC keeps its own texts.
_DLC_PALOC = re.compile(r"\.paloc$")
_DLC_PALOC_SUFFIX = ".dlc_01.paloc"


class PaintingPlanError(ValueError):
    """Raised when a painting cannot be planned; the message says what to change."""


# ----------------------------------------------------------------------------- reading


@dataclass
class PaintingSource:
    """What the painting planner reads: the game's entries, with a painting mod's files over them.

    `tables` maps a table stem (`iteminfo`, `gimmickinfo.dlc_01`) to its body and header
    paths; `item_paloc` maps a language code to its base `item.paloc` path.
    """

    entry_of: Callable[[str], Optional[object]]
    read_game: Callable[[str], bytes]
    tables: Mapping[str, Tuple[str, str]]
    item_paloc: Mapping[str, str]
    overlay: Mapping[str, Callable[[], bytes]] = field(default_factory=dict)
    _cache: Dict[str, bytes] = field(default_factory=dict, repr=False)

    @classmethod
    def from_snapshot(cls, snapshot, overlay: Optional[Mapping[str, Callable[[], bytes]]] = None) -> "PaintingSource":
        sources = snapshot.sources
        if sources is None:
            raise PaintingPlanError("The game tables have not been read yet. Read the archives first.")
        tables = {stem: (pair[0].path, pair[1].path) for stem, pair in sources.tables.items()}
        return cls(
            entry_of=lambda path: snapshot.entries.get(_normal(path)),
            read_game=snapshot.payload,
            tables=tables,
            item_paloc={language: entry.path for language, entry in snapshot.paloc_entries.items()},
            overlay=dict(overlay or {}),
        )

    @property
    def languages(self) -> Tuple[str, ...]:
        return tuple(sorted(self.item_paloc))

    def has(self, path: str) -> bool:
        return _normal(path) in self.overlay or self.entry_of(path) is not None

    def entry(self, path: str):
        entry = self.entry_of(path)
        if entry is None:
            raise PaintingPlanError(f"The game has no file {path}.")
        return entry

    def read(self, path: str) -> bytes:
        key = _normal(path)
        if key not in self._cache:
            loader = self.overlay.get(key)
            self._cache[key] = bytes(loader() if loader is not None else self.read_game(path))
        return self._cache[key]

    def table(self, stem: str) -> Optional[Tuple[bytes, bytes, str, str]]:
        """(body, header, body path, header path) of a table, or None when the game has none."""

        paths = self.tables.get(stem)
        if paths is None:
            return None
        return self.read(paths[0]), self.read(paths[1]), paths[0], paths[1]

    def rows(self, stem: str) -> Dict[int, bytes]:
        table = self.table(stem)
        if table is None:
            return {}
        from cdmw.core.structured_binary_editor import parse_pabgh_table

        body, header = table[0], table[1]
        parsed = parse_pabgh_table(header, payload=body)
        return {int(row.row_id): body[start:end] for row, start, end in parsed.row_spans(len(body))}


def _normal(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").lower()


@dataclass(frozen=True, slots=True)
class PaintingSourceRow:
    """A shipped painting a new one is copied from."""

    item_key: int
    name: str
    gimmick_key: int
    housing_key: int
    prefab_value: str
    prefab_file: str
    pami: str
    picture_texture: str
    icon_path: str
    icon_hash: int
    name_key: str
    desc_key: str


@dataclass(frozen=True, slots=True)
class PaintingFrame:
    """One frame a new painting can use."""

    mesh: str
    size_m: Tuple[float, float]
    canvas: CanvasMapping
    texture_size: Tuple[int, int]
    source: PaintingSourceRow
    shipped_paintings: int

    @property
    def stem(self) -> str:
        return PurePosixPath(self.mesh).stem

    @property
    def label(self) -> str:
        """`0.86 x 0.75 m frame, picture 0.78 x 0.64 m (cd_in_dpw_picture_01)`."""

        return (f"{self.size_m[0]:.2f} x {self.size_m[1]:.2f} m frame, picture "
                f"{self.canvas.size_m[0]:.2f} x {self.canvas.size_m[1]:.2f} m ({self.stem})")


@dataclass(frozen=True, slots=True)
class PaintingFrameCatalogue:
    frames: Tuple[PaintingFrame, ...]
    #: (frame mesh or painting name, why it is not offered)
    left_out: Tuple[Tuple[str, str], ...] = ()

    def frame(self, mesh: str) -> PaintingFrame:
        for frame in self.frames:
            if frame.mesh == mesh:
                return frame
        raise PaintingPlanError("Choose a frame for the painting." if not str(mesh or "").strip()
                                else f"The frame {mesh} is not one CDMW can use.")


def _u(layout, name: str, width: int) -> int:
    payload = field_payload(layout, name)
    if payload is None or len(payload) != width:
        raise PaintingPlanError(f"{name} is not a key in this row.")
    return int.from_bytes(payload, "little")


def _prefab_value(layout) -> str:
    payload = field_payload(layout, "_prefabPath") or b""
    if len(payload) < 4 or struct.unpack_from("<I", payload)[0] != len(payload) - 4:
        raise PaintingPlanError("The gimmick names no prefab.")
    return payload[4:].decode("utf-8")


def _picture_group(source: PaintingSource) -> Tuple[int, bytes]:
    for key, raw in source.rows("housingobjectgroupinfo").items():
        try:
            if named_prefix(raw, 2, key=key)[1] == PICTURE_GROUP_NAME:
                return key, raw
        except (RecordError, ValueError):
            continue
    raise PaintingPlanError(f"The game's housing groups have no {PICTURE_GROUP_NAME}.")


def _source_row(source: PaintingSource, housing_key: int, housing: Mapping[int, bytes],
                gimmicks: Mapping[int, bytes], items: Mapping[int, bytes]) -> Tuple[Optional[PaintingSourceRow], str]:
    """A shipped painting's chain, checked link by link, and its frame mesh."""

    from cdmw.core.iteminfo_row import parse_iteminfo_row
    from cdmw.core.stringinfo_table import stringinfo_key

    housing_layout = read_compact_layout(housing[housing_key], "housingobjectinfo")
    gimmick_key = _u(housing_layout, "_gimmickInfo", 4)
    gimmick = read_compact_layout(gimmicks[gimmick_key], "gimmickinfo")
    item_key = _u(gimmick, "_convertItemInfo", 4)
    if _u(gimmick, "_housingObjectInfo", 2) != housing_key:
        raise PaintingPlanError("its gimmick names another housing object")
    row = parse_iteminfo_row(items[item_key])
    from cdmw.core.item_layout import read_item_layout
    item_layout = read_item_layout(row.raw)
    if _u(item_layout, "_gimmickInfo", 4) != gimmick_key:
        raise PaintingPlanError("its item names another gimmick")
    name = row.string_key
    if name.startswith(PAINTING_NAME_PREFIX):
        return None, ""  # a painting CDMW added earlier is never a source
    icon_string = f"ItemIcon_{name}"
    icon_hash = stringinfo_key(icon_string)
    if struct.pack("<I", icon_hash) not in item_layout.data("_itemIconList"):
        raise PaintingPlanError("its icon is not named after the item")
    prefab_value = _prefab_value(gimmick)
    prefab_file = gimmick_prefab_file(prefab_value)
    prefab = source.read(prefab_file)
    pamis = sorted({match.decode("ascii") for match in _PAMI_REFERENCE.findall(prefab)})
    if len(pamis) != 1:
        raise PaintingPlanError(f"its prefab names {len(pamis)} material files, not one")
    text = source.read(pamis[0]).decode("utf-8")
    mesh = _STATIC_MESH.search(text)
    if mesh is None:
        raise PaintingPlanError("its material file names no mesh")
    return PaintingSourceRow(
        item_key=item_key, name=name, gimmick_key=gimmick_key, housing_key=housing_key,
        prefab_value=prefab_value, prefab_file=prefab_file, pami=pamis[0], picture_texture="",
        icon_path=f"{_ICON_FOLDER}/{icon_string.lower()}.dds", icon_hash=icon_hash,
        name_key=str(row.name_key or ""), desc_key=str(row.desc_key or ""),
    ), mesh.group(1).lstrip("/")


def discover_painting_frames(source: PaintingSource, *, stop_event: Optional[threading.Event] = None) -> PaintingFrameCatalogue:
    """Every frame the shipped paintings use, each with the lowest-keyed painting on it as its source."""

    from cdmw.core.crimson_formats import parse_pami_material_instances
    from cdmw.modding.mesh_parser import parse_pam

    _group_key, group_raw = _picture_group(source)
    members = housing_group_members(group_raw)
    housing = source.rows("housingobjectinfo")
    gimmicks = source.rows("gimmickinfo")
    items = source.rows("iteminfo")
    left_out: List[Tuple[str, str]] = []
    by_mesh: Dict[str, List[PaintingSourceRow]] = {}
    for housing_key in members:
        raise_if_cancelled(stop_event, "Reading the painting frames was cancelled.")
        if housing_key not in housing:
            continue  # a painting added by this very mod, or one the base table lacks
        try:
            row, mesh = _source_row(source, housing_key, housing, gimmicks, items)
        except (PaintingPlanError, PaintingRecordError, RecordError, KeyError, ValueError) as exc:
            left_out.append((f"housing object {housing_key}", str(exc)))
            continue
        if row is None:
            continue
        by_mesh.setdefault(mesh, []).append(row)
    frames = []
    for mesh, rows in sorted(by_mesh.items()):
        raise_if_cancelled(stop_event, "Reading the painting frames was cancelled.")
        rows.sort(key=lambda value: value.item_key)
        chosen = rows[0]
        try:
            pami_text = source.read(chosen.pami).decode("utf-8")
            textures = {}
            for instance in parse_pami_material_instances(pami_text):
                for parameter in instance.texture_parameters:
                    if parameter.parameter_name == "_baseColorTexture":
                        textures[(instance.primitive_name or instance.material_name).strip()] = parameter.texture_path
            parsed = parse_pam(source.read(mesh), PurePosixPath(mesh).name)
            canvas = find_canvas(parsed, list(textures))
            picture = textures[canvas.material]
            size = dds_size(source.read(picture)[:128])
            plan_picture_texture(size, canvas)
            if not source.has(chosen.icon_path):
                raise PaintingPlanError(f"its painting {chosen.name} has no icon file")
        except (PaintingPlanError, PaintingPictureError, RecordError, KeyError, ValueError, UnicodeDecodeError) as exc:
            left_out.append((mesh, str(exc)))
            continue
        low, high = parsed.bbox_min, parsed.bbox_max
        frames.append(PaintingFrame(
            mesh=mesh, size_m=(abs(high[0] - low[0]), abs(high[1] - low[1])), canvas=canvas, texture_size=size,
            source=replace(chosen, picture_texture=picture), shipped_paintings=len(rows)))
    frames.sort(key=lambda value: (value.size_m[0] * value.size_m[1], value.mesh))
    return PaintingFrameCatalogue(frames=tuple(frames), left_out=tuple(left_out))


# ----------------------------------------------------------------------------- planning


@dataclass(frozen=True, slots=True)
class PaintingRequest:
    """One painting the user asked for."""

    frame: str
    picture: object
    names: Mapping[str, str]
    descriptions: Mapping[str, str] = field(default_factory=dict)
    fit: str = FIT_FILL


#: (picture image, plan, frame) -> DDS bytes
TextureEncoder = Callable[[object, PicturePlan, PaintingFrame], bytes]
#: (picture path, reference icon entry, reference icon bytes, icon string) -> (archive path, DDS bytes)
IconBuilder = Callable[[Path, object, bytes, str], Tuple[str, bytes]]


def _english(texts: Mapping[str, str]) -> str:
    return str((texts or {}).get("eng", "") or "").strip()


def _check_requests(requests: Sequence[PaintingRequest], catalogue: PaintingFrameCatalogue):
    if not requests:
        raise PaintingPlanError("Add at least one painting.")
    checked = []
    for number, request in enumerate(requests, 1):
        label = f"Painting {number}"
        try:
            frame = catalogue.frame(request.frame)
        except PaintingPlanError as exc:
            raise PaintingPlanError(f"{label}: {exc}") from exc
        if not _english(request.names):
            raise PaintingPlanError(f"{label}: give the painting an English name.")
        if request.fit not in (FIT_FILL, FIT_WHOLE):
            raise PaintingPlanError(f"{label}: unknown picture fit {request.fit!r}.")
        try:
            picture = load_picture(request.picture)
        except PaintingPictureError as exc:
            raise PaintingPlanError(f"{label}: {exc}") from exc
        checked.append((request, frame, picture))
    return checked


def _keys_of(source: PaintingSource, stem: str) -> set:
    keys = set(source.rows(stem))
    keys |= set(source.rows(f"{stem}.dlc_01"))
    return keys


def _paloc(source: PaintingSource, path: str):
    from cdmw.core.paloc_format import parse_paloc

    return parse_paloc(source.read(path), name=path)


def _lookup(source: PaintingSource, path: str, key: str) -> Optional[object]:
    """The entry `key` in a base `.paloc` or the DLC's `<name>.dlc_01.paloc` beside it."""

    for candidate in (path, _DLC_PALOC.sub(_DLC_PALOC_SUFFIX, path)):
        if source.has(candidate):
            entry = _paloc(source, candidate).index().get(key)
            if entry is not None:
                return entry
    return None


def _like(template, key: str, text: str):
    """A new text record in the template record's category, as Create New Item writes item names."""

    from cdmw.core.paloc_format import LocalizationEntry

    return LocalizationEntry(category=template.category, key=str(key), text=str(text), reserved=template.reserved)


@dataclass
class _Plan:
    source: PaintingSource
    patches: Dict[str, Tuple[object, bytes]] = field(default_factory=dict)
    additions: List[ArchiveAddRequest] = field(default_factory=list)
    summary: List[str] = field(default_factory=list)

    def current(self, path: str) -> bytes:
        found = self.patches.get(_normal(path))
        return found[1] if found is not None else self.source.read(path)

    def patch(self, path: str, data: bytes, what: str) -> None:
        self.patches[_normal(path)] = (self.source.entry(path), bytes(data))
        self.summary.append(what)

    def add(self, template_path: str, path: str, data: bytes, what: str) -> None:
        if self.source.has(path) or any(_normal(item.path) == _normal(path) for item in self.additions):
            raise PaintingPlanError(f"{path} already exists; a new painting must not overwrite it.")
        self.additions.append(ArchiveAddRequest.from_template(self.source.entry(template_path), path, data))
        self.summary.append(what)

    def append_rows(self, stem: str, rows: Sequence[bytes], what: str) -> None:
        from cdmw.core.structured_binary_editor import append_table_rows

        paths = self.source.tables.get(stem)
        if paths is None:
            raise PaintingPlanError(f"The game has no {stem} table.")
        body, header = append_table_rows(self.current(paths[0]), self.current(paths[1]), list(rows))
        self.patch(paths[0], body, what)
        self.patch(paths[1], header, f"{stem} directory")


def plan_paintings(
    source: PaintingSource,
    catalogue: PaintingFrameCatalogue,
    requests: Sequence[PaintingRequest],
    *,
    encode_texture: TextureEncoder,
    build_icon: IconBuilder,
    earlier: Sequence[Mapping[str, object]] = (),
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
):
    """A Create New Item plan (:class:`NewItemPlan`) that adds every requested painting.

    `earlier` lists the paintings a mod being extended already holds (its record); their
    rows are already in `source`'s tables and their files stay in the mod.
    """

    from cdmw.core.item_icon_registry import IconRegistryError, add_icon_texture
    from cdmw.core.paloc_format import add_localization_entries, encode_paloc, text_for_language
    from cdmw.core.prefab_binary_edit import rewrite_prefab_paths_any_length
    from cdmw.core.stringinfo_table import append_stringinfo_strings, stringinfo_key
    from cdmw.core.structured_binary_editor import replace_table_row
    from cdmw.domain.new_item.allocation import localization_keys
    from cdmw.domain.new_item.spec import NewItemSpec
    from cdmw.services.new_item_planning import NewItemPlan

    log = on_log or (lambda _message: None)
    checked = _check_requests(requests, catalogue)
    keys = allocate_painting_keys(
        len(checked),
        item_keys=_keys_of(source, "iteminfo"),
        gimmick_keys=_keys_of(source, "gimmickinfo"),
        housing_keys=_keys_of(source, "housingobjectinfo"),
    )
    plan = _Plan(source)
    housing = source.rows("housingobjectinfo")
    gimmicks = source.rows("gimmickinfo")
    items = source.rows("iteminfo")
    group_key, _group_raw = _picture_group(source)
    records = [dict(value) for value in earlier]
    item_rows, gimmick_rows, housing_rows, icon_strings = [], [], [], []
    texts: Dict[str, List[Tuple[str, str, str, str]]] = {}
    planned = []
    for (request, frame, picture), own in zip(checked, keys):
        raise_if_cancelled(stop_event, "Painting plan cancelled.")
        src = frame.source
        paths = painting_paths(own, prefab_value=src.prefab_value, pami=src.pami)
        name_key, desc_key = localization_keys(own.item)
        log(f"Planning {own.name} on {frame.stem}...")
        try:
            item_rows.append(clone_painting_item(
                items[src.item_key], source_key=src.item_key, source_gimmick=src.gimmick_key, keys=own,
                name_key=str(name_key), desc_key=str(desc_key) if src.desc_key else None,
                icon_hashes={src.icon_hash: stringinfo_key(paths.icon_string)}))
            gimmick_rows.append(clone_painting_gimmick(
                gimmicks[src.gimmick_key], source_key=src.gimmick_key, source_item=src.item_key,
                source_housing=src.housing_key, keys=own, prefab_value=paths.prefab_value))
            housing_rows.append(clone_painting_housing(
                housing[src.housing_key], source_key=src.housing_key, source_gimmick=src.gimmick_key, keys=own))
        except PaintingRecordError as exc:
            raise PaintingPlanError(f"{own.name}: {exc}") from exc
        icon_strings.append(paths.icon_string)
        for language in source.languages:
            texts.setdefault(language, []).append((
                str(name_key), text_for_language(request.names, language).strip(),
                str(desc_key), text_for_language(request.descriptions, language).strip()))
        # The picture, its material file and the gimmick prefab, all at new paths.
        texture_plan = plan_picture_texture(frame.texture_size, frame.canvas)
        composed = compose_picture(picture, texture_plan, fit=request.fit)
        dds = encode_texture(composed, texture_plan, frame)
        if dds_size(dds[:128]) != (texture_plan.width, texture_plan.height):
            raise PaintingPlanError(f"{own.name}: the encoded picture is not {texture_plan.width} x {texture_plan.height}.")
        plan.add(src.picture_texture, paths.texture, dds,
                 f"Picture: {paths.texture} ({texture_plan.width} x {texture_plan.height}, {texture_plan.dds_format}, {texture_plan.mip_count} mips)")
        pami = retarget_pami_picture(source.read(src.pami).decode("utf-8"), frame.canvas.material, paths.texture)
        plan.add(src.pami, paths.pami, pami.encode("utf-8"), f"Material: {paths.pami}")
        try:
            prefab = rewrite_prefab_paths_any_length(source.read(src.prefab_file), {src.pami: paths.pami}).data
        except Exception as exc:  # noqa: BLE001  (the rewriter says why it refused)
            raise PaintingPlanError(f"{own.name}: the frame's prefab could not be copied: {exc}") from exc
        plan.add(src.prefab_file, paths.prefab_file, prefab, f"Prefab: {paths.prefab_file}")
        icon_path, icon_data = build_icon(Path(str(request.picture)), source.entry(src.icon_path),
                                          source.read(src.icon_path), paths.icon_string)
        plan.add(src.icon_path, icon_path, icon_data, f"Icon: {icon_path}")
        record = {
            "item_key": own.item, "gimmick_key": own.gimmick, "housing_key": own.housing, "internal_name": own.name,
            "frame": frame.mesh, "source_item": src.item_key, "source_name": src.name, "fit": request.fit,
            "picture_file": Path(str(request.picture)).name,
            "names": {k: str(v) for k, v in request.names.items() if str(v).strip()},
            "descriptions": {k: str(v) for k, v in request.descriptions.items() if str(v).strip()},
            "files": {"texture": paths.texture, "pami": paths.pami, "prefab": paths.prefab_file, "icon": icon_path},
            "texture": {"width": texture_plan.width, "height": texture_plan.height, "format": texture_plan.dds_format,
                        "mips": texture_plan.mip_count, "rect": list(texture_plan.rect)},
        }
        records.append(record)
        planned.append((own, src, record))

    raise_if_cancelled(stop_event, "Painting plan cancelled.")
    plan.append_rows("iteminfo", item_rows, f"ItemInfo: {len(item_rows)} painting item(s) appended")
    plan.append_rows("gimmickinfo", gimmick_rows, f"GimmickInfo: {len(gimmick_rows)} painting gimmick(s) appended")
    plan.append_rows("housingobjectinfo", housing_rows, f"HousingObjectInfo: {len(housing_rows)} housing object(s) appended")
    group_paths = source.tables["housingobjectgroupinfo"]
    group_body, group_header = plan.current(group_paths[0]), plan.current(group_paths[1])
    from cdmw.core.structured_binary_editor import parse_pabgh_table
    parsed = parse_pabgh_table(group_header, payload=group_body)
    group_row = next(group_body[start:end] for row, start, end in parsed.row_spans(len(group_body)) if row.row_id == group_key)
    for own in keys:
        group_row = add_housing_group_member(group_row, own.housing)
    group_body, group_header = replace_table_row(group_body, group_header, group_key, group_row)
    plan.patch(group_paths[0], group_body, f"{PICTURE_GROUP_NAME}: {len(keys)} housing object(s) added")
    plan.patch(group_paths[1], group_header, "HousingObjectGroupInfo directory")
    strings = source.tables.get("stringinfo")
    if strings is None:
        raise PaintingPlanError("The game has no StringInfo table for the icon names.")
    body, header, _added = append_stringinfo_strings(plan.current(strings[0]), plan.current(strings[1]), icon_strings, name="stringinfo")
    plan.patch(strings[0], body, f"StringInfo: {len(icon_strings)} icon name(s)")
    plan.patch(strings[1], header, "StringInfo directory")
    if not source.has(ICON_REGISTRY_PATH):
        raise PaintingPlanError(f"The game has no icon registry ({ICON_REGISTRY_PATH}).")
    registry = plan.current(ICON_REGISTRY_PATH)
    try:
        for (own, src, _record), icon_string in zip(planned, icon_strings):
            registry = add_icon_texture(registry, icon_string, like=f"ItemIcon_{src.name}")
    except IconRegistryError as exc:
        raise PaintingPlanError(f"Icon registry: {exc}") from exc
    plan.patch(ICON_REGISTRY_PATH, registry, f"Icon registry: {len(icon_strings)} icon(s) declared")
    for language in source.languages:
        raise_if_cancelled(stop_event, "Painting plan cancelled.")
        item_path = source.item_paloc[language]
        gimmick_path = str(PurePosixPath(item_path).with_name("gimmick.paloc"))
        item_table = _paloc(source, item_path)
        entries = []
        for (own, src, _record), (name_key, name, desc_key, desc) in zip(planned, texts[language]):
            template = _lookup(source, item_path, src.name_key)
            if template is None:
                raise PaintingPlanError(f"The {language} item texts have no entry for {src.name}.")
            entries.append(_like(template, name_key, name))
            if src.desc_key:
                described = _lookup(source, item_path, src.desc_key)
                if described is None:
                    raise PaintingPlanError(f"The {language} item texts have no description for {src.name}.")
                entries.append(_like(described, desc_key, desc or name))
        plan.patch(item_path, encode_paloc(add_localization_entries(item_table, entries)),
                   f"{language}: {len(entries)} item text(s)")
        if not source.has(gimmick_path):
            raise PaintingPlanError(f"The game has no {gimmick_path}.")
        gimmick_table = _paloc(source, gimmick_path)
        gimmick_entries = []
        for own, src, _record in planned:
            old_key = str(gimmick_text_key(src.gimmick_key))
            template = _lookup(source, gimmick_path, old_key)
            if template is None:
                raise PaintingPlanError(f"The {language} gimmick texts have no entry for {src.name}.")
            gimmick_entries.append(_like(template, str(own.gimmick_text_key), template.text))
        plan.patch(gimmick_path, encode_paloc(add_localization_entries(gimmick_table, gimmick_entries)),
                   f"{language}: {len(gimmick_entries)} gimmick text(s)")

    first_own, first_src, first_record = planned[0]
    spec = NewItemSpec(template_key=first_src.item_key, internal_name=first_own.name,
                       display_names=dict(first_record["names"]), descriptions=dict(first_record["descriptions"]),
                       item_key=first_own.item)
    patches = tuple(ArchivePatchRequest(entry=entry, payload_data=data) for entry, data in plan.patches.values())
    loose = {request.entry.path.replace("\\", "/"): bytes(request.payload_data) for request in patches}
    loose.update({request.path: bytes(request.payload_data) for request in plan.additions})
    manifest = {
        "kind": PAINTING_MOD_KIND,
        "generation": "current",
        "paintings": records,
        "iteminfo": [{"item_key": int(record["item_key"])} for record in records],
        "item_key": None,
    }
    return NewItemPlan(
        spec=spec,
        patches=patches,
        additions=tuple(plan.additions),
        loose_files=loose,
        new_paths=tuple(request.path for request in plan.additions),
        summary_lines=tuple(plan.summary),
        warnings=("A custom painting has not been tested in the game. Check it there before sharing the mod.",),
        manifest=manifest,
    )


# ----------------------------------------------------------------------------- the mod folder


def read_painting_mod(folder: Path, *, stop_event: Optional[threading.Event] = None):
    """(the folder's files as `{path: reader}`, its earlier paintings) for a painting mod to extend.

    An empty or missing folder gives nothing. A folder holding another mod is refused: a
    painting mod carries whole tables, and only CDMW's record of the paintings in it says
    which rows are its own.
    """

    import json

    from cdmw.core.mod_export_history import mod_metadata_path
    from cdmw.services.new_item_mod_base import mod_folder_payloads

    root = Path(folder)
    if not root.is_dir() or not any(root.iterdir()):
        return {}, ()
    payloads = mod_folder_payloads(root, stop_event=stop_event)
    if not payloads:
        return {}, ()
    record = mod_metadata_path(root, "new-item.json", stop_event=stop_event)
    manifest = {}
    if record.is_file():
        try:
            manifest = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    if not isinstance(manifest, dict) or manifest.get("kind") != PAINTING_MOD_KIND:
        raise PaintingPlanError(
            f"{root.name} holds another mod, or one CDMW has no record of. Choose an empty folder, "
            "or a painting mod CDMW made on this computer.")
    earlier = tuple(dict(value) for value in manifest.get("paintings", ()) if isinstance(value, dict))
    for painting in earlier:
        for path in dict(painting.get("files") or {}).values():
            if _normal(path) not in payloads:
                raise PaintingPlanError(f"{root.name} has lost {path} of {painting.get('internal_name')}. "
                                        "Build the paintings into a new folder.")
    return {path: payload.read_bytes for path, payload in payloads.items()}, earlier


def encode_picture_with_helper(image, plan: PicturePlan, _frame=None, *, stop_event: Optional[threading.Event] = None) -> bytes:
    """BC1 with a full mip chain through the bundled DirectXTex helper, in CDMW's temp folder."""

    from cdmw.app.app_folder import workspace_temp_folder
    from cdmw.core.texture_native import encode_dds_with_directxtex

    parent = workspace_temp_folder()
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="painting-", dir=parent) as folder:
        png, dds = Path(folder) / "picture.png", Path(folder) / "picture.dds"
        image.save(png)
        encode_dds_with_directxtex(png, dds, dds_format=plan.dds_format, width=plan.width, height=plan.height,
                                   mip_count=plan.mip_count, stop_event=stop_event)
        if not dds.is_file():
            raise PaintingPlanError("The picture could not be encoded: CDMW's texture helper is not available.")
        return dds.read_bytes()


def build_icon_with_helper(picture: Path, reference_entry, reference_payload: bytes, icon_string: str,
                           *, existing: Optional[Callable[[str], bool]] = None,
                           stop_event: Optional[threading.Event] = None) -> Tuple[str, bytes]:
    """Create New Item's icon generator, shaped like the source painting's icon."""

    from cdmw.core.item_icon_addition import build_new_item_icon

    icon = build_new_item_icon(source_path=Path(picture), reference_entry=reference_entry,
                               reference_payload=reference_payload, icon_string=icon_string,
                               existing_paths=existing, stop_event=stop_event)
    return icon.target_path, bytes(icon.payload_data)


def export_painting_mod(plan, folder: Path, *, title: str, stop_event: Optional[threading.Event] = None):
    """Write the plan as a DMM mod folder through Create New Item's export."""

    from cdmw.models import ModPackageInfo
    from cdmw.services.new_item_service import NewItemService

    names = [str(record.get("names", {}).get("eng") or record.get("internal_name")) for record in plan.manifest["paintings"]]
    info = ModPackageInfo(
        title=str(title or "").strip() or "Custom paintings",
        description="Adds " + ", ".join(names) + " as new paintings. Built by CDMW's painting template; untested in game.",
    )
    return NewItemService().export_loose(plan, Path(folder), manager="DMM", package_info=info,
                                        replace_existing=True, stop_event=stop_event)


@dataclass(frozen=True, slots=True)
class PaintingBuild:
    """A finished painting mod: the plan it was written from and where it went."""

    plan: object
    export: object
    paintings: Tuple[Mapping[str, object], ...]


def build_painting_mod(snapshot, requests: Sequence[PaintingRequest], folder: Path, title: str, *,
                       on_log: Optional[Callable[[str], None]] = None,
                       stop_event: Optional[threading.Event] = None) -> PaintingBuild:
    """Read the folder (an earlier painting mod is extended), plan, encode and write the mod."""

    log = on_log or (lambda _message: None)
    overlay, earlier = read_painting_mod(Path(folder), stop_event=stop_event)
    if earlier:
        log(f"Adding to {Path(folder).name}, which holds {len(earlier)} painting(s) already.")
    source = PaintingSource.from_snapshot(snapshot, overlay=overlay)
    catalogue = discover_painting_frames(source, stop_event=stop_event)
    plan = plan_paintings(
        source, catalogue, requests,
        encode_texture=lambda image, picture_plan, frame: encode_picture_with_helper(
            image, picture_plan, frame, stop_event=stop_event),
        build_icon=lambda picture, entry, payload, icon_string: build_icon_with_helper(
            picture, entry, payload, icon_string, existing=source.has, stop_event=stop_event),
        earlier=earlier, on_log=log, stop_event=stop_event)
    raise_if_cancelled(stop_event, "Painting plan cancelled.")
    log("Writing the mod folder...")
    export = export_painting_mod(plan, Path(folder), title=title, stop_event=stop_event)
    return PaintingBuild(plan=plan, export=export, paintings=tuple(plan.manifest["paintings"]))


def frame_thumbnails(source: PaintingSource, catalogue: PaintingFrameCatalogue, *, size: int = 96,
                     stop_event: Optional[threading.Event] = None) -> Dict[str, bytes]:
    """`{frame mesh: PNG bytes}` of each frame's source painting icon, for the frame list.

    A frame whose icon Pillow cannot decode simply has no thumbnail.
    """

    import io

    from PIL import Image

    result = {}
    for frame in catalogue.frames:
        raise_if_cancelled(stop_event, "Reading the painting frames was cancelled.")
        try:
            with Image.open(io.BytesIO(source.read(frame.source.icon_path))) as image:
                image.load()
                picture = image.convert("RGBA")
        except (OSError, ValueError, PaintingPlanError):
            continue
        picture.thumbnail((size, size))
        buffer = io.BytesIO()
        picture.save(buffer, "PNG")
        result[frame.mesh] = buffer.getvalue()
    return result
