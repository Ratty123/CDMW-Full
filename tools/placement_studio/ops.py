"""The operation vocabulary, plus derive / replay / merge.

The vocabulary *is* the safety model. Only Tier A-E operations exist, so the unsafe
edits that got the previous Weapon Placement Studio disabled are unrepresentable rather
than merely validated against.

XML edits are surgical text replacements, never parse-and-reserialize: the game files use
tabs, a fixed attribute order, and 6-decimal floats that no serializer round-trips.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import paac
from .corpus import Baseline, GoldenMod, normalize_game_path, sha256_bytes

# Paths carried wholesale as prerequisites rather than edited (Tier E).
_PREREQUISITE_SUFFIXES = ("characterinfo.pabgb",)

# Element identity attributes, by file kind.
_SOCKET_KEY = "Name"
_DESCRIPTOR_KEY = "PartName"

_SOCKET_ATTRS = ("Rotation", "Translation", "Parent")
_DESCRIPTOR_ATTRS = (
    "InSocketBone",
    "OutSocketBone",
    "InChildSocketBone",
    "OutChildSocketBone",
    "WeaponCasePart",
    "BagSocketBone",
    "VehicleBagSocketBone",
)


class DeriveError(RuntimeError):
    """Raised when a golden file cannot be expressed in the operation vocabulary."""


class ConflictError(RuntimeError):
    """Raised when two operation lists disagree about the same target."""


# ── Operations ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Operation:
    tier: str
    kind: str
    game_path: str
    target: str
    detail: Mapping[str, object] = field(default_factory=dict)

    @property
    def conflict_key(self) -> Tuple[str, str, str]:
        """Two operations conflict only when they address the same *field*.

        Rotation, Translation and Parent on one socket are three independent edits, so the
        attribute belongs in the key — otherwise a single plan appears to conflict with
        itself, and genuine cross-plan conflicts get lost in the noise.
        """

        attr = str(self.detail.get("attr") or "")
        # The root-level descriptor alias and its canonical twin are required to stay
        # byte-identical, so an edit to either is the same edit. Keying on the canonical
        # path lets a plan that ships only the alias compose with one that ships both.
        path = descriptor_alias_source(self.game_path) or self.game_path
        return (path, self.target, attr)

    def describe(self) -> str:
        if self.kind == "xml_attr":
            return (
                f"[{self.tier}] {self.game_path} :: {self.target} "
                f"{self.detail.get('attr')}: {self.detail.get('old')!r} -> {self.detail.get('new')!r}"
            )
        if self.kind == "paac_retarget":
            sites = self.detail.get("offsets") or []
            return (
                f"[{self.tier}] {self.game_path} :: retarget {self.detail.get('old')!r} -> "
                f"{self.detail.get('new')!r} at {len(sites)} site(s)"
            )
        return f"[{self.tier}] {self.game_path} :: {self.kind} {self.target}"

    def to_json(self) -> Dict[str, object]:
        return {
            "tier": self.tier,
            "kind": self.kind,
            "game_path": self.game_path,
            "target": self.target,
            "detail": dict(self.detail),
        }

    @staticmethod
    def from_json(payload: Mapping[str, object]) -> "Operation":
        return Operation(
            tier=str(payload["tier"]),
            kind=str(payload["kind"]),
            game_path=str(payload["game_path"]),
            target=str(payload["target"]),
            detail=dict(payload.get("detail") or {}),
        )


@dataclass(frozen=True, slots=True)
class Plan:
    """An ordered operation list. Composition happens here, not at the file level."""

    name: str
    operations: tuple[Operation, ...] = field(default=())
    blobs: Mapping[str, str] = field(default_factory=dict)  # sha256 -> hex payload key

    def tier_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for op in self.operations:
            counts[op.tier] = counts.get(op.tier, 0) + 1
        return dict(sorted(counts.items()))

    def touched_paths(self) -> List[str]:
        return sorted({op.game_path for op in self.operations})

    def to_json(self) -> Dict[str, object]:
        return {
            "format": "cdmw_placement_plan_v1",
            "name": self.name,
            "operations": [op.to_json() for op in self.operations],
        }


# ── XML surgery ──────────────────────────────────────────────────────


def container_span(text: str, tag: str) -> Optional[Tuple[int, int]]:
    """Locate `<tag ...> ... </tag>` and return the span of its inner body.

    Socket files hold the same `<Socket Name=...>` element name in two roles: real
    definitions inside `<SocketList>`, and bare references inside `<StackEquipInfo>`.
    Every element operation is scoped to a container so the two never mix.
    """

    open_match = re.search(rf"<{re.escape(tag)}\b[^>]*?>", text)
    if open_match is None:
        return None
    if open_match.group(0).rstrip().endswith("/>"):
        return (open_match.end(), open_match.end())
    close_index = text.find(f"</{tag}>", open_match.end())
    if close_index < 0:
        return None
    return (open_match.end(), close_index)


def _element_spans(
    text: str,
    key_attr: str,
    *,
    container: Optional[str] = None,
) -> Dict[str, Tuple[int, int]]:
    """Map element identity -> (start, end) span of its opening tag."""

    lower, upper = 0, len(text)
    if container:
        span = container_span(text, container)
        if span is None:
            return {}
        lower, upper = span

    spans: Dict[str, Tuple[int, int]] = {}
    for match in re.finditer(r"<[A-Za-z_][\w.\-]*\s[^<>]*?/?>", text, re.DOTALL):
        if match.start() < lower or match.end() > upper:
            continue
        chunk = match.group(0)
        key_match = re.search(rf'\b{re.escape(key_attr)}="([^"]*)"', chunk)
        if key_match:
            spans.setdefault(key_match.group(1), (match.start(), match.end()))
    return spans


def _container_for(game_path: str) -> Optional[str]:
    return "SocketList" if game_path.lower().endswith(".sockets.xml") else None


def _bump_count(text: str, tag: str, delta: int) -> str:
    """Keep a container's `Count` attribute consistent with its element count."""

    match = re.search(rf'(<{re.escape(tag)}\b[^>]*?\bCount=")(\d+)(")', text)
    if match is None:
        return text
    updated = int(match.group(2)) + delta
    return text[: match.start()] + f"{match.group(1)}{updated}{match.group(3)}" + text[match.end() :]


