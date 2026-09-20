"""Lossless XML edits for existing PBD owners and uniquely named profile clones.

Only selected scalar text, one existing assignment owner, and new catalogue
entries change. Offsets come from an XML parser, never matches inside comments.
The original encoding, BOM, comments and unrelated bytes survive unchanged.
"""

from dataclasses import dataclass, field
import re
from xml.parsers import expat
from xml.sax.saxutils import escape
from cdmw.domain.mesh.physics_profile import validate_profile_values


_MAX_BYTES = 4 * 1024 * 1024
_TAG = re.compile(rb"<(?:[^>'\"]|\"[^\"]*\"|'[^']*')*>")
_ATTRIBUTE = re.compile(rb"([^\s=/>]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
_PROFILE_ATTRIBUTE = "_pbdSimulationMaterialName"


@dataclass(eq=False)
class _Node:
    tag: str
    attributes: dict
    start: int
    open_end: int
    close_start: int = 0
    end: int = 0
    parent: object = None
    children: list = field(default_factory=list)


class ProfileXml:
    def __init__(self, data: bytes):
        if not 0 < len(data) <= _MAX_BYTES:
            raise ValueError("Physics XML cannot be edited without preserving its structure.")
        self.bom = next((bom for bom in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf") if data.startswith(bom)), b"")
        self.encoding = ("utf-16-le" if self.bom == b"\xff\xfe" or data.startswith(b"<\x00") else
                         "utf-16-be" if self.bom == b"\xfe\xff" or data.startswith(b"\x00<") else "utf-8")
        try:
            self.text = data[len(self.bom):].decode(self.encoding).encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Physics XML cannot be edited without preserving its structure.") from exc
        # The parser sees UTF-8 and a synthetic root for PAC XML sibling roots.
        # Replace a leading declaration with equal-length whitespace to retain
        # the byte offsets into the unmodified UTF-8 working representation.
        parsed = re.sub(rb"\A<\?xml\s[^?]*\?>", lambda match: b" " * len(match[0]), self.text, count=1)
        prefix = b"<CdmwDocument>"
        parser = expat.ParserCreate("utf-8")
        self.nodes, stack = [], []

        def forbidden(*_):
            raise ValueError("Physics XML cannot be edited without preserving its structure.")

        def start(tag, attributes):
            offset = parser.CurrentByteIndex - len(prefix)
            if offset < 0:
                return
            if len(stack) > 64 or len(self.nodes) >= 32768:
                forbidden()
            opening = _TAG.match(self.text, offset)
            if opening is None:
                forbidden()
            node = _Node(tag, attributes, offset, opening.end(), parent=stack[-1] if stack else None)
            if node.parent is not None:
                node.parent.children.append(node)
            self.nodes.append(node)
            stack.append(node)

        def end(_tag):
            if not stack:
                return
            node = stack.pop()
            if self.text[node.start:node.open_end].rstrip().endswith(b"/>"):
                node.close_start = node.end = node.open_end
            else:
                node.close_start = parser.CurrentByteIndex - len(prefix)
                closing = _TAG.match(self.text, node.close_start)
                if closing is None:
                    forbidden()
                node.end = closing.end()

        parser.StartElementHandler, parser.EndElementHandler = start, end
        parser.StartDoctypeDeclHandler = parser.EntityDeclHandler = forbidden
        try:
            parser.Parse(prefix + parsed + b"</CdmwDocument>", True)
        except expat.ExpatError as exc:
            raise ValueError("Physics XML cannot be edited without preserving its structure.") from exc

    def apply(self, edits):
        previous_end = 0
        for start, end, _ in sorted(edits):
            if not 0 <= start <= end <= len(self.text) or start < previous_end:
                raise ValueError("Physics XML cannot be edited without preserving its structure.")
            previous_end = end
        result = self.text
        for start, end, value in sorted(edits, reverse=True):
            result = result[:start] + value + result[end:]
        result = self.bom + result.decode("utf-8").encode(self.encoding)
        ProfileXml(result)  # Refuse malformed output before it enters any package.
        return result

    def attribute_edit(self, node, name, value):
        quoted = escape(value, {'"': '&quot;', "'": '&apos;'}).encode("utf-8")
        for match in _ATTRIBUTE.finditer(self.text, node.start, node.open_end):
            if match[1].decode("utf-8") == name:
                return match.start(3), match.end(3), quoted
        offset = node.open_end - (2 if self.text[node.open_end-2:node.open_end] == b"/>" else 1)
        return offset, offset, b" " + name.encode() + b'="' + quoted + b'"'

    def variant(self, node):
        while node is not None:
            if node.tag == "ModelProperty":
                return node.attributes.get("Index", "")
            node = node.parent
        return ""

    def owner(self, node, *, required=True):
        fallback = None
        while node is not None:
            if _PROFILE_ATTRIBUTE in node.attributes:
                return node
            if node.tag == "SkinnedMeshProperty" and fallback is None:
                fallback = node
            node = node.parent
        if fallback is not None:
            return fallback
        if required:
            raise ValueError("Physics profile assignment is ambiguous or does not match the PAC.")
        return None

    def assignment(self, variant, names):
        keys = {name.casefold() for name in names}
        rows = [node for node in self.nodes if self.variant(node) == variant
                and node.attributes.get("_subMeshName", "").casefold() in keys]
        if (len(keys) != len(names) or len(rows) != len(names)
                or {node.attributes["_subMeshName"].casefold() for node in rows} != keys):
            raise ValueError("Physics profile assignment is ambiguous or does not match the PAC.")
        owners = {self.owner(node) for node in rows}
        for owner in owners:
            if self.variant(owner) != variant:
                raise ValueError("Physics profile assignment is ambiguous or does not match the PAC.")
            affected = {node.attributes["_subMeshName"].casefold() for node in self.nodes
                        if "_subMeshName" in node.attributes and self.variant(node) == variant
                        and self.owner(node, required=False) is owner}
            if not affected <= keys:
                raise ValueError("Select every part sharing this physics profile assignment.")
        return owners


def edit_profile_values(data, values):
    validate_profile_values(values)
    document = ProfileXml(data)
    roots = [node for node in document.nodes if node.tag == "SimulationParameters" and node.parent is None]
    if len(roots) != 1 or roots[0].close_start == roots[0].open_end:
        raise ValueError("Physics XML cannot be edited without preserving its structure.")
    root = roots[0]
    edits, additions = [], []
    for key, value in sorted(values):
        scalar = format(value, ".9g").encode("ascii")
        matches = [node for node in root.children if node.tag == key]
        # SimulationMode resets guide rotation when encountered by the CPU
        # reader. A requested rotation override must come after that reset.
        if key == "UseRotationCorrection" and matches and any(
                node.tag == "SimulationMode" and node.start > matches[-1].start for node in root.children):
            additions.append(b"\n\t<" + key.encode() + b">" + scalar + b"</" + key.encode() + b">")
            continue
        if matches:
            node = matches[-1]  # The CPU reader processes duplicate scalars in order.
            content = document.text[node.open_end:node.close_start]
            if node.children or b"<" in content or b"&" in content or not content.strip():
                raise ValueError("Physics XML cannot be edited without preserving its structure.")
            start = node.open_end + len(content) - len(content.lstrip())
            end = node.close_start - len(content) + len(content.rstrip())
            edits.append((start, end, scalar))
        else:
            # Alternate Name/Value or attribute encodings are not silently
            # shadowed by a new field whose read order has not been established.
            if any(key in node.attributes or node.attributes.get("Name") == key for node in document.nodes):
                raise ValueError("Physics XML cannot be edited without preserving its structure.")
            additions.append(b"\n\t<" + key.encode() + b">" + scalar + b"</" + key.encode() + b">")
    if additions:
        edits.append((root.close_start, root.close_start, b"".join(additions)))
    return document.apply(edits)


def clone_catalogue_profiles(data, clones):
    """clones: (original symbolic name, original filename, new name, new filename)."""
    document = ProfileXml(data)
    entries = [node for node in document.nodes if "Name" in node.attributes and "Filename" in node.attributes]
    names = {node.attributes["Name"].casefold() for node in entries}
    paths = {node.attributes["Filename"].replace("\\", "/").casefold() for node in entries}
    inserts = {}
    for original, filename, name, new_filename in clones:
        matches = [node for node in entries if node.attributes["Name"].casefold() == original.casefold()
                   and node.attributes["Filename"].replace("\\", "/").casefold() == filename.casefold()]
        if len(matches) != 1:
            raise ValueError("Physics profile edit source is missing or has changed.")
        if name.casefold() in names or new_filename.casefold() in paths:
            raise ValueError("Generated physics profile name or path already exists.")
        names.add(name.casefold())
        paths.add(new_filename.casefold())
        node = matches[0]
        chunk = document.text[node.start:node.end]
        edits = [document.attribute_edit(node, "Name", name), document.attribute_edit(node, "Filename", new_filename)]
        for start, end, value in sorted(edits, reverse=True):
            chunk = chunk[:start-node.start] + value + chunk[end-node.start:]
        newline = b"\r\n" if b"\r\n" in document.text else b"\n"
        inserts.setdefault(node.end, []).append(newline + b"\t" + chunk)
    return document.apply([(offset, offset, b"".join(chunks)) for offset, chunks in inserts.items()])
