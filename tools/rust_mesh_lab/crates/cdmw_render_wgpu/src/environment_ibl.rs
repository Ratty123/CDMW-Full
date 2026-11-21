//! Physically prefiltered HDRI environment arrays and L2 SH irradiance for Studio & Outdoor viewports.
use bytemuck::{Pod, Zeroable};
use glam::{Vec2, Vec3};
use std::f32::consts::PI;
use std::sync::OnceLock;
use wgpu::util::DeviceExt;

pub(super) const ENV_WIDTH: u32 = 256;
pub(super) const ENV_HEIGHT: u32 = 128;
pub(super) const ENV_MIP_COUNT: u32 = 7;
pub(super) const ENV_LAYERS: u32 = 2;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StudioLookSettings {
    pub wetness: f32,
    pub exposure: f32,
    pub env_rotation_degrees: f32,
}

impl Default for StudioLookSettings {
    fn default() -> Self {
        Self {
            wetness: 0.0,
            exposure: 1.0,
            env_rotation_degrees: 0.0,
        }
    }
}

impl StudioLookSettings {
    pub(super) fn look_uniform(self) -> [f32; 4] {
        let wetness = if self.wetness.is_finite() {
            self.wetness.clamp(0.0, 1.0)
        } else {
            0.0
        };
        let exposure = if self.exposure.is_finite() {
            self.exposure.clamp(0.4, 2.5)
        } else {
            1.0
        };
        let radians = if self.env_rotation_degrees.is_finite() {
            self.env_rotation_degrees.to_radians()
        } else {
            0.0
        };
        [wetness, exposure, radians.sin(), radians.cos()]
    }

    pub(super) fn rotate_world_direction(self, direction: Vec3) -> Vec3 {
        let radians = if self.env_rotation_degrees.is_finite() {
            self.env_rotation_degrees.to_radians()
        } else {
            0.0
        };
        let (s, c) = radians.sin_cos();
        Vec3::new(
            direction.x * c + direction.z * s,
            direction.y,
            -direction.x * s + direction.z * c,
        )
    }
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub(super) struct StudioEnvUniform {
    pub sh_studio: [[f32; 4]; 9],
    pub sh_outdoor: [[f32; 4]; 9],
    pub look: [f32; 4],
}

pub(super) struct PrefilteredEnvData {
    // [layer][mip] RGBA16F packed half-floats (4 u16s per texel).
    mips_f16: [[Vec<u16>; ENV_MIP_COUNT as usize]; ENV_LAYERS as usize],
    pub sh_studio: [[f32; 4]; 9],
    pub sh_outdoor: [[f32; 4]; 9],
}

static ENV_DATA: OnceLock<PrefilteredEnvData> = OnceLock::new();

pub(super) fn cached_env_data() -> &'static PrefilteredEnvData {
    ENV_DATA.get_or_init(build_prefiltered_env_data)
}

pub(super) struct GpuEnvironmentIbl {
    _texture: wgpu::Texture,
    pub view: wgpu::TextureView,
    pub sampler: wgpu::Sampler,
}

