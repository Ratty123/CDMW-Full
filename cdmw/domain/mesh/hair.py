"""Immutable host copy of Rust hair rest state; simulation frames never enter it."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from collections.abc import Mapping

HAIR_STATE_VERSION = 1
HAIR_MAX_BYTES = 64 * 1024 * 1024
HAIR_MAX_VERTICES = 500_000


@dataclass(frozen=True, slots=True)
class HairAuthoringState:
    canonical: bytes

    @property
    def payload(self) -> dict:
        return json.loads(self.canonical)

    @property
    def revision(self) -> int:
        return self.payload["revision"]


def hair_state_from_payload(value: object, *, allow_unbound: bool = True) -> HairAuthoringState | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or type(value.get("version")) is not int or value.get("version") != HAIR_STATE_VERSION:
        raise ValueError("Unsupported hair authoring state version.")
    try:
        raw = json.dumps(dict(value), ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Hair authoring state contains unsupported values.") from exc
    if len(raw) > HAIR_MAX_BYTES:
        raise ValueError("Hair authoring state exceeds the 64 MiB limit.")
    state = json.loads(raw)

    def integer(number, limit):
        return type(number) is int and 0 <= number < limit

    def rows(values, width, limit):
        if not isinstance(values, list) or len(values) > limit:
            return False
        return all(isinstance(row, list) and len(row) == width and
                   all(type(v) in (int, float) and math.isfinite(v) for v in row) for row in values)

    if not integer(state.get("revision"), 2**63) or type(state.get("converted")) is not bool:
        raise ValueError("Invalid hair revision or conversion state.")
    scalp = state.get("scalp", {})
    if not isinstance(scalp, dict):
        raise ValueError("Invalid scalp reference geometry.")
    positions, triangles = scalp.get("positions"), scalp.get("triangles")
    if (not isinstance(scalp.get("identity"), str) or not scalp["identity"] or len(scalp["identity"]) > 256
            or not positions or not rows(positions, 3, HAIR_MAX_VERTICES)
            or not triangles or not rows(triangles, 3, 1_000_000)
            or any(not integer(i, len(positions)) for face in triangles for i in face)):
        raise ValueError("Invalid scalp reference geometry.")
    bound = state.get("bound_reference") == scalp["identity"]
    if not isinstance(state.get("bound_reference"), str) or not state["bound_reference"]:
        raise ValueError("Hair state has no reference binding identity.")
    if not allow_unbound and not bound:
        raise ValueError("The reference head changed; explicitly rebind the hair roots.")
    fitting = state.get("references", [])
    if not isinstance(fitting, list) or len(fitting) > 4:
        raise ValueError("Hair supports at most four fitting references.")
    for reference in fitting:
        if (not isinstance(reference, dict) or not isinstance(reference.get("identity"), str)
                or not reference["identity"] or len(reference["identity"]) > 256
                or not reference.get("positions") or not rows(reference["positions"], 3, HAIR_MAX_VERTICES)
                or not reference.get("triangles") or not rows(reference["triangles"], 3, 1_000_000)
                or any(not integer(i, len(reference["positions"])) for face in reference["triangles"] for i in face)):
            raise ValueError("Invalid neck or shoulder fitting reference.")
    template = state.get("template", {})
    if not isinstance(template, dict):
        raise ValueError("Invalid hair template provenance.")
    digest = template.get("sha256", "")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Hair template provenance requires its source SHA-256.")
    if template.get("character") != "Damiane":
        raise ValueError("This hair authoring release targets Damiane.")
    groups, guides, bindings = state.get("groups"), state.get("guides"), state.get("bindings")
    references = state.get("reference_parts")
    if (not isinstance(groups, list) or len(groups) > 128 or not isinstance(guides, list) or len(guides) > 4096
            or not isinstance(bindings, list) or len(bindings) > HAIR_MAX_VERTICES
            or not isinstance(references, list) or any(not integer(i, 4096) for i in references)):
        raise ValueError("Hair state exceeds its group, guide or binding limits.")
    by_id, parts = {}, set()
    for group in groups:
        if (not isinstance(group, dict) or not integer(group.get("id"), 2**32)
                or not integer(group.get("part"), 4096) or group["id"] in by_id or group["part"] in parts
                or group["part"] in references or group.get("mode") not in {"generated", "existing"}):
            raise ValueError("Hair groups must have distinct explicit output parts.")
        width, density, uv = group.get("width"), group.get("cards_per_guide"), group.get("uv_rect")
        if (type(width) not in (int, float) or not 0 < width <= 10
                or not integer(density, 33) or density < 1 or not rows([uv], 4, 1)
                or uv[2] <= uv[0] or uv[3] <= uv[1]):
            raise ValueError("Invalid hair width, density or atlas region.")
        by_id[group["id"]] = group
        parts.add(group["part"])
    for guide in guides:
        if not isinstance(guide, dict) or not integer(guide.get("group"), 2**32) or guide["group"] not in by_id:
            raise ValueError("Guide refers to a missing hair group.")
        points, root = guide.get("points"), guide.get("root", {})
        if not isinstance(root, dict):
            raise ValueError("Invalid guide scalp attachment.")
        bary = root.get("barycentric")
        if (not rows(points, 3, 64) or len(points) < 2 or not integer(root.get("triangle"), len(triangles) if bound else 1_000_000)
                or not rows([bary], 3, 1) or any(v < -1e-5 or v > 1.00001 for v in bary)
                or abs(sum(bary) - 1) > 1e-4):
            raise ValueError("Invalid guide or scalp attachment.")
        if bound:
            face = triangles[root["triangle"]]
            attached = [sum(positions[face[j]][axis] * bary[j] for j in range(3)) for axis in range(3)]
            if math.dist(points[0], attached) > 1e-4:
                raise ValueError("Hair root moved off its scalp attachment.")
        if any(math.dist(a, b) <= 1e-7 for a, b in zip(points, points[1:])):
            raise ValueError("Hair guide has a zero-length segment.")
    seen = set()
    for binding in bindings:
        if not isinstance(binding, dict) or not integer(binding.get("guide"), len(guides)):
            raise ValueError("Hair vertex binding has a missing guide.")
        guide = guides[binding["guide"]]
        key = (binding.get("part"), binding.get("vertex"))
        if (binding.get("part") != by_id[guide["group"]]["part"] or not integer(binding.get("vertex"), HAIR_MAX_VERTICES)
                or not integer(binding.get("segment"), len(guide["points"]) - 1) or key in seen
                or type(binding.get("t")) not in (int, float) or not 0 <= binding["t"] <= 1
                or not rows([binding.get("offset")], 3, 1)):
            raise ValueError("Invalid or ambiguous hair vertex binding.")
        seen.add(key)
    collisions = state.get("collisions")
    if not isinstance(collisions, list) or len(collisions) > 64:
        raise ValueError("Invalid hair collision geometry.")
    for item in collisions:
        if (not isinstance(item, dict) or not rows([item.get("a"), item.get("b")], 3, 2)
                or type(item.get("follows_head", True)) is not bool
                or type(item.get("radius")) not in (int, float) or not 0 < item["radius"] < 1000):
            raise ValueError("Invalid head, neck or shoulder collision capsule.")
    return HairAuthoringState(raw)
