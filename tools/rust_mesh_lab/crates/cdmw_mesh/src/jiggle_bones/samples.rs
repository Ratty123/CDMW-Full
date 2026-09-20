//! Decoded GPU wind/water sample generator (build 1.0.0.2944).
//! Requires explicit sample initialization and global environment inputs.
//! Matches `pac_jiggle_samples.py`, not bit-exact GPU or CPU simulation.

use super::{
    Motion, Result, TAU, angular_motion, finite, float32, floats, linear_motion, random, rotation,
    store_floats, transform, uint,
};

#[derive(Debug)]
pub struct Output {
    pub sample: [u8; 96],
    pub matrix: [[f64; 4]; 4],
    pub matrix_index: u32,
}

/// `global` is the 224-byte JiggleBoneEffectGlobalData at constant-buffer +48.
/// Only cycle 0 advances. Nonzero CPU mode preserves the supplied sample while
/// emitting its matrix; the separate CPU simulator is not run by this function.
pub fn step(previous: &[u8; 96], global: &[u8; 224], index: u32) -> Result<Output> {
    if index >= 512 {
        return Err("Jiggle sample index must be in the shader's 0..511 range.");
    }
    let mut motion = Motion {
        position: floats(previous, 48),
        velocity: floats(previous, 60),
        rotation: floats(previous, 72),
        angular_velocity: floats(previous, 84),
    };
    finite(&motion.position)?;
    finite(&motion.rotation)?;
    let mut sample = *previous;
    if uint(global, 140) == 0 {
        let wind = index < uint(global, 4);
        let [dt] = floats(global, 84);
        let [mut elapsed, mut duration] = floats(previous, 32);
        let settings: [f64; 8] = floats(global, if wind { 160 } else { 192 });
        finite(&[dt, elapsed, duration])?;
        finite(&motion.velocity)?;
        finite(&motion.angular_velocity)?;
        finite(&settings)?;
        if dt < 0.0 || [2, 3, 6, 7].iter().any(|i| settings[*i] < 0.0) {
            return Err("Jiggle sample time and speed/displacement limits must be nonnegative.");
        }
        let velocity_bits = (float32(
            float32(float32(motion.velocity[0] * 999999995904.0)? * motion.velocity[1])?
                * motion.velocity[2],
        )? as f32)
            .to_bits();
        let mut seed = index
            .wrapping_mul(index)
            .wrapping_mul(index & 63)
            .wrapping_mul(uint(global, 136))
            .wrapping_add(velocity_bits);
        elapsed = float32(elapsed + dt)?;
        let mut cycle_linear = floats::<3>(previous, 0);
        let mut cycle_angular = floats::<3>(previous, 16);
        if elapsed >= duration {
            let [cycle] = floats(global, if wind { 76 } else { 104 });
            let [perturb] = floats(global, if wind { 60 } else { 132 });
            finite(&[cycle, perturb])?;
            let unit = float32(f64::from(random(&mut seed)) * 3.051944077014923e-5)?;
            duration =
                float32(cycle * float32(1.0 + float32(unit * perturb)?)?)?.max(0.0333000011742115);
            elapsed = 0.0;
            if !wind {
                let rates: [f64; 4] = floats(global, 112);
                finite(&rates)?;
                finite(&cycle_linear)?;
                let mut angles = [0.0; 4];
                for (angle, rate) in angles.iter_mut().zip(rates) {
                    *angle = (float32(f64::from(random(&mut seed)) * 6.103888154029846e-5)? - 1.0)
                        * rate;
                }
                cycle_linear = transform(cycle_linear, rotation([angles[1], angles[0], 0.0]));
                cycle_angular = [angles[2], angles[3], 0.0];
                store_floats(&mut sample, 0, &cycle_linear)?;
                store_floats(&mut sample, 16, &[angles[2], angles[3], 0.0, 0.0])?;
            }
        }
        let phase = (elapsed / duration * TAU).sin();
        finite(&[phase])?;
        linear_motion(&mut motion, [0.0; 3], &settings, 1.0, dt, &mut seed)?;
        angular_motion(&mut motion, [0.0; 3], &settings, dt, &mut seed)?;
        let (direction, rotational, force, angular_force) = if wind {
            let direction: [f64; 3] = floats(global, 16);
            let rotational: [f64; 3] = floats(global, 32);
            let [acc, damping] = floats(global, 48);
            let [bias, perturb, speed] = floats(global, 64);
            finite(&[acc, damping, bias, perturb, speed])?;
            (
                direction,
                rotational,
                (speed * dt * (bias + perturb * phase)) * (damping * acc),
                (if phase > 0.0 { 1.0 } else { -1.0 }) * dt * damping,
            )
        } else {
            let [speed] = floats(global, 108);
            let [perturb] = floats(global, 128);
            finite(&[speed, perturb])?;
            let force = speed * dt * (1.0 + perturb * phase);
            (cycle_linear, cycle_angular, force, force)
        };
        finite(&direction)?;
        finite(&rotational)?;
        // External forces and a SECOND integration follow the clamped spring
        // stage. Do not silently re-clamp final speed, position or rotation.
        for i in 0..3 {
            motion.velocity[i] += force * direction[i];
            motion.angular_velocity[i] += angular_force * rotational[i];
            motion.position[i] += dt * motion.velocity[i];
            motion.rotation[i] += dt * motion.angular_velocity[i];
        }
        store_floats(&mut sample, 32, &[elapsed, duration])?;
        for (offset, values) in [
            (48, motion.position),
            (60, motion.velocity),
            (72, motion.rotation),
            (84, motion.angular_velocity),
        ] {
            store_floats(&mut sample, offset, &values)?;
        }
    }
    let basis = rotation(motion.rotation);
    let matrix = [
        [basis[0][0], basis[0][1], basis[0][2], 0.0],
        [basis[1][0], basis[1][1], basis[1][2], 0.0],
        [basis[2][0], basis[2][1], basis[2][2], 0.0],
        [
            motion.position[0],
            motion.position[1],
            motion.position[2],
            1.0,
        ],
    ];
    for row in &matrix {
        finite(row)?;
    }
    Ok(Output {
        sample,
        matrix,
        matrix_index: index + 1024,
    })
}

#[cfg(test)]
mod tests;
