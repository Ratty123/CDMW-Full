"""Inspector text for a socket and for an equipment row.

Pure formatting, split out of `window.py` so it stays under the repository's 1,000-line owner
ceiling — and so the text can be exercised without constructing a Qt window.
"""

from __future__ import annotations

from typing import Dict, Optional

from .model import PlacementBinding, Vec3


def _body_socket_using(session, child_socket: str) -> str:
    """The body socket a child socket is paired with, so a world point can be composed."""

    for binding in session.bindings():
        if binding.part.in_child_socket == child_socket:
            return binding.part.in_socket
        if binding.part.out_child_socket == child_socket:
            return binding.part.out_socket
    return ""


def describe_socket(session, socket_name: str) -> str:
    """Everything known about one socket, including what moves if it changes."""

    if session is None:
        return ""
    placed = session.placed(socket_name)
    usage = session.usage(socket_name)
    lines = [f"SOCKET  {socket_name}", ""]

    if placed is None:
        weapon = session.weapon
        child = weapon.sockets.get(socket_name) if weapon is not None else None
        if child is None:
            lines.append("Not a body socket for this model, and not defined by the selected item.")
            return "\n".join(lines)

        # A child socket is editable, so its values must be visible. Showing only "no world
        # position" left the one panel that explains an angle saying nothing about the angle.
        roll, pitch, yaw = child.rotation.to_euler_degrees()
        normalized = "" if child.rotation.is_normalized() else "   [NOT NORMALIZED]"
        lines += [
            f"  kind          item-local child socket",
            f"  defined in    {weapon.weapon_id}",
            f"  rotation      {child.rotation.format()}{normalized}",
            f"  translation   {child.translation.format()}",
            f"  euler (deg)   roll {roll:.2f}  pitch {pitch:.2f}  yaw {yaw:.2f}"
            + ("   [degenerate: pitch is at 90, euler cannot round-trip here]"
               if child.rotation.near_gimbal_lock else ""),
            f"  source        {child.source_file}",
            "",
            "A child socket has no standalone world position: it is an offset applied after",
            "the item attaches to a body socket. Its rotation is what orients the item.",
            "",
        ]
        composed = session.attachment_point(_body_socket_using(session, socket_name), socket_name)
        if composed is not None:
            lines += [
                "COMPOSED WITH ITS BODY SOCKET",
                f"  world         {composed.x:.6f} {composed.y:.6f} {composed.z:.6f}",
                "",
            ]
        usage = session.usage(socket_name)
        lines.append(f"WHAT MOVES IF THIS CHANGES  ({usage.total} part(s))")
        if usage.empty:
            lines.append("  nothing routes through this socket")
        for name in sorted(set(usage.stowed) | set(usage.held) | set(usage.child_offset)):
            lines.append(f"    {name}")
        return "\n".join(lines)

    socket = placed.socket
    world = placed.world_position
    normalized = "" if socket.rotation.is_normalized() else "   [NOT NORMALIZED]"
    lines += [
        f"  parent bone   {socket.parent_bone or '(world space)'}",
        f"  rotation      {socket.rotation.format()}{normalized}",
        f"  translation   {socket.translation.format()}",
        f"  world         {world.x:.6f} {world.y:.6f} {world.z:.6f}",
        f"  offset        {placed.offset_from_bone:.6f} from bone origin",
        f"  source        {socket.source_file}",
        "",
    ]

    roll, pitch, yaw = socket.rotation.to_euler_degrees()
    euler_line = f"  euler (deg)   roll {roll:.2f}  pitch {pitch:.2f}  yaw {yaw:.2f}"
    if socket.rotation.near_gimbal_lock:
        # Not a corner case: several weapon sockets sit exactly at pitch 90.
        euler_line += "   [degenerate: pitch is at 90, euler cannot round-trip here]"
    lines += [euler_line, ""]

    chain = session.bone_chain(socket_name)
    if chain:
        lines.append(f"BONE CHAIN ({len(chain)})")
        lines.append("  " + " -> ".join(chain[:8]) + (" -> ..." if len(chain) > 8 else ""))
        lines.append("")

    # The question the manual workflow keeps asking, answered before any edit is made.
    lines.append(f"WHAT MOVES IF THIS CHANGES  ({usage.total} part(s))")
    if usage.empty:
        lines.append("  nothing routes through this socket")
    for label, names in (
        ("stowed", usage.stowed),
        ("held", usage.held),
        ("child offset", usage.child_offset),
    ):
        if names:
            lines.append(f"  {label}:")
            lines.extend(f"    {name}" for name in sorted(names))

    siblings = session.sockets_on_bone(socket.parent_bone) if socket.parent_bone else []
    if len(siblings) > 1:
        lines += ["", f"OTHER SOCKETS ON {socket.parent_bone}"]
        lines.append("  " + ", ".join(n for n in siblings if n != socket_name))
    return "\n".join(lines)


def describe_part(
    session,
    binding: PlacementBinding,
    points: Dict[str, Optional[Vec3]],
) -> str:
    """Routing and resolved attachment points for one equipment row."""

    part = binding.part
    lines = [
        f"PART  {part.part_name}",
        "",
        f"  category      {part.category}",
        f"  weapon type   {part.weapon_type or '(n/a)'}",
        f"  side          {part.side or '(n/a)'}",
        f"  case part     {part.weapon_case_part or '(none - unsheathed type)'}",
        f"  source        {part.source_file}",
        "",
        "ROUTING",
        f"  stowed  body={part.in_socket or '-'}  child={part.in_child_socket or '-'}",
        f"  held    body={part.out_socket or '-'}  child={part.out_child_socket or '-'}",
    ]
    if part.bag_socket or part.vehicle_bag_socket:
        lines.append(
            f"  bag     {part.bag_socket or '-'}   vehicle={part.vehicle_bag_socket or '-'}"
        )
    lines.append("")

    lines.append("ATTACHMENT POINTS (body socket composed with child offset)")
    for role in ("stowed", "held"):
        point = points.get(role)
        lines.append(
            f"  {role:<7} {point.x:.6f} {point.y:.6f} {point.z:.6f}"
            if point
            else f"  {role:<7} unresolved"
        )

    gaps = binding.unresolved()
    if gaps:
        lines += ["", f"UNRESOLVED  {', '.join(gaps)}"]
        if session is not None and session.weapon is None:
            lines.append("  Select a weapon: child sockets come from the item's own file.")

    if binding.case_binding is not None:
        case = binding.case_binding
        lines += [
            "",
            f"CASE ROW  {case.part_name}",
            f"  stowed  body={case.part.in_socket or '-'}  child={case.part.in_child_socket or '-'}",
            "  A sheath normally shares the weapon's body socket so the two move together.",
        ]
    return "\n".join(lines)
