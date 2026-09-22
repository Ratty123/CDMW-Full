//! The procedural EffectTest_Lightning material used by mesh particles.
//!
//! Noise arithmetic was checked against the shipped RenderGPUParticles_VS
//! variant 5a038345_25fffac5_0_e2f61e7d_2_deba1dcd_b0ae633a. Keep the two
//! kernels distinct: the pivot's small noise uses a BCC lattice, while its
//! large noise sums three alternating simplex octaves.
//! Visibility is interpolated from that VS; emissive shaping follows PS
//! 5a038345_25fffac5_4_0fc1eb3c_2_deba1dcd_6c287fba (df866b7b91248a911fc91ffb6816a5a3).
use glam::{Mat4, Vec2, Vec3};
use serde_json::Value;

#[derive(Clone, Copy)]
pub(crate) struct LightningView {
    pub eye: Vec3,
    pub vertical_fov: f32,
    pub height: f32,
}

#[derive(Clone, Copy)]
pub(crate) struct LightningParticle {
    pub age: f32,
    pub seed: u32,
    pub scale: Vec3,
    pub parent: Mat4,
    pub transform: Mat4,
    pub view: LightningView,
}

fn number(values: &Value, key: &str) -> f32 {
    values
        .get(key)
        .and_then(Value::as_f64)
        .filter(|v| v.is_finite())
        .unwrap_or(0.) as f32
}

fn pair(values: &Value, key: &str) -> Vec2 {
    let value = &values[key];
    Vec2::new(
        value[0].as_f64().unwrap_or(0.) as f32,
        value[1].as_f64().unwrap_or(0.) as f32,
    )
}

struct Curve([f32; 128]);

impl Curve {
    fn read(material: &Value, key: &str) -> Option<Self> {
        let Some(spline) = material.get("splines").and_then(|v| v.get(key)) else {
            return Some(Self([1.; 128]));
        };
        let samples = spline
            .get("samples")
            .and_then(|v| v.get(0))
            .and_then(Value::as_array);
        if let Some(samples) = samples.filter(|v| v.len() == 128) {
            let mut result = [0.; 128];
            for (out, value) in result.iter_mut().zip(samples) {
                *out = value.as_f64()? as f32;
                if !out.is_finite() {
                    return None;
                }
            }
            Some(Self(result))
        } else if spline
            .get("preset")
            .and_then(Value::as_str)
            .is_none_or(str::is_empty)
            && spline
                .get("components")
                .and_then(Value::as_array)
                .is_none_or(Vec::is_empty)
        {
            Some(Self([1.; 128]))
        } else {
            None // Unknown interpolation or an unresolved preset must stay explicit.
        }
    }

    fn sample(&self, progress: f32) -> f32 {
        let at = progress.clamp(0., 1.) * 127.;
        let low = at.floor() as usize;
        self.0[low] + (self.0[(low + 1).min(127)] - self.0[low]) * at.fract()
    }
}

struct Amplitude {
    ratio: f32,
    time: f32,
    ratio_curve: Curve,
    time_curve: Curve,
}

impl Amplitude {
    fn read(material: &Value, ratio: &str, time: &str) -> Option<Self> {
        Some(Self {
            ratio: number(&material["values"], ratio),
            time: number(&material["values"], time),
            ratio_curve: Curve::read(material, &format!("{ratio}Spline"))?,
            time_curve: Curve::read(material, &format!("{time}Spline"))?,
        })
    }

    fn sample(&self, ratio: f32, age: f32) -> f32 {
        self.ratio * self.time * self.ratio_curve.sample(ratio) * self.time_curve.sample(age)
    }
}

struct Noise {
    amplitude: Amplitude,
    frequency: f32,
    speed: f32,
    offset: f32,
}

