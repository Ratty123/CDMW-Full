from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Sequence, Tuple

from cdmw.core.archive_mesh_types import MeshImportPreviewResult
from cdmw.domain.mesh.material_export_safety import material_export_safety_blockers
from cdmw.modding.mesh_parser import _find_pac_descriptors, _parse_par_sections
from cdmw.modding.pac_xml_profiles import build_pac_xml_material_authority_report, pac_xml_texture_alias_matches_parameter

from .final_package_preview_model import _material_label_for_mesh


def _dedupe(values):
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _pac_xml_normal_binding_warning(parameter_name: str, texture_path: str, *, kept_original: bool) -> str:
    if str(parameter_name or "").casefold() != "_normaltexture" or kept_original:
        return ""
    stem = PurePosixPath(str(texture_path or "").replace("\\", "/")).stem.casefold()
    normal_like = "normal" in stem or stem.endswith(("_n", "_wn", "_nm", "_nrm", "_nor", "_no"))
    normal_like = normal_like or bool(re.search(r"(?:^|[_\-.])n(?:$|[_\-.])", stem))
    if normal_like or pac_xml_texture_alias_matches_parameter(parameter_name, texture_path):
        return ""
    return f"Texture contract warning: _normalTexture points at a non-normal-looking DDS path: {texture_path}."


def _pac_xml_material_export_wrapper_rows(
    sidecars: Sequence[tuple[str, str, bool]],
) -> Tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    for sidecar_path, sidecar_text, corpus_proven in tuple(sidecars or ()):
        normalized_path = str(sidecar_path or "").replace("\\", "/").lower()
        if not normalized_path.endswith((".pac_xml", ".pac.xml")):
            continue
        try:
            report = build_pac_xml_material_authority_report(sidecar_text, sidecar_path)
        except Exception:
            continue
        parameters = (
            tuple(report.runtime_abi_parameters)
            + tuple(report.source_authority_parameters)
            + tuple(report.inherited_influence_parameters)
            + tuple(report.unknown_material_response_parameters)
        )
        for wrapper in tuple(report.wrapper_order or ()):
            wrapper_key = _material_key(wrapper.wrapper_name)
            wrapper_parameters = tuple(
                {
                    "name": parameter.parameter_name,
                    "type": parameter.parameter_type,
                    "value": parameter.texture_path or parameter.value,
                }
                for parameter in parameters
                if _material_key(parameter.wrapper_name) == wrapper_key
            )
            rows.append(
                {
                    "wrapper_name": wrapper.wrapper_name,
                    "shader_name": wrapper.shader_name,
                    "parameters": wrapper_parameters,
                    "corpus_proven": bool(corpus_proven),
                }
            )
    return tuple(rows)


def _material_export_route_rows(preview_result: MeshImportPreviewResult) -> Tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    for section in tuple(getattr(preview_result, "source_owned_output_draw_sections", ()) or ()):
        source_names = tuple(
            str(name or "").strip()
            for name in tuple(getattr(section, "atlas_source_material_names", ()) or ())
            if str(name or "").strip()
        )
        if not source_names:
            source_name = str(getattr(section, "source_material_name", "") or "").strip()
            source_names = tuple(part.strip() for part in source_name.split(" + ") if part.strip())
        target_names = tuple(
            dict.fromkeys(
                str(name or "").strip()
                for name in (
                    getattr(section, "target_submesh_name", ""),
                    getattr(section, "donor_material_name", ""),
                    getattr(section, "runtime_material_name", ""),
                    getattr(section, "runtime_slot_name", ""),
                )
                if str(name or "").strip()
            )
        )
        rows.append(
            {
                "source_material_names": source_names,
                "source_indices": tuple(getattr(section, "source_submesh_indices", ()) or ()),
                "target_wrapper_names": target_names,
            }
        )
    return tuple(rows)


