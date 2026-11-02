"""Structural HKX edits built on the relocating tagfile codec.

Only edits whose every byte follows from the codec's proven rules are
offered. Today that is string replacement: a ``char`` array reached solely
through ``hkStringPtr`` PTCH entries can take a string of any length; the item
is resized, DATA is laid out again, and every ITEM offset, PTCH entry,
self-relative reference and section size is regenerated. Shared string items
change for every owner, exactly as the game would read them.

Edits that would need derived physics data (hull topology and face angles,
mass properties, compound SIMD trees, constraint frames) are refused with the
reason recorded in ``HKX_BLOCKED_STRUCTURAL_EDITS``. The fixed-size patch gate
(``archive_hkx_edit_gate``) remains the route for in-place value edits.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Sequence, Tuple

from cdmw.core.archive_hkx_tagfile_layout import HKX_ITEM_KIND_ARRAY
from cdmw.core.archive_hkx_tagfile_model import (
    HkxTagfileModel,
    HkxTagfileReference,
    HkxTagfileRefused,
    copy_hkx_tagfile_model,
    parse_hkx_tagfile_model,
    serialize_hkx_tagfile_model,
)

HKX_STRUCTURAL_EDIT_GATE_FORMAT = "cdmw_hkx_structural_edit_gate_v1"
_STRING_POINTER_TYPE = "hkStringPtr"
_MAX_STRING_BYTES = 4096

HKX_BLOCKED_STRUCTURAL_EDITS: Mapping[str, str] = {
    "convex_hull_rebuild": (
        "New or resized hknpConvexShape hulls need each face's minHalfAngle byte, the shape's two header "
        "tolerances and packed mass properties. A normal-angle formula reproduces minHalfAngle for only about "
        "half of the shipped faces, so a generated hull cannot be proven to match what the game expects."
    ),
    "compound_children": (
        "Adding or removing hknpCompoundShape instances also changes the instance SIMD tree and the compound's "
        "mass properties; neither builder has been reproduced against shipped files."
    ),
    "ragdoll_bodies_and_constraints": (
        "Ragdoll bodies, constraints and motors carry frames, limits and motor links whose derivation from a "
        "skeleton is not recovered."
    ),
    "mesh_shapes": "hknpMeshShape geometry sections and their AABB trees use an unrecovered quantised encoding.",
    "new_types": "Adding a class to the TYPE section (TST1/TNA1/MTTP) is not implemented.",
    "cloth": "No installed HKX file contains a Havok Cloth (hcl) class, so there is no cloth data to rebuild.",
}


def _inbound_references(model: HkxTagfileModel) -> Dict[int, List[HkxTagfileReference]]:
    inbound: Dict[int, List[HkxTagfileReference]] = {}
    for reference in model.references:
        inbound.setdefault(reference.target_item, []).append(reference)
    return inbound


def _string_owner_ok(
    model: HkxTagfileModel, item_index: int, inbound: Mapping[int, Sequence[HkxTagfileReference]]
) -> Tuple[bool, str]:
    item = model.items[item_index]
    if item.kind != HKX_ITEM_KIND_ARRAY or model.type_name(item_index) != "char":
        return False, f"Item {item_index} is {model.type_name(item_index)}, not a char array."
    references = inbound.get(item_index, ())
    if not references:
        return False, f"Item {item_index} has no owner."
    for reference in references:
        if not reference.is_patch or model.type_names[int(reference.patch_type)] != _STRING_POINTER_TYPE:
            return False, f"Item {item_index} is reached by something other than an hkStringPtr."
    if not item.payload.endswith(b"\0") or b"\0" in item.payload[:-1]:
        return False, f"Item {item_index} is not one NUL-terminated string."
    return True, ""


def hkx_string_items(model: HkxTagfileModel) -> List[Tuple[int, str]]:
    """Return (item index, text) for every string the structural edit can replace.

    Shipped strings are UTF-8 (one source-scene path is Korean); undecodable
    bytes survive as surrogate escapes so a no-op replacement is byte-exact.
    """

    inbound = _inbound_references(model)
    strings = []
    for index in range(1, len(model.items)):
        if model.type_name(index) != "char":
            continue
        ok, _ = _string_owner_ok(model, index, inbound)
        if ok:
            strings.append((index, bytes(model.items[index].payload[:-1]).decode("utf-8", "surrogateescape")))
    return strings


def replace_hkx_string_items(model: HkxTagfileModel, texts: Mapping[int, str]) -> HkxTagfileModel:
    """Return a copy of ``model`` whose string items hold the given texts (item index -> text)."""

    inbound = _inbound_references(model)
    encoded_by_item: Dict[int, bytes] = {}
    for item_index, text in texts.items():
        if not 0 < item_index < len(model.items):
            raise HkxTagfileRefused("bad_edit", f"Item {item_index} does not exist.")
        ok, reason = _string_owner_ok(model, item_index, inbound)
        if not ok:
            raise HkxTagfileRefused("unproven_edit", reason)
        if "\0" in text:
            raise HkxTagfileRefused("bad_edit", "HKX strings cannot contain NUL characters.")
        encoded = text.encode("utf-8", "surrogateescape") + b"\0"
        if len(encoded) > _MAX_STRING_BYTES:
            raise HkxTagfileRefused("bad_edit", f"Strings are limited to {_MAX_STRING_BYTES - 1} bytes.")
        encoded_by_item[item_index] = encoded
    edited = copy_hkx_tagfile_model(model)
    for item_index, encoded in encoded_by_item.items():
        edited.items[item_index].payload = bytearray(encoded)
        edited.items[item_index].count = len(encoded)
    return edited


def replace_hkx_string_item(model: HkxTagfileModel, item_index: int, text: str) -> HkxTagfileModel:
    """Return a copy of ``model`` whose string item ``item_index`` holds ``text``."""

    return replace_hkx_string_items(model, {item_index: text})


def rename_hkx_strings(data: bytes, renames: Mapping[str, str]) -> bytes:
    """Rewrite every replaceable string equal to a key of ``renames``; refuse unknown keys."""

    model = parse_hkx_tagfile_model(data)
    strings = hkx_string_items(model)
    known = {text for _, text in strings}
    missing = sorted(set(renames) - known)
    if missing:
        raise HkxTagfileRefused("bad_edit", f"No replaceable string equals {missing[0]!r}.")
    edits = {item_index: renames[text] for item_index, text in strings if text in renames}
    return serialize_hkx_tagfile_model(replace_hkx_string_items(model, edits))


def hkx_structural_edit_gate_document(data: bytes) -> Dict[str, object]:
    """Describe which structural edits this file allows and why the others are refused."""

    document: Dict[str, object] = {
        "format": HKX_STRUCTURAL_EDIT_GATE_FORMAT,
        "fallback": "fixed_size_patch_gate",
        "blocked": dict(HKX_BLOCKED_STRUCTURAL_EDITS),
    }
    try:
        model = parse_hkx_tagfile_model(data)
    except HkxTagfileRefused as exc:
        document.update(codec_status="refused", codec_refusal_code=exc.code, codec_refusal=str(exc), allowed=[])
        return document
    if serialize_hkx_tagfile_model(model) != data:
        document.update(codec_status="rebuild_mismatch", allowed=[])
        return document
    strings = hkx_string_items(model)
    document.update(
        codec_status="exact",
        items=len(model.items) - 1,
        references=len(model.references),
        allowed=["string_replace"] if strings else [],
        strings=[{"item": index, "text": text} for index, text in strings],
    )
    return document
