//! Controlled guide-cloth stepping and the decoded PAC guide-to-render blend.
//!
//! The host resolves the matching rig and CPU rest geometry. This preview uses
//! explicit forces, a bounded Jacobi schedule and rigid anchor motion, not a
//! recovered game dispatch/profile. Area constraints are retained but inactive;
//! guide rotation correction, bone/layer/world contacts and runtime overrides
//! remain separate work. Source records and authored mesh positions are immutable.

use crate::jiggle_rig::{Rig, RigSnapshot};
use crate::jiggle_skinning::{self, Matrix};
use glam::{DMat4, DVec3};
use serde::{Deserialize, Serialize};

type Result<T> = std::result::Result<T, &'static str>;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Snapshot {
    pub version: u32,
    pub source_positions: Vec<[f64; 3]>,
    pub animation_frames: Vec<Matrix>,
    pub fixed: Vec<bool>,
    pub alpha_blends: Vec<f64>,
    pub constraints: Vec<Constraint>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Constraint {
    Pair { indices: [usize; 2], rest: f64 },
    Hinge { indices: [usize; 4], rest: f64 },
    Triangle { indices: [usize; 3], rest: f64 },
}

#[derive(Clone, Copy, Debug)]
pub struct Settings {
    pub gravity: f64,
    /// Decoded normal damping coefficient; each step multiplies v by 1-0.1*d.
    pub damping: f64,
    /// Explicit modified per-iteration coefficients, not raw material XML.
    pub stretch: f64,
    pub bend: f64,
    pub iterations: u32,
    pub speed_limit: f64,
    pub use_vertex_alpha: bool,
    pub ground_height: Option<f64>,
}

impl Default for Settings {
    fn default() -> Self {
        // Controlled preview choices. No active game material is inferred.
        Self {
            gravity: 9.81,
            damping: 0.5,
            stretch: 0.8,
            bend: 0.1,
            iterations: 4,
            speed_limit: 50.0,
            use_vertex_alpha: false,
            ground_height: None,
        }
    }
}

impl Settings {
    fn valid(self) -> bool {
        self.gravity.is_finite()
            && (0.0..=100.0).contains(&self.gravity)
            && self.damping.is_finite()
            && (0.0..=10.0).contains(&self.damping)
            && self.stretch.is_finite()
            && (0.0..=1.0).contains(&self.stretch)
            && self.bend.is_finite()
            && (0.0..=1.0).contains(&self.bend)
            && (1..=8).contains(&self.iterations)
            && self.speed_limit.is_finite()
            && (0.001..=1000.0).contains(&self.speed_limit)
            && self.ground_height.is_none_or(f64::is_finite)
    }
}

#[derive(Debug)]
struct Binding {
    rest: DVec3,
    indices: [usize; 4],
    weights: [f64; 4],
    skeletal_blend: f64,
}

#[derive(Debug)]
pub struct Simulation {
    snapshot: Snapshot,
    frames: Vec<DMat4>,
    bindings: Vec<Binding>,
    positions: Vec<DVec3>,
    velocities: Vec<DVec3>,
    output: Vec<[f32; 3]>,
    pub inactive_area_constraints: usize,
}

fn affine(rows: &Matrix) -> Result<DMat4> {
    let mut columns = *rows;
    for (i, column) in columns.iter_mut().enumerate() {
        column[3] = if i == 3 { 1.0 } else { 0.0 };
    }
    let matrix = DMat4::from_cols_array_2d(&columns);
    if !matrix.is_finite() {
        return Err("Cloth matrices must be finite.");
    }
    Ok(matrix)
}

fn inverse(matrix: DMat4) -> Result<DMat4> {
    if matrix.determinant().abs() <= 1e-12 {
        return Err("Cloth neutral binding is singular.");
    }
    let value = matrix.inverse();
    if !value.is_finite() {
        return Err("Cloth neutral binding is singular.");
    }
    Ok(value)
}

fn weighted_guides(frames: &[DMat4], indices: [usize; 4], weights: [f64; 4]) -> DMat4 {
    (0..4).fold(DMat4::ZERO, |sum, i| sum + frames[indices[i]] * weights[i])
}

