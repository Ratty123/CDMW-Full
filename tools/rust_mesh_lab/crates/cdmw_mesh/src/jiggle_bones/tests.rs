use super::*;

fn hex<const N: usize>(text: &str) -> [u8; N] {
    assert_eq!(text.len(), 2 * N);
    std::array::from_fn(|i| u8::from_str_radix(&text[i * 2..i * 2 + 2], 16).unwrap())
}

fn double(record: &[u8], offset: usize) -> f64 {
    f64::from_le_bytes(record[offset..offset + 8].try_into().unwrap())
}

#[test]
fn python_reference_frames_include_native_state_feedback() {
    let mut last = None;
    let mut cases = 0;
    for line in include_str!("vectors.txt")
        .lines()
        .filter(|line| !line.starts_with('#'))
    {
        let fields: Vec<_> = line.split('|').collect();
        assert_eq!(fields.len(), 10);
        let name = fields[0];
        let previous = match fields[1] {
            "-" => None,
            "^" => Some(last.expect("chained fixture requires a prior result")),
            value => Some(hex(value)),
        };
        let command = hex(fields[2]);
        let shader = hex(fields[3]);
        let animation = hex(fields[4]);
        let character = hex(fields[5]);
        let params: [u8; 73] = hex(fields[6]);
        let result = step(StepInput {
            previous_bone: previous.as_ref(),
            command_bone: &command,
            shader_data: &shader,
            animation_matrix: &animation,
            character_transform: &character,
            view_position: std::array::from_fn(|i| double(&params, i * 8)),
            previous_view_position: std::array::from_fn(|i| double(&params, 24 + i * 8)),
            bone_scale: double(&params, 48),
            delta_time: double(&params, 56),
            original_bone_index: uint(&params, 64),
            update_frame_index: uint(&params, 68),
            reset_requested: params[72] != 0,
        })
        .unwrap_or_else(|error| panic!("{name}: {error}"));
        let expected: [u8; 116] = hex(fields[7]);
        // All f32 motion, timer, seed-input and retained bytes must match, not
        // just an approximate final pose. The next frame uses the native state.
        assert_eq!(result.bone, expected, "{name}: packed state");
        let expected_matrix: [u8; 128] = hex(fields[8]);
        for (i, value) in result.matrix.iter().flatten().enumerate() {
            let expected = double(&expected_matrix, i * 8);
            assert!(
                (value - expected).abs() <= 2e-11 * (1.0 + expected.abs()),
                "{name}: matrix element {i}, got {value}, expected {expected}"
            );
        }
        assert_eq!(result.reset, fields[9] == "1", "{name}: reset");
        last = Some(result.bone);
        cases += 1;
    }
    assert_eq!(cases, 51);
}