def _material_export_safety_blockers(
    preview_result: MeshImportPreviewResult,
    source_materials: Sequence[Mapping[str, object]],
    sidecars: Sequence[tuple[str, str, bool]],
) -> Tuple[str, ...]:
    return material_export_safety_blockers(
        source_materials,
        _pac_xml_material_export_wrapper_rows(sidecars),
        _material_export_route_rows(preview_result),
    )


def _material_export_safety_blockers_for_specs(
    preview_result: MeshImportPreviewResult,
    source_materials: Sequence[Mapping[str, object]],
    sidecars: Sequence[tuple[str, object]],
    *,
    package_written: bool = False,
) -> Tuple[str, ...]:
    rows: list[tuple[str, str, bool]] = []
    for sidecar_path, spec in tuple(sidecars or ()):
        payload = bytes(getattr(spec, "payload_data", b"") or b"")
        if payload:
            text = payload.decode("utf-8", errors="ignore")
        else:
            source_path = getattr(spec, "source_path", None)
            try:
                text = source_path.read_text(encoding="utf-8", errors="ignore") if isinstance(source_path, Path) else ""
            except OSError:
                text = ""
        note = str(getattr(spec, "note", "") or "").casefold()
        rows.append((sidecar_path, text, bool(package_written or "original" in note)))
    return _material_export_safety_blockers(preview_result, source_materials, rows)