fn guide_matrix(frame: DMat4, source: [f64; 3]) -> DMat4 {
    let mut matrix = frame;
    matrix.w_axis =
        (frame.w_axis.truncate() - frame.transform_vector3(DVec3::from(source))).extend(1.0);
    matrix
}

fn half_index(bits: u16) -> Result<usize> {
    // This lane is a half-float index, not a packed uint16. Valid values are
    // nonnegative and <=1023; source rounding is floor(value+.5).
    let exponent = (bits >> 10) & 31;
    let mantissa = bits & 1023;
    let value = if exponent == 0 {
        f64::from(mantissa) * 2.0_f64.powi(-24)
    } else {
        f64::from(1024 + mantissa) * 2.0_f64.powi(i32::from(exponent) - 25)
    };
    if bits & 0x8000 != 0 && bits & 0x7FFF != 0 || exponent == 31 || value > 1023.0 {
        return Err("Invalid PAC cloth-guide index.");
    }
    Ok((value + 0.5).floor() as usize)
}

impl Simulation {
    pub fn new(
        snapshot: Snapshot,
        rig: &RigSnapshot,
        rest: &[[f32; 3]],
        records: &[[u8; 40]],
        contributions: &[u8],
        cancelled: &dyn Fn() -> bool,
    ) -> Result<Self> {
        if cancelled() {
            return Err("Cloth preview preparation was cancelled.");
        }
        let count = snapshot.fixed.len();
        if snapshot.version != 1
            || count == 0
            || count > 1024
            || snapshot.source_positions.len() != count
            || snapshot.animation_frames.len() != count
            || snapshot.alpha_blends.len() != count
            || snapshot.constraints.len() > 65535
            || rest.is_empty()
            || rest.len() > 100_000
            || rest.len() != records.len()
            || rest.len() != contributions.len()
            || contributions.iter().any(|b| *b > 63)
            || rest.iter().flatten().any(|v| !v.is_finite())
            || snapshot
                .source_positions
                .iter()
                .flatten()
                .any(|v| !v.is_finite())
            || snapshot
                .alpha_blends
                .iter()
                .any(|v| !v.is_finite() || !(0.0..=1.0).contains(v))
        {
            return Err("Cloth snapshot has invalid or unbounded guide/render buffers.");
        }
        Rig::new(rig.clone())?;
        let mut areas = 0;
        for constraint in &snapshot.constraints {
            let (indices, value): (&[usize], f64) = match constraint {
                Constraint::Pair { indices, rest } => (indices, *rest),
                Constraint::Hinge { indices, rest } => (indices, *rest),
                Constraint::Triangle { indices, rest } => {
                    areas += 1;
                    (indices, *rest)
                }
            };
            if !value.is_finite()
                || value < 0.0
                || indices.iter().any(|i| *i >= count)
                || indices
                    .iter()
                    .enumerate()
                    .any(|(i, v)| indices[..i].contains(v))
            {
                return Err("Cloth constraint has invalid geometry or guide indices.");
            }
        }
        let frames = snapshot
            .animation_frames
            .iter()
            .map(affine)
            .collect::<Result<Vec<_>>>()?;
        let guides = frames
            .iter()
            .zip(&snapshot.source_positions)
            .map(|(frame, source)| guide_matrix(*frame, *source))
            .collect::<Vec<_>>();
        let bones = rig
            .inverse_bind_matrices
            .iter()
            .zip(&rig.neutral_global_matrices)
            .map(|(inverse, pose)| {
                jiggle_skinning::prepare_bone(inverse, pose, None, [1.0; 3])
                    .map(|result| result.skeletal_matrix)
            })
            .collect::<Result<Vec<_>>>()?;
        let map = (0..rig.parents.len() as u32).collect::<Vec<_>>();
        let mut bindings = Vec::with_capacity(rest.len());
        for (i, ((position, record), contribution)) in
            rest.iter().zip(records).zip(contributions).enumerate()
        {
            if i.is_multiple_of(256) && cancelled() {
                return Err("Cloth preview preparation was cancelled.");
            }
            // Retain the original byte39 while selecting four/six SKELETAL
            // influences. A disabled cloth comparison must not reinterpret its
            // original guide lanes as two additional skeleton influences.
            let skeletal = affine(&jiggle_skinning::blend_vertex(
                jiggle_skinning::RenderInput {
                    record,
                    render_flags: 128,
                    bone_palette: &rig.bone_palette,
                    skinning_index_map: &map,
                    skeletal_matrices: &bones,
                    jiggle_matrices: None,
                    wind_weight: 0.0,
                    wind_samples: None,
                },
            )?)?;
            let mut binding = Binding {
                rest: DVec3::from(position.map(f64::from)),
                indices: [0; 4],
                weights: [0.0; 4],
                skeletal_blend: f64::from(*contribution) / 63.0,
            };
            if record[39] & 63 == 63 && *contribution != 63 {
                return Err(
                    "Cloth preview cannot enable a vertex without retained guide bindings.",
                );
            }
            let neutral = if *contribution == 63 {
                skeletal
            } else {
                let packed = u32::from_le_bytes(record[24..28].try_into().expect("fixed record"));
                binding.indices = [
                    ((packed >> 10) & 1023) as usize,
                    ((packed >> 20) & 1023) as usize,
                    half_index(u16::from_le_bytes([record[12], record[13]]))?,
                    half_index(u16::from_le_bytes([record[14], record[15]]))?,
                ];
                if binding.indices.iter().any(|i| *i >= count) {
                    return Err("Render cloth binding refers outside its guide mesh.");
                }
                let total = record[32..36].iter().map(|v| u32::from(*v)).sum::<u32>();
                if total == 0 {
                    return Err("Cloth preview cannot bind zero render-guide weights.");
                }
                binding.weights =
                    std::array::from_fn(|i| f64::from(record[32 + i]) / f64::from(total));
                let cloth = weighted_guides(&guides, binding.indices, binding.weights);
                cloth * (1.0 - binding.skeletal_blend) + skeletal * binding.skeletal_blend
            };
            // Validate the actual blended neutral transform. With rigid anchor
            // motion and rotation correction off, its inverse cancels during
            // playback, leaving the weighted translation delta below.
            inverse(neutral)?;
            bindings.push(binding);
        }
        let positions = frames.iter().map(|m| m.w_axis.truncate()).collect();
        Ok(Self {
            snapshot,
            frames,
            bindings,
            positions,
            velocities: vec![DVec3::ZERO; count],
            output: rest.to_vec(),
            inactive_area_constraints: areas,
        })
    }

