use super::*;
use crate::jiggle_bones::{self, StepInput};

const IDENTITY: Matrix = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
];

fn frame(position: [f64; 3], marker: f64, weight: f64) -> Matrix {
    let mut result = IDENTITY;
    result[3][..3].copy_from_slice(&position);
    result[0][3] = marker;
    result[1][3] = weight;
    result
}

fn record(slots: [u32; 6], weights: [u8; 6], jiggle: u8, cloth: u8) -> [u8; 40] {
    let mut data = [0; 40];
    for group in 0..2 {
        let packed = (0..3)
            .map(|i| slots[group * 3 + i] << (i * 10))
            .sum::<u32>();
        data[20 + group * 4..24 + group * 4].copy_from_slice(&packed.to_le_bytes());
    }
    data[28..34].copy_from_slice(&weights);
    data[38] = jiggle;
    data[39] = cloth | 0xc0;
    data
}

fn input<'a>(
    record: &'a [u8; 40],
    skeletal: &'a [Matrix],
    jiggle: Option<&'a [Matrix]>,
) -> RenderInput<'a> {
    RenderInput {
        record,
        render_flags: 128,
        bone_palette: &[0],
        skinning_index_map: &[0],
        skeletal_matrices: skeletal,
        jiggle_matrices: jiggle,
        wind_weight: 0.0,
        wind_samples: None,
    }
}

fn point(matrix: &Matrix, value: [f64; 3]) -> [f64; 3] {
    std::array::from_fn(|j| (0..3).map(|i| value[i] * matrix[i][j]).sum::<f64>() + matrix[3][j])
}

fn near(actual: &Matrix, expected: &Matrix) {
    for (actual, expected) in actual.iter().flatten().zip(expected.iter().flatten()) {
        assert!(
            (actual - expected).abs() <= 1e-12 * (1.0 + expected.abs()),
            "got {actual}, expected {expected}"
        );
    }
}

#[test]
fn inverse_bind_scale_and_metadata_are_composed_in_order() {
    let animation = [
        [0.0, 1.0, 0.0, 9.0],
        [-1.0, 0.0, 0.0, 8.0],
        IDENTITY[2],
        [10.0, 20.0, 30.0, 1.0],
    ];
    let prepared = prepare_bone(
        &frame([-2.0, 0.0, 0.0], 0.0, 0.0),
        &animation,
        Some(&frame([12.0, 20.0, 30.0], 2.0, 0.7)),
        [2.0, 3.0, 4.0],
    )
    .unwrap();
    assert_eq!(
        point(&prepared.skeletal_matrix, [2.0, 0.0, 0.0]),
        [10.0, 20.0, 30.0]
    );
    assert_eq!(
        point(&prepared.skeletal_matrix, [3.0, 0.0, 0.0]),
        [10.0, 22.0, 30.0]
    );
    let simulated = prepared.jiggle_matrix.unwrap();
    assert_eq!(point(&simulated, [2.0, 0.0, 0.0]), [12.0, 20.0, 30.0]);
    assert_eq!(point(&simulated, [3.0, 0.0, 0.0]), [14.0, 20.0, 30.0]);
    assert_eq!(
        (
            prepared.skeletal_matrix[0][3],
            prepared.skeletal_matrix[1][3]
        ),
        (1.0, 0.7)
    );
    assert_eq!(simulated.map(|row| row[3]), [0.0, 0.0, 0.0, 1.0]);
    let disabled = prepare_bone(&IDENTITY, &animation, None, [1.0; 3]).unwrap();
    assert!(disabled.jiggle_matrix.is_none());
    assert_eq!(
        disabled.skeletal_matrix.map(|row| row[3]),
        [0.0, 0.0, 0.0, 1.0]
    );
}

#[test]
fn six_slots_normalize_after_both_maps_and_four_slots_ignore_guide_fields() {
    let data = record([0, 1, 2, 0, 1, 2], [10, 20, 30, 40, 50, 60], 0, 63);
    let matrices = [1.0, 10.0, 100.0].map(|x| frame([x, 0.0, 0.0], 0.0, 0.0));
    let mut args = input(&data, &matrices, None);
    args.bone_palette = &[2, 0, 1];
    args.skinning_index_map = &[1, 2, 0];
    near(
        &blend_vertex(args).unwrap(),
        &frame([9750.0 / 210.0, 0.0, 0.0], 0.0, 0.0),
    );
    for (flags, cloth, expected_x) in [(128, 62, 10.0), (640, 63, 0.0), (1152, 63, 0.0)] {
        let data = record([0, 0, 0, 0, 1023, 1022], [30, 0, 0, 0, 255, 255], 0, cloth);
        let jiggle = [frame([10.0, 0.0, 0.0], 0.0, 0.0)];
        let mut args = input(&data, &[IDENTITY], Some(&jiggle));
        args.render_flags = flags;
        near(
            &blend_vertex(args).unwrap(),
            &frame([expected_x, 0.0, 0.0], 0.0, 0.0),
        );
    }
}