def _pac_xml_material_wrapper_structure_errors(sidecar_text: str, sidecar_path: str) -> Tuple[str, ...]:
    normalized_path = str(sidecar_path or "").replace("\\", "/").lower()
    if not (normalized_path.endswith(".pac_xml") or normalized_path.endswith(".pac.xml")):
        return ()
    text = str(sidecar_text or "")
    if "<ModelProperty" not in text or "<SkinnedMeshMaterialWrapper" not in text:
        return ()
    tag_pattern = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_:.-]+)\b([^>]*)>", flags=re.IGNORECASE | re.DOTALL)
    stack: List[Tuple[str, str, int]] = []
    item_ids_by_container: Dict[int, Dict[str, str]] = {}
    errors: List[str] = []
    for match in tag_pattern.finditer(text):
        is_close = bool(match.group(1))
        raw_tag = match.group(2)
        tag = raw_tag.split(":")[-1]
        attrs = match.group(3) or ""
        if is_close:
            normalized_tag = tag.lower()
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0].lower() == normalized_tag:
                    del stack[index:]
                    break
            continue
        self_closing = attrs.rstrip().endswith("/")
        if tag.lower() == "skinnedmeshmaterialwrapper":
            name_match = re.search(
                r'(?:_subMeshName|subMeshName|SubMeshName|Name|name)="([^"]+)"',
                attrs,
                flags=re.IGNORECASE,
            )
            wrapper_name = str(name_match.group(1) if name_match else "unnamed wrapper").strip()
            submesh_vector = next(
                (
                    ancestor
                    for ancestor in reversed(stack)
                    if ancestor[0].lower() == "vector"
                    and re.search(
                        r'\b(?:Name|name|_name)="_subMeshResources"',
                        ancestor[1],
                        flags=re.IGNORECASE,
                    )
                ),
                None,
            )
            if submesh_vector is None:
                errors.append(
                    f"{wrapper_name} wrapper was emitted outside _subMeshResources in {PurePosixPath(sidecar_path).name}."
                )
            else:
                item_match = re.search(r'\bItemID="(\d+)"', attrs, flags=re.IGNORECASE)
                if item_match is not None:
                    item_id = item_match.group(1)
                    by_id = item_ids_by_container.setdefault(submesh_vector[2], {})
                    previous = by_id.get(item_id)
                    if previous is not None:
                        errors.append(
                            f"{wrapper_name} duplicates SkinnedMeshMaterialWrapper ItemID {item_id} with {previous} "
                            f"inside _subMeshResources in {PurePosixPath(sidecar_path).name}."
                        )
                    else:
                        by_id[item_id] = wrapper_name
        if not self_closing:
            stack.append((tag, attrs, match.start()))
    wrapper_pattern = re.compile(
        r"<SkinnedMeshMaterialWrapper\b(?P<attrs>[^>]*)>(?P<body>.*?)</SkinnedMeshMaterialWrapper>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    parameter_pattern = re.compile(
        r"<MaterialParameter[A-Za-z0-9_:.-]*\b(?P<attrs>[^>]*)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for wrapper_match in wrapper_pattern.finditer(text):
        wrapper_attrs = wrapper_match.group("attrs") or ""
        name_match = re.search(
            r'(?:_subMeshName|subMeshName|SubMeshName|Name|name)="([^"]+)"',
            wrapper_attrs,
            flags=re.IGNORECASE,
        )
        wrapper_name = str(name_match.group(1) if name_match else "unnamed wrapper").strip()
        parameter_names_by_item_id: Dict[str, str] = {}
        for parameter_match in parameter_pattern.finditer(wrapper_match.group("body") or ""):
            parameter_attrs = parameter_match.group("attrs") or ""
            item_match = re.search(r'\bItemID="(\d+)"', parameter_attrs, flags=re.IGNORECASE)
            if item_match is None:
                continue
            parameter_name_match = re.search(
                r'(?:StringItemID|_name|Name|name)="([^"]+)"',
                parameter_attrs,
                flags=re.IGNORECASE,
            )
            parameter_name = str(parameter_name_match.group(1) if parameter_name_match else "unnamed parameter").strip()
            item_id = item_match.group(1)
            previous = parameter_names_by_item_id.get(item_id)
            if previous is not None and previous != parameter_name:
                errors.append(
                    f"{wrapper_name} duplicates material parameter ItemID {item_id} for {previous} and {parameter_name} "
                    f"in {PurePosixPath(sidecar_path).name}."
                )
            else:
                parameter_names_by_item_id[item_id] = parameter_name
    return tuple(_dedupe(errors))


def _pac_xml_submesh_resource_wrapper_names(sidecar_text: str, sidecar_path: str) -> Tuple[str, ...]:
    normalized_path = str(sidecar_path or "").replace("\\", "/").lower()
    if not (normalized_path.endswith(".pac_xml") or normalized_path.endswith(".pac.xml")):
        return ()
    text = str(sidecar_text or "")
    if "<ModelProperty" not in text or "<SkinnedMeshMaterialWrapper" not in text:
        return ()
    tag_pattern = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_:.-]+)\b([^>]*)>", flags=re.IGNORECASE | re.DOTALL)
    stack: List[Tuple[str, str, int]] = []
    names: List[str] = []
    for match in tag_pattern.finditer(text):
        is_close = bool(match.group(1))
        tag = match.group(2).split(":")[-1]
        attrs = match.group(3) or ""
        if is_close:
            normalized_tag = tag.lower()
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0].lower() == normalized_tag:
                    del stack[index:]
                    break
            continue
        self_closing = attrs.rstrip().endswith("/")
        if tag.lower() == "skinnedmeshmaterialwrapper":
            submesh_vector = next(
                (
                    ancestor
                    for ancestor in reversed(stack)
                    if ancestor[0].lower() == "vector"
                    and re.search(
                        r'\b(?:Name|name|_name)="_subMeshResources"',
                        ancestor[1],
                        flags=re.IGNORECASE,
                    )
                ),
                None,
            )
            if submesh_vector is not None:
                name_match = re.search(
                    r'(?:_subMeshName|subMeshName|SubMeshName|Name|name)="([^"]+)"',
                    attrs,
                    flags=re.IGNORECASE,
                )
                wrapper_name = str(name_match.group(1) if name_match else "").strip()
                if wrapper_name:
                    names.append(wrapper_name)
        if not self_closing:
            stack.append((tag, attrs, match.start()))
    return tuple(_dedupe(names))


