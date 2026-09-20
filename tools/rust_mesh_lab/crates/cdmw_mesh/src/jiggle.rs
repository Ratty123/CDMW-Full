//! Tool-side inertial soft deformation. These settings do not describe the game.
use glam::{Quat, Vec3};
use std::collections::{BTreeSet, HashMap};

const STEP: f64 = 1.0 / 120.0;

/// Idealized byte-38 blends from the two shipped stream-out shader branches.
/// The traced skinned-mesh CPU setup always selects LowNibble. FullByte retains
/// the alternate shader branch for research. This vertex preview does not yet
/// apply the decoded bone overrides from `jiggle_bones`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum WeightDecode {
    #[default]
    LowNibble,
    FullByte,
}

impl WeightDecode {
    pub fn decode(self, value: u8) -> f32 {
        match self {
            Self::LowNibble => f32::from(15 - (value & 15)) / 15.0,
            Self::FullByte => f32::from(255 - value) / 255.0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Motion {
    #[default]
    UpDown,
    StartStop,
    Turn,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Settings {
    pub softness: f32,
    pub damping: f32,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            softness: 0.5,
            damping: 0.6,
        }
    }
}

struct Edge {
    a: usize,
    b: usize,
    length: f32,
    lambda: f32,
}

pub struct Simulation {
    rest: Vec<Vec3>,
    positions: Vec<Vec3>,
    previous: Vec<Vec3>,
    targets: Vec<Vec3>,
    velocities: Vec<Vec3>,
    active: Vec<bool>,
    weights: Vec<f32>,
    edges: Vec<Edge>,
    pivot: Vec3,
    scale: f32,
    accumulator: f64,
    pub elapsed: f64,
}

impl Simulation {
    pub fn new(
        rest: &[[f32; 3]],
        indices: &[u32],
        weights: Vec<f32>,
    ) -> Result<Self, &'static str> {
        if rest.is_empty()
            || rest.len() > 100_000
            || indices.len() > 600_000
            || rest.len() != weights.len()
            || weights.iter().any(|v| !v.is_finite() || !(0.0..=1.0).contains(v))
            || !indices.len().is_multiple_of(3)
            || indices.iter().any(|i| *i as usize >= rest.len())
            || rest.iter().flatten().any(|v| !v.is_finite())
        {
            return Err(
                "Jiggle preview requires a finite mesh within 100,000 vertices and 200,000 triangles.",
            );
        }
        let active: Vec<bool> = weights.iter().map(|v| *v > 0.0).collect();
        let rest: Vec<Vec3> = rest.iter().copied().map(Vec3::from).collect();
        let min = rest
            .iter()
            .copied()
            .fold(Vec3::splat(f32::INFINITY), Vec3::min);
        let max = rest
            .iter()
            .copied()
            .fold(Vec3::splat(f32::NEG_INFINITY), Vec3::max);
        let scale = (max - min).max_element();
        if !(1e-6..=1e6).contains(&scale) || !(min + max).is_finite() {
            return Err("Jiggle preview mesh scale is outside the supported range.");
        }
        let mut pairs = BTreeSet::new();
        for face in indices.chunks_exact(3) {
            for (a, b) in [(face[0], face[1]), (face[1], face[2]), (face[2], face[0])] {
                let (a, b) = (a as usize, b as usize);
                if a != b && (active[a] || active[b]) {
                    pairs.insert((a.min(b), a.max(b)));
                }
            }
        }
        // Weld coincident UV/normal seam vertices in the simulation only.
        let mut coincident = HashMap::new();
        for (i, point) in rest.iter().enumerate() {
            let key = point
                .to_array()
                .map(|v| if v == 0.0 { 0 } else { v.to_bits() });
            if let Some(&other) = coincident.get(&key) {
                if active[i] || active[other] {
                    pairs.insert((other, i));
                }
            } else {
                coincident.insert(key, i);
            }
        }
        let edges = pairs
            .into_iter()
            .map(|(a, b)| Edge {
                a,
                b,
                length: rest[a].distance(rest[b]),
                lambda: 0.0,
            })
            .collect();
        Ok(Self {
            pivot: (min + max) * 0.5,
            scale,
            positions: rest.clone(),
            previous: rest.clone(),
            targets: rest.clone(),
            velocities: vec![Vec3::ZERO; rest.len()],
            rest,
            active,
            weights,
            edges,
            accumulator: 0.0,
            elapsed: 0.0,
        })
    }

    pub fn positions(&self) -> impl Iterator<Item = [f32; 3]> + '_ {
        self.positions.iter().enumerate().map(|(i, p)| {
            self.targets[i].lerp(*p, self.weights[i]).to_array()
        })
    }

    pub fn rotation(&self, motion: Motion) -> Quat {
        self.pose(motion).0
    }

