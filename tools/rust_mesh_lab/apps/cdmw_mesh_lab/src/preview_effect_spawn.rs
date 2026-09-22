//! Static surface spawning decoded from GPUParticleUpdateCS (types 5 and 6).
//! Target selection is a preview input, not proof of an EffectComponent binding.
use glam::{EulerRot, Mat4, Quat, Vec3, Vec4};
use serde_json::Value;

#[derive(Debug, Default)]
pub(crate) struct EffectSurfaces {
    item: Option<Surface>,
    character: Option<Surface>,
    authored: Vec<Option<Surface>>,
}

impl EffectSurfaces {
    pub(crate) fn read(scene: &Value, cancelled: &dyn Fn() -> bool) -> Result<Self, String> {
        let overlay = &scene["effects_overlay"];
        let mut result = Self {
            item: Surface::read(&overlay["spawn_surfaces"]["item"], cancelled)?,
            character: Surface::read(&overlay["spawn_surfaces"]["character"], cancelled)?,
            authored: Vec::new(),
        };
        if let Some(emitters) = overlay["emitters"].as_array() {
            for emitter in emitters.iter().take(2048) {
                result
                    .authored
                    .push(Surface::read(&emitter["spawn_surface"], cancelled)?);
            }
        }
        Ok(result)
    }

    pub(crate) fn select(
        &self,
        emitter: usize,
        kind: u64,
        target: i64,
    ) -> Option<(&Surface, bool)> {
        if kind == 5
            && let Some(surface) = self.authored.get(emitter).and_then(Option::as_ref)
        {
            return Some((surface, false));
        }
        let surface = match target {
            0 => self.item.as_ref(),
            1 => self.character.as_ref(),
            _ => None,
        }?;
        Some((surface, true))
    }
}

fn vector(value: &Value) -> Option<Vec3> {
    let values = value.as_array()?;
    let result = Vec3::new(
        values.first()?.as_f64()? as f32,
        values.get(1)?.as_f64()? as f32,
        values.get(2)?.as_f64()? as f32,
    );
    result.is_finite().then_some(result)
}

fn matrix(value: &Value) -> Option<Mat4> {
    if value.is_null() {
        return Some(Mat4::IDENTITY);
    }
    let values = value.as_array()?;
    if values.is_empty() {
        return Some(Mat4::IDENTITY);
    }
    if values.len() != 16 {
        return None;
    }
    let mut numbers = [0.; 16];
    for (number, value) in numbers.iter_mut().zip(values) {
        *number = value.as_f64()? as f32;
    }
    let result = Mat4::from_cols_array(&numbers);
    (result.is_finite() && result.determinant().abs() > 1e-12).then_some(result)
}

fn number(emitter: &Value, key: &str, default: f32) -> f32 {
    emitter[key]
        .as_f64()
        .map(|v| v as f32)
        .filter(|v| v.is_finite())
        .unwrap_or(default)
}

/// Native GPUParticleUpdateCS (e4d77e6c984757f8faa2d870eea9fdc7), ordinary
/// mesh births: delay/life, four volume draws, XYZ rotation, then scale. A
/// tracked type-6 surface restarts a separate stream for its volume draws.
/// These samples do not reproduce the game's frame allocator or global seed.
pub(crate) struct BirthSamples {
    pub delay: f32,
    pub life: f32,
    pub surface: [f32; 4],
    pub density: Vec3,
    pub rotation: Vec3,
    pub scale: Vec3,
}

impl BirthSamples {
    pub(crate) fn new(emitter: &Value, slot: u32, seed: u32) -> Self {
        let initial = seed ^ slot.wrapping_shl(8);
        let mut random = SpawnRandom(initial);
        let delay = random.next();
        let life = random.next();
        let tracked = emitter["spawn_volume_type"].as_u64() == Some(6)
            && number(emitter, "tracking_position_speed", 0.) > 0.;
        let mut volume = if tracked { SpawnRandom(initial) } else { random };
        let surface = [volume.next(), volume.next(), volume.next(), volume.next()];
        if !tracked {
            random = volume;
        }
        // Native upload enables constants flag 64 iff _spawnDensity is nonzero
        // (0x142fcdc00..2c / 0x142fcdf77..84). Its bias consumes three draws.
        let density = if vector(&emitter["spawn_direction_density"]).unwrap_or(Vec3::ZERO) != Vec3::ZERO {
            Vec3::new(random.next(), random.next(), random.next())
        } else { Vec3::ZERO };
        let rotation = Vec3::new(random.next(), random.next(), random.next());
        let scale_x = random.next();
        let scale = if emitter["use_uniform_scale_random"].as_bool().unwrap_or(true) {
            Vec3::splat(scale_x)
        } else {
            Vec3::new(scale_x, random.next(), random.next())
        };
        Self { delay, life, surface, density, rotation, scale }
    }
}