impl Noise {
    fn read(material: &Value, size: &str) -> Option<Self> {
        let name = format!("_{size}RatioPivotNoise");
        Some(Self {
            amplitude: Amplitude::read(
                material,
                &format!("{name}Amplitude"),
                &format!("_{size}TimePivotNoiseAmplitude"),
            )?,
            frequency: number(&material["values"], &format!("{name}Frequency")),
            speed: number(&material["values"], &format!("{name}Speed")),
            offset: number(&material["values"], &format!("{name}Offset")),
        })
    }
}

struct Thickness {
    range: Vec2,
    ratio_curve: Curve,
    time: f32,
    time_curve: Curve,
}

impl Thickness {
    fn read(material: &Value, branch: &str) -> Option<Self> {
        let name = format!("_{branch}BranchThickness");
        Some(Self {
            range: pair(&material["values"], &name),
            ratio_curve: Curve::read(material, &format!("{name}Spline"))?,
            time: number(&material["values"], &format!("{name}ByTime")),
            time_curve: Curve::read(material, &format!("{name}ByTimeSpline"))?,
        })
    }

    fn sample(&self, random: f32, ratio: f32, age: f32) -> f32 {
        (self.range.x + (self.range.y - self.range.x) * random)
            * self.ratio_curve.sample(ratio)
            * self.time
            * self.time_curve.sample(age)
    }
}

struct Shading {
    parameters: [[f32; 4]; 3],
    progress: Curve,
    speed: Curve,
    emissive: Curve,
}

impl Shading {
    fn read(material: &Value, flags: u64) -> Option<Self> {
        let values = &material["values"];
        let finite = |value: &Value| {
            let result = value.as_f64()? as f32;
            result.is_finite().then_some(result)
        };
        Some(Self {
            // A partial/unknown shading block must not turn valid geometry black
            // by silently treating missing emissive limits as [0, 0].
            parameters: [
                [finite(&values["_emissiveThickness"])?, finite(&values["_emissivePerimeter"])?,
                    finite(&values["_emissiveEffectRatio"])?, finite(&values["_emissiveForHideExp"])?],
                [finite(&values["_progress"])?, finite(&values["_speed"])?,
                    finite(&values["_emissiveMinMaxLimits"][0])?, finite(&values["_emissiveMinMaxLimits"][1])?],
                [u32::from(flags & 0x8000 != 0) as f32, 1., 0., 0.],
            ],
            progress: Curve::read(material, "_progressSpline")?,
            speed: Curve::read(material, "_speedSpline")?,
            emissive: Curve::read(material, "_emissiveThicknessSpline")?,
        })
    }
}

pub(crate) struct LightningMaterial {
    main: Thickness,
    sub: Thickness,
    small: Noise,
    big: Noise,
    deform: Amplitude,
    deform_frequency: f32,
    deform_speed: f32,
    deform_offset: f32,
    deform_sub_branch: f32,
    thickness_exponent: f32,
    sub_limits: Vec2,
    continuous: bool,
    distance_width: bool,
    distance_range: Vec2,
    distance_multiple: f32,
    shading: Option<Shading>,
}

impl LightningMaterial {
    pub(crate) fn gpu(&self) -> cdmw_render_wgpu::EffectLightningMaterial {
        let shading = self.shading.as_ref();
        cdmw_render_wgpu::EffectLightningMaterial {
            parameters: [
                [self.main.range.x, self.main.range.y, self.main.time, self.thickness_exponent],
                [self.sub.range.x, self.sub.range.y, self.sub.time, self.deform_sub_branch],
                [self.small.amplitude.ratio, self.small.amplitude.time, self.small.frequency, self.small.speed],
                [self.big.amplitude.ratio, self.big.amplitude.time, self.big.frequency, self.big.speed],
                [self.deform.ratio, self.deform.time, self.deform_frequency, self.deform_speed],
                [self.small.offset, self.big.offset, self.deform_offset, u32::from(self.continuous) as f32],
                [self.distance_range.x, self.distance_range.y, self.distance_multiple, u32::from(self.distance_width) as f32],
                [self.sub_limits.x, self.sub_limits.y, 0., 0.],
                shading.map_or([0.; 4], |s| s.parameters[0]),
                shading.map_or([0.; 4], |s| s.parameters[1]),
                shading.map_or([0.; 4], |s| s.parameters[2]),
            ],
            curves: [self.main.ratio_curve.0, self.main.time_curve.0,
                self.sub.ratio_curve.0, self.sub.time_curve.0,
                self.small.amplitude.ratio_curve.0, self.small.amplitude.time_curve.0,
                self.big.amplitude.ratio_curve.0, self.big.amplitude.time_curve.0,
                self.deform.ratio_curve.0, self.deform.time_curve.0,
                shading.map_or([1.; 128], |s| s.progress.0),
                shading.map_or([1.; 128], |s| s.speed.0),
                shading.map_or([1.; 128], |s| s.emissive.0)],
        }
    }

