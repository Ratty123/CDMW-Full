from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_hkx_layout_field',
    'math',
    'struct',
)
def _hkx_record_layout_post_0(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]], stride: Optional[int]) -> None:
    if type_name == "hknpConvexShape" and len(payload) >= 0x64:
        for offset, name, description in (
            (0x30, "vertices_offset_count", "Observed pair; count often matches decoded vertex count."),
            (0x40, "planes_offset_count", "Observed pair; count often matches decoded hull plane count."),
            (0x48, "faces_offset_count", "Observed pair; count often matches decoded face count."),
            (0x50, "face_indices_offset_count", "Observed pair; count often matches face-index byte count."),
            (0x58, "edge_table_a_offset_count", "Observed pair; likely convex edge/support metadata."),
            (0x60, "edge_table_b_offset_count", "Observed pair; likely convex edge/support metadata."),
        ):
            if offset + 8 <= len(payload):
                data_like, count_like = struct.unpack_from("<II", payload, offset)
                fields.append(
                    _hkx_layout_field(
                        name=name,
                        offset=offset,
                        size=8,
                        data_type="uint32[2]",
                        value={"data_or_offset": data_like, "count_or_flags": count_like},
                        description=description,
                        confidence="strong inference",
                        editable=False,
                    )
                )
        for offset, name, description in (
            (
                0x68,
                "convex_radius_or_collision_margin",
                "Likely convex radius/collision margin. Kept read-only in Havok XML view until the exact hknpConvexShape field role is confirmed.",
            ),
            (
                0x6C,
                "aabb_or_radius_factor",
                "Likely AABB expansion/radius factor. Kept read-only until confirmed across more samples.",
            ),
        ):
            if offset + 4 <= len(payload):
                value = struct.unpack_from("<f", payload, offset)[0]
                if math.isfinite(value):
                    fields.append(
                        _hkx_layout_field(
                            name=name,
                            offset=offset,
                            size=4,
                            data_type="float32",
                            value=float(value),
                            description=description,
                            confidence="experimental",
                            editable=False,
                        )
                    )


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    'Mapping',
    '_hkx_export_fixed_float_slot_rows',
    '_hkx_fixed_float_slot_description',
    '_hkx_layout_field',
    '_hkx_physics_tuning_confidence',
    '_hkx_physics_tuning_slot_name',
)
def _hkx_record_layout_post_1(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]], stride: Optional[int]) -> None:
    if type_name in {
        "hknpSharedMotionProperties",
        "hknpPhysicsSystemData::ExtendedBodyCinfo",
        "hknpRagdollConstraintData",
        "hknpLimitedHingeConstraintData",
        "hknpPositionConstraintMotor",
    }:
        for item in _hkx_export_fixed_float_slot_rows(payload, record):
            if not isinstance(item.get("index"), int):
                continue
            item_index = int(item["index"])
            item_stride = int(item.get("stride") or stride or 0)
            for slot in item.get("float_slots", []) if isinstance(item.get("float_slots"), list) else []:
                if not isinstance(slot, Mapping) or not isinstance(slot.get("offset"), int):
                    continue
                offset = int(slot["offset"])
                fields.append(
                    _hkx_layout_field(
                        name=_hkx_physics_tuning_slot_name(type_name, offset),
                        offset=item_index * item_stride + offset,
                        size=4,
                        data_type="float32",
                        value=slot.get("value"),
                        description=str(slot.get("description") or _hkx_fixed_float_slot_description(type_name, offset)),
                        confidence=_hkx_physics_tuning_confidence(type_name, offset),
                        editable=True,
                    )
                    | {
                        "item_index": item_index,
                        "item_relative_offset": offset,
                        "item_relative_hex_offset": f"0x{offset:X}",
                    }
                )


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_hkx_layout_field',
    'math',
    'struct',
)
def _hkx_record_layout_post_2(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]], stride: Optional[int]) -> None:
    if type_name == "hknpBoxShape" and len(payload) >= 0x6C:
        for offset, name, description in (
            (
                0x30,
                "shape_property_or_material_index",
                "Observed hknpBoxShape word. In Crimson Desert samples this often looks like a small property/material index.",
            ),
            (
                0x38,
                "box_vertices_offset_count",
                "Likely offset/count pair for the eight box corner vertices or equivalent local box point table.",
            ),
            (
                0x40,
                "box_planes_offset_count",
                "Likely offset/count pair for the six box plane equations.",
            ),
            (
                0x48,
                "box_faces_offset_count",
                "Likely offset/count pair for the six box face records.",
            ),
            (
                0x50,
                "box_face_indices_offset_count",
                "Likely offset/count pair for the fixed box face-index byte buffer.",
            ),
            (
                0x58,
                "box_edge_table_a_offset_count",
                "Likely offset/count pair for box edge/support metadata.",
            ),
            (
                0x60,
                "box_edge_table_b_offset_count",
                "Likely offset/count pair for box edge/support metadata.",
            ),
        ):
            if offset + 8 <= len(payload):
                low = struct.unpack_from("<I", payload, offset)[0]
                high = struct.unpack_from("<I", payload, offset + 4)[0]
                data_type = "uint32[2]" if offset != 0x30 else "uint32[2]/index"
                fields.append(
                    _hkx_layout_field(
                        name=name,
                        offset=offset,
                        size=8,
                        data_type=data_type,
                        value={"low_u32": low, "high_u32": high},
                        description=description,
                        confidence="strong inference" if offset >= 0x38 else "experimental",
                        editable=False,
                    )
                )
        for offset, name, description in (
            (
                0x68,
                "convex_radius_or_collision_margin",
                "Likely box convex radius/collision margin. Kept read-only until the exact hknpBoxShape field role is confirmed.",
            ),
            (
                0x6C,
                "aabb_or_radius_factor",
                "Likely AABB expansion/radius factor for the box shape. Kept read-only until confirmed across more samples.",
            ),
        ):
            if offset + 4 <= len(payload):
                value = struct.unpack_from("<f", payload, offset)[0]
                if math.isfinite(value):
                    fields.append(
                        _hkx_layout_field(
                            name=name,
                            offset=offset,
                            size=4,
                            data_type="float32",
                            value=float(value),
                            description=description,
                            confidence="strong inference" if 0.0 <= value < 1_000_000.0 else "experimental",
                            editable=False,
                        )
                    )
        if len(payload) >= 0xC0:
            frame_rows: List[List[float]] = []
            for row_index in range(4):
                row_offset = 0x80 + row_index * 16
                row = list(struct.unpack_from("<ffff", payload, row_offset))
                frame_rows.append([float(component) for component in row])
                fields.append(
                    _hkx_layout_field(
                        name=f"box_local_frame_or_extent_row[{row_index}]",
                        offset=row_offset,
                        size=16,
                        data_type="float32[4]",
                        value=[float(component) for component in row],
                        description=(
                            "Likely local box frame, center, extent, or packed transform row. "
                            "Included for comparison between samples; not safe for GUI editing yet."
                        ),
                        confidence="experimental",
                        editable=False,
                    )
                )
            fields.append(
                _hkx_layout_field(
                    name="box_local_frame_or_extents",
                    offset=0x80,
                    size=0x40,
                    data_type="float32[4][4]",
                    value=frame_rows,
                    description=(
                        "Four-row hknpBoxShape float block observed in real Crimson Desert samples. "
                        "This is likely where local orientation/center/extents live, but exact field names "
                        "need more sample correlation before edits are enabled."
                    ),
                    confidence="experimental",
                    editable=False,
                )
            )


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    '_hkx_layout_field',
    'math',
    'struct',
)
def _hkx_record_layout_post_3(payload: bytes, record: HkxItemRecord, type_name: str, fields: List[Dict[str, object]], stride: Optional[int]) -> None:
    if not fields:
        if type_name.startswith("hknp"):
            for offset in range(0, min(len(payload), 256) - 3, 4):
                value = struct.unpack_from("<f", payload, offset)[0]
                if not math.isfinite(value) or abs(value) < 1e-8 or abs(value) > 1_000_000.0:
                    continue
                fields.append(
                    _hkx_layout_field(
                        name=f"finite_float_0x{offset:X}",
                        offset=offset,
                        size=4,
                        data_type="float32",
                        value=float(value),
                        description=(
                            "Finite float candidate in a modern Havok Physics payload. It is exported for schema "
                            "recovery only and is not editable until the field role is confirmed."
                        ),
                        confidence="raw",
                        editable=False,
                    )
                )
        for offset in range(0, min(len(payload), 64), 4):
            if offset + 4 > len(payload):
                break
            u32_value = struct.unpack_from("<I", payload, offset)[0]
            fields.append(
                _hkx_layout_field(
                    name=f"u32_0x{offset:X}",
                    offset=offset,
                    size=4,
                    data_type="uint32",
                    value=u32_value,
                    description="Unverified 32-bit word sample from this preserved payload.",
                    confidence="raw",
                    editable=False,
                )
            )