def _attributes(chunk: str) -> Dict[str, str]:
    return dict(re.findall(r'\b([A-Za-z_][\w.\-]*)="([^"]*)"', chunk))


def _key_attr_for(game_path: str) -> Optional[str]:
    lowered = game_path.lower()
    if lowered.endswith(".sockets.xml"):
        return _SOCKET_KEY
    if "characterdescription" in lowered or "_description_player" in lowered:
        return _DESCRIPTOR_KEY
    return None


def _tracked_attrs_for(game_path: str) -> Sequence[str]:
    return _SOCKET_ATTRS if game_path.lower().endswith(".sockets.xml") else _DESCRIPTOR_ATTRS


def apply_xml_attr(
    text: str,
    key_attr: str,
    element: str,
    attr: str,
    old: str,
    new: str,
    *,
    container: Optional[str] = None,
) -> str:
    """Replace one attribute inside one element, leaving every other byte untouched."""

    spans = _element_spans(text, key_attr, container=container)
    if element not in spans:
        raise DeriveError(f"Element {key_attr}={element!r} not found")
    start, end = spans[element]
    chunk = text[start:end]
    needle = f'{attr}="{old}"'
    if needle not in chunk:
        raise DeriveError(f"{key_attr}={element!r} has no {attr}={old!r}")
    return text[:start] + chunk.replace(needle, f'{attr}="{new}"', 1) + text[end:]


def apply_xml_attr_add(
    text: str,
    key_attr: str,
    element: str,
    attr: str,
    value: str,
    *,
    after_attr: str = "",
    container: Optional[str] = None,
) -> str:
    """Add an attribute that vanilla omits, placed after a named sibling attribute."""

    spans = _element_spans(text, key_attr, container=container)
    if element not in spans:
        raise DeriveError(f"Element {key_attr}={element!r} not found")
    start, end = spans[element]
    chunk = text[start:end]
    if re.search(rf'\b{re.escape(attr)}="', chunk):
        raise DeriveError(f"{key_attr}={element!r} already has {attr}")

    addition = f' {attr}="{value}"'
    anchor = re.search(rf'\b{re.escape(after_attr)}="[^"]*"', chunk) if after_attr else None
    if anchor is not None:
        updated = chunk[: anchor.end()] + addition + chunk[anchor.end() :]
    else:
        tail = re.search(r"\s*/?>$", chunk)
        cut = tail.start() if tail else len(chunk)
        updated = chunk[:cut] + addition + chunk[cut:]
    return text[:start] + updated + text[end:]


