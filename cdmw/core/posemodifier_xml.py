"""Reader and surgical editor for `posemodifierdata.xml`.

`character/descriptors/posemodifierdata/posemodifierdata.xml` is 119 KB of the rig
behaviour the game actually runs: how far a creature turns its head to look at you, how
much a spine lags behind a turn, wheel radii and suspension travel on every cart, the
reach of each IK limb. It is keyed by `.pab` skeleton, so one block can serve five
characters.

Unlike `.papr`, this one is demonstrably live -- the engine's own
`pa::engineScript::PoseModifier*` classes are named after its sections.

## Why this does not use an XML parser

It is not one XML document and it is not well formed:

* eleven `<PoseModifierDataList>` root elements, one after another;
* nine anonymous `</>` closing tags;
* a UTF-8 BOM and no XML declaration;
* 24 comments, several of them Korean labels naming the vehicle a block belongs to
  (`<!-- 순환마차 -->`), which are the only human-readable identification in the file.

`ElementTree` refuses it outright ("junk after document element"). Feeding it through a
tolerant parser and re-serialising would fix the file into strict XML, drop the
comments, and rewrite the hand-authored tabs -- changing thousands of bytes the engine
reads with its own tolerant parser, to no benefit and some risk.

So this module scans rather than parses, records the byte span of every value, and
edits by patching those spans. An unedited document re-emits its source exactly, and an
edited one differs only inside the values that changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence, Tuple

_BOM = "﻿"

#: A tag, a comment, or an anonymous close. Ordered so comments win over tags.
#: The comment accepts `--!>` as well as `-->`, because a tolerant parser ends a
#: comment at either and a scanner that only knows `-->` runs straight past the
#: first one, swallowing the markup after it as comment text. Nothing in the
#: shipped file uses that spelling; the point is that mis-scanning it would be
#: silent, and this module's whole contract is that an unedited document re-emits
#: its source exactly.
_TOKEN = re.compile(
    r"(?P<comment><!--(?P<comment_body>.*?)--!?>)"
    r"|(?P<close></\s*(?P<close_name>[A-Za-z_][\w.\-]*)?\s*>)"
    r"|(?P<open><\s*(?P<name>[A-Za-z_][\w.\-]*)(?P<attrs>[^<>]*?)(?P<selfclose>/?)>)",
    re.DOTALL,
)
_ATTR = re.compile(r"(?P<name>[A-Za-z_][\w.\-]*)\s*=\s*\"(?P<value>[^\"]*)\"")


class PoseModifierError(ValueError):
    """Raised when the document is not the pose-modifier descriptor."""


@dataclass(frozen=True)
class Setting:
    """One editable value: an attribute, or the text of a leaf element."""

    #: `PoseModifierDataList` Type, e.g. `LookAt`.
    section: str
    #: `.pab` skeletons this block applies to. Empty for section-level blocks.
    keys: Tuple[str, ...]
    #: Element path inside the block, e.g. `Sight/PitchRange`.
    path: str
    #: Attribute name, or `""` when this is the element's text.
    attribute: str
    value: str
    #: Half-open character span of the value inside the document text.
    span: Tuple[int, int]
    #: Nearest preceding comment, which is often the only label a block has.
    note: str = ""

    @property
    def label(self) -> str:
        leaf = self.path.rsplit("/", 1)[-1]
        return f"{leaf}.{self.attribute}" if self.attribute else leaf

    @property
    def numbers(self) -> Tuple[float, ...]:
        """The numeric fields in the value. `-45 57` is two, `0.5` is one."""

        out = []
        for token in re.findall(r"-?\d+(?:\.\d+)?", self.value):
            try:
                out.append(float(token))
            except ValueError:
                pass
        return tuple(out)

    @property
    def numeric(self) -> bool:
        """True when the value is only numbers and separators, so a slider is safe."""

        return bool(self.value.strip()) and re.fullmatch(
            r"[\s,\-0-9.]+", self.value.strip()
        ) is not None


@dataclass(frozen=True)
class PoseModifierDocument:
    """The parsed descriptor, with the source text it was read from."""

    text: str
    settings: Tuple[Setting, ...]
    sections: Tuple[str, ...]
    #: `.pab` names the file switches a section off for, per section.
    disabled: Mapping[str, Tuple[str, ...]]

    def keys(self) -> Tuple[str, ...]:
        seen: dict[str, None] = {}
        for setting in self.settings:
            for key in setting.keys:
                seen.setdefault(key, None)
        return tuple(sorted(seen))

    def for_key(self, pab: str) -> Tuple[Setting, ...]:
        """Every setting that applies to one skeleton, matched case-insensitively."""

        wanted = pab.lower()
        return tuple(
            setting for setting in self.settings
            if any(key.lower() == wanted for key in setting.keys)
        )

    def for_section(self, section: str) -> Tuple[Setting, ...]:
        return tuple(s for s in self.settings if s.section == section)


def _decode(data: bytes | str) -> tuple[str, bool]:
    if isinstance(data, str):
        return data, False
    raw = data.decode("utf-8-sig", errors="strict")
    return raw, data.startswith(b"\xef\xbb\xbf")


def parse_posemodifier_xml(data: bytes | str, *, name: str = "") -> PoseModifierDocument:
    """Scan the descriptor, recording the span of every value."""

    where = f" ({name})" if name else ""
    text, _bom = _decode(data)
    if "PoseModifierDataList" not in text:
        raise PoseModifierError(f"not a pose-modifier descriptor{where}")

    settings: list[Setting] = []
    sections: list[str] = []
    disabled: dict[str, list[str]] = {}

    stack: list[str] = []
    section = ""
    keys: tuple[str, ...] = ()
    pending_keys: list[str] = []
    in_keylist = False
    in_disabled = False
    note = ""
    block_note = ""
    text_start: int | None = None
    text_owner: tuple[str, str] | None = None

    for match in _TOKEN.finditer(text):
        if match.group("comment"):
            body = match.group("comment_body").strip()
            # Several comments are commented-out markup rather than a label
            # (`<!-- <Bone>Bip01 Pelvis</Bone> -->`). Those describe nothing and showing
            # them as a description fills the column with noise.
            body = "" if "<" in body else body
            # A comment inside the key list names the whole block -- that is where the
            # Korean vehicle labels live, and they are the only identification a block
            # has. Anywhere else it labels the element that follows it.
            if in_keylist or in_disabled:
                block_note = body
            else:
                note = body
            continue

        # Text content of the element we just opened, if it is a leaf.
        if text_start is not None and text_owner is not None:
            raw = text[text_start:match.start()]
            if raw.strip():
                path, owner_note = text_owner
                value_start = text_start + (len(raw) - len(raw.lstrip()))
                value_end = text_start + len(raw.rstrip())
                if in_keylist or in_disabled:
                    pending_keys.append(raw.strip())
                else:
                    settings.append(Setting(
                        section=section, keys=keys, path=path, attribute="",
                        value=raw.strip(), span=(value_start, value_end),
                        note=owner_note or block_note,
                    ))
            text_start = None
            text_owner = None

        if match.group("close"):
            closing = match.group("close_name") or (stack[-1] if stack else "")
            if closing == "KeyList":
                keys = tuple(pending_keys)
                pending_keys = []
                in_keylist = False
            elif closing == "DisabledKeyList":
                disabled.setdefault(section, []).extend(pending_keys)
                pending_keys = []
                in_disabled = False
            elif closing == "PoseModifierData":
                keys = ()
                block_note = ""
            if stack:
                stack.pop()
            continue

        name_ = match.group("name")
        attrs = match.group("attrs") or ""
        self_close = bool(match.group("selfclose"))
        path = "/".join(stack[2:] + [name_]) if len(stack) >= 2 else name_

        if name_ == "PoseModifierDataList":
            found = _ATTR.search(attrs)
            section = found.group("value") if found and found.group("name") == "Type" else ""
            if section:
                sections.append(section)
        elif name_ == "KeyList":
            in_keylist = True
            pending_keys = []
        elif name_ == "DisabledKeyList":
            in_disabled = True
            pending_keys = []

        for attr in _ATTR.finditer(attrs):
            if name_ == "PoseModifierDataList" and attr.group("name") == "Type":
                continue
            offset = match.start("attrs") + attr.start("value")
            settings.append(Setting(
                section=section, keys=keys, path=path, attribute=attr.group("name"),
                value=attr.group("value"),
                span=(offset, offset + len(attr.group("value"))), note=note or block_note,
            ))

        if not self_close:
            stack.append(name_)
            text_start = match.end()
            text_owner = (path, note)
        # A note labels the element that follows it, not every element after it.
        if name_ not in ("KeyList", "DisabledKeyList"):
            note = ""

    if not sections:
        raise PoseModifierError(f"no PoseModifierDataList sections found{where}")
    return PoseModifierDocument(
        text=text,
        settings=tuple(settings),
        sections=tuple(sections),
        disabled={k: tuple(v) for k, v in disabled.items()},
    )


def encode_posemodifier_xml(document: PoseModifierDocument, *, bom: bool = True) -> bytes:
    """Serialise back to bytes. An unedited document reproduces its source exactly."""

    return (_BOM + document.text if bom else document.text).encode("utf-8")


def set_values(
    document: PoseModifierDocument,
    changes: Mapping[Tuple[int, int], str],
    *,
    expected: Mapping[Tuple[int, int], str] | None = None,
) -> PoseModifierDocument:
    """Replace values by span. `expected` guards against editing the wrong document.

    Spans are applied right to left so earlier offsets stay valid while later ones move.
    """

    if not changes:
        return document
    text = document.text
    for span in sorted(changes, key=lambda s: -s[0]):
        start, end = span
        if not 0 <= start <= end <= len(text):
            raise PoseModifierError(f"span {span} is outside the document")
        replacement = changes[span]
        if '"' in replacement or "<" in replacement or ">" in replacement:
            raise PoseModifierError(f"value {replacement!r} would break the markup")
        if expected is not None:
            if span not in expected:
                raise PoseModifierError(f"no expected value given for span {span}")
            if text[start:end] != expected[span]:
                raise PoseModifierError(
                    f"span {span} holds {text[start:end]!r}, not {expected[span]!r}"
                )
        text = text[:start] + replacement + text[end:]
    return parse_posemodifier_xml(text)


def set_setting(
    document: PoseModifierDocument, setting: Setting, value: str
) -> PoseModifierDocument:
    """Replace one setting's value, checking it still holds what the caller read."""

    return set_values(document, {setting.span: value}, expected={setting.span: setting.value})