pub(crate) fn preview_random_seed(emitter: &Value, emitter_index: usize) -> u32 {
    let source = emitter["source_index"].as_u64().unwrap_or(emitter_index as u64) as u32;
    let layer = emitter["layer_index"].as_u64().unwrap_or(0) as u32;
    let fixed_effect_seed = 0x4344_4d57u32.wrapping_add(layer);
    let authored = emitter["spawn_random_seed"].as_u64().unwrap_or(0) as u32;
    let seed = if emitter["spawn_use_effect_random_seed"].as_bool().unwrap_or(false) {
        authored.wrapping_add(fixed_effect_seed)
    } else { authored };
    // Zero requests a live game/frame random seed. Use a stable preview input
    // so seeking, quality changes and selecting an emitter do not reshuffle it.
    if seed == 0 { fixed_effect_seed.wrapping_add(source).max(1) } else { seed }
}

/// The native particle buffer stores birth lifetime, scale and Euler angles as
/// IEEE half floats. Quantize without adding a runtime dependency.
pub(crate) fn half_precision(value: f32) -> f32 {
    let absolute = value.abs();
    if !value.is_finite() {
        return value;
    }
    if absolute >= 65_520. {
        return f32::INFINITY.copysign(value);
    }
    if absolute < 0.000_061_035_156_25 {
        return (value * 16_777_216.).round_ties_even() / 16_777_216.;
    }
    let bits = value.to_bits();
    f32::from_bits(bits.wrapping_add(0xfff + ((bits >> 13) & 1)) & !0x1fff)
}

pub(crate) fn mesh_birth_rotation(angles: Vec3) -> Quat {
    // Native upload 0x142fce613..671 converts each authored component with
    // positive PI/180. The kernel's Y-X-Z matrix rows become right/up/front
    // vectors (DXIL %21643..21677), i.e. columns in glam's transform.
    Quat::from_euler(EulerRot::YXZ, angles.y, angles.x, angles.z).conjugate()
}

fn density_bias(position: Vec3, density: Vec3, random: Vec3) -> Vec3 {
    let radius = position.length();
    let amount = density.length();
    if radius <= 0. || amount <= 0. {
        return position;
    }
    let power = 1. / (amount + 1.);
    let weight = Vec3::from_array(random.to_array().map(|v| v.powf(power)))
        * (1. - (-amount).exp()).clamp(0., 1.);
    let direction = position / radius;
    (direction + (density / amount - direction) * weight).normalize_or(direction) * radius
}

pub(crate) struct SurfaceSample {
    pub position: Vec3,
    pub scale: f32,
}

#[derive(Debug)]
pub(crate) struct Surface {
    vertices: Vec<Vec3>,
    normals: Vec<Vec3>,
    faces: Vec<[usize; 3]>,
    areas: Vec<f32>,
}