def apply_xml_element_add(
    text: str,
    key_attr: str,
    element: str,
    raw: str,
    *,
    after: str,
    container: Optional[str] = None,
) -> str:
    """Insert a new element after a named sibling, keeping `Count` consistent.

    `raw` carries its own leading whitespace so indentation is reproduced exactly.
    """

    spans = _element_spans(text, key_attr, container=container)
    if element in spans:
        raise DeriveError(f"Element {key_attr}={element!r} already exists")
    if after and after in spans:
        insert_at = spans[after][1]
    else:
        span = container_span(text, container) if container else None
        if span is None:
            raise DeriveError(f"No insertion anchor for {element!r}")
        insert_at = span[1]
    updated = text[:insert_at] + raw + text[insert_at:]
    return _bump_count(updated, container, 1) if container else updated


# ── Derivation ───────────────────────────────────────────────────────


def _is_prerequisite(game_path: str) -> bool:
    return any(game_path.lower().endswith(suffix) for suffix in _PREREQUISITE_SUFFIXES)


def descriptor_alias_source(game_path: str) -> str:
    """Return the canonical descriptor a root-level alias mirrors, if any.

    The tuning guide requires `character/<name>.xml` and
    `character/descriptors/characterdescription/<name>.xml` to stay byte-identical. Treating
    the alias as a *derived* output rather than an independent file keeps that invariant
    structural, and lets two plans that both add it compose instead of colliding.
    """

    path = normalize_game_path(game_path)
    parts = path.split("/")
    if len(parts) == 2 and parts[0] == "character" and parts[1].endswith("_description_player_") is False:
        if parts[1].endswith(".xml") and "description" in parts[1]:
            return f"character/descriptors/characterdescription/{parts[1]}"
    return ""


def _decode(data: bytes) -> Optional[str]:
    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def derive_file(
    game_path: str,
    vanilla: Optional[bytes],
    modded: bytes,
    *,
    baseline: Optional[Baseline] = None,
    hash_index: Optional[Mapping[str, str]] = None,
) -> List[Operation]:
    """Express one modded file as operations against its vanilla counterpart."""

    path = normalize_game_path(game_path)
    digest = sha256_bytes(modded)

    if vanilla is not None and vanilla == modded:
        return []

    if _is_prerequisite(path):
        return [
            Operation(
                "E",
                "payload_carry",
                path,
                "*",
                {"sha256": digest, "size": len(modded), "same_length": vanilla is not None and len(vanilla) == len(modded)},
            )
        ]

    key_attr = _key_attr_for(path)
    if key_attr and vanilla is not None:
        vanilla_text = _decode(vanilla)
        modded_text = _decode(modded)
        if vanilla_text is not None and modded_text is not None:
            return _derive_xml(path, key_attr, vanilla_text, modded_text)

    if path.endswith(".paac") and vanilla is not None and len(vanilla) == len(modded):
        renames: Dict[Tuple[str, str], List[int]] = {}
        for old, new, offset in paac.diff_socket_renames(vanilla, modded):
            renames.setdefault((old, new), []).append(offset)
        if renames:
            rebuilt = vanilla
            for (old, new), offsets in renames.items():
                rebuilt = paac.retarget(rebuilt, old, new, offsets=offsets)
            if rebuilt == modded:
                return [
                    Operation("C", "paac_retarget", path, old, {"old": old, "new": new, "offsets": offsets})
                    for (old, new), offsets in sorted(renames.items())
                ]

    # Whole-file: substitution from an existing payload (Tier D) if the bytes already
    # exist somewhere in vanilla, otherwise an opaque carry.
    origin = (hash_index or {}).get(digest)
    tier = "D" if origin else "E"
    return [
        Operation(
            tier,
            "file_replace" if vanilla is not None else "file_add",
            path,
            "*",
            {"sha256": digest, "size": len(modded), "origin": origin or ""},
        )
    ]


