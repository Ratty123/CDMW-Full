"""Host authority for the resident .NET Colour tool page.

The .NET editor applies a colour edit locally so the viewport responds while
the pointer is still down, then publishes one latest-wins
``part_material_edit_request``. Python owns the stored values: it normalizes
the request, hands it to the active Builder, and the acknowledged material
parameter update carries the exact result back.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def normalized_part_material_edit(payload: Mapping[str, object]) -> dict[str, object] | None:
    """Return a clean edit, or None when the request carries nothing to apply.

    Everything is clamped here rather than trusted from the child process, so
    a malformed or hostile packet cannot write an out-of-range value into the
    adjustment that Build Mod later bakes.
    """
    indices = _submesh_indices(payload.get("source_submesh_indices"))
    if not indices:
        return None
    edit: dict[str, object] = {"source_submesh_indices": indices}
    if bool(payload.get("reset")):
        edit["reset"] = True
        return edit
    for key in ("tint_rgb", "colourise_rgb", "emissive_rgb"):
        colour = _rgb(payload.get(key))
        if colour is not None:
            edit[key] = colour
    strength = _clamped_float(payload.get("colourise_strength"), 0.0, 1.0)
    if strength is not None:
        edit["colourise_strength"] = strength
    emissive_strength = _clamped_float(payload.get("emissive_strength"), 0.0, 20.0)
    if emissive_strength is not None:
        edit["emissive_strength"] = emissive_strength
    if isinstance(payload.get("emissive"), bool):
        edit["emissive"] = bool(payload["emissive"])
    if len(edit) <= 1:
        return None
    return edit


def _submesh_indices(raw: object) -> tuple[int, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    indices: list[int] = []
    for value in raw:
        if isinstance(value, bool):
            continue
        try:
            index = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0 and index not in indices:
            indices.append(index)
    return tuple(sorted(indices))


def _rgb(raw: object) -> tuple[int, int, int] | None:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return None
    values = tuple(raw)[:3]
    if len(values) < 3:
        return None
    channels: list[int] = []
    for value in values:
        if isinstance(value, bool):
            return None
        try:
            channels.append(max(0, min(255, int(round(float(value))))))
        except (TypeError, ValueError, OverflowError):
            return None
    return channels[0], channels[1], channels[2]


def _clamped_float(raw: object, minimum: float, maximum: float) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return max(minimum, min(maximum, value))


class MeshEditorDotNetPartColourMixin:
    """Routes resident Colour page edits to the Builder that owns the parts."""

    def _handle_dotnet_part_material_edit_request(
        self,
        payload: Mapping[str, object],
    ) -> bool:
        edit = normalized_part_material_edit(payload)
        if edit is None:
            self._send_dotnet_command_result(
                "part_material_edit",
                ok=False,
                status="rejected",
                diagnostics=("The colour edit named no parts or no values.",),
                request_payload=payload,
            )
            return False
        handler = getattr(
            self.active_builder(),
            "_mesh_editor_apply_dotnet_part_material_edit",
            None,
        )
        if not callable(handler):
            self._send_dotnet_command_result(
                "part_material_edit",
                ok=False,
                status="unavailable",
                diagnostics=("Resident part colour authority is unavailable.",),
                request_payload=payload,
            )
            return False
        try:
            applied = bool(handler(edit))
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET part colour edit failed: {exc}", error=True)
            self._send_dotnet_command_result(
                "part_material_edit",
                ok=False,
                status="error",
                diagnostics=(str(exc),),
                request_payload=payload,
            )
            return False
        self._send_dotnet_command_result(
            "part_material_edit",
            ok=applied,
            status="applied" if applied else "rejected",
            request_payload=payload,
        )
        return applied


__all__ = [
    "MeshEditorDotNetPartColourMixin",
    "normalized_part_material_edit",
]