    pub fn positions(&self) -> &[[f32; 3]] {
        &self.output
    }
    pub fn guide_positions(&self) -> Vec<[f64; 3]> {
        self.positions.iter().map(|p| p.to_array()).collect()
    }
    pub fn guide_count(&self) -> usize {
        self.positions.len()
    }

    /// One bounded preview substep. Work is transactional: invalid input or an
    /// unstable projection leaves the previous complete simulation/draw state.
    pub fn step(&mut self, dt: f64, motion: Matrix, settings: Settings) -> Result<()> {
        if !dt.is_finite()
            || !(0.0..=0.1).contains(&dt)
            || dt == 0.0
            || !settings.valid()
            || motion.iter().flatten().any(|v| !v.is_finite())
            || motion.map(|r| r[3]) != [0.0, 0.0, 0.0, 1.0]
        {
            return Err("Invalid cloth preview time, motion or settings.");
        }
        let motion = DMat4::from_cols_array_2d(&motion);
        let axes = [
            motion.x_axis.truncate(),
            motion.y_axis.truncate(),
            motion.z_axis.truncate(),
        ];
        if axes.iter().any(|v| (v.length_squared() - 1.0).abs() > 1e-6)
            || axes[0].dot(axes[1]).abs() > 1e-6
            || axes[0].dot(axes[2]).abs() > 1e-6
            || axes[1].dot(axes[2]).abs() > 1e-6
            || (motion.determinant() - 1.0).abs() > 1e-6
        {
            return Err("Cloth preview motion must be a rigid transform.");
        }
        let animation = self
            .frames
            .iter()
            .map(|f| motion.transform_point3(f.w_axis.truncate()))
            .collect::<Vec<_>>();
        let masses = self
            .snapshot
            .fixed
            .iter()
            .map(|fixed| if *fixed { 0.0 } else { 1.0 })
            .collect::<Vec<_>>();
        let damping = 1.0 - f64::from(0.1_f32) * settings.damping;
        let mut positions = self
            .positions
            .iter()
            .zip(&self.velocities)
            .enumerate()
            .map(|(i, (p, v))| {
                if self.snapshot.fixed[i] {
                    animation[i]
                } else {
                    *p + (*v - DVec3::Y * settings.gravity * dt) * damping * dt
                }
            })
            .collect::<Vec<_>>();
        let mut corrections = vec![DVec3::ZERO; positions.len()];
        let mut counts = vec![0u32; positions.len()];
        for _ in 0..settings.iterations {
            corrections.fill(DVec3::ZERO);
            counts.fill(0);
            for constraint in &self.snapshot.constraints {
                match constraint {
                    Constraint::Pair {
                        indices: [a, b],
                        rest,
                    } if settings.stretch > 0.0 => {
                        let edge = positions[*a] - positions[*b];
                        let length = edge.length();
                        let error = length - rest;
                        let sum = masses[*a] + masses[*b];
                        if sum == 0.0
                            || length <= f64::from(0.0001_f32)
                            || error.abs() <= f64::from(0.0001_f32)
                        {
                            continue;
                        }
                        let correction = edge * (settings.stretch * error / (sum * length));
                        corrections[*a] -= correction * masses[*a];
                        corrections[*b] += correction * masses[*b];
                        counts[*a] += 1;
                        counts[*b] += 1;
                    }
                    Constraint::Hinge { indices, rest } if settings.bend > 0.0 => {
                        let values = angle_corrections(
                            indices.map(|i| positions[i]),
                            indices.map(|i| masses[i]),
                            *rest,
                            settings.bend,
                        );
                        for (index, value) in indices.iter().zip(values) {
                            corrections[*index] += value;
                            counts[*index] += 1;
                        }
                    }
                    // Disabled families must not dilute another family's
                    // correction count. Area is explicitly inactive here.
                    _ => {}
                }
            }
            for i in 0..positions.len() {
                if !self.snapshot.fixed[i] && counts[i] != 0 {
                    positions[i] += corrections[i] / f64::from(counts[i]);
                }
            }
        }
        let mut velocities = Vec::with_capacity(positions.len());
        for i in 0..positions.len() {
            if settings.use_vertex_alpha && !self.snapshot.fixed[i] {
                positions[i] = positions[i].lerp(animation[i], self.snapshot.alpha_blends[i]);
            }
            let mut ground_contact = false;
            if !self.snapshot.fixed[i]
                && let Some(height) = settings.ground_height
            {
                ground_contact = positions[i].y < height;
                positions[i].y = positions[i].y.max(height);
            }
            let mut velocity = if self.snapshot.fixed[i] {
                DVec3::ZERO
            } else {
                ((positions[i] - self.positions[i]) / dt).clamp_length_max(settings.speed_limit)
            };
            if ground_contact {
                velocity.y = 0.0;
            }
            if !positions[i].is_finite() || !velocity.is_finite() {
                return Err("Cloth preview projection became non-finite.");
            }
            velocities.push(velocity);
        }
        let displacement = positions
            .iter()
            .zip(&animation)
            .map(|(p, a)| *p - *a)
            .collect::<Vec<_>>();
        let mut output = Vec::with_capacity(self.bindings.len());
        for binding in &self.bindings {
            // This is the decoded matrix blend's rigid-motion, no-rotation-
            // correction specialization. It preserves edited display positions
            // and nonuniform neutral appearance without a second skin transform.
            let mut point = motion.transform_point3(binding.rest);
            if binding.skeletal_blend != 1.0 {
                let delta = (0..4).fold(DVec3::ZERO, |sum, i| {
                    sum + displacement[binding.indices[i]] * binding.weights[i]
                });
                point += delta * (1.0 - binding.skeletal_blend);
            }
            let packed = point.as_vec3().to_array();
            if packed.iter().any(|v| !v.is_finite()) {
                return Err("Cloth preview produced an invalid render position.");
            }
            output.push(packed);
        }
        self.positions = positions;
        self.velocities = velocities;
        self.output = output;
        Ok(())
    }
}