    pub(crate) fn read(emitter: &Value) -> Option<Self> {
        let material = emitter.get("material")?;
        let values = &material["values"];
        let flags = values["_materialFlags"].as_u64().unwrap_or(0);
        if material["name"].as_str() != Some("EffectTest_Lightning")
            || flags & 0x4000 == 0
            || number(values, "_noiseType") != 0.
            || number(values, "_smallRatioVertexNoiseAmplitude") != 0.
            || number(values, "_bigRatioVertexNoiseAmplitude") != 0.
        {
            return None;
        }
        Some(Self {
            main: Thickness::read(material, "main")?,
            sub: Thickness::read(material, "sub")?,
            small: Noise::read(material, "small")?,
            big: Noise::read(material, "big")?,
            deform: Amplitude::read(material, "_deformRatioAmplitude", "_deformTimeAmplitude")?,
            deform_frequency: number(values, "_deformRatioFrequency"),
            deform_speed: number(values, "_deformRatioSpeed"),
            deform_offset: number(values, "_deformRatioOffset"),
            deform_sub_branch: number(values, "_deformSubBranchAmplitude"),
            thickness_exponent: number(values, "_perimeterThicknessExp"),
            sub_limits: pair(values, "_subBranchThicknessMinMaxLimits"),
            continuous: flags & 0x20000 != 0,
            distance_width: flags & 0x40000 != 0,
            distance_range: pair(values, "_fieldOfViewDistanceRange"),
            distance_multiple: number(values, "_fieldOfViewMultipleValue"),
            shading: Shading::read(material, flags),
        })
    }

    fn phase(&self, age: f32, speed: f32) -> f32 {
        if self.continuous {
            age * speed
        } else {
            ((age - 0.01) * speed).trunc()
        }
    }

