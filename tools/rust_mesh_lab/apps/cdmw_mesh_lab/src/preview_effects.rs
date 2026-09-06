//! Deterministic, bounded simulation of decoded preview effects.
use cdmw_render_wgpu::{EffectBillboardInstance, EffectBlendMode, EffectLineVertex};
use glam::{EulerRot, Mat4, Quat, Vec3};
use serde_json::Value;

fn vec3_value(value: Option<&Value>, fallback: Vec3) -> Vec3 {
    let Some(values) = value.and_then(Value::as_array) else {
        return fallback;
    };
    if values.len() < 3 {
        return fallback;
    }
    let result = Vec3::new(
        values[0].as_f64().unwrap_or(f64::from(fallback.x)) as f32,
        values[1].as_f64().unwrap_or(f64::from(fallback.y)) as f32,
        values[2].as_f64().unwrap_or(f64::from(fallback.z)) as f32,
    );
    if result.is_finite() { result } else { fallback }
}

fn value_pair(value: Option<&Value>, fallback: (f32, f32)) -> (f32, f32) {
    let Some(values) = value.and_then(Value::as_array) else {
        return fallback;
    };
    let first = values
        .first()
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(fallback.0);
    let second = values
        .get(1)
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(fallback.1);
    (first.min(second), first.max(second))
}

fn seed_unit(seed: f32) -> f32 {
    (seed.sin() * 43_758.547).fract().abs()
}

fn seed_signed(seed: f32) -> f32 {
    seed_unit(seed) * 2.0 - 1.0
}

fn curve_sample(value: Option<&Value>, progress: f32, fallback: f32) -> f32 {
    let Some(samples) = value
        .and_then(Value::as_array)
        .filter(|samples| !samples.is_empty())
    else {
        return fallback;
    };
    let scaled = progress.clamp(0.0, 1.0) * (samples.len().saturating_sub(1)) as f32;
    let lower = scaled.floor() as usize;
    let upper = (lower + 1).min(samples.len() - 1);
    let read = |index: usize| {
        samples[index]
            .as_f64()
            .map(|value| value as f32)
            .filter(|value| value.is_finite())
            .unwrap_or(fallback)
    };
    read(lower) + (read(upper) - read(lower)) * scaled.fract()
}

fn color_curve_sample(value: Option<&Value>, progress: f32) -> Vec3 {
    let Some(samples) = value
        .and_then(Value::as_array)
        .filter(|samples| !samples.is_empty())
    else {
        return Vec3::ONE;
    };
    let scaled = progress.clamp(0.0, 1.0) * (samples.len().saturating_sub(1)) as f32;
    let lower = scaled.floor() as usize;
    let upper = (lower + 1).min(samples.len() - 1);
    vec3_value(samples.get(lower), Vec3::ONE)
        .lerp(vec3_value(samples.get(upper), Vec3::ONE), scaled.fract())
        .max(Vec3::ZERO)
}

fn effect_preview_colour(
    emitter: &Value,
    progress: f32,
    alpha: f32,
    brightness: f32,
    blend: &str,
) -> [f32; 4] {
    let life_colour = color_curve_sample(emitter.get("color_over_life"), progress);
    let emissive = vec3_value(emitter.get("emissive_color"), Vec3::ONE).max(Vec3::ZERO);
    let mut colour = life_colour * emissive * brightness.max(0.15).sqrt();
    let peak = colour.max_element();
    if peak > 1.0 {
        colour /= peak;
    } else if peak < 0.08 {
        // Black smoke and incomplete material records still need a visible guide
        // against the dark Preview background.
        colour = Vec3::splat(0.42);
    }
    let preview_alpha = if blend.eq_ignore_ascii_case("additive") {
        alpha.max(0.72)
    } else {
        alpha.max(0.38)
    };
    [
        colour.x.clamp(0.04, 1.0),
        colour.y.clamp(0.04, 1.0),
        colour.z.clamp(0.04, 1.0),
        preview_alpha.clamp(0.0, 1.0),
    ]
}

fn effect_billboard_colour(
    emitter: &Value,
    progress: f32,
    alpha: f32,
    brightness: f32,
) -> [f32; 4] {
    let life_colour = if emitter.get("color_over_life").is_some() {
        color_curve_sample(emitter.get("color_over_life"), progress)
    } else {
        vec3_value(emitter.get("emissive_color"), Vec3::ONE)
    };
    let colour = (life_colour * brightness.max(0.0)).clamp(Vec3::ZERO, Vec3::splat(64.0));
    [colour.x, colour.y, colour.z, alpha.clamp(0.0, 1.0)]
}