def scale_setting(
    document: PoseModifierDocument, setting: Setting, factor: float, *, places: int = 3
) -> PoseModifierDocument:
    """Multiply every number in a value, keeping its separators and its number style.

    `-45 57` scaled by 2 becomes `-90 114`: the two-number form these ranges use is
    preserved rather than collapsed to a single value. A token written with a decimal
    point keeps one, so `-60.0` halves to `-30.0` rather than `-30` -- the file is hand
    authored and a diff should not carry reformatting the modder did not ask for.
    """

    if not setting.numeric:
        raise PoseModifierError(f"{setting.label} is not numeric: {setting.value!r}")

    def rescale(match: re.Match) -> str:
        token = match.group(0)
        scaled = round(float(token) * factor, places)
        if scaled == int(scaled):
            return f"{int(scaled)}.0" if "." in token else str(int(scaled))
        return str(scaled)

    return set_setting(
        document, setting, re.sub(r"-?\d+(?:\.\d+)?", rescale, setting.value)
    )


def rebuild_is_exact(data: bytes, *, name: str = "") -> bool:
    """Parse then re-encode, and say whether the bytes came back identical."""

    try:
        document = parse_posemodifier_xml(data, name=name)
    except PoseModifierError:
        return False
    return encode_posemodifier_xml(document, bom=data.startswith(b"\xef\xbb\xbf")) == data


def changed_files(original: bytes, document: PoseModifierDocument, game_path: str) -> dict:
    """`{game path: bytes}` for the packager, empty when nothing actually changed."""

    rebuilt = encode_posemodifier_xml(document, bom=original.startswith(b"\xef\xbb\xbf"))
    return {} if rebuilt == original else {game_path: rebuilt}