impl Surface {
    fn read(value: &Value, cancelled: &dyn Fn() -> bool) -> Result<Option<Self>, String> {
        let Some(points) = value["vertices"].as_array() else {
            return Ok(None);
        };
        let Some(triangles) = value["faces"].as_array() else {
            return Ok(None);
        };
        if points.len() > 524_288 || triangles.len() > 524_288 || triangles.is_empty() {
            return Ok(None);
        }
        let mut vertices = Vec::with_capacity(points.len());
        let mut normals = Vec::with_capacity(points.len());
        for (index, point) in points.iter().enumerate() {
            if index % 1024 == 0 && cancelled() {
                return Err("Preview load cancelled".into());
            }
            let Some(position) = vector(point) else {
                return Ok(None);
            };
            let Some(normal) = vector(&value["normals"][index]) else {
                return Ok(None);
            };
            vertices.push(position);
            normals.push(normal.normalize_or(Vec3::Y));
        }
        let mut faces = Vec::with_capacity(triangles.len());
        let mut areas = Vec::with_capacity(triangles.len());
        for (index, triangle) in triangles.iter().enumerate() {
            if index % 1024 == 0 && cancelled() {
                return Err("Preview load cancelled".into());
            }
            let Some(indices) = triangle.as_array().filter(|v| v.len() == 3) else {
                return Ok(None);
            };
            let mut face = [0; 3];
            for (out, input) in face.iter_mut().zip(indices) {
                let Some(input) = input.as_u64().and_then(|v| usize::try_from(v).ok()) else {
                    return Ok(None);
                };
                if input >= vertices.len() {
                    return Ok(None);
                }
                *out = input;
            }
            let Some(area) = value["areas"][index]
                .as_f64()
                .map(|v| v as f32)
                .filter(|v| v.is_finite() && *v >= 0.)
            else {
                return Ok(None);
            };
            faces.push(face);
            areas.push(area);
        }
        Ok(Some(Self {
            vertices,
            normals,
            faces,
            areas,
        }))
    }

    /// The caller supplies the particle slot and a stable preview emitter seed.
    /// GPU frame scheduling and animated stream-out motion remain external inputs.
    pub(crate) fn sample(
        &self,
        emitter: &Value,
        model: Mat4,
        world_space: bool,
        slot: u32,
        seed: u32,
        birth_samples: Option<&BirthSamples>,
    ) -> Option<SurfaceSample> {
        let kind = emitter["spawn_volume_type"].as_u64()?;
        if !(5..=6).contains(&kind) || !model.is_finite() || model.determinant().abs() < 1e-12 {
            return None;
        }
        let volume = matrix(&emitter["spawn_volume_transform"])?;
        let values = emitter["spawn_volume_data"].as_array()?;
        if values.len() != 4 {
            return None;
        }
        let mut data = Vec4::ZERO;
        for index in 0..4 {
            data[index] = values[index].as_f64()? as f32;
        }
        if !data.is_finite() {
            return None;
        }
        let generated_samples = (birth_samples.is_none() && emitter["kind"].as_str() == Some("mesh"))
            .then(|| BirthSamples::new(emitter, slot, seed));
        let birth_samples = birth_samples.or(generated_samples.as_ref());
        let picks = if let Some(samples) = birth_samples {
            samples.surface
        } else {
            // Other geometry modes retain their approximate sampler until
            // their birth/stream-header contract is decoded.
            let mut random = SpawnRandom(seed ^ slot.wrapping_shl(8));
            [random.next(), random.next(), random.next(), random.next()]
        };
        let count = self.faces.len() as f32;
        let mut fraction = (picks[0] + slot as f32 / count).fract();
        let mut index = ((fraction * count) as usize).min(self.faces.len() - 1);
        let density = number(emitter, "spawn_surface_density", 10000.).max(0.);
        let uniform = emitter["spawn_uniform_surface_density"]
            .as_bool()
            .unwrap_or(false);
        if uniform {
            // The shipped shader retries at most 32 times using squared area
            // acceptance, then retains its final candidate even if none passed.
            let mut retry = SpawnRandom(slot);
            for _ in 0..32 {
                if (self.areas[index] * density).clamp(0., 1.).powi(2) >= picks[3] {
                    break;
                }
                fraction = (fraction + retry.next()).fract();
                index = ((fraction * count) as usize).min(self.faces.len() - 1);
            }
        }
        let [a, b, c] = self.faces[index];
        // Deliberately NOT uniform sqrt barycentrics: these are the two nested
        // lerps in the shipped kernel, scaled by spawnVolumeData.y.
        let u = picks[1] * data.y.clamp(0., 1.);
        let v = picks[2] * data.y.clamp(0., 1.);
        let position = self.vertices[a]
            .lerp(self.vertices[b], u)
            .lerp(self.vertices[c], v);
        let normal = self.normals[a]
            .lerp(self.normals[b], u)
            .lerp(self.normals[c], v)
            .normalize_or(Vec3::Y);
        let inverse = model.inverse();
        let local = if world_space {
            inverse.transform_point3(position)
        } else {
            position
        };
        let normal = if world_space {
            inverse.transform_vector3(normal).normalize_or(Vec3::Y)
        } else {
            normal
        };
        if kind == 6 {
            let distance = volume.inverse().transform_point3(local).length();
            let density_rejected =
                !uniform && (self.areas[index] * density).clamp(0., 1.) < picks[3];
            if density_rejected || distance < data.w || (data.z > 0. && distance > data.z) {
                return None;
            }
        }
        let mut position = local + normal * data.x;
        if let Some(samples) = birth_samples {
            position = density_bias(position,
                vector(&emitter["spawn_direction_density"]).unwrap_or(Vec3::ZERO), samples.density);
        }
        if kind == 5 && !world_space {
            position = volume.transform_point3(position);
        }
        let ratio = number(emitter, "spawn_surface_area_scale_ratio", 0.);
        let scale = if ratio > 0. {
            let t = (self.areas[index] / ratio).clamp(0., 1.);
            (t * t * (3. - 2. * t)).max(0.05)
        } else { 1. };
        Some(SurfaceSample { position, scale })
    }
}

