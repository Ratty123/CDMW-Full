"""What the sound bank editor shows and how its edits are applied, without Qt.

`bank_value_rows` lists every value the constrained writer can change in a
version-150 bank. `apply_sound_bank_edit_plan` applies a plan in a fixed
order (in-place values, then added/removed properties, then removed and added
variations), re-reading the bank between steps so every step sees the layout
the previous one produced.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from cdmw.core.archive_wwise_bank import HIRC_OBJECT_TYPES, read_bank_embedded_bytes, read_embedded_media
from cdmw.core.archive_wwise_bank_edit import (
    ADDABLE_PROPERTIES_BY_KIND,
    ADDABLE_RANGES_BY_KIND,
    EDITABLE_PROPERTY_ENCODINGS,
    HircEdit,
    HircPropertyChange,
    WwiseBankEditError,
    apply_hirc_edits,
    change_hirc_properties,
)
from cdmw.core.archive_wwise_bank_variations import (
    add_sound_variation,
    allocate_wwise_id,
    bank_ids,
    remove_sound_variation,
)
from cdmw.core.archive_wwise_hirc import (
    KIND_ACTION,
    KIND_RANDOM_SEQUENCE,
    KIND_SOUND,
    PARSED,
    PROPERTY_NAMES,
    read_hirc_graph,
)

_UNITS = {
    0x00: "dB", 0x01: "cents", 0x02: "", 0x03: "", 0x04: "dB", 0x05: "dB", 0x06: "", 0x08: "dB", 0x09: "dB",
    0x0A: "dB", 0x0B: "dB", 0x0C: "dB", 0x0D: "dB", 0x22: "s", 0x29: "%", 0x39: "ms", 0x3A: "ms", 0x54: "loops (0 = forever)",
}


@dataclass(slots=True, frozen=True)
class BankValueRow:
    object_id: int
    kind: int
    target: str
    """The `HircEdit` target that writes this value."""

    value: float | int
    integer: bool
    unit: str = ""

    @property
    def kind_name(self) -> str:
        return HIRC_OBJECT_TYPES.get(self.kind, f"type {self.kind}")


@dataclass(slots=True, frozen=True)
class VariationRequest:
    container_id: int
    template_sound_id: int
    audio_path: Path
    weight: Optional[int] = None


@dataclass(slots=True, frozen=True)
class SoundBankEditPlan:
    values: Tuple[HircEdit, ...] = ()
    properties: Tuple[HircPropertyChange, ...] = ()
    removed_variations: Tuple[Tuple[int, int], ...] = ()
    """(container id, sound id) pairs."""

    added_variations: Tuple[VariationRequest, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.values or self.properties or self.removed_variations or self.added_variations)


@dataclass(slots=True, frozen=True)
class SoundBankObject:
    """One object the editor can add a property to, with what it may take."""

    object_id: int
    kind: int
    addable_properties: Tuple[str, ...]
    addable_ranges: Tuple[str, ...]
    children: Tuple[int, ...] = ()
    """For a random/sequence container: its child Sounds, which can be copied or removed."""


@dataclass(slots=True, frozen=True)
class SoundBankEditorModel:
    rows: Tuple[BankValueRow, ...]
    objects: Tuple[SoundBankObject, ...]
    notes: Tuple[str, ...] = field(default_factory=tuple)


def _decoded(raw: int, encoding: str) -> float | int:
    return struct.unpack(encoding, struct.pack("<I", raw))[0]


def build_sound_bank_editor_model(data: bytes) -> SoundBankEditorModel:
    graph = read_hirc_graph(data)
    if not graph.nodes:
        version = graph.version or "unknown"
        return SoundBankEditorModel((), (), (f"Bank version {version} is not decoded, so nothing can be edited.",))
    rows: List[BankValueRow] = []
    objects: List[SoundBankObject] = []
    by_id = graph.by_id()
    counts: dict[int, int] = {}
    for node in graph.nodes:
        counts[node.object_id] = counts.get(node.object_id, 0) + 1
    for node in graph.nodes:
        if node.status != PARSED or counts[node.object_id] > 1:
            continue
        for prop in node.properties:
            encoding = EDITABLE_PROPERTY_ENCODINGS.get(prop.prop_id)
            if encoding:
                rows.append(BankValueRow(node.object_id, node.kind, f"property:{prop.name}", _decoded(prop.raw, encoding),
                                         encoding != "<f", _UNITS.get(prop.prop_id, "")))
        for item in node.ranged_properties:
            encoding = EDITABLE_PROPERTY_ENCODINGS.get(item.prop_id)
            if encoding:
                unit = _UNITS.get(item.prop_id, "")
                rows.append(BankValueRow(node.object_id, node.kind, f"range:{item.name}:min", _decoded(item.min_raw, encoding), encoding != "<f", unit))
                rows.append(BankValueRow(node.object_id, node.kind, f"range:{item.name}:max", _decoded(item.max_raw, encoding), encoding != "<f", unit))
        for value in node.values:
            if node.kind == KIND_ACTION or node.kind == KIND_RANDOM_SEQUENCE:
                rows.append(BankValueRow(node.object_id, node.kind, f"value:{value.name}", value.value, value.encoding != "<f"))
        for item in node.playlist:
            rows.append(BankValueRow(node.object_id, node.kind, f"weight:{item.object_id}", item.weight, True, "playlist weight"))
        if "property_bundle" in node.details:
            stored = {prop.prop_id for prop in node.properties}
            stored_ranges = {item.prop_id for item in node.ranged_properties}
            children: Tuple[int, ...] = ()
            if node.kind == KIND_RANDOM_SEQUENCE:
                children = tuple(child for child in node.children if child in by_id and by_id[child].kind == KIND_SOUND)
            objects.append(
                SoundBankObject(
                    node.object_id,
                    node.kind,
                    tuple(PROPERTY_NAMES[i] for i in sorted(ADDABLE_PROPERTIES_BY_KIND.get(node.kind, ())) if i not in stored),
                    tuple(PROPERTY_NAMES[i] for i in sorted(ADDABLE_RANGES_BY_KIND.get(node.kind, ()))
                          if i not in stored_ranges and "ranged_bundle" in node.details),
                    children,
                )
            )
    notes = []
    duplicates = sorted(object_id for object_id, count in counts.items() if count > 1)
    if duplicates:
        notes.append(f"{len(duplicates)} object id(s) appear twice in this bank and are left out.")
    return SoundBankEditorModel(tuple(rows), tuple(objects), tuple(notes))


def apply_sound_bank_edit_plan(
    data: bytes,
    plan: SoundBankEditPlan,
    *,
    build_media: Optional[Callable[[bytes, Path], bytes]] = None,
    template_media: Optional[Callable[[int], bytes]] = None,
    taken_ids: Sequence[int] = (),
    on_log: Optional[Callable[[str], None]] = None,
) -> Tuple[bytes, Tuple[str, ...]]:
    """Applies a plan and returns the new bank bytes and what changed.

    `build_media(original, path)` turns the user's audio into Wwise media shaped
    like `original`; `template_media(source_id)` returns the media a template
    Sound plays when the bank does not embed it; `taken_ids` are ids used
    anywhere else in the game, which new ids must avoid.
    """

    log = on_log or (lambda _message: None)
    changes: List[str] = []
    if plan.values:
        result = apply_hirc_edits(data, plan.values)
        data, changes = result.data, changes + list(result.changes)
    if plan.properties:
        result = change_hirc_properties(data, plan.properties)
        data, changes = result.data, changes + list(result.changes)
    for container_id, sound_id in plan.removed_variations:
        result = remove_sound_variation(data, container_id, sound_id)
        data, changes = result.data, changes + list(result.changes)
    taken = set(taken_ids)
    for request in plan.added_variations:
        if build_media is None:
            raise WwiseBankEditError("Adding a variation needs a media builder.")
        graph = read_hirc_graph(data)
        template = graph.by_id().get(request.template_sound_id)
        if template is None or template.source is None:
            raise WwiseBankEditError(f"Sound {request.template_sound_id} is not in this bank.")
        embedded = {item.source_id: item for item in read_embedded_media(data)}
        source_id = template.source.source_id
        if source_id in embedded:
            original = read_bank_embedded_bytes(data, embedded[source_id])
        elif template_media is not None:
            original = template_media(source_id)
        else:
            raise WwiseBankEditError(f"The media sound {request.template_sound_id} plays is not available.")
        media = build_media(original, request.audio_path)
        taken |= bank_ids(data)
        name = f"cdmw_variation_{request.container_id}_{request.audio_path.stem}"
        new_sound = allocate_wwise_id(name, taken)
        taken.add(new_sound)
        new_source = allocate_wwise_id(name + "_media", taken)
        taken.add(new_source)
        log(f"Adding {request.audio_path.name} to container {request.container_id} as sound {new_sound}...")
        result = add_sound_variation(
            data,
            request.container_id,
            request.template_sound_id,
            media,
            new_sound_id=new_sound,
            new_source_id=new_source,
            weight=request.weight,
        )
        data, changes = result.data, changes + list(result.changes)
    return data, tuple(changes)


__all__ = [
    "BankValueRow",
    "SoundBankEditPlan",
    "SoundBankEditorModel",
    "SoundBankObject",
    "VariationRequest",
    "apply_sound_bank_edit_plan",
    "build_sound_bank_editor_model",
]
