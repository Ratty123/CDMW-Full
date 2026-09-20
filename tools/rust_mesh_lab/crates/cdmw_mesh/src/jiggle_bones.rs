//! Decoded per-bone `UpdateJiggleEffect` path from game build 1.0.0.2944.
//!
//! This core requires resolved animation/runtime records. It does not establish
//! dispatch eligibility, select a character profile, or generate wind samples.
//! PAC byte 38 is a later render blend, not one of these spring parameters.
//! Calculations use f64 with f32 storage/seed rounding, matching the Python
//! reference in `cdmw/modding/pac_jiggle_bones.py`, not bit-exact GPU arithmetic.

pub mod samples;

type Vector = [f64; 3];
type Basis = [Vector; 3];
type Result<T> = std::result::Result<T, &'static str>;
const PI: f64 = std::f32::consts::PI as f64;
const TAU: f64 = std::f32::consts::TAU as f64;
const EPSILON: f64 = 9.999999747378752e-5;

/// Fixed-size records prevent partial runtime buffers from reaching the solver.
/// `command_bone` is the current state after commands; it does not replace the
/// previous motion/timer. Only command flags & 3 == 3 select a new instance.
pub struct StepInput<'a> {
    pub previous_bone: Option<&'a [u8; 116]>,
    pub command_bone: &'a [u8; 116],
    pub shader_data: &'a [u8; 264],
    pub animation_matrix: &'a [u8; 64],
    pub character_transform: &'a [u8; 272],
    pub view_position: [f64; 3],
    pub previous_view_position: [f64; 3],
    pub bone_scale: f64,
    pub original_bone_index: u32,
    pub update_frame_index: u32,
    pub delta_time: f64,
    pub reset_requested: bool,
}

#[derive(Debug)]
pub struct StepOutput {
    pub bone: [u8; 116],
    /// Row-major pose; row0.w/row1.w retain the downstream blend metadata.
    pub matrix: [[f64; 4]; 4],
    pub reset: bool,
}

#[derive(Debug, PartialEq, Eq)]
pub struct PreparedCommand {
    pub state_index: u32,
    pub bone: [u8; 116],
}

fn uint(record: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(record[offset..offset + 4].try_into().expect("fixed record"))
}

fn floats<const N: usize>(record: &[u8], offset: usize) -> [f64; N] {
    std::array::from_fn(|i| f64::from(f32::from_bits(uint(record, offset + 4 * i))))
}

fn finite(values: &[f64]) -> Result<()> {
    if values.iter().all(|v| v.is_finite()) {
        Ok(())
    } else {
        Err("Bone jiggle inputs and results must be finite.")
    }
}

fn float32(value: f64) -> Result<f64> {
    let value = value as f32;
    if value.is_finite() {
        Ok(f64::from(value))
    } else {
        Err("Bone jiggle value exceeds finite float32 range.")
    }
}

fn store_floats(record: &mut [u8], offset: usize, values: &[f64]) -> Result<()> {
    for (i, value) in values.iter().enumerate() {
        let value = float32(*value)? as f32;
        record[offset + i * 4..offset + i * 4 + 4].copy_from_slice(&value.to_le_bytes());
    }
    Ok(())
}

fn length(v: Vector) -> f64 {
    v[0].hypot(v[1]).hypot(v[2])
}

fn transform(v: Vector, basis: Basis) -> Vector {
    std::array::from_fn(|j| (0..3).map(|i| v[i] * basis[i][j]).sum())
}

fn random(seed: &mut u32) -> u32 {
    // The GPU feeds float bits back into its seed; this is not the CPU RNG.
    let first = seed.wrapping_mul(214013).wrapping_add(2531011);
    let second = first.wrapping_mul(214013).wrapping_add(2531011);
    let integer = ((second & 0xffff0000) | (first >> 16)) % 32767;
    let sample = (f64::from(integer) * 3.051944077014923e-5) as f32;
    *seed = (second >> 1).wrapping_add(sample.to_bits() >> 1);
    integer
}

