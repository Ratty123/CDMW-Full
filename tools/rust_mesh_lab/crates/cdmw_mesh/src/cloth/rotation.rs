//! Decoded two-edge branch of ComputePbdUpdateResult. The preview supplies the
//! flags/space explicitly; singular or unknown neighbor data is unsupported.
use glam::{DMat3, DVec3};

fn unit(value: DVec3) -> super::Result<DVec3> {
    let length = value.length();
    if !length.is_finite() || length == 0.0 {
        return Err("Degenerate guide rotation has no finite result.");
    }
    Ok(value / length)
}

pub(super) fn two_edge(
    index: usize,
    neighbors: [u16; 2],
    animation: &[DVec3],
    simulated: &[DVec3],
) -> super::Result<DMat3> {
    let mut directions = [(DVec3::Y, DVec3::Y), (DVec3::X, DVec3::X)];
    for (slot, neighbor) in neighbors.into_iter().enumerate() {
        let neighbor = usize::from(neighbor);
        if neighbor >= animation.len() {
            continue;
        }
        let input = animation[neighbor] - animation[index];
        let output = simulated[neighbor] - simulated[index];
        let a = unit(input)?;
        let b = unit(output)?;
        let blend = (output.length() / (f64::from(0.8_f32) * input.length())).clamp(0.0, 1.0);
        directions[slot] = (a, unit(a.lerp(b, blend))?);
    }
    let basis = |y: DVec3, second: DVec3| -> super::Result<DMat3> {
        let z = unit(second.cross(y))?;
        let x = unit(y.cross(z))?;
        Ok(DMat3::from_cols(x, y, z))
    };
    let input = basis(directions[0].0, directions[1].0)?;
    let output = basis(directions[0].1, directions[1].1)?;
    // Python reference rows are transposed by glam's column representation.
    let correction = output * input.inverse();
    if !correction.is_finite() {
        return Err("Degenerate guide rotation has no finite result.");
    }
    Ok(correction)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decoded_frame_alignment_and_compression_match_reference_vectors() {
        let animation = [DVec3::ZERO, DVec3::Y, DVec3::X];
        let simulated = [DVec3::ZERO, -DVec3::X, DVec3::Y];
        let rotation = two_edge(0, [1, 2], &animation, &simulated).unwrap();
        assert!(rotation.abs_diff_eq(DMat3::from_rotation_z(std::f64::consts::FRAC_PI_2), 1e-12));
        let compressed = f64::from(0.8_f32) / 2.0;
        let simulated = simulated.map(|p| p * compressed);
        let rotation = two_edge(0, [1, 2], &animation, &simulated).unwrap();
        assert!(rotation.abs_diff_eq(DMat3::from_rotation_z(std::f64::consts::FRAC_PI_4), 1e-12));
        assert_eq!(
            two_edge(0, [u16::MAX; 2], &animation, &simulated).unwrap(),
            DMat3::IDENTITY
        );
        assert!(two_edge(0, [0, 2], &animation, &simulated).is_err());
        assert!(two_edge(0, [1, 1], &animation, &simulated).is_err());
    }
}