pub(crate) fn push_effect_line(
    lines: &mut Vec<EffectLineVertex>,
    start: Vec3,
    end: Vec3,
    colour: [f32; 4],
) {
    lines.extend_from_slice(&[
        EffectLineVertex {
            position: start.to_array(),
            colour,
        },
        EffectLineVertex {
            position: end.to_array(),
            colour,
        },
    ]);
}

fn effect_spawn_position(emitter: &Value, seed: f32) -> Vec3 {
    if emitter.get("spawn").and_then(Value::as_str) == Some("points")
        && let Some(points) = emitter.get("points").and_then(Value::as_array)
        && !points.is_empty()
    {
        let index = (seed_unit(seed) * points.len() as f32).floor() as usize % points.len();
        return vec3_value(points.get(index), Vec3::ZERO);
    }
    let spread = vec3_value(emitter.get("spread"), Vec3::ZERO).abs();
    Vec3::new(
        seed_signed(seed + 1.37) * spread.x,
        seed_signed(seed + 4.11) * spread.y,
        seed_signed(seed + 7.93) * spread.z,
    )
}

fn effect_force(emitter: &Value, seed: f32) -> Vec3 {
    let Some(values) = emitter.get("force").and_then(Value::as_array) else {
        return Vec3::ZERO;
    };
    let low = vec3_value(values.first(), Vec3::ZERO);
    let high = vec3_value(values.get(1), low);
    Vec3::new(
        low.x + (high.x - low.x) * seed_unit(seed + 2.03),
        low.y + (high.y - low.y) * seed_unit(seed + 5.17),
        low.z + (high.z - low.z) * seed_unit(seed + 8.29),
    )
}

pub(crate) fn particle_kinematics(
    origin: Vec3,
    initial_velocity: Vec3,
    acceleration: Vec3,
    damping: f32,
    age: f32,
) -> (Vec3, Vec3) {
    if damping > 1.0e-5 {
        let terminal_velocity = acceleration / damping;
        let attenuation = (-damping * age).exp();
        let transient = initial_velocity - terminal_velocity;
        let velocity = terminal_velocity + transient * attenuation;
        let position =
            origin + terminal_velocity * age + transient * ((1.0 - attenuation) / damping);
        (position, velocity)
    } else {
        let velocity = initial_velocity + acceleration * age;
        let position = origin + initial_velocity * age + acceleration * (0.5 * age * age);
        (position, velocity)
    }
}

fn effect_scale(emitter: &Value, seed: f32) -> f32 {
    let Some(values) = emitter.get("scale").and_then(Value::as_array) else {
        return 0.04;
    };
    let low = vec3_value(values.first(), Vec3::splat(0.04)).abs();
    let high = vec3_value(values.get(1), low).abs();
    let selected = low.lerp(high, seed_unit(seed + 0.91));
    selected.max_element().max(0.002)
}

