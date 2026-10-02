//! Controlled guide-cloth stepping and the decoded PAC guide-to-render blend.
//!
//! The host resolves the matching rig and CPU rest geometry. This preview uses
//! explicit forces, a bounded Jacobi schedule and rigid anchor motion, not a
//! recovered game dispatch/profile. Optional single/two-edge rotation uses decoded
//! neighbors. Optional authored body primitives follow the same rigid test motion.
//! Area constraints remain inactive; layer/world contacts and runtime overrides
//! remain separate work. Source and authored data are immutable.

use crate::jiggle_rig::{Rig, RigSnapshot};
use crate::jiggle_skinning::{self, Matrix};
use glam::{DMat4, DVec3};
use serde::{Deserialize, Serialize};

mod rotation;
mod spline;
pub use collision::BodyCollider;

type Result<T> = std::result::Result<T, &'static str>;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Snapshot {
    pub version: u32,
    pub source_positions: Vec<[f64; 3]>,
    pub animation_frames: Vec<Matrix>,
    pub fixed: Vec<bool>,
    pub alpha_blends: Vec<f64>,
    #[serde(default)]
    pub orientation_neighbors: Vec<Option<[u16; 2]>>,
    pub constraints: Vec<Constraint>,
    #[serde(default)]
    pub spline_chains: Vec<Vec<usize>>,
    #[serde(default)]
    pub body_colliders: Vec<BodyCollider>,
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
    /// Acceleration toward -Y; negate authored XML gravity at the preview boundary.
    pub gravity: f64,
    /// Decoded normal damping coefficient; each step multiplies v by 1-0.1*d.
    pub damping: f64,
    /// Explicit modified per-iteration coefficients, not raw material XML.
    pub stretch: f64,
    pub bend: f64,
    pub spline: bool,
    /// Controlled angular spring-back coefficient, converted from raw XML.
    pub restore_angle: f64,
    pub iterations: u32,
    pub speed_limit: f64,
    pub use_vertex_alpha: bool,
    pub rotate_guides: bool,
    /// Select the decoded single-edge branch; ignored with rotation disabled.
    pub single_edge_rotation: bool,
    pub ground_height: Option<f64>,
    pub body_collisions: bool,
    pub collision_margin: f64,
}

impl Default for Settings {
    fn default() -> Self {
        // Controlled preview choices. No active game material is inferred.
        Self {
            gravity: 9.81,
            damping: 0.5,
            stretch: 0.8,
            bend: 0.1,
            spline: false,
            restore_angle: 0.025,
            iterations: 4,
            speed_limit: 50.0,
            use_vertex_alpha: false,
            rotate_guides: false,
            single_edge_rotation: false,
            ground_height: None,
            body_collisions: false,
            collision_margin: 0.01,
        }
    }
}

impl Settings {
    fn valid(self) -> bool {
        self.gravity.is_finite()
            && (-100.0..=100.0).contains(&self.gravity)
            && self.damping.is_finite()
            && (0.0..=10.0).contains(&self.damping)
            && self.stretch.is_finite()
            && (0.0..=1.0).contains(&self.stretch)
            && self.bend.is_finite()
            && (0.0..=1.0).contains(&self.bend)
            && self.restore_angle.is_finite()
            && (0.0..=1.0).contains(&self.restore_angle)
            && (1..=8).contains(&self.iterations)
            && self.speed_limit.is_finite()
            && (0.001..=1000.0).contains(&self.speed_limit)
            && self.ground_height.is_none_or(f64::is_finite)
            && self.collision_margin.is_finite()
            && (0.0..=0.1).contains(&self.collision_margin)
    }
}

