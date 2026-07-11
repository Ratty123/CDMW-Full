from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_flat_havok_objects',
    '_hkx_xml_add_havok_packfile',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_havok_view(root, document):
    havok_xml_view = document.get("havok_xml_view")
    if not isinstance(havok_xml_view, Mapping):
        return
    view_element = ET.SubElement(
        root,
        "havokXmlView",
        {
            "format": str(havok_xml_view.get("format") or ""),
            "official_havok_xml": "true" if bool(havok_xml_view.get("official_havok_xml")) else "false",
            "sdk_version": str(havok_xml_view.get("sdk_version") or ""),
            "object_count": _hkx_xml_scalar(havok_xml_view.get("object_count")),
            "exported_object_count": _hkx_xml_scalar(havok_xml_view.get("exported_object_count")),
            "truncated_objects": _hkx_xml_scalar(havok_xml_view.get("truncated_objects")),
            "imported": "false",
        },
    )
    _hkx_xml_add_text(view_element, "description", havok_xml_view.get("description", ""))
    root_recovery = havok_xml_view.get("root_recovery")
    if isinstance(root_recovery, Mapping):
        root_recovery_element = ET.SubElement(
            view_element,
            "rootObjectRecovery",
            {
                "toplevelobject": str(root_recovery.get("toplevelobject") or ""),
                "class": str(root_recovery.get("class") or ""),
                "method": str(root_recovery.get("method") or ""),
                "confidence": str(root_recovery.get("confidence") or ""),
                "named_variant_count": _hkx_xml_scalar(root_recovery.get("named_variant_count")),
                "description": str(root_recovery.get("description") or ""),
            },
        )
        named_variants = root_recovery.get("named_variants")
        if isinstance(named_variants, list):
            for variant in named_variants:
                if isinstance(variant, Mapping):
                    ET.SubElement(
                        root_recovery_element,
                        "namedVariant",
                        {
                            "record": str(variant.get("record") or ""),
                            "name": str(variant.get("name") or ""),
                            "className": str(variant.get("className") or ""),
                            "class_reference_target": str(variant.get("class_reference_target") or ""),
                            "variant": str(variant.get("variant") or ""),
                            "variant_class": str(variant.get("variant_class") or ""),
                            "confidence": str(variant.get("confidence") or ""),
                        },
                    )
    hkobjects = havok_xml_view.get("hkobjects")
    hkpackfile_view = havok_xml_view.get("hkpackfile_view")
    _hkx_xml_add_havok_packfile(view_element, havok_xml_view, hkobjects, hkpackfile_view)
    _hkx_xml_add_flat_havok_objects(view_element, hkobjects)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_descriptor_hint(hints_element, hint):
    hint_element = ET.SubElement(
        hints_element,
        "descriptor",
        {
            "path": str(hint.get("path") or ""),
            "stem": str(hint.get("stem") or ""),
            "root_tag": str(hint.get("root_tag") or ""),
            "body_desc_count": _hkx_xml_scalar(hint.get("body_desc_count")),
            "constraint_desc_count": _hkx_xml_scalar(hint.get("constraint_desc_count")),
            "shape_desc_count": _hkx_xml_scalar(hint.get("shape_desc_count")),
        },
    )
    _hkx_xml_add_text(hint_element, "description", hint.get("description", ""))
    for list_key, tag_name in (
        ("body_names", "body"),
        ("socket_names", "socket"),
        ("fixed_socket_names", "fixedSocket"),
        ("physics_material_names", "physicsMaterial"),
    ):
        values = hint.get(list_key)
        if not isinstance(values, list) or not values:
            continue
        group_element = ET.SubElement(hint_element, list_key)
        for value in values:
            ET.SubElement(group_element, tag_name, {"name": str(value)})
    numeric_hints = hint.get("numeric_hints")
    if isinstance(numeric_hints, list) and numeric_hints:
        numeric_element = ET.SubElement(hint_element, "numericHints")
        for numeric_hint in numeric_hints:
            if not isinstance(numeric_hint, Mapping):
                continue
            numeric_hint_element = ET.SubElement(
                numeric_element,
                "hint",
                {
                    "name": str(numeric_hint.get("name") or ""),
                    "description": str(numeric_hint.get("description") or ""),
                },
            )
            values = numeric_hint.get("values")
            if isinstance(values, list):
                for value in values:
                    _hkx_xml_add_text(numeric_hint_element, "value", value)
    body_descriptors = hint.get("body_descriptors")
    if isinstance(body_descriptors, list) and body_descriptors:
        bodies_element = ET.SubElement(hint_element, "bodyDescriptors")
        for body in body_descriptors:
            if not isinstance(body, Mapping):
                continue
            body_element = ET.SubElement(
                bodies_element,
                "body",
                {
                    "index": _hkx_xml_scalar(body.get("index")),
                    "tag": str(body.get("tag") or ""),
                    "body_name": str(body.get("body_name") or ""),
                    "socket_name": str(body.get("socket_name") or ""),
                    "fixed_socket_name": str(body.get("fixed_socket_name") or ""),
                    "physics_material_name": str(body.get("physics_material_name") or ""),
                },
            )
            numeric = body.get("numeric_hints")
            if isinstance(numeric, list) and numeric:
                numeric_element = ET.SubElement(body_element, "numericHints")
                for numeric_hint in numeric:
                    if isinstance(numeric_hint, Mapping):
                        ET.SubElement(
                            numeric_element,
                            "hint",
                            {
                                "name": str(numeric_hint.get("name") or ""),
                                "value": str(numeric_hint.get("value") or ""),
                                "description": str(numeric_hint.get("description") or ""),
                            },
                        )
            shapes = body.get("shape_descriptors")
            if isinstance(shapes, list) and shapes:
                shapes_element = ET.SubElement(body_element, "shapeDescriptors")
                for shape in shapes:
                    if not isinstance(shape, Mapping):
                        continue
                    shape_element = ET.SubElement(
                        shapes_element,
                        "shape",
                        {
                            "index": _hkx_xml_scalar(shape.get("index")),
                            "tag": str(shape.get("tag") or ""),
                            "shape_kind": str(shape.get("shape_kind") or ""),
                        },
                    )
                    numeric = shape.get("numeric_hints")
                    if isinstance(numeric, list) and numeric:
                        numeric_element = ET.SubElement(shape_element, "numericHints")
                        for numeric_hint in numeric:
                            if isinstance(numeric_hint, Mapping):
                                ET.SubElement(
                                    numeric_element,
                                    "hint",
                                    {
                                        "name": str(numeric_hint.get("name") or ""),
                                        "value": str(numeric_hint.get("value") or ""),
                                        "description": str(numeric_hint.get("description") or ""),
                                    },
                                )
    constraint_descriptors = hint.get("constraint_descriptors")
    if isinstance(constraint_descriptors, list) and constraint_descriptors:
        constraints_element = ET.SubElement(hint_element, "constraintDescriptors")
        for constraint in constraint_descriptors:
            if not isinstance(constraint, Mapping):
                continue
            constraint_element = ET.SubElement(
                constraints_element,
                "constraint",
                {
                    "index": _hkx_xml_scalar(constraint.get("index")),
                    "tag": str(constraint.get("tag") or ""),
                    "body_name": str(constraint.get("body_name") or ""),
                    "socket_name": str(constraint.get("socket_name") or ""),
                    "fixed_socket_name": str(constraint.get("fixed_socket_name") or ""),
                },
            )
            numeric = constraint.get("numeric_hints")
            if isinstance(numeric, list) and numeric:
                numeric_element = ET.SubElement(constraint_element, "numericHints")
                for numeric_hint in numeric:
                    if isinstance(numeric_hint, Mapping):
                        ET.SubElement(
                            numeric_element,
                            "hint",
                            {
                                "name": str(numeric_hint.get("name") or ""),
                                "value": str(numeric_hint.get("value") or ""),
                                "description": str(numeric_hint.get("description") or ""),
                            },
                        )


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_descriptor_hint',
)
def _hkx_xml_add_companion_descriptor_hints(root, document):
    descriptor_hints = document.get("companion_descriptor_hints")
    if not (isinstance(descriptor_hints, list) and descriptor_hints):
        return
    hints_element = ET.SubElement(
        root,
        "companionDescriptorHints",
        {
            "status": "read_only_context",
            "imported": "false",
            "description": (
                "Referenced physics descriptor XML hints. These labels and values help interpret HKX bodies, "
                "constraints, shapes, damping, and limits; the HKX importer ignores this section."
            ),
        },
    )
    for hint in descriptor_hints:
        if isinstance(hint, Mapping):
            _hkx_xml_add_descriptor_hint(hints_element, hint)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_add_value_layout',
    '_hkx_xml_add_vector',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_shape_metadata(shapes_element, shape):
    editable_fields = shape.get("editable_fields")
    shape_attrs = {
        "index": shape.get("index"),
        "shape_type": shape.get("shape_type"),
        "shape_record_index": shape.get("shape_record_index"),
        "editable_fields": " ".join(str(field) for field in editable_fields)
        if isinstance(editable_fields, list)
        else "",
    }
    shape_element = ET.SubElement(
        shapes_element,
        "shape",
        {key: _hkx_xml_scalar(value) for key, value in shape_attrs.items() if value not in (None, "")},
    )
    shape_descriptions = shape.get("descriptions")
    if isinstance(shape_descriptions, Mapping):
        descriptions_element = ET.SubElement(shape_element, "descriptions")
        for field_name, description in shape_descriptions.items():
            _hkx_xml_add_text(descriptions_element, "field", description, name=str(field_name))
    name_hint = shape.get("name_hint")
    if isinstance(name_hint, Mapping):
        hint_element = ET.SubElement(
            shape_element,
            "name_hint",
            {
                "name": str(name_hint.get("name") or ""),
                "source": str(name_hint.get("source") or "HavokShapeNameProperty"),
                "property_record_index": _hkx_xml_scalar(name_hint.get("property_record_index")),
                "name_record_index": _hkx_xml_scalar(name_hint.get("name_record_index")),
                "confidence": str(name_hint.get("confidence") or "experimental"),
                "imported": "false",
            },
        )
        _hkx_xml_add_text(hint_element, "description", name_hint.get("description", ""))
    body_contexts = shape.get("body_contexts")
    if isinstance(body_contexts, list) and body_contexts:
        contexts_element = ET.SubElement(shape_element, "body_contexts", {"imported": "false"})
        for context in body_contexts:
            if not isinstance(context, Mapping):
                continue
            context_element = ET.SubElement(
                contexts_element,
                "body_context",
                {
                    "body_name": str(context.get("body_name") or ""),
                    "socket_name": str(context.get("socket_name") or ""),
                    "fixed_socket_name": str(context.get("fixed_socket_name") or ""),
                    "physics_material_name": str(context.get("physics_material_name") or ""),
                    "descriptor_path": str(context.get("descriptor_path") or ""),
                    "descriptor_body_index": _hkx_xml_scalar(context.get("descriptor_body_index")),
                    "descriptor_shape_index": _hkx_xml_scalar(context.get("descriptor_shape_index")),
                    "descriptor_shape_kind": str(context.get("descriptor_shape_kind") or ""),
                    "confidence": str(context.get("confidence") or "experimental"),
                },
            )
            _hkx_xml_add_text(context_element, "description", context.get("description", ""))
    shape_layouts = shape.get("value_layouts")
    if isinstance(shape_layouts, Mapping):
        layouts_element = ET.SubElement(shape_element, "valueLayouts")
        for field_name, layout in shape_layouts.items():
            _hkx_xml_add_value_layout(layouts_element, str(field_name), layout)
    records = shape.get("records")
    if isinstance(records, Mapping):
        records_element = ET.SubElement(shape_element, "records")
        for field_name, record_index in records.items():
            ET.SubElement(records_element, "record", {"field": str(field_name), "index": _hkx_xml_scalar(record_index)})
    for vector_field in ("bounds_min", "bounds_max", "center", "extent"):
        values = shape.get(vector_field)
        if isinstance(values, list) and len(values) == 3:
            _hkx_xml_add_vector(shape_element, vector_field, values, ("x", "y", "z"))
    return shape_element, editable_fields


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_vector',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_shape_geometry(shape_element, shape, editable_fields):
    vertices = shape.get("vertices")
    if isinstance(vertices, list):
        vertices_element = ET.SubElement(shape_element, "vertices")
        for index, vertex in enumerate(vertices):
            if isinstance(vertex, list) and len(vertex) == 3:
                _hkx_xml_add_vector(vertices_element, "v", vertex, ("x", "y", "z"), index=index)
    planes = shape.get("planes")
    if isinstance(planes, list):
        planes_element = ET.SubElement(shape_element, "planes")
        for index, plane in enumerate(planes):
            if isinstance(plane, list) and len(plane) == 4:
                _hkx_xml_add_vector(planes_element, "plane", plane, ("normal_x", "normal_y", "normal_z", "distance"), index=index)
    faces = shape.get("faces")
    if isinstance(faces, list):
        faces_element = ET.SubElement(shape_element, "faces", {"read_only": "true"})
        for index, face in enumerate(faces):
            if isinstance(face, list):
                face_element = ET.SubElement(faces_element, "face", {"index": str(index)})
                face_element.text = " ".join(str(int(vertex_index)) for vertex_index in face)
    sphere_center = shape.get("sphere_center")
    if isinstance(sphere_center, list) and len(sphere_center) == 3:
        _hkx_xml_add_vector(shape_element, "sphere_center", sphere_center, ("x", "y", "z"))
    sphere_radius = shape.get("sphere_radius")
    if isinstance(sphere_radius, (int, float)):
        ET.SubElement(shape_element, "sphere_radius", {"value": _hkx_xml_scalar(float(sphere_radius))})
    capsule_radius = shape.get("capsule_radius")
    if isinstance(capsule_radius, (int, float)):
        ET.SubElement(shape_element, "capsule_radius", {"value": _hkx_xml_scalar(float(capsule_radius))})
    capsule_endpoints = shape.get("capsule_endpoints")
    if isinstance(capsule_endpoints, list):
        endpoints_element = ET.SubElement(shape_element, "capsule_endpoints")
        for index, point in enumerate(capsule_endpoints):
            if isinstance(point, list) and len(point) == 3:
                _hkx_xml_add_vector(endpoints_element, "point", point, ("x", "y", "z"), index=index)
    mass_properties = shape.get("mass_properties")
    if isinstance(mass_properties, Mapping):
        mass_attrs = {
            "status": str(mass_properties.get("status") or "experimental_fixed_size_edit"),
            "warning": str(mass_properties.get("warning") or ""),
        }
        mass_element = ET.SubElement(
            shape_element,
            "mass_properties",
            {key: value for key, value in mass_attrs.items() if value},
        )
        float_rows = mass_properties.get("float_rows")
        if isinstance(float_rows, list):
            for index, row in enumerate(float_rows):
                if isinstance(row, list) and len(row) == 4:
                    _hkx_xml_add_vector(mass_element, "row", row, ("x", "y", "z", "w"), index=index)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_shape_payload(shape_element, shape, editable_fields):
    shape_payload = shape.get("shape_payload")
    if isinstance(shape_payload, Mapping):
        payload_attrs = {
            "status": str(shape_payload.get("status") or "experimental_fixed_offset_edit"),
            "warning": str(shape_payload.get("warning") or ""),
        }
        payload_element = ET.SubElement(
            shape_element,
            "shape_payload",
            {key: value for key, value in payload_attrs.items() if value},
        )
        float_slots = shape_payload.get("float_slots")
        if isinstance(float_slots, list):
            for slot in float_slots:
                if not isinstance(slot, Mapping):
                    continue
                offset = slot.get("offset")
                value = slot.get("value")
                if not isinstance(offset, int) or not isinstance(value, (int, float)):
                    continue
                slot_attrs = {
                    "offset": _hkx_xml_scalar(offset),
                    "hex_offset": str(slot.get("hex_offset") or f"0x{offset:X}"),
                    "value": _hkx_xml_scalar(float(value)),
                }
                description = slot.get("description")
                if description:
                    slot_attrs["description"] = str(description)
                ET.SubElement(payload_element, "float", slot_attrs)
    hull_topology = shape.get("hull_topology")
    if isinstance(hull_topology, Mapping):
        topology_element = ET.SubElement(
            shape_element,
            "hull_topology",
            {
                "status": str(hull_topology.get("status") or "experimental_topology_edit"),
                "warning": str(hull_topology.get("warning") or ""),
            },
        )
        topology_descriptions = hull_topology.get("descriptions")
        if isinstance(topology_descriptions, Mapping):
            descriptions_element = ET.SubElement(topology_element, "descriptions")
            for field_name, description in topology_descriptions.items():
                _hkx_xml_add_text(descriptions_element, "field", description, name=str(field_name))
        face_records = hull_topology.get("face_records")
        if isinstance(face_records, list):
            face_records_element = ET.SubElement(topology_element, "face_records")
            for face in face_records:
                if not isinstance(face, Mapping):
                    continue
                ET.SubElement(
                    face_records_element,
                    "face",
                    {
                        "index": _hkx_xml_scalar(face.get("index")),
                        "index_start": _hkx_xml_scalar(face.get("index_start")),
                        "vertex_count": _hkx_xml_scalar(face.get("vertex_count")),
                        "meta": _hkx_xml_scalar(face.get("meta")),
                    },
                )
        face_indices = hull_topology.get("face_indices")
        if isinstance(face_indices, list):
            _hkx_xml_add_text(
                topology_element,
                "face_indices",
                " ".join(str(int(value)) for value in face_indices if isinstance(value, int)),
            )
        edge_tables = hull_topology.get("edge_tables")
        if isinstance(edge_tables, list):
            edge_tables_element = ET.SubElement(topology_element, "edge_tables")
            for table_index, table in enumerate(edge_tables):
                if not isinstance(table, Mapping):
                    continue
                table_element = ET.SubElement(
                    edge_tables_element,
                    "edge_table",
                    {
                        "index": _hkx_xml_scalar(table_index),
                        "record_index": _hkx_xml_scalar(table.get("record_index")),
                        "pair_count": _hkx_xml_scalar(table.get("pair_count")),
                    },
                )
                pairs = table.get("pairs")
                if isinstance(pairs, list):
                    for pair in pairs:
                        if not isinstance(pair, Mapping):
                            continue
                        ET.SubElement(
                            table_element,
                            "pair",
                            {
                                "index": _hkx_xml_scalar(pair.get("index")),
                                "a": _hkx_xml_scalar(pair.get("a")),
                                "b": _hkx_xml_scalar(pair.get("b")),
                            },
                        )
        face_loops = hull_topology.get("face_vertex_loops")
        if isinstance(face_loops, list):
            loops_element = ET.SubElement(topology_element, "face_vertex_loops", {"read_only": "true"})
            for index, face in enumerate(face_loops):
                if isinstance(face, list):
                    face_element = ET.SubElement(loops_element, "face", {"index": str(index)})
                    face_element.text = " ".join(str(int(vertex_index)) for vertex_index in face)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_mesh_details',
    '_hkx_xml_add_text',
    '_hkx_xml_add_vector',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_shape_summaries(shape_element, shape):
    mesh_summary = shape.get("mesh_summary")
    if isinstance(mesh_summary, Mapping):
        ET.SubElement(
            shape_element,
            "mesh_summary",
            {str(key): _hkx_xml_scalar(value) for key, value in mesh_summary.items() if value is not None},
        )
    _hkx_xml_add_mesh_details(shape_element, shape.get("mesh_details"))
    capsule_summary = shape.get("capsule_summary")
    if isinstance(capsule_summary, Mapping):
        capsule_element = ET.SubElement(
            shape_element,
            "capsule_summary",
            {
                str(key): _hkx_xml_scalar(value)
                for key, value in capsule_summary.items()
                if value is not None and key not in {"start", "end"}
            },
        )
        for point_key in ("start", "end"):
            point = capsule_summary.get(point_key)
            if isinstance(point, list) and len(point) == 3:
                _hkx_xml_add_vector(capsule_element, point_key, point, ("x", "y", "z"))
    box_summary = shape.get("box_summary")
    if isinstance(box_summary, Mapping):
        box_element = ET.SubElement(
            shape_element,
            "box_summary",
            {
                "status": str(box_summary.get("status") or "read_only_schema_recovery"),
                "confidence": str(box_summary.get("confidence") or "experimental"),
                "convex_radius_or_collision_margin": _hkx_xml_scalar(
                    box_summary.get("convex_radius_or_collision_margin")
                ),
                "aabb_or_radius_factor": _hkx_xml_scalar(box_summary.get("aabb_or_radius_factor")),
                "imported": "false",
            },
        )
        _hkx_xml_add_text(box_element, "warning", box_summary.get("warning", ""))
        for vector_key in ("center", "half_extents", "bounds_min", "bounds_max"):
            vector_value = box_summary.get(vector_key)
            if isinstance(vector_value, list) and len(vector_value) == 3:
                _hkx_xml_add_vector(box_element, vector_key, vector_value, ("x", "y", "z"))
        frame_rows = box_summary.get("local_frame_rows")
        if isinstance(frame_rows, list):
            rows_element = ET.SubElement(box_element, "local_frame_rows", {"read_only": "true"})
            for row_index, row in enumerate(frame_rows):
                if isinstance(row, list) and len(row) == 4:
                    _hkx_xml_add_vector(rows_element, "row", row, ("x", "y", "z", "w"), index=row_index)
        offset_pairs = box_summary.get("offset_count_pairs")
        if isinstance(offset_pairs, Mapping):
            pairs_element = ET.SubElement(box_element, "offset_count_pairs", {"read_only": "true"})
            for pair_name, pair in offset_pairs.items():
                if not isinstance(pair, Mapping):
                    continue
                ET.SubElement(
                    pairs_element,
                    "pair",
                    {
                        "name": str(pair_name),
                        "offset": _hkx_xml_scalar(pair.get("offset")),
                        "count": _hkx_xml_scalar(pair.get("count")),
                    },
                )
    read_only_reason = shape.get("read_only_reason")
    if read_only_reason:
        _hkx_xml_add_text(shape_element, "read_only_reason", read_only_reason)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_shape_geometry',
    '_hkx_xml_add_shape_metadata',
    '_hkx_xml_add_shape_payload',
    '_hkx_xml_add_shape_summaries',
)
def _hkx_xml_add_shapes(root, document):
    shapes_element = ET.SubElement(root, "shapes")
    shapes = document.get("shapes")
    if not isinstance(shapes, list):
        return
    for shape in shapes:
        if not isinstance(shape, Mapping):
            continue
        shape_element, editable_fields = _hkx_xml_add_shape_metadata(shapes_element, shape)
        _hkx_xml_add_shape_geometry(shape_element, shape, editable_fields)
        _hkx_xml_add_shape_payload(shape_element, shape, editable_fields)
        _hkx_xml_add_shape_summaries(shape_element, shape)
