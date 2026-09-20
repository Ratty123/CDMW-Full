//! Decoded rotation branches of ComputePbdUpdateResult. The preview supplies the
//! flags/space explicitly; singular or unknown neighbor data is unsupported.
use glam::{DMat3, DVec3};

fn unit(value: DVec3) -> super::Result<DVec3> {
    let length = value.length();
    if !length.is_finite() || length == 0.0 {
        return Err("Degenerate guide rotation has no finite result.");
    }
    Ok(value / length)
}

pub(super) fn single_edge(
    index: usize,
    neighbors: [u16; 2],
    animation: &[DVec3],
    simulated: &[DVec3],
    result: &[DVec3],
) -> super::Result<DMat3> {
    // A valid second neighbor wins, including when its edge is too short.
    let neighbor = usize::from(if usize::from(neighbors[1]) < animation.len() {
        neighbors[1]
    } else {
        neighbors[0]
    });
    if neighbor >= animation.len() {
        return Ok(DMat3::IDENTITY);
    }
    let a = animation[index] - animation[neighbor];
    // Only the current endpoint uses the selected/interpolated result.
    let b = result[index] - simulated[neighbor];
    if a.length().min(b.length()) <= f64::from(0.01_f32) {
        return Ok(DMat3::IDENTITY);
    }
    let (a, b) = (unit(a)?, unit(b)?);
    let cosine = a.dot(b);
    if cosine < f64::from(-0.9999_f32) {
        // The shader uses -I here, not a proper 180-degree rotation.
        return Ok(-DMat3::IDENTITY);
    }
    let DVec3 { x, y, z } = a.cross(b);
    let h = 1.0 / (1.0 + cosine);
    let correction = DMat3::from_cols(
        DVec3::new(cosine + h * x * x, h * x * y + z, h * x * z - y),
        DVec3::new(h * x * y - z, cosine + h * y * y, h * y * z + x),
        DVec3::new(h * x * z + y, h * y * z - x, cosine + h * z * z),
    );
    if !correction.is_finite() {
        return Err("Degenerate guide rotation has no finite result.");
    }
    Ok(correction)
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
    fn single_edge_preserves_neighbor_priority_short_edges_and_shader_reversal() {
        let animation = [DVec3::ZERO, -DVec3::X, -DVec3::Y];
        let quarter_turn = DMat3::from_rotation_z(std::f64::consts::FRAC_PI_2);
        let mut simulated = [DVec3::ZERO, -DVec3::Y, -DVec3::Y];
        assert_eq!(
            single_edge(0, [1, 2], &animation, &simulated, &simulated).unwrap(),
            DMat3::IDENTITY
        );
        assert!(
            single_edge(0, [1, u16::MAX], &animation, &simulated, &simulated)
                .unwrap()
                .abs_diff_eq(quarter_turn, 1e-12)
        );
        simulated[2] *= 0.001;
        assert_eq!(
            single_edge(0, [1, 2], &animation, &simulated, &simulated).unwrap(),
            DMat3::IDENTITY
        );
        simulated[1] = DVec3::X;
        assert_eq!(
            single_edge(0, [1, u16::MAX], &animation, &simulated, &simulated).unwrap(),
            -DMat3::IDENTITY
        );
        assert_eq!(
            single_edge(0, [u16::MAX; 2], &animation, &simulated, &simulated).unwrap(),
            DMat3::IDENTITY
        );
    }

    #[test]
    fn single_edge_uses_result_endpoint_and_raw_neighbor_in_three_dimensions() {
        let animation = [DVec3::ZERO, -DVec3::X];
        let simulated = [DVec3::ZERO, -DVec3::X];
        let result = [DVec3::Y, DVec3::splat(99.)];
        let rotation = single_edge(0, [1, u16::MAX], &animation, &simulated, &result).unwrap();
        assert!(rotation.abs_diff_eq(DMat3::from_rotation_z(std::f64::consts::FRAC_PI_4), 1e-12));
        let simulated = [DVec3::ZERO, -DVec3::Y - DVec3::Z];
        let diagonal = std::f64::consts::FRAC_1_SQRT_2;
        let expected = DMat3::from_cols(
            DVec3::new(0., diagonal, diagonal),
            DVec3::new(-diagonal, 0.5, -0.5),
            DVec3::new(-diagonal, -0.5, 0.5),
        );
        assert!(
            single_edge(0, [1, u16::MAX], &animation, &simulated, &simulated)
                .unwrap()
                .abs_diff_eq(expected, 1e-12)
        );
    }

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
