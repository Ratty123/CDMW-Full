from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_hkx_layout_field',
    'struct',
)
def _hkx_record_layout_fields_0(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name.startswith('hkArray') and len(payload) >= 16:
        data_reference = struct.unpack_from("<Q", payload, 0)[0]
        size_value = struct.unpack_from("<I", payload, 8)[0]
        capacity_and_flags = struct.unpack_from("<I", payload, 12)[0]
        fields.extend(
            [
                _hkx_layout_field(
                    name="data_reference_or_offset",
                    offset=0,
                    size=8,
                    data_type="uint64/reference",
                    value={"raw_u64": data_reference, "low_u32": data_reference & 0xFFFFFFFF},
                    description="Likely Havok array data reference or offset. Exact 2024.2 reference encoding is still unconfirmed.",
                    confidence="experimental",
                    editable=False,
                ),
                _hkx_layout_field(
                    name="size",
                    offset=8,
                    size=4,
                    data_type="uint32",
                    value=size_value,
                    description="Likely current array element count.",
                    confidence="experimental",
                    editable=False,
                ),
                _hkx_layout_field(
                    name="capacity_and_flags",
                    offset=12,
                    size=4,
                    data_type="uint32",
                    value=capacity_and_flags,
                    description="Likely Havok array capacity and flags word. Rebuilding this safely is not supported yet.",
                    confidence="experimental",
                    editable=False,
                ),
            ]
        )
        return True
    elif type_name.startswith('hkRefPtr') and len(payload) >= 8:
        raw_reference = struct.unpack_from("<Q", payload, 0)[0]
        fields.append(
            _hkx_layout_field(
                name="referenced_object",
                offset=0,
                size=8,
                data_type="uint64/reference",
                value={"raw_u64": raw_reference, "low_u32": raw_reference & 0xFFFFFFFF},
                description="Likely Havok reference pointer payload. Target is shown separately when the value matches an ITEM record offset.",
                confidence="experimental",
                editable=False,
            )
        )
        return True
    elif type_name == 'hkFloat3' and record.count > 0 and (len(payload) >= record.count * 12):
        fields.append(
            _hkx_layout_field(
                name="float3_rows",
                offset=0,
                size=record.count * 12,
                data_type="float32[3][]",
                value={"row_count": record.count, "stride": 12},
                description="Local-space vector rows. For decoded convex shapes these are usually vertices.",
                confidence="strong inference",
                editable=True,
            )
        )
        return True
    elif type_name == 'hkVector4' and record.count > 0 and (len(payload) >= record.count * 16):
        fields.append(
            _hkx_layout_field(
                name="float4_rows",
                offset=0,
                size=record.count * 16,
                data_type="float32[4][]",
                value={"row_count": record.count, "stride": 16},
                description="Four-float vector rows. For decoded convex shapes these are usually plane equations.",
                confidence="strong inference",
                editable=True,
            )
        )
        return True
    elif type_name == 'hkQsTransform' and record.count > 0 and (len(payload) >= record.count * 48):
        transform_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 128)):
            base = item_index * transform_stride
            if base + 48 > len(payload):
                break
            translation = [float(value) for value in struct.unpack_from("<ffff", payload, base)]
            rotation = [float(value) for value in struct.unpack_from("<ffff", payload, base + 16)]
            scale = [float(value) for value in struct.unpack_from("<ffff", payload, base + 32)]
            fields.append(
                _hkx_layout_field(
                    name=f"qs_transform[{item_index}]",
                    offset=base,
                    size=48,
                    data_type="struct{hkVector4 translation; hkQuaternion rotation; hkVector4 scale}",
                    value={"translation": translation, "rotation": rotation, "scale": scale},
                    description=(
                        "Read-only hkQsTransform row. Usually skeleton pose or mapping data: translation, quaternion-like "
                        "rotation, and scale. Editing requires skeleton schema validation and is not enabled."
                    ),
                    confidence="strong inference",
                    editable=False,
                )
            )
        return True
    return False


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_HKX_ENUM_RECORD_TYPES',
    '_HKX_SCALAR_ARRAY_TYPES',
    '_hkx_enum_record_values',
    '_hkx_layout_field',
    '_hkx_scalar_array_values',
    'struct',
)
def _hkx_record_layout_fields_1(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name == 'hkMatrix4' and record.count > 0 and (len(payload) >= record.count * 64):
        matrix_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 64)):
            base = item_index * matrix_stride
            if base + 64 > len(payload):
                break
            rows = [
                [float(value) for value in struct.unpack_from("<ffff", payload, base + row_index * 16)]
                for row_index in range(4)
            ]
            fields.append(
                _hkx_layout_field(
                    name=f"matrix4[{item_index}]",
                    offset=base,
                    size=64,
                    data_type="float32[4][4]",
                    value={"rows": rows},
                    description=(
                        "Read-only hkMatrix4 row. Corpus scans show these in hkx mesh/scene metadata; editing "
                        "requires owner-specific transform semantics and is disabled."
                    ),
                    confidence="strong inference",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hkBone' and record.count > 0 and (len(payload) >= record.count * 16):
        bone_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 256)):
            base = item_index * bone_stride
            if base + 16 > len(payload):
                break
            name_ref = struct.unpack_from("<I", payload, base)[0]
            parent_or_lock = struct.unpack_from("<i", payload, base + 8)[0]
            flags_or_axis = struct.unpack_from("<I", payload, base + 12)[0]
            fields.append(
                _hkx_layout_field(
                    name=f"bone[{item_index}]",
                    offset=base,
                    size=bone_stride,
                    data_type="uint32 name_ref; int32 parent_or_lock; uint32 flags",
                    value={
                        "name_reference": name_ref,
                        "parent_or_lock": parent_or_lock,
                        "flags_or_axis": flags_or_axis,
                    },
                    description=(
                        "Read-only hkBone row. The first word commonly references a char/name record; later words likely "
                        "include parent/lock/axis metadata. Skeleton rebuilding is not supported."
                    ),
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hkInt16' and record.count > 0 and (len(payload) >= record.count * 2):
        values = [int(struct.unpack_from("<h", payload, index * 2)[0]) for index in range(min(int(record.count), 512))]
        fields.append(
            _hkx_layout_field(
                name="int16_values",
                offset=0,
                size=min(len(payload), int(record.count) * 2),
                data_type="int16[]",
                value={"values": values, "value_count": int(record.count), "truncated": max(0, int(record.count) - len(values))},
                description="Read-only hkInt16 array. In skeleton files this often stores parent indices or compact index maps.",
                confidence="experimental",
                editable=False,
            )
        )
        return True
    elif type_name in _HKX_SCALAR_ARRAY_TYPES and record.count > 0:
        scalar_values = _hkx_scalar_array_values(payload, record)
        if scalar_values:
            field_name, data_type, _fmt, byte_width, description = _HKX_SCALAR_ARRAY_TYPES[type_name]
            fields.append(
                _hkx_layout_field(
                    name=field_name,
                    offset=0,
                    size=min(len(payload), int(scalar_values["decoded_value_count"]) * byte_width),
                    data_type=data_type,
                    value=scalar_values,
                    description=description + " Editing is disabled until the owning Havok object field is confirmed.",
                    confidence="strong inference",
                    editable=False,
                )
            )
        return True
    elif type_name in _HKX_ENUM_RECORD_TYPES and record.count > 0:
        enum_values = _hkx_enum_record_values(payload, record)
        if enum_values:
            fields.append(
                _hkx_layout_field(
                    name="enum_or_flags_values",
                    offset=0,
                    size=min(len(payload), int(enum_values["decoded_value_count"]) * int(enum_values["storage_byte_width"])),
                    data_type=f"enum/flags[{enum_values['storage_byte_width']}-byte]",
                    value=enum_values,
                    description=(
                        str(enum_values["description"])
                        + " Names for each numeric value are not fully mapped yet, so this is read-only context."
                    ),
                    confidence="strong inference",
                    editable=False,
                )
            )
        return True
    elif type_name == 'int' and record.count > 0 and (len(payload) >= record.count * 4):
        values = [int(struct.unpack_from("<i", payload, index * 4)[0]) for index in range(min(int(record.count), 512))]
        fields.append(
            _hkx_layout_field(
                name="int32_values",
                offset=0,
                size=min(len(payload), int(record.count) * 4),
                data_type="int32[]",
                value={"values": values, "value_count": int(record.count), "truncated": max(0, int(record.count) - len(values))},
                description=(
                    "Read-only int array. In skeleton/mapper files this commonly stores compact bone or mapping indices. "
                    "Changing array values is not enabled until mapper reference rules are fully recovered."
                ),
                confidence="strong inference",
                editable=False,
            )
        )
        return True
    return False


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_hkx_layout_field',
    'struct',
)
def _hkx_record_layout_fields_2(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name == 'char' and payload:
        nul_index = payload.find(b"\0")
        string_bytes = payload[: nul_index if nul_index >= 0 else len(payload)]
        decoded_text = string_bytes.decode("utf-8", errors="replace")
        fields.append(
            _hkx_layout_field(
                name="ascii_or_utf8_text",
                offset=0,
                size=len(payload),
                data_type="char[]",
                value=decoded_text,
                description=(
                    "Read-only string payload. These names are used as descriptor, skeleton, body, shape, or root-container "
                    "labels. String editing is not safe because it can change record length and reference layout."
                ),
                confidence="confirmed" if nul_index >= 0 else "strong inference",
                editable=False,
            )
        )
        return True
    elif type_name == 'hknpConvexHull::Face' and record.count > 0 and (len(payload) >= record.count * 4):
        fields.append(
            _hkx_layout_field(
                name="face_records",
                offset=0,
                size=record.count * 4,
                data_type="struct{u16 index_start; u8 vertex_count; u8 meta}[]",
                value={"record_count": record.count, "stride": 4},
                description="Convex face table. index_start points into the face-index byte array.",
                confidence="strong inference",
                editable=True,
            )
        )
        return True
    elif type_name == 'hkUint8' and record.count > 0:
        fields.append(
            _hkx_layout_field(
                name="byte_values",
                offset=0,
                size=min(record.count, len(payload)),
                data_type="uint8[]",
                value={"value_count": record.count},
                description="Byte array. In decoded convex hulls this is usually the face vertex index buffer.",
                confidence="strong inference",
                editable=True,
            )
        )
        return True
    elif type_name == 'hknpConvexHull::Edge' and record.count > 0 and (len(payload) >= record.count * 4):
        fields.append(
            _hkx_layout_field(
                name="uint16_pairs",
                offset=0,
                size=record.count * 4,
                data_type="uint16[2][]",
                value={"pair_count": record.count, "stride": 4},
                description="Convex edge/support pairs. Topology role is still inferred.",
                confidence="strong inference",
                editable=True,
            )
        )
        return True
    elif type_name == 'hknpShapeMassProperties' and len(payload) >= 64:
        row_labels = (
            (
                "mass_properties_row0_basis_or_inertia",
                "Mass-property row 0. In tested payloads this often resembles a basis/inertia row or transform-like vector.",
            ),
            (
                "mass_properties_row1_basis_or_inertia",
                "Mass-property row 1. In tested payloads this often resembles a basis/inertia row or transform-like vector.",
            ),
            (
                "mass_properties_row2_basis_or_inertia",
                "Mass-property row 2. In tested payloads this often resembles a basis/inertia row or transform-like vector.",
            ),
            (
                "mass_properties_row3_center_mass_or_scale",
                "Mass-property row 3. In sampled shape records this is the most likely center/mass/scale-like row, but exact fields remain experimental.",
            ),
        )
        for row_index, (row_name, row_description) in enumerate(row_labels):
            row_offset = row_index * 16
            row = list(struct.unpack_from("<ffff", payload, row_offset))
            fields.append(
                _hkx_layout_field(
                    name=row_name,
                    offset=row_offset,
                    size=16,
                    data_type="float32[4]",
                    value=[float(component) for component in row],
                    description=row_description,
                    confidence="experimental",
                    editable=True,
                )
            )
        fields.append(
            _hkx_layout_field(
                name="mass_property_float4_rows",
                offset=0,
                size=64,
                data_type="float32[4][4]",
                value={"row_count": 4, "stride": 16},
                description="Mass-property matrix/vector payload. Exact Havok field names are not recovered yet.",
                confidence="experimental",
                editable=True,
            )
        )
        return True
    return False


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_hkx_first_u32_words',
    '_hkx_layout_field',
    'math',
    'struct',
)
def _hkx_record_layout_fields_3(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name == 'hkCompressedMassProperties' and len(payload) >= 16:
        word_count = min(16, len(payload) // 4)
        u32_words = _hkx_first_u32_words(payload[: word_count * 4], word_count)
        u16_values = [
            int(struct.unpack_from("<H", payload, offset)[0])
            for offset in range(0, min(len(payload), 64) - 1, 2)
        ]
        finite_floats: List[Dict[str, object]] = []
        for offset in range(0, min(len(payload), 96) - 3, 4):
            value = struct.unpack_from("<f", payload, offset)[0]
            if math.isfinite(value) and 1e-8 <= abs(value) <= 1_000_000.0:
                finite_floats.append({"offset": offset, "hex_offset": f"0x{offset:X}", "value": float(value)})
        fields.append(
            _hkx_layout_field(
                name="compressed_mass_properties_sample",
                offset=0,
                size=min(len(payload), 96),
                data_type="hkCompressedMassProperties/read-only",
                value={
                    "u32_words": u32_words,
                    "u16_values_sample": u16_values[:32],
                    "finite_float_candidates": finite_floats[:16],
                    "payload_byte_length": len(payload),
                },
                description=(
                    "Read-only compressed mass-property payload sample. Havok stores mass/inertia/center data in a "
                    "compact form here; exact 2024.2 packing rules are not recovered, so edits are disabled."
                ),
                confidence="experimental",
                editable=False,
            )
        )
        return True
    elif type_name == 'hkPackedVector3' and record.count > 0 and (len(payload) >= 4):
        packed_stride = max(4, len(payload) // max(1, int(record.count)))
        row_limit = min(int(record.count), 256)
        rows: List[Dict[str, object]] = []
        for item_index in range(row_limit):
            base = item_index * packed_stride
            if base + 4 > len(payload):
                break
            raw = payload[base : base + min(packed_stride, 8)]
            first_four = raw[:4]
            signed_bytes = [
                int(value - 256) if value >= 128 else int(value)
                for value in first_four
            ]
            rows.append(
                {
                    "index": item_index,
                    "offset": base,
                    "hex_offset": f"0x{base:X}",
                    "packed_u32": int(struct.unpack_from("<I", first_four, 0)[0]),
                    "bytes": [int(value) for value in first_four],
                    "signed_bytes": signed_bytes,
                    "normalized_signed_127": [round(value / 127.0, 6) for value in signed_bytes[:3]],
                }
            )
        fields.append(
            _hkx_layout_field(
                name="packed_vector3_rows",
                offset=0,
                size=min(len(payload), row_limit * packed_stride),
                data_type="hkPackedVector3[]/read-only",
                value={
                    "row_count": int(record.count),
                    "candidate_stride": packed_stride,
                    "rows": rows,
                    "truncated_rows": max(0, int(record.count) - len(rows)),
                },
                description=(
                    "Read-only packed vector rows. The byte triplets are useful for comparing compressed mass or shape "
                    "payloads, but edits are disabled until scale/offset ownership is recovered."
                ),
                confidence="experimental",
                editable=False,
            )
        )
        return True
    elif type_name == 'HavokShapeNameProperty' and len(payload) >= 36:
        raw_name_reference = struct.unpack_from("<I", payload, 0x20)[0]
        fields.append(
            _hkx_layout_field(
                name="shape_name_reference",
                offset=0x20,
                size=4,
                data_type="uint32/char_record_reference",
                value={
                    "raw_value": raw_name_reference,
                    "candidate_char_record_index": raw_name_reference - 1 if raw_name_reference > 0 else None,
                },
                description=(
                    "Read-only HavokShapeNameProperty name reference. In tested Crimson Desert files this value minus "
                    "one points to a char record containing the body/shape label."
                ),
                confidence="strong inference",
                editable=False,
            )
        )
        return True
    return False


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_hkx_finite_float_slots',
    '_hkx_first_u32_words',
    '_hkx_layout_field',
    '_hkx_u32_pair_rows',
    'math',
    'struct',
)
def _hkx_record_layout_fields_4(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name == 'hknpTriangleShape' and len(payload) >= 16:
        vector_rows: List[Dict[str, object]] = []
        for offset in range(0, min(len(payload), 160) - 15, 16):
            row_values = struct.unpack_from("<ffff", payload, offset)
            if any(math.isfinite(value) and abs(value) > 1e-8 and abs(value) <= 1_000_000.0 for value in row_values):
                vector_rows.append(
                    {
                        "offset": offset,
                        "hex_offset": f"0x{offset:X}",
                        "value": [float(component) for component in row_values],
                    }
                )
        pair_rows = _hkx_u32_pair_rows(payload, limit_bytes=min(len(payload), 160))[:20]
        fields.append(
            _hkx_layout_field(
                name="triangle_shape_candidate_layout",
                offset=0,
                size=min(len(payload), 160),
                data_type="hknpTriangleShape/read-only",
                value={
                    "u32_pair_rows": pair_rows,
                    "finite_vector4_rows": vector_rows[:8],
                    "finite_float_slots": _hkx_finite_float_slots(payload, limit_bytes=min(len(payload), 160), limit=24),
                    "payload_byte_length": len(payload),
                },
                description=(
                    "Read-only hknpTriangleShape candidate layout. Corpus evidence shows this is a high-priority "
                    "shape class, but exact vertex/material/tag member names are not proven enough for safe edits."
                ),
                confidence="experimental",
                editable=False,
                decode_source="typed_layout",
                decode_strength="candidate_only",
                read_only_reason="Triangle shape edits are blocked until vertex, material, shape-tag, and child-reference fields are confirmed.",
            )
        )
        return True
    elif type_name == 'hknpMaterial' and record.count > 0:
        material_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 128)):
            base = item_index * material_stride
            if base >= len(payload):
                break
            words = _hkx_first_u32_words(payload[base : base + min(material_stride, 48)], min(12, max(1, material_stride // 4)))
            finite_floats = []
            for offset in range(0, min(material_stride, 80) - 3, 4):
                value = struct.unpack_from("<f", payload, base + offset)[0]
                if math.isfinite(value) and 1e-8 <= abs(value) <= 1_000_000.0:
                    finite_floats.append({"offset": offset, "hex_offset": f"0x{offset:X}", "value": float(value)})
            named_candidates = []
            for offset, name in (
                (0x00, "material_id_or_flags"),
                (0x04, "collision_filter_or_quality"),
                (0x08, "friction_or_restitution_bits"),
                (0x0C, "surface_response_or_flags"),
            ):
                if offset + 4 <= material_stride:
                    named_candidates.append(
                        {
                            "name": name,
                            "offset": offset,
                            "hex_offset": f"0x{offset:X}",
                            "u32": struct.unpack_from("<I", payload, base + offset)[0],
                        }
                    )
            fields.append(
                _hkx_layout_field(
                    name=f"material[{item_index}]",
                    offset=base,
                    size=material_stride,
                    data_type="hknpMaterial/read-only",
                    value={
                        "u32_words": words,
                        "named_candidates": named_candidates,
                        "finite_float_slots": finite_floats[:16],
                    },
                    description=(
                        "Read-only hknpMaterial row. Likely friction/restitution/filter/material flags; exact field names "
                        "are not confirmed, so material editing is not enabled."
                    ),
                    confidence="experimental",
                    editable=False,
                    decode_source="typed_layout",
                    decode_strength="candidate_only",
                    read_only_reason="Material edits are blocked until friction/restitution/filter fields and game material mapping are confirmed.",
                )
            )
        return True
    return False


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_hkx_finite_float_slots',
    '_hkx_first_u32_words',
    '_hkx_layout_field',
    '_hkx_u32_pair_rows',
    'math',
    'struct',
)
def _hkx_record_layout_fields_5(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name in {'hknpBallAndSocketConstraintData', 'hknpHingeConstraintData', 'hknpVelocityConstraintMotor'} and len(payload) >= 16:
        constraint_stride = len(payload) // max(1, int(record.count)) if record.count else len(payload)
        for item_index in range(min(max(1, int(record.count)), 64)):
            base = item_index * constraint_stride
            if base >= len(payload):
                break
            row_payload = payload[base : base + constraint_stride]
            vector_rows: List[Dict[str, object]] = []
            for row_offset in range(0, min(len(row_payload), 0x140) - 15, 16):
                row_values = struct.unpack_from("<ffff", row_payload, row_offset)
                if any(math.isfinite(value) and abs(value) > 1e-8 and abs(value) <= 1_000_000.0 for value in row_values):
                    vector_rows.append(
                        {
                            "offset": row_offset,
                            "hex_offset": f"0x{row_offset:X}",
                            "value": [float(component) for component in row_values],
                        }
                    )
            fields.append(
                _hkx_layout_field(
                    name=f"{type_name.split('::')[-1]}[{item_index}]",
                    offset=base,
                    size=constraint_stride,
                    data_type=f"{type_name}/read-only",
                    value={
                        "u32_words": _hkx_first_u32_words(row_payload[: min(len(row_payload), 96)], min(24, len(row_payload) // 4)),
                        "u32_pair_rows": _hkx_u32_pair_rows(row_payload, limit_bytes=min(len(row_payload), 160))[:20],
                        "finite_float_slots": _hkx_finite_float_slots(row_payload, limit_bytes=min(len(row_payload), 0x180), limit=64),
                        "frame_or_axis_vector_rows": vector_rows[:16],
                        "truncated_vector_rows": max(0, len(vector_rows) - 16),
                    },
                    description=(
                        f"Read-only {type_name} candidate layout. Float/vector rows are useful for browsing "
                        "joint frames, pivots, limits, and motor-like values, but edits are disabled until exact "
                        "member names and safe constraints are confirmed."
                    ),
                    confidence="experimental",
                    editable=False,
                    decode_source="typed_layout",
                    decode_strength="candidate_only",
                    read_only_reason="Constraint/motor structural edits are blocked; only separately mapped fixed-size tuning rows are patchable.",
                )
            )
        return True
    elif type_name == 'hknpCylinderShape' and len(payload) >= 112:
        radius_candidates: List[Dict[str, object]] = []
        for offset, name in ((0x68, "convex_radius_or_margin"), (0x6C, "cylinder_radius_or_half_extent")):
            if offset + 4 <= len(payload):
                value = struct.unpack_from("<f", payload, offset)[0]
                if math.isfinite(value):
                    radius_candidates.append(
                        {
                            "name": name,
                            "offset": offset,
                            "hex_offset": f"0x{offset:X}",
                            "value": float(value),
                        }
                    )
        axis_rows: List[Dict[str, object]] = []
        for offset, name in ((0x80, "axis_or_endpoint_row0"), (0x90, "axis_or_endpoint_row1")):
            if offset + 16 <= len(payload):
                axis_rows.append(
                    {
                        "name": name,
                        "offset": offset,
                        "hex_offset": f"0x{offset:X}",
                        "value": [float(component) for component in struct.unpack_from("<ffff", payload, offset)],
                    }
                )
        fields.append(
            _hkx_layout_field(
                name="cylinder_shape_candidates",
                offset=0,
                size=min(len(payload), 0xA0),
                data_type="hknpCylinderShape/read-only",
                value={
                    "radius_candidates": radius_candidates,
                    "axis_or_endpoint_rows": axis_rows,
                    "u32_words": _hkx_first_u32_words(payload[: min(len(payload), 96)], min(24, len(payload) // 4)),
                },
                description=(
                    "Read-only hknpCylinderShape candidate layout from vehicle/wagon corpus samples. Offsets 0x68/0x6C "
                    "and rows near 0x80/0x90 are exposed for comparison; cylinder edits are blocked until the exact "
                    "radius/axis field semantics are confirmed."
                ),
                confidence="experimental",
                editable=False,
            )
        )
        return True
    elif type_name == 'hkSkeleton' and len(payload) >= 64:
        for offset, name, description in (
            (0x18, "bones_reference_or_count_pair", "Likely skeleton bone array reference/count pair."),
            (0x28, "parent_indices_reference_or_count_pair", "Likely parent-index array reference/count pair."),
            (0x38, "reference_pose_reference_or_count_pair", "Likely reference-pose transform array reference/count pair."),
            (0x48, "float_slots_or_metadata_pair", "Possible skeleton float slots or metadata reference/count pair."),
        ):
            if offset + 8 > len(payload):
                continue
            low, high = struct.unpack_from("<II", payload, offset)
            fields.append(
                _hkx_layout_field(
                    name=name,
                    offset=offset,
                    size=8,
                    data_type="uint32[2]/reference_count",
                    value={"data_or_reference": low, "count_or_flags": high},
                    description=description + " Structural skeleton edits are not supported.",
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    return False
