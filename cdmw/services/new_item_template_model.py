"""Owned template copies: preserve geometry/material inputs except explicit edits."""

from pathlib import PurePosixPath

from cdmw.domain.cancellation import raise_if_cancelled


def template_material_parts(snapshot, key, *, stop_event=None):
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    from cdmw.services.new_item_variants import xml_path

    try:
        family = snapshot.family(key)
    except ValueError:
        return {}
    parts = {}
    for item in family.files_for("pac"):
        raise_if_cancelled(stop_event)
        path = xml_path(item.path)
        if item.exists and snapshot.has_entry(path):
            text = snapshot.payload(path).decode("utf-8-sig")
            parts[item.path.casefold()] = tuple((row.submesh_name, row.submesh_name)
                                               for row in find_material_wrappers(text))
    return parts


def transform_template_mesh(mesh, matrix):
    """Use the viewport's row-vector matrix without changing topology, UVs or skin."""
    if not matrix:
        return mesh
    import numpy as np
    from cdmw.domain.new_item.authoring_rules import validate_template_transform
    from cdmw.modding.mesh_deformer import clone_mesh_for_editing
    from cdmw.modding.mesh_totals import refresh_mesh_totals

    validate_template_transform(matrix)
    values = np.asarray(matrix, dtype=float).reshape(4, 4)
    copied = clone_mesh_for_editing(mesh)
    normal_matrix = np.linalg.inv(values[:3, :3]).T
    for part in copied.submeshes:
        positions = np.asarray(part.vertices, dtype=float)
        if not len(positions):
            continue
        transformed = positions @ values[:3, :3] + values[3, :3]
        part.vertices = [tuple(row) for row in transformed]
        for attribute in ("normals", "tangents"):
            original = getattr(part, attribute, ())
            if not original:
                continue
            directions = np.asarray([row[:3] for row in original]) @ (
                normal_matrix if attribute == "normals" else values[:3, :3]
            )
            if attribute == "tangents" and len(part.normals) == len(directions):
                normals = np.asarray(part.normals)
                directions -= normals * np.sum(directions * normals, axis=1)[:, None]
            directions /= np.maximum(np.linalg.norm(directions, axis=1)[:, None], 1e-12)
            setattr(part, attribute, [(*row, *original[index][3:]) for index, row in enumerate(directions)])
        low, high = transformed.min(axis=0), transformed.max(axis=0)
        part.source_bbox_min = tuple(low)
        part.source_bbox_extent = tuple(high - low)
    points = [point for part in copied.submeshes for point in part.vertices]
    if points:
        copied.bbox_min = tuple(min(point[axis] for point in points) for axis in range(3))
        copied.bbox_max = tuple(max(point[axis] for point in points) for axis in range(3))
    refresh_mesh_totals(copied)
    return copied


def transform_template_pac(payload, matrix, *, stop_event=None):
    """Transform every stored LOD without rebuilding topology or skin/cloth records."""
    import math
    import struct
    import numpy as np
    from cdmw.domain.new_item.authoring_rules import validate_template_transform
    from cdmw.modding.pac_cloth import pac_cloth_lods
    from cdmw.modding.mesh_pac_builder import _pack_pac_normal, _patch_pac_descriptor_bounds, _quantize_pac_u16

    validate_template_transform(matrix)
    values = np.asarray(matrix, dtype=float).reshape(4, 4)
    linear = values[:3, :3]
    normal_matrix = np.linalg.inv(linear).T
    try:
        levels = pac_cloth_lods(payload)
    except ValueError as exc:
        raise ValueError("Template placement requires complete independent PAC vertex records at every LOD.") from exc
    transformed, bounds = [], {}
    for mesh in levels:
        raise_if_cancelled(stop_event)
        for part in mesh.submeshes:
            if not part.vertices:
                continue
            positions = np.asarray(part.vertices) @ linear + values[3, :3]
            descriptor = part.source_descriptor_offset
            low, high = positions.min(axis=0), positions.max(axis=0)
            if descriptor in bounds:
                low, high = np.minimum(low, bounds[descriptor][0]), np.maximum(high, bounds[descriptor][1])
            bounds[descriptor] = low, high
            transformed.append((part, positions))
    result = bytearray(payload)
    for descriptor, (low, high) in tuple(bounds.items()):
        low = np.nextafter(low.astype(np.float32), np.float32(-np.inf))
        extent = np.nextafter((high - low).astype(np.float32), np.float32(np.inf))
        bounds[descriptor] = tuple(float(v) for v in low), tuple(float(v) for v in extent)
        _patch_pac_descriptor_bounds(result, descriptor, *bounds[descriptor])
    change_directions = not np.allclose(linear, np.eye(3) * linear[0, 0], rtol=0, atol=1e-12)
    for part, positions in transformed:
        low, extent = bounds[part.source_descriptor_offset]
        normals = np.asarray(part.normals) @ normal_matrix if change_directions else None
        if normals is not None:
            normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-12)
        for index, (offset, point) in enumerate(zip(part.source_vertex_offsets, positions, strict=True)):
            if index % 4096 == 0:
                raise_if_cancelled(stop_event)
            struct.pack_into("<3H", result, offset, *(_quantize_pac_u16(point[i], low[i], extent[i]) for i in range(3)))
            if not change_directions:
                continue
            packed = struct.unpack_from("<I", payload, offset + 16)[0]
            lane = struct.unpack_from("<h", payload, offset + 6)[0]
            # Shipped shader decoding: signed magnitude X/Z in bytes 6..7,
            # Y in normal bits 0..9, handedness in bit 31 (positive-scale edits).
            tx, ty = abs(lane / 32767.0) * 2 - 1, (packed & 1023) / 511.5 - 1
            tz = math.sqrt(max(0, 1 - tx * tx - ty * ty)) * (-1 if lane < 0 else 1)
            tangent = np.asarray((tx, ty, tz)) @ linear
            tangent -= normals[index] * np.dot(tangent, normals[index])
            length = np.linalg.norm(tangent)
            if length > 1e-12:
                tangent /= length
                magnitude = max(0, min(32767, round((float(tangent[0]) + 1) * 16383.5)))
                struct.pack_into("<h", result, offset + 6, -magnitude if tangent[2] < 0 else magnitude)
                packed = (packed & ~1023) | max(0, min(1023, round((float(tangent[1]) + 1) * 511.5)))
            struct.pack_into("<I", result, offset + 16, _pack_pac_normal(tuple(normals[index]), packed))
    return bytes(result)


