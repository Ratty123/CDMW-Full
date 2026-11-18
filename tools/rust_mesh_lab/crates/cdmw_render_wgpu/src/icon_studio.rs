//! The environment of the "Game icon studio" lighting preset.
//!
//! The game bakes its item icons ahead of time; the rig that lit them is not in
//! the shipped archives. This is a studio of our own, tuned against those icons:
//! soft boxes around the camera and a lit room with a light floor. Everything a
//! surface receives comes from this one description. A reflection reads it
//! blurred for the surface's roughness, and the diffuse term reads its
//! irradiance, so a metal and the cloth beside it are lit by the same room.
//!
//! The soft boxes are spherical Gaussians, `radiance * exp(sharpness * (cos - 1))`,
//! and the room is `mean + slope * up`. Both have closed forms for the blur and
//! for the irradiance, so there is no cube map to build, filter or cache: the
//! shader evaluates the studio directly. The constants live here and are written
//! into the shader source by [`wgsl`], which keeps the shader and the tests below
//! on one set of numbers.

use glam::Vec3;

pub(crate) struct SoftBox {
    /// Direction to the box as (camera right, camera up, towards the camera).
    pub axis: [f32; 3],
    pub sharpness: f32,
    pub radiance: [f32; 3],
}

/// The first box is the key: it is the one that casts the shadow.
pub(crate) const SOFT_BOXES: [SoftBox; 5] = [
    SoftBox {
        axis: [-0.25, 0.35, 0.90],
        sharpness: 9.0,
        radiance: [12.2, 12.0, 11.7],
    },
    SoftBox {
        axis: [0.78, 0.10, 0.60],
        sharpness: 6.0,
        radiance: [1.95, 2.0, 2.1],
    },
    SoftBox {
        axis: [0.0, 1.0, 0.10],
        sharpness: 6.0,
        radiance: [2.5, 2.5, 2.5],
    },
    SoftBox {
        axis: [-0.85, 0.25, -0.45],
        sharpness: 14.0,
        radiance: [2.5, 2.5, 2.6],
    },
    SoftBox {
        axis: [0.85, 0.30, -0.45],
        sharpness: 14.0,
        radiance: [2.5, 2.5, 2.6],
    },
];

/// The room between the boxes: `ROOM_MEAN + ROOM_SLOPE * up`, a light floor
/// under a brighter ceiling.
pub(crate) const ROOM_MEAN: [f32; 3] = [0.50, 0.50, 0.51];
pub(crate) const ROOM_SLOPE: [f32; 3] = [0.20, 0.20, 0.21];

/// Scene radiance is multiplied by this before the filmic curve.
pub(crate) const EXPOSURE: f32 = 0.9;

/// The key box's world direction for a view direction (towards the camera), for
/// the shadow map. The studio's right and up come from the view direction alone,
/// as in the shader: the orbit camera never rolls, and offscreen captures fill in
/// only that part of the camera's basis.
pub(crate) fn key_direction(towards_camera: Vec3) -> Vec3 {
    let right = Vec3::Y.cross(towards_camera).normalize_or(Vec3::X);
    let up = towards_camera.cross(right);
    let [x, y, z] = SOFT_BOXES[0].axis;
    (right * x + up * y + towards_camera * z).normalize_or(towards_camera)
}

fn vec3(value: [f32; 3]) -> String {
    format!("vec3<f32>({:?},{:?},{:?})", value[0], value[1], value[2])
}

/// The constants above as WGSL, followed by the studio's shading functions.
pub(crate) fn wgsl() -> String {
    let count = SOFT_BOXES.len();
    let axes = SOFT_BOXES
        .iter()
        .map(|soft_box| vec3(Vec3::from(soft_box.axis).normalize().to_array()))
        .collect::<Vec<_>>()
        .join(",");
    let sharpness = SOFT_BOXES
        .iter()
        .map(|soft_box| format!("{:?}", soft_box.sharpness))
        .collect::<Vec<_>>()
        .join(",");
    let radiance = SOFT_BOXES
        .iter()
        .map(|soft_box| vec3(soft_box.radiance))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "const ICON_BOX_COUNT: u32 = {count}u;\n\
         const ICON_BOX_AXES = array<vec3<f32>,{count}>({axes});\n\
         const ICON_BOX_SHARPNESS = array<f32,{count}>({sharpness});\n\
         const ICON_BOX_RADIANCE = array<vec3<f32>,{count}>({radiance});\n\
         const ICON_ROOM_MEAN = {};\n\
         const ICON_ROOM_SLOPE = {};\n\
         const ICON_EXPOSURE: f32 = {EXPOSURE:?};\n{}",
        vec3(ROOM_MEAN),
        vec3(ROOM_SLOPE),
        include_str!("icon_studio_lighting.wgsl")
    )
}