fn angle_corrections(p: [DVec3; 4], masses: [f64; 4], rest: f64, stiffness: f64) -> [DVec3; 4] {
    let edge = p[1] - p[0];
    let c = p[2] - p[0];
    let d = p[3] - p[0];
    let raw = [edge.cross(c), edge.cross(d)];
    if raw
        .iter()
        .any(|n| n.length_squared() < f64::from(0.00001_f32))
    {
        return [DVec3::ZERO; 4];
    }
    let lengths = raw.map(DVec3::length);
    let n = [raw[0] / lengths[0], raw[1] / lengths[1]];
    let cosine = n[0].dot(n[1]).clamp(-1.0, 1.0);
    let gradient = |v: DVec3, first: DVec3, second: DVec3, length: f64| {
        (v.cross(second) - cosine * v.cross(first)) / length
    };
    let gc = gradient(edge, n[0], n[1], lengths[0]);
    let gd = gradient(edge, n[1], n[0], lengths[1]);
    let gb = -gradient(c, n[0], n[1], lengths[0]) - gradient(d, n[1], n[0], lengths[1]);
    let gradients = [-gb - gc - gd, gb, gc, gd];
    let denominator = (0..4)
        .map(|i| masses[i] * gradients[i].length_squared())
        .sum::<f64>();
    if denominator <= f64::from(0.001_f32) {
        return [DVec3::ZERO; 4];
    }
    let amount = -(1.0 - cosine * cosine).max(0.0).sqrt() * (cosine.acos() - rest) / denominator;
    std::array::from_fn(|i| gradients[i] * (stiffness * amount * masses[i]))
}

