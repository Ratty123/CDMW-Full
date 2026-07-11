pub(super) fn tag_item(marker: &[u8], payload: &[u8], flags: u32) -> Vec<u8> {
    let length = 4 + payload.len() as u32 + 4;
    let mut out = Vec::new();
    out.extend_from_slice(&(flags | length).to_be_bytes());
    out.extend_from_slice(marker);
    out.extend_from_slice(payload);
    out
}

pub(super) fn sample_hkx() -> Vec<u8> {
    let type_names = b"hknpCompoundShape\0hknpConvexShape\0hkFloat3\0\xff";
    let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
    let mut item_payload = vec![0u8; 12];
    item_payload.extend_from_slice(&0x10000001u32.to_le_bytes());
    item_payload.extend_from_slice(&0u32.to_le_bytes());
    item_payload.extend_from_slice(&1u32.to_le_bytes());
    item_payload.extend_from_slice(&0x20000002u32.to_le_bytes());
    item_payload.extend_from_slice(&32u32.to_le_bytes());
    item_payload.extend_from_slice(&4u32.to_le_bytes());
    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &[0u8; 64], 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn array_ref_hkx() -> Vec<u8> {
    let type_names = b"hkArray\0hkRefPtr\0hknpShape\0\xff";
    let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
    let mut data_payload = vec![0u8; 64];
    data_payload[0..8].copy_from_slice(&32u64.to_le_bytes());
    data_payload[8..12].copy_from_slice(&3u32.to_le_bytes());
    data_payload[12..16].copy_from_slice(&0x8000_0003u32.to_le_bytes());
    data_payload[16..24].copy_from_slice(&32u64.to_le_bytes());
    data_payload[32..36].copy_from_slice(&0.25f32.to_le_bytes());
    data_payload[36..40].copy_from_slice(&1.5f32.to_le_bytes());

    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 1u32),
        (0x1000_0002u32, 16u32, 1u32),
        (0x1000_0003u32, 32u32, 1u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    let mut indx_payload = Vec::new();
    for word in [0u32, 32u32, 1u32] {
        indx_payload.extend_from_slice(&word.to_le_bytes());
    }
    body.extend(tag_item(b"INDX", &indx_payload, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn nested_indx_ptch_hkx() -> Vec<u8> {
    let type_names = b"hkArray\0hkRefPtr\0hknpShape\0\xff";
    let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
    let mut data_payload = vec![0u8; 64];
    data_payload[16..24].copy_from_slice(&2u64.to_le_bytes());
    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 1u32),
        (0x1000_0002u32, 16u32, 1u32),
        (0x1000_0003u32, 32u32, 1u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }
    let mut item_section = Vec::new();
    item_section
        .extend_from_slice(&(0x4000_0000u32 | (8 + item_payload.len() as u32)).to_be_bytes());
    item_section.extend_from_slice(b"ITEM");
    item_section.extend_from_slice(&item_payload);
    let mut ptch_payload = Vec::new();
    for word in [1u32, 1, 0, 2, 1, 16] {
        ptch_payload.extend_from_slice(&word.to_le_bytes());
    }
    let mut indx_payload = item_section;
    indx_payload.extend(tag_item(b"PTCH", &ptch_payload, 0x40000000));

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend(tag_item(b"TPAD", b"", 0));
    body.extend(tag_item(b"INDX", &indx_payload, 0));
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn motor_hkx() -> Vec<u8> {
    let type_names = b"hknpPositionConstraintMotor\0\xff";
    let tna1 = [2u8, 0, 0];
    let mut data_payload = vec![0u8; 64];
    for (offset, value) in [
        (0x20usize, -1_000_000.0f32),
        (0x24usize, 1_000_000.0f32),
        (0x28usize, 0.8f32),
        (0x2Cusize, 1.0f32),
        (0x30usize, 2.0f32),
    ] {
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    let mut item_payload = vec![0u8; 12];
    item_payload.extend_from_slice(&0x1000_0001u32.to_le_bytes());
    item_payload.extend_from_slice(&0u32.to_le_bytes());
    item_payload.extend_from_slice(&1u32.to_le_bytes());

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn sphere_hkx() -> Vec<u8> {
    let type_names = b"hknpSphereShape\0\xff";
    let tna1 = [2u8, 0, 0];
    let mut data_payload = vec![0u8; 128];
    data_payload[0x68..0x6C].copy_from_slice(&0.25f32.to_le_bytes());
    let mut item_payload = vec![0u8; 12];
    item_payload.extend_from_slice(&0x1000_0001u32.to_le_bytes());
    item_payload.extend_from_slice(&0u32.to_le_bytes());
    item_payload.extend_from_slice(&1u32.to_le_bytes());

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn compressed_mass_hkx() -> Vec<u8> {
    let type_names = b"hknpShapeMassProperties\0hkCompressedMassProperties\0hkPackedVector3\0\xff";
    let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
    let mut data_payload = vec![0u8; 160];
    for (index, value) in [
        1.0f32, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0, 3.0, 0.0, 0.0, 1.0, 4.0, 5.0, 6.0, 7.0, 8.0,
    ]
    .iter()
    .copied()
    .enumerate()
    {
        data_payload[index * 4..index * 4 + 4].copy_from_slice(&value.to_le_bytes());
    }
    for (index, value) in [0x1122_3344u32, 0x5566_7788, 0x0001_0002, 0x0003_0004]
        .iter()
        .copied()
        .enumerate()
    {
        let offset = 64 + index * 4;
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    data_payload[128..140].copy_from_slice(&[0, 64, 128, 255, 1, 2, 3, 4, 250, 251, 252, 253]);
    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 1u32),
        (0x1000_0002u32, 64u32, 1u32),
        (0x2000_0003u32, 128u32, 3u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn scalar_enum_hkx() -> Vec<u8> {
    let type_names = b"unsigned int\0unsigned short\0unsigned long long\0hknpShapeType::Enum\0hknpShape::FlagsEnum\0\xff";
    let tna1 = [6u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0];
    let mut data_payload = vec![0u8; 80];
    for (index, value) in [7u32, 8, 0xABCD_EF01].iter().copied().enumerate() {
        let offset = index * 4;
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    for (index, value) in [1u16, 2, u16::MAX, 1024].iter().copied().enumerate() {
        let offset = 16 + index * 2;
        data_payload[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
    }
    for (index, value) in [0x1122_3344_5566_7788u64, 0x0102_0304_0506_0708]
        .iter()
        .copied()
        .enumerate()
    {
        let offset = 32 + index * 8;
        data_payload[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    data_payload[64..67].copy_from_slice(&[3, 4, 7]);
    data_payload[68..72].copy_from_slice(&0x10u32.to_le_bytes());
    data_payload[72..76].copy_from_slice(&0x20u32.to_le_bytes());

    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x2000_0001u32, 0u32, 3u32),
        (0x2000_0002u32, 16u32, 4u32),
        (0x2000_0003u32, 32u32, 2u32),
        (0x2000_0004u32, 64u32, 3u32),
        (0x2000_0005u32, 68u32, 2u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn box_hkx() -> Vec<u8> {
    let type_names = b"hknpBoxShape\0\xff";
    let tna1 = [2u8, 0, 0];
    let mut data_payload = vec![0u8; 192];
    for (offset, value) in [
        (0x30usize, 14u32),
        (0x38usize, 136u32),
        (0x3Cusize, 8u32),
        (0x40usize, 224u32),
        (0x44usize, 6u32),
        (0x48usize, 312u32),
        (0x4Cusize, 6u32),
        (0x50usize, 336u32),
        (0x54usize, 24u32),
        (0x58usize, 360u32),
        (0x5Cusize, 24u32),
        (0x60usize, 448u32),
        (0x64usize, 8u32),
    ] {
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    for (offset, value) in [(0x68usize, 0.015f32), (0x6Cusize, 0.008f32)] {
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    for (index, value) in [
        1.0f32, 0.0, 0.0, 0.075, 0.0, 1.0, 0.0, 0.048, 0.0, 0.0, 1.0, 0.009, -4.5, 1.0, 6.25, 0.5,
    ]
    .iter()
    .enumerate()
    {
        let offset = 0x80usize + index * 4;
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    let mut item_payload = vec![0u8; 12];
    item_payload.extend_from_slice(&0x1000_0001u32.to_le_bytes());
    item_payload.extend_from_slice(&0u32.to_le_bytes());
    item_payload.extend_from_slice(&1u32.to_le_bytes());

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn skeleton_support_hkx() -> Vec<u8> {
    let type_names =
        b"char\0HavokShapeNameProperty\0hkQsTransform\0hkBone\0hkInt16\0hkSkeleton\0hknpMaterial\0\xff";
    let tna1 = [8u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0, 6, 0];
    let mut data_payload = vec![0u8; 480];
    data_payload[0..10].copy_from_slice(b"Bone_Test\0");
    data_payload[32 + 0x20..32 + 0x24].copy_from_slice(&1u32.to_le_bytes());
    for row_index in 0..2usize {
        let base = 80 + row_index * 48;
        for (component, value) in [row_index as f32, 1.0, 2.0, 1.0].iter().enumerate() {
            data_payload[base + component * 4..base + component * 4 + 4]
                .copy_from_slice(&value.to_le_bytes());
        }
        for (component, value) in [0.0f32, 0.0, 0.0, 1.0].iter().enumerate() {
            data_payload[base + 16 + component * 4..base + 20 + component * 4]
                .copy_from_slice(&value.to_le_bytes());
        }
        for (component, value) in [1.0f32, 1.0, 1.0, 1.0].iter().enumerate() {
            data_payload[base + 32 + component * 4..base + 36 + component * 4]
                .copy_from_slice(&value.to_le_bytes());
        }
    }
    for (offset, value) in [(176usize, 1u32), (184usize, u32::MAX), (192usize, 1u32)] {
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    data_payload[208..210].copy_from_slice(&(-1i16).to_le_bytes());
    data_payload[210..212].copy_from_slice(&0i16.to_le_bytes());
    for (offset, value) in [
        (224 + 0x18, 176u32),
        (224 + 0x1C, 2u32),
        (224 + 0x28, 208u32),
        (224 + 0x2C, 2u32),
        (224 + 0x38, 80u32),
        (224 + 0x3C, 2u32),
    ] {
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    for material_index in 0..2usize {
        let base = 320 + material_index * 80;
        data_payload[base..base + 4]
            .copy_from_slice(&(27u32 + material_index as u32).to_le_bytes());
        for (component, value) in [1.0f32, 0.25, 0.1].iter().enumerate() {
            data_payload[base + 24 + component * 4..base + 28 + component * 4]
                .copy_from_slice(&value.to_le_bytes());
        }
        data_payload[base + 48..base + 52].copy_from_slice(&5.0f32.to_le_bytes());
    }
    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 11u32),
        (0x1000_0002u32, 32u32, 1u32),
        (0x2000_0003u32, 80u32, 2u32),
        (0x2000_0004u32, 176u32, 2u32),
        (0x2000_0005u32, 208u32, 2u32),
        (0x1000_0006u32, 224u32, 1u32),
        (0x2000_0007u32, 320u32, 2u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn skeleton_mapper_support_hkx() -> Vec<u8> {
    let type_names =
        b"char\0hkaSkeletonMapper\0hkaSkeletonMapperData::SimpleMapping\0hkaAnimationContainer\0int\0\xff";
    let tna1 = [6u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0];
    let mut data_payload = vec![0u8; 512];
    data_payload[0..15].copy_from_slice(b"SkeletonMapper\0");
    for (offset, value) in [(32 + 0x20, 17u32), (32 + 0x28, 19u32), (32 + 0x60, 2u32)] {
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    for row_index in 0..2usize {
        let base = 240 + row_index * 64;
        for (offset, value) in [
            (0usize, row_index as u32),
            (4usize, row_index as u32 + 10),
            (8usize, row_index as u32 + 20),
            (0x3Cusize, row_index as u32 + 30),
        ] {
            data_payload[base + offset..base + offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        for (component, value) in [0.5f32 + row_index as f32, 1.0, 1.0, 1.0]
            .iter()
            .enumerate()
        {
            data_payload[base + 0x20 + component * 4..base + 0x24 + component * 4]
                .copy_from_slice(&value.to_le_bytes());
        }
    }
    data_payload[368 + 0x18..368 + 0x1C].copy_from_slice(&4u32.to_le_bytes());
    for (index, value) in [0i32, 1, 2, 3].iter().enumerate() {
        let offset = 480 + index * 4;
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 15u32),
        (0x1000_0002u32, 32u32, 1u32),
        (0x2000_0003u32, 240u32, 2u32),
        (0x1000_0004u32, 368u32, 1u32),
        (0x2000_0005u32, 480u32, 4u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn root_container_hkx() -> Vec<u8> {
    let type_names = b"hkRootLevelContainer\0hkRootLevelContainer::NamedVariant\0hknpPhysicsSceneData\0hknpConstraintCinfo\0\xff";
    let tna1 = [5u8, 0, 0, 1, 0, 2, 0, 3, 0];
    let mut data_payload = vec![0u8; 160];
    data_payload[0..8].copy_from_slice(&32u64.to_le_bytes());
    data_payload[8..12].copy_from_slice(&1u32.to_le_bytes());
    data_payload[12..16].copy_from_slice(&0x8000_0001u32.to_le_bytes());
    data_payload[32..40].copy_from_slice(&72u64.to_le_bytes());
    data_payload[40..48].copy_from_slice(&88u64.to_le_bytes());
    data_payload[48..56].copy_from_slice(&96u64.to_le_bytes());
    data_payload[96..100].copy_from_slice(&128u32.to_le_bytes());
    data_payload[100..104].copy_from_slice(&1u32.to_le_bytes());
    data_payload[128..132].copy_from_slice(&32u32.to_le_bytes());
    data_payload[132..136].copy_from_slice(&96u32.to_le_bytes());
    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 1u32),
        (0x1000_0002u32, 32u32, 1u32),
        (0x1000_0003u32, 96u32, 1u32),
        (0x1000_0004u32, 128u32, 1u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn root_reference_payload_hkx() -> Vec<u8> {
    let type_names = b"hkRefVariant\0hkStringPtr\0hkMemoryResourceContainer\0hknpPhysicsSystemData\0hknpConstraintData\0hknpRefDragProperties\0hknpRefMassDistribution\0\xff";
    let tna1 = [8u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0, 6, 0];
    let mut data_payload = vec![0u8; 256];
    data_payload[0..8].copy_from_slice(&64u64.to_le_bytes());
    data_payload[8..12].copy_from_slice(&4u32.to_le_bytes());
    data_payload[12..16].copy_from_slice(&8u32.to_le_bytes());
    data_payload[16..24].copy_from_slice(&80u64.to_le_bytes());
    data_payload[24..28].copy_from_slice(&12u32.to_le_bytes());
    data_payload[28..32].copy_from_slice(&16u32.to_le_bytes());
    for (base, pair_a, pair_b, value) in [
        (32usize, 64u32, 2u32, 0.25f32),
        (64usize, 112u32, 1u32, 1.5f32),
        (112usize, 160u32, 6u32, 2.5f32),
        (160usize, 208u32, 7u32, 0.75f32),
        (208usize, 32u32, 9u32, 3.25f32),
    ] {
        data_payload[base..base + 4].copy_from_slice(&pair_a.to_le_bytes());
        data_payload[base + 4..base + 8].copy_from_slice(&pair_b.to_le_bytes());
        data_payload[base + 16..base + 20].copy_from_slice(&value.to_le_bytes());
    }
    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 1u32),
        (0x1000_0002u32, 16u32, 1u32),
        (0x1000_0003u32, 32u32, 1u32),
        (0x1000_0004u32, 64u32, 1u32),
        (0x1000_0005u32, 112u32, 1u32),
        (0x1000_0006u32, 160u32, 1u32),
        (0x1000_0007u32, 208u32, 1u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn body_constraint_reference_hkx() -> Vec<u8> {
    let type_names = b"hknpPhysicsSystemData\0hknpPhysicsSystemData::ExtendedBodyCinfo\0hknpConstraintCinfo\0\xff";
    let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
    let mut data_payload = vec![0u8; 256];
    for (offset, low, high) in [
        (0x00usize, 320u32, 2u32),
        (0x08usize, 352u32, 3u32),
        (0x10usize, 64u32, 1u32),
        (0x18usize, 192u32, 1u32),
        (0x20usize, 400u32, 4u32),
    ] {
        data_payload[offset..offset + 4].copy_from_slice(&low.to_le_bytes());
        data_payload[offset + 4..offset + 8].copy_from_slice(&high.to_le_bytes());
    }
    for (offset, low, high) in [
        (64usize + 0x08, 400u32, 12u32),
        (64usize + 0x10, 352u32, 3u32),
        (64usize + 0x18, 27u32, 5u32),
        (64usize + 0x20, 99u32, 2u32),
        (64usize + 0x60, 123u32, 456u32),
    ] {
        data_payload[offset..offset + 4].copy_from_slice(&low.to_le_bytes());
        data_payload[offset + 4..offset + 8].copy_from_slice(&high.to_le_bytes());
    }
    for (index, value) in [1.0f32, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0, 3.0]
        .iter()
        .copied()
        .enumerate()
    {
        let offset = 64 + 0x30 + index * 4;
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    for (offset, low, high) in [
        (192usize + 0x00, 10u32, 0u32),
        (192usize + 0x08, 11u32, 0u32),
        (192usize + 0x10, 160u32, 1u32),
        (192usize + 0x18, 7u32, 9u32),
    ] {
        data_payload[offset..offset + 4].copy_from_slice(&low.to_le_bytes());
        data_payload[offset + 4..offset + 8].copy_from_slice(&high.to_le_bytes());
    }
    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 1u32),
        (0x1000_0002u32, 64u32, 1u32),
        (0x1000_0003u32, 192u32, 1u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn compound_blocker_hkx() -> Vec<u8> {
    let type_names = b"hknpCompoundShape\0hknpShapeInstance\0hkcdSimdTreeNamespace::Node\0hknpShapeProperties::Entry\0hkFreeListArrayElement<tVALUE_TYPE=7>\0hknpShapeMassProperties\0\xff";
    let tna1 = [7u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0];
    let mut data_payload = vec![0u8; 416];
    for (offset, value) in [
        (0x20usize, 128u32),
        (0x24usize, 2u32),
        (0x30usize, 192u32),
        (0x34usize, 2u32),
        (0x40usize, 288u32),
        (0x44usize, 2u32),
    ] {
        data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    for base in [128usize, 160, 192, 208, 256, 272, 288, 320] {
        for index in 0..4usize {
            data_payload[base + index * 4..base + index * 4 + 4]
                .copy_from_slice(&((base + index) as u32).to_le_bytes());
        }
    }
    for (index, value) in [
        1.0f32, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0, 3.0, 0.0, 0.0, 1.0, 4.0, 5.0, 6.0, 7.0, 8.0,
    ]
    .iter()
    .enumerate()
    {
        data_payload[352 + index * 4..352 + index * 4 + 4].copy_from_slice(&value.to_le_bytes());
    }
    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 1u32),
        (0x2000_0002u32, 128u32, 2u32),
        (0x2000_0003u32, 192u32, 2u32),
        (0x2000_0004u32, 256u32, 2u32),
        (0x2000_0005u32, 288u32, 2u32),
        (0x1000_0006u32, 352u32, 1u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}

pub(super) fn real_hkclass_metadata_hkx() -> Vec<u8> {
    let type_names = b"char\0hkClass\0hkClassMember\0hknpFoo\0\xff";
    let tna1 = [5u8, 0, 0, 1, 0, 2, 0, 3, 0];
    let mut data_payload = vec![0u8; 288];
    data_payload[16..24].copy_from_slice(b"hknpFoo\0");
    data_payload[32..37].copy_from_slice(b"mass\0");
    data_payload[48..54].copy_from_slice(b"child\0");

    data_payload[80..88].copy_from_slice(&2u64.to_le_bytes());
    data_payload[104] = 11;
    data_payload[105] = 0;
    data_payload[106..108].copy_from_slice(&0u16.to_le_bytes());
    data_payload[108..110].copy_from_slice(&0x1234u16.to_le_bytes());
    data_payload[110..112].copy_from_slice(&0x20u16.to_le_bytes());

    data_payload[120..128].copy_from_slice(&3u64.to_le_bytes());
    data_payload[128..136].copy_from_slice(&5u64.to_le_bytes());
    data_payload[144] = 20;
    data_payload[145] = 25;
    data_payload[146..148].copy_from_slice(&0u16.to_le_bytes());
    data_payload[148..150].copy_from_slice(&1u16.to_le_bytes());
    data_payload[150..152].copy_from_slice(&0x28u16.to_le_bytes());

    data_payload[160..168].copy_from_slice(&1u64.to_le_bytes());
    data_payload[176..180].copy_from_slice(&64u32.to_le_bytes());
    data_payload[200..208].copy_from_slice(&4u64.to_le_bytes());
    data_payload[208..212].copy_from_slice(&2u32.to_le_bytes());
    data_payload[232..236].copy_from_slice(&4u32.to_le_bytes());
    data_payload[236..240].copy_from_slice(&3u32.to_le_bytes());
    data_payload[240..244].copy_from_slice(&0xABCDEF01u32.to_le_bytes());

    let mut item_payload = vec![0u8; 12];
    for (raw_type_flags, offset, count) in [
        (0x1000_0001u32, 0u32, 1u32),
        (0x1000_0001u32, 16u32, 8u32),
        (0x1000_0001u32, 32u32, 5u32),
        (0x1000_0001u32, 48u32, 6u32),
        (0x1000_0003u32, 80u32, 2u32),
        (0x1000_0002u32, 160u32, 1u32),
    ] {
        item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
        item_payload.extend_from_slice(&offset.to_le_bytes());
        item_payload.extend_from_slice(&count.to_le_bytes());
    }

    let mut body = b"TAG0".to_vec();
    body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
    body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
    body.extend(tag_item(b"TST1", type_names, 0x40000000));
    body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
    body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
    body.extend_from_slice(b"ITEM");
    body.extend(item_payload);
    let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
    out.extend(body);
    out
}