fn spring_multiplier(seed: &mut u32) -> f64 {
    let value = (f64::from(random(seed)) * 1.5259720385074615e-5) as f32;
    f64::from(value + 0.5)
}

fn wrap(mut angle: f64) -> Result<f64> {
    // Preserve both +/- PI endpoints and the shader's two reduction stages.
    if (-PI..=PI).contains(&angle) {
        return Ok(angle);
    }
    if angle >= TAU || angle <= -TAU {
        angle -= float32(angle * 0.15915493667125702)?.trunc() * TAU;
    }
    Ok(angle - float32(angle * 0.31830987334251404)?.trunc() * TAU)
}

fn angle_difference(a: f64, b: f64) -> Result<f64> {
    let mut difference = wrap(a)? - wrap(b)?;
    if difference > PI {
        difference -= TAU;
    } else if difference < -PI {
        difference += TAU;
    }
    Ok(difference)
}

fn shader_atan2(y: f64, x: f64) -> f64 {
    if x == 0.0 {
        return if y >= 0.0 { PI / 2.0 } else { -PI / 2.0 };
    }
    let angle = (y / x).atan();
    if x < 0.0 {
        angle + if y >= 0.0 { PI } else { -PI }
    } else {
        angle
    }
}

fn angles(rows: Basis, scales: Vector) -> Vector {
    let x = (-(rows[2][1] / scales[2]).clamp(-1.0, 1.0)).asin();
    if x.cos() > EPSILON {
        [
            x,
            shader_atan2(rows[2][0] / scales[2], rows[2][2] / scales[2]),
            shader_atan2(rows[0][1] / scales[0], rows[1][1] / scales[1]),
        ]
    } else {
        [
            x,
            0.0,
            shader_atan2(-rows[1][0] / scales[1], rows[0][0] / scales[0]),
        ]
    }
}

fn rotation([x, y, z]: Vector) -> Basis {
    let (sx, sy, sz) = (x.sin(), y.sin(), z.sin());
    let (cx, cy, cz) = (x.cos(), y.cos(), z.cos());
    [
        [cz * cy + sz * sx * sy, sz * cx, sz * sx * cy - cz * sy],
        [cz * sx * sy - sz * cy, cz * cx, cz * sx * cy + sz * sy],
        [cx * sy, -sx, cx * cy],
    ]
}

fn limit_length(v: Vector, limit: f64) -> Result<Vector> {
    let magnitude = length(v);
    finite(&[magnitude])?;
    Ok(if magnitude > limit {
        v.map(|x| x * limit / magnitude)
    } else {
        v
    })
}

fn unit(v: Vector) -> Result<Vector> {
    let magnitude = length(v);
    finite(&[magnitude])?;
    if magnitude == 0.0 {
        return Err("Bone jiggle axis normalization is undefined for a zero vector.");
    }
    Ok(v.map(|x| x / magnitude))
}

#[derive(Clone, Copy)]
struct Motion {
    position: Vector,
    velocity: Vector,
    rotation: Vector,
    angular_velocity: Vector,
}

fn linear_motion(
    m: &mut Motion,
    target: Vector,
    settings: &[f64; 8],
    size: f64,
    dt: f64,
    seed: &mut u32,
) -> Result<()> {
    let [acc, damping, speed, difference, ..] = *settings;
    let acceleration = acc * dt * spring_multiplier(seed);
    m.velocity = limit_length(
        std::array::from_fn(|i| {
            (m.velocity[i] + acceleration * (target[i] - m.position[i])) * damping
        }),
        speed * size,
    )?;
    let predicted = std::array::from_fn(|i| m.position[i] + m.velocity[i] * dt);
    let offset = std::array::from_fn(|i| predicted[i] - target[i]);
    m.position = if length(offset) > difference * size {
        let limited = limit_length(offset, difference * size)?;
        std::array::from_fn(|i| target[i] + limited[i])
    } else {
        predicted
    };
    // A position clamp does not reconstruct velocity.
    Ok(())
}

