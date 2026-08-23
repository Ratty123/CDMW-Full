"""The catalogue of shipped effects: what each `.pae` instances, draws and spans.

The studio's effect list was a list of stems. An effect's binary says more
(:mod:`cdmw.core.effect_binary`): which emitters it instances, which textures and
meshes those draw, its bounding box, whether it loops. This service reads every
effect once (about a minute for the 6,109 shipped ones), keeps the facts as a JSON
cache keyed by the archives' effect population, and answers searches over stem,
emitter, texture and mesh names, so "fire", "lightning" or "ember" find effects by
what they are made of and not only by what they are called.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, Tuple

from cdmw.core.effect_binary import EffectBinaryError, EffectDocument, decode_effect_binary
from cdmw.services.new_item_snapshot import EFFECT_DIR, NewItemSnapshot

__all__ = [
    "CATALOGUE_SCHEMA",
    "EffectFacts",
    "EffectCatalogue",
    "build_effect_catalogue",
    "effect_facts_from_document",
    "load_effect_catalogue",
    "save_effect_catalogue",
]

CATALOGUE_SCHEMA = 1
Vec3 = Tuple[float, float, float]
LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class EffectFacts:
    """What one shipped effect is made of, as its binary says."""

    stem: str
    #: `EffectData._effectDataName`, the authoring name (`fx/materialfx/...`).
    name: str
    #: `emitter/<stem>` names, in order.
    emitters: Tuple[str, ...]
    textures: Tuple[str, ...]
    meshes: Tuple[str, ...]
    box_min: Vec3
    box_max: Vec3
    infinite_emitter: bool
    infinite_particle: bool
    has_lights: bool
    #: `_maxSpawnableTime` / `_effectLifeCycleTime`, seconds; 0 when unset.
    max_spawnable_time: float
    life_cycle_time: float
    byte_length: int
    #: "" when the file walked to the byte; the walk note otherwise.
    walk_note: str = ""

    @property
    def size(self) -> Vec3:
        return tuple(max(0.0, high - low) for low, high in zip(self.box_min, self.box_max))  # type: ignore[return-value]

    @property
    def loops(self) -> bool:
        return self.infinite_emitter or self.infinite_particle

    def search_text(self) -> str:
        return " ".join((self.stem, self.name, *self.emitters, *self.textures, *self.meshes)).casefold()

    def matches(self, needle: str) -> bool:
        needle = needle.casefold().strip()
        if not needle:
            return True
        haystack = self.search_text()
        return all(token in haystack for token in needle.split())


@dataclass(slots=True)
class EffectCatalogue:
    facts: Dict[str, EffectFacts] = field(default_factory=dict)
    #: The effect population the catalogue was built from: count and total bytes.
    signature: str = ""

    def __len__(self) -> int:
        return len(self.facts)

    def get(self, stem: str) -> Optional[EffectFacts]:
        return self.facts.get(str(stem or ""))

    def search(self, needle: str = "", *, limit: Optional[int] = 300) -> Tuple[EffectFacts, ...]:
        out = [item for item in self.facts.values() if item.matches(needle)]
        out.sort(key=lambda item: item.stem)
        return tuple(out if limit is None else out[: max(0, int(limit))])


def effect_facts_from_document(stem: str, document: EffectDocument) -> EffectFacts:
    root = document.root

    def vec(name: str) -> Vec3:
        value = root.value(name)
        if value is None:
            return (0.0, 0.0, 0.0)
        raw = value.value
        return tuple(float(v) for v in raw) if isinstance(raw, tuple) and len(raw) == 3 else (0.0, 0.0, 0.0)  # type: ignore[return-value]

    def flag(name: str) -> bool:
        value = root.value(name)
        return bool(value.value) if value is not None else False

    def number(name: str) -> float:
        value = root.value(name)
        try:
            return float(value.value) if value is not None else 0.0  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0

    name_value = root.value("_effectDataName")
    # the root's own flags are only written when set; an emitter looping for ever
    # (`_loopCount` -1) says the same thing from below
    infinite_emitter = flag("_hasInfiniteEmitter")
    infinite_particle = flag("_hasInfiniteLifeTimeParticle")
    for spawn in root.find("EmitterSpawnData"):
        loop = spawn.value("_loopCount")
        if loop is not None and loop.value == -1:
            infinite_emitter = True
        forever = spawn.value("_isInfiniteParticle")
        if forever is not None and forever.value:
            infinite_particle = True
    resources = document.resources()
    textures = tuple(path for path in resources if path.lower().endswith(".dds") and "nonetexture" not in path.lower())
    meshes = tuple(path for path in resources if path.lower().endswith((".pam", ".pac")))
    return EffectFacts(
        stem=stem,
        name=str(name_value.value) if name_value is not None else "",
        emitters=document.emitter_names(),
        textures=textures,
        meshes=meshes,
        box_min=vec("_boundingBoxMin"),
        box_max=vec("_boundingBoxMax"),
        infinite_emitter=infinite_emitter,
        infinite_particle=infinite_particle,
        has_lights=flag("_hasEmitterLights"),
        max_spawnable_time=number("_maxSpawnableTime"),
        life_cycle_time=number("_effectLifeCycleTime"),
        byte_length=document.byte_length,
        walk_note="" if document.walk_complete else document.walk_note,
    )


def catalogue_signature(snapshot: NewItemSnapshot) -> str:
    """Count and total size of the effect entries: what a cache is valid for."""

    total = 0
    count = 0
    for stem in snapshot.effect_stems:
        entry = snapshot.entries.get(f"{EFFECT_DIR}{stem}.pae")
        if entry is None:
            continue
        count += 1
        total += int(getattr(entry, "orig_size", 0) or getattr(entry, "comp_size", 0) or 0)
    return f"{CATALOGUE_SCHEMA}:{count}:{total}"


def build_effect_catalogue(
    snapshot: NewItemSnapshot,
    *,
    on_log: Optional[LogFn] = None,
    on_progress: Optional[ProgressFn] = None,
    stop_event: Optional[threading.Event] = None,
    stems: Optional[Iterable[str]] = None,
) -> EffectCatalogue:
    """Read and decode every effect the snapshot names (or `stems`) into a catalogue."""

    wanted = sorted(stems) if stems is not None else sorted(snapshot.effect_stems)
    catalogue = EffectCatalogue(signature=catalogue_signature(snapshot))
    total = len(wanted)
    for index, stem in enumerate(wanted):
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("Effect indexing cancelled.")
        path = f"{EFFECT_DIR}{stem}.pae"
        if not snapshot.has_entry(path):
            continue
        try:
            data = bytes(snapshot.read_entry(snapshot.entry(path)))
            document = decode_effect_binary(data)
            catalogue.facts[stem] = effect_facts_from_document(stem, document)
        except (EffectBinaryError, ValueError, OSError) as exc:
            catalogue.facts[stem] = EffectFacts(
                stem=stem, name="", emitters=(), textures=(), meshes=(), box_min=(0.0, 0.0, 0.0), box_max=(0.0, 0.0, 0.0),
                infinite_emitter=False, infinite_particle=False, has_lights=False, max_spawnable_time=0.0, life_cycle_time=0.0,
                byte_length=0, walk_note=str(exc),
            )
        if on_progress is not None and (index % 50 == 0 or index + 1 == total):
            on_progress(index + 1, total, stem)
    if on_log is not None:
        indexed = len(catalogue.facts)
        broken = sum(1 for item in catalogue.facts.values() if item.walk_note)
        on_log(f"Indexed {indexed} effects; {broken} did not decode.")
    return catalogue


def save_effect_catalogue(catalogue: EffectCatalogue, path: Path) -> None:
    payload = {
        "schema": CATALOGUE_SCHEMA,
        "signature": catalogue.signature,
        "effects": [asdict(item) for item in catalogue.facts.values()],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def load_effect_catalogue(path: Path, *, signature: str = "") -> Optional[EffectCatalogue]:
    """The cached catalogue at `path`, or None when missing, unreadable, or built for
    another effect population than `signature` (when given)."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, Mapping) or payload.get("schema") != CATALOGUE_SCHEMA:
        return None
    if signature and str(payload.get("signature", "")) != signature:
        return None
    catalogue = EffectCatalogue(signature=str(payload.get("signature", "")))
    for row in payload.get("effects", ()):
        if not isinstance(row, Mapping):
            continue
        try:
            item = EffectFacts(
                stem=str(row["stem"]), name=str(row.get("name", "")),
                emitters=tuple(row.get("emitters", ())), textures=tuple(row.get("textures", ())), meshes=tuple(row.get("meshes", ())),
                box_min=tuple(row.get("box_min", (0.0, 0.0, 0.0))), box_max=tuple(row.get("box_max", (0.0, 0.0, 0.0))),  # type: ignore[arg-type]
                infinite_emitter=bool(row.get("infinite_emitter")), infinite_particle=bool(row.get("infinite_particle")),
                has_lights=bool(row.get("has_lights")), max_spawnable_time=float(row.get("max_spawnable_time", 0.0)),
                life_cycle_time=float(row.get("life_cycle_time", 0.0)), byte_length=int(row.get("byte_length", 0)),
                walk_note=str(row.get("walk_note", "")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        catalogue.facts[item.stem] = item
    return catalogue