#[cfg(test)]
mod tests {
    //! The same formulas as `icon_studio_lighting.wgsl`, on the CPU, checked
    //! against brute-force integrals of the studio's radiance.
    use super::*;
    use std::f32::consts::PI;

    fn axis(soft_box: &SoftBox) -> Vec3 {
        Vec3::from(soft_box.axis).normalize()
    }

    /// Integral of `exp(sharpness * (cos - 1))` over the sphere.
    fn lobe_integral(sharpness: f32) -> f32 {
        2.0 * PI * (1.0 - (-2.0 * sharpness).exp()) / sharpness
    }

    fn radiance(direction: Vec3) -> Vec3 {
        let mut sum = Vec3::from(ROOM_MEAN) + Vec3::from(ROOM_SLOPE) * direction.y;
        for soft_box in &SOFT_BOXES {
            sum += Vec3::from(soft_box.radiance)
                * (soft_box.sharpness * (direction.dot(axis(soft_box)) - 1.0)).exp();
        }
        sum
    }

    fn kernel_sharpness(roughness: f32) -> f32 {
        let alpha = (roughness * roughness).max(0.002);
        0.5 / (alpha * alpha)
    }

    fn prefiltered(direction: Vec3, roughness: f32) -> Vec3 {
        let kernel = kernel_sharpness(roughness);
        let slope = 1.0 / kernel.min(12.0).tanh() - 1.0 / kernel;
        let mut sum = Vec3::from(ROOM_MEAN) + Vec3::from(ROOM_SLOPE) * direction.y * slope;
        for soft_box in &SOFT_BOXES {
            let blurred = soft_box.sharpness * kernel / (soft_box.sharpness + kernel);
            let scale = lobe_integral(soft_box.sharpness) / lobe_integral(blurred);
            sum += Vec3::from(soft_box.radiance)
                * scale
                * (blurred * (direction.dot(axis(soft_box)) - 1.0)).exp();
        }
        sum
    }

    fn lobe_irradiance(cosine: f32, sharpness: f32) -> f32 {
        let eml = (-sharpness).exp();
        let em2l = eml * eml;
        let rl = 1.0 / sharpness;
        let scale = 1.0 + 2.0 * em2l - rl;
        let bias = (eml - em2l) * rl - em2l;
        let x = (1.0 - scale).sqrt();
        let x0 = 0.36 * cosine;
        let x1 = x / (4.0 * 0.36);
        let n = x0 + x1;
        let y = if x0.abs() <= x1 {
            n * n / x
        } else {
            cosine.clamp(0.0, 1.0)
        };
        (scale * y + bias) * lobe_integral(sharpness)
    }

    /// Irradiance divided by pi: what a white diffuse surface sends back.
    fn irradiance_over_pi(normal: Vec3) -> Vec3 {
        let mut sum = Vec3::from(ROOM_MEAN) + Vec3::from(ROOM_SLOPE) * normal.y * (2.0 / 3.0);
        for soft_box in &SOFT_BOXES {
            sum += Vec3::from(soft_box.radiance)
                * lobe_irradiance(normal.dot(axis(soft_box)), soft_box.sharpness)
                / PI;
        }
        sum
    }

    /// Evenly spread directions with their shared solid angle.
    fn sphere(count: usize) -> (Vec<Vec3>, f32) {
        let golden = PI * (3.0 - 5.0_f32.sqrt());
        let directions = (0..count)
            .map(|index| {
                let y = 1.0 - 2.0 * (index as f32 + 0.5) / count as f32;
                let radius = (1.0 - y * y).sqrt();
                let angle = golden * index as f32;
                Vec3::new(angle.cos() * radius, y, angle.sin() * radius)
            })
            .collect();
        (directions, 4.0 * PI / count as f32)
    }

    fn normals() -> Vec<Vec3> {
        let mut normals = vec![Vec3::X, -Vec3::X, Vec3::Y, -Vec3::Y, Vec3::Z, -Vec3::Z];
        normals.extend(SOFT_BOXES.iter().map(axis));
        normals.push(Vec3::new(0.4, -0.5, 0.75).normalize());
        normals
    }