def _derive_xml(path: str, key_attr: str, vanilla_text: str, modded_text: str) -> List[Operation]:
    tier = "A" if key_attr == _SOCKET_KEY else "B"
    tracked = _tracked_attrs_for(path)
    container = _container_for(path)

    vanilla_spans = _element_spans(vanilla_text, key_attr, container=container)
    modded_spans = _element_spans(modded_text, key_attr, container=container)

    # Ordered identities in the modded file, so an insertion can name its predecessor.
    ordered = [name for name, _span in sorted(modded_spans.items(), key=lambda kv: kv[1][0])]
    predecessor = {name: (ordered[i - 1] if i else "") for i, name in enumerate(ordered)}

    operations: List[Operation] = []
    for element in ordered:
        start, end = modded_spans[element]
        modded_attrs = _attributes(modded_text[start:end])
        if element not in vanilla_spans:
            # Capture from the predecessor's exact end so the separator bytes (CRLF plus
            # indentation) are reproduced verbatim rather than reconstructed.
            after = predecessor.get(element, "")
            if after and after in modded_spans:
                raw = modded_text[modded_spans[after][1] : end]
            else:
                body = container_span(modded_text, container) if container else None
                raw = modded_text[body[0] : end] if body else modded_text[start:end]
            operations.append(
                Operation(
                    # Socket *creation* in a definition file is safe; it is referencing a
                    # socket that does not exist that must stay blocked.
                    "A2" if tier == "A" else "B2",
                    "xml_element_add",
                    path,
                    element,
                    {
                        "raw": raw,
                        "after": after,
                        "container": container or "",
                        # `raw` and `after` are position-dependent: the same socket added at
                        # a different index yields different bytes for identical intent.
                        # Content is what two plans must agree on, so conflict detection
                        # compares this and ignores placement.
                        "content": modded_attrs,
                    },
                )
            )
            continue
        v_start, v_end = vanilla_spans[element]
        vanilla_attrs = _attributes(vanilla_text[v_start:v_end])
        modded_order = [
            name for name, _value in re.findall(r'\b([A-Za-z_][\w.\-]*)="([^"]*)"', modded_text[start:end])
        ]
        for attr in tracked:
            old = vanilla_attrs.get(attr)
            new = modded_attrs.get(attr)
            if new is None or old == new:
                continue
            if old is None:
                # Routing attributes are optional in vanilla; adding one is a real edit.
                position = modded_order.index(attr) if attr in modded_order else 0
                after_attr = modded_order[position - 1] if position > 0 else ""
                operations.append(
                    Operation(
                        tier,
                        "xml_attr_add",
                        path,
                        element,
                        {"attr": attr, "new": new, "after_attr": after_attr},
                    )
                )
                continue
            operations.append(
                Operation(tier, "xml_attr", path, element, {"attr": attr, "old": old, "new": new})
            )

    # Anything we did not model shows up as an unexplained residue during replay, so
    # verification stays honest rather than silently accepting a partial derivation.
    return operations


def derive_mod(
    mod: GoldenMod,
    baseline: Baseline,
    *,
    hash_index: Optional[Mapping[str, str]] = None,
) -> Tuple[Plan, List[str]]:
    """Derive a full operation list for a golden mod. Returns (plan, warnings)."""

    operations: List[Operation] = []
    warnings: List[str] = []
    shipped = {entry.game_path for entry in mod.files}
    for entry in mod.files:
        alias_source = descriptor_alias_source(entry.game_path)
        if alias_source and alias_source in shipped:
            # Both halves shipped: the alias is a mirror, so it composes instead of
            # colliding when two plans each add it.
            operations.append(
                Operation("B2", "descriptor_alias", entry.game_path, "*", {"mirrors": alias_source})
            )
            continue

        vanilla: Optional[bytes] = None
        if entry.game_path in baseline:
            vanilla = baseline.read(entry.game_path)
        elif alias_source and alias_source in baseline:
            # Alias shipped alone: it carries the real edits, diffed against the canonical
            # vanilla because the game has no root-level copy to compare with.
            vanilla = baseline.read(alias_source)
        modded = entry.disk_path.read_bytes()
        try:
            derived = derive_file(
                entry.game_path, vanilla, modded, baseline=baseline, hash_index=hash_index
            )
        except Exception as exc:  # noqa: BLE001 - collect, do not abort the corpus sweep
            warnings.append(f"{entry.game_path}: {exc}")
            continue
        operations.extend(derived)
    return Plan(mod.key, tuple(operations)), warnings


