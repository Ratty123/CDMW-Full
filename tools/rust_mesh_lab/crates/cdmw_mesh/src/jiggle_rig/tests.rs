use super::*;

const IDENTITY: Matrix = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
];

fn translated(mut matrix: Matrix, x: f64, y: f64) -> Matrix {
    matrix[3][0] = x;
    matrix[3][1] = y;
    matrix
}

fn snapshot() -> RigSnapshot {
    let root = [
        [0.0, 1.0, 0.0, 0.0],
        [-1.0, 0.0, 0.0, 0.0],
        IDENTITY[2],
        [10.0, 20.0, 0.0, 1.0],
    ];
    let inverse = [
        [0.0, -1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0],
        IDENTITY[2],
        [-20.0, 10.0, 0.0, 1.0],
    ];
    RigSnapshot {
        bone_palette: vec![1, 0],
        parents: vec![-1, 0],
        inverse_bind_matrices: vec![inverse, translated(inverse, -22.0, 10.0)],
        neutral_global_matrices: vec![root, translated(root, 10.0, 22.0)],
        neutral_local_matrices: vec![root, translated(IDENTITY, 2.0, 0.0)],
    }
}

fn packed<const N: usize>(values: &[f32], offset: usize) -> [u8; N] {
    let mut result = [0; N];
    for (i, value) in values.iter().enumerate() {
        result[offset + i * 4..offset + i * 4 + 4].copy_from_slice(&value.to_le_bytes());
    }
    result
}

