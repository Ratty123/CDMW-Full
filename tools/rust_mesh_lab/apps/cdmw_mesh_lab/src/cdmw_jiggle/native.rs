//! Prepared on the existing bounded loader; playback has no file/Python work.
use super::*;
use cdmw_archive::CancellationToken;
use cdmw_mesh::jiggle_bones::samples;
use cdmw_mesh::jiggle_rig::{FrameInput, FrameOutput, Rig, RigSnapshot, VertexBinding};
use cdmw_mesh::jiggle_skinning::Matrix;
use serde::Deserialize;
use std::collections::BTreeMap;

const STEP: f64 = 1.0 / 60.0; // Repeatable preview clock, not a decoded game rate.
const NORMAL_SETTINGS: [f32; 8] = [680.0, 0.82, 3.0, 0.055, 400.0, 0.7, 200.0, 0.7];

#[derive(Clone, Copy, Debug)]
pub(crate) struct Settings {
    pub values: [f32; 8],
    pub wind: Wind,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct Wind {
    pub enabled: bool,
    pub speed: f32,
    pub direction: f32,
    pub cycle: f32,
    pub gusts: f32,
}

impl Default for Wind {
    fn default() -> Self {
        Self {
            enabled: false,
            speed: 1.0,
            direction: 0.0,
            cycle: 2.0,
            gusts: 0.5,
        }
    }
}

impl Wind {
    fn valid(self) -> bool {
        [self.speed, self.direction, self.cycle, self.gusts]
            .iter()
            .all(|v| v.is_finite())
            && (0.0..=20.0).contains(&self.speed)
            && (0.0..=360.0).contains(&self.direction)
            && (0.05..=10.0).contains(&self.cycle)
            && (0.0..=1.0).contains(&self.gusts)
    }