    #[test]
    fn diffuse_term_is_the_integral_of_the_reflected_room() {
        let (directions, weight) = sphere(200_000);
        for normal in normals() {
            let mut integral = Vec3::ZERO;
            for direction in &directions {
                integral += radiance(*direction) * direction.dot(normal).max(0.0) * weight;
            }
            let expected = integral / PI;
            let actual = irradiance_over_pi(normal);
            let error = (actual - expected).abs().max_element();
            assert!(
                error <= 0.03 * expected.max_element() + 0.01,
                "normal {normal:?}: closed form {actual:?}, integral {expected:?}"
            );
        }
    }

    #[test]
    fn blur_for_roughness_keeps_the_rooms_energy() {
        let (directions, weight) = sphere(200_000);
        let total = |roughness: Option<f32>| {
            directions
                .iter()
                .map(|direction| match roughness {
                    Some(roughness) => prefiltered(*direction, roughness),
                    None => radiance(*direction),
                })
                .sum::<Vec3>()
                * weight
        };
        let sharp = total(None);
        for roughness in [0.05, 0.18, 0.4, 0.7, 1.0] {
            let blurred = total(Some(roughness));
            assert!(
                (blurred - sharp).abs().max_element() <= 0.01 * sharp.max_element(),
                "roughness {roughness}: {blurred:?} against {sharp:?}"
            );
        }
    }

    #[test]
    fn a_mirror_sees_the_room_itself_and_a_rough_surface_a_flatter_one() {
        let key = axis(&SOFT_BOXES[0]);
        let away = -key;
        for direction in normals() {
            let mirror = prefiltered(direction, 0.04);
            let exact = radiance(direction);
            assert!(
                (mirror - exact).abs().max_element() <= 0.01 * exact.max_element(),
                "{direction:?}: {mirror:?} against {exact:?}"
            );
        }
        // Roughness widens the key box and dims its centre; the far side gains.
        let mut last = prefiltered(key, 0.04).y;
        let mut last_away = prefiltered(away, 0.04).y;
        for roughness in [0.3, 0.6, 1.0] {
            let centre = prefiltered(key, roughness).y;
            let far = prefiltered(away, roughness).y;
            assert!(centre < last, "roughness {roughness}: key centre {centre}");
            assert!(far > last_away, "roughness {roughness}: far side {far}");
            last = centre;
            last_away = far;
        }
    }

    #[test]
    fn shader_source_carries_these_constants() {
        let source = wgsl();
        assert!(source.contains(&format!(
            "const ICON_BOX_COUNT: u32 = {}u;",
            SOFT_BOXES.len()
        )));
        assert!(source.contains(&format!("const ICON_EXPOSURE: f32 = {EXPOSURE:?};")));
        assert!(source.contains(&format!("const ICON_ROOM_MEAN = {};", vec3(ROOM_MEAN))));
        for soft_box in &SOFT_BOXES {
            assert!(source.contains(&vec3(soft_box.radiance)));
        }
        // The formulas the CPU twins above mirror.
        for line in [
            "let kernel = 0.5/(alpha*alpha);",
            "let blurred = sharpness*kernel/(sharpness+kernel);",
            "let slope = 1.0/tanh(min(kernel,12.0))-1.0/kernel;",
            "ICON_ROOM_SLOPE*N.y*(2.0/3.0)",
        ] {
            assert!(source.contains(line), "missing: {line}");
        }
    }

    #[test]
    fn preset_is_listed_under_its_own_id_and_shader_value() {
        use crate::LightingPreset;
        assert_eq!(
            LightingPreset::from_id("icon_studio"),
            Some(LightingPreset::IconStudio)
        );
        assert_eq!(LightingPreset::IconStudio.label(), "Game icon studio");
        assert_eq!(LightingPreset::IconStudio.shader_value(), 4);
        let mut ids = LightingPreset::ALL.map(LightingPreset::id).to_vec();
        let mut values = LightingPreset::ALL
            .map(LightingPreset::shader_value)
            .to_vec();
        ids.dedup();
        values.dedup();
        assert_eq!((ids.len(), values.len()), (5, 5));
        // The studio's own shader branches are the ones written for value 4.
        let source = wgsl();
        assert!(
            source.contains("if camera.lighting_preset == 4u { return icon_studio_tone(colour); }")
        );
    }

    #[test]
    fn key_box_follows_the_camera() {
        let front = key_direction(Vec3::Z);
        assert!(front.abs_diff_eq(axis(&SOFT_BOXES[0]), 1e-6));
        let side = key_direction(Vec3::X);
        assert!(side.x > 0.7 && side.z > 0.2 && side.y > 0.3, "{side:?}");
        // Looking straight down has no horizon to take right from.
        assert!(key_direction(Vec3::Y).is_normalized());
    }
}