# ── Replay ───────────────────────────────────────────────────────────


def canonical_text(data: bytes) -> bytes:
    """Strip incidental editor artifacts before comparing hand-edited files.

    The golden mods were produced in a text editor that dropped the UTF-8 BOM and trimmed
    trailing whitespace — including stray tabs that exist in the *vanilla* files. Those
    differences carry no placement intent, and a tool that reproduced them would be worse,
    not better. Byte identity is still reported separately; this is what the gate uses.
    """

    text = data
    if text.startswith(b"\xef\xbb\xbf"):
        text = text[3:]
    lines = text.replace(b"\r\n", b"\n").split(b"\n")
    return b"\n".join(line.rstrip() for line in lines).rstrip() + b"\n"


def structural_view(data: bytes, game_path: str) -> Optional[Dict[str, Dict[str, str]]]:
    """Reduce an XML file to the element/attribute map the vocabulary actually models.

    Some golden files carry mojibake in their Korean comments: the author's editor read
    UTF-8 as cp1252 and saved it back, corrupting the comment text. Gameplay is unaffected
    (they are comments), which is why it went unnoticed — but it makes byte-identity both
    impossible and undesirable, since correct output is *better* than the hand-made file.
    Comparing the modelled data instead keeps the gate honest without chasing that damage.
    """

    key_attr = _key_attr_for(game_path)
    if key_attr is None:
        return None
    text = _decode(data)
    if text is None:
        return None
    container = _container_for(game_path)
    spans = _element_spans(text, key_attr, container=container)
    return {name: _attributes(text[start:end]) for name, (start, end) in spans.items()}


@dataclass(frozen=True, slots=True)
class ReplayResult:
    matched: tuple[str, ...] = field(default=())
    mismatched: tuple[str, ...] = field(default=())
    unverifiable: tuple[str, ...] = field(default=())
    byte_identical: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.mismatched

    def summary(self) -> str:
        return (
            f"{len(self.matched)} equivalent "
            f"({len(self.byte_identical)} byte-exact), "
            f"{len(self.mismatched)} mismatched, "
            f"{len(self.unverifiable)} opaque"
        )


def replay(plan: Plan, baseline: Baseline) -> Dict[str, bytes]:
    """Apply an operation list to pinned vanilla bytes, producing output files."""

    by_path: Dict[str, List[Operation]] = {}
    for op in plan.operations:
        by_path.setdefault(op.game_path, []).append(op)

    output: Dict[str, bytes] = {}
    aliases: Dict[str, str] = {}
    for path, operations in by_path.items():
        alias = next((op for op in operations if op.kind == "descriptor_alias"), None)
        if alias is not None:
            aliases[path] = str(alias.detail["mirrors"])
            continue

        opaque = [op for op in operations if op.kind in {"file_replace", "file_add", "payload_carry"}]
        if opaque:
            continue  # bytes are not reconstructible from the plan alone; verified by hash

        alias_source = descriptor_alias_source(path)
        if path in baseline:
            data = baseline.read(path)
        elif alias_source and alias_source in baseline:
            data = baseline.read(alias_source)
        else:
            data = b""
        key_attr = _key_attr_for(path)

        if key_attr:
            text = _decode(data)
            if text is None:
                raise DeriveError(f"{path}: not decodable as text")
            container = _container_for(path)
            # Attribute edits first: insertions shift offsets and can add new identities.
            for op in operations:
                if op.kind == "xml_attr":
                    text = apply_xml_attr(
                        text,
                        key_attr,
                        op.target,
                        str(op.detail["attr"]),
                        str(op.detail["old"]),
                        str(op.detail["new"]),
                        container=container,
                    )
                elif op.kind == "xml_attr_add":
                    text = apply_xml_attr_add(
                        text,
                        key_attr,
                        op.target,
                        str(op.detail["attr"]),
                        str(op.detail["new"]),
                        after_attr=str(op.detail.get("after_attr") or ""),
                        container=container,
                    )
            for op in operations:
                if op.kind == "xml_element_add":
                    text = apply_xml_element_add(
                        text,
                        key_attr,
                        op.target,
                        str(op.detail["raw"]),
                        after=str(op.detail.get("after") or ""),
                        container=str(op.detail.get("container") or "") or None,
                    )
            output[path] = text.encode("utf-8")
            continue

        for op in operations:
            if op.kind == "paac_retarget":
                data = paac.retarget(
                    data,
                    str(op.detail["old"]),
                    str(op.detail["new"]),
                    offsets=[int(x) for x in (op.detail.get("offsets") or [])],
                )
        output[path] = data

    # Aliases mirror their canonical descriptor after it has been built.
    for path, source in aliases.items():
        if source in output:
            output[path] = output[source]
        elif source in baseline:
            output[path] = baseline.read(source)
    return output


