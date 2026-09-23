"""Lossless edits to the shipped equipment shrink and postfix rule fragments.

Only selected nodes and insertion sites change. Unknown XML, comments, whitespace
and UTF-8 BOMs remain byte-identical. These rules are experimental in-game.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from xml.parsers import expat

from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice

SHRINK_PATH = "character/descriptors/partshrinkdesc.xml"
POSTFIX_PATH = "character/descriptors/conditionalpartprefab/conditionalpartprefab_postfix.xml"
_OPEN = re.compile(rb'<[^\s/>]+(?:"[^"]*"|\'[^\']*\'|[^\'">])*>')
_IDENTIFIER = re.compile(r"[A-Za-z0-9_]+\Z")


@dataclass
class _Node:
    name: str
    attrs: dict[str, str]
    start: int
    open_end: int
    close_start: int = 0
    end: int = 0
    text: str = ""
    children: list[_Node] = field(default_factory=list)


def _nodes(data: bytes) -> list[_Node]:
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Equipment visibility descriptor exceeds 4 MiB.")
    try:
        data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("Equipment visibility currently requires a UTF-8 descriptor.") from exc
    if b"\0" in data or re.search(rb'<!\s*(?:DOCTYPE|ENTITY)\b', data, re.I):
        raise ValueError("Unsupported equipment visibility XML encoding or declaration.")
    offset = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    declaration = re.match(rb'\s*<\?xml\s.*?\?>', data[offset:], re.S)
    if declaration:
        offset += declaration.end()
    prefix = b"<CDMWVisibilityRoot>"
    parser = expat.ParserCreate("UTF-8")
    roots, stack = [], []
    count = 0

    def start(name, attrs):
        nonlocal count
        if not stack:
            stack.append(None)
            return
        count += 1
        if count > 32768 or len(stack) > 64:
            raise ValueError("Equipment visibility XML exceeds the structural limit.")
        position = parser.CurrentByteIndex - len(prefix) + offset
        token = _OPEN.match(data, position)
        if token is None:
            raise ValueError("Cannot locate an equipment visibility XML element.")
        node = _Node(name, attrs, position, token.end())
        (roots if stack[-1] is None else stack[-1].children).append(node)
        stack.append(node)

    def end(_name):
        node = stack.pop()
        if node is None:
            return
        position = parser.CurrentByteIndex - len(prefix) + offset
        if data[node.open_end - 2:node.open_end] == b"/>":
            node.close_start = node.end = node.open_end
        else:
            node.close_start = position
            node.end = data.index(b">", position) + 1

    def text(value):
        if stack and stack[-1] is not None:
            stack[-1].text += value

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.CharacterDataHandler = text
    try:
        parser.Parse(prefix + data[offset:] + b"</CDMWVisibilityRoot>", True)
    except expat.ExpatError as exc:
        raise ValueError(f"Malformed equipment visibility XML: {exc}") from exc
    return roots


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _patch(data, edits):
    chunks, cursor = [], 0
    for start, end, replacement in sorted(edits, key=lambda e: (e[0], e[1])):
        if not cursor <= start <= end <= len(data):
            raise ValueError("Overlapping equipment visibility XML edits.")
        chunks.extend((data[cursor:start], replacement))
        cursor = end
    chunks.append(data[cursor:])
    return b"".join(chunks)


def _attribute(fragment, name, value):
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid generated visibility identifier: {value!r}")
    opening = _OPEN.match(fragment)
    pattern = re.compile(rb'(\s' + name.encode() + rb'\s*=\s*)(["\'])(.*?)\2', re.S)
    match = pattern.search(fragment, 0, opening.end())
    if match is None:
        raise ValueError(f"Equipment visibility XML is missing {name}.")
    return fragment[:match.start(3)] + value.encode() + fragment[match.end(3):]


def _append(node, content):
    if node.close_start == node.open_end and node.end == node.open_end:
        return node.open_end - 2, node.open_end, b">" + content + b"</" + node.name.encode() + b">"
    return node.close_start, node.close_start, content


def _indent(data, node):
    start = data.rfind(b"\n", 0, node.start) + 1
    before = data[start:node.start]
    return before if not before.strip() else b"\t\t"


def _rules(roots):
    containers = [n for n in roots if n.name == "Shrink"]
    if len(containers) != 1:
        raise ValueError("Expected one Shrink section in the equipment descriptor.")
    rules = {}
    for node in containers[0].children:
        if node.name != "ShrinkTag":
            continue
        name = node.attrs.get("Name", "")
        if not name or name in rules:
            raise ValueError(f"Missing or duplicate equipment shrink rule: {name!r}")
        rules[name] = node
    return containers[0], rules


def shrink_rule_names(data: bytes) -> frozenset[str]:
    return frozenset(_rules(_nodes(data))[1])


@dataclass(frozen=True)
class VisibilityProfile:
    source_tag: str
    tag: str
    choice: BodyVisibilityChoice


def clone_shrink_rules(data: bytes, profiles: tuple[VisibilityProfile, ...]) -> bytes:
    if not profiles:
        return data
    roots = _nodes(data)
    container, rules = _rules(roots)
    profiles = tuple(dict.fromkeys(profiles))
    if len({p.tag for p in profiles}) != len(profiles):
        raise ValueError("Conflicting generated equipment visibility profiles.")
    aliases = {}
    for profile in profiles:
        profile.choice.validate()
        if profile.source_tag not in rules or profile.tag in rules:
            raise ValueError(f"Missing source or occupied visibility profile: {profile.source_tag} -> {profile.tag}")
        aliases.setdefault(profile.source_tag, []).append(profile.tag)
    # These optional sections are recognized by the executable, but their
    # inheritance semantics have not been proven. Refuse to silently discard them.
    if any(n.name in {"UnderLayerNoCut", "UsePostCutbox", "UsePumpUpVertex"} for n in roots):
        raise ValueError("This shrink descriptor uses cut/pump overrides whose visibility inheritance is not supported yet.")
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    edits, clones = [], []

    def receiver_edits(node, choice=None):
        result = []
        for receiver in _walk(node.children):
            if receiver.name != "Shrink":
                continue
            value = receiver.text.strip()
            if receiver.children or not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"Unsupported receiver in shrink rule {node.attrs.get('Name')}: {value!r}")
            if choice is not None and value in choice.receiver_tags:
                result.append((receiver.start, receiver.end, b""))
            else:
                added = b"".join(newline + _indent(data, receiver) + b"<Shrink>" + name.encode() + b"</Shrink>"
                                 for name in aliases.get(value, ()))
                if added:
                    result.append((receiver.end, receiver.end, added))
        return result

    for node in rules.values():
        edits.extend(receiver_edits(node))
    for profile in profiles:
        node = rules[profile.source_tag]
        fragment = _patch(data[node.start:node.end],
                          [(a-node.start, b-node.start, value) for a,b,value in receiver_edits(node, profile.choice)])
        clones.append(newline + b"\t" + _attribute(fragment, "Name", profile.tag) + newline)
    edits.append(_append(container, b"".join(clones)))

    for setting in (n for n in roots if n.name == "GlobalSetting"):
        for section in setting.children:
            added = []
            if section.name == "ShrinkDepthBias":
                for profile in profiles:
                    sources = [n for n in section.children if n.name == profile.source_tag]
                    if len(sources) > 1:
                        raise ValueError(f"Duplicate depth setting for {profile.source_tag}.")
                    for node in sources:
                        fragment = data[node.start:node.end]
                        old, new = node.name.encode(), profile.tag.encode()
                        fragment = fragment.replace(b"<"+old, b"<"+new, 1)
                        if fragment.endswith(b"</"+old+b">"):
                            fragment = fragment[:-(len(old)+3)] + b"</"+new+b">"
                        added.append(newline + b"\t\t" + fragment)
            elif section.name == "ConditionalShrinkDepthBias":
                for profile in profiles:
                    added.extend(newline + b"\t\t" + _attribute(data[n.start:n.end], "ShrinkTag", profile.tag)
                                 for n in section.children if n.name == "Caster" and n.attrs.get("ShrinkTag") == profile.source_tag)
            if added:
                edits.append(_append(section, b"".join(added) + newline))
    result = _patch(data, edits)
    _nodes(result)
    return result


def matching_postfixes(data: bytes, stem: str) -> tuple[str, ...]:
    return tuple(node.attrs['SourcePartPrefabPostfix'] for node in _nodes(data)
                 if node.name == "PostfixCondition" and node.attrs.get('SourcePartPrefabPostfix')
                 and stem.casefold().endswith(node.attrs['SourcePartPrefabPostfix'].casefold()))


def clone_postfix_rules(data: bytes, requests: tuple[tuple[str, str, BodyVisibilityChoice], ...]) -> bytes:
    """Copy every matching condition to an isolated output stem, filtering Hide targets."""
    roots = _nodes(data)
    added = []
    for source_stem, output_stem, choice in requests:
        if matching_postfixes(data, output_stem):
            raise ValueError(f"Output prefab {output_stem} still matches an existing postfix rule.")
        for node in roots:
            suffix = node.attrs.get("SourcePartPrefabPostfix", "")
            if node.name != "PostfixCondition" or not suffix or not source_stem.casefold().endswith(suffix.casefold()):
                continue
            removals = [(n.start-node.start, n.end-node.start, b"") for n in node.children
                        if node.attrs.get("Type") == "Hide" and n.name == "TargetPart"
                        and n.attrs.get("PartName") in choice.hidden_parts]
            fragment = _patch(data[node.start:node.end], removals)
            added.append(_attribute(fragment, "SourcePartPrefabPostfix", output_stem))
    if not added:
        return data
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    result = data + newline + newline.join(added) + newline
    _nodes(result)
    return result
