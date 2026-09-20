use super::*;

fn hex<const N: usize>(text: &str) -> [u8; N] {
    assert_eq!(text.len(), N * 2);
    std::array::from_fn(|i| u8::from_str_radix(&text[2 * i..2 * i + 2], 16).unwrap())
}

#[test]
fn sample_frames_match_python_with_native_state_feedback() {
    let mut previous = None;
    let mut count = 0;
    for line in include_str!("vectors.txt")
        .lines()
        .filter(|line| !line.starts_with('#'))
    {
        let fields: Vec<_> = line.split('|').collect();
        assert_eq!(fields.len(), 6);
        let input = if fields[2] == "^" {
            previous.unwrap()
        } else {
            hex(fields[2])
        };
        let index = fields[1].parse().unwrap();
        let output = step(&input, &hex(fields[3]), index).expect(fields[0]);
        assert_eq!(
            output.sample,
            hex::<96>(fields[4]),
            "{}: packed state",
            fields[0]
        );
        let expected = hex::<128>(fields[5]);
        for (i, actual) in output.matrix.iter().flatten().enumerate() {
            let expected = f64::from_le_bytes(expected[8 * i..8 * i + 8].try_into().unwrap());
            assert!(
                (actual - expected).abs() <= 2e-11 * (1.0 + expected.abs()),
                "{}: matrix[{i}], {actual} != {expected}",
                fields[0]
            );
        }
        assert_eq!(output.matrix_index, index + 1024);
        previous = Some(output.sample);
        count += 1;
    }
    assert_eq!(count, 41);
}

#[test]
fn sample_rejects_invalid_index_and_consumed_values() {
    let mut global = [0; 224];
    let previous = [0; 96];
    assert!(step(&previous, &global, 512).is_err());
    store_floats(&mut global, 84, &[-1.0]).unwrap();
    assert!(
        step(&previous, &global, 0)
            .unwrap_err()
            .contains("nonnegative")
    );
    global[84..88].copy_from_slice(&f32::NAN.to_le_bytes());
    assert!(step(&previous, &global, 0).unwrap_err().contains("finite"));
    global[140..144].copy_from_slice(&1_u32.to_le_bytes());
    assert_eq!(step(&previous, &global, 0).unwrap().sample, previous);
}