#[test]
fn byte38_modes_and_weighted_overrides_are_not_spring_strengths() {
    for (byte, flags, blend) in [
        (0, 128, 1.0),
        (240, 128, 1.0),
        (249, 128, 0.4),
        (254, 128, 1.0 / 15.0),
        (255, 128, 0.0),
        (143, 128, 0.0),
        (240, 0, 15.0 / 255.0),
    ] {
        let data = record([0; 6], [255, 0, 0, 0, 0, 0], byte, 63);
        let ordinary = [frame([2.0, 0.0, 0.0], 0.0, 0.0)];
        let jiggle = [frame([17.0, 0.0, 0.0], 0.0, 0.0)];
        let mut args = input(&data, &ordinary, Some(&jiggle));
        args.render_flags = flags;
        near(
            &blend_vertex(args).unwrap(),
            &frame([2.0 + 15.0 * blend, 0.0, 0.0], 0.0, 0.0),
        );
    }
    let data = record([0, 1, 0, 0, 0, 0], [64, 192, 0, 0, 0, 0], 255, 63);
    let ordinary = [frame([0.0; 3], 1.0, 0.8), frame([0.0; 3], 0.0, 0.4)];
    let jiggle = [frame([20.0, 0.0, 0.0], 0.0, 0.0); 2];
    let mut args = input(&data, &ordinary, Some(&jiggle));
    args.bone_palette = &[0, 1];
    args.skinning_index_map = &[0, 1];
    // Weighted marker 1/4 selects weighted override 1/2; do not divide by marker.
    near(
        &blend_vertex(args).unwrap(),
        &frame([10.0, 0.0, 0.0], 0.0, 0.0),
    );
    for (weight, expected_x) in [(2.0, 20.0), (0.0, 0.0), (-0.5, 0.0)] {
        let data = record([0; 6], [255, 0, 0, 0, 0, 0], 255, 63);
        let ordinary = [frame([0.0; 3], 1.0, weight)];
        let jiggle = [frame([10.0, 0.0, 0.0], 0.0, 0.0)];
        let result = blend_vertex(input(
            &data,
            &ordinary,
            Some(if weight > 0.0 { &jiggle } else { &[] }),
        ))
        .unwrap();
        near(&result, &frame([expected_x, 0.0, 0.0], 0.0, 0.0));
    }
}

#[test]
fn wind_uses_original_bone_and_full_basis_before_vertex_blending() {
    let data = record([0; 6], [255, 0, 0, 0, 0, 0], 9, 63);
    let jiggle = [[
        [2.0, 0.0, 0.0, 0.0],
        [0.0, 3.0, 0.0, 0.0],
        [0.0, 0.0, 4.0, 0.0],
        [10.0, 20.0, 30.0, 1.0],
    ]];
    let mut samples = vec![IDENTITY; 1026];
    samples[1025] = [
        [0.0, 1.0, 0.0, 0.0],
        [-1.0, 0.0, 0.0, 0.0],
        IDENTITY[2],
        [1.0, 2.0, 3.0, 1.0],
    ];
    let mut args = input(&data, &[IDENTITY], Some(&jiggle));
    args.bone_palette = &[257];
    args.skinning_index_map = &[0; 258];
    args.wind_weight = 0.5;
    args.wind_samples = Some(&samples);
    near(
        &blend_vertex(args).unwrap(),
        &[
            [1.0, 0.6, 0.0, 0.0],
            [-0.4, 1.2, 0.0, 0.0],
            [0.0, 0.0, 2.2, 0.0],
            [4.2, 8.4, 12.6, 1.0],
        ],
    );

    let data = record([0; 6], [255, 0, 0, 0, 0, 0], 0, 63);
    let jiggle = [frame([2.0, 0.0, 0.0], 0.0, 0.0)];
    samples[1024] = frame([3.0, 0.0, 0.0], 0.5, 0.0);
    let mut args = input(&data, &[IDENTITY], Some(&jiggle));
    args.wind_weight = 1.0;
    args.wind_samples = Some(&samples);
    assert_eq!(
        point(&blend_vertex(args).unwrap(), [1.0, 0.0, 0.0]),
        [8.5, 0.0, 0.0]
    );
}