def _pac_xml_material_shader_name_errors(sidecar_text: str, sidecar_path: str) -> Tuple[str, ...]:
    normalized_path = str(sidecar_path or "").replace("\\", "/").lower()
    if not (normalized_path.endswith(".pac_xml") or normalized_path.endswith(".pac.xml")):
        return ()
    errors: List[str] = []
    wrapper_pattern = re.compile(
        r"<SkinnedMeshMaterialWrapper\b(?P<attrs>[^>]*)>.*?</SkinnedMeshMaterialWrapper>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in wrapper_pattern.finditer(str(sidecar_text or "")):
        block = match.group(0)
        attrs = match.group("attrs") or ""
        name_match = re.search(
            r'(?:_subMeshName|subMeshName|SubMeshName|Name|name)="([^"]+)"',
            attrs,
            flags=re.IGNORECASE,
        )
        material_match = re.search(r'<Material\b[^>]*\b_materialName="([^"]*)"', block, flags=re.IGNORECASE | re.DOTALL)
        wrapper_name = str(name_match.group(1) if name_match else "unnamed wrapper").strip()
        material_name = str(material_match.group(1) if material_match else "").strip()
        if not material_name:
            continue
        if _material_key(material_name) == _material_key(wrapper_name):
            errors.append(
                f"{wrapper_name} material shader name is the source material label ({material_name}) in {PurePosixPath(sidecar_path).name}; "
                "complete source-owned swap must keep a game shader family such as SkinnedMeshStandard_Ver2."
            )
    return tuple(_dedupe(errors))


def _pac_xml_submesh_resource_order_errors(
    sidecar_wrapper_names: Sequence[str],
    visible_material_names: Sequence[str],
) -> Tuple[str, ...]:
    visible_names = [
        str(name or "").strip()
        for name in tuple(visible_material_names or ())
        if _material_key(name)
    ]
    if len(visible_names) <= 1:
        return ()
    visible_keys = [_material_key(name) for name in visible_names]
    visible_key_set = set(visible_keys)
    sidecar_names = [
        str(name or "").strip()
        for name in tuple(sidecar_wrapper_names or ())
        if _material_key(name) in visible_key_set
    ]
    if len(sidecar_names) < len(visible_names):
        return ()
    sidecar_names = sidecar_names[: len(visible_names)]
    sidecar_keys = [_material_key(name) for name in sidecar_names]
    if sidecar_keys == visible_keys:
        return ()
    return (
        "Complete source-owned swap PAC XML _subMeshResources wrapper order does not match rebuilt PAC draw order. "
        f"PAC: {', '.join(visible_names[:8])}; sidecar: {', '.join(sidecar_names[:8])}."
        + (" ..." if len(visible_names) > 8 else ""),
    )


def _pac_xml_submesh_resource_idbase_errors(sidecar_text: str, sidecar_path: str) -> Tuple[str, ...]:
    normalized_path = str(sidecar_path or "").replace("\\", "/").lower()
    if not (normalized_path.endswith(".pac_xml") or normalized_path.endswith(".pac.xml")):
        return ()
    text = str(sidecar_text or "")
    errors: List[str] = []
    tag_pattern = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_:.-]+)\b([^>]*)>", flags=re.IGNORECASE | re.DOTALL)
    stack: List[Tuple[str, bool, int, int, str]] = []

    def validate_vector(attrs: str, body: str) -> None:
        item_ids: List[int] = []
        for item_match in re.finditer(r"<SkinnedMeshMaterialWrapper\b[^>]*\bItemID=\"(\d+)\"", body, flags=re.IGNORECASE | re.DOTALL):
            try:
                item_ids.append(int(item_match.group(1)))
            except ValueError:
                continue
        if not item_ids:
            return
        idbase_match = re.search(r'\bIdBase="(\d+)"', attrs, flags=re.IGNORECASE)
        if idbase_match is None:
            errors.append(
                f"_subMeshResources in {PurePosixPath(sidecar_path).name} has material wrapper ItemID(s) but no IdBase."
            )
            return
        try:
            idbase = int(idbase_match.group(1))
        except ValueError:
            idbase = -1
        required = max(item_ids)
        if idbase < required:
            errors.append(
                f"_subMeshResources IdBase {idbase} is lower than source-owned material wrapper ItemID {required} in {PurePosixPath(sidecar_path).name}."
            )

    for match in tag_pattern.finditer(text):
        is_close = bool(match.group(1))
        tag = match.group(2).split(":")[-1].lower()
        attrs = match.group(3) or ""
        if is_close:
            for index in range(len(stack) - 1, -1, -1):
                open_tag, is_target, _start, open_end, open_attrs = stack[index]
                if open_tag.lower() != tag:
                    continue
                del stack[index:]
                if is_target:
                    validate_vector(open_attrs, text[open_end:match.start()])
                break
            continue
        if attrs.rstrip().endswith("/"):
            continue
        is_target = (
            tag == "vector"
            and re.search(r'\b(?:Name|name|_name)="_subMeshResources"', attrs, flags=re.IGNORECASE) is not None
        )
        stack.append((tag, is_target, match.start(), match.end(), attrs))
    return tuple(_dedupe(errors))