    fn global_data(self, frame: u32, dt: f64) -> [u8; 224] {
        let mut data = [0; 224];
        data[4..8].copy_from_slice(&256_u32.to_le_bytes());
        let angle = self.direction.to_radians();
        put_floats(&mut data, 16, &[angle.cos(), 0.0, angle.sin()]);
        // Explicit repeatable tool inputs, not captured game weather. Gusts
        // vary speed/cycle and apply a small alternating yaw perturbation.
        put_floats(&mut data, 32, &[0.0, self.gusts * self.speed * 0.1, 0.0]);
        put_floats(&mut data, 48, &[1.0, 1.0]);
        put_floats(
            &mut data,
            60,
            &[self.gusts * 0.25, 1.0, self.gusts, self.speed, self.cycle],
        );
        put_floats(&mut data, 84, &[dt as f32]);
        data[136..140].copy_from_slice(&frame.to_le_bytes());
        put_floats(&mut data, 160, &NORMAL_SETTINGS);
        data
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot() -> RigSnapshot {
        let identity =
            std::array::from_fn(|i| std::array::from_fn(|j| if i == j { 1.0 } else { 0.0 }));
        RigSnapshot {
            bone_palette: vec![0],
            parents: vec![-1],
            inverse_bind_matrices: vec![identity],
            neutral_global_matrices: vec![identity],
            neutral_local_matrices: vec![identity],
        }
    }

    fn simulation(enabled: bool, bytes: Vec<u8>) -> Simulation {
        let mut record = [0; 40];
        record[28] = 255;
        record[39] = 63;
        Simulation::new(
            snapshot(),
            &[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            &[record; 3],
            bytes,
            enabled,
            &CancellationToken::default(),
        )
        .unwrap()
    }

    #[test]
    fn decoded_jiggle_motion_uses_packed_contribution_and_changes_only_the_draw_copy() {
        let mut original = simulation(true, vec![240; 3]);
        let mut current = simulation(true, vec![255, 247, 240]);
        let mut disabled = simulation(false, vec![240; 3]);
        let rest = disabled.positions.clone();
        for _ in 0..20 {
            for s in [&mut original, &mut current, &mut disabled] {
                s.advance(STEP, jiggle::Motion::UpDown, Settings::default())
                    .unwrap();
            }
        }
        let offset = disabled.positions[0][1] - rest[0][1];
        assert!(offset > 0.0);
        for (p, source) in disabled.positions.iter().zip(&rest) {
            assert_eq!(p[0], source[0]);
            assert_eq!(p[2], source[2]);
            assert!((p[1] - source[1] - offset).abs() < 1e-6);
        }
        assert_ne!(original.positions, disabled.positions);
        assert_eq!(current.positions[0], disabled.positions[0]);
        assert_eq!(current.positions[2], original.positions[2]);
        let expected = disabled.positions[1][1]
            + (original.positions[1][1] - disabled.positions[1][1]) * (8.0 / 15.0);
        assert!((current.positions[1][1] - expected).abs() < 1e-6);

        let mut changed = simulation(true, vec![240; 3]);
        let mut settings = Settings::default();
        settings.values[0] = 30.0;
        for _ in 0..20 {
            changed
                .advance(STEP, jiggle::Motion::UpDown, settings)
                .unwrap();
        }
        assert_ne!(changed.positions, original.positions);
        for motion in [jiggle::Motion::StartStop, jiggle::Motion::Turn] {
            let mut a = simulation(true, vec![240; 3]);
            let mut b = simulation(true, vec![240; 3]);
            for _ in 0..20 {
                a.advance(STEP, motion, Settings::default()).unwrap();
                b.advance(STEP, motion, Settings::default()).unwrap();
            }
            assert_eq!(a.positions, b.positions);
            assert_ne!(a.positions, rest);
            assert!(a.positions.iter().flatten().all(|v| v.is_finite()));
        }
    }

    #[test]
    fn decoded_jiggle_wind_controls_preserve_disabled_vertices_and_reset_cleanly() {
        let bytes = vec![255, 240, 247];
        let mut calm = simulation(true, bytes.clone());
        let mut along_x = simulation(true, bytes.clone());
        let mut along_z = simulation(true, bytes);
        let mut disabled = simulation(false, vec![240; 3]);
        let mut disabled_calm = simulation(false, vec![240; 3]);
        let mut settings = Settings::default();
        settings.wind.enabled = true;
        settings.wind.speed = 2.0;
        settings.wind.gusts = 0.0;
        for _ in 0..20 {
            calm.advance(STEP, jiggle::Motion::UpDown, Settings::default())
                .unwrap();
            along_x
                .advance(STEP, jiggle::Motion::UpDown, settings)
                .unwrap();
            disabled
                .advance(STEP, jiggle::Motion::UpDown, settings)
                .unwrap();
            disabled_calm
                .advance(STEP, jiggle::Motion::UpDown, Settings::default())
                .unwrap();
            let mut z_settings = settings;
            z_settings.wind.direction = 90.0;
            along_z
                .advance(STEP, jiggle::Motion::UpDown, z_settings)
                .unwrap();
        }
        assert_eq!(along_x.positions[0], calm.positions[0]);
        assert_eq!(along_z.positions[0], calm.positions[0]);
        let full_x = along_x.positions[1][0] - calm.positions[1][0];
        let full_z = along_z.positions[1][2] - calm.positions[1][2];
        assert!(full_x > 1e-5 && full_z > 1e-5);
        assert!((full_x - full_z).abs() < 1e-6);
        assert!(
            (along_x.positions[2][0] - calm.positions[2][0] - full_x * 8.0 / 15.0).abs() < 1e-6
        );
        assert_eq!(disabled.positions, disabled_calm.positions);
        for s in [&mut calm, &mut along_x] {
            s.advance(STEP, jiggle::Motion::UpDown, Settings::default())
                .unwrap();
        }
        assert_eq!(along_x.positions, calm.positions);
        assert!(along_x.wind_states.iter().all(|s| *s == [0; 96]));
    }

    #[test]
    fn decoded_jiggle_wind_zero_speed_is_still_and_invalid_controls_do_not_advance() {
        let mut calm = simulation(true, vec![240; 3]);
        let mut windy = simulation(true, vec![240; 3]);
        let mut settings = Settings::default();
        settings.wind.enabled = true;
        settings.wind.speed = 0.0;
        for _ in 0..20 {
            calm.advance(STEP, jiggle::Motion::Turn, Settings::default())
                .unwrap();
            windy.advance(STEP, jiggle::Motion::Turn, settings).unwrap();
        }
        assert_eq!(windy.positions, calm.positions);
        let positions = windy.positions.clone();
        let elapsed = windy.elapsed;
        settings.wind.cycle = 0.0;
        assert!(windy.advance(STEP, jiggle::Motion::Turn, settings).is_err());
        assert_eq!(windy.positions, positions);
        assert_eq!(windy.elapsed, elapsed);
    }

    #[test]
    fn decoded_jiggle_rejects_cancelled_and_incomplete_rigs() {
        let mut incomplete = snapshot();
        incomplete.neutral_local_matrices.clear();
        assert!(
            Simulation::new(
                incomplete,
                &[],
                &[],
                vec![],
                true,
                &CancellationToken::default()
            )
            .is_err()
        );
        let cancelled = CancellationToken::default();
        cancelled.cancel();
        assert!(
            Simulation::new(snapshot(), &[], &[], vec![], true, &cancelled)
                .unwrap_err()
                .to_string()
                .contains("cancelled")
        );
    }

    #[test]
    fn decoded_jiggle_bounds_draw_geometry_before_reading_the_payload() {
        let root = tempfile::tempdir().unwrap();
        let bridge = cdmw_session::CdmwBridge::for_test(root.path().to_path_buf(), "jiggle", 1, 0);
        let source = bridge
            .jiggle_source(&serde_json::json!({"jiggle": {"decoded": {"file": {
                "path": "jiggle-rig.json", "data_type": "jiggle_rig_json", "count": 1,
                "byte_length": 0, "sha256": "0".repeat(64), "content_type": "application/json"
            }}}}))
            .unwrap();
        let app = crate::headless_tests::triangle_application().unwrap();
        let mut rest = app.mesh.as_ref().unwrap().draw_snapshot();
        rest.indices = vec![0; 600_003];
        let request = Request {
            source,
            rest,
            vertices: vec![(0, 0, 0); 3],
            enabled: true,
            cloth: false,
            geometry_revision: 0,
        };
        assert!(
            prepare(request, &CancellationToken::default())
                .unwrap_err()
                .contains("bounded visible mesh")
        );
    }
}

impl Default for Settings {
    fn default() -> Self {
        // Decoded initialization profile. Live character selection is unknown.
        Self {
            values: NORMAL_SETTINGS,
            wind: Wind::default(),
        }
    }
}

#[derive(Debug)]
pub(crate) struct Request {
    pub source: cdmw_session::JiggleSource,
    pub rest: DrawSnapshot,
    pub vertices: Vec<(u32, u32, u8)>,
    pub enabled: bool,
    pub cloth: bool,
    pub geometry_revision: u64,
}

#[derive(Debug)]
pub(crate) struct Prepared {
    pub rest: DrawSnapshot,
    pub simulation: super::Simulation,
    pub rest_surface_normals: Vec<Vec3>,
    pub moving: usize,
    pub geometry_revision: u64,
}

#[derive(Deserialize)]
struct Payload {
    version: u32,
    rig: RigSnapshot,
    parts: Vec<Part>,
    cloth: Option<cdmw_mesh::cloth::Snapshot>,
}

#[derive(Deserialize)]
struct Part {
    index: u32,
    records: Vec<String>,
}

fn record(text: &str) -> Result<[u8; 40]> {
    if text.len() != 80 || !text.bytes().all(|b| b.is_ascii_hexdigit()) {
        bail!("Invalid retained jiggle vertex record.");
    }
    let mut bytes = [0; 40];
    for (i, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[2 * i..2 * i + 2], 16)?;
    }
    Ok(bytes)
}

pub(crate) fn prepare(
    request: Request,
    cancellation: &CancellationToken,
) -> Result<Prepared, String> {
    let work = || -> Result<Prepared> {
        cancellation.check()?;
        if request.vertices.len() != request.rest.positions.len()
            || request.vertices.is_empty()
            || request.vertices.len() > 100_000
            || request.rest.normals.len() != request.rest.positions.len()
            || request.rest.indices.len() > 600_000
            || !request.rest.indices.len().is_multiple_of(3)
            || request
                .rest
                .indices
                .iter()
                .any(|i| *i as usize >= request.vertices.len())
        {
            bail!("Jiggle snapshot does not match a bounded visible mesh.");
        }
        let bytes = request.source.read()?;
        cancellation.check()?;
        let payload: Payload = serde_json::from_slice(&bytes)?;
        if payload.version != 1 || payload.parts.is_empty() || payload.parts.len() > 4096 {
            bail!("Unsupported decoded jiggle snapshot.");
        }
        let mut parts = BTreeMap::new();
        let mut count = 0usize;
        for part in payload.parts {
            count = count
                .checked_add(part.records.len())
                .ok_or_else(|| anyhow::anyhow!("Too many jiggle records."))?;
            if count > 100_000 || parts.insert(part.index, part.records).is_some() {
                bail!("Duplicate or oversized jiggle snapshot parts.");
            }
        }
        let mut records = Vec::with_capacity(request.vertices.len());
        let mut contributions = Vec::with_capacity(request.vertices.len());
        for (i, &(part, vertex, contribution)) in request.vertices.iter().enumerate() {
            if i.is_multiple_of(256) {
                cancellation.check()?;
            }
            let value = parts
                .get(&part)
                .and_then(|rows| rows.get(vertex as usize))
                .ok_or_else(|| {
                    anyhow::anyhow!(
                        "A visible part has no verified PAC records for decoded motion."
                    )
                })?;
            records.push(record(value)?);
            contributions.push(contribution);
        }
        cancellation.check()?;
        let simulation = if request.cloth {
            if !request.enabled { contributions.fill(63); }
            super::Simulation::Cloth(Box::new(crate::cdmw_cloth::preview::Simulation::new(
                payload.cloth.ok_or_else(|| anyhow::anyhow!("Cloth preview needs a decoded guide mesh."))?,
                &payload.rig, &request.rest.positions, &records, &contributions, cancellation)?))
        } else {
            super::Simulation::Decoded(Box::new(Simulation::new(
                payload.rig, &request.rest.positions, &records, contributions, request.enabled, cancellation)?))
        };
        let mut rest_surface_normals = vec![Vec3::ZERO; request.rest.positions.len()];
        surface_normals(&request.rest, &mut rest_surface_normals);
        for normal in &mut rest_surface_normals {
            *normal = normal.normalize_or_zero();
        }
        cancellation.check()?;
        let moving = if request.enabled {
            request
                .vertices
                .iter()
                .filter(|(_, _, b)| if request.cloth { *b < 63 } else { b & 15 != 15 })
                .count()
        } else {
            0
        };
        Ok(Prepared {
            rest: request.rest,
            simulation,
            rest_surface_normals,
            moving,
            geometry_revision: request.geometry_revision,
        })
    };
    work().map_err(|error| error.to_string())
}

#[derive(Debug)]
pub(crate) struct Simulation {
    rig: Rig,
    binding: VertexBinding,
    roots: Vec<(u32, Matrix)>,
    frame: Option<FrameOutput>,
    contributions: Vec<u8>,
    enabled: bool,
    scales: Vec<[f64; 3]>,
    character: [u8; 272],
    pivot: Vec3,
    scale: f32,
    accumulator: f64,
    pub elapsed: f64,
    frame_index: u32,
    wind_states: Vec<[u8; 96]>,
    wind_matrices: Vec<Matrix>,
    wind_active: bool,
    pub positions: Vec<[f32; 3]>,
    pub rotation: Quat,
}

fn put_floats(bytes: &mut [u8], offset: usize, values: &[f32]) {
    for (i, value) in values.iter().enumerate() {
        bytes[offset + 4 * i..offset + 4 * i + 4].copy_from_slice(&value.to_le_bytes());
    }
}

impl Simulation {
    fn new(
        snapshot: RigSnapshot,
        rest: &[[f32; 3]],
        records: &[[u8; 40]],
        contributions: Vec<u8>,
        enabled: bool,
        cancelled: &CancellationToken,
    ) -> Result<Self> {
        let roots = snapshot
            .parents
            .iter()
            .zip(&snapshot.neutral_local_matrices)
            .enumerate()
            .filter(|(_, (parent, _))| **parent == -1)
            .map(|(i, (_, matrix))| (i as u32, *matrix))
            .collect();
        let rig = Rig::new(snapshot).map_err(anyhow::Error::msg)?;
        let positions = rest.iter().map(|p| p.map(f64::from)).collect::<Vec<_>>();
        let binding = rig
            .bind_vertices_cancellable(&positions, records, 128, &|| cancelled.check().is_err())
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
            bail!("Invalid jiggle preview mesh scale.");
        }
        let mut character = [0; 272];
        for base in [0, 64, 192] {
            for i in 0..4 {
                put_floats(&mut character, base + 20 * i, &[1.0]);
            }
        }
        // Explicit tool-side character bounds. These are not captured runtime values.
        put_floats(&mut character, 128, &min.to_array());
        put_floats(&mut character, 144, &max.to_array());
        let scales = vec![[1.0; 3]; rig.bone_count()];
        let mut result = Self {
            rig,
            binding,
            roots,
            frame: None,
            contributions,
            enabled,
            scales,
            character,
            pivot: (min + max) * 0.5,
            scale,
            accumulator: 0.0,
            elapsed: 0.0,
            frame_index: 0,
            wind_states: vec![[0; 96]; 256],
            wind_matrices: vec![
                std::array::from_fn(|i| std::array::from_fn(|j| if i == j {
                    1.0
                } else {
                    0.0
                }));
                1280
            ],
            wind_active: false,
            positions: rest.to_vec(),
            rotation: Quat::IDENTITY,
        };
        result.step(jiggle::Motion::UpDown, Settings::default(), 0.0)?;
        Ok(result)
    }