/// GPUParticleUpdateCS advances twice, combines high words, and folds the
/// resulting float's bits back into the state. A sin hash has a different spread.
#[derive(Clone, Copy)]
struct SpawnRandom(u32);
impl SpawnRandom {
    fn next(&mut self) -> f32 {
        let first = self.0.wrapping_mul(214_013).wrapping_add(2_531_011);
        let second = first.wrapping_mul(214_013).wrapping_add(2_531_011);
        let value = (((second & 0xffff_0000) | (first >> 16)) % 32767) as f32 / 32766.;
        self.0 = (second >> 1).wrapping_add(value.to_bits() >> 1);
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn surface() -> Value {
        json!({"vertices": [[0,0,0],[1,0,0],[0,1,0]], "normals": [[0,0,1],[0,0,1],[0,0,1]],
            "faces": [[0,1,2],[0,1,2]], "areas": [0.5,0.5]})
    }
    fn emitter() -> Value {
        json!({"spawn_volume_type":6, "spawn_volume_data":[0.02,1,2,0], "spawn_surface_density":10000})
    }

    #[test]
    fn mesh_birth_draws_match_the_decoded_native_sequence() {
        // Scalar evaluation of the shipped DXIL integer/f32 instructions,
        // initial seed 123 ^ (7 << 8). Values are independent of a sin hash.
        let mut e = emitter();
        e["kind"] = json!("mesh");
        let untracked = BirthSamples::new(&e, 7, 123);
        assert_eq!(untracked.delay, 0.961_972_8);
        assert_eq!(untracked.life, 0.869_071_6);
        assert_eq!(untracked.surface, [0.828_877_5, 0.351_919_68, 0.111_151_81, 0.273_759_4]);
        assert_eq!(untracked.rotation, Vec3::new(0.345_846_3, 0.620_826_5, 0.249_587_98));
        assert_eq!(untracked.scale, Vec3::splat(0.084_325_22));
        e["tracking_position_speed"] = json!(10000.);
        let tracked = BirthSamples::new(&e, 7, 123);
        assert_eq!(tracked.life, untracked.life);
        assert_eq!(tracked.surface, [0.961_972_8, 0.869_071_6, 0.828_877_5, 0.351_919_68]);
        assert_eq!(tracked.rotation, Vec3::new(0.828_877_5, 0.351_919_68, 0.111_151_81));
        assert_eq!(tracked.scale, Vec3::splat(0.273_759_4));
        e["use_uniform_scale_random"] = json!(false);
        assert_eq!(BirthSamples::new(&e, 7, 123).scale, Vec3::new(0.273_759_4, 0.345_846_3, 0.620_826_5));
        e["spawn_direction_density"] = json!([8., 0., 0.]);
        let biased = BirthSamples::new(&e, 7, 123);
        assert_eq!(biased.density, tracked.rotation);
        assert_eq!(biased.rotation, Vec3::new(0.273_759_4, 0.345_846_3, 0.620_826_5));
        // Tracking changes the stream only for target-mesh volumes (type 6).
        e["spawn_volume_type"] = json!(5);
        assert_eq!(BirthSamples::new(&e, 7, 123).surface, untracked.surface);

        e["source_index"] = json!(7);
        let seed = preview_random_seed(&e, 0);
        assert_eq!(preview_random_seed(&e, 99), seed);
        e["spawn_random_seed"] = json!(123);
        assert_eq!(preview_random_seed(&e, 99), 123);
        e["spawn_use_effect_random_seed"] = json!(true);
        assert_ne!(preview_random_seed(&e, 99), 123);
    }

    #[test]
    fn mesh_surface_uses_tracking_draws_and_authored_area_scale() {
        let s = Surface::read(&surface(), &|| false).unwrap().unwrap();
        let mut e = emitter();
        e["kind"] = json!("mesh");
        let first = s.sample(&e, Mat4::IDENTITY, true, 7, 123, None).unwrap();
        assert!(first.position.distance(Vec3::new(0.312_803_18, 0.111_151_81, 0.02)) < 1e-6);
        assert_eq!(first.scale, 1.);
        e["tracking_position_speed"] = json!(10000.);
        e["spawn_surface_area_scale_ratio"] = json!(1.);
        let tracked = s.sample(&e, Mat4::IDENTITY, true, 7, 123, None).unwrap();
        assert!(tracked.position.distance(Vec3::new(0.148_717_7, 0.828_877_5, 0.02)) < 1e-6);
        assert_eq!(tracked.scale, 0.5);
        e["spawn_surface_area_scale_ratio"] = json!(1000.);
        assert_eq!(s.sample(&e, Mat4::IDENTITY, true, 7, 123, None).unwrap().scale, 0.05);
        e["spawn_direction_density"] = json!([8., 0., 0.]);
        let biased = s.sample(&e, Mat4::IDENTITY, true, 7, 123, None).unwrap().position;
        assert!((biased.length() - tracked.position.length()).abs() < 1e-6);
        assert!(biased.x > 0.8 && biased.y < 0.2);
    }

    #[test]
    fn native_birth_precision_and_delay_reach_indexed_particles() {
        assert_eq!(half_precision(0.2), 0.199_951_17);
        assert_eq!(half_precision(1.000_488_281_25), 1.); // tie, even mantissa
        assert_eq!(half_precision(1.001_464_843_75), 1.001_953_1);
        assert_eq!(half_precision(2f32.powi(-25)), 0.);
        assert_eq!(half_precision(3. * 2f32.powi(-25)), 2f32.powi(-23));
        assert_eq!(half_precision(-0.2), -0.199_951_17);
        assert!(half_precision(65_520.).is_infinite());
        let s = Surface::read(&surface(), &|| false).unwrap().unwrap();
        let mut e = emitter();
        e["kind"] = json!("mesh");
        e["particle_faces"] = json!([[0,1,2]]);
        e["alpha_over_life"] = json!([1.]);
        e["scale"] = json!([[0.01,0.01,0.01],[0.04,0.04,0.04]]);
        e["rotation_3d"] = json!([[20.,-35.,70.],[20.,-35.,70.]]);
        e["life"] = json!([0.2,0.4]);
        e["bursts_per_second"] = json!(0.);
        e["burst"] = json!(8);
        e["max_particles"] = json!(32);
        e["spawn_random_seed"] = json!(123);
        e["tracking_position_speed"] = json!(10000.);
        let draw = |e: &Value, time| crate::preview_effects::effect_emitter_particles(
            e, 0, time, 0.001, 0, Mat4::IDENTITY, Vec3::X, Vec3::Y, -Vec3::Z, 256,
            crate::preview_effect_lightning::LightningView { eye: Vec3::Z * 5., vertical_fov: 0.7, height: 480. },
            Some((&s, true)), Some(0),
        ).meshes;
        let particles = draw(&e, 0.1);
        assert_eq!(particles.len(), 8);
        let seventh = particles[7].particle;
        assert_eq!(seventh.seed[0], 7); // _particleID, not the old sine seed 49.
        assert_eq!(&seventh.scale_age[..3], &[0.018_218_994; 3]);
        assert!((seventh.scale_age[3] - 0.1 / 0.373_779_3).abs() < 1e-6);
        // Native DXIL basis at the half-precision angles. Mixed axes catch
        // both the previous XYZ order and accidentally transposed directions.
        let basis = [
            Vec3::new(0.095_848_784, -0.836_863_4, -0.538_955_15),
            Vec3::new(0.882_988_15, 0.321_432_17, -0.342_072_04),
            Vec3::new(0.459_505_14, -0.443_103_85, 0.769_749_34),
        ];
        for (column, expected) in seventh.transform[..3].iter().zip(basis) {
            let actual = Vec3::new(column[0], column[1], column[2]) / seventh.scale_age[0];
            assert!(actual.distance(expected) < 1e-6, "{actual:?} != {expected:?}");
        }
        e["start_delay"] = json!([0.,1.]);
        e["life"] = json!([0.2,0.2]);
        e["burst"] = json!(32);
        let delayed = draw(&e, 0.8);
        assert!(!delayed.is_empty() && delayed.len() < 32);
        assert!(delayed.iter().all(|p| p.particle.scale_age[3] <= 1.));
        assert!(draw(&e, 1.3).is_empty());
    }

    #[test]
    fn rejected_infinite_births_keep_their_slots_across_time_and_draw_quality() {
        let s = Surface::read(&surface(), &|| false).unwrap().unwrap();
        let mut e = emitter();
        e["kind"] = json!("mesh");
        e["particle_faces"] = json!([[0,1,2]]);
        e["alpha_over_life"] = json!([1.]);
        e["spawn_volume_data"] = json!([0.,1.,0.35,0.]);
        e["spawn_random_seed"] = json!(123);
        e["tracking_position_speed"] = json!(10000.);
        e["burst"] = json!(64);
        e["burst_min"] = json!(64);
        e["max_particles"] = json!(130); // The third burst reserves only two slots.
        e["bursts_per_second"] = json!(10.);
        e["infinite_life"] = json!(true);
        e["repeat_curves"] = json!(true);
        let ids = |time, limit| crate::preview_effects::effect_emitter_particles(
            &e, 0, time, 0.001, 0, Mat4::IDENTITY, Vec3::X, Vec3::Y, -Vec3::Z, limit,
            crate::preview_effect_lightning::LightningView { eye: Vec3::Z * 5., vertical_fov: 0.7, height: 480. },
            Some((&s, true)), Some(0),
        ).meshes.into_iter().map(|v| v.particle.seed[0]).collect::<Vec<_>>();
        let complete = ids(0.5, 2048);
        assert!(!complete.is_empty() && complete.len() < 64);
        assert!(complete.iter().any(|&id| id >= 64));
        assert!(complete.iter().all(|&id| id < 130));
        assert_eq!(ids(0.5, 64), complete);
        assert_eq!(ids(100., 2048), complete);
    }

    #[test]
    fn surface_volume_moves_over_a_fixed_target_and_clips_without_fallback() {
        let surface = Surface::read(&surface(), &|| false).unwrap().unwrap();
        let emitter = emitter();
        let origin = surface
            .sample(&emitter, Mat4::IDENTITY, true, 7, 123, None)
            .unwrap().position;
        assert!((origin.z - 0.02).abs() < 1e-6);
        assert!(origin.x >= 0. && origin.y >= 0. && origin.x + origin.y <= 1.);
        assert!(
            surface
                .sample(
                    &emitter,
                    Mat4::from_translation(Vec3::X * 10.),
                    true,
                    7,
                    123,
                    None
                )
                .is_none()
        );
        let placed = Mat4::from_scale_rotation_translation(
            Vec3::splat(2.),
            glam::Quat::from_rotation_z(0.7),
            Vec3::X * 0.2,
        );
        let local = surface.sample(&emitter, placed, true, 7, 123, None).unwrap().position;
        assert!(
            placed
                .transform_point3(local)
                .distance(origin + Vec3::Z * 0.02)
                < 1e-5
        );
    }
    #[test]
    fn density_shell_and_surface_spread_follow_separate_volume_components() {
        let surface = Surface::read(&surface(), &|| false).unwrap().unwrap();
        let mut emitter = emitter();
        emitter["spawn_surface_density"] = json!(0);
        assert!(
            surface
                .sample(&emitter, Mat4::IDENTITY, true, 7, 123, None)
                .is_none()
        );
        emitter["spawn_surface_density"] = json!(10000);
        emitter["spawn_volume_data"] = json!([0.02, 0, 2, 0]);
        assert_eq!(
            surface.sample(&emitter, Mat4::IDENTITY, true, 7, 123, None).map(|v| v.position),
            Some(Vec3::Z * 0.02)
        );
        emitter["spawn_volume_data"][3] = json!(0.1);
        assert!(
            surface
                .sample(&emitter, Mat4::IDENTITY, true, 7, 123, None)
                .is_none()
        );
        emitter["spawn_volume_type"] = json!(5);
        assert!(
            surface
                .sample(&emitter, Mat4::IDENTITY, false, 7, 123, None)
                .is_some()
        );
    }
    #[test]
    fn surface_selection_never_substitutes_character_or_point_and_cancels_preparation() {
        let scene = json!({"effects_overlay":{"spawn_surfaces":{"item":surface()}, "emitters":[{"spawn_surface":surface()}]}});
        let surfaces = EffectSurfaces::read(&scene, &|| false).unwrap();
        assert!(surfaces.select(0, 6, 0).is_some());
        assert!(surfaces.select(0, 6, 1).is_none());
        assert!(surfaces.select(0, 6, 2).is_none());
        assert!(!surfaces.select(0, 5, 2).unwrap().1);
        assert!(
            EffectSurfaces::read(&scene, &|| true)
                .unwrap_err()
                .contains("cancelled")
        );
    }

    #[test]
    fn point_override_does_not_reuse_inherited_surface_samples() {
        let emitter = json!({"spawn_volume_type":0, "spawn":"points", "points":[[99,99,99]],
            "spawn_volume_transform":[1,0,0,0,0,1,0,0,0,0,1,0,0.1,0.2,0.3,1],
            "alpha_over_life":[1.], "scale":[[0.1,0.1,0.1],[0.1,0.1,0.1]]});
        let drawn = crate::preview_effects::effect_emitter_billboards(
            &emitter,
            0,
            0.1,
            0.001,
            0,
            Mat4::IDENTITY,
            Vec3::X,
            Vec3::Y,
            -Vec3::Z,
        );
        assert!(!drawn.is_empty());
        assert!(Vec3::from_array(drawn[0].center).distance(Vec3::new(0.1, 0.2, 0.3)) < 1e-6);
    }

    #[test]
    fn surface_spawning_reaches_particle_draws_and_respects_live_placement() {
        let mut emitter = emitter();
        emitter["alpha_over_life"] = json!([1.]);
        emitter["scale"] = json!([[0.1, 0.1, 0.1], [0.1, 0.1, 0.1]]);
        emitter["burst"] = json!(10);
        let scene = json!({"effects_overlay":{"spawn_surfaces":{"item":surface()}}});
        let surfaces = EffectSurfaces::read(&scene, &|| false).unwrap();
        let draw = |placement, target| {
            crate::preview_effects::effect_emitter_billboards_with_limit(
                &emitter,
                0,
                0.1,
                0.001,
                0,
                placement,
                Vec3::X,
                Vec3::Y,
                -Vec3::Z,
                256,
                crate::preview_effect_lightning::LightningView {
                    eye: Vec3::Z * 5.,
                    vertical_fov: 0.7,
                    height: 480.,
                },
                surfaces.select(0, 6, target),
            )
        };
        let drawn = draw(Mat4::IDENTITY, 0);
        assert_eq!(drawn.len(), 10);
        assert!(drawn.iter().all(|p| (p.center[2] - 0.02).abs() < 1e-5));
        assert!(draw(Mat4::IDENTITY, 2).is_empty());
        assert!(draw(Mat4::from_translation(Vec3::X * 10.), 0).is_empty());
    }
}
