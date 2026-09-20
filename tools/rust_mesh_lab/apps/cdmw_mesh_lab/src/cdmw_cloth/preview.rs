//! Playback adapter for the shared motion preview controller and bounded loader.
use super::super::*;
use cdmw_archive::CancellationToken;
use cdmw_mesh::{cloth, jiggle, jiggle_rig::RigSnapshot, jiggle_skinning::Matrix};

const FRAME_STEP: f64 = 1.0 / 60.0;
// Small steps keep dense guide meshes from stretching under gravity before
// Jacobi corrections can propagate. This is an explicit preview schedule.
pub(crate) const SUBSTEPS: u32 = 8;
const STEP: f64 = FRAME_STEP / SUBSTEPS as f64;

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
        Ok(Self {
            core,
            pivot: (min + max) * 0.5,
            scale,
            accumulator: 0.0,
            elapsed: 0.0,
            rotation: Quat::IDENTITY,
        })
    }

    pub fn positions(&self) -> &[[f32; 3]] {
        self.core.positions()
    }

    pub fn advance(
        &mut self,
        seconds: f64,
        motion: jiggle::Motion,
        settings: cloth::Settings,
    ) -> Result<()> {
        if !seconds.is_finite() || seconds < 0.0 {
            bail!("Invalid cloth preview frame time.");
        }
        let settings = substep_settings(settings)?;
        self.accumulator = (self.accumulator + seconds).min(FRAME_STEP * 8.0);
        while self.accumulator + 1e-12 >= STEP {
            let elapsed = self.elapsed + STEP;
            let phase = (elapsed % 4.0) as f32;
            let (rotation, translation) = match motion {
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
            let transform: Matrix = glam::Mat4::from_rotation_translation(
                rotation,
                self.pivot + translation - rotation * self.pivot,
            )
            .to_cols_array_2d()
            .map(|row| row.map(f64::from));
            self.core
                .step(STEP, transform, settings)
                .map_err(anyhow::Error::msg)?;
            self.elapsed = elapsed;
            self.rotation = rotation;
            self.accumulator -= STEP;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