    fn pose(&self, motion: Motion) -> (Quat, Vec3) {
        let phase = (self.elapsed % 4.0) as f32;
        match motion {
            Motion::UpDown => {
                let bounce = (self.elapsed % 1.2) as f32 * std::f32::consts::TAU / 1.2;
                (Quat::IDENTITY, Vec3::Y * self.scale * 0.06 * (1.0 - bounce.cos()))
            }
            Motion::StartStop => {
                let fraction = if phase < 0.6 {
                    phase / 0.6
                } else if phase < 2.0 {
                    1.0
                } else if phase < 2.6 {
                    1.0 - (phase - 2.0) / 0.6
                } else {
                    0.0
                };
                let travel = fraction * fraction * (3.0 - 2.0 * fraction);
                (Quat::IDENTITY, Vec3::Z * self.scale * 0.16 * travel)
            }
            Motion::Turn => (
                Quat::from_rotation_y((phase * std::f32::consts::TAU / 4.0).sin() * 0.4),
                Vec3::ZERO,
            ),
        }
    }

    pub fn advance(
        &mut self,
        seconds: f64,
        motion: Motion,
        settings: Settings,
    ) -> Result<(), &'static str> {
        if !seconds.is_finite()
            || seconds < 0.0
            || !settings.softness.is_finite()
            || !(0.0..=1.0).contains(&settings.softness)
            || !settings.damping.is_finite()
            || !(0.0..=1.0).contains(&settings.damping)
        {
            return Err("Invalid jiggle preview settings or frame time.");
        }
        // Bound catch-up after a paused/minimized window; never integrate a huge dt.
        self.accumulator = (self.accumulator + seconds).min(STEP * 8.0);
        while self.accumulator + 1e-12 >= STEP {
            self.elapsed += STEP;
            self.step(motion, settings);
            self.accumulator -= STEP;
        }
        Ok(())
    }

    fn step(&mut self, motion: Motion, settings: Settings) {
        let dt = STEP as f32;
        let (rotation, translation) = self.pose(motion);
        let omega = (5.0 - 3.5 * settings.softness) * std::f32::consts::TAU;
        let damping = 0.15 + settings.damping * 1.35;
        let denominator = 1.0 + 2.0 * damping * omega * dt + omega * omega * dt * dt;
        self.previous.clone_from(&self.positions);
        for i in 0..self.rest.len() {
            let target = self.pivot + translation + rotation * (self.rest[i] - self.pivot);
            self.targets[i] = target;
            if self.active[i] {
                self.velocities[i] = (self.velocities[i]
                    + (target - self.positions[i]) * omega * omega * dt)
                    / denominator;
                self.positions[i] += self.velocities[i] * dt;
            } else {
                self.positions[i] = target;
            }
        }
        // XPBD edge constraints preserve the rest shape and pin region borders.
        let alpha = 1e-7 / (dt * dt);
        for edge in &mut self.edges {
            edge.lambda = 0.0;
        }
        for _ in 0..4 {
            for edge in &mut self.edges {
                let delta = self.positions[edge.b] - self.positions[edge.a];
                let length = delta.length();
                if length < 1e-10 {
                    continue;
                }
                let a = f32::from(u8::from(self.active[edge.a]));
                let b = f32::from(u8::from(self.active[edge.b]));
                let change = (-(length - edge.length) - alpha * edge.lambda) / (a + b + alpha);
                edge.lambda += change;
                let correction = delta / length * change;
                self.positions[edge.a] -= correction * a;
                self.positions[edge.b] += correction * b;
            }
        }
        for i in 0..self.rest.len() {
            if self.active[i] {
                // Conservative displacement envelope, not decoded game collision.
                let offset =
                    (self.positions[i] - self.targets[i]).clamp_length_max(self.scale * 0.04);
                self.positions[i] = self.targets[i] + offset;
                self.velocities[i] = (self.positions[i] - self.previous[i]) / dt;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jiggle_decoded_weights_scale_the_final_blend_without_amplification() {
        assert_eq!(WeightDecode::LowNibble.decode(249), 0.4);
        assert_eq!(WeightDecode::FullByte.decode(249), 6.0 / 255.0);
        assert_eq!(WeightDecode::LowNibble.decode(255), 0.0);
        assert_eq!(WeightDecode::FullByte.decode(255), 0.0);
        let positions = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]];
        let mut full = Simulation::new(&positions, &[0, 1, 2], vec![1.0; 3]).unwrap();
        let mut half = Simulation::new(&positions, &[0, 1, 2], vec![0.5; 3]).unwrap();
        for _ in 0..90 {
            full.advance(STEP, Motion::UpDown, Settings::default()).unwrap();
            half.advance(STEP, Motion::UpDown, Settings::default()).unwrap();
            for (i, (a, b)) in full.positions().zip(half.positions()).enumerate() {
                let expected = full.targets[i] + (Vec3::from(a) - full.targets[i]) * 0.5;
                assert!(Vec3::from(b).distance(expected) < 1e-6);
            }
        }
        for bad in [f32::NAN, -0.01, 1.01] {
            assert!(Simulation::new(&positions, &[0, 1, 2], vec![bad; 3]).is_err());
        }
    }

    fn fixture(active: Vec<bool>) -> Simulation {
        Simulation::new(
            &[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            &[0, 1, 2],
            active.into_iter().map(|v| f32::from(u8::from(v))).collect(),
        )
        .unwrap()
    }

    #[test]
    fn jiggle_up_down_cycles_vertically_with_inertia_and_rigid_comparison() {
        assert_eq!(Motion::default(), Motion::UpDown);
        let mut soft = fixture(vec![true; 3]);
        let mut rigid = fixture(vec![false; 3]);
        let mut height = 0.0;
        let mut went_up = false;
        let mut went_down = false;
        let mut lagged = false;
        for _ in 0..288 {
            soft.advance(STEP, Motion::UpDown, Settings::default()).unwrap();
            rigid.advance(STEP, Motion::UpDown, Settings::default()).unwrap();
            let next_height = rigid.positions[0].y;
            went_up |= next_height > height + 1e-5;
            went_down |= next_height < height - 1e-5;
            height = next_height;
            assert_eq!(rigid.positions, rigid.targets);
            assert_eq!(rigid.rotation(Motion::UpDown), Quat::IDENTITY);
            for i in 0..3 {
                assert_eq!(rigid.positions[i].x, rigid.rest[i].x);
                assert_eq!(rigid.positions[i].z, rigid.rest[i].z);
                assert!(soft.positions[i].is_finite());
                let offset = soft.positions[i].distance(rigid.positions[i]);
                lagged |= offset > 0.0001;
                assert!(offset <= soft.scale * 0.04001);
            }
        }
        assert!(went_up && went_down && lagged);
        assert!(rigid.positions[0].distance(rigid.rest[0]) < 1e-5);
    }

    #[test]
    fn jiggle_inertia_moves_surface_while_disabled_vertices_follow_targets() {
        let mut sim = fixture(vec![false, true, true]);
        for _ in 0..80 {
            sim.advance(STEP, Motion::StartStop, Settings::default())
                .unwrap();
        }
        assert_eq!(sim.positions[0], sim.targets[0]);
        assert!(sim.positions[1].distance(sim.targets[1]) > 0.0001);
        assert!(sim.positions[1].distance(sim.targets[1]) <= sim.scale * 0.04001);
        let before = sim.positions[1].distance(sim.targets[1]);
        for _ in 0..135 {
            sim.advance(STEP, Motion::StartStop, Settings::default())
                .unwrap();
        }
        assert!(sim.positions[1].distance(sim.targets[1]) < before);
        let mut rigid = fixture(vec![false; 3]);
        for _ in 0..100 {
            rigid
                .advance(STEP, Motion::Turn, Settings::default())
                .unwrap();
        }
        assert_eq!(rigid.positions, rigid.targets);
    }

    #[test]
    fn jiggle_fixed_step_is_repeatable_across_frame_rates_and_reset() {
        let mut a = fixture(vec![true; 3]);
        let mut b = fixture(vec![true; 3]);
        for _ in 0..60 {
            a.advance(1.0 / 60.0, Motion::Turn, Settings::default())
                .unwrap();
        }
        for _ in 0..30 {
            b.advance(1.0 / 30.0, Motion::Turn, Settings::default())
                .unwrap();
        }
        assert_eq!(a.positions, b.positions);
        assert!(a.positions.iter().all(|p| p.is_finite()));
        let fresh = fixture(vec![true; 3]);
        assert_eq!(fresh.positions, fresh.rest);
        assert_eq!(fresh.elapsed, 0.0);
        assert!(
            a.advance(f64::NAN, Motion::Turn, Settings::default())
                .is_err()
        );
        a.advance(1000.0, Motion::Turn, Settings::default())
            .unwrap();
        assert!(a.elapsed < 1.1);
    }

    #[test]
    fn jiggle_rejects_invalid_mesh_and_welds_seams() {
        assert!(Simulation::new(&[[0.0; 3]], &[0, 1, 0], vec![1.0]).is_err());
        let mut sim = Simulation::new(
            &[
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 0.0, 0.0],
            ],
            &[0, 1, 2, 0, 3, 2],
            vec![0.0, 1.0, 0.0, 1.0],
        )
        .unwrap();
        for _ in 0..60 {
            sim.advance(STEP, Motion::Turn, Settings::default())
                .unwrap();
        }
        assert!(sim.positions[1].distance(sim.positions[3]) < 1e-5);
    }
}