def _pac_runtime_abi_preflight_errors(
    rebuilt_data: bytes,
    preview_result: MeshImportPreviewResult,
) -> Tuple[str, ...]:
    data = bytes(rebuilt_data or b"")
    parsed_mesh = getattr(preview_result, "parsed_mesh", None)
    if not data or data[:4] != b"PAR " or not str(getattr(parsed_mesh, "format", "") or "").lower() == "pac":
        return ()
    planned_sections = tuple(getattr(preview_result, "source_owned_output_draw_sections", ()) or ())
    if not planned_sections:
        return ()
    try:
        sections = _parse_par_sections(data)
        sec0 = next((section for section in sections if int(section.get("index", -1)) == 0), None)
        if not sec0:
            return ("Complete source-owned swap PAC runtime ABI validation failed: section 0 is missing.",)
        n_lods = data[int(sec0["offset"]) + 4] if int(sec0["size"]) >= 5 else 0
        descriptors = _find_pac_descriptors(data, int(sec0["offset"]), int(sec0["size"]), n_lods)
    except Exception as exc:
        return (f"Complete source-owned swap PAC runtime ABI validation failed: {exc}",)

    errors: List[str] = []
    if len(descriptors) != len(planned_sections):
        errors.append(
            "Complete source-owned swap PAC runtime ABI changed descriptor count: "
            f"{len(descriptors):,} descriptor(s), expected {len(planned_sections):,} original runtime slot(s)."
        )

    total_vertices = int(getattr(parsed_mesh, "total_vertices", 0) or 0)
    if total_vertices > 1000 and int(sec0.get("size", 0) or 0) < 1024:
        errors.append(
            "Complete source-owned swap PAC runtime ABI has a suspiciously small section 0 "
            f"({int(sec0.get('size', 0) or 0):,} bytes); original descriptor/metadata tail was likely rebuilt instead of preserved."
        )

    for index, (desc, planned) in enumerate(zip(descriptors, planned_sections)):
        expected_name = str(getattr(planned, "runtime_slot_name", "") or "").strip()
        expected_material = str(getattr(planned, "runtime_material_name", "") or "").strip()
        if expected_name and _material_key(getattr(desc, "name", "")) != _material_key(expected_name):
            errors.append(
                f"Complete source-owned swap PAC runtime ABI changed draw slot {index} name: "
                f"{getattr(desc, 'name', '')} != {expected_name}."
            )
        if expected_material and _material_key(getattr(desc, "material", "")) != _material_key(expected_material):
            errors.append(
                f"Complete source-owned swap PAC runtime ABI changed draw slot {index} material: "
                f"{getattr(desc, 'material', '')} != {expected_material}."
            )
        vertex_counts = [int(value or 0) for value in tuple(getattr(desc, "vertex_counts", ()) or ())]
        index_counts = [int(value or 0) for value in tuple(getattr(desc, "index_counts", ()) or ())]
        active_vertex_counts = [value for value in vertex_counts[: int(getattr(desc, "stored_lod_count", 0) or 0)] if value > 0]
        active_index_counts = [value for value in index_counts[: int(getattr(desc, "stored_lod_count", 0) or 0)] if value > 0]
        if len(active_vertex_counts) > 1 and any(active_vertex_counts[i] > active_vertex_counts[i - 1] for i in range(1, len(active_vertex_counts))):
            errors.append(f"Complete source-owned swap PAC draw slot {index} has non-monotonic LOD vertex counts: {active_vertex_counts}.")
        if len(active_index_counts) > 1 and any(active_index_counts[i] > active_index_counts[i - 1] for i in range(1, len(active_index_counts))):
            errors.append(f"Complete source-owned swap PAC draw slot {index} has non-monotonic LOD index counts: {active_index_counts}.")
        if (
            len(active_vertex_counts) > 1
            and len(set(active_vertex_counts)) == 1
            and len(active_index_counts) > 1
            and len(set(active_index_counts)) == 1
            and active_vertex_counts[0] > 8
            and active_index_counts[0] > 24
        ):
            errors.append(
                f"Complete source-owned swap PAC draw slot {index} duplicates full LOD geometry across all LODs "
                f"({active_vertex_counts[0]:,} vertices, {active_index_counts[0]:,} indices)."
            )
    return tuple(_dedupe(errors))


