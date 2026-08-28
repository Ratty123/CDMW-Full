"""The character the effect dialog draws behind the item: the game's own, in its own pose.

The dialog needs a body, and a stick figure of the right height answers "how big is this
effect" but not "where will it be". The game's own answer is on disk: the player rig's
`.pab` gives every bone its bind transform, the body socket file gives every attachment
point, the character descriptor says which one a held part uses, and Placement & Animations'
bare-character assembly supplies the nude body plus its separate face in that same bind space.

Weapon previews have two frames and the dialog has to serve both:

* the **item's** frame, which the effect's offset is measured in, because the effect rides
  on the weapon's prefab and moves with it;
* the **character's** frame, which is the one a reader can look at, because a camera has
  an up and a person standing upright is the only pose that reads.

So the scene is the character's frame moved to put the item's own origin there: the body
is translated by minus the attachment's position and left standing, and the item is turned
by the attachment's rotation. Item-space numbers reach the scene through
:func:`rotate_point` and drags come back through :func:`unrotate_point`.

**The attachment is not the body socket alone.** Placement & Animations composes it as
`inverse(child socket on the item) . body socket world`, and the child socket carries the
item's orientation. The selected template's prefab names its part and socket file; the
matching character descriptor supplies that part's held body and child sockets. Failing
that, the prefab's own attachment pair stands in, then the established right-hand/basic
pair. The frame most weapons of the same kind use remains the last child-frame fallback.

Wearable armour already lives in the matching rig's upright bind frame. It stays there rather
than being recentered onto the weapon hand; Model & Placement's fitted source origin is the
pivot that keeps an applied helmet correction around the head. When the matching archive body
is unavailable, the dialog uses a bind-space stand-in instead of the weapon-hand stand-in.

Everything here is best effort. An install missing any piece gets a truthful stand-in rather
than an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.domain.new_item.placement import BODY_PLACEMENT_FRAME, equipment_placement_frame
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

__all__ = [
    "CHARACTER_SUBMESH_PREFIX",
    "CharacterReference",
    "HeldCharacter",
    "build_character_reference",
    "character_rig_model",
    "character_reference_from_snapshot",
    "TRAIL_SOCKET",
    "hold_the_item",
    "item_child_frame",
    "rotate_point",
    "unrotate_point",
    "rotate_mesh",
]

CHARACTER_SUBMESH_PREFIX = "effect_character_"

#: The fallback playable rig and attachment when the selected template cannot resolve its own.
_RIG_MODEL = "1_phm"
_HAND_SOCKET = "RHand_Socket"
#: The fallback item-side frame. Exact descriptor routes also use Long, Short, lantern and
#: carry-specific child sockets.
_CHILD_SOCKET = "Basic_ChildSocket"
#: The socket the game hangs a weapon's trail effect on. Every one of the 48 shipped weapon
#: socket files carries one, and it sits at the far end of the weapon: 2 to 4 per cent from
#: the tip on an axe or a mace, a little past it on a sword, partway along a chain weapon.
#: Effect sockets are named `FX_...` -- muzzles, chambers and sparks are the others.
TRAIL_SOCKET = "FX_Trail_00_Socket"
_EFFECT_SOCKET_PREFIX = "fx"
#: The rotation that leaves everything where it is.
IDENTITY_ROTATION: Tuple[float, ...] = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
@dataclass(frozen=True, slots=True)
class CharacterReference:
    """The character's body plus the attachment frames and part routes its rig owns.

    Both are item-independent, which is what makes this the expensive half worth keeping:
    the body is a mesh read out of the archives, and the sockets are walks of 434 bones.
    """

    #: the body in the rig's own space, standing on the floor
    body: ParsedMesh
    #: the fallback attachment's world matrix, row-major, sixteen numbers
    body_matrix: Tuple[float, ...]
    socket: str
    rig: str
    sources: Tuple[str, ...]
    body_matrices: Mapping[str, Tuple[float, ...]] = field(default_factory=dict)
    parts: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HeldCharacter:
    """The scene body and the optional turn from item space into that body frame.

    Weapons move the body around the held origin and carry their attachment rotation.
    Wearables keep the matching body's bind frame, where item and scene axes already agree.
    """

    mesh: ParsedMesh
    item_rotation: Optional[Tuple[float, ...]]
    socket: str
    #: the frame on the item that mated with the socket, "" when none was found
    child_socket: str
    #: where that frame came from: "prefab", "convention", "wearable", or "" for none
    held_from: str
    sources: Tuple[str, ...]
    #: `(name, point)` for each `FX_...` socket on the item, in the item's own frame, from
    #: the socket file the item's prefab named. Empty when that file was not found, because
    #: another weapon's trail sits at another weapon's tip.
    effect_sockets: Tuple[Tuple[str, Tuple[float, float, float]], ...] = ()

    @property
    def submesh_count(self) -> int:
        return len(self.mesh.submeshes)

    @property
    def body_name(self) -> str:
        """The body mesh's own file name, for a line that says which character this is."""

        return self.sources[0].rsplit("/", 1)[-1] if self.sources else ""