#[test]
fn zero_weights_and_disabled_jiggle_obey_actual_buffer_consumption() {
    let data = record([0; 6], [0; 6], 0, 63);
    let result = blend_vertex(input(&data, &[IDENTITY], Some(&[IDENTITY]))).unwrap();
    assert!(result.iter().all(|row| row[..3] == [0.0; 3]));
    for (flags, byte, active) in [(128, 0, false), (128, 255, true), (512, 0, true)] {
        let data = record([0; 6], [255, 0, 0, 0, 0, 0], byte, 63);
        let mut args = input(&data, &[IDENTITY], if active { Some(&[]) } else { None });
        args.render_flags = flags;
        args.wind_weight = 1.0;
        near(&blend_vertex(args).unwrap(), &IDENTITY);
    }
    let data = record([0, 1, 0, 0, 0, 0], [255, 0, 0, 0, 0, 0], 0, 63);
    assert!(
        blend_vertex(input(&data, &[IDENTITY], None))
            .unwrap_err()
            .contains("outside")
    );
    let data = record([0; 6], [255, 0, 0, 0, 0, 0], 0, 63);
    let mut args = input(&data, &[IDENTITY], Some(&[IDENTITY]));
    args.wind_weight = 1.0;
    assert!(blend_vertex(args).unwrap_err().contains("sample buffer"));
    assert!(blend_vertex(input(&data, &[frame([f64::NAN, 0.0, 0.0], 0.0, 0.0)], None)).is_err());
    assert!(prepare_bone(&IDENTITY, &IDENTITY, None, [f64::INFINITY; 3]).is_err());
}

fn packed<const N: usize>(values: &[f32], offset: usize) -> [u8; N] {
    let mut result = [0; N];
    for (i, value) in values.iter().enumerate() {
        result[offset + i * 4..offset + i * 4 + 4].copy_from_slice(&value.to_le_bytes());
    }
    result
}

#[test]
fn native_bone_step_reaches_a_guide_bound_render_vertex() {
    let pose = frame([2.0, 0.0, 0.0], 0.0, 0.0);
    let animation = packed(
        &pose.iter().flatten().map(|v| *v as f32).collect::<Vec<_>>(),
        0,
    );
    let mut character = [0; 272];
    let identity: [u8; 64] = packed(
        &IDENTITY
            .iter()
            .flatten()
            .map(|v| *v as f32)
            .collect::<Vec<_>>(),
        0,
    );
    character[..64].copy_from_slice(&identity);
    character[192..256].copy_from_slice(&identity);
    let state = packed(&[2.0, 0.0, 0.0, 4.0, 0.0, 0.0], 0);
    let shader = packed(&[0.0, 1.0, 100.0, 100.0, 0.0, 1.0, 100.0, 100.0], 32);
    let step = jiggle_bones::step(StepInput {
        previous_bone: Some(&state),
        command_bone: &[0; 116],
        shader_data: &shader,
        animation_matrix: &animation,
        character_transform: &character,
        view_position: [0.0; 3],
        previous_view_position: [0.0; 3],
        bone_scale: 1.0,
        original_bone_index: 0,
        update_frame_index: 1,
        delta_time: 0.25,
        reset_requested: false,
    })
    .unwrap();
    let prepared = prepare_bone(
        &frame([-2.0, 0.0, 0.0], 0.0, 0.0),
        &pose,
        Some(&step.matrix),
        [1.0; 3],
    )
    .unwrap();
    let data = record([0, 0, 0, 0, 1023, 1022], [255, 0, 0, 0, 255, 255], 9, 21);
    let result = blend_vertex(input(
        &data,
        &[prepared.skeletal_matrix],
        Some(&[prepared.jiggle_matrix.unwrap()]),
    ))
    .unwrap();
    assert_eq!(point(&result, [2.0, 0.0, 0.0]), [2.4, 0.0, 0.0]);
    // Canonical output can feed the separate guide-cloth stage; guide data
    // remains unconsumed here rather than being mistaken for skeletal slots.
    assert_eq!(result.map(|row| row[3]), [0.0, 0.0, 0.0, 1.0]);
}
