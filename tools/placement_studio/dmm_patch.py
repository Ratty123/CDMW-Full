"""DMM `.xml.patch` files for the shared XML that Placement & Animations edits.

DMM merges a full copy of a shared XML file with other mods' copies by position. Character
Creator Enhanced inserts rows into Kliff's descriptor, so a full copy's edits landed on the
wrong rows and the game crashed at load (research reference, Section 12.3). A
`<file>.xml.patch` beside the target's path edits rows in place instead, found by their
attributes, so it applies on whatever copy DMM has assembled.

The rules below come from DMM 4.7.4 mount logs and in-game mounts, not from documentation:

* `find` takes a bare element name and searches the whole file; `[@...]` predicates and
  `A/B` paths match nothing;
* each `match-<attr>` filter narrows the rows and several are ANDed;
* `<insert into="SocketList">` appends the element it holds to that container.

Two kinds of file are lowered: character descriptors (`PartInOutSocket` rows, keyed by
`PartName`) and body socket files (`<model>.pab.sockets.xml`, sockets keyed by `Name`).
Weapon socket files, prefabs, clips and charts stay whole: they belong to one item.

Every patch is proven before it is used: `apply_patch` replays it the way DMM does, every
operation has to hit exactly one element, and the result has to hold the edited rows. What
a patch cannot express (a removed, added or reordered descriptor row, a removed socket, an
edit outside the rows) is refused with a reason rather than shipped as a full copy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .documents import is_body_socket_file, is_descriptor_file

#: What DMM expects after the target's own file name.
PATCH_SUFFIX = ".patch"

_DESCRIPTOR_KEY = "PartName"
_SOCKET_TAG = "Socket"
_SOCKET_KEY = "Name"
_SOCKET_CONTAINER = "SocketList"

#: Attributes tried, in this order, to single out one of several rows with the same name. The
#: duplicates in shipped descriptors are `PartInOutOverride` rows, which carry only `Visible`.
_ROW_FILTER_PREFERENCE = ("OutSocketBone", "InSocketBone", "Visible")

_TAG = re.compile(r"<(/?)([A-Za-z_][\w.\-]*)?((?:[^<>\"]|\"[^\"]*\")*?)(/?)>")
_ATTRIBUTE = re.compile(r'([A-Za-z_][\w.\-]*)="([^"]*)"')
_COMMENT = re.compile(r"<!--.*?-->|<\?.*?\?>", re.DOTALL)


class PatchError(ValueError):
    """A patch that cannot express the edit, or that would not apply as DMM applies it."""


def patch_path(game_path: str) -> str:
    return game_path + PATCH_SUFFIX


def target_of(patch_game_path: str) -> str:
    """`.../phm_01.pab.sockets.xml.patch` -> `.../phm_01.pab.sockets.xml`, or ""."""

    if patch_game_path.lower().endswith(".xml" + PATCH_SUFFIX):
        return patch_game_path[: -len(PATCH_SUFFIX)]
    return ""


def patchable(game_path: str) -> str:
    """`descriptor`, `body_sockets`, or "" for a file that ships whole."""

    if is_descriptor_file(game_path):
        return "descriptor"
    if is_body_socket_file(game_path):
        return "body_sockets"
    return ""


# ── reading tags ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Tag:
    name: str
    attrs: Tuple[Tuple[str, str], ...]
    start: int
    end: int
    closing: bool
    self_closing: bool
    #: The element names this tag sits inside, outermost first.
    path: Tuple[str, ...]

    def attributes(self) -> Dict[str, str]:
        return dict(self.attrs)


def _blank_comments(text: str) -> str:
    """Comments and declarations as spaces, so offsets still index the original text."""

    return _COMMENT.sub(lambda match: " " * len(match.group(0)), text)


def _tags(text: str) -> List[_Tag]:
    """Every tag in document order. The game closes elements with a bare `</>` as often as
    with `</Name>`, so nesting is tracked by hand."""

    scan = _blank_comments(text)
    stack: List[str] = []
    out: List[_Tag] = []
    for match in _TAG.finditer(scan):
        closing, name, rest, self_closing = match.groups()
        if closing:
            if stack:
                stack.pop()
            out.append(_Tag(name or "", (), match.start(), match.end(), True, False, tuple(stack)))
            continue
        if not name:
            continue
        out.append(_Tag(name, tuple(_ATTRIBUTE.findall(rest)), match.start(), match.end(),
                        False, bool(self_closing), tuple(stack)))
        if not self_closing:
            stack.append(name)
    return out


def decode_text(data: bytes) -> str:
    payload = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    for encoding in ("utf-8", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise PatchError("The file is neither UTF-8 nor cp1252 text")


# ── comparing ────────────────────────────────────────────────────────


def _token(tag: _Tag):
    if tag.closing:
        return ("/",)
    return (tag.name, frozenset(tag.attrs), tag.self_closing)


def _is_socket_definition(tag: _Tag) -> bool:
    return (not tag.closing and tag.name == _SOCKET_TAG and bool(tag.path)
            and tag.path[-1] == _SOCKET_CONTAINER)


def _canonical(text: str, kind: str):
    """What has to be equal for two files to mean the same to the game.

    Attribute order and whitespace are not part of it. For a body socket file, neither is the
    order of the socket definitions: an insert lands at the end of the list.
    """

    tags = _tags(text)
    if kind != "body_sockets":
        return tuple(_token(tag) for tag in tags)
    rest = tuple(_token(tag) for tag in tags if not _is_socket_definition(tag))
    sockets = sorted(sorted(tag.attrs) for tag in tags if _is_socket_definition(tag))
    return rest, tuple(tuple(row) for row in sockets)


# ── writing patches ──────────────────────────────────────────────────


def _filter_text(filters: Sequence[Tuple[str, str]]) -> str:
    return " ".join(f'match-{name}="{value}"' for name, value in filters)


def _attribute_ops(find: str, filters: Sequence[Tuple[str, str]], before: Mapping[str, str],
                   after: Mapping[str, str], *, last: Sequence[str] = ()) -> List[str]:
    """`<set>`/`<unset>` lines turning one element's attributes from `before` into `after`.

    An op on an attribute the filters rely on goes last, or the element's later ops would no
    longer find it; `last` adds attributes to hold back the same way.
    """

    held = {name for name, _value in filters} | set(last)
    head = f'find="{find}" {_filter_text(filters)}'
    ordered: List[Tuple[bool, str]] = []
    for name, value in after.items():
        if before.get(name) != value:
            ordered.append((name in held, f'\t<set {head} attr="{name}" value="{value}"/>'))
    for name in before:
        if name not in after:
            ordered.append((name in held, f'\t<unset {head} attr="{name}"/>'))
    return [line for _late, line in sorted(ordered, key=lambda item: item[0])]


def _wrap(lines: Sequence[str]) -> str:
    return "<xml-patch>\n" + "".join(line + "\n" for line in lines) + "</xml-patch>\n"


def _row_filters(row: _Tag, rows: Sequence[_Tag]) -> List[Tuple[str, str]]:
    attrs = row.attributes()
    name = attrs[_DESCRIPTOR_KEY]
    same = [other.attributes() for other in rows
            if other.name == row.name and other.attributes().get(_DESCRIPTOR_KEY) == name]
    filters = [(_DESCRIPTOR_KEY, name)]
    if len(same) == 1:
        return filters
    candidates = list(_ROW_FILTER_PREFERENCE) + sorted(
        key for key in attrs if key not in _ROW_FILTER_PREFERENCE and key != _DESCRIPTOR_KEY)
    for key in candidates:
        value = attrs.get(key)
        if value is not None and sum(1 for other in same if other.get(key) == value) == 1:
            return filters + [(key, value)]
    raise PatchError(f"No attribute tells the {len(same)} rows named {name} apart, so a patch "
                     f"cannot edit just one of them")


def descriptor_patch(base: str, edited: str) -> str:
    """A patch turning the descriptor `base` into `edited`, row by row."""

    base_tags, edited_tags = _tags(base), _tags(edited)
    base_rows = [tag for tag in base_tags if not tag.closing and _DESCRIPTOR_KEY in tag.attributes()]
    edited_rows = [tag for tag in edited_tags
                   if not tag.closing and _DESCRIPTOR_KEY in tag.attributes()]
    if len(base_rows) != len(edited_rows):
        raise PatchError(
            f"The descriptor has {len(edited_rows)} equipment rows where the game's has "
            f"{len(base_rows)}; a patch can change rows but not add or remove them")
    lines: List[str] = []
    for before, after in zip(base_rows, edited_rows):
        identity = (before.name, before.attributes()[_DESCRIPTOR_KEY], before.path)
        if identity != (after.name, after.attributes()[_DESCRIPTOR_KEY], after.path):
            raise PatchError(
                f"The descriptor's rows are in a different order from the game's (at "
                f"{before.attributes()[_DESCRIPTOR_KEY]})")
        if before.attributes() == after.attributes():
            continue
        lines += _attribute_ops(before.name, _row_filters(before, base_rows),
                                before.attributes(), after.attributes())
    return _wrap(lines)


def _socket_filters(name: str, attrs: Mapping[str, str], tags: Sequence[_Tag]) -> List[Tuple[str, str]]:
    """`Name`, plus `Parent` when a bare reference elsewhere (`StackEquipInfo`) shares it."""

    others = [tag.attributes() for tag in tags if not tag.closing and tag.name == _SOCKET_TAG]
    filters = [(_SOCKET_KEY, name)]
    if sum(1 for other in others if other.get(_SOCKET_KEY) == name) == 1:
        return filters
    parent = attrs.get("Parent")
    if parent is not None:
        filters.append(("Parent", parent))
        if sum(1 for other in others
               if other.get(_SOCKET_KEY) == name and other.get("Parent") == parent) == 1:
            return filters
    raise PatchError(f"Socket {name} is defined more than once in this file, so a patch cannot "
                     f"edit just one of them")


def _socket_lists(tags: Sequence[_Tag]) -> List[_Tag]:
    return [tag for tag in tags if not tag.closing and tag.name == _SOCKET_CONTAINER]


def socket_patch(base: str, edited: str) -> str:
    """A patch turning the body socket file `base` into `edited`: inserts, Count, then sets."""

    base_tags, edited_tags = _tags(base), _tags(edited)
    if len(_socket_lists(base_tags)) != 1 or len(_socket_lists(edited_tags)) != 1:
        raise PatchError("A body socket file needs exactly one SocketList")
    before: Dict[str, _Tag] = {}
    after: Dict[str, _Tag] = {}
    for tags, out in ((base_tags, before), (edited_tags, after)):
        for tag in tags:
            if _is_socket_definition(tag):
                name = tag.attributes().get(_SOCKET_KEY, "")
                if not name or name in out:
                    raise PatchError(f"Socket {name or '(unnamed)'} is defined more than once")
                out[name] = tag
    removed = sorted(set(before) - set(after))
    if removed:
        raise PatchError(f"A patch cannot remove sockets ({', '.join(removed)})")

    lines: List[str] = []
    for name, tag in after.items():
        if name not in before:
            raw = edited[tag.start:tag.end]
            lines += [f'\t<insert into="{_SOCKET_CONTAINER}">', f"\t\t{raw}", "\t</insert>"]
    base_count = _socket_lists(base_tags)[0].attributes().get("Count")
    edited_count = _socket_lists(edited_tags)[0].attributes().get("Count")
    if edited_count is not None and edited_count != base_count:
        lines.append(f'\t<set find="{_SOCKET_CONTAINER}" attr="Count" value="{edited_count}"/>')
    for name, tag in before.items():
        old, new = tag.attributes(), after[name].attributes()
        if old != new:
            lines += _attribute_ops(_SOCKET_TAG, _socket_filters(name, old, base_tags), old, new,
                                    last=("Parent",))
    return _wrap(lines)


# ── applying patches ─────────────────────────────────────────────────

_OP = re.compile(
    r"<(set|unset)\b((?:[^<>\"]|\"[^\"]*\")*?)/>"
    r"|<insert\b((?:[^<>\"]|\"[^\"]*\")*?)>(.*?)</insert>",
    re.DOTALL,
)
_OP_ATTRIBUTE = re.compile(r'([\w\-]+)="([^"]*)"')


@dataclass(frozen=True, slots=True)
class PatchOp:
    kind: str
    find: str = ""
    filters: Tuple[Tuple[str, str], ...] = ()
    attr: str = ""
    value: Optional[str] = None
    into: str = ""
    content: str = ""

    def notation(self) -> str:
        if self.kind == "insert":
            return f"insert into {self.into}: {self.content.strip()}"
        where = " ".join(f"{name}={value}" for name, value in self.filters)
        if self.kind == "unset":
            return f"unset {self.find} [{where}] {self.attr}"
        return f"set {self.find} [{where}] {self.attr} = {self.value}"


def parse_patch(patch: str) -> List[PatchOp]:
    body = _blank_comments(patch).strip()
    if not body.startswith("<xml-patch>") or not body.endswith("</xml-patch>"):
        raise PatchError("Not an <xml-patch> document")
    ops: List[PatchOp] = []
    for match in _OP.finditer(body):
        kind, attrs_text, insert_attrs, content = match.groups()
        if kind is None:
            into = dict(_OP_ATTRIBUTE.findall(insert_attrs)).get("into", "")
            ops.append(PatchOp("insert", into=into, content=content))
            continue
        attrs = _OP_ATTRIBUTE.findall(attrs_text)
        given = dict(attrs)
        filters = tuple((name[len("match-"):], value) for name, value in attrs
                        if name.startswith("match-"))
        ops.append(PatchOp(kind, find=given.get("find", ""), filters=filters,
                           attr=given.get("attr", ""), value=given.get("value")))
    return ops


def _closing_tag(tags: Sequence[_Tag], opening: _Tag) -> Optional[_Tag]:
    depth = 0
    started = False
    for tag in tags:
        if tag is opening:
            started = True
            continue
        if not started:
            continue
        if tag.closing:
            if depth == 0:
                return tag
            depth -= 1
        elif not tag.self_closing:
            depth += 1
    return None


def _apply_one(text: str, op: PatchOp) -> str:
    tags = _tags(text)
    if op.kind == "insert":
        containers = [tag for tag in tags if not tag.closing and tag.name == op.into]
        if len(containers) != 1 or containers[0].self_closing:
            raise PatchError(f"insert into {op.into}: {len(containers)} containers found")
        closing = _closing_tag(tags, containers[0])
        if closing is None:
            raise PatchError(f"insert into {op.into}: the container is never closed")
        line_start = text.rfind("\n", 0, closing.start) + 1
        newline = "\r\n" if "\r\n" in text else "\n"
        indent = text[line_start:closing.start]
        if indent.strip():
            line_start, indent = closing.start, ""
        child = op.content.strip()
        return text[:line_start] + indent + "\t" + child + newline + text[line_start:]
    if not op.find or not op.attr:
        raise PatchError(f"{op.kind} needs find and attr")
    hits = [tag for tag in tags if not tag.closing and tag.name == op.find
            and all(tag.attributes().get(name) == value for name, value in op.filters)]
    if len(hits) != 1:
        raise PatchError(f"{op.notation()}: matched {len(hits)} elements, not one")
    tag = hits[0]
    chunk = text[tag.start:tag.end]
    existing = re.search(rf'(\s){re.escape(op.attr)}="[^"]*"', chunk)
    if op.kind == "unset":
        if existing is None:
            raise PatchError(f"{op.notation()}: the element has no such attribute")
        chunk = chunk[:existing.start()] + chunk[existing.end():]
    elif op.value is None:
        raise PatchError(f"{op.notation()}: set without a value")
    elif existing is not None:
        chunk = (chunk[:existing.start()] + existing.group(1)
                 + f'{op.attr}="{op.value}"' + chunk[existing.end():])
    else:
        tail = re.search(r"\s*/?>$", chunk)
        cut = tail.start() if tail else len(chunk)
        chunk = chunk[:cut] + f' {op.attr}="{op.value}"' + chunk[cut:]
    return text[:tag.start] + chunk + text[tag.end:]


def apply_patch(base: str, patch: str) -> str:
    """Apply a patch in order, as DMM does; refuse any op that does not hit exactly one element."""

    text = base
    for op in parse_patch(patch):
        text = _apply_one(text, op)
    return text


def prove(base: str, edited: str, patch: str, kind: str) -> None:
    """Raise unless `patch` applied to `base` gives what `edited` means to the game."""

    applied = apply_patch(base, patch)
    if _canonical(applied, kind) != _canonical(edited, kind):
        raise PatchError("Applying the patch to the game's file does not give the edited file")


def _outside_rows(text: str):
    return tuple(_token(tag) for tag in _tags(text)
                 if tag.closing or _DESCRIPTOR_KEY not in tag.attributes())


def make_patch(game_path: str, base: bytes, edited: bytes) -> bytes:
    """The proven patch for one file, as the bytes DMM reads."""

    kind = patchable(game_path)
    if not kind:
        raise PatchError(f"{game_path} is not a file Placement & Animations writes as a patch")
    before, after = decode_text(base), decode_text(edited)
    if _canonical(before, kind) == _canonical(after, kind):
        raise PatchError(f"{game_path} has no change to write")
    try:
        if kind == "descriptor":
            # Everything but the rows has to be untouched: a patch only ever edits rows.
            if _outside_rows(before) != _outside_rows(after):
                raise PatchError("Something other than equipment rows was changed")
            patch = descriptor_patch(before, after)
        else:
            patch = socket_patch(before, after)
        prove(before, after, patch, kind)
    except PatchError as exc:
        raise PatchError(f"{game_path}: {exc}") from None
    return patch.encode("utf-8")


# ── lowering a package ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Lowered:
    """A payload with its shared XML written as patches."""

    files: Mapping[str, bytes]
    #: Game path of every file now shipped as a patch.
    patched: Tuple[str, ...] = ()

    def path_for(self, game_path: str) -> str:
        return patch_path(game_path) if game_path in self.patched else game_path


def lower_for_dmm(files: Mapping[str, bytes], base_for: Callable[[str], Optional[bytes]]) -> Lowered:
    """Write every descriptor and body socket file the game ships as a proven `.xml.patch`.

    `base_for(path)` returns the game's bytes for a path, or None for a file the game does not
    ship; such a file is new, belongs to this mod alone, and stays whole. Raises `PatchError`
    for a file whose edit a patch cannot express.
    """

    out: Dict[str, bytes] = {}
    patched: List[str] = []
    for path, data in files.items():
        base = base_for(path) if patchable(path) else None
        if base is None or base == data:
            out[path] = data
            continue
        out[patch_path(path)] = make_patch(path, base, data)
        patched.append(path)
    collisions = sorted(set(patch_path(path) for path in patched) & set(files))
    if collisions:
        raise PatchError(f"The mod already ships {collisions[0]}")
    return Lowered(out, tuple(sorted(patched)))