fn uint(record: &mut [u8], offset: usize, value: u32) {
    record[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn run(
    rig: &Rig,
    previous: Option<&FrameOutput>,
    frame: u32,
    commands: &BTreeMap<u32, [u8; 116]>,
    poses: &BTreeMap<u32, Matrix>,
) -> Result<FrameOutput> {
    let shader = packed(&[0.0, 1.0, 100.0, 100.0, 0.0, 1.0, 100.0, 100.0], 32);
    let identity: [u8; 64] = packed(
        &IDENTITY
            .iter()
            .flatten()
            .map(|v| *v as f32)
            .collect::<Vec<_>>(),
        0,
    );
    let mut character = [0; 272];
    character[..64].copy_from_slice(&identity);
    character[192..256].copy_from_slice(&identity);
    rig.step(
        previous,
        FrameInput {
            shader_data: &shader,
            character_transform: &character,
            view_position: [0.0; 3],
            previous_view_position: [0.0; 3],
            bone_scale: 1.0,
            character_space_scales: &vec![[1.0; 3]; rig.bone_count()],
            update_frame_index: frame,
            delta_time: 0.25,
            reset_requested: false,
            local_pose_overrides: poses,
            commands,
        },
    )
}

fn impulse() -> [u8; 116] {
    let mut record = packed(&[4.0, 0.0, 0.0], 48);
    record[72..84].copy_from_slice(&packed::<12>(&[1.0, 2.0, 1.0], 0));
    uint(&mut record, 84, 4);
    uint(&mut record, 108, 3);
    record
}

fn value(record: &[u8], offset: usize) -> f32 {
    f32::from_le_bytes(record[offset..offset + 4].try_into().unwrap())
}

fn assert_point(actual: [f64; 3], expected: [f64; 3], tolerance: f64) {
    for (actual, expected) in actual.into_iter().zip(expected) {
        assert!(
            (actual - expected).abs() <= tolerance,
            "got {actual}, expected {expected}"
        );
    }
}

#[test]
fn rest_pose_is_preserved_and_forward_parents_retain_original_ordinals() {
    let source = snapshot();
    let rig = Rig::new(source.clone()).unwrap();
    assert_eq!(
        rig.pose(&BTreeMap::new()).unwrap(),
        source.neutral_global_matrices
    );
    let same = BTreeMap::from([(1, source.neutral_local_matrices[1])]);
    assert_eq!(rig.pose(&same).unwrap(), source.neutral_global_matrices);
    let mut forward = source;
    forward.parents = vec![1, -1];
    forward.inverse_bind_matrices.reverse();
    forward.neutral_global_matrices.reverse();
    forward.neutral_local_matrices.reverse();
    let rig = Rig::new(forward.clone()).unwrap();
    assert_eq!(rig.order, [1, 0]);
    let pose = rig
        .pose(&BTreeMap::from([(
            1,
            translated(forward.neutral_local_matrices[1], 10.0, 21.0),
        )]))
        .unwrap();
    assert_eq!(pose[0][3], [10.0, 23.0, 0.0, 1.0]);
    assert_eq!(pose[1][3], [10.0, 21.0, 0.0, 1.0]);
    assert_eq!(rig.palette(), &[1, 0]);
}

#[test]
fn pending_impulse_continues_without_reinjection_or_simulated_parent_feedback() {
    let rig = Rig::new(snapshot()).unwrap();
    let commands = BTreeMap::from([(0, impulse())]);
    let first = run(&rig, None, 1, &commands, &BTreeMap::new()).unwrap();
    let second = run(&rig, Some(&first), 2, &BTreeMap::new(), &BTreeMap::new()).unwrap();
    assert_eq!(first.reset_bones, [0, 1]);
    assert!(second.reset_bones.is_empty());
    for (frame, expected) in [(&first, 1.0), (&second, 2.0)] {
        assert_point(
            frame.jiggle_matrices[0][3][..3].try_into().unwrap(),
            [expected, 0.0, 0.0],
            2e-5,
        );
        assert_point(
            frame.jiggle_matrices[1][3][..3].try_into().unwrap(),
            [0.0; 3],
            2e-5,
        );
    }
    assert_eq!(value(&second.bone_states[0], 104), 0.5);
    assert_eq!(value(&second.bone_states[0], 12), 4.0);
}

#[test]
fn neutral_binding_inverts_the_blend_and_preserves_sculpted_positions() {
    let mut source = snapshot();
    // Different bone scales make inverse(blend) different from blend(inverse).
    let mut skin0 = translated(IDENTITY, 2.0, 0.0);
    let mut skin1 = translated(IDENTITY, 5.0, 1.0);
    skin0[0][0] = 2.0;
    skin1[0][0] = 4.0;
    source.neutral_global_matrices[0] = multiply(&source.neutral_global_matrices[0], &skin0);
    source.neutral_global_matrices[1] = multiply(&source.neutral_global_matrices[1], &skin1);
    source.neutral_local_matrices[0] = source.neutral_global_matrices[0];
    source.neutral_local_matrices[1] = multiply(
        &source.neutral_global_matrices[1],
        &inverse_affine(&source.neutral_global_matrices[0]).unwrap(),
    );
    let rig = Rig::new(source).unwrap();
    let mut record = [0; 40];
    uint(&mut record, 20, 1 << 10);
    record[28..30].copy_from_slice(&[128, 128]);
    record[38] = 9;
    record[39] = 63;
    // Source (10,22,0) becomes (33.5,22.5,0). A +1.5 sculpt edit stays present.
    let displayed = [[33.5, 22.5, 0.0], [35.0, 22.5, 0.0]];
    let binding = rig.bind_vertices(&displayed, &[record; 2], 128).unwrap();
    assert!((binding.to_source[0][0][0] - 1.0 / 3.0).abs() < 1e-12);
    let rest = run(&rig, None, 1, &BTreeMap::new(), &BTreeMap::new()).unwrap();
    let rest_positions = binding
        .positions(&rig, &rest, &[9; 2], true, 0.0, None)
        .unwrap();
    for (position, expected) in rest_positions.into_iter().zip(displayed) {
        assert_point(position, expected, 1e-12);
    }
    let mut moving = run(
        &rig,
        Some(&rest),
        2,
        &BTreeMap::from([(0, impulse())]),
        &BTreeMap::new(),
    )
    .unwrap();
    let positions = binding
        .positions(&rig, &moving, &[9; 2], true, 0.0, None)
        .unwrap();
    // Half the skin is attached to the moving bone, then nibble9 contributes0.4.
    assert_point(positions[0], [33.7, 22.5, 0.0], 2e-5);
    assert_point(positions[1], [35.2, 22.5, 0.0], 2e-5);
    moving.skeletal_matrices[0][0][3] = 1.0;
    moving.skeletal_matrices[0][1][3] = 1.0;
    let overridden = binding
        .positions(&rig, &moving, &[255; 2], true, 0.0, None)
        .unwrap();
    assert_point(overridden[0], [33.75, 22.5, 0.0], 2e-5);
    let disabled = binding
        .positions(&rig, &moving, &[255; 2], false, 0.0, None)
        .unwrap();
    for (position, expected) in disabled.into_iter().zip(displayed) {
        assert_point(position, expected, 1e-12);
    }
}

#[test]
fn malformed_or_inconsistent_rig_snapshots_are_rejected() {
    for fault in 0..9 {
        let mut data = snapshot();
        match fault {
            0 => data.parents = vec![],
            1 => {
                data.inverse_bind_matrices.pop();
            }
            2 => data.parents = vec![1, 0],
            3 => data.parents[1] = 1,
            4 => data.bone_palette = vec![2],
            5 => data.bone_palette.clear(),
            6 => data.neutral_global_matrices[0][0][3] = 1.0,
            7 => data.neutral_local_matrices[1][3][0] = 3.0,
            8 => data.inverse_bind_matrices[0][0][0] = f64::NAN,
            _ => unreachable!(),
        }
        assert!(Rig::new(data).is_err(), "accepted fault {fault}");
    }
}

#[test]
fn frames_and_bindings_cannot_be_reused_with_a_different_rig() {
    let rig = Rig::new(snapshot()).unwrap();
    let other = Rig::new(snapshot()).unwrap();
    let frame = run(&rig, None, 1, &BTreeMap::new(), &BTreeMap::new()).unwrap();
    let mut record = [0; 40];
    record[28] = 255;
    record[39] = 63;
    let binding = rig
        .bind_vertices(&[[10.0, 22.0, 0.0]], &[record], 128)
        .unwrap();
    assert!(run(&other, Some(&frame), 2, &BTreeMap::new(), &BTreeMap::new()).is_err());
    let other_frame = run(&other, None, 1, &BTreeMap::new(), &BTreeMap::new()).unwrap();
    assert!(
        binding
            .positions(&other, &other_frame, &[0], true, 0.0, None)
            .is_err()
    );
    assert!(
        binding
            .positions(&rig, &other_frame, &[0], true, 0.0, None)
            .is_err()
    );
    assert!(
        binding
            .positions(&rig, &frame, &[], true, 0.0, None)
            .is_err()
    );
    assert!(
        run(
            &rig,
            None,
            1,
            &BTreeMap::from([(2, impulse())]),
            &BTreeMap::new()
        )
        .is_err()
    );
    assert!(rig.pose(&BTreeMap::from([(2, IDENTITY)])).is_err());
    assert!(rig.pose(&BTreeMap::from([(0, [[0.0; 4]; 4])])).is_err());
    let mut incomplete = frame;
    incomplete.bone_states.pop();
    assert!(
        run(
            &rig,
            Some(&incomplete),
            2,
            &BTreeMap::new(),
            &BTreeMap::new()
        )
        .is_err()
    );
}

#[test]
fn invalid_geometry_and_singular_blended_rest_transforms_fail_binding() {
    let rig = Rig::new(snapshot()).unwrap();
    let mut record = [0; 40];
    record[39] = 63;
    assert!(rig.bind_vertices(&[], &[], 128).is_err());
    assert!(rig.bind_vertices(&[[0.0; 3]], &[], 128).is_err());
    // All-zero raw weights produce a singular zero XYZ basis, not identity.
    assert!(rig.bind_vertices(&[[0.0; 3]], &[record], 128).is_err());
    record[28] = 255;
    assert!(rig.bind_vertices(&[[f64::NAN; 3]], &[record], 128).is_err());
    uint(&mut record, 20, 1023 << 10);
    assert!(rig.bind_vertices(&[[0.0; 3]], &[record], 128).is_err());
}
