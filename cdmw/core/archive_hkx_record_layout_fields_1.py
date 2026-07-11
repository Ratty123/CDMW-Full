from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_hkx_first_u32_words',
    '_hkx_layout_field',
    'math',
    'struct',
)
def _hkx_record_layout_fields_6(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name == 'hkaSkeletonMapper' and len(payload) >= 64:
        for offset, name, description in (
            (
                0x20,
                "source_skeleton_or_root_reference",
                "Likely source skeleton/root reference. In paired Crimson Desert mapper records this value swaps with the target reference.",
            ),
            (
                0x28,
                "target_skeleton_or_root_reference",
                "Likely target skeleton/root reference. Used to browse mapper direction; structural edits are not supported.",
            ),
            (
                0x60,
                "mapper_data_or_mapping_reference",
                "Likely mapper-data reference or compact mapping record index. Exact reference encoding is still being recovered.",
            ),
        ):
            if offset + 8 > len(payload):
                continue
            low, high = struct.unpack_from("<II", payload, offset)
            fields.append(
                _hkx_layout_field(
                    name=name,
                    offset=offset,
                    size=8,
                    data_type="uint32[2]/reference_pair",
                    value={"data_or_reference": low, "count_or_flags": high},
                    description=description,
                    confidence="experimental",
                    editable=False,
                )
            )
        nonzero_words = []
        for offset in range(0, min(len(payload), 208) - 3, 4):
            word = struct.unpack_from("<I", payload, offset)[0]
            if word:
                nonzero_words.append({"offset": offset, "hex_offset": f"0x{offset:X}", "value": word})
        fields.append(
            _hkx_layout_field(
                name="mapper_header_nonzero_words",
                offset=0,
                size=min(len(payload), 208),
                data_type="uint32[]/skeleton-mapper-header",
                value={"nonzero_words": nonzero_words[:64], "truncated": max(0, len(nonzero_words) - 64)},
                description=(
                    "Read-only hkaSkeletonMapper header sample. Useful for comparing source/target mapper pairs and "
                    "finding links to SimpleMapping rows."
                ),
                confidence="experimental",
                editable=False,
            )
        )
        return True
    elif type_name in {'hkaSkeletonMapperData::SimpleMapping', 'hkaSkeletonMapperData::ChainMapping'} and record.count > 0:
        mapping_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 256)):
            base = item_index * mapping_stride
            if base >= len(payload):
                break
            row = payload[base : base + mapping_stride]
            words = _hkx_first_u32_words(row[: min(len(row), 64)], min(16, max(1, len(row) // 4)))
            finite_floats = []
            for offset in range(0, min(len(row), 64) - 3, 4):
                value = struct.unpack_from("<f", row, offset)[0]
                if math.isfinite(value) and 1e-8 <= abs(value) <= 1_000_000.0:
                    finite_floats.append({"offset": offset, "hex_offset": f"0x{offset:X}", "value": float(value)})
            fields.append(
                _hkx_layout_field(
                    name=f"simple_mapping[{item_index}]",
                    offset=base,
                    size=mapping_stride,
                    data_type=f"{type_name}/read-only",
                    value={
                        "u32_words": words,
                        "finite_float_slots": finite_floats[:20],
                        "likely_bone_index_words": [word for word in words if isinstance(word, int) and 0 <= word <= 1024][:8],
                    },
                    description=(
                        "Read-only skeleton mapper row. Simple/chain mapping records likely map source bones to target "
                        "bones with compact transform/weight blocks. Editing is disabled because a bad mapper can break "
                        "skeleton binding."
                    ),
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hkaAnimationContainer' and len(payload) >= 16:
        for offset in range(0, min(len(payload), 112), 8):
            if offset + 8 > len(payload):
                break
            low, high = struct.unpack_from("<II", payload, offset)
            if low == 0 and high == 0:
                continue
            fields.append(
                _hkx_layout_field(
                    name=f"animation_container_pair_0x{offset:X}",
                    offset=offset,
                    size=8,
                    data_type="uint32[2]/array_or_reference_pair",
                    value={"data_or_reference": low, "count_or_flags": high},
                    description=(
                        "Read-only hkaAnimationContainer reference/count candidate. It identifies contained animation, "
                        "skeleton, or binding arrays; structural edits are not supported."
                    ),
                    confidence="experimental",
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
    'struct',
)
def _hkx_record_layout_fields_7(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name.startswith('hkx') and payload:
        finite_slots = _hkx_finite_float_slots(payload, limit_bytes=min(len(payload), 256), limit=32)
        pair_rows = _hkx_u32_pair_rows(payload, limit_bytes=min(len(payload), 256))[:24]
        fields.append(
            _hkx_layout_field(
                name="hkx_scene_payload_sample",
                offset=0,
                size=min(len(payload), 256),
                data_type=f"{type_name}/read-only",
                value={
                    "u32_words": _hkx_first_u32_words(payload[: min(len(payload), 96)], min(24, len(payload) // 4)),
                    "u32_pair_rows": pair_rows,
                    "finite_float_slots": finite_slots,
                    "payload_byte_length": len(payload),
                },
                description=(
                    "Read-only hkx scene/mesh/animation payload sample. This keeps common corpus classes such as "
                    "hkxAnimatedFloat, hkxAnimatedVector, hkxAttribute, hkxNode, hkxMaterial, and mesh-section records "
                    "visible for schema recovery without enabling unsafe structural edits."
                ),
                confidence="experimental",
                editable=False,
            )
        )
        return True
    elif type_name in {'hkRefVariant', 'hkStringPtr'} and len(payload) >= 8:
        raw_reference = struct.unpack_from("<Q", payload, 0)[0]
        fields.append(
            _hkx_layout_field(
                name="referenced_value",
                offset=0,
                size=8,
                data_type="uint64/reference",
                value={"raw_u64": raw_reference, "low_u32": raw_reference & 0xFFFFFFFF},
                description=(
                    "Read-only Havok reference/string pointer payload. If the low word matches an ITEM DATA offset, "
                    "the relationship graph exposes the target separately."
                ),
                confidence="experimental",
                editable=False,
            )
        )
        if len(payload) >= 16:
            low, high = struct.unpack_from("<II", payload, 8)
            fields.append(
                _hkx_layout_field(
                    name="reference_metadata_pair",
                    offset=8,
                    size=8,
                    data_type="uint32[2]",
                    value={"a": low, "b": high},
                    description="Possible variant type/context metadata. Structural edits are not supported.",
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name in {'hkMemoryResourceContainer', 'hknpConstraintData', 'hknpRefDragProperties', 'hknpRefMassDistribution'} and len(payload) >= 8:
        pair_rows = _hkx_u32_pair_rows(payload, limit_bytes=192)
        for row in pair_rows[:24]:
            offset = int(row["offset"])
            fields.append(
                _hkx_layout_field(
                    name=f"reference_or_value_pair_0x{offset:X}",
                    offset=offset,
                    size=8,
                    data_type="uint32[2]/reference_or_value",
                    value={"a": row["a"], "b": row["b"], "as_u64": row["as_u64"]},
                    description=(
                        f"Read-only {type_name} pair. These pairs are useful for identifying arrays, references, "
                        "counts, flags, and tuning records; structural edits are not supported."
                    ),
                    confidence="experimental",
                    editable=False,
                )
            )
        finite_slots = _hkx_finite_float_slots(payload, limit_bytes=192, limit=16)
        if finite_slots:
            fields.append(
                _hkx_layout_field(
                    name="finite_float_candidates",
                    offset=0,
                    size=min(len(payload), 192),
                    data_type="float32[]/candidate",
                    value={"slots": finite_slots, "truncated": 0},
                    description=(
                        "Finite float candidates inside this payload. Values may be drag, mass distribution, solver, "
                        "or scaling terms depending on the owning class; edits are disabled until fields are named."
                    ),
                    confidence="experimental",
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
def _hkx_record_layout_fields_8(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name in {'hknpWheelConstraintData', 'hknpFixedConstraintData', 'hknpBreakableConstraintData'} and len(payload) >= 16:
        constraint_stride = len(payload) // max(1, int(record.count)) if record.count else len(payload)
        for item_index in range(min(max(1, int(record.count)), 64)):
            base = item_index * constraint_stride
            if base >= len(payload):
                break
            row_payload = payload[base : base + constraint_stride]
            finite_slots = _hkx_finite_float_slots(row_payload, limit_bytes=min(len(row_payload), 0x1C0), limit=80)
            vector_rows: List[Dict[str, object]] = []
            for row_offset in range(0x40, min(len(row_payload), 0x120) - 15, 16):
                row_values = struct.unpack_from("<ffff", row_payload, row_offset)
                if any(math.isfinite(value) and abs(value) > 1e-8 for value in row_values):
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
                        "finite_float_slots": finite_slots,
                        "frame_or_axis_vector_rows": vector_rows[:16],
                        "truncated_vector_rows": max(0, len(vector_rows) - 16),
                    },
                    description=(
                        f"Read-only {type_name} candidate layout from the corpus. Float/vector rows are useful for "
                        "identifying wheel/fixed/breakable joint frames and strength-like values, but edits are disabled "
                        "until class-specific field names and constraints are confirmed."
                    ),
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hknpShapeProperties::Entry' and record.count > 0 and (len(payload) >= min(record.count * 16, 16)):
        entry_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 64)):
            base = item_index * entry_stride
            if base + 16 > len(payload):
                break
            key_or_id, value_or_ref, flags_or_type, user_data = struct.unpack_from("<IIII", payload, base)
            fields.append(
                _hkx_layout_field(
                    name=f"property_entry[{item_index}]",
                    offset=base,
                    size=min(entry_stride, 16),
                    data_type="uint32[4]",
                    value={
                        "key_or_id": key_or_id,
                        "value_or_reference": value_or_ref,
                        "flags_or_type": flags_or_type,
                        "user_data": user_data,
                    },
                    description=(
                        "Likely hknp shape-property entry row. Exact key/value/flags names are not confirmed; "
                        "structural edits are not supported."
                    ),
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name.startswith('hkFreeListArrayElement') and record.count > 0:
        element_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 64)):
            base = item_index * element_stride
            if base >= len(payload):
                break
            sample = _hkx_first_u32_words(payload[base : base + min(element_stride, 32)], min(8, max(1, element_stride // 4)))
            fields.append(
                _hkx_layout_field(
                    name=f"free_list_element[{item_index}]",
                    offset=base,
                    size=element_stride,
                    data_type="uint32[]/free-list-element",
                    value={"u32_words": sample},
                    description=(
                        "Free-list element backing compound/shape-instance storage. Values are decoded for "
                        "browsing and reference recovery only; list rebuilding is not supported."
                    ),
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hknpMeshShape::GeometrySection' and record.count > 0:
        section_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 64)):
            base = item_index * section_stride
            if base >= len(payload):
                break
            row_payload = payload[base : base + section_stride]
            fields.append(
                _hkx_layout_field(
                    name=f"geometry_section[{item_index}]",
                    offset=base,
                    size=section_stride,
                    data_type="hknpMeshShape::GeometrySection/read-only",
                    value={
                        "u32_pair_rows": _hkx_u32_pair_rows(row_payload, limit_bytes=min(len(row_payload), 96))[:12],
                        "u32_words": _hkx_first_u32_words(row_payload[: min(len(row_payload), 64)], min(16, len(row_payload) // 4)),
                    },
                    description=(
                        "Read-only mesh geometry-section row. The row contains candidate references/counts for AABB nodes, "
                        "primitive buffers, mesh byte buffers, and shape tags; mesh topology rebuilds remain blocked."
                    ),
                    confidence="experimental",
                    editable=False,
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
    'struct',
)
def _hkx_record_layout_fields_9(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name == 'hknpMeshShape::GeometrySection::Primitive' and record.count > 0:
        primitive_stride = max(1, len(payload) // max(1, int(record.count)))
        rows: List[Dict[str, object]] = []
        for item_index in range(min(int(record.count), 256)):
            base = item_index * primitive_stride
            if base >= len(payload):
                break
            raw = payload[base : base + min(primitive_stride, 8)]
            rows.append(
                {
                    "index": item_index,
                    "offset": base,
                    "hex_offset": f"0x{base:X}",
                    "bytes": [int(value) for value in raw],
                    "u32": int(struct.unpack_from("<I", raw.ljust(4, b"\0"), 0)[0]) if raw else 0,
                }
            )
        fields.append(
            _hkx_layout_field(
                name="primitive_words",
                offset=0,
                size=min(len(payload), len(rows) * primitive_stride),
                data_type="hknpMeshShape::GeometrySection::Primitive[]/read-only",
                value={
                    "candidate_stride": primitive_stride,
                    "rows": rows,
                    "truncated_rows": max(0, int(record.count) - len(rows)),
                },
                description=(
                    "Read-only packed mesh primitive rows. The corpus confirms this is a high-frequency unknown; "
                    "rows are exposed for bit-layout recovery, but primitive topology editing is still disabled."
                ),
                confidence="experimental",
                editable=False,
            )
        )
        return True
    elif type_name == 'hknpMeshShape::ShapeTagTableEntry' and record.count > 0:
        entry_stride = max(1, len(payload) // max(1, int(record.count)))
        for item_index in range(min(int(record.count), 128)):
            base = item_index * entry_stride
            if base >= len(payload):
                break
            row_payload = payload[base : base + entry_stride]
            fields.append(
                _hkx_layout_field(
                    name=f"shape_tag_entry[{item_index}]",
                    offset=base,
                    size=entry_stride,
                    data_type="hknpMeshShape::ShapeTagTableEntry/read-only",
                    value={
                        "u32_words": _hkx_first_u32_words(row_payload[: min(len(row_payload), 32)], min(8, len(row_payload) // 4)),
                        "bytes": [int(value) for value in row_payload[:16]],
                    },
                    description=(
                        "Read-only mesh shape-tag table entry. Shape tag range semantics are not fully recovered, "
                        "so edits are disabled."
                    ),
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hknpCompoundShape' and len(payload) >= 32:
        for offset, name, description in (
            (0x00, "base_or_vtable_words", "Initial object/base words for hknpCompoundShape."),
            (0x20, "shape_instances_or_storage_pair", "Possible child shape instance storage offset/count or reference pair."),
            (0x30, "simd_tree_or_bounds_pair", "Possible tree/bounds reference or count pair."),
            (0x40, "free_list_or_child_metadata_pair", "Possible free-list/child metadata pair."),
            (0x50, "shape_property_or_flags_pair", "Possible property/flags pair."),
            (0x60, "compound_runtime_pair", "Possible runtime/cache pair."),
        ):
            if offset + 8 > len(payload):
                continue
            first, second = struct.unpack_from("<II", payload, offset)
            fields.append(
                _hkx_layout_field(
                    name=name,
                    offset=offset,
                    size=8,
                    data_type="uint32[2]",
                    value={"a": first, "b": second},
                    description=description + " Exact Havok 2024.2 field names are still being recovered.",
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hknpShapeInstance' and record.count > 0:
        instance_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 64)):
            base = item_index * instance_stride
            if base >= len(payload):
                break
            words = _hkx_first_u32_words(payload[base : base + min(instance_stride, 32)], min(8, max(1, instance_stride // 4)))
            fields.append(
                _hkx_layout_field(
                    name=f"shape_instance[{item_index}]",
                    offset=base,
                    size=instance_stride,
                    data_type="uint32[]/shape-instance",
                    value={"u32_words": words},
                    description=(
                        "Child shape-instance row. Likely links child shape data, transform/filter metadata, and "
                        "shape keys. Reference decoding is shown separately where offsets match ITEM records."
                    ),
                    confidence="experimental",
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
    'math',
    'struct',
)
def _hkx_record_layout_fields_10(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name in {'hkcdSimdTreeNamespace::Node', 'hknpAabb8TreeNode'} and record.count > 0:
        node_stride = len(payload) // max(1, int(record.count))
        for item_index in range(min(int(record.count), 128)):
            base = item_index * node_stride
            if base >= len(payload):
                break
            words = _hkx_first_u32_words(payload[base : base + min(node_stride, 32)], min(8, max(1, node_stride // 4)))
            float_values: List[float] = []
            for offset in range(0, min(node_stride, 32) - 3, 4):
                value = struct.unpack_from("<f", payload, base + offset)[0]
                if math.isfinite(value) and abs(value) <= 1_000_000.0:
                    float_values.append(float(value))
            fields.append(
                _hkx_layout_field(
                    name=f"simd_tree_node[{item_index}]",
                    offset=base,
                    size=node_stride,
                    data_type="uint32[]/float32[]/tree-node",
                    value={"u32_words": words, "float_sample": float_values[:8]},
                    description=(
                        "Spatial acceleration tree node used by compound/mesh shapes. Bounds/child encoding is "
                        "not fully named yet, but rows are now separated for comparison across files."
                    ),
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hkRootLevelContainer' and len(payload) >= 16:
        fields.extend(
            [
                _hkx_layout_field(
                    name="named_variants_data_reference",
                    offset=0,
                    size=8,
                    data_type="uint64/reference",
                    value=struct.unpack_from("<Q", payload, 0)[0],
                    description="Likely array/reference to hkRootLevelContainer::NamedVariant records.",
                    confidence="experimental",
                    editable=False,
                ),
                _hkx_layout_field(
                    name="named_variants_size",
                    offset=8,
                    size=4,
                    data_type="uint32",
                    value=struct.unpack_from("<I", payload, 8)[0],
                    description="Likely number of root named variants.",
                    confidence="experimental",
                    editable=False,
                ),
                _hkx_layout_field(
                    name="named_variants_capacity_and_flags",
                    offset=12,
                    size=4,
                    data_type="uint32",
                    value=struct.unpack_from("<I", payload, 12)[0],
                    description="Likely Havok array capacity/flags for root variants. Structural edits are not supported.",
                    confidence="experimental",
                    editable=False,
                ),
            ]
        )
        return True
    elif type_name == 'hkRootLevelContainer::NamedVariant' and len(payload) >= 24:
        for offset, name, description in (
            (0, "name_reference", "Likely reference to variant name string."),
            (8, "class_name_reference", "Likely reference to Havok class/type name string."),
            (16, "object_reference", "Likely reference to the root object for this named variant."),
        ):
            fields.append(
                _hkx_layout_field(
                    name=name,
                    offset=offset,
                    size=8,
                    data_type="uint64/reference",
                    value=struct.unpack_from("<Q", payload, offset)[0],
                    description=description,
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hknpPhysicsSystemData' and len(payload) >= 8:
        for offset, name, description in (
            (0x00, "materials_array_or_reference_pair", "Likely reference/count pair for hknpMaterial rows."),
            (0x08, "motion_properties_array_or_reference_pair", "Likely reference/count pair for hknpSharedMotionProperties rows."),
            (0x10, "body_cinfo_array_or_reference_pair", "Likely reference/count pair for ExtendedBodyCinfo body rows."),
            (0x18, "constraint_cinfo_array_or_reference_pair", "Likely reference/count pair for hknpConstraintCinfo rows."),
            (0x20, "shape_reference_array_or_pair", "Likely reference/count pair for shape references."),
            (0x28, "system_metadata_or_flags_pair", "Likely physics-system metadata, flags, or runtime pair."),
        ):
            if offset + 8 > len(payload):
                continue
            low, high = struct.unpack_from("<II", payload, offset)
            if low == 0 and high == 0:
                continue
            fields.append(
                _hkx_layout_field(
                    name=name,
                    offset=offset,
                    size=8,
                    data_type="uint32[2]/reference_count",
                    value={"data_or_reference": low, "count_or_flags": high},
                    description=description + " Structural array/reference edits are not supported.",
                    confidence="experimental",
                    editable=False,
                )
            )
        finite_slots = _hkx_finite_float_slots(payload, limit_bytes=192, limit=16)
        if finite_slots:
            fields.append(
                _hkx_layout_field(
                    name="system_finite_float_candidates",
                    offset=0,
                    size=min(len(payload), 192),
                    data_type="float32[]/candidate",
                    value={"slots": finite_slots},
                    description="Read-only finite float candidates in hknpPhysicsSystemData.",
                    confidence="experimental",
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
def _hkx_record_layout_fields_11(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]]) -> bool:
    if type_name == 'hknpPhysicsSystemData::ExtendedBodyCinfo' and len(payload) >= 8:
        for offset, name, description in (
            (0x00, "body_base_flags_or_type_pair", "Likely body type, flags, or base metadata pair."),
            (0x08, "shape_reference_or_key_pair", "Likely shape reference/index plus shape-key or flags."),
            (0x10, "motion_properties_reference_pair", "Likely reference/index to hknpSharedMotionProperties."),
            (0x18, "material_or_collision_filter_pair", "Likely material/filter/collision-layer metadata."),
            (0x20, "body_name_user_data_or_bone_pair", "Likely body name, user data, bone, or attachment index metadata."),
            (0x28, "body_transform_header_pair", "Likely header before transform/orientation float block."),
            (0x50, "body_runtime_or_quality_pair", "Likely runtime quality/motion/activation metadata."),
            (0x60, "body_mass_or_inertia_header_pair", "Likely header near mass/inertia-related fields."),
        ):
            if offset + 8 > len(payload):
                continue
            low, high = struct.unpack_from("<II", payload, offset)
            if low == 0 and high == 0:
                continue
            fields.append(
                _hkx_layout_field(
                    name=name,
                    offset=offset,
                    size=8,
                    data_type="uint32[2]/body-cinfo",
                    value={"a": low, "b": high},
                    description=description + " Kept read-only until exact body schema is confirmed.",
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name == 'hknpConstraintCinfo' and len(payload) >= 8:
        for offset, name, description in (
            (0x00, "body_a_reference_or_index_pair", "Likely first constrained body reference/index pair."),
            (0x08, "body_b_reference_or_index_pair", "Likely second constrained body reference/index pair."),
            (0x10, "constraint_data_reference_pair", "Likely reference/index to hknpConstraintData or concrete constraint data."),
            (0x18, "constraint_priority_flags_pair", "Likely priority, collision, enable, or runtime flags."),
            (0x20, "constraint_user_data_or_metadata_pair", "Likely user data or constraint metadata pair."),
        ):
            if offset + 8 > len(payload):
                continue
            low, high = struct.unpack_from("<II", payload, offset)
            if low == 0 and high == 0:
                continue
            fields.append(
                _hkx_layout_field(
                    name=name,
                    offset=offset,
                    size=8,
                    data_type="uint32[2]/constraint-cinfo",
                    value={"a": low, "b": high},
                    description=description + " Constraint reference edits are not supported.",
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    elif type_name in {'hknpPhysicsSceneData', 'hknpRagdollData', 'hknpConstraintCinfo'}:
        for offset in range(0, min(len(payload), 128), 8):
            if offset + 8 > len(payload):
                break
            low = struct.unpack_from("<I", payload, offset)[0]
            high = struct.unpack_from("<I", payload, offset + 4)[0]
            if low == 0 and high == 0:
                continue
            field_name = f"u32_pair_0x{offset:X}"
            description = "Unverified pair of 32-bit words from a physics container/constraint-info payload."
            if type_name == "hknpConstraintCinfo":
                description = "Possible body/constraint reference or flags pair. Structural reference edits are not supported."
            elif type_name == "hknpPhysicsSceneData":
                description = "Possible physics-system/body/constraint array reference or count pair."
            elif type_name == "hknpRagdollData":
                description = "Possible ragdoll body/constraint/skeleton array reference or count pair."
            fields.append(
                _hkx_layout_field(
                    name=field_name,
                    offset=offset,
                    size=8,
                    data_type="uint32[2]",
                    value={"a": low, "b": high},
                    description=description,
                    confidence="experimental",
                    editable=False,
                )
            )
        return True
    return False
