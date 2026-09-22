//! Static surface spawning decoded from GPUParticleUpdateCS (types 5 and 6).
//! Target selection is a preview input, not proof of an EffectComponent binding.
use glam::{Mat4, Vec3, Vec4};
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
    ) -> Option<Vec3> {
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
        let mut random = SpawnRandom(seed ^ slot.wrapping_shl(8));
        let picks = [random.next(), random.next(), random.next(), random.next()];
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
            Some(local + normal * data.x)
        } else if world_space {
            Some(local + normal * data.x)
        } else {
            Some(volume.transform_point3(local + normal * data.x))
        }
    }
}

/// GPUParticleUpdateCS advances twice, combines high words, and folds the
/// resulting float's bits back into the state. A sin hash has a different spread.
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
    fn surface_volume_moves_over_a_fixed_target_and_clips_without_fallback() {
        let surface = Surface::read(&surface(), &|| false).unwrap().unwrap();
        let emitter = emitter();
        let origin = surface
            .sample(&emitter, Mat4::IDENTITY, true, 7, 123)
            .unwrap();
        assert!((origin.z - 0.02).abs() < 1e-6);
        assert!(origin.x >= 0. && origin.y >= 0. && origin.x + origin.y <= 1.);
        assert!(
            surface
                .sample(
                    &emitter,
                    Mat4::from_translation(Vec3::X * 10.),
                    true,
                    7,
                    123
                )
                .is_none()
        );
        let placed = Mat4::from_scale_rotation_translation(
            Vec3::splat(2.),
            glam::Quat::from_rotation_z(0.7),
            Vec3::X * 0.2,
        );
        let local = surface.sample(&emitter, placed, true, 7, 123).unwrap();
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
                .sample(&emitter, Mat4::IDENTITY, true, 7, 123)
                .is_none()
        );
        emitter["spawn_surface_density"] = json!(10000);
        emitter["spawn_volume_data"] = json!([0.02, 0, 2, 0]);
        assert_eq!(
            surface.sample(&emitter, Mat4::IDENTITY, true, 7, 123),
            Some(Vec3::Z * 0.02)
        );
        emitter["spawn_volume_data"][3] = json!(0.1);
        assert!(
            surface
                .sample(&emitter, Mat4::IDENTITY, true, 7, 123)
                .is_none()
        );
        emitter["spawn_volume_type"] = json!(5);
        assert!(
            surface
                .sample(&emitter, Mat4::IDENTITY, false, 7, 123)
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