fn angular_motion(
    m: &mut Motion,
    target: Vector,
    settings: &[f64; 8],
    dt: f64,
    seed: &mut u32,
) -> Result<()> {
    let [_, _, _, _, acc, damping, speed, difference] = *settings;
    let acceleration = acc * dt * spring_multiplier(seed);
    for (i, target) in target.into_iter().enumerate() {
        let velocity = (m.angular_velocity[i]
            + acceleration * angle_difference(target, m.rotation[i])?)
            * damping;
        m.angular_velocity[i] = velocity.clamp(-speed, speed);
        let predicted = m.rotation[i] + m.angular_velocity[i] * dt;
        m.rotation[i] =
            target + angle_difference(predicted, target)?.clamp(-difference, difference);
    }
    Ok(())
}

fn perturb_angles(mut value: Vector, size: f64, seed: &mut u32) -> Result<Vector> {
    let signs: Vector = std::array::from_fn(|_| {
        if ((f64::from(random(seed)) * 3.051944077014923e-5) as f32) < 0.5 {
            -1.0
        } else {
            1.0
        }
    });
    let magnitudes: Vector = std::array::from_fn(|_| f64::from(random(seed)));
    let amplitude = 9.58796499617165e-6 - (size - 1.0) * 1.725833726595738e-6;
    for i in 0..3 {
        value[i] = wrap(value[i] + signs[i] * amplitude * magnitudes[i])?;
    }
    Ok(value)
}

struct Instance {
    axis: Vector,
    angle: f64,
    elapsed: f64,
    flags: u32,
    weight: f64,
    passthrough: bool,
}

fn axis_instance(
    m: &mut Motion,
    effect: &mut Instance,
    target: Vector,
    settings: &[f64; 8],
    dt: f64,
    seed: &mut u32,
    restore_damping: bool,
) -> Result<()> {
    let [_, _, _, _, acc, damping, speed, difference] = *settings;
    let multiplier = spring_multiplier(seed);
    let mut velocity = (m.angular_velocity[0]
        + angle_difference(0.0, effect.angle)? * dt * acc * multiplier)
        * damping;
    velocity = velocity.clamp(-speed, speed);
    effect.angle =
        angle_difference(effect.angle + velocity * dt, 0.0)?.clamp(-difference, difference);
    let direction = std::array::from_fn(|_| 1.0 - f64::from(random(seed)) * 6.103888154029846e-5);
    let perturbation = unit(direction)?;
    let perturbed: Vector =
        std::array::from_fn(|i| effect.axis[i] + 0.10000000149011612 * perturbation[i]);
    // The interpolation toward X is deliberately not saturated.
    effect.axis = unit(std::array::from_fn(|i| {
        perturbed[i] + ([1.0, 0.0, 0.0][i] - perturbed[i]) * (3.0 * dt)
    }))?;
    let axis = if length(effect.axis) > 9.999999747378752e-6 {
        unit(effect.axis)?
    } else {
        effect.axis
    };
    let [x, y, z] = axis.map(|a| a * (effect.angle * 0.5).sin());
    let w = (effect.angle * 0.5).cos();
    let correction = [
        [
            1.0 - 2.0 * (y * y + z * z),
            2.0 * (x * y + w * z),
            2.0 * (x * z - w * y),
        ],
        [
            2.0 * (x * y - w * z),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z + w * x),
        ],
        [
            2.0 * (x * z + w * y),
            2.0 * (y * z - w * x),
            1.0 - 2.0 * (x * x + y * y),
        ],
    ];
    let target_basis = rotation(target);
    m.rotation = angles(correction.map(|row| transform(row, target_basis)), [1.0; 3]);
    if restore_damping {
        if damping == 0.0 {
            return Err("Bone jiggle pre-fade angular damping division is undefined at zero.");
        }
        velocity /= damping;
    }
    m.angular_velocity[0] = velocity;
    Ok(())
}

