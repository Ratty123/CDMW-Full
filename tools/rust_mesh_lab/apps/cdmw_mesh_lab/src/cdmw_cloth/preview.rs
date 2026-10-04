//! Playback adapter for the shared motion preview controller and bounded loader.
use super::super::*;
use cdmw_archive::CancellationToken;
use cdmw_mesh::{cloth, jiggle, jiggle_rig::RigSnapshot, jiggle_skinning::Matrix};

const FRAME_STEP: f64 = 1.0 / 60.0;
// Small steps keep dense guide meshes from stretching under gravity before
// Jacobi corrections can propagate. This is an explicit preview schedule.
pub(crate) const SUBSTEPS: u32 = 8;
const STEP: f64 = FRAME_STEP / SUBSTEPS as f64;

pub(crate) fn default_settings(spline: bool) -> cloth::Settings {
    if spline {
        cloth::Settings {
            spline: true,
            bend: 0.0,
            restore_angle: 0.0,
            use_vertex_alpha: true,
            rotate_guides: true,
            single_edge_rotation: true,
            ..Default::default()
        }
    } else {
        cloth::Settings::default()
    }
}

pub(crate) fn substep_settings(mut settings: cloth::Settings) -> Result<cloth::Settings> {
    if !settings.damping.is_finite() || !(0.0..=10.0).contains(&settings.damping) {
        bail!("Invalid cloth preview damping.");
    }
    // Preserve the slider's 60 Hz decay rather than applying it eight times.
    let coefficient = f64::from(0.1_f32);
    let decay = (1.0 - coefficient * settings.damping).max(0.0);
    settings.damping = (1.0 - decay.powf(1.0 / f64::from(SUBSTEPS))) / coefficient;
    Ok(settings)
}

#[derive(Debug)]
pub(crate) struct Simulation {
    core: cloth::Simulation,
    pivot: Vec3,
    scale: f32,
    accumulator: f64,
    pub elapsed: f64,
    pub rotation: Quat,
    pub motion_transform: glam::Mat4,
    weapon_reference_start: usize,
    weapon_transform: glam::DMat4,
    pub weapon_target: glam::DMat4,
    pub hold_body: bool,
}

impl Simulation {
    pub fn new(
        mut snapshot: cloth::Snapshot,
        rig: &RigSnapshot,
        rest: &[[f32; 3]],
        records: &[[u8; 40]],
        contributions: &[u8],
        cancellation: &CancellationToken,
    ) -> Result<Self> {
        // Authored alpha is a frame blend too. Preserve its net amount when
        // the optional blend is enabled; invalid source values remain invalid.
        for alpha in &mut snapshot.alpha_blends {
            if (0.0..=1.0).contains(alpha) {
                *alpha = 1.0 - (1.0 - *alpha).powf(1.0 / f64::from(SUBSTEPS));
            }
        }
        let core = cloth::Simulation::new(snapshot, rig, rest, records, contributions, &|| {
            cancellation.check().is_err()
        })
        .map_err(anyhow::Error::msg)?;
        let min = rest
            .iter()
            .copied()
            .map(Vec3::from)
            .fold(Vec3::splat(f32::INFINITY), Vec3::min);
        let max = rest
            .iter()
            .copied()
            .map(Vec3::from)
            .fold(Vec3::splat(f32::NEG_INFINITY), Vec3::max);
        let scale = (max - min).max_element();
        if !(1e-6..=1e6).contains(&scale) || !(min + max).is_finite() {
            bail!("Invalid cloth preview mesh scale.");
        }
        let weapon_reference_start = core.weapon_colliders().len();
        Ok(Self {
            core,
            pivot: (min + max) * 0.5,
            scale,
            accumulator: 0.0,
            elapsed: 0.0,
            rotation: Quat::IDENTITY,
            motion_transform: glam::Mat4::IDENTITY,
            weapon_reference_start,
            weapon_transform: glam::DMat4::IDENTITY,
            weapon_target: glam::DMat4::IDENTITY,
            hold_body: false,
        })
    }

    pub fn positions(&self) -> &[[f32; 3]] {
        self.core.positions()
    }

    pub fn set_weapon_reference(&mut self, count: usize) -> Result<()> {
        if count == 0 || count > self.core.weapon_colliders().len() {
            bail!("Weapon reference contacts do not match the preview snapshot.");
        }
        self.weapon_reference_start = self.core.weapon_colliders().len() - count;
        Ok(())
    }