def prepare_template_model(snapshot, paths, *, glow=None, translucency=None, shader_controls=(), transform=(), on_log=None, on_progress=None, stop_event=None):
    from cdmw.core.pac_xml_standard_material import find_material_wrappers, rewrite_emission
    from cdmw.services.new_item_planning import ModelFiles, NewItemPlanError
    from cdmw.services.new_item_materials import encode_emissive_solid
    from cdmw.services.new_item_variants import xml_path

    if not paths:
        raise NewItemPlanError("The template has no editable model.")
    selected_glow = {name.casefold() for name in (glow.parts if glow else ())}
    selected_glass = {name.casefold() for name in (translucency.parts if translucency else ())}
    found_glow, found_glass, found_controls = set(), set(), set()
    from cdmw.domain.mesh.shader_controls import validate_choices
    validate_choices(shader_controls, glow_parts=tuple(selected_glow), translucent_parts=tuple(selected_glass), equipment=True)
    side, geometry = {}, {}
    notes = ["Template geometry and authored materials retained with explicit appearance/placement edits."]
    solid = None
    for path in paths:
        raise_if_cancelled(stop_event)
        if on_log is not None:
            on_log(f"Preparing template model: {PurePosixPath(path).name}...")
        payload = snapshot.payload(path)
        if transform:
            payload = transform_template_pac(payload, transform, stop_event=stop_event)
        geometry[path] = payload
        xml = xml_path(path)
        if not snapshot.has_entry(xml):
            continue
        original = snapshot.payload(xml)
        text = original.decode("utf-8-sig")
        emission, glass = {}, {}
        for row in find_material_wrappers(text):
            name = row.submesh_name.casefold()
            if name in selected_glow:
                found_glow.add(name)
                texture = row.textures.get("_emissiveIntensityTexture", "")
                if not texture and glow.rgb is not None:
                    texture = row.textures.get("_emissiveProgressTexture", "")
                    if not texture:
                        raise NewItemPlanError(f"{row.submesh_name}: RGB glow needs a source glow texture.")
                if not texture:
                    if solid is None:
                        solid = encode_emissive_solid()
                    texture = str(PurePosixPath(path.replace("character/model/", "character/texture/")).with_suffix("")) + "_cdmw_glow.dds"
                    side[texture] = solid
                emission[name] = (texture, glow.hex_color(), glow.intensity)
            if name in selected_glass:
                found_glass.add(name)
                glass[name] = translucency.values_for(name)
        if glass:
            from cdmw.services.new_item_template_materials import bake_template_translucency

            text, textures, baked_notes = bake_template_translucency(snapshot, text, path, glass,
                on_log=on_log, on_progress=on_progress, stop_event=stop_event)
            side.update(textures)
            notes.extend(baked_notes)
        if emission:
            from cdmw.core.pac_xml_emission import rewrite_emission_animation
            # Validate against the source shader before switching it.
            text = rewrite_emission_animation(text, {name: glow.animation for name in emission})
            text = rewrite_emission(text, emission)
            from cdmw.core.pac_xml_emission import rewrite_rgb_emission
            text = rewrite_rgb_emission(text, {name: (glow.rgb, glow.hex_color()) for name in emission})
        if glass:
            from cdmw.services.translucency_surface import apply_translucency_surface

            sources = {key.casefold(): data for key, data in side.items()}
            def read_surface(path):
                return sources.get(path.casefold()) if path.casefold() in sources else (
                    snapshot.payload(path) if snapshot.has_entry(path) else None)
            try:
                text, textures = apply_translucency_surface(text, glass,
                    {name: translucency.surface_for(name) for name in glass}, path, read_surface, stop_event=stop_event)
            except ValueError as exc:
                raise NewItemPlanError(str(exc)) from exc
            side.update(textures)
        if shader_controls:
            from cdmw.core.material_shader_controls import rewrite_shader_controls
            text, matched = rewrite_shader_controls(text, shader_controls, allow_missing=True)
            found_controls.update(matched)
        if emission or glass or shader_controls:
            side[xml] = (b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b"") + text.encode("utf-8")
    missing = (selected_glow - found_glow) | (selected_glass - found_glass) | ({name.casefold() for name, _ in shader_controls} - found_controls)
    if missing:
        raise NewItemPlanError("Template material bindings were not found: " + ", ".join(sorted(missing)))
    side.update({path: data for path, data in geometry.items() if path != paths[0]})
    return ModelFiles(pac_data=geometry[paths[0]], side_files=side, material_route="template",
                      notes=tuple(notes))