#[cfg(test)]
mod tests {
    use super::*;
    use glam::DQuat;

    fn rig() -> RigSnapshot {
        let identity = DMat4::IDENTITY.to_cols_array_2d();
        RigSnapshot {
            bone_palette: vec![0],
            parents: vec![-1],
            inverse_bind_matrices: vec![identity],
            neutral_global_matrices: vec![identity],
            neutral_local_matrices: vec![identity],
        }
    }

    fn snapshot() -> Snapshot {
        let positions = vec![[0.0, 1.0, 0.0], [0.0; 3], [1.0, 0.0, 0.0]];
        Snapshot {
            version: 1,
            animation_frames: positions
                .iter()
                .map(|p| DMat4::from_translation(DVec3::from(*p)).to_cols_array_2d())
                .collect(),
            source_positions: positions,
            fixed: vec![true, false, false],
            alpha_blends: vec![1.0, 0.5, 0.0],
            constraints: vec![Constraint::Pair {
                indices: [0, 1],
                rest: 1.0,
            }],
        }
    }

    fn records() -> Vec<[u8; 40]> {
        (0u32..3)
            .map(|index| {
                let mut record = [0; 40];
                record[28] = 255;
                record[32] = 255;
                record[24..28].copy_from_slice(&(index << 10).to_le_bytes());
                record
            })
            .collect()
    }

    fn simulation(contributions: [u8; 3]) -> Simulation {
        let snapshot = snapshot();
        let rest = snapshot
            .source_positions
            .iter()
            .map(|p| p.map(|v| v as f32))
            .collect::<Vec<_>>();
        Simulation::new(snapshot, &rig(), &rest, &records(), &contributions, &|| {
            false
        })
        .unwrap()
    }

    fn close(actual: [f32; 3], expected: DVec3) {
        assert!(
            DVec3::from(actual.map(f64::from)).distance(expected) < 1e-6,
            "{actual:?} != {expected:?}"
        );
    }

    #[test]
    fn decoded_guide_weights_and_damping_preserve_fixed_and_disabled_vertices() {
        let mut current = simulation([63, 32, 0]);
        let mut original = simulation([0; 3]);
        let mut disabled = simulation([63; 3]);
        let rest = disabled.positions().to_vec();
        let settings = Settings {
            stretch: 0.0,
            gravity: 3.0,
            damping: 1.0,
            ..Settings::default()
        };
        for simulation in [&mut current, &mut original, &mut disabled] {
            simulation
                .step(0.02, DMat4::IDENTITY.to_cols_array_2d(), settings)
                .unwrap();
        }
        let drop = -3.0 * 0.02 * 0.02 * (1.0 - f64::from(0.1_f32));
        assert_eq!(current.positions()[0], rest[0]);
        close(current.positions()[1], DVec3::Y * (drop * 31.0 / 63.0));
        close(current.positions()[2], DVec3::X + DVec3::Y * drop);
        assert_eq!(current.positions()[2], original.positions()[2]);
        assert_eq!(disabled.positions(), rest);
        assert_eq!(current.guide_count(), 3);
    }