def _normalize(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/").lower()


def character_rig_model(
    model_folder: str, *, default: str = _RIG_MODEL
) -> str:
    """The player-rig segment in an item model folder, or the established default.

    ``character/model/1_pc/2_phw/armor/13_hel`` and the shorter snapshot form
    ``1_pc/2_phw/armor/13_hel`` both resolve to ``2_phw``.
    """

    parts = tuple(part for part in _normalize(model_folder).split("/") if part)
    for index, part in enumerate(parts[:-1]):
        if part == "1_pc":
            return parts[index + 1]
    return default


def rotate_point(point: Sequence[float], rotation: Sequence[float]) -> Tuple[float, float, float]:
    """A point in the item's frame, in the scene's. `rotation` is 3x3 row-major, and the
    point is a row vector, which is the convention the archives' matrices are in."""

    x, y, z = float(point[0]), float(point[1]), float(point[2])
    return (
        x * rotation[0] + y * rotation[3] + z * rotation[6],
        x * rotation[1] + y * rotation[4] + z * rotation[7],
        x * rotation[2] + y * rotation[5] + z * rotation[8],
    )


def unrotate_point(point: Sequence[float], rotation: Sequence[float]) -> Tuple[float, float, float]:
    """A point in the scene's frame, back in the item's: a rotation inverts by transposing."""

    x, y, z = float(point[0]), float(point[1]), float(point[2])
    return (
        x * rotation[0] + y * rotation[1] + z * rotation[2],
        x * rotation[3] + y * rotation[4] + z * rotation[5],
        x * rotation[6] + y * rotation[7] + z * rotation[8],
    )


def rotate_mesh(mesh: ParsedMesh, rotation: Sequence[float]) -> ParsedMesh:
    """`mesh` turned into the scene's frame, normals with it, bounds recomputed."""

    from dataclasses import replace as _replace

    from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs

    rotation = tuple(float(v) for v in rotation)
    if len(rotation) != 9:
        raise ValueError("a rotation is nine numbers")
    submeshes = []
    for source in mesh.submeshes:
        turned = _replace(
            source,
            vertices=[rotate_point(vertex, rotation) for vertex in source.vertices],
            normals=[rotate_point(normal, rotation) for normal in (source.normals or ())],
        )
        # Preview texture paths and material parameters are runtime attributes on the
        # canonical SubMesh. dataclasses.replace copies declared fields only, so the
        # character-frame turn used to strip the imported weapon's texture bindings.
        copy_extra_submesh_attrs(source, turned)
        submeshes.append(turned)
    every = [vertex for submesh in submeshes for vertex in submesh.vertices]
    low = tuple(min(vertex[axis] for vertex in every) for axis in range(3)) if every else mesh.bbox_min
    high = tuple(max(vertex[axis] for vertex in every) for axis in range(3)) if every else mesh.bbox_max
    return _replace(mesh, submeshes=submeshes, bbox_min=low, bbox_max=high)


def _body_mesh_paths(
    paths: Iterable[str], sizes: Mapping[str, int], *, rig_model: str = _RIG_MODEL
) -> List[str]:
    """Placement & Animations' bare figure: the nude anatomy plus its separate face.

    `sizes` is kept for callers that still pass it; nothing here needs it any more.

    The old path looked for a single ``*_lod_*`` PAC. Kliff has no matching file in the
    indexed character set and fell back to the bar mannequin; Damian's match is a generic
    distance proxy rather than her assembled body. Placement & Animations already owns the
    correct deterministic choice, including the separate head that gives the nude mesh a
    face, so construct its index over this snapshot and ask it for the same answer.
    """

    del sizes
    from tools.placement_studio.armour import (
        FACE_SLOT,
        NUDE_SLOT,
        ArmourIndex,
        ArmourPiece,
        _FACE,
        _NUDE,
    )

    model = _normalize(rig_model).rsplit("/", 1)[-1] or _RIG_MODEL
    pieces = []
    for path in sorted({_normalize(path) for path in paths if path}):
        if "_lod_" in path.rsplit("/", 1)[-1]:
            continue
        match = _NUDE.match(path)
        slot = NUDE_SLOT
        if match is None:
            match = _FACE.match(path)
            slot = FACE_SLOT
        if match is None or match.group(2) != model:
            continue
        pieces.append(ArmourPiece(path=path, slot=slot, model=model))
    return ArmourIndex(pieces).base_body(model)


def build_character_reference(
    entry_paths: Iterable[str],
    read: Callable[[str], bytes],
    *,
    sizes: Optional[Mapping[str, int]] = None,
    socket_name: str = _HAND_SOCKET,
    rig_model: str = _RIG_MODEL,
    max_vertices: int = 60_000,
    stop_event=None,
) -> Optional[CharacterReference]:
    """The player, standing, with `socket_name` at the origin, or None.

    `entry_paths` is every path in the archives and `read` reads one. `sizes` remains for
    compatibility. A rig with no matching nude anatomy keeps its exact sockets and routes
    but uses the bind-space stand-in mesh.
    """

    try:
        from tools.placement_studio.documents import (
            DescriptorDocument,
            SocketDocument,
            is_descriptor_file,
        )
        from tools.placement_studio.resolver import descriptor_model_of
        from tools.placement_studio.skeleton import BoneHierarchy
    except Exception:  # noqa: BLE001 - the studio's reader is optional; no character without it
        return None

    def checked_read(path: str) -> bytes:
        raise_if_cancelled(stop_event, "Operation cancelled.")
        payload = read(path)
        raise_if_cancelled(stop_event, "Operation cancelled.")
        return payload

    raise_if_cancelled(stop_event, "Operation cancelled.")
    paths = [_normalize(path) for path in entry_paths]
    model = _normalize(rig_model).rsplit("/", 1)[-1] or _RIG_MODEL
    rigs = sorted(
        path for path in paths
        if path.endswith(".pab") and f"/model/1_pc/{model}/" in path
    )
    sockets = sorted(
        path for path in paths
        if path.endswith(".pab.sockets.xml") and f"/1_pc/{model}/" in path
    )
    if not rigs or not sockets:
        return None
    rig = rigs[0]
    stem = rig.rsplit("/", 1)[-1]
    socket_file = next((path for path in sockets if path.rsplit("/", 1)[-1].startswith(stem)), sockets[0])

    try:
        hierarchy = BoneHierarchy.from_pab(checked_read(rig), rig)
        document = SocketDocument.load(checked_read(socket_file), socket_file)
        body_matrices = {}
        for body_socket in document.sockets():
            placed = hierarchy.place(body_socket)
            if placed.anchored:
                body_matrices[body_socket.name] = tuple(float(v) for v in placed.world_matrix)
        body_matrix = body_matrices.get(socket_name)
        if body_matrix is None:
            return None
    except RunCancelled:
        raise
    except Exception:  # noqa: BLE001 - a rig that does not read leaves the figure in place
        return None

    parts = {}
    for path in sorted(paths):
        if (
            not is_descriptor_file(path)
            or "/characterdescription/" not in path
            or descriptor_model_of(path) != model
        ):
            continue
        try:
            parts.update(DescriptorDocument.load(checked_read(path), path).part_map())
        except RunCancelled:
            raise
        except Exception:  # noqa: BLE001 - the prefab's own pair remains available
            continue

    from cdmw.modding.mesh_parser import parse_mesh

    submeshes: List[SubMesh] = []
    sources: List[str] = []
    total = 0
    for path in _body_mesh_paths(paths, dict(sizes or {}), rig_model=model):
        try:
            parsed = parse_mesh(checked_read(path), path.rsplit("/", 1)[-1])
        except RunCancelled:
            raise
        except Exception:  # noqa: BLE001 - one piece that does not decode is not the end
            continue
        for submesh in tuple(getattr(parsed, "submeshes", ()) or ()):
            vertices = [tuple(float(value) for value in vertex[:3]) for vertex in submesh.vertices]
            if not vertices:
                continue
            total += len(vertices)
            if total > max_vertices:
                break
            submeshes.append(
                SubMesh(
                    name=f"{CHARACTER_SUBMESH_PREFIX}{len(submeshes)}",
                    material=f"{CHARACTER_SUBMESH_PREFIX}body",
                    vertices=vertices,
                    uvs=list(submesh.uvs or ()) or [(0.0, 0.0)] * len(vertices),
                    normals=list(submesh.normals or ()) or [(0.0, 1.0, 0.0)] * len(vertices),
                    faces=list(submesh.faces or ()),
                    vertex_count=len(vertices),
                    face_count=len(submesh.faces or ()),
                )
            )
        sources.append(path)
        if total > max_vertices:
            break
    if submeshes:
        every = [vertex for submesh in submeshes for vertex in submesh.vertices]
        low = tuple(min(vertex[axis] for vertex in every) for axis in range(3))
        high = tuple(max(vertex[axis] for vertex in every) for axis in range(3))
        mesh = ParsedMesh(
            path=f"{CHARACTER_SUBMESH_PREFIX}reference.pac",
            format="pac",
            submeshes=submeshes,
            bbox_min=low,
            bbox_max=high,
            total_vertices=sum(len(item.vertices) for item in submeshes),
            total_faces=sum(len(item.faces) for item in submeshes),
            has_uvs=True,
            has_bones=False,
        )
    else:
        from cdmw.services.effect_placement_preview import character_reference_mesh

        mesh = character_reference_mesh(bind_space=True)
        sources.append(rig)
    return CharacterReference(
        body=mesh, body_matrix=body_matrix, socket=socket_name, rig=rig, sources=tuple(sources),
        body_matrices=body_matrices, parts=parts,
    )


def _preferred_prefab_paths(prefab_paths: Sequence[str]) -> Tuple[str, ...]:
    """The template's part order, with held parts before sheathed ``_in`` companions."""

    normalized = tuple(_normalize(path) for path in prefab_paths if path)
    return tuple(sorted(normalized, key=lambda path: "_in" in path))


def _part_names_in_prefab(prefab: bytes) -> Tuple[str, ...]:
    """Descriptor part names remain unambiguous ASCII even in older prefab layouts."""

    import re

    return tuple(
        dict.fromkeys(match.decode("ascii") for match in re.findall(rb"CD_[A-Za-z0-9_]+", prefab))
    )


def _item_attachment_route(
    prefab_paths: Sequence[str],
    read: Callable[[str], bytes],
    reference: CharacterReference,
) -> Tuple[str, str, str]:
    """The held body socket, child socket and authority for the selected template."""

    try:
        from cdmw.core.archive_attachment_patches import inspect_prefab_attachment_profile_fields
    except Exception:  # noqa: BLE001 - the established pair remains available
        return reference.socket, _CHILD_SOCKET, "fallback"

    for prefab in _preferred_prefab_paths(prefab_paths):
        try:
            payload = read(prefab)
            profile = {
                item.field_name: item.value
                for item in inspect_prefab_attachment_profile_fields(payload)
            }
        except Exception:  # noqa: BLE001 - another owned part may carry the route
            continue
        if profile:
            part = reference.parts.get(str(profile.get("_partName") or ""))
            body_socket = str(getattr(part, "out_socket", "") or "")
            child_socket = str(getattr(part, "out_child_socket", "") or "")
            if body_socket:
                return body_socket, child_socket or _CHILD_SOCKET, "descriptor"
            body_socket = str(profile.get("_attachedSocketName") or "")
            child_socket = str(profile.get("_pivotSocketName") or "")
            if body_socket:
                return body_socket, child_socket or _CHILD_SOCKET, "prefab"
        for part_name in _part_names_in_prefab(payload):
            part = reference.parts.get(part_name)
            body_socket = str(getattr(part, "out_socket", "") or "")
            child_socket = str(getattr(part, "out_child_socket", "") or "")
            if body_socket:
                return body_socket, child_socket or _CHILD_SOCKET, "descriptor-name"
    return reference.socket, _CHILD_SOCKET, "fallback"


def _reference_at_socket(reference: CharacterReference, socket_name: str) -> CharacterReference:
    """The cached character reference addressed through another known body socket."""

    matrix = reference.body_matrices.get(str(socket_name or ""))
    if matrix is None or socket_name == reference.socket:
        return reference
    from dataclasses import replace

    return replace(reference, body_matrix=matrix, socket=str(socket_name))


def item_child_frame(
    entry_paths: Iterable[str],
    read: Callable[[str], bytes],
    *,
    prefab_paths: Sequence[str] = (),
    model_folder: str = "",
    child_socket: str = _CHILD_SOCKET,
) -> Tuple[Optional[Tuple[float, ...]], str, str, Tuple[Tuple[str, Tuple[float, float, float]], ...]]:
    """The item's mating frame and its effect sockets: (matrix, socket name, where, sockets).

    A weapon prefab names the socket file it uses in `_socketFileName`, and several weapons
    share one file, so the prefab is the only thing that says which applies. When there is
    no prefab to read, the frame most of the weapons of the same kind use stands in: the
    rotation is the same quarter turn on nearly all of them and only the offset along the
    grip differs, so the pose is right and the grip may be a few centimetres out.
    """

    try:
        from tools.placement_studio.documents import SocketDocument
        from tools.placement_studio.skeleton import invert_rigid
    except Exception:  # noqa: BLE001 - without the studio's reader there is no frame to find
        return None, "", "", ()

    paths = [_normalize(path) for path in entry_paths]
    known = set(paths)

    def read_sockets(socket_file: str):
        if socket_file not in known:
            return None
        try:
            return SocketDocument.load(read(socket_file), socket_file)
        except Exception:  # noqa: BLE001 - an unreadable socket file is no frame
            return None

    def frame_in(socket_file: str) -> Optional[Tuple[float, ...]]:
        document = read_sockets(socket_file)
        if document is None:
            return None
        found = next((item for item in document.sockets() if item.name == child_socket), None)
        if found is None:
            return None
        return tuple(float(v) for v in invert_rigid(found.rotation, found.translation))

    # the item's own answer: its prefab names the file. The sheathed prefab describes the
    # item on the character's back, so the held one is preferred.
    for prefab in _preferred_prefab_paths(prefab_paths):
        if prefab not in known:
            continue
        try:
            named = _socket_files_named_in(read(prefab))
        except Exception:  # noqa: BLE001 - an unreadable prefab is not an error here
            continue
        for socket_file in named:
            matrix = frame_in(socket_file)
            if matrix is not None:
                return matrix, child_socket, "prefab", _effect_sockets_in(read_sockets(socket_file))

    # what the weapons of this kind do, by weight of numbers
    kind = _normalize(model_folder).rstrip("/").split("/model/")[-1]
    if kind:
        from collections import Counter

        tally: Counter = Counter()
        for socket_file in sorted(path for path in paths if path.endswith(".sockets.xml") and f"/socketbonedata/{kind}/" in path):
            matrix = frame_in(socket_file)
            if matrix is not None:
                tally[matrix] += 1
        if tally:
            # no effect sockets with a borrowed frame: another weapon's trail is at another
            # weapon's tip, and a preset that puts the effect there would be a guess
            return tally.most_common(1)[0][0], child_socket, "convention", ()
    return None, "", "", ()


def _effect_sockets_in(document) -> Tuple[Tuple[str, Tuple[float, float, float]], ...]:
    """The `FX_...` sockets on an item, as points in its own frame.

    A child socket is an item-local offset -- the studio's placement never walks a bone for
    one -- so the translation is the point, and it is what the effect dialog's offset boxes
    are measured in.
    """

    if document is None:
        return ()
    found = []
    for socket in document.sockets():
        if not socket.name.lower().startswith(_EFFECT_SOCKET_PREFIX):
            continue
        point = socket.translation
        found.append((socket.name, (float(point.x), float(point.y), float(point.z))))
    return tuple(found)


def _socket_files_named_in(prefab: bytes) -> List[str]:
    """Every `.sockets.xml` a prefab names, in the order it names them.

    The prefab is a binary object graph and this only wants one string out of it, so it is
    read as strings rather than parsed: a path is printable and ends in a known suffix.
    """

    import re

    found: List[str] = []
    for match in re.findall(rb"[\x20-\x7e]{8,}", prefab):
        text = match.decode("ascii", "replace")
        for candidate in re.findall(r"[A-Za-z0-9_/\\.\-]+\.sockets\.xml", text):
            normalized = _normalize(candidate)
            if normalized not in found:
                found.append(normalized)
    return found


def hold_the_item(
    reference: CharacterReference,
    child_frame: Optional[Sequence[float]] = None,
    *,
    child_socket: str = "",
    held_from: str = "",
    effect_sockets: Sequence[Tuple[str, Sequence[float]]] = (),
    max_vertices: int = 60_000,
) -> HeldCharacter:
    """Stand `reference`'s body around an item whose origin is the origin.

    The attachment is `child_frame . body_matrix`, the studio's own composition. The body
    gives up that matrix's translation and keeps standing; the item, which the caller turns
    with :func:`rotate_mesh`, takes its rotation.
    """

    from dataclasses import replace as _replace

    from tools.placement_studio.skeleton import multiply

    attachment = tuple(float(v) for v in reference.body_matrix)
    if child_frame is not None:
        attachment = tuple(float(v) for v in multiply(tuple(float(v) for v in child_frame), attachment))
    rotation = attachment[0:3] + attachment[4:7] + attachment[8:11]
    origin = attachment[12:15]

    submeshes = [
        _replace(
            submesh,
            vertices=[tuple(vertex[axis] - origin[axis] for axis in range(3)) for vertex in submesh.vertices],
        )
        for submesh in reference.body.submeshes
    ]
    every = [vertex for submesh in submeshes for vertex in submesh.vertices]
    mesh = _replace(
        reference.body,
        submeshes=submeshes,
        bbox_min=tuple(min(vertex[axis] for vertex in every) for axis in range(3)) if every else reference.body.bbox_min,
        bbox_max=tuple(max(vertex[axis] for vertex in every) for axis in range(3)) if every else reference.body.bbox_max,
    )
    return HeldCharacter(
        mesh=mesh, item_rotation=tuple(rotation), socket=reference.socket,
        child_socket=child_socket if child_frame is not None else "",
        held_from=held_from if child_frame is not None else "",
        sources=reference.sources,
        effect_sockets=tuple(
            (str(name), (float(point[0]), float(point[1]), float(point[2]))) for name, point in effect_sockets
        ),
    )


def character_reference_from_snapshot(
    snapshot, *, model_folder: str = "", rig_model: str = "", stop_event=None
) -> Tuple[Optional[CharacterReference], str]:
    """The character out of a new-item snapshot, and one line saying what came of it.

    The snapshot already holds every archive entry and reads any of them, which is all
    :func:`build_character_reference` wants; this is the seam that keeps the studio's
    controller out of the archives. ``rig_model`` is an explicit preview-only override;
    otherwise the selected template's model folder remains authoritative.
    """

    try:
        selected_rig = (
            _normalize(rig_model).rsplit("/", 1)[-1]
            if rig_model
            else character_rig_model(model_folder)
        )
        reference = build_character_reference(
            snapshot.entries.keys(),
            snapshot.payload,
            sizes={path: entry.orig_size for path, entry in snapshot.entries.items()},
            rig_model=selected_rig,
            stop_event=stop_event,
        )
    except RunCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - the stand-in figure is drawn instead
        return None, f"The character for the placement viewport could not be read: {exc}"
    if reference is None:
        return None, "The archives carry no character for the placement viewport; a stand-in figure is drawn."
    return reference, ""


def held_character_from_snapshot(
    snapshot,
    reference: Optional[CharacterReference],
    *,
    prefab_paths: Sequence[str] = (),
    model_folder: str = "",
    template_key: Optional[int] = None,
    stop_event=None,
) -> Tuple[Optional["HeldCharacter"], str]:
    """`reference` holding this item, and one line saying how it is held.

    Split from :func:`character_reference_from_snapshot` because the halves cost different
    things: the body is a mesh and a 434-bone walk, read once, while the frame the item
    mates by is one prefab and one small XML, read per item.
    """

    raise_if_cancelled(stop_event, "Operation cancelled.")

    def checked_read(path: str) -> bytes:
        raise_if_cancelled(stop_event, "Operation cancelled.")
        payload = snapshot.payload(path)
        raise_if_cancelled(stop_event, "Operation cancelled.")
        return payload

    equip_type_name = ""
    if template_key is not None:
        try:
            equip_type_name = snapshot.equip_type_name(snapshot.row(int(template_key)))
        except Exception:  # noqa: BLE001 - old snapshot-shaped callers keep the folder fallback
            pass
    if equipment_placement_frame(equip_type_name, model_folder) == BODY_PLACEMENT_FRAME:
        if reference is None:
            from cdmw.services.effect_placement_preview import character_reference_mesh

            mesh = character_reference_mesh(bind_space=True)
            sources: Tuple[str, ...] = ()
        else:
            mesh = reference.body
            sources = reference.sources
        wearable = HeldCharacter(
            mesh=mesh,
            item_rotation=None,
            socket="",
            child_socket="",
            held_from="wearable",
            sources=sources,
        )
        return wearable, ""
    if reference is None:
        return None, ""
    try:
        body_socket, requested_child_socket, _route_from = _item_attachment_route(
            prefab_paths, checked_read, reference
        )
        routed_reference = _reference_at_socket(reference, body_socket)
        if routed_reference.socket != body_socket:
            requested_child_socket = _CHILD_SOCKET
        child, child_socket, held_from, sockets = item_child_frame(
            snapshot.entries.keys(), checked_read,
            prefab_paths=prefab_paths, model_folder=model_folder, child_socket=requested_child_socket,
        )
        held = hold_the_item(
            routed_reference, child, child_socket=child_socket, held_from=held_from, effect_sockets=sockets
        )
    except RunCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - the stand-in figure is drawn instead
        return None, f"The character for the placement viewport could not be read: {exc}"
    body = held.body_name
    if held.held_from == "prefab":
        return held, f"Placement viewport: {body} holds the item at {held.socket}, mated by the item's own {held.child_socket}."
    if held.held_from == "convention":
        return held, (
            f"Placement viewport: {body} holds the item at {held.socket}, mated by the {held.child_socket} that most "
            "weapons of this kind use, because the item's own prefab named no socket file."
        )
    return held, (
        f"Placement viewport: {body} holds the item at {held.socket} with no mating frame, so the angle it is held "
        "at may be a quarter turn off."
    )
