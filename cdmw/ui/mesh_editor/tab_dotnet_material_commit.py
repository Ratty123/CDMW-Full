from __future__ import annotations

import copy
from collections.abc import Mapping
from types import SimpleNamespace


def remember_sent_material_parameters(tab: object, payload: Mapping[str, object] | None) -> None:
    setattr(tab, "standalone_dotnet_sent_material_parameter_payload", dict(payload) if payload else None)


def material_resource_snapshot(
    tab: object,
    mesh_snapshot: object,
    bindings: object,
    affected_submeshes: object = (),
) -> object:
    rows = tuple(getattr(mesh_snapshot, "submeshes", ()) or getattr(mesh_snapshot, "meshes", ()) or ())
    if not rows:
        controller = tab._dotnet_target_controller()
        rows = tuple(getattr(controller.working_mesh(clone=False), "submeshes", ()) or ())
    submeshes = [copy.copy(row) for row in rows]
    fallback_indices = tuple(affected_submeshes or ())
    attrs = {
        "base": ("texture", "preview_texture_path"),
        "albedo": ("texture", "preview_texture_path"),
        "diffuse": ("texture", "preview_texture_path"),
        "normal": ("preview_normal_texture_path",),
        "material": ("preview_material_texture_path",),
        "mask": ("preview_material_texture_path",),
        "specular": ("preview_material_texture_path",),
        "roughness": ("preview_material_texture_path",),
        "metallic": ("preview_material_texture_path",),
        "height": ("preview_height_texture_path",),
        "emissive": ("preview_emissive_texture_path",),
    }
    for binding in tuple(bindings or ()):
        if not isinstance(binding, Mapping):
            continue
        channel = str(binding.get("channel", "base") or "base").strip().lower() or "base"
        path = "" if bool(binding.get("remove", False)) else str(
            binding.get("source_dds_path", binding.get("path", "")) or ""
        )
        raw_indices = tuple(binding.get("affected_submeshes", ()) or fallback_indices)
        indices = range(len(submeshes)) if not raw_indices else (
            int(index) for index in raw_indices if not isinstance(index, bool)
        )
        for index in indices:
            if 0 <= index < len(submeshes):
                for attr in attrs.get(channel, (f"preview_{channel}_texture_path",)):
                    setattr(submeshes[index], attr, path)
    return SimpleNamespace(submeshes=submeshes)


def remember_sent_material_resources(
    tab: object,
    payload: Mapping[str, object] | None,
    bindings: object = (),
) -> None:
    staged = None
    if payload is not None and tuple(bindings or ()):
        staged = {
            "session_id": str(payload.get("session_id", "") or ""),
            "edit_revision": int(payload.get("edit_revision", 0) or 0),
            "generation": int(payload.get("generation", 0) or 0),
            "bindings": tuple(dict(binding) for binding in bindings if isinstance(binding, Mapping)),
            "parameter_groups": tuple(
                dict(group)
                for group in tuple(payload.get("material_authority_parameter_groups", ()) or ())
                if isinstance(group, Mapping)
            ),
            "material_authority_fingerprint": str(
                payload.get("material_authority_fingerprint", "") or ""
            ),
            "material_authority_revision": int(
                payload.get("material_authority_revision", 0) or 0
            ),
        }
    setattr(tab, "standalone_dotnet_sent_material_resource_payload", staged)


def finish_sent_material_resources(tab: object, *, committed: bool) -> None:
    staged = getattr(tab, "standalone_dotnet_sent_material_resource_payload", None)
    if not isinstance(staged, Mapping):
        return
    builder = tab.active_builder()
    callback = getattr(builder, "_mesh_editor_embedded_material_resources_finished", None)
    if callable(callback):
        args = (
            int(staged.get("generation", 0) or 0),
            bool(committed),
            tuple(staged.get("bindings", ()) or ()),
        )
        try:
            callback(
                *args,
                str(staged.get("material_authority_fingerprint", "") or ""),
                int(staged.get("material_authority_revision", 0) or 0),
            )
        except TypeError:
            callback(*args)


def commit_acknowledged_material_resources(tab: object, payload: Mapping[str, object]) -> bool:
    staged = getattr(tab, "standalone_dotnet_sent_material_resource_payload", None)
    if not isinstance(staged, Mapping):
        return True
    try:
        generation = int(payload.get("generation", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    if generation != staged.get("generation"):
        return False
    staged_fingerprint = str(staged.get("material_authority_fingerprint", "") or "")
    acknowledged_fingerprint = str(payload.get("material_authority_fingerprint", "") or "")
    if staged_fingerprint and acknowledged_fingerprint != staged_fingerprint:
        return False
    controller = tab._dotnet_target_controller()
    service = getattr(controller, "mesh_service", None)
    commit_state = getattr(service, "commit_resident_material_state", None)
    commit_resources = getattr(service, "commit_resident_material_resources", None)
    commit = commit_state if callable(commit_state) else commit_resources
    if not callable(commit):
        return False
    try:
        if callable(commit_state):
            commit_state(
                str(staged.get("session_id", "") or ""),
                tuple(staged.get("bindings", ()) or ()),
                parameter_groups=tuple(staged.get("parameter_groups", ()) or ()),
                material_authority_fingerprint=staged_fingerprint,
                material_authority_revision=int(staged.get("material_authority_revision", 0) or 0),
                expected_mesh_revision=int(staged.get("edit_revision", 0) or 0),
            )
        else:
            if tuple(staged.get("parameter_groups", ()) or ()) or staged_fingerprint:
                raise RuntimeError("atomic resident material state commit is unavailable")
            commit_resources(
                str(staged.get("session_id", "") or ""),
                tuple(staged.get("bindings", ()) or ()),
                expected_mesh_revision=int(staged.get("edit_revision", 0) or 0),
            )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        tab.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
        tab._set_dotnet_status(f"Could not commit resident material resources for export: {exc}", error=True)
        finish_sent_material_resources(tab, committed=False)
        remember_sent_material_resources(tab, None)
        return False
    finish_sent_material_resources(tab, committed=True)
    remember_sent_material_resources(tab, None)
    return True


def commit_acknowledged_material_parameters(tab: object, payload: Mapping[str, object]) -> bool:
    staged = getattr(tab, "standalone_dotnet_sent_material_parameter_payload", None)
    if not isinstance(staged, Mapping):
        return False
    identity = ("session_id", "edit_revision", "parameter_generation")
    if any(staged.get(key) != payload.get(key, payload.get("generation") if key == "parameter_generation" else None) for key in identity):
        return False
    controller = tab._dotnet_target_controller()
    service = getattr(controller, "mesh_service", None)
    commit = getattr(service, "commit_resident_material_parameters", None)
    if not callable(commit):
        return False
    try:
        commit(
            str(staged.get("session_id", "") or ""),
            tuple(staged.get("groups", ()) or ()),
            expected_mesh_revision=int(staged.get("edit_revision", 0) or 0),
        )
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        tab.standalone_dotnet_lifecycle_counts["material_parameter_failed_count"] += 1
        tab._set_dotnet_status(f"Could not commit resident material parameters for export: {exc}", error=True)
        remember_sent_material_parameters(tab, None)
        return False
    remember_sent_material_parameters(tab, None)
    return True


__all__ = [
    "commit_acknowledged_material_parameters",
    "commit_acknowledged_material_resources",
    "finish_sent_material_resources",
    "material_resource_snapshot",
    "remember_sent_material_parameters",
    "remember_sent_material_resources",
]