    #[test]
    fn authored_constraint_and_alpha_option_control_anchor_following() {
        let mut loose = simulation([0; 3]);
        let mut tight = simulation([0; 3]);
        let mut alpha = simulation([0; 3]);
        let settings = Settings {
            gravity: 0.0,
            damping: 0.0,
            stretch: 0.0,
            iterations: 1,
            ..Settings::default()
        };
        let motion = DMat4::from_translation(DVec3::Y).to_cols_array_2d();
        loose.step(1.0 / 60.0, motion, settings).unwrap();
        tight
            .step(
                1.0 / 60.0,
                motion,
                Settings {
                    stretch: 1.0,
                    ..settings
                },
            )
            .unwrap();
        alpha
            .step(
                1.0 / 60.0,
                motion,
                Settings {
                    use_vertex_alpha: true,
                    ..settings
                },
            )
            .unwrap();
        close(loose.positions()[0], DVec3::Y * 2.0);
        close(loose.positions()[1], DVec3::ZERO);
        close(tight.positions()[1], DVec3::Y);
        close(alpha.positions()[1], DVec3::Y * 0.5);
    }

    #[test]
    fn disabled_comparison_preserves_edited_positions_under_rigid_motion_and_neutral_scale() {
        let mut snapshot = snapshot();
        for frame in &mut snapshot.animation_frames {
            frame[0][0] = 2.0;
            frame[1][1] = 3.0;
        }
        let mut rig = rig();
        rig.neutral_global_matrices[0][0][0] = 2.0;
        rig.neutral_local_matrices = rig.neutral_global_matrices.clone();
        let rest = vec![[3.0, 4.0, 5.0], [0.1, 0.3, 0.9], [-1.0, 0.5, 0.25]];
        let mut sim =
            Simulation::new(snapshot, &rig, &rest, &records(), &[63; 3], &|| false).unwrap();
        let motion = DMat4::from_rotation_translation(
            DQuat::from_rotation_z(0.7),
            DVec3::new(2.0, -1.0, 0.5),
        );
        sim.step(1.0 / 60.0, motion.to_cols_array_2d(), Settings::default())
            .unwrap();
        for (actual, source) in sim.positions().iter().zip(&rest) {
            close(
                *actual,
                motion.transform_point3(DVec3::from(source.map(f64::from))),
            );
        }
    }