fn step_instance(
    previous: &[u8; 116],
    selected: &[u8; 116],
    m: &mut Motion,
    target_position: Vector,
    target_rotation: Vector,
    settings: &[f64; 8],
    size: f64,
    dt: f64,
    seed: &mut u32,
) -> Result<Instance> {
    let impulse: Vector = floats(selected, 48);
    let angular_impulse: Vector = floats(selected, 60);
    let [weight, duration, fade_range] = floats(selected, 72);
    let mode = uint(selected, 84);
    let [angle, elapsed] = floats(previous, 100);
    let mut effect = Instance {
        axis: floats(previous, 88),
        angle,
        elapsed,
        flags: uint(selected, 108),
        weight,
        passthrough: false,
    };
    finite(&impulse)?;
    finite(&angular_impulse)?;
    finite(&effect.axis)?;
    finite(&[weight, duration, fade_range, angle, elapsed])?;
    if effect.flags & 2 != 0 {
        effect.elapsed = 0.0;
        m.velocity = if mode & 4 != 0 {
            std::array::from_fn(|i| m.velocity[i] + impulse[i])
        } else {
            [0.0; 3]
        };
        if mode & 8 == 0 {
            effect.angle = 0.0;
            m.angular_velocity = [0.0; 3];
        } else if mode & 2 != 0 {
            let speed = length(std::array::from_fn(|i| {
                m.angular_velocity[i] + angular_impulse[i]
            }));
            m.angular_velocity = [speed; 3];
            effect.axis = [1.0, 0.0, 0.0];
            effect.angle = 0.0;
        } else {
            if length(angular_impulse) > 0.0 {
                m.rotation = perturb_angles(m.rotation, size, seed)?;
            }
            m.angular_velocity =
                std::array::from_fn(|i| m.angular_velocity[i] + angular_impulse[i]);
        }
    }
    effect.elapsed += dt;
    let fade = if fade_range > 0.0 {
        ((fade_range - duration + effect.elapsed) / fade_range).clamp(0.0, 1.0)
    } else {
        0.0
    };
    let before_fade = fade < EPSILON;
    effect.weight = weight - fade * weight;
    effect.passthrough = effect.weight < EPSILON;
    if mode & 4 != 0 {
        linear_motion(m, target_position, settings, size, dt, seed)?;
        if before_fade && !effect.passthrough {
            if settings[1] == 0.0 {
                return Err("Bone jiggle pre-fade linear damping division is undefined at zero.");
            }
            m.velocity = m.velocity.map(|v| v / settings[1]);
        }
    } else {
        m.position = target_position;
    }
    if mode & 8 != 0 {
        if mode & 2 != 0 {
            let restore_damping = before_fade && !effect.passthrough;
            axis_instance(
                m,
                &mut effect,
                target_rotation,
                settings,
                dt,
                seed,
                restore_damping,
            )?;
        } else {
            let spring_target = if before_fade {
                perturb_angles(target_rotation, size, seed)?
            } else {
                target_rotation
            };
            angular_motion(m, spring_target, settings, dt, seed)?;
        }
    } else {
        m.rotation = target_rotation;
    }
    if effect.passthrough {
        m.position = target_position;
        m.rotation = target_rotation;
        m.velocity = [0.0; 3];
        m.angular_velocity = [0.0; 3];
    }
    effect.flags &= if duration <= effect.elapsed { !3 } else { !2 };
    Ok(effect)
}

/// Resolve a command after the caller has selected its skeleton/object resource.
/// Low-byte LOD > 1 or absent jiggle data skips it. LOD0's animation offset is
/// used even for LOD1, with u32 address wrapping. Concurrent command ordering
/// and packed resource lookup are not inferred by this helper.
pub fn prepare_command(
    command: &[u8; 48],
    skeleton: &[u8; 124],
    object: &[u8; 128],
    shader: Option<&[u8; 264]>,
) -> Result<Option<PreparedCommand>> {
    if uint(object, 0) & 0xfe != 0 || uint(object, 84) == u32::MAX {
        return Ok(None);
    }
    let shader = shader.ok_or("Eligible bone jiggle commands require resolved shader data.")?;
    let state_index = uint(shader, 12)
        .wrapping_add(uint(command, 44))
        .wrapping_add(uint(skeleton, 32));
    let mut bone = [0; 116];
    bone[48..88].copy_from_slice(&command[..40]);
    bone[108..112].copy_from_slice(&3_u32.to_le_bytes());
    Ok(Some(PreparedCommand { state_index, bone }))
}