impl GpuEnvironmentIbl {
    pub(super) fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Self {
        let data = cached_env_data();
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("CDMW studio & outdoor prefiltered HDRI"),
            size: wgpu::Extent3d {
                width: ENV_WIDTH,
                height: ENV_HEIGHT,
                depth_or_array_layers: ENV_LAYERS,
            },
            mip_level_count: ENV_MIP_COUNT,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba16Float,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        for layer in 0..ENV_LAYERS {
            for mip in 0..ENV_MIP_COUNT {
                let mip_w = (ENV_WIDTH >> mip).max(1);
                let mip_h = (ENV_HEIGHT >> mip).max(1);
                let bytes: &[u8] = bytemuck::cast_slice(&data.mips_f16[layer as usize][mip as usize]);
                queue.write_texture(
                    wgpu::TexelCopyTextureInfo {
                        texture: &texture,
                        mip_level: mip,
                        origin: wgpu::Origin3d {
                            x: 0,
                            y: 0,
                            z: layer,
                        },
                        aspect: wgpu::TextureAspect::All,
                    },
                    bytes,
                    wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(mip_w * 8),
                        rows_per_image: Some(mip_h),
                    },
                    wgpu::Extent3d {
                        width: mip_w,
                        height: mip_h,
                        depth_or_array_layers: 1,
                    },
                );
            }
        }
        let view = texture.create_view(&wgpu::TextureViewDescriptor {
            dimension: Some(wgpu::TextureViewDimension::D2Array),
            ..Default::default()
        });
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("CDMW prefiltered HDRI sampler"),
            address_mode_u: wgpu::AddressMode::Repeat,
            address_mode_v: wgpu::AddressMode::ClampToEdge,
            address_mode_w: wgpu::AddressMode::ClampToEdge,
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::MipmapFilterMode::Linear,
            ..Default::default()
        });
        Self {
            _texture: texture,
            view,
            sampler,
        }
    }

    pub(super) fn create_uniform_buffer(
        device: &wgpu::Device,
        look: StudioLookSettings,
    ) -> wgpu::Buffer {
        let data = cached_env_data();
        let uniform = StudioEnvUniform {
            sh_studio: data.sh_studio,
            sh_outdoor: data.sh_outdoor,
            look: look.look_uniform(),
        };
        device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW studio environment SH & look uniform"),
            contents: bytemuck::bytes_of(&uniform),
            usage: wgpu::BufferUsages::UNIFORM,
        })
    }
}

#[inline]
fn f32_to_f16(value: f32) -> u16 {
    if !value.is_finite() || value <= 0.0 {
        return 0;
    }
    let clamped = value.min(65504.0);
    let bits = clamped.to_bits();
    let exp = ((bits >> 23) & 0xff) as i32 - 127 + 15;
    let frac = bits & 0x007f_ffff;
    if exp <= 0 {
        if exp < -10 {
            return 0;
        }
        let mant = (frac | 0x0080_0000) >> (1 - exp + 13);
        return mant as u16;
    }
    if exp >= 31 {
        return 0x7bff;
    }
    ((exp as u16) << 10) | ((frac >> 13) as u16)
}

#[cfg(test)]
#[inline]
fn f16_to_f32(bits: u16) -> f32 {
    let sign = u32::from(bits & 0x8000) << 16;
    let exp = u32::from((bits >> 10) & 0x1f);
    let frac = u32::from(bits & 0x03ff);
    let fbits = match exp {
        0 if frac == 0 => sign,
        0 => {
            let mut m = frac;
            let mut shift = 0_u32;
            while (m & 0x0400) == 0 {
                m <<= 1;
                shift += 1;
            }
            m &= 0x03ff;
            let new_exp = 127 - 15 - shift;
            sign | ((new_exp + 1) << 23) | (m << 13)
        }
        31 => sign | 0x7f80_0000 | (frac << 13),
        _ => sign | ((exp + 127 - 15) << 23) | (frac << 13),
    };
    f32::from_bits(fbits)
}