    pub(crate) fn deform_vertex(
        &self,
        position: Vec3,
        normal: Vec3,
        uv: Vec2,
        controls: Vec3,
        particle: LightningParticle,
    ) -> Vec3 {
        let LightningParticle {
            age,
            seed,
            scale: particle_scale,
            parent,
            transform,
            view,
        } = particle;
        let normal = (normal / particle_scale).normalize_or_zero();
        let pivot = position + normal * 0.001;
        let ratio = 1. - uv.x;
        // The material uses the same two-step integer generator as the game,
        // not a new random value on every frame.
        let first = seed.wrapping_mul(54_787_328).wrapping_add(221_680_323);
        let second = first.wrapping_mul(214_013).wrapping_add(2_531_011);
        let random_bits = ((second & 0xffff0000) | (first >> 16)) % 32_767;
        let random = random_bits as f32 / 32_766.;
        let random_offset = random_bits as f32 * 0.030_519_44;
        let is_main = controls.y >= 0.9;
        let perimeter = controls.z.max(0.).powf(self.thickness_exponent);
        let mut main_width = self.main.sample(random, ratio, age) * perimeter;
        let mut sub_width = self.sub.sample(random, ratio, age) * perimeter;
        if self.distance_width {
            let distance = parent.w_axis.truncate().distance(view.eye);
            let amount = ((distance - self.distance_range.x)
                / (self.distance_range.y - self.distance_range.x).max(1.0e-6))
            .clamp(0., 1.);
            let multiple = 1. + (self.distance_multiple - 1.) * amount;
            main_width *= multiple;
            sub_width *= multiple;
        }
        let sub_width = sub_width.max(self.sub_limits.x).min(self.sub_limits.y);
        let world_position = transform.transform_point3(position);
        let distance = world_position.distance(view.eye);
        let scale_length = particle_scale.length();
        let minimum =
            (0.004_2 + 0.037_8 * (distance * 0.01).clamp(0., 1.)) / (2. * scale_length).max(1.);
        let width = (if is_main { main_width } else { sub_width }).max(minimum);
        let parent_scale = Vec3::new(
            parent.x_axis.length(),
            parent.y_axis.length(),
            parent.z_axis.length(),
        );
        let mut expansion = -normal * width;
        if parent_scale.max_element() > 1. {
            expansion /= parent_scale.max(Vec3::splat(1.0e-8));
        }
        let v_width = 1. - ((uv.y - 0.5).abs() * 2.).clamp(0., 1.);
        let pixel_width = view.vertical_fov.min(1.221_730_5).tan() * distance / view.height.max(1.)
            * (0.5 + 0.5 * v_width)
            / scale_length.max(1.0e-8);
        expansion = expansion.normalize_or_zero() * expansion.length().max(pixel_width);

        let angle = self.deform_frequency * uv.x
            + seed as f32
            + self.deform_offset
            + self.phase(age, self.deform_speed);
        let mut amplitude = self.deform.sample(ratio, age);
        if !is_main {
            amplitude *= self.deform_sub_branch + (1. - self.deform_sub_branch) * (1. - uv.y);
        }
        let bend = Vec3::new(angle.sin(), 0., angle.cos()) * amplitude;
        let small_point = pivot * self.small.frequency
            + Vec3::Y * (self.small.offset + random_offset + self.phase(age, self.small.speed));
        let big_point = pivot * self.big.frequency
            + Vec3::new(
                23.,
                43. + random_offset + self.big.offset + self.phase(age, self.big.speed),
                11.,
            );
        position
            + expansion
            + bend
            + bcc_noise(small_point) * self.small.amplitude.sample(ratio, age)
            + large_pivot_noise(big_point) * self.big.amplitude.sample(ratio, age)
    }
}

fn modulo(value: f32, divisor: f32) -> f32 {
    value - (value / divisor).floor() * divisor
}

fn bcc_gradient(hash: f32) -> Vec3 {
    let cube = Vec3::from_array(
        [1., 2., 4.].map(|divisor| modulo((hash / divisor).floor(), 2.) * 2. - 1.),
    );
    let mut cuboct = cube;
    cuboct[(hash / 16.) as usize] = 0.;
    let kind = modulo((hash / 8.).floor(), 2.);
    let rhomb = (1. - kind) * cube + kind * (cuboct + cube.cross(cuboct));
    (cuboct * 1.224_744_9 + rhomb) * (32.802_013 - 1.408_598_4 * kind)
}

