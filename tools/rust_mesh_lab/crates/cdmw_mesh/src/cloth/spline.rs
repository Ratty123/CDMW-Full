//! Controlled ordered-chain projection, not the game's recovered spline shader.
//! Stretch uses retained pair constraints. Bend preserves local authored shape;
//! angular spring-back restores the animated directions. Roots remain fixed.
use super::{Constraint, Result, Settings, Snapshot};
use glam::{DQuat, DVec3};

pub(super) fn validate(snapshot: &Snapshot) -> Result<()> {
    if snapshot.spline_chains.is_empty() {
        return Ok(());
    }
    let count = snapshot.fixed.len();
    let mut seen = vec![false; count];
    for chain in &snapshot.spline_chains {
        if chain.len() < 2 || chain.len() > count {
            return Err("Invalid spline guide chain.");
        }
        for &index in chain {
            if index >= count || seen[index] {
                return Err("Spline chains contain repeated or invalid guides.");
            }
            seen[index] = true;
        }
        if !snapshot.fixed[chain[0]] {
            return Err("Spline chains need fixed roots.");
        }
        for pair in chain.windows(2) {
            if !snapshot.constraints.iter().any(|constraint| {
                matches!(constraint,
                Constraint::Pair { indices, rest } if *rest > 0.0
                    && (*indices == [pair[0], pair[1]] || *indices == [pair[1], pair[0]]))
            }) {
                return Err("Spline chains need retained pair constraints along every edge.");
            }
            if DVec3::from(snapshot.source_positions[pair[0]])
                .distance(DVec3::from(snapshot.source_positions[pair[1]]))
                <= 1e-8
            {
                return Err("Spline chains contain degenerate edges.");
            }
        }
    }
    if seen.iter().any(|value| !value) {
        return Err("Spline chains must account for every guide.");
    }
    Ok(())
}

pub(super) fn neighbors(chains: &[Vec<usize>], count: usize) -> Vec<Option<[u16; 2]>> {
    let mut result = vec![None; count];
    for chain in chains {
        for (i, &index) in chain.iter().enumerate() {
            let neighbor = if i == 0 { chain[1] } else { chain[i - 1] };
            result[index] = Some([neighbor as u16, u16::MAX]);
        }
    }
    result
}

pub(super) fn project(
    chains: &[Vec<usize>],
    positions: &[DVec3],
    animation: &[DVec3],
    masses: &[f64],
    settings: Settings,
    dt: f64,
    corrections: &mut [DVec3],
    counts: &mut [u32],
) {
    let restore = angular_response(settings.restore_angle, dt);
    let bend = angular_response(settings.bend, dt);
    for chain in chains {
        for i in 1..chain.len() {
            let (a, b) = (chain[i - 1], chain[i]);
            let edge = positions[b] - positions[a];
            let length = edge.length();
            let reference = animation[b] - animation[a];
            let mass = masses[a] + masses[b];
            if length <= 1e-8 || reference.length_squared() <= 1e-16 || mass == 0.0 {
                continue;
            }
            let reference = reference.normalize();
            let mut correction = DVec3::ZERO;
            let mut active = false;
            if restore > 0.0 {
                correction += (reference * length - edge) * restore;
                active = true;
            }
            if i > 1 && bend > 0.0 {
                let parent = chain[i - 2];
                let old = animation[a] - animation[parent];
                let current = positions[a] - positions[parent];
                if old.length_squared() > 1e-16 && current.length_squared() > 1e-16 {
                    let direction =
                        DQuat::from_rotation_arc(old.normalize(), current.normalize()) * reference;
                    correction += (direction * length - edge) * bend;
                    active = true;
                }
            }
            if active {
                corrections[a] -= correction * (masses[a] / mass);
                corrections[b] += correction * (masses[b] / mass);
                counts[a] += 1;
                counts[b] += 1;
            }
        }
    }
}

fn angular_response(stiffness: f64, dt: f64) -> f64 {
    if stiffness == 0.0 || stiffness == 1.0 {
        return stiffness;
    }
    // Controlled 60 Hz calibration, not a recovered game timestep. Interpret
    // the reference response as compliance, then scale it by dt squared.
    // Repeating the full response at 480 Hz made soft ribbons act like rods.
    let step_ratio = dt * 60.0;
    let scaled_step = step_ratio * step_ratio;
    scaled_step / ((1.0 - stiffness) / stiffness + scaled_step)
}