fn effect_sequence_uv(emitter: &Value, progress: f32) -> [f32; 4] {
    let values = emitter.get("sequence").and_then(Value::as_array);
    let columns = values
        .and_then(|items| items.first())
        .and_then(Value::as_u64)
        .unwrap_or(1)
        .clamp(1, 64) as u32;
    let rows = values
        .and_then(|items| items.get(1))
        .and_then(Value::as_u64)
        .unwrap_or(1)
        .clamp(1, 64) as u32;
    let cell_count = columns.saturating_mul(rows).max(1);
    let frame =
        ((progress.clamp(0.0, 0.999_999) * cell_count as f32).floor() as u32).min(cell_count - 1);
    let column = frame % columns;
    let row = frame / columns;
    [
        column as f32 / columns as f32,
        row as f32 / rows as f32,
        1.0 / columns as f32,
        1.0 / rows as f32,
    ]
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn effect_emitter_billboards(
    emitter: &Value,
    emitter_index: usize,
    time: f32,
    minimum_radius: f32,
    texture_index: usize,
    model_matrix: Mat4,
    camera_right: Vec3,
    camera_up: Vec3,
    camera_forward: Vec3,
) -> Vec<EffectBillboardInstance> {
    effect_emitter_billboards_with_limit(
        emitter,
        emitter_index,
        time,
        minimum_radius,
        texture_index,
        model_matrix,
        camera_right,
        camera_up,
        camera_forward,
        256,
    )
}

pub(crate) fn effect_emitter_billboards_with_limit(
    emitter: &Value,
    emitter_index: usize,
    time: f32,
    minimum_radius: f32,
    texture_index: usize,
    model_matrix: Mat4,
    camera_right: Vec3,
    camera_up: Vec3,
    camera_forward: Vec3,
    particle_limit: usize,
) -> Vec<EffectBillboardInstance> {
    let max_particles_per_emitter = particle_limit.clamp(64, 2048);
    let max_instances_per_emitter = max_particles_per_emitter * 8;
    let simulation_speed = emitter
        .get("simulation_speed")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .clamp(0.0, 20.0);
    let (delay_low, delay_high) = value_pair(emitter.get("start_delay"), (0.0, 0.0));
    let delay = delay_low + (delay_high - delay_low) * seed_unit(emitter_index as f32 + 17.3);
    let simulation_time = time.max(0.0) * simulation_speed - delay.max(0.0);
    if simulation_time < 0.0 || emitter.get("burst").and_then(Value::as_u64) == Some(0) {
        return Vec::new();
    }
    let burst = emitter
        .get("burst")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or(1)
        .clamp(1, 64);
    let maximum = emitter
        .get("max_particles")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or(burst)
        .clamp(1, max_particles_per_emitter);
    let bursts_per_second = emitter
        .get("bursts_per_second")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .clamp(0.0, 120.0);
    let interval = if bursts_per_second > 0.0 {
        bursts_per_second.recip()
    } else {
        f32::MAX
    };
    let (life_low, life_high) = value_pair(emitter.get("life"), (1.0, 1.0));
    let longest_life = life_high.clamp(0.01, 120.0);
    let looping = emitter.get("loop").and_then(Value::as_bool).unwrap_or(true);
    let spawn_time = emitter
        .get("spawn_time")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .max(0.0);
    let repeats = emitter
        .get("loop_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        .clamp(0, 1000);
    let spawn_time = spawn_time * (repeats + 1) as f32;
    let last_birth = if looping {
        simulation_time
    } else {
        simulation_time.min(spawn_time)
    };
    let newest_burst = (last_birth / interval).floor() as i64;
    let burst_history =
        ((longest_life / interval).ceil() as usize + 1).min(max_particles_per_emitter);
    let kind = emitter
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("billboard");
    let mass = emitter
        .get("mass")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .abs()
        .max(0.01);
    let damping = emitter
        .get("damping")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .clamp(0.0, 100.0);
    let speed_limit = emitter
        .get("speed_limit")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .max(0.0);
    let (rotation_low, rotation_high) = value_pair(emitter.get("rotation"), (0.0, 0.0));
    let velocity_stretch = emitter
        .get("velocity_stretch")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .clamp(0.0, 20.0);
    let brightness = emitter
        .get("brightness")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .max(0.0);
    let blend_name = emitter
        .get("blend")
        .and_then(Value::as_str)
        .unwrap_or("alpha");
    let blend = if blend_name.eq_ignore_ascii_case("additive") {
        EffectBlendMode::Additive
    } else {
        EffectBlendMode::Alpha
    };
    let scene_scale = (model_matrix.transform_vector3(Vec3::X).length()
        + model_matrix.transform_vector3(Vec3::Y).length()
        + model_matrix.transform_vector3(Vec3::Z).length())
        / 3.0;
    let scene_scale = scene_scale.max(1.0e-6);
    let mut instances = Vec::new();
    let mut emitted = 0usize;
    let candidates = burst
        .saturating_mul(burst_history.min(newest_burst.saturating_add(1).max(0) as usize))
        .max(1);
    let keep_fraction = (maximum as f32 / candidates as f32).min(1.0);
    'bursts: for history in (0..burst_history).rev() {
        let burst_index = newest_burst - history as i64;
        if burst_index < 0 {
            continue;
        }
        let birth = burst_index as f32 * interval;
        if !looping
            && ((spawn_time <= 0.0 && burst_index > 0) || (spawn_time > 0.0 && birth > spawn_time))
        {
            continue;
        }
        let age = simulation_time - birth;
        if age < 0.0 || age > longest_life {
            continue;
        }
        let minimum_burst = emitter
            .get("burst_min")
            .and_then(Value::as_u64)
            .unwrap_or(burst as u64)
            .min(burst as u64) as usize;
        let actual_burst = minimum_burst
            + (seed_unit(emitter_index as f32 * 173.17 + burst_index as f32 * 19.91)
                * (burst - minimum_burst + 1) as f32)
                .floor() as usize;
        for particle in 0..actual_burst.min(burst) {
            if emitted >= maximum || instances.len() >= max_instances_per_emitter {
                break 'bursts;
            }
            let seed =
                emitter_index as f32 * 173.17 + burst_index as f32 * 19.91 + particle as f32 * 7.13;
            if seed_unit(seed + 43.7) >= keep_fraction {
                continue;
            }
            let life =
                (life_low + (life_high - life_low) * seed_unit(seed + 3.73)).clamp(0.01, 120.0);
            if age > life {
                continue;
            }
            let progress = (age / life).clamp(0.0, 1.0);
            let origin = effect_spawn_position(emitter, seed);
            let acceleration = effect_force(emitter, seed) / mass;
            let initial_velocity = effect_range(emitter.get("velocity"), seed + 11.1, Vec3::ZERO);
            let (local_center, velocity) = limited_particle_kinematics(
                origin,
                initial_velocity,
                acceleration,
                damping,
                age,
                speed_limit,
            );
            let center = model_matrix.transform_point3(local_center);
            let alpha = curve_sample(emitter.get("alpha_over_life"), progress, 1.0).clamp(0.0, 1.0);
            if alpha <= 0.001 {
                continue;
            }
            let scale_curve = curve_sample(emitter.get("scale_over_life"), progress, 1.0).max(0.0);
            let axes_curve = if emitter
                .get("scale_axes_over_life")
                .and_then(Value::as_array)
                .is_some_and(|v| !v.is_empty())
            {
                color_curve_sample(emitter.get("scale_axes_over_life"), progress)
            } else {
                Vec3::splat(scale_curve)
            };
            let scales = emitter.get("scale").and_then(Value::as_array);
            let scale_low = vec3_value(scales.and_then(|v| v.first()), Vec3::splat(0.04)).abs();
            let scale_high = vec3_value(scales.and_then(|v| v.get(1)), scale_low).abs();
            let size = scale_low.lerp(scale_high, seed_unit(seed + 0.91)) * axes_curve;
            if size.x <= 1.0e-6 || size.y <= 1.0e-6 {
                continue;
            }
            let radius = size.max_element();
            let colour = effect_billboard_colour(emitter, progress, alpha, brightness);
            let uv_rect = effect_sequence_uv(emitter, progress);
            let cells = (uv_rect[2] * uv_rect[3]).recip();
            let frame_blend = (progress.clamp(0.0, 0.999_999) * cells).fract();
            let texture_channel =
                if emitter.get("texture_channels").and_then(Value::as_u64) == Some(4) {
                    (seed_unit(seed + 37.1) * 4.0).floor().min(3.0) as i32
                } else if emitter.get("texture_is_mask").and_then(Value::as_bool) == Some(true) {
                    0
                } else {
                    -1
                };
            if kind == "mesh"
                && emitter
                    .get("particle_faces")
                    .and_then(Value::as_array)
                    .is_some_and(|v| !v.is_empty())
            {
                let angles = effect_range(emitter.get("rotation_3d"), seed + 23.3, Vec3::ZERO)
                    * (std::f32::consts::PI / 180.0);
                let rotation = Quat::from_euler(EulerRot::XYZ, angles.x, angles.y, angles.z);
                let transform = model_matrix
                    * Mat4::from_scale_rotation_translation(size, rotation, local_center);
                append_particle_mesh(
                    &mut instances,
                    emitter,
                    transform,
                    colour,
                    texture_index,
                    texture_channel,
                    blend,
                    max_instances_per_emitter,
                );
            } else if kind == "beam" {
                let local_axis =
                    vec3_value(emitter.get("beam_axis"), Vec3::Y).normalize_or(Vec3::Y);
                let length = emitter
                    .get("beam_length")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .filter(|value| value.is_finite())
                    .unwrap_or(0.0)
                    .abs()
                    .max(radius * 2.0);
                let width = emitter
                    .get("beam_width")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .filter(|value| value.is_finite())
                    .unwrap_or(radius)
                    .abs()
                    .max(minimum_radius * 0.5);
                let jitter = emitter
                    .get("beam_jitter")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .filter(|value| value.is_finite())
                    .unwrap_or(0.0)
                    .abs();
                let beam_delta = model_matrix.transform_vector3(local_axis * length);
                let world_length = beam_delta.length().max(radius * scene_scale * 2.0);
                let side = beam_delta
                    .normalize_or(Vec3::Y)
                    .cross(camera_forward)
                    .normalize_or(camera_right);
                let mut previous = center;
                for segment in 1..=6 {
                    if instances.len() >= max_instances_per_emitter {
                        break;
                    }
                    let fraction = segment as f32 / 6.0;
                    let current = center
                        + beam_delta * fraction
                        + side
                            * seed_signed(seed + segment as f32 * 5.19)
                            * world_length
                            * jitter
                            * (std::f32::consts::PI * fraction).sin();
                    let segment_axis = current - previous;
                    let ribbon_up = camera_forward.cross(segment_axis).normalize_or(camera_up)
                        * width
                        * scene_scale;
                    instances.push(EffectBillboardInstance {
                        center: ((previous + current) * 0.5).to_array(),
                        axis_right: (segment_axis * 0.5).to_array(),
                        axis_up: ribbon_up.to_array(),
                        colour,
                        uv_rect: [
                            uv_rect[0] + uv_rect[2] * (segment - 1) as f32 / 6.0,
                            uv_rect[1],
                            uv_rect[2] / 6.0,
                            uv_rect[3],
                        ],
                        texture_channel,
                        frame_blend: 0.0,
                        triangle_uvs: None,
                        texture_index,
                        blend,
                        depth: 0.0,
                    });
                    previous = current;
                }
            } else {
                let angle = (rotation_low
                    + (rotation_high - rotation_low) * seed_unit(seed + 23.3))
                .to_radians();
                let mut right_direction = camera_right * angle.cos() + camera_up * angle.sin();
                let mut up_direction = -camera_right * angle.sin() + camera_up * angle.cos();
                let world_velocity = model_matrix.transform_vector3(velocity);
                let projected_velocity =
                    world_velocity - camera_forward * world_velocity.dot(camera_forward);
                let stretch = 1.0 + projected_velocity.length() * velocity_stretch;
                if velocity_stretch > 0.0 && projected_velocity.length_squared() > 1.0e-8 {
                    up_direction = projected_velocity.normalize();
                    right_direction = up_direction
                        .cross(camera_forward)
                        .normalize_or(right_direction);
                }
                instances.push(EffectBillboardInstance {
                    center: center.to_array(),
                    axis_right: (right_direction * size.x * scene_scale).to_array(),
                    axis_up: (up_direction * size.y * scene_scale * stretch.clamp(1.0, 20.0))
                        .to_array(),
                    colour,
                    uv_rect,
                    texture_channel,
                    frame_blend,
                    triangle_uvs: None,
                    texture_index,
                    blend,
                    depth: 0.0,
                });
            }
            emitted += 1;
        }
    }
    instances
}

pub(crate) fn effect_emitter_lines(
    emitter: &Value,
    emitter_index: usize,
    time: f32,
    minimum_radius: f32,
) -> Vec<EffectLineVertex> {
    const MAX_PARTICLES_PER_EMITTER: usize = 256;
    const MAX_LINE_VERTICES_PER_EMITTER: usize = MAX_PARTICLES_PER_EMITTER * 20;

    let simulation_speed = emitter
        .get("simulation_speed")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .clamp(0.0, 20.0);
    let simulation_time = time.max(0.0) * simulation_speed;
    let burst = emitter
        .get("burst")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or(1)
        .clamp(1, 64);
    let maximum = emitter
        .get("max_particles")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or(burst)
        .clamp(1, MAX_PARTICLES_PER_EMITTER);
    let bursts_per_second = emitter
        .get("bursts_per_second")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .clamp(0.01, 120.0);
    let interval = bursts_per_second.recip();
    let (life_low, life_high) = value_pair(emitter.get("life"), (1.0, 1.0));
    let longest_life = life_high.clamp(0.01, 120.0);
    let looping = emitter.get("loop").and_then(Value::as_bool).unwrap_or(true);
    let spawn_time = emitter
        .get("spawn_time")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .max(0.0);
    let newest_burst = (simulation_time / interval).floor() as i64;
    let burst_history =
        ((longest_life / interval).ceil() as usize + 1).min(MAX_PARTICLES_PER_EMITTER);
    let kind = emitter
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("billboard");
    let mass = emitter
        .get("mass")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .abs()
        .max(0.01);
    let damping = emitter
        .get("damping")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .clamp(0.0, 100.0);
    let speed_limit = emitter
        .get("speed_limit")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .max(0.0);
    let (rotation_low, rotation_high) = value_pair(emitter.get("rotation"), (0.0, 0.0));
    let velocity_stretch = emitter
        .get("velocity_stretch")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .max(0.0);
    let brightness = emitter
        .get("brightness")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .max(0.0);
    let emissive_luma = vec3_value(emitter.get("emissive_color"), Vec3::ONE)
        .max(Vec3::ZERO)
        .dot(Vec3::new(0.2126, 0.7152, 0.0722))
        .max(0.05);
    let sequence_cells = emitter
        .get("sequence")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .take(2)
                .filter_map(Value::as_u64)
                .product::<u64>()
                .max(1) as f32
        })
        .unwrap_or(1.0);
    // Texture identity remains in the package for a future sprite pass. The
    // line preview below preserves the authored blend and colour meanwhile.
    let _sprite_identity = emitter.get("texture").and_then(Value::as_str).unwrap_or("");
    let blend = emitter
        .get("blend")
        .and_then(Value::as_str)
        .unwrap_or("alpha");

    let mut lines = Vec::new();
    let mut emitted = 0_usize;
    'bursts: for history in 0..burst_history {
        let burst_index = newest_burst - history as i64;
        if burst_index < 0 {
            continue;
        }
        let birth = burst_index as f32 * interval;
        if !looping
            && ((spawn_time <= 0.0 && burst_index > 0) || (spawn_time > 0.0 && birth > spawn_time))
        {
            continue;
        }
        let age = simulation_time - birth;
        if age < 0.0 || age > longest_life {
            continue;
        }
        for particle in 0..burst {
            if emitted >= maximum || lines.len() + 20 > MAX_LINE_VERTICES_PER_EMITTER {
                break 'bursts;
            }
            let seed =
                emitter_index as f32 * 173.17 + burst_index as f32 * 19.91 + particle as f32 * 7.13;
            let life =
                (life_low + (life_high - life_low) * seed_unit(seed + 3.73)).clamp(0.01, 120.0);
            if age > life {
                continue;
            }
            let progress = (age / life).clamp(0.0, 1.0);
            let origin = effect_spawn_position(emitter, seed);
            let acceleration = effect_force(emitter, seed) / mass;
            let initial_direction = Vec3::new(
                seed_signed(seed + 11.1),
                seed_signed(seed + 13.7),
                seed_signed(seed + 17.9),
            )
            .normalize_or(Vec3::Y);
            let initial_speed = vec3_value(emitter.get("spread"), Vec3::splat(0.1))
                .abs()
                .max_element()
                .max(0.01);
            let initial_velocity = initial_direction * initial_speed;
            let (center, mut velocity) =
                particle_kinematics(origin, initial_velocity, acceleration, damping, age);
            if speed_limit > 0.0 && velocity.length() > speed_limit {
                velocity = velocity.normalize_or_zero() * speed_limit;
            }
            let alpha = curve_sample(emitter.get("alpha_over_life"), progress, 1.0).clamp(0.0, 1.0);
            if alpha <= 0.001 {
                continue;
            }
            let scale_curve = curve_sample(emitter.get("scale_over_life"), progress, 1.0).max(0.0);
            let color_luma = color_curve_sample(emitter.get("color_over_life"), progress)
                .dot(Vec3::new(0.2126, 0.7152, 0.0722))
                .max(0.05);
            let flipbook_pulse = 0.9
                + 0.1
                    * (progress * sequence_cells * std::f32::consts::TAU)
                        .sin()
                        .abs();
            let radius = (effect_scale(emitter, seed)
                * scale_curve
                * alpha.sqrt()
                * (brightness * emissive_luma * color_luma)
                    .clamp(0.25, 4.0)
                    .sqrt()
                * flipbook_pulse)
                .max(minimum_radius);
            let colour = effect_preview_colour(emitter, progress, alpha, brightness, blend);
            let angle = (rotation_low + (rotation_high - rotation_low) * seed_unit(seed + 23.3))
                .to_radians();
            let right = Vec3::new(angle.cos(), angle.sin(), 0.0) * radius;
            let mut up = Vec3::new(-angle.sin(), angle.cos(), 0.0) * radius;
            if velocity_stretch > 0.0 && velocity.length_squared() > 1.0e-8 {
                up += velocity.normalize() * radius * velocity_stretch.min(20.0);
            }
            if kind == "beam" {
                let axis = vec3_value(emitter.get("beam_axis"), Vec3::Y).normalize_or(Vec3::Y);
                let length = emitter
                    .get("beam_length")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .filter(|value| value.is_finite())
                    .unwrap_or(0.0)
                    .abs();
                let width = emitter
                    .get("beam_width")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .filter(|value| value.is_finite())
                    .unwrap_or(radius)
                    .abs()
                    .max(minimum_radius * 0.5);
                let jitter = emitter
                    .get("beam_jitter")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .filter(|value| value.is_finite())
                    .unwrap_or(0.0)
                    .abs();
                let side = axis.cross(Vec3::Y).normalize_or(Vec3::X);
                let segments = 6;
                let mut previous = center;
                for segment in 1..=segments {
                    let fraction = segment as f32 / segments as f32;
                    let point = center
                        + axis * length * fraction
                        + side * seed_signed(seed + segment as f32 * 5.19) * length * jitter;
                    push_effect_line(&mut lines, previous, point, colour);
                    previous = point;
                }
                push_effect_line(
                    &mut lines,
                    center - side * width,
                    center + side * width,
                    colour,
                );
            } else {
                push_effect_line(&mut lines, center - right, center + right, colour);
                push_effect_line(&mut lines, center - up, center + up, colour);
                if kind == "mesh" {
                    let forward = right.cross(up).normalize_or(Vec3::Z) * radius;
                    push_effect_line(&mut lines, center - forward, center + forward, colour);
                }
            }
            emitted += 1;
        }
    }
    if lines.is_empty() {
        // At time zero many authored alpha curves intentionally start at zero.
        // Keep the emitter discoverable instead of presenting an empty preview.
        let radius = minimum_radius.max(0.003);
        let colour = effect_preview_colour(emitter, 0.5, 0.7, brightness, blend);
        for axis in [Vec3::X, Vec3::Y, Vec3::Z] {
            push_effect_line(&mut lines, -axis * radius, axis * radius, colour);
        }
    }
    lines
}