    pub fn advance(
        &mut self,
        seconds: f64,
        motion: jiggle::Motion,
        settings: Settings,
    ) -> Result<()> {
        if !seconds.is_finite()
            || seconds < 0.0
            || settings.values.iter().any(|v| !v.is_finite() || *v < 0.0)
            || !settings.wind.valid()
        {
            bail!("Invalid decoded jiggle settings or frame time.");
        }
        self.accumulator = (self.accumulator + seconds).min(STEP * 8.0);
        while self.accumulator + 1e-12 >= STEP {
            self.elapsed += STEP;
            self.frame_index = self.frame_index.wrapping_add(1);
            self.step(motion, settings, STEP)?;
            self.accumulator -= STEP;
        }
        Ok(())
    }

    fn step(&mut self, motion: jiggle::Motion, settings: Settings, dt: f64) -> Result<()> {
        let phase = (self.elapsed % 4.0) as f32;
        let (rotation, translation) = match motion {
            jiggle::Motion::UpDown => {
                let phase = (self.elapsed % 1.2) as f32 * std::f32::consts::TAU / 1.2;
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
        // Animate root local poses; this is a repeatable pose test, not inferred
        // game-world movement or animation sampling. Children follow animation.
        let motion_matrix = glam::Mat4::from_rotation_translation(
            rotation,
            self.pivot + translation - rotation * self.pivot,
        )
        .to_cols_array_2d()
        .map(|row| row.map(f64::from));
        let poses = self
            .roots
            .iter()
            .map(|(index, root)| {
                (
                    *index,
                    std::array::from_fn(|i| {
                        std::array::from_fn(|j| {
                            (0..4).map(|k| root[i][k] * motion_matrix[k][j]).sum()
                        })
                    }),
                )
            })
            .collect();
        let mut shader = [0; 264];
        put_floats(&mut shader, 32, &settings.values);
        let frame = self
            .rig
            .step(
                self.frame.as_ref(),
                FrameInput {
                    shader_data: &shader,
                    character_transform: &self.character,
                    view_position: [0.0; 3],
                    previous_view_position: [0.0; 3],
                    bone_scale: 1.0,
                    character_space_scales: &self.scales,
                    update_frame_index: self.frame_index,
                    delta_time: dt,
                    reset_requested: false,
                    local_pose_overrides: &poses,
                    commands: &BTreeMap::new(),
                },
            )
            .map_err(anyhow::Error::msg)?;
        let wind_active = self.enabled && settings.wind.enabled;
        if wind_active {
            let global = settings.wind.global_data(self.frame_index, dt);
            for (index, state) in self.wind_states.iter_mut().enumerate() {
                let output =
                    samples::step(state, &global, index as u32).map_err(anyhow::Error::msg)?;
                *state = output.sample;
                self.wind_matrices[output.matrix_index as usize] = output.matrix;
            }
        } else if self.wind_active {
            self.wind_states.fill([0; 96]);
        }
        self.wind_active = wind_active;
        let positions = self
            .binding
            .positions(
                &self.rig,
                &frame,
                &self.contributions,
                self.enabled,
                if wind_active { 1.0 } else { 0.0 },
                wind_active.then_some(self.wind_matrices.as_slice()),
            )
            .map_err(anyhow::Error::msg)?;
        let positions: Vec<_> = positions.into_iter().map(|p| p.map(|v| v as f32)).collect();
        if positions.iter().flatten().any(|v| !v.is_finite()) {
            bail!("Decoded jiggle positions exceed the renderer's range.");
        }
        self.positions = positions;
        self.frame = Some(frame);
        self.rotation = rotation;
        Ok(())
    }
}