def verify(plan: Plan, baseline: Baseline, mod: GoldenMod) -> ReplayResult:
    """Replay a plan and compare byte-for-byte against the shipped golden mod."""

    produced = replay(plan, baseline)
    expected = {entry.game_path: entry.disk_path for entry in mod.files}

    opaque_paths = {
        op.game_path
        for op in plan.operations
        if op.kind in {"file_replace", "file_add", "payload_carry"}
    }

    matched: List[str] = []
    mismatched: List[str] = []
    unverifiable: List[str] = []
    byte_identical: List[str] = []

    for path, disk_path in sorted(expected.items()):
        golden = disk_path.read_bytes()
        if path in produced:
            got = produced[path]
            if got == golden:
                matched.append(path)
                byte_identical.append(path)
            elif canonical_text(got) == canonical_text(golden):
                matched.append(path)
            else:
                got_view = structural_view(got, path)
                gold_view = structural_view(golden, path)
                if got_view is not None and got_view == gold_view:
                    matched.append(path)
                else:
                    mismatched.append(path)
        elif path in opaque_paths:
            unverifiable.append(path)
        elif path in baseline and baseline.read(path) == golden:
            matched.append(path)
            byte_identical.append(path)
        else:
            mismatched.append(path)

    return ReplayResult(
        tuple(matched), tuple(mismatched), tuple(unverifiable), tuple(byte_identical)
    )


# ── Merge ────────────────────────────────────────────────────────────


def _intent(op: Operation) -> object:
    """The part of an operation two plans must agree on, ignoring placement bytes."""

    if op.kind == "xml_element_add":
        return op.detail.get("content")
    return {k: v for k, v in op.detail.items() if k != "offsets"}


def merge(plans: Sequence[Plan], *, name: str = "merged") -> Plan:
    """Compose plans at the operation level.

    Two operations on the same file but different targets are not a conflict — that is
    the whole point. Only same-target disagreement is.
    """

    seen: Dict[Tuple[str, str], Operation] = {}
    ordered: List[Operation] = []
    for plan in plans:
        for op in plan.operations:
            existing = seen.get(op.conflict_key)
            if existing is None:
                seen[op.conflict_key] = op
                ordered.append(op)
                continue
            if existing.kind == op.kind and _intent(existing) == _intent(op):
                continue  # identical intent, keep one
            raise ConflictError(
                f"Conflict on {op.game_path} :: {op.target}\n"
                f"  {existing.describe()}\n"
                f"  {op.describe()}"
            )
    return Plan(name, tuple(ordered))


def merge_report(plans: Sequence[Plan]) -> Dict[str, object]:
    """Merge without raising, reporting conflicts as data."""

    seen: Dict[Tuple[str, str], Operation] = {}
    conflicts: List[str] = []
    shared_files: Dict[str, set] = {}
    for plan in plans:
        for op in plan.operations:
            shared_files.setdefault(op.game_path, set()).add(plan.name)
            existing = seen.get(op.conflict_key)
            if existing is None:
                seen[op.conflict_key] = op
            elif existing.kind != op.kind or _intent(existing) != _intent(op):
                conflicts.append(f"{op.game_path} :: {op.target}")
    overlapping = sorted(p for p, names in shared_files.items() if len(names) > 1)
    return {
        "operations": len(seen),
        "conflicts": sorted(set(conflicts)),
        "files_touched_by_multiple_plans": overlapping,
    }


def write_plan(plan: Plan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_json(), indent=2), encoding="utf-8")


def read_plan(path: Path) -> Plan:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return Plan(
        str(payload.get("name", path.stem)),
        tuple(Operation.from_json(row) for row in payload.get("operations", [])),
    )