fn effect_range(value: Option<&Value>, seed: f32, fallback: Vec3) -> Vec3 {
    let values = value.and_then(Value::as_array);
    let low = vec3_value(values.and_then(|v| v.first()), fallback);
    let high = vec3_value(values.and_then(|v| v.get(1)), low);
    low + (high - low)
        * Vec3::new(
            seed_unit(seed + 2.03),
            seed_unit(seed + 5.17),
            seed_unit(seed + 8.29),
        )
}

#[allow(clippy::too_many_arguments)]
fn append_particle_mesh(
    instances: &mut Vec<EffectBillboardInstance>,
    emitter: &Value,
    transform: Mat4,
    colour: [f32; 4],
    texture_index: usize,
    texture_channel: i32,
    blend: EffectBlendMode,
    limit: usize,
) {
    let Some(vertices) = emitter.get("particle_vertices").and_then(Value::as_array) else {
        return;
    };
    let Some(faces) = emitter.get("particle_faces").and_then(Value::as_array) else {
        return;
    };
    let uvs = emitter.get("particle_uvs").and_then(Value::as_array);
    // A particle is either complete or omitted when its geometry exceeds the
    // frame budget. Never leave a half-drawn shard in the viewport.
    if faces.len() > limit.saturating_sub(instances.len()) {
        return;
    }
    for face in faces {
        let Some(indices) = face.as_array().filter(|v| v.len() == 3) else {
            continue;
        };
        let indices = indices
            .iter()
            .filter_map(Value::as_u64)
            .filter_map(|i| usize::try_from(i).ok())
            .collect::<Vec<_>>();
        if indices.len() != 3 || indices.iter().any(|i| *i >= vertices.len()) {
            continue;
        }
        let points = indices
            .iter()
            .map(|i| transform.transform_point3(vec3_value(vertices.get(*i), Vec3::ZERO)))
            .collect::<Vec<_>>();
        let edge1 = points[1] - points[0];
        let edge2 = points[2] - points[0];
        let normal = edge1.cross(edge2).normalize_or_zero();
        let light = 0.4 + 0.6 * normal.dot(Vec3::new(0.3, 0.8, 0.5).normalize()).abs();
        let mut shaded = colour;
        for c in &mut shaded[..3] {
            *c *= light;
        }
        let read_uv = |i: usize| -> [f32; 2] {
            let value = uvs.and_then(|v| v.get(i)).and_then(Value::as_array);
            [0, 1].map(|axis| {
                value
                    .and_then(|v| v.get(axis))
                    .and_then(Value::as_f64)
                    .filter(|v| v.is_finite())
                    .unwrap_or(0.0) as f32
            })
        };
        instances.push(EffectBillboardInstance {
            center: points[0].to_array(),
            axis_right: edge1.to_array(),
            axis_up: edge2.to_array(),
            colour: shaded,
            uv_rect: [0., 0., 1., 1.],
            texture_index,
            texture_channel,
            frame_blend: 0.0,
            triangle_uvs: Some([
                read_uv(indices[0]),
                read_uv(indices[1]),
                read_uv(indices[2]),
            ]),
            blend,
            depth: 0.0,
        });
    }
}