#[derive(Debug)]
struct Binding {
    rest: DVec3,
    source_rest: DVec3,
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
    previous_motion: DMat4,
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
            || (!snapshot.orientation_neighbors.is_empty()
                && snapshot.orientation_neighbors.len() != count)
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
        if snapshot.body_colliders.len() > 128
            || snapshot
                .body_colliders
                .iter()
                .any(|c| !c.valid(rig.parents.len()))
            || snapshot
                .body_colliders
                .windows(2)
                .any(|rows| rows[0].source_ordinal >= rows[1].source_ordinal)
        {
            return Err("Cloth body colliders have invalid geometry or source bindings.");
        }
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
        spline::validate(&snapshot)?;
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
                source_rest: DVec3::ZERO,
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
            // Bind displayed positions through the complete neutral blend so
            // guide rotation preserves neutral scale and existing sculpt edits.
            binding.source_rest = inverse(neutral)?.transform_point3(binding.rest);
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
            previous_motion: DMat4::IDENTITY,
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
        if settings.spline && self.snapshot.spline_chains.is_empty() {
            return Err("Spline preview needs complete ordered guide chains with fixed roots.");
        }
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
        if settings.body_collisions && self.snapshot.body_colliders.is_empty() {
            return Err("No authored body colliders are available for this preview.");
        }
        let colliders =
            if settings.body_collisions && self.bindings.iter().any(|b| b.skeletal_blend < 1.0) {
                self.snapshot
                    .body_colliders
                    .iter()
                    .map(|c| c.in_motion(motion))
                    .collect::<Vec<_>>()
            } else {
                Vec::new()
            };
        let to_previous_body = self.previous_motion * motion.inverse();
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
                    Constraint::Hinge { indices, rest } if settings.bend > 0.0 && !settings.spline => {
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
            if settings.spline {
                spline::project(
                    &self.snapshot.spline_chains,
                    &positions,
                    &animation,
                    &masses,
                    settings,
                    &mut corrections,
                    &mut counts,
                );
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
            // Recover integration/constraint velocity before positional contact
            // correction. Initial penetration is not an outgoing impulse;
            // moving bodies transfer normal velocity explicitly below.
            let mut velocity = if self.snapshot.fixed[i] {
                DVec3::ZERO
            } else {
                ((positions[i] - self.positions[i]) / dt).clamp_length_max(settings.speed_limit)
            };
            let mut contacts = Vec::new();
            if !self.snapshot.fixed[i] {
                for collider in &colliders {
                    if let Some((point, normal)) =
                        collider.project(positions[i], settings.collision_margin)?
                    {
                        positions[i] = point;
                        let body_velocity = (point - to_previous_body.transform_point3(point)) / dt;
                        contacts.push((normal, body_velocity));
                    }
                }
            }
            let mut ground_contact = false;
            if !self.snapshot.fixed[i]
                && let Some(height) = settings.ground_height
            {
                ground_contact = positions[i].y < height;
                positions[i].y = positions[i].y.max(height);
            }
            if ground_contact {
                velocity.y = 0.0;
            }
            for (normal, body_velocity) in contacts {
                let inward = (velocity - body_velocity).dot(normal).min(0.0);
                velocity -= inward * normal;
            }
            velocity = velocity.clamp_length_max(settings.speed_limit);
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
        let rotated =
            if settings.rotate_guides && self.bindings.iter().any(|b| b.skeletal_blend < 1.0) {
                let spline_neighbors = settings.spline.then(||
                    spline::neighbors(&self.snapshot.spline_chains, positions.len()));
                let neighbors = spline_neighbors.as_ref().unwrap_or(&self.snapshot.orientation_neighbors);
                if neighbors.len() != positions.len() {
                    return Err("Guide rotation needs known orientation neighbors.");
                }
                let mut deltas = Vec::with_capacity(positions.len());
                for i in 0..positions.len() {
                    let neighbors =
                        neighbors[i]
                        .ok_or("Guide rotation needs known orientation neighbors.")?;
                    let correction = if settings.single_edge_rotation || settings.spline {
                        // This controlled preview displays the current step directly.
                        rotation::single_edge(i, neighbors, &animation, &positions, &positions)?
                    } else {
                        rotation::two_edge(i, neighbors, &animation, &positions)?
                    };
                    let animated = motion * self.frames[i];
                    let mut simulated = glam::DMat4::from_cols(
                        (correction * animated.x_axis.truncate()).extend(0.0),
                        (correction * animated.y_axis.truncate()).extend(0.0),
                        (correction * animated.z_axis.truncate()).extend(0.0),
                        positions[i].extend(1.0),
                    );
                    let source = self.snapshot.source_positions[i];
                    simulated = guide_matrix(simulated, source);
                    let animated = motion * guide_matrix(self.frames[i], source);
                    deltas.push(simulated - animated);
                }
                Some(deltas)
            } else {
                None
            };
        let mut output = Vec::with_capacity(self.bindings.len());
        for binding in &self.bindings {
            // Start with rigid motion, then apply the guide matrix difference.
            // With correction off, that difference reduces to translation.
            let mut point = motion.transform_point3(binding.rest);
            if binding.skeletal_blend != 1.0 {
                let delta = (0..4).fold(DVec3::ZERO, |sum, i| {
                    let delta = if let Some(matrices) = &rotated {
                        (matrices[binding.indices[i]] * binding.source_rest.extend(1.0)).truncate()
                    } else {
                        displacement[binding.indices[i]]
                    };
                    sum + delta * binding.weights[i]
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
        self.previous_motion = motion;
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

    #[test]
    fn single_edge_rotation_handles_collinear_guides_and_preserves_render_contributions() {
        const ID: Matrix = DMat4::IDENTITY.to_cols_array_2d();
        let mut data = snapshot();
        data.source_positions = vec![[0., 0., 0.], [1., 0., 0.], [2., 0., 0.]];
        data.animation_frames = data
            .source_positions
            .iter()
            .map(|point| DMat4::from_translation(DVec3::from(*point)).to_cols_array_2d())
            .collect();
        data.fixed = vec![false; 3];
        data.alpha_blends = vec![0.; 3];
        data.constraints.clear();
        data.orientation_neighbors = vec![Some([1, 2]), Some([u16::MAX; 2]), Some([u16::MAX; 2])];
        let mut record = [0_u8; 40];
        record[28] = 255;
        record[32] = 255;
        let rest = [[0.25, 0.5, 0.]; 3];
        let mut sim =
            Simulation::new(data, &rig(), &rest, &[record; 3], &[0, 32, 63], &|| false).unwrap();
        sim.positions = vec![
            DVec3::new(0.2, 0.3, 0.),
            DVec3::new(0.2, 1.3, 0.),
            DVec3::new(0.2, 2.3, 0.),
        ];
        let mut settings = Settings {
            gravity: 0.,
            rotate_guides: true,
            ..Default::default()
        };
        let guides = sim.guide_positions();
        // Two collinear edges cannot define a frame; one edge still defines
        // the decoded direction correction, without inventing another axis.
        assert!(sim.step(1. / 60., ID, settings).is_err());
        assert_eq!(sim.positions(), rest);
        assert_eq!(sim.guide_positions(), guides);
        settings.single_edge_rotation = true;
        sim.step(1. / 60., ID, settings).unwrap();
        let expected = DVec3::new(-0.3, 0.55, 0.);
        close(sim.positions()[0], expected);
        close(
            sim.positions()[1],
            DVec3::from(rest[1].map(f64::from)).lerp(expected, 31. / 63.),
        );
        assert_eq!(sim.positions()[2], rest[2]);
        let output = sim.positions().to_vec();
        sim.snapshot.orientation_neighbors[0] = None;
        assert!(sim.step(1. / 60., ID, settings).is_err());
        assert_eq!(sim.positions(), output);
        settings.rotate_guides = false;
        sim.step(1. / 60., ID, settings).unwrap();
        close(sim.positions()[0], DVec3::new(0.45, 0.8, 0.));
        assert_eq!(sim.positions()[2], rest[2]);
    }

    #[test]
    fn guide_rotation_transforms_about_each_guide_and_preserves_disabled_vertices() {
        const ID: Matrix = [
            [1., 0., 0., 0.],
            [0., 1., 0., 0.],
            [0., 0., 1., 0.],
            [0., 0., 0., 1.],
        ];
        let mut data = snapshot();
        data.source_positions = vec![[0., 0., 0.], [0., 1., 0.], [1., 0., 0.]];
        data.animation_frames = data
            .source_positions
            .iter()
            .map(|point| {
                let mut frame = ID;
                frame[3][..3].copy_from_slice(point);
                frame
            })
            .collect();
        data.fixed = vec![false; 3];
        data.alpha_blends = vec![0.; 3];
        data.constraints.clear();
        data.orientation_neighbors = vec![Some([1, 2]), Some([2, 0]), Some([0, 1])];
        let mut record = [0_u8; 40];
        record[28] = 255;
        record[32] = 255;
        let rest = [[0.25, 0.5, 0.], [0.25, 0.5, 0.], [0.25, 0.5, 0.]];
        let mut sim = Simulation::new(
            data.clone(),
            &rig(),
            &rest,
            &[record; 3],
            &[0, 32, 63],
            &|| false,
        )
        .unwrap();
        sim.positions = vec![
            DVec3::new(0.2, 0.3, 0.),
            DVec3::new(-0.8, 0.3, 0.),
            DVec3::new(0.2, 1.3, 0.),
        ];
        let settings = Settings {
            gravity: 0.,
            rotate_guides: true,
            ..Default::default()
        };
        sim.step(1. / 60., ID, settings).unwrap();
        let expected = DVec3::new(-0.3, 0.55, 0.);
        assert!(DVec3::from(sim.positions()[0].map(f64::from)).abs_diff_eq(expected, 1e-7));
        let expected = DVec3::from(rest[1].map(f64::from)).lerp(expected, 31. / 63.);
        assert!(DVec3::from(sim.positions()[1].map(f64::from)).abs_diff_eq(expected, 1e-7));
        assert_eq!(sim.positions()[2], rest[2]);
        let before = sim.positions().to_vec();
        let guide_before = sim.guide_positions();
        sim.snapshot.orientation_neighbors[0] = None;
        assert!(sim.step(1. / 60., ID, settings).is_err());
        assert_eq!(sim.positions(), before);
        assert_eq!(sim.guide_positions(), guide_before);

        // Nonuniform guide and skeletal scales give a different inverse neutral
        // blend at each contribution. Edited display positions are still the
        // authoritative rest pose, not positions reconstructed from the record.
        let mut scaled = data.clone();
        for frame in &mut scaled.animation_frames {
            frame[0][0] = 2.;
            frame[1][1] = 3.;
            frame[2][2] = 4.;
        }
        let mut scaled_rig = rig();
        scaled_rig.neutral_global_matrices[0][0][0] = 4.;
        scaled_rig.neutral_global_matrices[0][1][1] = 5.;
        scaled_rig.neutral_global_matrices[0][2][2] = 6.;
        scaled_rig.neutral_local_matrices = scaled_rig.neutral_global_matrices.clone();
        let edited = [[0.25, 0.5, 0.75]; 3];
        let mut scaled = Simulation::new(
            scaled,
            &scaled_rig,
            &edited,
            &[record; 3],
            &[0, 32, 63],
            &|| false,
        )
        .unwrap();
        scaled.positions = guide_before.iter().copied().map(DVec3::from).collect();
        scaled.step(1. / 60., ID, settings).unwrap();
        close(scaled.positions()[0], DVec3::new(-0.3, 0.55, 0.75));
        let fraction = 32. / 63.;
        let source_x = 0.25 / (2. + 2. * fraction);
        let source_y = 0.5 / (3. + 2. * fraction);
        close(
            scaled.positions()[1],
            DVec3::new(
                0.25 + (1. - fraction) * (0.2 - 3. * source_y - 2. * source_x),
                0.5 + (1. - fraction) * (0.3 + 2. * source_x - 3. * source_y),
                0.75,
            ),
        );
        assert_eq!(scaled.positions()[2], edited[2]);
        let mut old = data;
        old.orientation_neighbors.clear();
        let mut sim =
            Simulation::new(old, &rig(), &rest, &[record; 3], &[0, 32, 63], &|| false).unwrap();
        assert!(sim.step(1. / 60., ID, settings).is_err());
        assert!(sim.step(1. / 60., ID, Settings::default()).is_ok());
    }
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
            orientation_neighbors: Vec::new(),
            body_colliders: Vec::new(),
            spline_chains: Vec::new(),
            constraints: vec![Constraint::Pair {
                indices: [0, 1],
                rest: 1.0,
            }],
        }
    }

    fn spline_simulation(contributions: [u8; 3]) -> Simulation {
        let mut source = snapshot();
        source.source_positions = vec![[0.0; 3], [0.0, 0.0, 0.5], [0.0, 0.0, 1.0]];
        source.animation_frames = source
            .source_positions
            .iter()
            .map(|p| DMat4::from_translation(DVec3::from(*p)).to_cols_array_2d())
            .collect();
        source.alpha_blends = vec![1.0, 0.0, 0.0];
        source.spline_chains = vec![vec![0, 1, 2]];
        source.constraints = vec![
            Constraint::Pair {
                indices: [0, 1],
                rest: 0.5,
            },
            Constraint::Pair {
                indices: [1, 2],
                rest: 0.5,
            },
        ];
        let rest = source
            .source_positions
            .iter()
            .map(|p| [0.1, p[1] as f32, p[2] as f32])
            .collect::<Vec<_>>();
        Simulation::new(source, &rig(), &rest, &records(), &contributions, &|| false).unwrap()
    }

    #[test]
    fn spline_preview_plays_rotates_and_preserves_fixed_and_disabled_vertices() {
        let settings = Settings {
            spline: true,
            rotate_guides: true,
            ..Settings::default()
        };
        let mut moving = spline_simulation([63, 0, 0]);
        let mut disabled = spline_simulation([63; 3]);
        let original = disabled.positions().to_vec();
        for _ in 0..120 {
            moving
                .step(1.0 / 60.0, DMat4::IDENTITY.to_cols_array_2d(), settings)
                .unwrap();
            disabled
                .step(1.0 / 60.0, DMat4::IDENTITY.to_cols_array_2d(), settings)
                .unwrap();
        }
        assert_eq!(moving.guide_positions()[0], [0.0; 3]);
        assert_eq!(moving.positions()[0], original[0]);
        assert_ne!(moving.positions()[2], original[2]);
        assert_eq!(disabled.positions(), original);
        assert!(moving.positions().iter().flatten().all(|x| x.is_finite()));
        let before = moving.positions().to_vec();
        assert!(
            moving
                .step(
                    1.0 / 60.0,
                    DMat4::IDENTITY.to_cols_array_2d(),
                    Settings {
                        restore_angle: f64::NAN,
                        ..settings
                    }
                )
                .is_err()
        );
        assert_eq!(moving.positions(), before);
    }

    #[test]
    fn spline_preview_controls_change_the_result_and_spring_back_restores_direction() {
        let baseline = Settings {
            spline: true,
            bend: 0.0,
            restore_angle: 0.0,
            ..Settings::default()
        };
        let run = |settings| {
            let mut simulation = spline_simulation([0; 3]);
            for _ in 0..60 {
                simulation
                    .step(1.0 / 60.0, DMat4::IDENTITY.to_cols_array_2d(), settings)
                    .unwrap();
            }
            DVec3::from(simulation.guide_positions()[2])
        };
        let base = run(baseline);
        for settings in [
            Settings {
                gravity: 0.0,
                ..baseline
            },
            Settings {
                damping: 3.0,
                ..baseline
            },
            Settings {
                stretch: 0.1,
                ..baseline
            },
            Settings {
                bend: 0.8,
                ..baseline
            },
            Settings {
                iterations: 8,
                ..baseline
            },
            Settings {
                restore_angle: 0.8,
                ..baseline
            },
        ] {
            assert!(
                run(settings).distance(base) > 1e-5,
                "control did not affect spline: {settings:?}"
            );
        }
        let restored = run(Settings {
            restore_angle: 0.8,
            ..baseline
        });
        assert!(restored.distance(DVec3::Z) < base.distance(DVec3::Z));
    }

    #[test]
    fn spline_preview_rejects_missing_or_ambiguous_chain_topology() {
        let mut simulation = simulation([0; 3]);
        assert!(
            simulation
                .step(
                    1.0 / 60.0,
                    DMat4::IDENTITY.to_cols_array_2d(),
                    Settings {
                        spline: true,
                        ..Settings::default()
                    }
                )
                .is_err()
        );
        let mut source = snapshot();
        for chains in [
            vec![vec![0, 1]],
            vec![vec![0, 1, 1]],
            vec![vec![1, 2, 0]],
            vec![vec![0, 1, 2]],
        ] {
            source.spline_chains = chains;
            assert!(spline::validate(&source).is_err());
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
    fn signed_gravity_moves_dynamic_guides_in_both_directions_and_keeps_pins_fixed() {
        for gravity in [-100.0, -20.0, 0.0, 20.0, 100.0] {
            let mut sim = simulation([0; 3]);
            let rest = sim.positions().to_vec();
            let settings = Settings {
                gravity,
                damping: 0.0,
                stretch: 0.0,
                bend: 0.0,
                ..Settings::default()
            };
            sim.step(0.02, DMat4::IDENTITY.to_cols_array_2d(), settings)
                .unwrap();
            let displacement = -gravity * 0.02 * 0.02;
            assert_eq!(sim.positions()[0], rest[0]);
            close(sim.positions()[1], DVec3::Y * displacement);
            close(sim.positions()[2], DVec3::X + DVec3::Y * displacement);
        }
    }

    #[test]
    fn signed_gravity_rejects_invalid_values_without_changing_the_frame() {
        let mut sim = simulation([0; 3]);
        let rest = sim.positions().to_vec();
        let guides = sim.guide_positions();
        for gravity in [-100.1, 100.1, f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
            let settings = Settings {
                gravity,
                ..Settings::default()
            };
            assert!(
                sim.step(0.02, DMat4::IDENTITY.to_cols_array_2d(), settings)
                    .is_err()
            );
            assert_eq!(sim.positions(), rest);
            assert_eq!(sim.guide_positions(), guides);
            assert!(sim.velocities.iter().all(|v| *v == DVec3::ZERO));
        }
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
    fn body_depenetration_does_not_launch_resting_guides() {
        for dt in [1.0 / 60.0, 1.0 / 480.0] {
            let mut sim = simulation([0; 3]);
            sim.snapshot.body_colliders.push(BodyCollider {
                kind: 5,
                center1: [-0.25, -1.0, 0.0],
                center2: [-0.25, 2.0, 0.0],
                radius: 0.5,
                bone_index: 0,
                source_ordinal: 0,
            });
            let settings = Settings {
                gravity: 0.0,
                damping: 0.0,
                stretch: 0.0,
                bend: 0.0,
                body_collisions: true,
                ..Settings::default()
            };
            for _ in 0..16 {
                sim.step(dt, DMat4::IDENTITY.to_cols_array_2d(), settings)
                    .unwrap();
                close(sim.positions()[1], DVec3::X * 0.26);
                assert!(sim.velocities[1].length() < 1e-10);
                assert_eq!(sim.positions()[0], [0.0, 1.0, 0.0]);
            }
        }
    }

    #[test]
    fn body_contacts_preserve_tangent_outward_and_moving_body_velocity() {
        let dt = 1.0 / 480.0;
        for incoming in [-1.0, 1.0] {
            let mut sim = simulation([0; 3]);
            sim.snapshot.body_colliders.push(BodyCollider {
                kind: 5,
                center1: [-0.25, -1.0, 0.0],
                center2: [-0.25, 2.0, 0.0],
                radius: 0.5,
                bone_index: 0,
                source_ordinal: 0,
            });
            let settings = Settings {
                gravity: 0.0,
                damping: 0.0,
                stretch: 0.0,
                bend: 0.0,
                body_collisions: true,
                ..Settings::default()
            };
            sim.velocities[1] = DVec3::new(incoming, 0.7, 0.0);
            sim.step(dt, DMat4::IDENTITY.to_cols_array_2d(), settings)
                .unwrap();
            let expected = DVec3::new(incoming.max(0.0), 0.7, 0.0);
            assert!(sim.velocities[1].distance(expected) < 1e-10);
            // The body moves faster than the outgoing guide. Contact transfers
            // its normal speed while preserving frictionless tangential motion.
            let motion = DMat4::from_translation(DVec3::X * (2.0 * dt));
            sim.step(dt, motion.to_cols_array_2d(), settings).unwrap();
            assert!(sim.velocities[1].distance(DVec3::new(2.0, 0.7, 0.0)) < 1e-10);
        }
    }

    #[test]
    fn body_contacts_follow_motion_preserve_contributions_and_bound_velocity() {
        let body = BodyCollider {
            kind: 5,
            center1: [-0.25, -1.0, 0.0],
            center2: [-0.25, 2.0, 0.0],
            radius: 0.5,
            bone_index: 0,
            source_ordinal: 0,
        };
        let make = |contributions| {
            let mut sim = simulation(contributions);
            sim.snapshot.body_colliders.push(body.clone());
            sim
        };
        let mut current = make([63, 32, 0]);
        let mut original = make([0; 3]);
        let mut disabled = make([63; 3]);
        let mut no_contacts = make([0; 3]);
        let settings = Settings {
            gravity: 0.0,
            damping: 0.0,
            stretch: 0.0,
            bend: 0.0,
            body_collisions: true,
            collision_margin: 0.01,
            speed_limit: 2.0,
            ..Settings::default()
        };
        let identity = DMat4::IDENTITY.to_cols_array_2d();
        for sim in [&mut current, &mut original, &mut disabled] {
            sim.step(0.01, identity, settings).unwrap();
        }
        no_contacts
            .step(
                0.01,
                identity,
                Settings {
                    body_collisions: false,
                    ..settings
                },
            )
            .unwrap();
        close(original.positions()[1], DVec3::X * 0.26);
        close(current.positions()[1], DVec3::X * (0.26 * 31.0 / 63.0));
        close(no_contacts.positions()[1], DVec3::ZERO);
        assert_eq!(disabled.positions(), no_contacts.positions());
        assert_eq!(original.guide_positions()[0], [0.0, 1.0, 0.0]);
        let motion = DMat4::from_translation(DVec3::X * 0.5) * DMat4::from_rotation_z(0.2);
        original
            .step(0.01, motion.to_cols_array_2d(), settings)
            .unwrap();
        let a = motion.transform_point3(DVec3::from(body.center1));
        let b = motion.transform_point3(DVec3::from(body.center2));
        let guide = DVec3::from(original.guide_positions()[1]);
        let axis = (b - a).normalize();
        let nearest = a + axis * (guide - a).dot(axis).clamp(0.0, (b - a).length());
        assert!(guide.distance(nearest) >= body.radius + settings.collision_margin - 1e-10);
        assert!(
            original
                .velocities
                .iter()
                .all(|v| v.length() <= settings.speed_limit + 1e-10)
        );
        close(original.positions()[0], motion.transform_point3(DVec3::Y));
    }

    #[test]
    fn body_contacts_reject_invalid_payloads_and_failed_steps_are_transactional() {
        let base = snapshot();
        let rest = base
            .source_positions
            .iter()
            .map(|p| p.map(|v| v as f32))
            .collect::<Vec<_>>();
        let body = BodyCollider {
            kind: 5,
            center1: [0.0, -1.0, 0.0],
            center2: [0.0, 2.0, 0.0],
            radius: 0.5,
            bone_index: 0,
            source_ordinal: 0,
        };
        let mut bad = vec![body.clone()];
        bad[0].radius = -0.5;
        let mut bad_bone = vec![body.clone()];
        bad_bone[0].bone_index = 1;
        for rows in [
            bad,
            bad_bone,
            vec![body.clone(); 2],
            vec![body.clone(); 129],
        ] {
            let mut snapshot = base.clone();
            snapshot.body_colliders = rows;
            assert!(
                Simulation::new(snapshot, &rig(), &rest, &records(), &[0; 3], &|| false).is_err()
            );
        }
        let mut sim = simulation([0; 3]);
        let frame = sim.positions().to_vec();
        let guides = sim.guide_positions();
        let settings = Settings {
            gravity: 0.0,
            stretch: 0.0,
            body_collisions: true,
            ..Settings::default()
        };
        assert!(
            sim.step(0.01, DMat4::IDENTITY.to_cols_array_2d(), settings)
                .is_err()
        );
        sim.snapshot.body_colliders.push(body);
        // Guide 1 lies exactly on the capsule axis, with no finite contact normal.
        assert!(
            sim.step(0.01, DMat4::IDENTITY.to_cols_array_2d(), settings)
                .is_err()
        );
        assert!(
            sim.step(
                0.01,
                DMat4::IDENTITY.to_cols_array_2d(),
                Settings {
                    collision_margin: f64::NAN,
                    ..settings
                }
            )
            .is_err()
        );
        assert_eq!(sim.positions(), frame);
        assert_eq!(sim.guide_positions(), guides);
        assert_eq!(sim.previous_motion, DMat4::IDENTITY);
        assert!(sim.velocities.iter().all(|v| *v == DVec3::ZERO));
        sim.step(
            0.01,
            DMat4::IDENTITY.to_cols_array_2d(),
            Settings {
                body_collisions: false,
                ..settings
            },
        )
        .unwrap();
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

mod collision {
    //! Authored neutral body primitives for the controlled cloth preview.
    //! Surface selection follows the decoded sphere/cylinder/capsule queries.
    //! Candidate admission, rigid test motion and frictionless velocity response
    //! are explicit preview choices, not the game's runtime collision profile.

    use super::Result;
    use glam::{DMat4, DVec3};
    use serde::{Deserialize, Serialize};

    #[derive(Clone, Debug, Serialize, Deserialize)]
    pub struct BodyCollider {
        pub kind: u8,
        pub center1: [f64; 3],
        pub center2: [f64; 3],
        pub radius: f64,
        pub bone_index: usize,
        pub source_ordinal: u32,
    }

    impl BodyCollider {
        pub(super) fn valid(&self, bones: usize) -> bool {
            matches!(self.kind, 1 | 3 | 5)
                && self.bone_index < bones
                && self.radius.is_finite()
                && self.radius > 0.0
                && self.radius <= 1e6
                && self
                    .center1
                    .iter()
                    .chain(&self.center2)
                    .all(|v| v.is_finite() && v.abs() <= 1e9)
                && (self.kind != 1 || self.center1 == self.center2)
                && (self.kind != 3
                    || DVec3::from(self.center1).distance(DVec3::from(self.center2)) > 1e-6)
        }

        pub(super) fn in_motion(&self, motion: DMat4) -> PlacedCollider {
            PlacedCollider {
                kind: self.kind,
                a: motion.transform_point3(DVec3::from(self.center1)),
                b: motion.transform_point3(DVec3::from(self.center2)),
                radius: self.radius,
            }
        }
    }

    pub(super) struct PlacedCollider {
        kind: u8,
        a: DVec3,
        b: DVec3,
        radius: f64,
    }

    fn unit(value: DVec3) -> Result<DVec3> {
        value
            .try_normalize()
            .ok_or("Body collision normal is degenerate.")
    }

    impl PlacedCollider {
        /// Only points inside the expanded primitive are admitted by this preview.
        /// Fixed guides are excluded by the caller. A contact returns its projected
        /// position and normal; the caller resolves velocity relative to the body.
        pub(super) fn project(&self, point: DVec3, margin: f64) -> Result<Option<(DVec3, DVec3)>> {
            let radius = self.radius + margin;
            let edge = self.b - self.a;
            let length = edge.length();
            if self.kind == 1 || self.kind == 5 {
                let center = if self.kind == 5 && length >= f64::from(0.000001_f32) {
                    let axis = edge / length;
                    self.a + axis * (point - self.a).dot(axis).clamp(0.0, length)
                } else {
                    self.a
                };
                let radial = point - center;
                if radial.length_squared() >= radius * radius {
                    return Ok(None);
                }
                let normal = unit(radial)?;
                return Ok(Some((center + radius * normal, normal)));
            }
            let axis = unit(edge)?;
            let a = self.a - margin * axis;
            let half = length * 0.5 + margin;
            let relative = point - a;
            let along = relative.dot(axis);
            let radial = relative - along * axis;
            let radial_distance = radial.length() - radius;
            let cap_distance = (along - half).abs() - half;
            if radial_distance >= 0.0 || cap_distance >= 0.0 {
                return Ok(None);
            }
            let cap_normal = if along > half { axis } else { -axis };
            // The decoded query chooses the cap on equal cap/side distances.
            let side = cap_distance < radial_distance;
            let mut normal = if side { unit(radial)? } else { cap_normal };
            let distance = if side { radial_distance } else { cap_distance };
            let surface = point - distance * normal;
            let band = half.min(radius) * 0.5;
            if radial_distance.min(cap_distance) > -band {
                normal = unit(
                    (band + radial_distance) * unit(radial)? + (band + cap_distance) * cap_normal,
                )?;
            }
            Ok(Some((surface, normal)))
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        fn collider(kind: u8) -> PlacedCollider {
            BodyCollider {
                kind,
                center1: [0.0; 3],
                center2: [0.0, 2.0, 0.0],
                radius: 1.0,
                bone_index: 0,
                source_ordinal: 0,
            }
            .in_motion(DMat4::IDENTITY)
        }

        #[test]
        fn cloth_body_surfaces_preserve_capsule_ends_sphere_radius_and_cylinder_caps() {
            let (point, normal) = collider(5)
                .project(DVec3::new(0.5, 1.0, 0.0), 0.1)
                .unwrap()
                .unwrap();
            assert!(point.distance(DVec3::new(1.1, 1.0, 0.0)) < 1e-12);
            assert_eq!(normal, DVec3::X);
            assert_eq!(
                collider(5)
                    .project(DVec3::new(0.0, 2.5, 0.0), 0.0)
                    .unwrap()
                    .unwrap()
                    .0,
                DVec3::new(0.0, 3.0, 0.0)
            );
            assert_eq!(
                collider(1)
                    .project(DVec3::new(0.0, 0.5, 0.0), 0.0)
                    .unwrap()
                    .unwrap()
                    .0,
                DVec3::Y
            );
            assert_eq!(
                collider(3)
                    .project(DVec3::new(0.5, 1.5, 0.0), 0.0)
                    .unwrap()
                    .unwrap(),
                (DVec3::new(0.5, 2.0, 0.0), DVec3::Y)
            );
            assert_eq!(
                collider(3).project(DVec3::new(0.5, 2.5, 0.0), 0.0).unwrap(),
                None
            );
            assert_eq!(
                collider(5).project(DVec3::new(2.0, 1.0, 0.0), 0.0).unwrap(),
                None
            );
            assert!(collider(5).project(DVec3::Y, 0.0).is_err());
        }
    }
}