    #[test]
    fn angle_kernel_matches_the_owned_python_reference_and_keeps_zero_mass_fixed() {
        let points =
            [[0.0; 3], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, -0.8, 0.6]].map(DVec3::from);
        let expected = [
            [0.0; 3],
            [0.0; 3],
            [0.0, 0.0, -0.16087527719832106],
            [0.0, -0.0965251663189926, -0.12870022175865684],
        ];
        let result = angle_corrections(points, [0.0, 1.0, 1.0, 1.0], std::f64::consts::PI, 0.5);
        for (actual, expected) in result.iter().zip(expected) {
            assert!(actual.distance(DVec3::from(expected)) < 1e-12);
        }
        assert_eq!(
            angle_corrections([DVec3::ZERO; 4], [1.0; 4], 1.0, 1.0),
            [DVec3::ZERO; 4]
        );
    }

    #[test]
    fn preview_floor_clears_normal_velocity_when_landing() {
        let mut sim = simulation([0; 3]);
        sim.step(
            0.1,
            DMat4::IDENTITY.to_cols_array_2d(),
            Settings {
                stretch: 0.0,
                ground_height: Some(-0.01),
                ..Settings::default()
            },
        )
        .unwrap();
        assert_eq!(sim.guide_positions()[1][1], -0.01);
        assert_eq!(sim.velocities[1].y, 0.0);
    }

    #[test]
    fn disabled_bending_does_not_dilute_stretch_projection() {
        let mut snapshot = snapshot();
        snapshot.source_positions.push([1.0, 1.0, 1.0]);
        snapshot
            .animation_frames
            .push(DMat4::from_translation(DVec3::ONE).to_cols_array_2d());
        snapshot.fixed.push(false);
        snapshot.alpha_blends.push(0.0);
        snapshot.constraints.push(Constraint::Hinge {
            indices: [0, 1, 2, 3],
            rest: 1.0,
        });
        let mut sim = Simulation::new(
            snapshot,
            &rig(),
            &[[0.0, 1.0, 0.0], [0.0; 3], [1.0, 0.0, 0.0]],
            &records(),
            &[0; 3],
            &|| false,
        )
        .unwrap();
        sim.step(
            1.0 / 60.0,
            DMat4::from_translation(DVec3::Y).to_cols_array_2d(),
            Settings {
                gravity: 0.0,
                stretch: 1.0,
                bend: 0.0,
                iterations: 1,
                ..Settings::default()
            },
        )
        .unwrap();
        close(sim.positions()[1], DVec3::Y);
    }

    #[test]
    fn bounded_motion_stays_finite_and_failed_steps_preserve_the_last_complete_frame() {
        let mut sim = simulation([0; 3]);
        for i in 0..90 {
            let motion = DMat4::from_translation(DVec3::Y * (0.1 * (f64::from(i) * 0.1).sin()));
            sim.step(
                1.0 / 60.0,
                motion.to_cols_array_2d(),
                Settings {
                    ground_height: Some(-0.25),
                    ..Settings::default()
                },
            )
            .unwrap();
            assert!(sim.positions().iter().flatten().all(|v| v.is_finite()));
            assert!(sim.guide_positions()[1][1] >= -0.25);
        }
        let frame = sim.positions().to_vec();
        let guides = sim.guide_positions();
        assert!(
            sim.step(
                f64::NAN,
                DMat4::IDENTITY.to_cols_array_2d(),
                Settings::default()
            )
            .is_err()
        );
        assert!(
            sim.step(
                0.01,
                DMat4::from_scale(DVec3::splat(2.0)).to_cols_array_2d(),
                Settings::default()
            )
            .is_err()
        );
        assert!(
            sim.step(
                0.01,
                DMat4::IDENTITY.to_cols_array_2d(),
                Settings {
                    iterations: 0,
                    ..Settings::default()
                }
            )
            .is_err()
        );
        assert_eq!(sim.positions(), frame);
        assert_eq!(sim.guide_positions(), guides);
    }

    #[test]
    fn preparation_rejects_stale_zero_weight_and_even_zero_weight_out_of_range_guide_indices() {
        let snapshot = snapshot();
        let rest = [[0.0; 3]; 3];
        assert!(
            Simulation::new(
                snapshot.clone(),
                &rig(),
                &rest,
                &records(),
                &[0; 3],
                &|| true
            )
            .is_err()
        );
        let mut bad = records();
        bad[0][32..36].fill(0);
        assert!(
            Simulation::new(snapshot.clone(), &rig(), &rest, &bad, &[0; 3], &|| false).is_err()
        );
        bad = records();
        bad[0][12..14].copy_from_slice(&0x6400u16.to_le_bytes()); // half1024, zero weight.
        assert!(
            Simulation::new(snapshot.clone(), &rig(), &rest, &bad, &[0; 3], &|| false).is_err()
        );
        let mut bad_snapshot = snapshot.clone();
        bad_snapshot.constraints.push(Constraint::Pair {
            indices: [0, 3],
            rest: 1.0,
        });
        assert!(
            Simulation::new(bad_snapshot, &rig(), &rest, &records(), &[0; 3], &|| false).is_err()
        );
        let mut area_snapshot = snapshot;
        area_snapshot.constraints.push(Constraint::Triangle {
            indices: [0, 1, 2],
            rest: 0.5,
        });
        let sim =
            Simulation::new(area_snapshot, &rig(), &rest, &records(), &[0; 3], &|| false).unwrap();
        assert_eq!(sim.inactive_area_constraints, 1);
    }
}