fn limited_particle_kinematics(
    origin: Vec3,
    initial_velocity: Vec3,
    acceleration: Vec3,
    damping: f32,
    age: f32,
    limit: f32,
) -> (Vec3, Vec3) {
    if limit <= 0.0 {
        return particle_kinematics(origin, initial_velocity, acceleration, damping, age);
    }
    // Integrate the capped velocity, not an uncapped displacement. Fixed work per
    // particle keeps scrubbing deterministic and independent of frame rate.
    let step = age / 32.0;
    let mut position = origin;
    let mut velocity = initial_velocity.clamp_length_max(limit);
    for _ in 0..32 {
        let next = particle_kinematics(Vec3::ZERO, velocity, acceleration, damping, step)
            .1
            .clamp_length_max(limit);
        position += (velocity + next) * (0.5 * step);
        velocity = next;
    }
    (position, velocity)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn draw(emitter: &Value, time: f32) -> Vec<EffectBillboardInstance> {
        effect_emitter_billboards(
            emitter,
            0,
            time,
            1.0,
            0,
            Mat4::IDENTITY,
            Vec3::X,
            Vec3::Y,
            -Vec3::Z,
        )
    }
    fn emitter() -> Value {
        json!({"loop":false,"bursts_per_second":0.,"life":[2.,2.],"alpha_over_life":[1.],"scale":[[0.1,0.4,0.1],[0.1,0.4,0.1]],"color_over_life":[[1.,0.3,0.1]],"emissive_color":[0.1,0.1,0.1]})
    }
    #[test]
    fn delay_zero_bursts_and_finite_repeats_control_emission() {
        let mut e = emitter();
        e["start_delay"] = json!([2., 2.]);
        assert!(draw(&e, 1.).is_empty());
        assert!(!draw(&e, 2.5).is_empty());
        e["burst"] = json!(0);
        assert!(draw(&e, 2.5).is_empty());
        e["burst"] = json!(1);
        e["start_delay"] = json!([0., 0.]);
        e["life"] = json!([0.1, 0.1]);
        e["bursts_per_second"] = json!(30.);
        e["spawn_time"] = json!(1.);
        assert!(draw(&e, 1.5).is_empty());
        e["loop_count"] = json!(2);
        assert!(!draw(&e, 1.5).is_empty());
    }

    #[test]
    fn quality_is_bounded_and_seeded_particle_comparisons_are_repeatable() {
        let e = json!({"loop":true,"burst":32,"bursts_per_second":30.,"life":[10.,10.],"max_particles":10000,"spread":[1.,1.,1.],"scale":[[0.1,0.1,0.1],[0.1,0.1,0.1]],"alpha_over_life":[1.]});
        let render = |budget, seed| {
            effect_emitter_billboards_with_limit(
                &e,
                seed,
                5.,
                1.,
                0,
                Mat4::IDENTITY,
                Vec3::X,
                Vec3::Y,
                -Vec3::Z,
                budget,
            )
        };
        let draft = render(64, 0);
        let high = render(1024, 0);
        assert!(!draft.is_empty() && draft.len() <= 64);
        assert!(high.len() > draft.len() && high.len() <= 1024);
        assert_eq!(high[0].center, render(1024, 0)[0].center);
        assert_ne!(high[0].center, render(1024, 1)[0].center);
    }
    #[test]
    fn authored_velocity_colour_and_rectangular_shape_survive_without_invented_spin() {
        let mut e = emitter();
        e["velocity"] = json!([[2., 0., 0.], [2., 0., 0.]]);
        let p = draw(&e, 0.5);
        assert_eq!(p.len(), 1);
        assert_eq!(p[0].center, [1., 0., 0.]);
        assert_eq!(p[0].axis_right, [0.1, 0., 0.]);
        assert_eq!(p[0].axis_up, [0., 0.4, 0.]);
        assert_eq!(p[0].colour, [1., 0.3, 0.1, 1.]);
    }
    #[test]
    fn invisible_particles_do_not_receive_a_minimum_visible_size() {
        let mut e = emitter();
        e["scale_over_life"] = json!([0.]);
        assert!(draw(&e, 0.5).is_empty());
        e["scale_over_life"] = json!([1.]);
        e["alpha_over_life"] = json!([0.]);
        assert!(draw(&e, 0.5).is_empty());
    }
    #[test]
    fn speed_limit_bounds_displacement_as_well_as_reported_velocity() {
        let (p, v) =
            limited_particle_kinematics(Vec3::ZERO, Vec3::ZERO, Vec3::Y * 1000., 0., 2., 2.);
        assert!(p.length() <= 4.0001 && p.y > 3.);
        assert!((v.length() - 2.).abs() < 0.001);
    }
    #[test]
    fn zero_interval_is_one_burst_and_expired_particles_disappear() {
        let e = emitter();
        assert_eq!(draw(&e, 1.).len(), 1);
        assert!(draw(&e, 2.01).is_empty());
    }
    #[test]
    fn particle_budget_keeps_a_range_of_ages_and_is_deterministic() {
        let mut e = emitter();
        e["loop"] = json!(true);
        e["burst"] = json!(16);
        e["max_particles"] = json!(256);
        e["bursts_per_second"] = json!(120.);
        e["velocity"] = json!([[1., 0., 0.], [1., 0., 0.]]);
        let p = draw(&e, 3.);
        assert!(p.len() <= 256 && !p.is_empty());
        assert!(p.iter().any(|p| p.center[0] < 0.5));
        assert!(p.iter().any(|p| p.center[0] > 1.5));
        assert_eq!(p, draw(&e, 3.));
    }
    #[test]
    fn mesh_particles_use_authored_triangles_and_uvs() {
        let mut e = emitter();
        e["kind"] = json!("mesh");
        e["particle_vertices"] = json!([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]);
        e["particle_faces"] = json!([[0, 1, 2]]);
        e["particle_uvs"] = json!([[0., 0.], [1., 0.], [0., 1.]]);
        let p = draw(&e, 0.5);
        assert_eq!(p.len(), 1);
        assert_eq!(p[0].axis_right, [0.1, 0., 0.]);
        assert_eq!(p[0].axis_up, [0., 0.4, 0.]);
        assert_eq!(p[0].triangle_uvs, Some([[0., 0.], [1., 0.], [0., 1.]]));
    }
}
