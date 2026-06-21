"""Diagnostics formatters for static replacement preview state."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path

from cdmw.models import ModelPreviewData


def mesh_editor_diagnostics_initial_state() -> dict[str, object]:
    return {"text_widget": None, "last_text": ""}


def mesh_editor_diagnostics_copied_status() -> str:
    return "Mesh Editor diagnostics copied."


def mesh_editor_diagnostics_text_widget(state: Mapping[str, object]) -> object:
    return state.get("text_widget")


def mesh_editor_diagnostics_set_text_widget(
    state: MutableMapping[str, object],
    text_widget: object,
) -> None:
    state["text_widget"] = text_widget


def mesh_editor_diagnostics_record_text(
    state: MutableMapping[str, object],
    text: str,
    *,
    auto: bool,
) -> bool:
    text_value = str(text)
    if bool(auto) and text_value == str(state.get("last_text", "") or ""):
        return False
    state["last_text"] = text_value
    return True


def mesh_editor_diagnostics_append_safe_value(
    lines: list[str],
    label: str,
    getter: Callable[[], object],
) -> None:
    try:
        value = getter()
    except Exception as exc:
        value = f"<error: {exc}>"
    lines.append(f"{label}: {value}")


def mesh_editor_diagnostics_model_lines(label: str, model: object, *, limit: int = 18) -> list[str]:
    lines: list[str] = []
    if not isinstance(model, ModelPreviewData):
        lines.append(f"{label}: unavailable")
        return lines
    meshes = list(getattr(model, "meshes", ()) or ())
    vertex_count = int(getattr(model, "vertex_count", 0) or sum(len(getattr(mesh, "positions", ()) or ()) for mesh in meshes))
    face_count = int(getattr(model, "face_count", 0) or sum(len(getattr(mesh, "indices", ()) or ()) // 3 for mesh in meshes))
    textured = sum(
        1
        for mesh in meshes
        if (
            str(getattr(mesh, "preview_texture_path", "") or "").strip()
            or str(getattr(mesh, "preview_material_texture_path", "") or "").strip()
            or tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
        )
    )
    double_sided = sum(1 for mesh in meshes if bool(getattr(mesh, "preview_double_sided", False)))
    editable = sum(1 for mesh in meshes if int(getattr(mesh, "source_submesh_index", -1) or -1) >= 0)
    lines.extend(
        [
            f"{label}: meshes={len(meshes):,} verts={vertex_count:,} faces={face_count:,} textured={textured:,} double_sided={double_sided:,} editable={editable:,}",
            f"{label} path: {str(getattr(model, 'path', '') or '')}",
            f"{label} summary: {str(getattr(model, 'summary', '') or '')}",
        ]
    )
    for index, mesh in enumerate(meshes[: max(0, int(limit))]):
        material_inputs = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
        input_summary = ", ".join(
            (
                f"{str(getattr(item, 'parameter_name', '') or getattr(item, 'slot_kind', '') or '?')}"
                f":{str(getattr(item, 'semantic_subtype', '') or getattr(item, 'semantic_type', '') or '?')}"
            )
            for item in material_inputs[:5]
        )
        textures = [
            slot
            for slot, value in (
                ("base", getattr(mesh, "preview_texture_path", "")),
                ("normal", getattr(mesh, "preview_normal_texture_path", "")),
                ("material", getattr(mesh, "preview_material_texture_path", "")),
                ("height", getattr(mesh, "preview_height_texture_path", "")),
            )
            if str(value or "").strip()
        ]
        lines.append(
            f"  [{index:02d}] src={int(getattr(mesh, 'source_submesh_index', -1) or -1)} "
            f"role={str(getattr(mesh, 'preview_role', '') or '-')} "
            f"mat={str(getattr(mesh, 'material_name', '') or '-')[:70]} "
            f"verts={len(getattr(mesh, 'positions', ()) or ()):>7,} "
            f"faces={len(getattr(mesh, 'indices', ()) or ()) // 3:>7,} "
            f"uv={len(getattr(mesh, 'texture_coordinates', ()) or ()):>7,} "
            f"norm={len(getattr(mesh, 'normals', ()) or ()):>7,} "
            f"two_sided={bool(getattr(mesh, 'preview_double_sided', False))} "
            f"textures={'+'.join(textures) or '-'} inputs={input_summary or '-'}"
        )
    if len(meshes) > limit:
        lines.append(f"  ... {len(meshes) - limit:,} more mesh(es)")
    return lines


def mesh_editor_diagnostics_source_mesh_lines(
    label: str,
    mesh: object,
    *,
    limit: int = 18,
    enabled_predicate: Callable[[int], bool] | None = None,
) -> list[str]:
    lines: list[str] = []
    submeshes = list(getattr(mesh, "submeshes", ()) or ()) if mesh is not None else []
    if not submeshes:
        lines.append(f"{label}: unavailable")
        return lines
    total_vertices = sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in submeshes)
    total_faces = sum(len(getattr(submesh, "faces", ()) or ()) for submesh in submeshes)
    total_uvs = sum(len(getattr(submesh, "uvs", ()) or ()) for submesh in submeshes)
    total_normals = sum(len(getattr(submesh, "normals", ()) or ()) for submesh in submeshes)
    lines.append(
        f"{label}: submeshes={len(submeshes):,} verts={total_vertices:,} faces={total_faces:,} "
        f"uv={total_uvs:,} normals={total_normals:,}"
    )
    lines.append(f"{label} path: {str(getattr(mesh, 'path', '') or '')}")
    for index, submesh in enumerate(submeshes[: max(0, int(limit))]):
        enabled = True
        if enabled_predicate is not None:
            try:
                enabled = enabled_predicate(index)
            except Exception:
                pass
        lines.append(
            f"  [{index:02d}] enabled={enabled} "
            f"mat={str(getattr(submesh, 'material', '') or getattr(submesh, 'name', '') or '-')[:70]} "
            f"verts={len(getattr(submesh, 'vertices', ()) or ()):>7,} "
            f"faces={len(getattr(submesh, 'faces', ()) or ()):>7,} "
            f"uv={len(getattr(submesh, 'uvs', ()) or ()):>7,} "
            f"norm={len(getattr(submesh, 'normals', ()) or ()):>7,}"
        )
    if len(submeshes) > limit:
        lines.append(f"  ... {len(submeshes) - limit:,} more submesh(es)")
    return lines


def mesh_editor_diagnostics_manifest_lines(package_dir: object, *, limit: int = 24) -> list[str]:
    lines: list[str] = []
    try:
        manifest_path = Path(package_dir) / "manifest.json" if package_dir is not None else None
    except TypeError:
        manifest_path = None
    if manifest_path is None or not manifest_path.is_file():
        lines.append("manifest: unavailable")
        return lines
    lines.append(f"manifest path: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        lines.append(f"manifest read error: {exc}")
        return lines
    if not isinstance(manifest, Mapping):
        lines.append("manifest: invalid payload")
        return lines
    batches = manifest.get("batches")
    batch_list = list(batches) if isinstance(batches, Sequence) and not isinstance(batches, (str, bytes, bytearray)) else []
    texture_counts: Counter[str] = Counter()
    material_input_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    two_sided_count = 0
    uv_count = 0
    tangent_count = 0
    editable_count = 0
    total_batch_vertices = 0
    for batch in batch_list:
        if not isinstance(batch, Mapping):
            continue
        total_batch_vertices += int(batch.get("vertex_count", 0) or 0)
        if bool(batch.get("two_sided", batch.get("double_sided", False))):
            two_sided_count += 1
        if bool(batch.get("has_texture_coordinates", False)):
            uv_count += 1
        if bool(batch.get("tangents_usable", False)):
            tangent_count += 1
        identity = batch.get("editor_identity")
        if isinstance(identity, Mapping):
            role = str(identity.get("role", "") or batch.get("editor_role", "") or "-")
            if bool(identity.get("editable", batch.get("editor_editable", False))):
                editable_count += 1
        else:
            role = str(batch.get("editor_role", "") or "-")
            if bool(batch.get("editor_editable", False)):
                editable_count += 1
        role_counts[role] += 1
        for slot_group in ("textures", "dds_textures"):
            textures = batch.get(slot_group)
            if isinstance(textures, Mapping):
                for slot_name, value in textures.items():
                    if str(value or "").strip():
                        texture_counts[str(slot_name)] += 1
        material_inputs = batch.get("material_inputs")
        if isinstance(material_inputs, Sequence) and not isinstance(material_inputs, (str, bytes, bytearray)):
            for material_input in material_inputs:
                if not isinstance(material_input, Mapping):
                    continue
                slot = str(material_input.get("slot_kind", "") or "?")
                subtype = str(material_input.get("semantic_subtype", "") or material_input.get("semantic_type", "") or "?")
                packed = ",".join(str(value) for value in tuple(material_input.get("packed_channels", ()) or ())) or "-"
                material_input_counts[f"{slot}:{subtype}:{packed}"] += 1
    lines.extend(
        [
            "manifest: "
            f"schema={manifest.get('schema_version', '?')} backend={manifest.get('backend', '?')} "
            f"workspace={manifest.get('editor_workspace', '?')} display={manifest.get('display_mode', '?')} "
            f"diagnostic={manifest.get('render_diagnostic_mode', '?')} view={manifest.get('d3d11_view_mode', '?')}",
            f"manifest counts: meshes={manifest.get('mesh_count', '?')} verts={manifest.get('vertex_count', '?')} "
            f"faces={manifest.get('face_count', '?')} batches={len(batch_list):,} batch_vertices={total_batch_vertices:,}",
            f"manifest flags: two_sided_batches={two_sided_count:,} uv_batches={uv_count:,} tangent_batches={tangent_count:,} editable_batches={editable_count:,}",
            "manifest roles: " + (", ".join(f"{key}={value}" for key, value in sorted(role_counts.items())) or "-"),
            "manifest textures: " + (", ".join(f"{key}={value}" for key, value in sorted(texture_counts.items())) or "-"),
            "manifest material inputs: "
            + (", ".join(f"{key}={value}" for key, value in sorted(material_input_counts.items())) or "-"),
        ]
    )
    render_settings = manifest.get("render_settings")
    if isinstance(render_settings, Mapping):
        lines.append(
            "manifest render settings: "
            f"visible={render_settings.get('visible_texture_mode', '?')} "
            f"diagnostic={render_settings.get('render_diagnostic_mode', '?')} "
            f"support_disabled={render_settings.get('disable_all_support_maps', '?')} "
            f"normal_disabled={render_settings.get('disable_normal_map', '?')} "
            f"material_disabled={render_settings.get('disable_material_map', '?')} "
            f"height_disabled={render_settings.get('disable_height_map', '?')}"
        )
    load_trace = manifest.get("load_trace")
    if isinstance(load_trace, Mapping) and load_trace:
        trace_order = (
            "prepare_ms",
            "geometry_pack_ms",
            "material_apply_ms",
            "package_write_ms",
            "dds_manifest_ms",
            "texture_copy_ms",
        )
        trace_parts = []
        for key in trace_order:
            if key in load_trace:
                try:
                    trace_parts.append(f"{key}={float(load_trace.get(key, 0.0) or 0.0):.1f}ms")
                except (TypeError, ValueError, OverflowError):
                    trace_parts.append(f"{key}={load_trace.get(key)}")
        for key, value in sorted(load_trace.items()):
            if key in trace_order:
                continue
            try:
                trace_parts.append(f"{key}={float(value or 0.0):.1f}ms")
            except (TypeError, ValueError, OverflowError):
                trace_parts.append(f"{key}={value}")
        lines.append("manifest load trace: " + (", ".join(trace_parts) or "-"))
    for index, batch in enumerate(batch_list[: max(0, int(limit))]):
        if not isinstance(batch, Mapping):
            continue
        identity = batch.get("editor_identity")
        role = ""
        source_index = ""
        editable = ""
        if isinstance(identity, Mapping):
            role = str(identity.get("role", "") or "")
            source_index = str(identity.get("source_submesh_index", ""))
            editable = str(identity.get("editable", ""))
        texture_slots = []
        for slot_group in ("textures", "dds_textures"):
            textures = batch.get(slot_group)
            if isinstance(textures, Mapping):
                texture_slots.extend(str(slot) for slot, value in textures.items() if str(value or "").strip())
        material_inputs = batch.get("material_inputs")
        input_summary = "-"
        if isinstance(material_inputs, Sequence) and not isinstance(material_inputs, (str, bytes, bytearray)):
            input_summary = ", ".join(
                f"{str(item.get('parameter_name', '') or item.get('slot_kind', '') or '?')}:{str(item.get('semantic_subtype', '') or item.get('semantic_type', '') or '?')}"
                for item in material_inputs[:5]
                if isinstance(item, Mapping)
            ) or "-"
        lines.append(
            f"  batch[{index:02d}] src={source_index or batch.get('source_submesh_index', '-')} role={role or batch.get('editor_role', '-')} editable={editable or batch.get('editor_editable', '-')}"
            f" mat={str(batch.get('material_name', '') or '-')[:60]} verts={int(batch.get('vertex_count', 0) or 0):>7,} "
            f"two_sided={bool(batch.get('two_sided', batch.get('double_sided', False)))} uv={bool(batch.get('has_texture_coordinates', False))} "
            f"tan={bool(batch.get('tangents_usable', False))} tex={'+'.join(sorted(set(texture_slots))) or '-'} inputs={input_summary}"
        )
    if len(batch_list) > limit:
        lines.append(f"  ... {len(batch_list) - limit:,} more batch(es)")
    return lines


__all__ = [
    "mesh_editor_diagnostics_initial_state",
    "mesh_editor_diagnostics_append_safe_value",
    "mesh_editor_diagnostics_copied_status",
    "mesh_editor_diagnostics_manifest_lines",
    "mesh_editor_diagnostics_model_lines",
    "mesh_editor_diagnostics_record_text",
    "mesh_editor_diagnostics_set_text_widget",
    "mesh_editor_diagnostics_source_mesh_lines",
    "mesh_editor_diagnostics_text_widget",
]