    pub fn collider_lines(&self, centred: bool) -> Vec<cdmw_render_wgpu::EffectLineVertex> {
        let transform = if centred { glam::Mat4::IDENTITY } else { self.motion_transform };
        let mut lines = Vec::new();
        for (colliders, colour, weapon) in [(self.core.body_colliders(), [0.2, 0.85, 1., 1.], false),
                                   (self.core.weapon_colliders(), [1., 0.7, 0.15, 1.], true)] {
        for (index, collider) in colliders.iter().enumerate() {
            let transform = if weapon && index >= self.weapon_reference_start {
                transform * self.weapon_target.as_mat4()
            } else { transform };
            let a = Vec3::from(collider.center1.map(|v| v as f32));
            let b = if collider.kind == 1 { a } else { Vec3::from(collider.center2.map(|v| v as f32)) };
            let radius = collider.radius as f32;
            let axis = (b - a).try_normalize().unwrap_or(Vec3::Y);
            let seed = if axis.x.abs() < 0.9 { Vec3::X } else { Vec3::Z };
            let x = axis.cross(seed).normalize();
            let z = axis.cross(x);
            let mut line = |from: Vec3, to: Vec3| {
                for point in [from, to] {
                    lines.push(cdmw_render_wgpu::EffectLineVertex {
                        position: transform.transform_point3(point).to_array(), colour,
                    });
                }
            };
            for center in [a, b] {
                for i in 0..16 {
                    let p = std::f32::consts::TAU * i as f32 / 16.;
                    let q = std::f32::consts::TAU * (i + 1) as f32 / 16.;
                    line(center + radius * (x * p.cos() + z * p.sin()),
                         center + radius * (x * q.cos() + z * q.sin()));
                }
            }
            for radial in [x, z, -x, -z] {
                line(a + radial * radius, b + radial * radius);
                if collider.kind == 3 { continue; }
                for (center, direction) in [(a, -axis), (b, axis)] {
                    for i in 0..8 {
                        let p = std::f32::consts::FRAC_PI_2 * i as f32 / 8.;
                        let q = std::f32::consts::FRAC_PI_2 * (i + 1) as f32 / 8.;
                        line(center + radius * (radial * p.cos() + direction * p.sin()),
                             center + radius * (radial * q.cos() + direction * q.sin()));
                    }
                }
            }
        }
        }
        lines
    }

