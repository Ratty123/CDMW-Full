//! Playback adapter for the shared motion preview controller and bounded loader.
use super::super::*;
use cdmw_archive::CancellationToken;
use cdmw_mesh::{cloth, jiggle, jiggle_rig::RigSnapshot, jiggle_skinning::Matrix};

const STEP: f64 = 1.0 / 60.0;

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
        snapshot: cloth::Snapshot,
        rig: &RigSnapshot,
        rest: &[[f32; 3]],
        records: &[[u8; 40]],
        contributions: &[u8],
        cancellation: &CancellationToken,
    ) -> Result<Self> {
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
        self.accumulator = (self.accumulator + seconds).min(STEP * 8.0);
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