fn bcc_noise(point: Vec3) -> Vec3 {
    let permute = |value: f32| value * (value * 34. + 133.);
    let mut result = Vec3::ZERO;
    for shift in [0., 144.5] {
        let point = point + Vec3::splat(shift);
        // Round_ne is ties-to-even. Strict comparisons below are intentional:
        // equal distances do not choose an arbitrary largest axis.
        let nearest = Vec3::from_array(point.to_array().map(f32::round_ties_even));
        let delta = point - nearest;
        let score = delta.abs();
        let side = Vec3::from_array(std::array::from_fn(|axis| {
            if score[axis] > score[(axis + 1) % 3].max(score[(axis + 2) % 3]) {
                if delta[axis] < 0. { -1. } else { 1. }
            } else {
                0.
            }
        }));
        for vertex in [nearest, nearest + side] {
            let delta = point - vertex;
            let hash = permute(modulo(vertex.x, 289.));
            let hash = permute(modulo(hash + vertex.y, 289.));
            let hash = modulo(permute(modulo(hash + vertex.z, 289.)), 48.);
            let gradient = bcc_gradient(hash);
            let weight = (0.5 - delta.length_squared()).max(0.);
            let square = weight * weight;
            result +=
                gradient * (square * square) - delta * (8. * square * weight * delta.dot(gradient));
        }
    }
    result
}

fn simplex_noise(point: Vec3) -> Vec3 {
    let permute = |value: f32| modulo(value * (value * 34. + 1.), 289.);
    let lattice = (point + Vec3::splat(point.element_sum() / 3.)).floor();
    let delta = point - lattice + Vec3::splat(lattice.element_sum() / 6.);
    let order = Vec3::from_array(std::array::from_fn(|axis| {
        if delta[axis] >= delta[(axis + 1) % 3] {
            1.
        } else {
            0.
        }
    }));
    let inverse = Vec3::ONE - order;
    let previous = Vec3::new(inverse.z, inverse.x, inverse.y);
    let first = order.min(previous);
    let second = order.max(previous);
    let lattice = Vec3::from_array(lattice.to_array().map(|v| modulo(v, 289.)));
    let mut result = Vec3::ZERO;
    for (step, delta) in [
        (Vec3::ZERO, delta),
        (first, delta - first + Vec3::splat(1. / 6.)),
        (second, delta - second + Vec3::splat(1. / 3.)),
        (Vec3::ONE, delta - Vec3::splat(0.5)),
    ] {
        let hash = permute(lattice.z + step.z);
        let hash = permute(hash + lattice.y + step.y);
        let hash = modulo(permute(hash + lattice.x + step.x), 49.);
        let x = (hash / 7.).floor();
        let y = (hash - x * 7.).floor();
        let mut x = x * (2. / 7.) - 0.928_571_4;
        let mut y = y * (2. / 7.) - 0.928_571_4;
        let z = 1. - x.abs() - y.abs();
        if z <= 0. {
            x -= x.floor() * 2. + 1.;
            y -= y.floor() * 2. + 1.;
        }
        let gradient = Vec3::new(x, y, z);
        let gradient = gradient * (1.792_842_9 - 0.853_734_73 * gradient.length_squared());
        let weight = (0.6 - delta.length_squared()).max(0.);
        let square = weight * weight;
        // The shipped derivative uses -6 here, not the -8 in the BCC kernel.
        result +=
            gradient * (square * square) - delta * (6. * square * weight * delta.dot(gradient));
    }
    result
}