    pub fn advance(
        &mut self,
        seconds: f64,
        motion: jiggle::Motion,
        settings: cloth::Settings,
    ) -> Result<()> {
        if !seconds.is_finite() || seconds < 0.0 || !motion.is_valid() {
            bail!("Invalid cloth preview frame time.");
        }
        let settings = substep_settings(settings)?;
        self.accumulator = (self.accumulator + seconds).min(FRAME_STEP * 8.0);
        let steps = ((self.accumulator + 1e-12) / STEP).floor() as u32;
        let (_, start_rotation, start_translation) = self.weapon_transform.to_scale_rotation_translation();
        let (_, end_rotation, end_translation) = self.weapon_target.to_scale_rotation_translation();
        let mut step = 0;
        while self.accumulator + 1e-12 >= STEP {
            step += 1;
            let fraction = f64::from(step) / f64::from(steps);
            let weapon_transform = glam::DMat4::from_rotation_translation(
                start_rotation.slerp(end_rotation, fraction), start_translation.lerp(end_translation, fraction));
            let elapsed = self.elapsed + STEP;
            let phase = (elapsed % 4.0) as f32;
            let (rotation, translation) = match motion {
                jiggle::Motion::Freehand(offset) => (Quat::IDENTITY, offset),
                jiggle::Motion::UpDown => {
                    let phase = (elapsed % 1.2) as f32 * std::f32::consts::TAU / 1.2;
                    (
                        Quat::IDENTITY,
                        Vec3::Y * self.scale * 0.06 * (1.0 - phase.cos()),
                    )
                }
                jiggle::Motion::StartStop => {
                    let t = if phase < 0.6 {
                        phase / 0.6
                    } else if phase < 2.0 {
                        1.0
                    } else if phase < 2.6 {
                        1.0 - (phase - 2.0) / 0.6
                    } else {
                        0.0
                    };
                    (
                        Quat::IDENTITY,
                        Vec3::Z * self.scale * 0.16 * t * t * (3.0 - 2.0 * t),
                    )
                }
                jiggle::Motion::Turn => (
                    Quat::from_rotation_y((phase * std::f32::consts::TAU / 4.0).sin() * 0.4),
                    Vec3::ZERO,
                ),
            };
            let rotation = if self.hold_body { self.rotation } else { rotation };
            let motion_transform = if self.hold_body { self.motion_transform } else { glam::Mat4::from_rotation_translation(
                rotation,
                self.pivot + translation - rotation * self.pivot,
            ) };
            let transform: Matrix = motion_transform.to_cols_array_2d()
                .map(|row| row.map(f64::from));
            self.core
                .step_with_weapon_transform(STEP, transform, settings, self.weapon_reference_start,
                                            weapon_transform.to_cols_array_2d())
                .map_err(anyhow::Error::msg)?;
            self.elapsed = elapsed;
            self.rotation = rotation;
            self.motion_transform = motion_transform;
            self.weapon_transform = weapon_transform;
            self.accumulator -= STEP;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spline_strip() -> Result<(Simulation, Vec<[f32; 3]>)> {
        let identity = glam::DMat4::IDENTITY.to_cols_array_2d();
        let positions = (0..6).map(|i| [0., 0., f64::from(i) * 0.16]).collect::<Vec<_>>();
        let snapshot = cloth::Snapshot {
            version: 1,
            animation_frames: positions.iter().map(|p| {
                let mut frame = identity;
                frame[3][..3].copy_from_slice(p);
                frame
            }).collect(),
            source_positions: positions.clone(),
            fixed: vec![true, false, false, false, false, false],
            alpha_blends: vec![1., 0., 0., 0., 0., 0.],
            orientation_neighbors: Vec::new(),
            body_colliders: Vec::new(),
            weapon_colliders: Vec::new(),
            spline_chains: vec![vec![0, 1, 2, 3, 4, 5]],
            constraints: (1..6).map(|i| cloth::Constraint::Pair { indices: [i - 1, i], rest: 0.16 }).collect(),
        };
        let rig = RigSnapshot {
            bone_palette: vec![0],
            parents: vec![-1],
            inverse_bind_matrices: vec![identity],
            neutral_global_matrices: vec![identity],
            neutral_local_matrices: vec![identity],
        };
        let mut rest = positions.iter().map(|p| [0.02, p[1] as f32, p[2] as f32]).collect::<Vec<_>>();
        rest.push([0.04, -0.1, 0.42]);
        let records = (0u32..7).map(|i| {
            let mut record = [0; 40];
            record[28] = 255;
            record[32] = 255;
            record[24..28].copy_from_slice(&((i % 6) << 10).to_le_bytes());
            record
        }).collect::<Vec<_>>();
        let simulation = Simulation::new(snapshot, &rig, &rest, &records,
            &[0, 0, 0, 0, 0, 0, 63], &CancellationToken::default())?;
        Ok((simulation, rest))
    }

    fn spline_profile() -> cloth::Settings {
        cloth::Settings {
            spline: true, gravity: 10., damping: 0.75, stretch: 0.60009765625,
            bend: 0., restore_angle: 0.00630950927734375, iterations: 2,
            use_vertex_alpha: true, rotate_guides: true, single_edge_rotation: true,
            ..Default::default()
        }
    }

    #[test]
    fn spline_profile_hangs_under_gravity_without_stretching_or_moving_rigid_vertices() -> Result<()> {
        let (mut simulation, rest) = spline_strip()?;
        for _ in 0..180 {
            simulation.advance(FRAME_STEP, jiggle::Motion::Freehand(Vec3::ZERO), spline_profile())?;
        }
        let guides = simulation.core.guide_positions();
        let drop = guides[0][1] - guides[5][1];
        assert!(drop > 0.6, "an 80 cm ribbon only dropped {drop} m");
        assert_eq!(guides[0], [0.; 3]);
        assert_eq!(simulation.positions()[6], rest[6]);
        for pair in guides.windows(2) {
            let ratio = glam::DVec3::from(pair[0]).distance(glam::DVec3::from(pair[1])) / 0.16;
            assert!((0.98..1.02).contains(&ratio), "spline segment length changed by {ratio}");
        }
        Ok(())
    }

    #[test]
    fn spline_profile_flexes_during_start_stop_and_keeps_its_attachment() -> Result<()> {
        let (mut simulation, rest) = spline_strip()?;
        let mut maximum_bend = 0f64;
        for _ in 0..180 {
            simulation.advance(FRAME_STEP, jiggle::Motion::StartStop, spline_profile())?;
            let guides = simulation.core.guide_positions();
            let root = Vec3::from(guides[0].map(|v| v as f32));
            assert!(root.distance(simulation.motion_transform.transform_point3(Vec3::ZERO)) < 1e-6);
            assert!(Vec3::from(simulation.positions()[6]).distance(
                simulation.motion_transform.transform_point3(Vec3::from(rest[6]))) < 1e-6);
            for points in guides.windows(3) {
                let a = (glam::DVec3::from(points[1]) - glam::DVec3::from(points[0])).normalize();
                let b = (glam::DVec3::from(points[2]) - glam::DVec3::from(points[1])).normalize();
                maximum_bend = maximum_bend.max(a.dot(b).clamp(-1., 1.).acos().to_degrees());
            }
        }
        assert!(maximum_bend > 30., "spline acted like a stick: {maximum_bend} degrees");
        Ok(())
    }

    #[test]
    fn spline_profile_keeps_comparable_sag_at_different_solver_step_sizes() -> Result<()> {
        let mut tips = Vec::new();
        for rate in [240u32, 480, 960] {
            let (simulation, _) = spline_strip()?;
            let mut core = simulation.core;
            let mut settings = spline_profile();
            let coefficient = f64::from(0.1_f32);
            let decay = 1. - coefficient * settings.damping;
            settings.damping = (1. - decay.powf(60. / f64::from(rate))) / coefficient;
            for _ in 0..3 * rate {
                core.step(1. / f64::from(rate), glam::DMat4::IDENTITY.to_cols_array_2d(), settings)
                    .map_err(anyhow::Error::msg)?;
            }
            tips.push(glam::DVec3::from(core.guide_positions()[5]));
        }
        for tip in &tips {
            assert!(tip.y < -0.6, "small steps froze the spline at {tip:?}");
            assert!(tip.distance(tips[1]) < 0.04, "step size changed the spline shape: {tips:?}");
        }
        Ok(())
    }

    #[test]
    fn small_steps_bound_strip_stretch_and_preserve_preview_clock_and_damping() -> Result<()> {
        for damping in [0.0, 0.5, 10.0] {
            let settings = substep_settings(cloth::Settings {
                damping,
                ..Default::default()
            })?;
            let coefficient = f64::from(0.1_f32);
            assert!(
                ((1.0 - coefficient * settings.damping).powi(SUBSTEPS as i32)
                    - (1.0 - coefficient * damping).max(0.0))
                .abs()
                    < 1e-12
            );
        }
        assert!(
            substep_settings(cloth::Settings {
                damping: -1.0,
                ..Default::default()
            })
            .is_err()
        );
        let identity = [
            [1., 0., 0., 0.],
            [0., 1., 0., 0.],
            [0., 0., 1., 0.],
            [0., 0., 0., 1.],
        ];
        let positions = (0..24)
            .map(|i| [0.0, 1.0 - f64::from(i) * 0.03, 0.0])
            .collect::<Vec<_>>();
        let frames = positions
            .iter()
            .map(|position| {
                let mut frame = identity;
                frame[3][..3].copy_from_slice(position);
                frame
            })
            .collect();
        let snapshot = cloth::Snapshot {
            version: 1,
            source_positions: positions.clone(),
            animation_frames: frames,
            fixed: (0..24).map(|i| i == 0).collect(),
            alpha_blends: vec![0.0; 24],
            orientation_neighbors: Vec::new(),
            body_colliders: Vec::new(),
            weapon_colliders: Vec::new(),
            spline_chains: Vec::new(),
            constraints: (1..24)
                .map(|i| cloth::Constraint::Pair {
                    indices: [i - 1, i],
                    rest: 0.03,
                })
                .collect(),
        };
        let rig = RigSnapshot {
            bone_palette: vec![0],
            parents: vec![-1],
            inverse_bind_matrices: vec![identity],
            neutral_global_matrices: vec![identity],
            neutral_local_matrices: vec![identity],
        };
        let rest = [
            positions[0].map(|v| v as f32),
            positions[23].map(|v| v as f32),
        ];
        let records = [0_u32, 23].map(|index| {
            let mut record = [0_u8; 40];
            record[28] = 255;
            record[32] = 255;
            record[24..28].copy_from_slice(&(index << 10).to_le_bytes());
            record
        });
        let mut simulation = Simulation::new(
            snapshot,
            &rig,
            &rest,
            &records,
            &[0, 0],
            &CancellationToken::default(),
        )?;
        for _ in 0..120 {
            simulation.advance(
                FRAME_STEP,
                jiggle::Motion::UpDown,
                cloth::Settings::default(),
            )?;
        }
        assert!((simulation.elapsed - 2.0).abs() < 1e-12);
        let guides = simulation.core.guide_positions();
        let maximum_ratio = guides
            .windows(2)
            .map(|pair| glam::DVec3::from(pair[0]).distance(glam::DVec3::from(pair[1])) / 0.03)
            .fold(0.0, f64::max);
        assert!(
            maximum_ratio < 1.15,
            "strip stretched {maximum_ratio} times its rest length"
        );
        let offset = Vec3::new(0.1, 0.05, -0.08);
        for _ in 0..30 {
            simulation.advance(FRAME_STEP, jiggle::Motion::Freehand(offset), cloth::Settings::default())?;
        }
        assert!(Vec3::from(simulation.positions()[0]).distance(Vec3::from(rest[0]) + offset) < 1e-5);
        assert!(
            simulation
                .positions()
                .iter()
                .flatten()
                .all(|v| v.is_finite())
        );
        Ok(())
    }

    #[test]
    fn authored_half_alpha_still_blends_halfway_over_one_frame() -> Result<()> {
        let identity = [
            [1., 0., 0., 0.],
            [0., 1., 0., 0.],
            [0., 0., 1., 0.],
            [0., 0., 0., 1.],
        ];
        let mut second = identity;
        second[3][0] = 1.0;
        let snapshot = cloth::Snapshot {
            version: 1,
            source_positions: vec![[0., 0., 0.], [1., 0., 0.]],
            animation_frames: vec![identity, second],
            fixed: vec![false; 2],
            alpha_blends: vec![0.5, 1.0],
            orientation_neighbors: Vec::new(),
            body_colliders: Vec::new(),
            weapon_colliders: Vec::new(),
            spline_chains: Vec::new(),
            constraints: vec![],
        };
        let rig = RigSnapshot {
            bone_palette: vec![0],
            parents: vec![-1],
            inverse_bind_matrices: vec![identity],
            neutral_global_matrices: vec![identity],
            neutral_local_matrices: vec![identity],
        };
        let records = [0_u32, 1].map(|index| {
            let mut record = [0_u8; 40];
            record[28] = 255;
            record[32] = 255;
            record[24..28].copy_from_slice(&(index << 10).to_le_bytes());
            record
        });
        for invalid in [-1e-18, 1.0001, f64::NAN] {
            let mut bad = snapshot.clone();
            bad.alpha_blends[0] = invalid;
            assert!(
                Simulation::new(
                    bad,
                    &rig,
                    &[[0., 0., 0.], [1., 0., 0.]],
                    &records,
                    &[0, 0],
                    &CancellationToken::default()
                )
                .is_err()
            );
        }
        let mut simulation = Simulation::new(
            snapshot,
            &rig,
            &[[0., 0., 0.], [1., 0., 0.]],
            &records,
            &[0, 0],
            &CancellationToken::default(),
        )?;
        let mut motion = identity;
        motion[3][1] = 1.0;
        let settings = substep_settings(cloth::Settings {
            gravity: 0.0,
            damping: 10.0,
            use_vertex_alpha: true,
            ..Default::default()
        })?;
        // Isolate alpha by holding the target and removing inertial velocity.
        for _ in 0..SUBSTEPS {
            simulation
                .core
                .step(STEP, motion, settings)
                .map_err(anyhow::Error::msg)?;
        }
        let guides = simulation.core.guide_positions();
        assert!((guides[0][1] - 0.5).abs() < 1e-12);
        assert!((guides[1][1] - 1.0).abs() < 1e-12);
        Ok(())
    }
}