fn put_uint(record: &mut [u8], offset: usize, value: u32) {
    record[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn identity() -> [u8; 64] {
    let mut result = [0; 64];
    for i in 0..4 {
        store_floats(&mut result, 20 * i, &[1.0]).unwrap();
    }
    result
}

#[test]
fn command_address_lod_and_payload_contract() {
    let mut command: [u8; 48] = std::array::from_fn(|i| i as u8);
    put_uint(&mut command, 44, 6);
    let mut skeleton = [0; 124];
    put_uint(&mut skeleton, 32, 7);
    put_uint(&mut skeleton, 36, 99);
    let mut object = [0; 128];
    put_uint(&mut object, 0, 0x101);
    let mut shader = [0; 264];
    put_uint(&mut shader, 12, 20);
    let prepared = prepare_command(&command, &skeleton, &object, Some(&shader))
        .unwrap()
        .unwrap();
    assert_eq!(prepared.state_index, 33);
    assert_eq!(&prepared.bone[48..88], &command[..40]);
    assert_eq!(&prepared.bone[..48], &[0; 48]);
    assert_eq!(&prepared.bone[88..108], &[0; 20]);
    assert_eq!(uint(&prepared.bone, 108), 3);
    assert_eq!(uint(&prepared.bone, 112), 0);
    put_uint(&mut shader, 12, u32::MAX - 1);
    assert_eq!(
        prepare_command(&command, &skeleton, &object, Some(&shader))
            .unwrap()
            .unwrap()
            .state_index,
        11
    );
    assert!(prepare_command(&command, &skeleton, &object, None).is_err());
    put_uint(&mut object, 0, 2);
    assert_eq!(
        prepare_command(&command, &skeleton, &object, None).unwrap(),
        None
    );
    put_uint(&mut object, 0, 1);
    put_uint(&mut object, 84, u32::MAX);
    assert_eq!(
        prepare_command(&command, &skeleton, &object, None).unwrap(),
        None
    );
}

#[test]
fn mask_validates_only_the_consumed_entries_and_mode() {
    let mut shader = [0; 264];
    put_uint(&mut shader, 64, 2);
    put_uint(&mut shader, 68, 33);
    assert!(blend_override(&shader, 0, 0.3).is_err());
    put_uint(&mut shader, 64, 1);
    assert_eq!(blend_override(&shader, 0, 0.3).unwrap(), (1.0, 0.3));
    put_uint(&mut shader, 64, 2);
    put_uint(&mut shader, 68, 1);
    put_uint(&mut shader, 136, f32::NAN.to_bits());
    assert!(blend_override(&shader, 0, 0.3).is_err());
    assert_eq!(blend_override(&shader, 1, 0.3).unwrap(), (1.0, 0.3));
}

#[test]
fn rejects_consumed_invalid_motion_and_undefined_operations() {
    let previous = [0; 116];
    let mut command = [0; 116];
    let mut shader = [0; 264];
    store_floats(
        &mut shader,
        32,
        &[0.0, 1.0, 100.0, 100.0, 0.0, 1.0, 100.0, 100.0],
    )
    .unwrap();
    let animation = identity();
    let mut character = [0; 272];
    character[..64].copy_from_slice(&animation);
    character[192..256].copy_from_slice(&animation);
    let run = |previous: &[u8; 116],
               command: &[u8; 116],
               shader: &[u8; 264],
               animation: &[u8; 64],
               dt| {
        step(StepInput {
            previous_bone: Some(previous),
            command_bone: command,
            shader_data: shader,
            animation_matrix: animation,
            character_transform: &character,
            view_position: [0.0; 3],
            previous_view_position: [0.0; 3],
            bone_scale: 1.0,
            original_bone_index: 0,
            update_frame_index: 1,
            delta_time: dt,
            reset_requested: false,
        })
    };
    assert!(run(&previous, &command, &shader, &animation, -0.1).is_err());
    assert!(run(&previous, &command, &shader, &animation, f64::NAN).is_err());
    assert!(run(&previous, &command, &shader, &[0; 64], 0.25).is_err());
    let mut bad_shader = shader;
    store_floats(&mut bad_shader, 40, &[-1.0]).unwrap();
    assert!(run(&previous, &command, &bad_shader, &animation, 0.25).is_err());
    let mut bad_previous = previous;
    put_uint(&mut bad_previous, 0, f32::INFINITY.to_bits());
    assert!(run(&bad_previous, &command, &shader, &animation, 0.25).is_err());
    store_floats(&mut command, 72, &[1.0, 2.0, 0.5]).unwrap();
    put_uint(&mut command, 108, 3);
    put_uint(&mut command, 84, 4);
    store_floats(&mut shader, 36, &[0.0]).unwrap();
    assert!(
        run(&previous, &command, &shader, &animation, 0.25)
            .unwrap_err()
            .contains("linear damping")
    );
    put_uint(&mut command, 84, 10);
    store_floats(&mut shader, 52, &[0.0]).unwrap();
    assert!(
        run(&previous, &command, &shader, &animation, 0.25)
            .unwrap_err()
            .contains("angular damping")
    );
    assert!(unit([0.0; 3]).is_err());
}

#[test]
fn gpu_random_feedback_and_angle_endpoints() {
    let mut seed = 1;
    let values: Vec<_> = (0..8).map(|_| random(&mut seed)).collect();
    assert_eq!(values, [4210, 1236, 16264, 15735, 28297, 8608, 27987, 4706]);
    assert_eq!(wrap(PI).unwrap(), PI);
    assert_eq!(wrap(-PI).unwrap(), -PI);
    assert_eq!(wrap(TAU).unwrap(), 0.0);
    assert_eq!(wrap(-TAU).unwrap(), 0.0);
}