/// Output metadata: nonzero low-two-bit mode sets the marker. Mode 2 applies
/// the LAST matching u16 bone-mask entry. Weights are deliberately not clamped.
pub fn blend_override(
    shader: &[u8; 264],
    original_bone_index: u32,
    instance_weight: f64,
) -> Result<(f64, f64)> {
    finite(&[instance_weight])?;
    let mode = uint(shader, 64) & 3;
    let mut weight = instance_weight;
    if mode == 2 {
        let count = uint(shader, 68) as usize;
        if count > 32 {
            return Err("Bone jiggle mask count exceeds its 32-entry runtime record.");
        }
        for i in 0..count {
            let offset = 72 + 2 * i;
            let bone = u16::from_le_bytes([shader[offset], shader[offset + 1]]);
            if u32::from(bone) == original_bone_index {
                [weight] = floats(shader, 136 + 4 * i);
            }
        }
        finite(&[weight])?;
    }
    Ok((f64::from(u8::from(mode != 0)), weight))
}

/// Advance one resolved bone. Damping is per update and dt is rounded to f32;
/// there is no tool-side fixed timestep. A reset does not cancel an instance.
/// Consumed invalid numbers, zero bases/axes and zero damping divisions fail.
pub fn step(input: StepInput<'_>) -> Result<StepOutput> {
    finite(&[input.bone_scale, input.delta_time])?;
    if input.delta_time < 0.0 {
        return Err("Bone jiggle delta time must be nonnegative.");
    }
    let dt = float32(input.delta_time)?;
    finite(&input.view_position)?;
    finite(&input.previous_view_position)?;
    let previous = input.previous_bone.unwrap_or(&[0; 116]);
    let previous_flags = uint(previous, 108);
    let command_flags = uint(input.command_bone, 108);
    let selected = if command_flags & 3 == 3 {
        input.command_bone
    } else {
        previous
    };
    let mut flags = if command_flags & 3 == 3 {
        command_flags
    } else {
        previous_flags
    };
    let active = flags & 1 != 0;
    let rows: [[f64; 4]; 4] = std::array::from_fn(|i| floats(input.animation_matrix, 16 * i));
    let world: Basis = std::array::from_fn(|i| floats(input.character_transform, 16 * i));
    let inverse: Basis = std::array::from_fn(|i| floats(input.character_transform, 192 + 16 * i));
    let origin: Vector = floats(input.character_transform, 48);
    let old_origin: Vector = floats(input.character_transform, 112);
    let platform: Vector = floats(input.shader_data, 0);
    for row in &rows {
        finite(row)?;
    }
    for row in world
        .iter()
        .chain(&inverse)
        .chain([&origin, &old_origin, &platform])
    {
        finite(row)?;
    }
    let origin_delta = std::array::from_fn(|i| {
        (input.view_position[i] + origin[i]) - (input.previous_view_position[i] + old_origin[i])
    });
    let inverse_dt = if dt < 9.999999747378752e-6 {
        0.0
    } else {
        1.0 / dt
    };
    let reset = input.previous_bone.is_none()
        || input.reset_requested
        || uint(previous, 112).wrapping_add(1) != input.update_frame_index
        || length(origin_delta) * inverse_dt > 70.0;
    let movement: Vector = if input.previous_bone.is_none() {
        [0.0; 3]
    } else {
        std::array::from_fn(|i| {
            (input.view_position[i] + origin[i] - platform[i])
                - (input.previous_view_position[i] + old_origin[i])
        })
    };
    let animated = rows.map(|row| transform([row[0], row[1], row[2]], world));
    let basis = [animated[0], animated[1], animated[2]];
    let scales = basis.map(length);
    for row in &animated {
        finite(row)?;
    }
    finite(&scales)?;
    if scales.contains(&0.0) {
        return Err("Bone jiggle cannot decompose a zero-length animation basis.");
    }
    let target_position = animated[3];
    let target_rotation = angles(basis, scales);
    let mut old_motion = [[0.0; 3]; 4];
    let mut settings = [0.0; 8];
    let mut size = 1.0;
    let mut seed = input
        .original_bone_index
        .wrapping_add(input.update_frame_index);
    if active || !reset {
        old_motion = std::array::from_fn(|i| floats(previous, 12 * i));
        for vector in old_motion {
            finite(&vector)?;
            let product = float32(float32(vector[1] * vector[0])? * vector[2])? as f32;
            seed = seed.wrapping_add(product.to_bits());
        }
        settings = floats(input.shader_data, 32);
        finite(&settings)?;
        if [2, 3, 6, 7].iter().any(|i| settings[*i] < 0.0) {
            return Err("Bone jiggle speed and displacement limits must be nonnegative.");
        }
        let size_a: Vector = floats(input.character_transform, 128);
        let size_b: Vector = floats(input.character_transform, 144);
        finite(&size_a)?;
        finite(&size_b)?;
        size = (input.bone_scale
            * 0.5555555820465088
            * length(std::array::from_fn(|i| size_b[i] - size_a[i])))
        .clamp(1.0, 5.0);
    }
    let mut motion = if reset {
        Motion {
            position: std::array::from_fn(|i| target_position[i] + movement[i]),
            velocity: [0.0; 3],
            rotation: target_rotation,
            angular_velocity: [0.0; 3],
        }
    } else {
        Motion {
            position: std::array::from_fn(|i| old_motion[0][i] + movement[i]),
            velocity: old_motion[1],
            rotation: old_motion[2],
            angular_velocity: old_motion[3],
        }
    };
    let effect = if active {
        Some(step_instance(
            previous,
            selected,
            &mut motion,
            target_position,
            target_rotation,
            &settings,
            size,
            dt,
            &mut seed,
        )?)
    } else {
        if !reset {
            linear_motion(&mut motion, target_position, &settings, size, dt, &mut seed)?;
            angular_motion(&mut motion, target_rotation, &settings, dt, &mut seed)?;
        }
        None
    };
    let passthrough = effect.as_ref().map_or(reset, |effect| effect.passthrough);
    let mut matrix = rows;
    if !passthrough {
        let rotated = rotation(motion.rotation);
        for i in 0..3 {
            let vector = transform(rotated[i].map(|v| v * scales[i]), inverse);
            matrix[i] = [vector[0], vector[1], vector[2], 0.0];
        }
        let vector = transform(motion.position, inverse);
        matrix[3] = [vector[0], vector[1], vector[2], 1.0];
    }
    let (marker, weight) = blend_override(
        input.shader_data,
        input.original_bone_index,
        effect.as_ref().map_or(0.0, |effect| effect.weight),
    )?;
    matrix[0][3] = marker;
    matrix[1][3] = weight;
    for row in &matrix {
        finite(row)?;
    }
    let mut bone = *previous;
    if let Some(effect) = effect {
        bone[48..88].copy_from_slice(&selected[48..88]);
        store_floats(
            &mut bone,
            88,
            &[
                effect.axis[0],
                effect.axis[1],
                effect.axis[2],
                effect.angle,
                effect.elapsed,
            ],
        )?;
        flags = effect.flags;
    }
    for (i, vector) in [
        motion.position,
        motion.velocity,
        motion.rotation,
        motion.angular_velocity,
    ]
    .iter()
    .enumerate()
    {
        store_floats(&mut bone, 12 * i, vector)?;
    }
    bone[108..112].copy_from_slice(&flags.to_le_bytes());
    bone[112..116].copy_from_slice(&input.update_frame_index.to_le_bytes());
    Ok(StepOutput {
        bone,
        matrix,
        reset,
    })
}

#[cfg(test)]
mod tests;