fn large_pivot_noise(point: Vec3) -> Vec3 {
    let mut result = Vec3::ZERO;
    let mut frequency = 1.;
    let mut amplitude = -42.;
    for octave in 0..3 {
        result += simplex_noise((point + Vec3::splat((3 - octave) as f32)) * frequency) * amplitude;
        frequency *= 2.;
        amplitude *= -0.5;
    }
    result / 3.
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn emitter() -> Value {
        json!({"material": {"name": "EffectTest_Lightning", "values": {
            "_materialFlags": 16384,
            "_mainBranchThickness": [0.1, 0.1], "_subBranchThickness": [0.5, 0.5],
            "_mainBranchThicknessByTime": 1., "_subBranchThicknessByTime": 1.,
            "_subBranchThicknessMinMaxLimits": [0., 100.], "_perimeterThicknessExp": 2.,
            "_deformRatioAmplitude": 1., "_deformTimeAmplitude": 1.,
            "_deformRatioFrequency": 6., "_deformRatioSpeed": 2., "_deformSubBranchAmplitude": 1.
        }}})
    }

    fn particle(age: f32) -> LightningParticle {
        LightningParticle {
            age,
            seed: 17,
            scale: Vec3::ONE,
            parent: Mat4::IDENTITY,
            transform: Mat4::IDENTITY,
            view: LightningView {
                eye: Vec3::Z * 5.,
                vertical_fov: 45_f32.to_radians(),
                height: 512.,
            },
        }
    }

    #[test]
    fn lightning_shading_retains_resolved_curves_and_rejects_incomplete_blocks() {
        let mut emitter = emitter();
        let partial = LightningMaterial::read(&emitter).unwrap().gpu();
        assert_eq!(partial.parameters[10][1], 0.);
        let values = emitter["material"]["values"].as_object_mut().unwrap();
        for (key,value) in [("_emissiveThickness",2.), ("_emissivePerimeter",4.),
            ("_emissiveEffectRatio",1.), ("_emissiveForHideExp",1.), ("_progress",0.5), ("_speed",1.)] {
            values.insert(key.into(), json!(value));
        }
        values.insert("_materialFlags".into(), json!(0x4000 | 0x8000));
        values.insert("_emissiveMinMaxLimits".into(), json!([0.,1e8]));
        emitter["material"]["splines"] = json!({
            "_progressSpline": {"samples":[vec![0.25;128]]},
            "_speedSpline": {"samples":[vec![0.5;128]]},
            "_emissiveThicknessSpline": {"samples":[vec![0.75;128]]}
        });
        let gpu = LightningMaterial::read(&emitter).unwrap().gpu();
        assert_eq!(gpu.parameters[8], [2.,4.,1.,1.]);
        assert_eq!(gpu.parameters[9], [0.5,1.,0.,1e8]);
        assert_eq!(gpu.parameters[10], [1.,1.,0.,0.]);
        assert_eq!(gpu.curves[10..], [[0.25;128],[0.5;128],[0.75;128]]);
        emitter["material"]["splines"]["_progressSpline"] = json!({"preset":"unresolved"});
        assert_eq!(LightningMaterial::read(&emitter).unwrap().gpu().parameters[10][1], 0.);
    }

    #[test]
    fn lightning_motion_obeys_stepped_phase_and_continuous_flag() {
        let mut emitter = emitter();
        let material = LightningMaterial::read(&emitter).unwrap();
        let render = |material: &LightningMaterial, age| {
            material.deform_vertex(
                Vec3::new(1., 2., 3.),
                Vec3::Y,
                Vec2::new(0.37, 0.5),
                Vec3::ONE,
                particle(age),
            )
        };
        assert_eq!(render(&material, 0.21), render(&material, 0.29));
        assert!((render(&material, 0.21) - render(&material, 0.61)).length() > 0.5);
        emitter["material"]["values"]["_materialFlags"] = json!(0x4000 | 0x20000);
        let continuous = LightningMaterial::read(&emitter).unwrap();
        assert!((render(&continuous, 0.21) - render(&continuous, 0.29)).length() > 0.1);
    }

    #[test]
    fn lightning_branch_controls_change_width_without_tinting_or_generic_jitter() {
        let emitter = emitter();
        let material = LightningMaterial::read(&emitter).unwrap();
        let render = |controls| {
            material.deform_vertex(Vec3::ZERO, Vec3::Y, Vec2::ZERO, controls, particle(0.5))
        };
        let main = render(Vec3::new(0.1, 1., 1.));
        let sub = render(Vec3::new(0.1, 0.5, 1.));
        assert!((main.y + 0.1).abs() < 1.0e-6);
        assert!((sub.y + 0.5).abs() < 1.0e-6);
        assert_eq!(main.x, sub.x);
        assert_eq!(main.z, sub.z);
        let thin = render(Vec3::new(0.1, 1., 0.5));
        assert!((thin.y + 0.025).abs() < 1.0e-6);
    }

    #[test]
    fn lightning_consumes_baked_material_curves_and_rejects_unknown_modes() {
        let mut emitter = emitter();
        emitter["material"]["splines"] =
            json!({"_deformTimeAmplitudeSpline": {"samples": [vec![0.; 128]]}});
        let material = LightningMaterial::read(&emitter).unwrap();
        let actual =
            material.deform_vertex(Vec3::ZERO, Vec3::Y, Vec2::ZERO, Vec3::ONE, particle(0.5));
        assert_eq!(actual, Vec3::new(0., -0.1, 0.));
        emitter["material"]["splines"]["_deformTimeAmplitudeSpline"] =
            json!({"components": [[{"interpolation": 37}]], "samples": [[]]});
        assert!(LightningMaterial::read(&emitter).is_none());
        emitter["material"]["splines"] = json!({});
        emitter["material"]["values"]["_noiseType"] = json!(1);
        assert!(LightningMaterial::read(&emitter).is_none());
    }

    #[test]
    fn lightning_noise_matches_decoded_shader_arithmetic() {
        // Independent numerical references: 503 BCC and 378 simplex DXIL
        // instructions, rounded to float32. No game mesh or shader is bundled.
        let samples = [
            (
                [0., 0., 0.],
                [-4.100_251_7, -9.122_014, -9.122_014],
                [0.035_593_472, 0.035_593_472, -0.180_182_13],
            ),
            (
                [0.13, 0.47, 0.79],
                [1.039_085_1, 0.108_880_915, -1.166_515_7],
                [0.005_873_694, 0.011_551_425, -0.011_538_134],
            ),
            (
                [2.17, 7.37, 1.91],
                [0.862_208_7, -1.054_518_1, -2.125_008_6],
                [0.031_937_137, -0.030_513_067, -0.037_577_398],
            ),
            (
                [-2.23, -0.39, 5.27],
                [-0.877_776_6, -2.141_624_5, 2.063_987_7],
                [-0.015_363_171, -0.023_121_57, -0.018_758_822],
            ),
            (
                [23.31, 108.2, 11.02],
                [-3.007_142_5, -0.458_162_3, -0.484_148_92],
                [0.044_223_573, 0.010_615_779, -0.030_847_441],
            ),
            (
                [0.5, 0.5, 0.5],
                [-12.654_4695, 0., -4.806_115_6],
                [-0.054_270_405, 0.116_510_26, -0.118_313_25],
            ),
            (
                [1.2, 2.3, 3.4],
                [0.288_275_45, -0.098_356_01, 2.384_689_3],
                [-0.000_177_280_98, 0.007_589_494, -0.060_122_41],
            ),
        ];
        for (point, small, large) in samples {
            let point = Vec3::from_array(point);
            assert!(
                (bcc_noise(point) - Vec3::from_array(small))
                    .abs()
                    .max_element()
                    < 0.000_02,
                "BCC at {point:?}"
            );
            assert!(
                (simplex_noise(point) - Vec3::from_array(large))
                    .abs()
                    .max_element()
                    < 0.000_002,
                "simplex at {point:?}"
            );
        }
    }

    #[test]
    #[ignore = "D3D12 readback of production GPU lightning deformation; synthetic geometry only"]
    fn lightning_gpu_deformation_matches_decoded_cpu_reference() {
        use cdmw_render_wgpu::{EffectMeshAsset, EffectMeshVertex, EffectMeshParticle, EffectMeshView};
        let mut e = emitter();
        for (key,value) in [("_smallRatioPivotNoiseAmplitude",0.01), ("_smallTimePivotNoiseAmplitude",1.),
            ("_smallRatioPivotNoiseFrequency",8.), ("_smallRatioPivotNoiseSpeed",5.),
            ("_bigRatioPivotNoiseAmplitude",0.2), ("_bigTimePivotNoiseAmplitude",1.),
            ("_bigRatioPivotNoiseFrequency",1.), ("_bigRatioPivotNoiseSpeed",3.)] {
            e["material"]["values"][key] = json!(value);
        }
        for (i,key) in ["_mainBranchThicknessSpline","_mainBranchThicknessByTimeSpline",
            "_subBranchThicknessSpline","_subBranchThicknessByTimeSpline",
            "_smallRatioPivotNoiseAmplitudeSpline","_smallTimePivotNoiseAmplitudeSpline",
            "_bigRatioPivotNoiseAmplitudeSpline","_bigTimePivotNoiseAmplitudeSpline",
            "_deformRatioAmplitudeSpline","_deformTimeAmplitudeSpline"].into_iter().enumerate() {
            let samples = (0..128).map(|n| 0.3 + i as f32 * 0.03 + n as f32 / 254.).collect::<Vec<_>>();
            e["material"]["splines"][key] = json!({"samples":[samples]});
        }
        let material = LightningMaterial::read(&e).unwrap();
        let vertices = (0..24).map(|i| {
            let t = i as f32 / 23.;
            EffectMeshVertex { position: [t-0.5,t*2.,t*10.],
                normal: Vec3::new(t+0.2,1.,-0.1).normalize().to_array(), uv: [t,0.7-t*0.3],
                controls: [0.3, if i%2 == 0 {1.} else {0.5}, 0.25+t*0.7,1.] }
        }).collect::<Vec<_>>();
        let parent = Mat4::from_scale_rotation_translation(Vec3::new(1.2,0.8,2.),
            glam::Quat::from_rotation_y(0.4),Vec3::new(0.2,1.5,0.));
        let view = LightningView {eye:Vec3::new(0.5,1.2,3.),vertical_fov:0.65,height:720.};
        let particles = [0.21,0.51,0.81].into_iter().enumerate().map(|(i,age)| {
            let scale = Vec3::new(0.02,0.015,0.03);
            let transform = parent * Mat4::from_scale_rotation_translation(scale,
                glam::Quat::from_rotation_x(0.2+i as f32),Vec3::new(0.1,0.,0.))
                * Mat4::from_translation(Vec3::new(0.,0.,-5.));
            LightningParticle { age, seed: [0,17,4819][i], scale, parent, transform, view }
        }).collect::<Vec<_>>();
        let gpu_particles = particles.iter().map(|p| EffectMeshParticle {
            transform: p.transform.to_cols_array_2d(), colour: [1.;4],
            scale_age: [p.scale.x,p.scale.y,p.scale.z,p.age], seed: [p.seed,0,0,0],
            parent_scale: [parent.x_axis.length(),parent.y_axis.length(),parent.z_axis.length(),0.],
            parent_origin: parent.w_axis.to_array(),
        }).collect::<Vec<_>>();
        let asset = EffectMeshAsset { vertices, indices: vec![0,1,2], lightning: material.gpu() };
        let positions = pollster::block_on(cdmw_render_wgpu::run_headless_effect_mesh_deformation(
            &asset,&gpu_particles,EffectMeshView { eye_height:[view.eye.x,view.eye.y,view.eye.z,view.height],
                fov_padding:[view.vertical_fov,0.,0.,0.] })).expect("GPU deformation readback");
        let mut maximum = 0_f32;
        for ((p,v),actual) in particles.iter().flat_map(|p| asset.vertices.iter().map(move |v| (p,v))).zip(positions) {
            let expected = p.transform.transform_point3(material.deform_vertex(Vec3::from_array(v.position),
                Vec3::from_array(v.normal),Vec2::from_array(v.uv),Vec3::new(v.controls[0],v.controls[1],v.controls[2]),*p));
            maximum = maximum.max((expected-Vec3::new(actual[0],actual[1],actual[2])).abs().max_element());
        }
        assert!(maximum < 0.0002, "GPU/decoded CPU deviation: {maximum}");
    }
}