def _material_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _material_loose_key(value: object) -> str:
    key = _material_key(value)
    return re.sub(r"\d+", lambda match: str(int(match.group(0) or "0")), key)


def _binding_material_name(binding: object) -> str:
    return (
        str(getattr(binding, "material_name", "") or "").strip()
        or str(getattr(binding, "part_name", "") or "").strip()
        or str(getattr(binding, "submesh_name", "") or "").strip()
        or "Material"
    )


def _candidate_mesh_indices(
    preview_model: ModelPreviewData,
    binding: object,
    *,
    allow_single_mesh_fallback: bool = True,
) -> Tuple[int, ...]:
    meshes = list(getattr(preview_model, "meshes", []) or [])
    if not meshes:
        return ()
    binding_candidates = [
        _material_key(getattr(binding, attribute_name, ""))
        for attribute_name in ("material_name", "part_name", "submesh_name")
    ]
    binding_candidates = [candidate for candidate in binding_candidates if candidate]
    matched: List[int] = []
    if binding_candidates:
        for index, mesh in enumerate(meshes):
            mesh_candidates = [
                _material_key(getattr(mesh, attribute_name, ""))
                for attribute_name in ("material_name", "texture_name")
            ]
            if any(candidate and candidate in mesh_candidates for candidate in binding_candidates):
                matched.append(index)
    if matched:
        return tuple(matched)
    loose_binding_candidates = {
        _material_loose_key(getattr(binding, attribute_name, ""))
        for attribute_name in ("material_name", "part_name", "submesh_name")
        if _material_loose_key(getattr(binding, attribute_name, ""))
    }
    if loose_binding_candidates:
        for index, mesh in enumerate(meshes):
            loose_mesh_candidates = {
                _material_loose_key(getattr(mesh, attribute_name, ""))
                for attribute_name in ("material_name", "texture_name")
                if _material_loose_key(getattr(mesh, attribute_name, ""))
            }
            if loose_binding_candidates & loose_mesh_candidates:
                matched.append(index)
    if matched:
        return tuple(matched)
    if allow_single_mesh_fallback and len(meshes) == 1:
        return (0,)
    return ()
