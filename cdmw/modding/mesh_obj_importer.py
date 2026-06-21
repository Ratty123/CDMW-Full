"""Wavefront OBJ round-trip importer for mesh replacement flows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .logging import get_logger
from .mesh_parser import ParsedMesh, SubMesh

logger = get_logger("core.mesh_importer")

_OBJ_ROUNDTRIP_SIDECAR_FORMATS = {"obj_meta_v1", "mesh_roundtrip_manifest_v2"}


def _resolve_obj_index(raw_index: str, item_count: int) -> int:
    """Resolve a Wavefront OBJ index token to a zero-based Python index."""
    value = int(raw_index)
    if value > 0:
        return value - 1
    if value < 0:
        return item_count + value
    raise ValueError("OBJ indices are 1-based and cannot be zero")


def _obj_roundtrip_sidecar_candidates(obj_path: Path) -> tuple[Path, ...]:
    return (Path(f"{obj_path}.meta.json"),)


def _load_obj_roundtrip_sidecar(obj_path: str) -> Optional[dict[str, object]]:
    for candidate in _obj_roundtrip_sidecar_candidates(Path(obj_path)):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read OBJ round-trip sidecar %s: %s", candidate, exc)
            continue
        if not isinstance(payload, dict):
            logger.warning("Ignoring OBJ round-trip sidecar %s because it is not a JSON object.", candidate)
            continue
        payload_format = str(payload.get("format", "") or "").strip()
        if payload_format and payload_format not in _OBJ_ROUNDTRIP_SIDECAR_FORMATS:
            logger.warning(
                "Ignoring OBJ round-trip sidecar %s because it uses unsupported format %r.",
                candidate,
                payload_format,
            )
            continue
        logger.info("Loaded OBJ round-trip sidecar: %s", candidate)
        return payload
    return None


def _normalize_obj_sidecar_texture_name(sidecar_submesh_entry: object) -> str:
    if not isinstance(sidecar_submesh_entry, dict):
        return ""
    return str(sidecar_submesh_entry.get("texture", "") or "").strip()


def _resolve_obj_material_library_paths(obj_path: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    seen: set[str] = set()
    try:
        with obj_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line.lower().startswith("mtllib "):
                    continue
                raw_value = line[7:].strip()
                if not raw_value:
                    continue
                candidate = (obj_path.parent / raw_value).expanduser().resolve()
                lowered = str(candidate).lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                candidates.append(candidate)
    except OSError:
        return ()
    fallback_candidate = obj_path.with_suffix(".mtl").expanduser().resolve()
    fallback_key = str(fallback_candidate).lower()
    if fallback_key not in seen:
        candidates.append(fallback_candidate)
    return tuple(candidates)


def _load_obj_material_texture_map(obj_path: str) -> dict[str, str]:
    texture_by_material: dict[str, str] = {}
    for candidate in _resolve_obj_material_library_paths(Path(obj_path)):
        if not candidate.is_file():
            continue
        current_material = ""
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    lowered = line.lower()
                    if lowered.startswith("newmtl "):
                        current_material = line[7:].strip()
                        continue
                    if not current_material or not lowered.startswith("map_kd "):
                        continue
                    texture_value = line[7:].strip()
                    if texture_value and current_material not in texture_by_material:
                        texture_by_material[current_material] = texture_value
        except OSError as exc:
            logger.warning("Failed to read OBJ material library %s: %s", candidate, exc)
            continue
    return texture_by_material


def _normalize_obj_sidecar_source_vertex_map(
    sidecar_submesh_entry: object,
    *,
    expected_count: Optional[int] = None,
) -> list[int]:
    if not isinstance(sidecar_submesh_entry, dict):
        return []
    raw_map = sidecar_submesh_entry.get("source_vertex_map")
    if not isinstance(raw_map, list):
        return []
    normalized: list[int] = []
    for value in raw_map:
        try:
            normalized.append(int(value))
        except Exception:
            return []
    if expected_count is not None and len(normalized) != expected_count:
        return []
    return normalized


def _match_obj_roundtrip_sidecar_submeshes(
    sidecar_payload: Optional[dict[str, object]],
    submesh_list: list[dict],
    *,
    source_path: str,
    source_format: str,
) -> list[Optional[dict[str, object]]]:
    matched_entries: list[Optional[dict[str, object]]] = [None] * len(submesh_list)
    if not sidecar_payload:
        return matched_entries

    sidecar_source_path = str(sidecar_payload.get("source_path", "") or "").strip()
    if source_path and sidecar_source_path and sidecar_source_path != source_path:
        logger.warning(
            "Ignoring OBJ round-trip sidecar because source path mismatch: %s != %s",
            sidecar_source_path,
            source_path,
        )
        return matched_entries

    sidecar_source_format = str(sidecar_payload.get("source_format", "") or "").strip().lower()
    if source_format and sidecar_source_format and sidecar_source_format != source_format.strip().lower():
        logger.warning(
            "Ignoring OBJ round-trip sidecar because source format mismatch: %s != %s",
            sidecar_source_format,
            source_format,
        )
        return matched_entries

    raw_submeshes = sidecar_payload.get("submeshes")
    if not isinstance(raw_submeshes, list) or not raw_submeshes:
        return matched_entries

    sidecar_submeshes = [entry for entry in raw_submeshes if isinstance(entry, dict)]
    if not sidecar_submeshes:
        return matched_entries

    by_name: dict[str, dict[str, object]] = {}
    for sidecar_entry in sidecar_submeshes:
        sidecar_name = str(sidecar_entry.get("name", "") or "").strip()
        if not sidecar_name or sidecar_name in by_name:
            continue
        by_name[sidecar_name] = sidecar_entry

    if len(sidecar_submeshes) == len(submesh_list):
        by_name_matches: list[Optional[dict[str, object]]] = []
        for sm_data in submesh_list:
            submesh_name = str(sm_data.get("name", "") or "").strip()
            by_name_matches.append(by_name.get(submesh_name) if submesh_name else None)
        if all(entry is not None for entry in by_name_matches):
            return [entry for entry in by_name_matches if entry is not None]
        return [entry for entry in sidecar_submeshes]

    for index, sm_data in enumerate(submesh_list):
        submesh_name = str(sm_data.get("name", "") or "").strip()
        if submesh_name and submesh_name in by_name:
            matched_entries[index] = by_name[submesh_name]
    return matched_entries


# ═══════════════════════════════════════════════════════════════════════
#  OBJ IMPORTER
# ═══════════════════════════════════════════════════════════════════════

def import_obj(obj_path: str) -> ParsedMesh:
    """Import an OBJ file back into a ParsedMesh.

    Reads OBJ round-trip metadata comments (source_path, source_format)
    to identify the original game file.

    Returns:
        ParsedMesh with vertices, UVs, normals, faces per submesh.
    """
    sidecar_payload = _load_obj_roundtrip_sidecar(obj_path)
    material_texture_map = _load_obj_material_texture_map(obj_path)
    source_path = ""
    source_format = ""
    submeshes: list[SubMesh] = []

    # Current submesh being built
    current_name = ""
    verts: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normals: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    # Global vertex/uv/normal arrays (OBJ uses global indices)
    all_verts: list[tuple[float, float, float]] = []
    all_uvs: list[tuple[float, float]] = []
    all_normals: list[tuple[float, float, float]] = []

    # Per-submesh: track which global indices belong to each submesh
    submesh_list: list[dict] = []
    current_faces_global: list[tuple] = []
    current_material = ""
    saw_object_markers = False

    with open(obj_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # Parse metadata comments
            if line.startswith("# source_path:"):
                source_path = line.split(":", 1)[1].strip()
                continue
            if line.startswith("# source_format:"):
                source_format = line.split(":", 1)[1].strip()
                continue
            if line.startswith("#") or not line:
                continue

            parts = line.split()
            if not parts:
                continue

            if parts[0] == "v" and len(parts) >= 4:
                all_verts.append((float(parts[1]), float(parts[2]), float(parts[3])))

            elif parts[0] == "vt" and len(parts) >= 3:
                u = float(parts[1])
                v = 1.0 - float(parts[2])  # flip V back (OBJ export flipped it)
                all_uvs.append((u, v))

            elif parts[0] == "vn" and len(parts) >= 4:
                all_normals.append((float(parts[1]), float(parts[2]), float(parts[3])))

            elif parts[0] in {"o", "g"}:
                # New object/submesh — save previous
                saw_object_markers = True
                if current_name and current_faces_global:
                    submesh_list.append({
                        "name": current_name,
                        "material": current_material,
                        "faces_global": current_faces_global,
                    })
                current_name = parts[1] if len(parts) > 1 else f"submesh_{len(submesh_list)}"
                current_faces_global = []
                current_material = ""

            elif parts[0] == "usemtl":
                current_material = parts[1] if len(parts) > 1 else ""

            elif parts[0] == "f" and len(parts) >= 4:
                if not current_name:
                    current_name = "default"
                # Parse face indices (supports v, v/vt, v/vt/vn, v//vn) and
                # triangulate polygons by fan because Blender commonly exports quads.
                face_verts = []
                for fp in parts[1:]:
                    indices = fp.split("/")
                    vi = _resolve_obj_index(indices[0], len(all_verts))
                    ti = _resolve_obj_index(indices[1], len(all_uvs)) if len(indices) > 1 and indices[1] else -1
                    ni = _resolve_obj_index(indices[2], len(all_normals)) if len(indices) > 2 and indices[2] else -1
                    face_verts.append((vi, ti, ni))
                if len(face_verts) < 3:
                    continue
                for tri_idx in range(1, len(face_verts) - 1):
                    current_faces_global.append(
                        (face_verts[0], face_verts[tri_idx], face_verts[tri_idx + 1])
                    )

    # Save last submesh
    if current_name and current_faces_global:
        submesh_list.append({
            "name": current_name,
            "material": current_material,
            "faces_global": current_faces_global,
        })

    if not submesh_list:
        raise ValueError("OBJ import did not contain any face/object data.")

    matched_sidecar_entries = _match_obj_roundtrip_sidecar_submeshes(
        sidecar_payload,
        submesh_list,
        source_path=source_path,
        source_format=source_format,
    )

    # Convert global indices to per-submesh local indices.
    # Key: keep ALL vertices in each submesh's range (not just face-referenced ones).
    # Some meshes have unused vertices that must be preserved for correct rebuild.

    # First, determine vertex ownership: each submesh "owns" a contiguous range
    # based on the order vertices appear in the OBJ (submesh 0 first, etc.)
    vert_offset = 0
    for sm_data in submesh_list:
        # Count vertices that belong to this submesh in the OBJ
        # (vertices appear between 'o' markers, counted during parse above)
        # We stored them in all_verts in order — need to find this submesh's range
        pass

    def _build_generic_submesh(
        sm_data: dict,
        *,
        sidecar_entry: Optional[dict[str, object]] = None,
    ) -> SubMesh:
        vertex_key_to_local: dict[tuple[int, int, int], int] = {}
        local_verts: list[tuple[float, float, float]] = []
        local_uvs: list[tuple[float, float]] = []
        local_normals: list[tuple[float, float, float]] = []
        local_faces: list[tuple[int, int, int]] = []
        local_source_vertex_map: list[int] = []
        sidecar_source_map = _normalize_obj_sidecar_source_vertex_map(sidecar_entry)

        for face in sm_data["faces_global"]:
            local_face = []
            for vi, ti, ni in face:
                key = (vi, ti, ni)
                local_index = vertex_key_to_local.get(key)
                if local_index is None:
                    local_index = len(local_verts)
                    vertex_key_to_local[key] = local_index
                    local_verts.append(
                        all_verts[vi] if 0 <= vi < len(all_verts) else (0.0, 0.0, 0.0)
                    )
                    local_uvs.append(
                        all_uvs[ti] if 0 <= ti < len(all_uvs) else (0.0, 0.0)
                    )
                    local_normals.append(
                        all_normals[ni] if 0 <= ni < len(all_normals) else (0.0, 1.0, 0.0)
                    )
                    if sidecar_source_map and 0 <= vi < len(sidecar_source_map):
                        local_source_vertex_map.append(sidecar_source_map[vi])
                local_face.append(local_index)
            if len(local_face) == 3:
                local_faces.append(tuple(local_face))

        return SubMesh(
            name=sm_data["name"],
            material=sm_data["material"],
            texture=_normalize_obj_sidecar_texture_name(sidecar_entry) or material_texture_map.get(sm_data["material"], ""),
            vertices=local_verts,
            uvs=local_uvs if len(local_uvs) == len(local_verts) else [],
            normals=local_normals if len(local_normals) == len(local_verts) else [],
            faces=local_faces,
            source_vertex_map=(
                local_source_vertex_map if len(local_source_vertex_map) == len(local_verts) else []
            ),
            vertex_count=len(local_verts),
            face_count=len(local_faces),
        )

    # Build vertex ranges from the OBJ structure:
    # Vertices between successive 'o' markers belong to that submesh
    # Re-parse to find vertex counts per submesh
    sm_vert_counts = []
    sm_uv_counts = []
    sm_normal_counts = []
    current_v = current_vt = current_vn = 0

    if saw_object_markers:
        with open(obj_path, "r", encoding="utf-8") as f:
            in_submesh = False
            for line in f:
                line = line.strip()
                if line.startswith("o ") or line.startswith("g "):
                    if in_submesh:
                        sm_vert_counts.append(current_v)
                        sm_uv_counts.append(current_vt)
                        sm_normal_counts.append(current_vn)
                    current_v = current_vt = current_vn = 0
                    in_submesh = True
                elif line.startswith("v ") and not line.startswith("vt") and not line.startswith("vn"):
                    current_v += 1
                elif line.startswith("vt "):
                    current_vt += 1
                elif line.startswith("vn "):
                    current_vn += 1
            if in_submesh:
                sm_vert_counts.append(current_v)
                sm_uv_counts.append(current_vt)
                sm_normal_counts.append(current_vn)

    # Now build each submesh using the FULL vertex range (not just face-referenced).
    # Blender may remap/deduplicate vt/vn indices independently from position indices,
    # so we must honor the face-level vi/ti/ni tuples instead of assuming vi==ti==ni.
    v_offset = 0
    vt_offset = 0
    vn_offset = 0

    for si, sm_data in enumerate(submesh_list):
        matched_sidecar_entry = matched_sidecar_entries[si] if si < len(matched_sidecar_entries) else None
        if not saw_object_markers or si >= len(sm_vert_counts):
            submeshes.append(_build_generic_submesh(sm_data, sidecar_entry=matched_sidecar_entry))
            continue

        nv = sm_vert_counts[si] if si < len(sm_vert_counts) else 0
        nvt = sm_uv_counts[si] if si < len(sm_uv_counts) else 0
        nvn = sm_normal_counts[si] if si < len(sm_normal_counts) else 0

        if nv <= 0:
            submeshes.append(_build_generic_submesh(sm_data, sidecar_entry=matched_sidecar_entry))
            continue

        # Preserve the original exported vertex slots, including any unused vertices,
        # then split only when the same position is referenced with multiple UV/normal
        # pairs after Blender re-export.
        base_verts = [
            all_verts[v_offset + i] if (v_offset + i) < len(all_verts) else (0.0, 0.0, 0.0)
            for i in range(nv)
        ]
        base_uvs = [
            all_uvs[vt_offset + i] if i < nvt and (vt_offset + i) < len(all_uvs) else (0.0, 0.0)
            for i in range(nv)
        ]
        base_normals = [
            all_normals[vn_offset + i] if i < nvn and (vn_offset + i) < len(all_normals) else (0.0, 1.0, 0.0)
            for i in range(nv)
        ]

        local_verts = list(base_verts)
        local_uvs = list(base_uvs)
        local_normals = list(base_normals)
        local_source_vertex_map = _normalize_obj_sidecar_source_vertex_map(
            matched_sidecar_entry,
            expected_count=nv,
        )

        assigned_uvs: list[tuple[float, float] | None] = [None] * nv
        assigned_normals: list[tuple[float, float, float] | None] = [None] * nv
        split_vertex_map: dict[tuple[int, int, int], int] = {}

        def _resolve_corner_index(vi: int, ti: int, ni: int) -> int:
            local_vi = vi - v_offset
            if not (0 <= local_vi < nv):
                return 0

            local_ti = ti - vt_offset if ti >= 0 else -1
            local_ni = ni - vn_offset if ni >= 0 else -1
            key = (local_vi, local_ti, local_ni)
            existing_idx = split_vertex_map.get(key)
            if existing_idx is not None:
                return existing_idx

            uv_value = (
                all_uvs[ti]
                if 0 <= ti < len(all_uvs)
                else (base_uvs[local_vi] if local_vi < len(base_uvs) else (0.0, 0.0))
            )
            normal_value = (
                all_normals[ni]
                if 0 <= ni < len(all_normals)
                else (base_normals[local_vi] if local_vi < len(base_normals) else (0.0, 1.0, 0.0))
            )

            current_uv = assigned_uvs[local_vi]
            current_normal = assigned_normals[local_vi]
            if current_uv is None and current_normal is None:
                assigned_uvs[local_vi] = uv_value
                assigned_normals[local_vi] = normal_value
                local_uvs[local_vi] = uv_value
                local_normals[local_vi] = normal_value
                split_vertex_map[key] = local_vi
                return local_vi

            if current_uv == uv_value and current_normal == normal_value:
                split_vertex_map[key] = local_vi
                return local_vi

            clone_idx = len(local_verts)
            local_verts.append(base_verts[local_vi])
            local_uvs.append(uv_value)
            local_normals.append(normal_value)
            if local_source_vertex_map and local_vi < len(local_source_vertex_map):
                local_source_vertex_map.append(local_source_vertex_map[local_vi])
            split_vertex_map[key] = clone_idx
            return clone_idx

        local_faces = []
        for face in sm_data["faces_global"]:
            local_face = []
            for vi, ti, ni in face:
                local_face.append(_resolve_corner_index(vi, ti, ni))
            if len(local_face) == 3:
                local_faces.append(tuple(local_face))

        sm = SubMesh(
            name=sm_data["name"],
            material=sm_data["material"],
            texture=_normalize_obj_sidecar_texture_name(matched_sidecar_entry) or material_texture_map.get(sm_data["material"], ""),
            vertices=local_verts,
            uvs=local_uvs if len(local_uvs) == len(local_verts) else [],
            normals=local_normals if len(local_normals) == len(local_verts) else [],
            faces=local_faces,
            source_vertex_map=(
                local_source_vertex_map if len(local_source_vertex_map) == len(local_verts) else []
            ),
            vertex_count=len(local_verts),
            face_count=len(local_faces),
        )
        submeshes.append(sm)

        v_offset += nv
        vt_offset += nvt
        vn_offset += nvn

    result = ParsedMesh(
        path=source_path,
        format=source_format,
        submeshes=submeshes,
        total_vertices=sum(len(s.vertices) for s in submeshes),
        total_faces=sum(len(s.faces) for s in submeshes),
        has_uvs=any(s.uvs for s in submeshes),
    )

    if result.submeshes:
        all_v = [v for s in submeshes for v in s.vertices]
        if all_v:
            xs, ys, zs = zip(*all_v)
            result.bbox_min = (min(xs), min(ys), min(zs))
            result.bbox_max = (max(xs), max(ys), max(zs))

    logger.info("Imported OBJ %s: %d submeshes, %d verts, %d faces, source=%s (%s)",
                obj_path, len(submeshes), result.total_vertices,
                result.total_faces, source_path, source_format)
    return result