#[inline]
fn smoothstep(edge0: f32, edge1: f32, x: f32) -> f32 {
    let t = ((x - edge0) / (edge1 - edge0)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

#[inline]
fn hash21(ix: i32, iy: i32) -> f32 {
    let mut n = (ix as u32)
        .wrapping_mul(374_761_393)
        .wrapping_add((iy as u32).wrapping_mul(668_265_263));
    n = (n ^ (n >> 13)).wrapping_mul(1_274_126_177);
    ((n ^ (n >> 16)) & 0x00ff_ffff) as f32 / 16_777_216.0
}

fn value_noise_2d(p: Vec2) -> f32 {
    let ix = p.x.floor() as i32;
    let iy = p.y.floor() as i32;
    let fx = p.x - ix as f32;
    let fy = p.y - iy as f32;
    let ux = fx * fx * (3.0 - 2.0 * fx);
    let uy = fy * fy * (3.0 - 2.0 * fy);
    let a = hash21(ix, iy);
    let b = hash21(ix + 1, iy);
    let c = hash21(ix, iy + 1);
    let d = hash21(ix + 1, iy + 1);
    let x0 = a + (b - a) * ux;
    let x1 = c + (d - c) * ux;
    x0 + (x1 - x0) * uy
}

fn fbm_clouds(p: Vec2) -> f32 {
    let mut sum = 0.0;
    let mut amp = 0.52;
    let mut freq = 1.0;
    for _ in 0..4 {
        sum += value_noise_2d(p * freq) * amp;
        freq *= 2.07;
        amp *= 0.48;
    }
    sum
}

/// Rectangular studio softbox emission with physically diffused edge falloff and subtle internal gradient.
fn softbox_panel(dir: Vec3, axis: Vec3, half_tan: Vec2, radiance: Vec3) -> Vec3 {
    let axis = axis.normalize();
    let d = dir.dot(axis);
    if d <= 0.05 {
        return Vec3::ZERO;
    }
    let ref_up = if axis.y.abs() < 0.94 { Vec3::Y } else { Vec3::Z };
    let right = ref_up.cross(axis).normalize();
    let up = axis.cross(right).normalize();
    let plane = dir / d;
    let px = plane.dot(right);
    let py = plane.dot(up);
    let edge_x = 1.0 - smoothstep(half_tan.x * 0.62, half_tan.x * 1.18, px.abs());
    let edge_y = 1.0 - smoothstep(half_tan.y * 0.62, half_tan.y * 1.18, py.abs());
    let falloff = (edge_x * edge_y) * smoothstep(0.05, 0.35, d);
    // Subtle hot center to edge diffuser falloff inside a real softbox.
    let rx = (px / half_tan.x).clamp(-1.0, 1.0);
    let ry = (py / half_tan.y).clamp(-1.0, 1.0);
    let diffuser = 1.0 - 0.24 * (rx * rx + ry * ry).min(1.0);
    radiance * falloff * diffuser
}

fn studio_panorama(dir: Vec3) -> Vec3 {
    let up = (dir.y * 0.5 + 0.5).clamp(0.0, 1.0);
    let floor_col = Vec3::new(0.115, 0.110, 0.106);
    let wall_col = Vec3::new(0.245, 0.252, 0.275);
    let ceiling_col = Vec3::new(0.39, 0.43, 0.50);
    let mut env = floor_col.lerp(ceiling_col, smoothstep(0.16, 0.86, up));
    let horizon_band = (-dir.y.abs() * 6.5).exp();
    env = env.lerp(wall_col * 1.25, horizon_band * 0.48);

    // Negative-fill dark flags give steel, brass, and gold realistic dark reflections.
    let flag_a = (1.0 - (dir.x * 1.5 - dir.z * 0.65).abs()).clamp(0.0, 1.0).powf(2.6)
        * (1.0 - dir.y.abs() * 1.05).clamp(0.0, 1.0);
    let flag_b = (1.0 - (dir.x * 0.65 + dir.z * 1.45).abs()).clamp(0.0, 1.0).powf(2.6)
        * (0.65 - dir.y).clamp(0.0, 1.0);
    let flag_mask = (flag_a + flag_b * 0.72).clamp(0.0, 1.0);
    env *= 1.0 - flag_mask * 0.76;

    // Realistic studio softboxes (broad diffusers, no artificial 14.0 pinpoint spike).
    env += softbox_panel(
        dir,
        Vec3::new(-0.45, 0.80, -0.55),
        Vec2::new(0.36, 0.26),
        Vec3::new(4.65, 4.42, 4.02),
    );
    env += softbox_panel(
        dir,
        Vec3::new(-0.06, 0.98, -0.18),
        Vec2::new(0.62, 0.16),
        Vec3::new(2.10, 2.15, 2.26),
    );
    env += softbox_panel(
        dir,
        Vec3::new(0.70, 0.26, 0.44),
        Vec2::new(0.45, 0.34),
        Vec3::new(1.12, 1.28, 1.58),
    );
    env += softbox_panel(
        dir,
        Vec3::new(0.22, 0.60, 0.76),
        Vec2::new(0.32, 0.20),
        Vec3::new(1.42, 1.26, 1.06),
    );
    env += softbox_panel(
        dir,
        Vec3::new(-0.35, -0.70, -0.52),
        Vec2::new(0.85, 0.55),
        Vec3::new(0.26, 0.23, 0.20),
    );
    env.max(Vec3::splat(0.02))
}

fn outdoor_panorama(dir: Vec3) -> Vec3 {
    let sun_dir = Vec3::new(-0.45, 0.80, -0.55).normalize();
    let azimuth = dir.z.atan2(dir.x);
    let ridge = 0.015
        + 0.032 * (azimuth * 3.0 + 0.6).sin().abs()
        + 0.016 * (azimuth * 7.0 - 1.1).cos()
        + 0.008 * (azimuth * 13.0 + 2.3).sin();

    // Earth & distant Pywel terrain bounce below the mountain ridge.
    let soil_var = fbm_clouds(Vec2::new(azimuth * 2.5, dir.y * 6.0));
    let ground_base = Vec3::new(0.18, 0.145, 0.11).lerp(Vec3::new(0.26, 0.21, 0.155), soil_var * 0.65);
    let mountain_haze = Vec3::new(0.42, 0.45, 0.50);
    let ridge_blend = smoothstep(ridge - 0.015, ridge + 0.015, dir.y);

    // Rayleigh / zenith-to-horizon atmosphere gradient.
    let sky_t = smoothstep(0.0, 0.78, dir.y.max(0.0));
    let zenith = Vec3::new(0.16, 0.36, 0.76);
    let horizon = Vec3::new(0.86, 0.80, 0.72);
    let mut sky = horizon.lerp(zenith, sky_t.powf(0.68));
    // Atmospheric forward scattering around solar azimuth.
    let sun_cos = dir.dot(sun_dir).clamp(-1.0, 1.0);
    let mie_glow = ((sun_cos * 0.5 + 0.5).powf(4.0)) * 0.42 + (sun_cos.max(0.0)).powf(24.0) * 1.15;
    sky += Vec3::new(1.0, 0.88, 0.70) * mie_glow;

    // Projected cloud deck plane for sky dome realism.
    if dir.y > 0.04 {
        let proj = Vec2::new(dir.x, dir.z) / (dir.y + 0.18);
        let density = smoothstep(0.46, 0.82, fbm_clouds(proj * 1.35 + Vec2::new(1.7, -0.9)));
        let horizon_fade = smoothstep(0.04, 0.24, dir.y);
        let sun_lit = (sun_cos * 0.5 + 0.5).clamp(0.2, 1.0);
        let cloud_col = Vec3::new(0.58, 0.64, 0.74).lerp(Vec3::new(1.42, 1.34, 1.22), sun_lit);
        sky = sky.lerp(cloud_col, density * horizon_fade * 0.72);
    }

    // Distant mountain silhouette band right along the horizon.
    let mountain_band = smoothstep(-0.08, ridge - 0.01, dir.y) * (1.0 - ridge_blend);
    let terrain = ground_base.lerp(mountain_haze, mountain_band * 0.75);
    let mut env = terrain.lerp(sky, ridge_blend);

    // Solar disk + aureole (kept within half-float headroom).
    let sun_angle = (1.0 - sun_cos.max(0.0)).max(0.0);
    let sun_disk = (-sun_angle * 1600.0).exp();
    let sun_aureole = (-sun_angle * 45.0).exp();
    env += Vec3::new(15.0, 13.4, 10.8) * sun_disk + Vec3::new(1.85, 1.55, 1.18) * sun_aureole;
    env.max(Vec3::splat(0.02))
}

#[inline]
fn texel_direction(u: f32, v: f32) -> Vec3 {
    let phi = (u - 0.5) * (2.0 * PI);
    let theta = v * PI;
    let sin_theta = theta.sin();
    Vec3::new(sin_theta * phi.cos(), theta.cos(), sin_theta * phi.sin())
}

#[inline]
fn sample_equirect_bilinear(base: &[Vec3], dir: Vec3) -> Vec3 {
    let u = (dir.z.atan2(dir.x) / (2.0 * PI) + 0.5).rem_euclid(1.0);
    let v = (dir.y.clamp(-1.0, 1.0).acos() / PI).clamp(0.0, 1.0);
    let fx = u * ENV_WIDTH as f32 - 0.5;
    let fy = (v * ENV_HEIGHT as f32 - 0.5).clamp(0.0, (ENV_HEIGHT - 1) as f32);
    let x0 = (fx.floor() as i32).rem_euclid(ENV_WIDTH as i32) as usize;
    let x1 = (x0 + 1) % ENV_WIDTH as usize;
    let y0 = (fy.floor() as usize).min(ENV_HEIGHT as usize - 1);
    let y1 = (y0 + 1).min(ENV_HEIGHT as usize - 1);
    let tx = fx - fx.floor();
    let ty = fy - fy.floor();
    let w = ENV_WIDTH as usize;
    let c00 = base[y0 * w + x0];
    let c10 = base[y0 * w + x1];
    let c01 = base[y1 * w + x0];
    let c11 = base[y1 * w + x1];
    let c0 = c00.lerp(c10, tx);
    let c1 = c01.lerp(c11, tx);
    c0.lerp(c1, ty)
}

#[inline]
fn radical_inverse_vdc(mut bits: u32) -> f32 {
    bits = bits.rotate_right(16);
    bits = ((bits & 0x5555_5555) << 1) | ((bits & 0xAAAA_AAAA) >> 1);
    bits = ((bits & 0x3333_3333) << 2) | ((bits & 0xCCCC_CCCC) >> 2);
    bits = ((bits & 0x0F0F_0F0F) << 4) | ((bits & 0xF0F0_F0F0) >> 4);
    bits = ((bits & 0x00FF_00FF) << 8) | ((bits & 0xFF00_FF00) >> 8);
    bits as f32 * 2.328_306_4e-10
}

fn importance_sample_ggx(xi: Vec2, n: Vec3, roughness: f32) -> Vec3 {
    let a = roughness * roughness;
    let phi = 2.0 * PI * xi.x;
    let cos_theta = ((1.0 - xi.y) / (1.0 + (a * a - 1.0) * xi.y).max(1e-6))
        .clamp(0.0, 1.0)
        .sqrt();
    let sin_theta = (1.0 - cos_theta * cos_theta).max(0.0).sqrt();
    let h_tangent = Vec3::new(phi.cos() * sin_theta, phi.sin() * sin_theta, cos_theta);
    let up = if n.y.abs() < 0.999 { Vec3::Y } else { Vec3::X };
    let tangent = up.cross(n).normalize();
    let bitangent = n.cross(tangent);
    (tangent * h_tangent.x + bitangent * h_tangent.y + n * h_tangent.z).normalize()
}

fn sh_basis(n: Vec3) -> [f32; 9] {
    [
        0.28209479,
        0.48860251 * n.y,
        0.48860251 * n.z,
        0.48860251 * n.x,
        1.09254843 * n.x * n.y,
        1.09254843 * n.y * n.z,
        0.31539157 * (3.0 * n.z * n.z - 1.0),
        1.09254843 * n.x * n.z,
        0.54627422 * (n.x * n.x - n.y * n.y),
    ]
}

fn integrate_irradiance_sh(base: &[Vec3]) -> [[f32; 4]; 9] {
    // Lambertian cosine kernel A_l / pi: A0/pi = 1.0, A1/pi = 2/3, A2/pi = 1/4.
    const KERNEL: [f32; 9] = [
        1.0,
        2.0 / 3.0,
        2.0 / 3.0,
        2.0 / 3.0,
        0.25,
        0.25,
        0.25,
        0.25,
        0.25,
    ];
    let mut accum = [Vec3::ZERO; 9];
    let d_phi = (2.0 * PI) / ENV_WIDTH as f32;
    let d_theta = PI / ENV_HEIGHT as f32;
    for y in 0..ENV_HEIGHT {
        let v = (y as f32 + 0.5) / ENV_HEIGHT as f32;
        let theta = v * PI;
        let weight = d_phi * d_theta * theta.sin();
        for x in 0..ENV_WIDTH {
            let u = (x as f32 + 0.5) / ENV_WIDTH as f32;
            let dir = texel_direction(u, v);
            let col = base[(y * ENV_WIDTH + x) as usize] * weight;
            let basis = sh_basis(dir);
            for (slot, b) in accum.iter_mut().zip(basis) {
                *slot += col * b;
            }
        }
    }
    let mut out = [[0.0_f32; 4]; 9];
    for i in 0..9 {
        let scaled = accum[i] * KERNEL[i];
        out[i] = [scaled.x, scaled.y, scaled.z, 0.0];
    }
    out
}

fn pack_rgba16f(texels: &[Vec3]) -> Vec<u16> {
    let mut packed = Vec::with_capacity(texels.len() * 4);
    for col in texels {
        packed.push(f32_to_f16(col.x));
        packed.push(f32_to_f16(col.y));
        packed.push(f32_to_f16(col.z));
        packed.push(0x3C00); // 1.0 in f16
    }
    packed
}

fn build_layer_mips_and_sh(generator: fn(Vec3) -> Vec3) -> ([Vec<u16>; ENV_MIP_COUNT as usize], [[f32; 4]; 9]) {
    let mut base = Vec::with_capacity((ENV_WIDTH * ENV_HEIGHT) as usize);
    for y in 0..ENV_HEIGHT {
        let v = (y as f32 + 0.5) / ENV_HEIGHT as f32;
        for x in 0..ENV_WIDTH {
            let u = (x as f32 + 0.5) / ENV_WIDTH as f32;
            base.push(generator(texel_direction(u, v)));
        }
    }
    let sh = integrate_irradiance_sh(&base);
    let mut mips: [Vec<u16>; ENV_MIP_COUNT as usize] = std::array::from_fn(|_| Vec::new());
    mips[0] = pack_rgba16f(&base);

    const SAMPLES: u32 = 40;
    for mip in 1..ENV_MIP_COUNT {
        let mip_w = (ENV_WIDTH >> mip).max(1);
        let mip_h = (ENV_HEIGHT >> mip).max(1);
        let roughness = (mip as f32 / (ENV_MIP_COUNT - 1) as f32).clamp(0.05, 1.0);
        let mut level = Vec::with_capacity((mip_w * mip_h) as usize);
        for y in 0..mip_h {
            let v = (y as f32 + 0.5) / mip_h as f32;
            for x in 0..mip_w {
                let u = (x as f32 + 0.5) / mip_w as f32;
                let n = texel_direction(u, v);
                let r = n;
                let view = r;
                let mut total_col = Vec3::ZERO;
                let mut total_w = 0.0_f32;
                for s in 0..SAMPLES {
                    let xi = Vec2::new(s as f32 / SAMPLES as f32, radical_inverse_vdc(s));
                    let h = importance_sample_ggx(xi, n, roughness);
                    let l = (2.0 * view.dot(h) * h - view).normalize();
                    let ndotl = n.dot(l).max(0.0);
                    if ndotl > 0.0 {
                        total_col += sample_equirect_bilinear(&base, l) * ndotl;
                        total_w += ndotl;
                    }
                }
                let filtered = if total_w > 1e-5 {
                    total_col / total_w
                } else {
                    sample_equirect_bilinear(&base, r)
                };
                level.push(filtered);
            }
        }
        mips[mip as usize] = pack_rgba16f(&level);
    }
    (mips, sh)
}

fn build_prefiltered_env_data() -> PrefilteredEnvData {
    let (studio_mips, sh_studio) = build_layer_mips_and_sh(studio_panorama);
    let (outdoor_mips, sh_outdoor) = build_layer_mips_and_sh(outdoor_panorama);
    PrefilteredEnvData {
        mips_f16: [studio_mips, outdoor_mips],
        sh_studio,
        sh_outdoor,
    }
}

#[cfg(test)]
pub(super) fn evaluate_sh_irradiance(sh: &[[f32; 4]; 9], normal: Vec3) -> Vec3 {
    let basis = sh_basis(normal.normalize());
    let mut sum = Vec3::ZERO;
    for i in 0..9 {
        sum += Vec3::new(sh[i][0], sh[i][1], sh[i][2]) * basis[i];
    }
    sum.max(Vec3::ZERO)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn f16_roundtrip_is_finite_and_bounded() {
        assert_eq!(f32_to_f16(-1.0), 0);
        assert_eq!(f32_to_f16(f32::NAN), 0);
        let one = f16_to_f32(f32_to_f16(1.0));
        assert!((one - 1.0).abs() < 1e-3);
        let bright = f16_to_f32(f32_to_f16(16.5));
        assert!((bright - 16.5).abs() < 0.05);
    }

    #[test]
    fn prefiltered_hdri_and_sh_are_finite_and_energy_consistent() {
        let data = cached_env_data();
        for layer in 0..ENV_LAYERS as usize {
            for mip in 0..ENV_MIP_COUNT as usize {
                let expected_len =
                    ((ENV_WIDTH >> mip).max(1) * (ENV_HEIGHT >> mip).max(1) * 4) as usize;
                assert_eq!(data.mips_f16[layer][mip].len(), expected_len);
                assert!(
                    data.mips_f16[layer][mip]
                        .iter()
                        .all(|bits| f16_to_f32(*bits).is_finite())
                );
            }
        }
        for sh in [&data.sh_studio, &data.sh_outdoor] {
            for dir in [Vec3::Y, -Vec3::Y, Vec3::X, -Vec3::Z] {
                let irr = evaluate_sh_irradiance(sh, dir);
                assert!(irr.is_finite() && irr.min_element() > 0.05 && irr.max_element() < 4.0);
            }
        }
        let sky_irr = evaluate_sh_irradiance(&data.sh_outdoor, Vec3::Y);
        let ground_irr = evaluate_sh_irradiance(&data.sh_outdoor, -Vec3::Y);
        assert!(sky_irr.y > ground_irr.y, "outdoor sky brighter than ground");
        assert!(sky_irr.z > ground_irr.z, "outdoor sky bluer than ground");
    }

    #[test]
    fn rotation_preserves_zero_and_rotates_around_y() {
        let look = StudioLookSettings::default();
        assert_eq!(look.look_uniform(), [0.0, 1.0, 0.0, 1.0]);
        let key = Vec3::new(-0.45, 0.80, -0.55).normalize();
        assert!(look.rotate_world_direction(key).abs_diff_eq(key, 1e-6));
        let quarter = StudioLookSettings {
            env_rotation_degrees: 90.0,
            ..Default::default()
        };
        let rotated = quarter.rotate_world_direction(Vec3::Z);
        assert!(rotated.abs_diff_eq(Vec3::X, 1e-5));
    }
}
