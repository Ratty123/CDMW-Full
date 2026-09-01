#![forbid(unsafe_code)]

use bytemuck::{Pod, Zeroable};
use cdmw_mesh::DrawSnapshot;
use cdmw_texture::{ColorSpace, DdsFormat, TextureRole, plan_2d_upload};
use glam::{Mat4, Quat, Vec2, Vec3};
use std::collections::{BTreeMap, HashSet, hash_map::DefaultHasher};
use std::hash::{Hash, Hasher};
use std::path::Path;
use std::sync::Arc;
use thiserror::Error;
use wgpu::util::DeviceExt;
use winit::dpi::PhysicalSize;
use winit::window::Window;

const SHADER: &str = r#"
struct CameraUniform {
    view_projection: mat4x4<f32>,
    view_mode: u32,
    output_is_srgb: u32,
    _padding_1: u32,
    _padding_2: u32,
    wire_colour: vec4<f32>,
    point_colour: vec4<f32>,
    view_direction: vec4<f32>,
};

struct VertexOut {
    @builtin(position) position: vec4<f32>,
    @location(0) color: vec3<f32>,
    @location(1) uv: vec2<f32>,
    @location(2) normal: vec3<f32>,
    @location(3) tangent: vec4<f32>,
    @location(4) @interpolate(flat) part_id: u32,
    @location(5) deformation: vec4<f32>,
};

struct MaterialUniform {
    flags: u32,
    skin_detail_scale: f32,
    skin_detail_opacity: f32,
    _padding_0: u32,
    emissive_color_and_intensity: vec4<f32>,
    surface_factors: vec4<f32>,
    relief_factors: vec4<f32>,
    texture_tint_and_strength: vec4<f32>,
};

@group(0) @binding(0) var base_texture: texture_2d<f32>;
@group(0) @binding(1) var normal_texture: texture_2d<f32>;
@group(0) @binding(2) var material_texture: texture_2d<f32>;
@group(0) @binding(3) var roughness_texture: texture_2d<f32>;
@group(0) @binding(4) var metalness_texture: texture_2d<f32>;
@group(0) @binding(5) var occlusion_texture: texture_2d<f32>;
@group(0) @binding(6) var emissive_texture: texture_2d<f32>;
@group(0) @binding(7) var material_sampler: sampler;
@group(0) @binding(8) var<uniform> material: MaterialUniform;
@group(0) @binding(9) var specular_texture: texture_2d<f32>;
@group(0) @binding(10) var opacity_texture: texture_2d<f32>;
@group(0) @binding(11) var height_texture: texture_2d<f32>;
@group(0) @binding(12) var flow_texture: texture_2d<f32>;
@group(0) @binding(13) var layer_mask_texture: texture_2d<f32>;
@group(0) @binding(14) var skin_detail_mask_texture: texture_2d<f32>;
@group(0) @binding(15) var skin_detail_normal_texture: texture_2d<f32>;
@group(0) @binding(16) var skin_detail_material_texture: texture_2d<f32>;
@group(0) @binding(17) var glossiness_texture: texture_2d<f32>;
@group(1) @binding(0) var<uniform> camera: CameraUniform;

const MATERIAL_BASE_COLOR: u32 = 1u;
const MATERIAL_NORMAL: u32 = 2u;
const MATERIAL_SURFACE: u32 = 4u;
const MATERIAL_ROUGHNESS: u32 = 8u;
const MATERIAL_METALNESS: u32 = 16u;
const MATERIAL_OCCLUSION: u32 = 32u;
const MATERIAL_EMISSIVE: u32 = 64u;
const MATERIAL_ROUGHNESS_FACTOR: u32 = 128u;
const MATERIAL_METALNESS_FACTOR: u32 = 256u;
const MATERIAL_SPECULAR_FACTOR: u32 = 512u;
const MATERIAL_SPECULAR: u32 = 1024u;
const MATERIAL_OPACITY: u32 = 2048u;
const MATERIAL_ALPHA_CUTOUT: u32 = 4096u;
const MATERIAL_HEIGHT: u32 = 8192u;
const MATERIAL_HAIR_FLOW: u32 = 16384u;
const MATERIAL_LAYER_MASK: u32 = 32768u;
const MATERIAL_NORMAL_Y_INVERTED: u32 = 65536u;
const MATERIAL_CATEGORY: u32 = 131072u;
const MATERIAL_EMISSIVE_INTENSITY_MASK: u32 = 262144u;
const MATERIAL_SKIN_DETAIL_MASK: u32 = 524288u;
const MATERIAL_SKIN_DETAIL_NORMAL: u32 = 1048576u;
const MATERIAL_SKIN_DETAIL_MATERIAL: u32 = 2097152u;
const MATERIAL_GLOSSINESS: u32 = 4194304u;
const MATERIAL_TEXTURE_TINT: u32 = 8388608u;
const MATERIAL_MIP_LOD_BIAS: f32 = -2.0;

fn make_vertex_out(
    position: vec3<f32>,
    normal: vec3<f32>,
    uv: vec2<f32>,
    tangent: vec4<f32>,
    deformation: vec4<f32>,
    instance_index: u32,
) -> VertexOut {
    var out: VertexOut;
    out.position = camera.view_projection * vec4<f32>(position, 1.0);
    out.color = normal * 0.35 + vec3<f32>(0.55, 0.58, 0.65);
    out.uv = uv;
    out.normal = normal;
    out.tangent = tangent;
    out.part_id = instance_index;
    out.deformation = deformation;
    return out;
}

@vertex
fn vs_main(
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) tangent: vec4<f32>,
    @location(4) deformation: vec4<f32>,
    @builtin(instance_index) instance_index: u32,
) -> VertexOut {
    return make_vertex_out(position, normal, uv, tangent, deformation, instance_index);
}

fn safe_normalize(value: vec3<f32>, fallback: vec3<f32>) -> vec3<f32> {
    let length_squared = dot(value, value);
    return select(fallback, value * inverseSqrt(max(length_squared, 1e-8)), length_squared > 1e-8);
}

fn facing_normal(normal: vec3<f32>, front_facing: bool) -> vec3<f32> {
    let resolved = safe_normalize(normal, vec3<f32>(0.0, 1.0, 0.0));
    return select(-resolved, resolved, front_facing);
}

fn linear_to_srgb(value: vec3<f32>) -> vec3<f32> {
    let bounded = max(value, vec3<f32>(0.0));
    let lower = bounded * 12.92;
    let upper = 1.055 * pow(bounded, vec3<f32>(1.0 / 2.4)) - vec3<f32>(0.055);
    return select(upper, lower, bounded <= vec3<f32>(0.0031308));
}

fn srgb_to_linear(value: vec3<f32>) -> vec3<f32> {
    let bounded = clamp(value, vec3<f32>(0.0), vec3<f32>(1.0));
    let lower = bounded / 12.92;
    let upper = pow((bounded + vec3<f32>(0.055)) / 1.055, vec3<f32>(2.4));
    return select(upper, lower, bounded <= vec3<f32>(0.04045));
}

fn linear_to_srgb_scalar(value: f32) -> f32 {
    let bounded = max(value, 0.0);
    return select(1.055 * pow(bounded, 1.0 / 2.4) - 0.055, bounded * 12.92, bounded <= 0.0031308);
}

fn srgb_to_linear_scalar(value: f32) -> f32 {
    let bounded = clamp(value, 0.0, 1.0);
    return select(pow((bounded + 0.055) / 1.055, 2.4), bounded / 12.92, bounded <= 0.04045);
}

fn present(linear_rgb: vec3<f32>, alpha: f32) -> vec4<f32> {
    let bounded = max(linear_rgb, vec3<f32>(0.0));
    let rgb = select(linear_to_srgb(bounded), bounded, camera.output_is_srgb != 0u);
    return vec4<f32>(clamp(rgb, vec3<f32>(0.0), vec3<f32>(1.0)), alpha);
}

fn present_srgb(display_rgb: vec3<f32>, alpha: f32) -> vec4<f32> {
    return present(srgb_to_linear(display_rgb), alpha);
}

fn aces_tone_map(value: f32) -> f32 {
    let x = max(value, 0.0);
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

fn workbench_tone(color: vec3<f32>, exposure: f32) -> vec3<f32> {
    let exposed = max(color * max(exposure, 0.05), vec3<f32>(0.0));
    let exposed_luma = dot(exposed, vec3<f32>(0.2126, 0.7152, 0.0722));
    let mapped_luma = aces_tone_map(exposed_luma);
    var mapped = exposed * (mapped_luma / max(exposed_luma, 1e-5));
    let current_luma = dot(mapped, vec3<f32>(0.2126, 0.7152, 0.0722));
    let display_luma = linear_to_srgb_scalar(current_luma);
    var contrasted_display = clamp((display_luma - 0.5) * 1.08 + 0.5, 0.0, 1.0);
    contrasted_display = pow(contrasted_display, 0.92);
    let contrasted_luma = srgb_to_linear_scalar(contrasted_display);
    mapped *= contrasted_luma / max(current_luma, 1e-5);
    return clamp(mapped, vec3<f32>(0.0), vec3<f32>(1.0));
}

fn wrapped_ndotl(normal: vec3<f32>, light_direction: vec3<f32>, wrap: f32) -> f32 {
    let safe_wrap = max(wrap, 0.0);
    return clamp((dot(normal, light_direction) + safe_wrap) / (1.0 + safe_wrap), 0.0, 1.0);
}

fn studio_softbox_lobe(
    direction: vec3<f32>,
    softbox_direction: vec3<f32>,
    sharpness: f32,
    roughness: f32,
) -> f32 {
    let safe_roughness = clamp(roughness, 0.0, 1.0);
    let roughness_squared = safe_roughness * safe_roughness;
    let filtered_sharpness = mix(max(sharpness, 1.0), 1.35, roughness_squared);
    let filtered_peak = mix(1.0, 0.22, roughness_squared);
    return pow(
        clamp(dot(direction, normalize(softbox_direction)), 0.0, 1.0),
        filtered_sharpness,
    ) * filtered_peak;
}

fn preview_environment_radiance(reflected_view: vec3<f32>, roughness: f32) -> vec3<f32> {
    let safe_roughness = clamp(roughness, 0.0, 1.0);
    let roughness_squared = safe_roughness * safe_roughness;
    let horizon_band = pow(clamp(1.0 - abs(reflected_view.y) * 1.12, 0.0, 1.0), 2.2);
    let front_softbox = studio_softbox_lobe(
        reflected_view, vec3<f32>(-0.24, 0.28, -0.93), 34.0, safe_roughness);
    let back_softbox = studio_softbox_lobe(
        reflected_view, vec3<f32>(0.42, 0.22, 0.88), 28.0, safe_roughness);
    let top_softbox = studio_softbox_lobe(
        reflected_view, vec3<f32>(-0.12, 0.96, -0.25), 38.0, safe_roughness);
    let side_softbox = studio_softbox_lobe(
        reflected_view, vec3<f32>(0.92, 0.12, -0.38), 26.0, safe_roughness);
    let opposite_side_softbox = studio_softbox_lobe(
        reflected_view, vec3<f32>(-0.88, 0.16, -0.44), 30.0, safe_roughness);
    let dark_band = pow(
        clamp(1.0 - abs(reflected_view.x * 1.35 + reflected_view.y * 0.45), 0.0, 1.0),
        3.2,
    ) * clamp(0.95 - reflected_view.z, 0.0, 1.0);

    // Match the live Vortice workbench: compose the directional studio at high
    // precision, then compress every channel by the same peak-derived factor.
    // That keeps the warm/cool lobe ratios without turning pale source colour
    // into an exposure-like white reflection.
    var radiance = vec3<f32>(0.070, 0.065, 0.060);
    radiance += horizon_band * vec3<f32>(0.55, 0.46, 0.38);
    radiance += front_softbox * vec3<f32>(7.50, 6.20, 4.60);
    radiance += back_softbox * vec3<f32>(3.20, 2.35, 1.55);
    radiance += top_softbox * vec3<f32>(4.60, 4.30, 3.80);
    radiance += side_softbox * vec3<f32>(3.00, 2.65, 2.20);
    radiance += opposite_side_softbox * vec3<f32>(0.55, 0.65, 0.82);
    radiance *= mix(1.0, 0.16, dark_band * mix(0.96, 0.38, safe_roughness));
    radiance = mix(radiance, vec3<f32>(0.32, 0.28, 0.24), roughness_squared * 0.34);
    let radiance_peak = max(radiance.r, max(radiance.g, radiance.b));
    radiance = radiance / (1.0 + radiance_peak);
    return max(radiance, vec3<f32>(0.010, 0.010, 0.012));
}

fn preview_environment_irradiance(normal: vec3<f32>) -> vec3<f32> {
    let safe_normal = safe_normalize(normal, vec3<f32>(0.0, 1.0, 0.0));
    let sky_amount = clamp(safe_normal.y * 0.5 + 0.5, 0.0, 1.0);
    let ground_amount = 1.0 - sky_amount;
    let front_wrap = pow(clamp(
        dot(safe_normal, normalize(vec3<f32>(-0.24, 0.28, -0.93))) * 0.5 + 0.5,
        0.0,
        1.0,
    ), 2.0);
    let side_wrap = pow(clamp(
        dot(safe_normal, normalize(vec3<f32>(0.92, 0.12, -0.38))) * 0.5 + 0.5,
        0.0,
        1.0,
    ), 2.4);
    var irradiance = vec3<f32>(0.055, 0.060, 0.072);
    irradiance += sky_amount * vec3<f32>(0.18, 0.23, 0.34);
    irradiance += ground_amount * vec3<f32>(0.075, 0.060, 0.048);
    irradiance += front_wrap * vec3<f32>(0.38, 0.31, 0.23);
    irradiance += side_wrap * vec3<f32>(0.08, 0.13, 0.24);
    return irradiance;
}

fn environment_brdf_approx(
    reflectance_at_normal: vec3<f32>,
    roughness: f32,
    ndotv: f32,
) -> vec3<f32> {
    let c0 = vec4<f32>(-1.0, -0.0275, -0.572, 0.022);
    let c1 = vec4<f32>(1.0, 0.0425, 1.04, -0.04);
    let fit = clamp(roughness, 0.0, 1.0) * c0 + c1;
    let a004 = min(fit.x * fit.x, exp2(-9.28 * clamp(ndotv, 0.0, 1.0))) * fit.x + fit.y;
    let scale_bias = vec2<f32>(-1.04, 1.04) * a004 + fit.zw;
    return clamp(
        reflectance_at_normal * scale_bias.x + vec3<f32>(scale_bias.y),
        vec3<f32>(0.0),
        vec3<f32>(1.0),
    );
}

fn distribution_ggx(normal: vec3<f32>, half_vector: vec3<f32>, roughness: f32) -> f32 {
    let alpha = roughness * roughness;
    let alpha_squared = alpha * alpha;
    let ndoth = clamp(dot(normal, half_vector), 0.0, 1.0);
    let denominator = ndoth * ndoth * (alpha_squared - 1.0) + 1.0;
    return alpha_squared / max(3.14159265359 * denominator * denominator, 1e-5);
}

fn geometry_schlick_ggx(ndot_direction: f32, roughness: f32) -> f32 {
    let remapped = roughness + 1.0;
    let k = remapped * remapped / 8.0;
    return ndot_direction / max(ndot_direction * (1.0 - k) + k, 1e-5);
}

fn geometry_smith(
    normal: vec3<f32>,
    view_direction: vec3<f32>,
    light_direction: vec3<f32>,
    roughness: f32,
) -> f32 {
    return geometry_schlick_ggx(clamp(dot(normal, view_direction), 0.0, 1.0), roughness)
        * geometry_schlick_ggx(clamp(dot(normal, light_direction), 0.0, 1.0), roughness);
}

fn fresnel_schlick(cos_theta: f32, reflectance_at_normal: vec3<f32>) -> vec3<f32> {
    return reflectance_at_normal
        + (vec3<f32>(1.0) - reflectance_at_normal)
            * pow(1.0 - clamp(cos_theta, 0.0, 1.0), 5.0);
}

fn neutral_surface(normal: vec3<f32>, front_facing: bool) -> vec3<f32> {
    let normal_length_squared = dot(normal, normal);
    let normalized = normal * inverseSqrt(max(normal_length_squared, 1e-8));
    var surface_normal = select(vec3<f32>(0.0, 1.0, 0.0), normalized, normal_length_squared > 1e-8);
    surface_normal = select(-surface_normal, surface_normal, front_facing);
    let view_direction = safe_normalize(camera.view_direction.xyz, vec3<f32>(0.0, 0.0, -1.0));
    var camera_right = safe_normalize(cross(view_direction, vec3<f32>(0.0, 1.0, 0.0)), vec3<f32>(1.0, 0.0, 0.0));
    let camera_up = safe_normalize(cross(camera_right, view_direction), vec3<f32>(0.0, 1.0, 0.0));
    let key_light = safe_normalize(view_direction - camera_right * 0.18 + camera_up * 0.35, view_direction);
    let fill_light = safe_normalize(view_direction + camera_right * 0.35 + camera_up * 0.45, view_direction);
    let shade = 0.38
        + 0.52 * max(dot(surface_normal, key_light), 0.0)
        + 0.10 * max(dot(surface_normal, fill_light), 0.0);
    return vec3<f32>(0.56, 0.58, 0.62) * shade;
}

@fragment
fn fs_solid(input: VertexOut, @builtin(front_facing) front_facing: bool) -> @location(0) vec4<f32> {
    if input.deformation.a > 0.0001 {
        let overlay_amount = clamp(input.deformation.a, 0.0, 0.88);
        return present(
            mix(neutral_surface(input.normal, front_facing), input.deformation.rgb, overlay_amount),
            1.0);
    }
    if camera.view_mode == 1u {
        return present(neutral_surface(input.normal, front_facing), 1.0);
    }
    if camera.view_mode == 4u {
        let checker = (u32(floor(input.uv.x * 16.0)) + u32(floor(input.uv.y * 16.0))) & 1u;
        let value = select(0.08, 0.88, checker != 0u);
        return present_srgb(vec3<f32>(value), 1.0);
    }
    if material.flags == 0u {
        if camera.view_mode == 8u {
            let part_id = f32(input.part_id) + 1.0;
            return present_srgb(fract(part_id * vec3<f32>(0.6180339, 0.3819660, 0.7548777)), 1.0);
        }
        return present(neutral_surface(input.normal, front_facing), 1.0);
    }

    var texel = textureSampleBias(base_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS);
    if (material.flags & MATERIAL_TEXTURE_TINT) != 0u {
        let texture_tint = max(
            material.texture_tint_and_strength.rgb,
            vec3<f32>(0.0));
        let tint_strength = clamp(material.texture_tint_and_strength.w, 0.0, 1.0);
        if tint_strength <= 0.001 {
            // A zero base-tint strength is the imported glTF baseColorFactor
            // contract: multiply the sampled texture exactly.
            texel = vec4<f32>(
                clamp(texel.rgb * texture_tint, vec3<f32>(0.0), vec3<f32>(1.0)),
                texel.a);
        } else if min(u32(material.relief_factors.z + 0.5), 11u) == 6u {
            // PAC hair dye is authored in display-space colour. Decode it before
            // deriving the hue bias so a neutral hair tile keeps its value and
            // gains the authored warmth instead of collapsing toward grey.
            let linear_tint = srgb_to_linear(texture_tint);
            let tint_luma = max(
                dot(linear_tint, vec3<f32>(0.299, 0.587, 0.114)),
                0.08);
            let tint_bias = clamp(
                linear_tint / tint_luma,
                vec3<f32>(0.38),
                vec3<f32>(1.72));
            let dyed = clamp(
                texel.rgb * tint_bias,
                vec3<f32>(0.0),
                vec3<f32>(1.0));
            texel = vec4<f32>(mix(texel.rgb, dyed, tint_strength), texel.a);
        } else {
            // Equipment archive colours use a luma-normalised hue shift. This
            // keeps their source detail and brightness in the sampled GPU path
            // instead of baking replacement pixels.
            let tint_luma = max(
                dot(texture_tint, vec3<f32>(0.299, 0.587, 0.114)),
                0.08);
            let tint_bias = clamp(
                texture_tint / tint_luma,
                vec3<f32>(0.38),
                vec3<f32>(1.72));
            let tinted = clamp(
                texel.rgb * tint_bias,
                vec3<f32>(0.0),
                vec3<f32>(1.0));
            texel = vec4<f32>(mix(texel.rgb, tinted, tint_strength), texel.a);
        }
    }
    var material_alpha = texel.a;
    if (material.flags & MATERIAL_OPACITY) != 0u {
        material_alpha = textureSampleBias(opacity_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS).r;
    }
    if (material.flags & MATERIAL_ALPHA_CUTOUT) != 0u {
        if material_alpha < material.surface_factors.w {
            discard;
        }
    }
    if camera.view_mode == 8u {
        let part_id = f32(input.part_id) + 1.0;
        return present_srgb(fract(part_id * vec3<f32>(0.6180339, 0.3819660, 0.7548777)), 1.0);
    }
    if camera.view_mode == 2u {
        return present(texel.rgb, 1.0);
    }
    if camera.view_mode == 5u {
        return present_srgb(vec3<f32>(material_alpha), 1.0);
    }
    if camera.view_mode == 7u {
        var layer_mask = texel.a;
        if (material.flags & MATERIAL_LAYER_MASK) != 0u {
            let mask = textureSampleBias(layer_mask_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS);
            layer_mask = mask[min(u32(material.relief_factors.y), 3u)];
        }
        return present_srgb(vec3<f32>(layer_mask), 1.0);
    }
    let geometry_normal = facing_normal(input.normal, front_facing);
    let tangent = normalize(input.tangent.xyz - geometry_normal * dot(geometry_normal, input.tangent.xyz));
    let bitangent = normalize(cross(geometry_normal, tangent)) * input.tangent.w;
    var tangent_normal = vec3<f32>(0.0, 0.0, 1.0);
    if (material.flags & MATERIAL_NORMAL) != 0u {
        var tangent_xy = textureSampleBias(normal_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS).xy * 2.0 - vec2<f32>(1.0);
        if (material.flags & MATERIAL_NORMAL_Y_INVERTED) != 0u {
            tangent_xy.y = -tangent_xy.y;
        }
        let tangent_z = sqrt(max(1.0 - dot(tangent_xy, tangent_xy), 0.0));
        tangent_normal = normalize(vec3<f32>(tangent_xy, tangent_z));
    }
    var skin_detail_weight = 0.0;
    if (material.flags & MATERIAL_SKIN_DETAIL_MASK) != 0u {
        skin_detail_weight = clamp(
            textureSampleBias(
                skin_detail_mask_texture,
                material_sampler,
                input.uv,
                MATERIAL_MIP_LOD_BIAS).r * material.skin_detail_opacity,
            0.0,
            1.0);
    }
    let skin_detail_uv = input.uv / max(material.skin_detail_scale, 0.001);
    if (material.flags & MATERIAL_SKIN_DETAIL_NORMAL) != 0u && skin_detail_weight > 0.0001 {
        var detail_xy = textureSampleBias(
            skin_detail_normal_texture,
            material_sampler,
            skin_detail_uv,
            MATERIAL_MIP_LOD_BIAS).xy * 2.0 - vec2<f32>(1.0);
        if (material.flags & MATERIAL_NORMAL_Y_INVERTED) != 0u {
            detail_xy.y = -detail_xy.y;
        }
        let detail_z = sqrt(max(1.0 - dot(detail_xy, detail_xy), 0.0));
        let detail_normal = normalize(vec3<f32>(detail_xy, detail_z));
        let whiteout = normalize(vec3<f32>(
            tangent_normal.xy + detail_normal.xy,
            tangent_normal.z * detail_normal.z));
        tangent_normal = normalize(mix(tangent_normal, whiteout, skin_detail_weight));
    }
    var surface_normal = normalize(
        tangent * tangent_normal.x
        + bitangent * tangent_normal.y
        + geometry_normal * tangent_normal.z);
    var height_value = 0.5;
    if (material.flags & MATERIAL_HEIGHT) != 0u {
        height_value = textureSampleBias(height_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS).r;
        var height_uv_x = dpdx(input.uv);
        var height_uv_y = dpdy(input.uv);
        if dot(height_uv_x, height_uv_x) < 1e-8 {
            height_uv_x = vec2<f32>(1.0 / 1024.0, 0.0);
        }
        if dot(height_uv_y, height_uv_y) < 1e-8 {
            height_uv_y = vec2<f32>(0.0, 1.0 / 1024.0);
        }
        let height_x = textureSampleBias(height_texture, material_sampler, input.uv + height_uv_x, MATERIAL_MIP_LOD_BIAS).r
            - textureSampleBias(height_texture, material_sampler, input.uv - height_uv_x, MATERIAL_MIP_LOD_BIAS).r;
        let height_y = textureSampleBias(height_texture, material_sampler, input.uv + height_uv_y, MATERIAL_MIP_LOD_BIAS).r
            - textureSampleBias(height_texture, material_sampler, input.uv - height_uv_y, MATERIAL_MIP_LOD_BIAS).r;
        let height_normal = normalize(
            surface_normal - tangent * height_x * 2.4 + bitangent * height_y * 2.4);
        surface_normal = normalize(mix(
            surface_normal,
            height_normal,
            clamp(material.relief_factors.x, 0.0, 1.0)));
    }
    if camera.view_mode == 3u {
        return present_srgb(surface_normal * 0.5 + vec3<f32>(0.5), 1.0);
    }

    let category_code = min(u32(material.relief_factors.z + 0.5), 11u);
    let category_confidence = clamp(material.relief_factors.w, 0.0, 1.0);
    let is_metal = category_code == 1u;
    let is_leather = category_code == 2u;
    let is_wood = category_code == 3u;
    let is_cloth = category_code == 4u;
    let is_skin = category_code == 5u;
    let is_hair = category_code == 6u;
    let is_glass = category_code == 7u;
    let is_gem = category_code == 8u;
    let is_stone = category_code == 9u;
    let is_eye = category_code == 10u;
    let is_tooth = category_code == 11u;
    let is_glossy = is_glass || is_gem || is_eye;
    let has_skin_specular_response =
        is_skin && (material.flags & MATERIAL_SPECULAR) != 0u;
    let has_authoritative_roughness =
        (material.flags & (MATERIAL_SURFACE | MATERIAL_ROUGHNESS)) != 0u
        || has_skin_specular_response;
    let has_source_glossiness =
        (material.flags & MATERIAL_GLOSSINESS) != 0u
        && !has_authoritative_roughness;
    let has_source_roughness =
        has_authoritative_roughness || has_source_glossiness;
    let has_source_metalness =
        (material.flags & (MATERIAL_SURFACE | MATERIAL_METALNESS)) != 0u;
    let has_source_base_color = (material.flags & MATERIAL_BASE_COLOR) != 0u;

    var roughness = 0.66;
    var metalness = 0.0;
    var skin_subsurface_multiplier = 1.0;
    if (material.flags & MATERIAL_SURFACE) != 0u {
        let packed = textureSampleBias(material_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS);
        roughness = clamp(packed.g, 0.04, 1.0);
        metalness = clamp(packed.b, 0.0, 1.0);
    }
    if (material.flags & MATERIAL_ROUGHNESS) != 0u {
        roughness = clamp(textureSampleBias(roughness_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS).r, 0.04, 1.0);
    }
    if (material.flags & MATERIAL_METALNESS) != 0u {
        metalness = clamp(textureSampleBias(metalness_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS).r, 0.0, 1.0);
    }
    if has_skin_specular_response {
        let skin_specular_response = textureSampleBias(
            specular_texture,
            material_sampler,
            input.uv,
            MATERIAL_MIP_LOD_BIAS).rgb;
        // SkinnedMeshSkin packs subsurface response in R and direct roughness
        // in G. B is deliberately ignored: unlike equipment `_sp`, it is not
        // a metalness channel for this shader family.
        skin_subsurface_multiplier = mix(
            0.65,
            1.10,
            clamp(skin_specular_response.r, 0.0, 1.0));
        roughness = clamp(skin_specular_response.g, 0.04, 1.0);
    }
    if has_source_glossiness {
        let authored_glossiness = clamp(textureSampleBias(
            glossiness_texture,
            material_sampler,
            input.uv,
            MATERIAL_MIP_LOD_BIAS).r, 0.0, 1.0);
        roughness = clamp(1.0 - authored_glossiness, 0.04, 1.0);
    }
    if !has_source_roughness {
        var category_roughness = 0.66;
        if is_metal { category_roughness = 0.16; }
        if is_leather { category_roughness = 0.76; }
        if is_wood { category_roughness = 0.70; }
        if is_cloth { category_roughness = 0.84; }
        if is_skin { category_roughness = 0.58; }
        if is_hair { category_roughness = 0.64; }
        if is_glass { category_roughness = 0.30; }
        if is_gem { category_roughness = 0.26; }
        if is_stone { category_roughness = 0.82; }
        if is_eye { category_roughness = 0.30; }
        if is_tooth { category_roughness = 0.58; }
        roughness = mix(0.66, category_roughness, category_confidence);
    }
    if !has_source_metalness && is_metal {
        metalness = mix(0.28, 0.62, category_confidence);
    }
    if (material.flags & MATERIAL_ROUGHNESS_FACTOR) != 0u {
        let factor_weight = select(0.55, 0.15, has_source_roughness);
        roughness = clamp(mix(roughness, material.surface_factors.x, factor_weight), 0.04, 1.0);
    }
    if (material.flags & MATERIAL_METALNESS_FACTOR) != 0u {
        let declared_metalness = clamp(material.surface_factors.y, 0.0, 1.0);
        metalness = select(declared_metalness, max(metalness, declared_metalness), has_source_metalness);
    }
    if (material.flags & MATERIAL_SKIN_DETAIL_MATERIAL) != 0u && skin_detail_weight > 0.0001 {
        let skin_detail_surface = textureSampleBias(
            skin_detail_material_texture,
            material_sampler,
            skin_detail_uv,
            MATERIAL_MIP_LOD_BIAS);
        roughness = clamp(
            mix(roughness, skin_detail_surface.g, skin_detail_weight),
            0.04,
            1.0);
    }
    if is_skin {
        metalness = 0.0;
    }
    if (material.flags & MATERIAL_HEIGHT) != 0u {
        let height_relief = (height_value - 0.5) * clamp(material.relief_factors.x, 0.0, 1.0);
        roughness = clamp(roughness - height_relief * 0.10, 0.04, 1.0);
    }
    var raw_occlusion = 1.0;
    if (material.flags & MATERIAL_OCCLUSION) != 0u {
        raw_occlusion = clamp(textureSampleBias(occlusion_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS).r, 0.0, 1.0);
    }
    var occlusion_category_weight = 0.78;
    if is_metal { occlusion_category_weight = 1.0; }
    if is_glossy { occlusion_category_weight = 0.82; }
    if is_skin { occlusion_category_weight = 0.58; }
    if is_hair { occlusion_category_weight = 0.62; }
    if is_cloth || is_leather || is_wood || is_stone { occlusion_category_weight = 0.68; }
    let occlusion = mix(1.0, raw_occlusion, 0.45 * occlusion_category_weight);

    let game_outdoor = camera.view_mode == 9u;
    let view_direction = safe_normalize(camera.view_direction.xyz, vec3<f32>(0.0, 0.0, -1.0));
    let camera_right = safe_normalize(
        cross(view_direction, vec3<f32>(0.0, 1.0, 0.0)),
        vec3<f32>(1.0, 0.0, 0.0));
    let camera_up = safe_normalize(
        cross(camera_right, view_direction),
        vec3<f32>(0.0, 1.0, 0.0));
    let key_direction = safe_normalize(
        view_direction - camera_right * 0.18 + camera_up * 0.35,
        view_direction);
    let fill_direction = safe_normalize(
        view_direction + camera_right * 0.35 + camera_up * 0.45,
        view_direction);
    let key_half_vector = safe_normalize(key_direction + view_direction, view_direction);
    let fill_half_vector = safe_normalize(fill_direction + view_direction, view_direction);
    let key_light = wrapped_ndotl(surface_normal, key_direction, 0.58);
    let fill_light = wrapped_ndotl(surface_normal, fill_direction, 0.82);
    let ndotv = clamp(dot(surface_normal, view_direction), 0.0, 1.0);
    let rim_light = pow(1.0 - ndotv, 2.0);

    var ambient_floor = 0.50;
    var depth_authority = 0.68;
    if is_metal { ambient_floor = 0.24; depth_authority = 1.0; }
    if is_skin { ambient_floor = 0.56; depth_authority = 0.50; }
    if is_hair { ambient_floor = 0.48; depth_authority = 0.52; }
    if is_glossy { ambient_floor = 0.47; depth_authority = 0.80; }
    if is_leather { ambient_floor = 0.40; depth_authority = 0.70; }
    if is_cloth { ambient_floor = 0.42; depth_authority = 0.68; }
    if is_wood { ambient_floor = 0.49; depth_authority = 0.70; }
    if is_stone { ambient_floor = 0.48; depth_authority = 0.78; }
    if is_tooth { ambient_floor = 0.54; depth_authority = 0.58; }
    let shaped_light = ambient_floor * 0.84
        + 0.62 * (key_light * 0.72 + fill_light * 0.18 + rim_light * 0.10);
    let diffuse_depth = mix(1.0, shaped_light, depth_authority);
    // The Vortice path retains a small source-coloured body term beneath its
    // HDR studio reflections. Rust uses a bounded procedural environment, so a
    // 0.20 floor preserves the same albedo readability without adding neutral
    // light or changing the authored metal hue.
    let metal_body_scale = select(0.34, 0.20, has_source_metalness);
    var body_scale = mix(1.0, metal_body_scale, metalness);
    if is_glass { body_scale *= 0.68; }
    if is_gem { body_scale *= 0.78; }
    let authored_cloth_or_leather =
        has_source_base_color && (is_cloth || is_leather);
    var albedo_tint = vec3<f32>(1.0);
    if is_leather && !has_source_base_color {
        albedo_tint = vec3<f32>(1.035, 0.985, 0.95);
    }
    if is_cloth && !has_source_base_color {
        albedo_tint = vec3<f32>(0.985, 0.995, 1.015);
    }
    if is_skin { albedo_tint = vec3<f32>(1.04, 0.98, 0.955); }
    let shaded_albedo = clamp(texel.rgb * albedo_tint, vec3<f32>(0.0), vec3<f32>(1.0));
    let texture_luma = dot(shaded_albedo, vec3<f32>(0.299, 0.587, 0.114));
    var material_lift = 0.030;
    if is_metal { material_lift = 0.020; }
    if is_skin { material_lift = 0.025; }
    if is_hair { material_lift = 0.035; }
    if is_hair && (material.flags & MATERIAL_TEXTURE_TINT) != 0u { material_lift = 0.0; }
    if authored_cloth_or_leather { material_lift = 0.0; }
    let cloth_high_luma_guard = select(
        0.0,
        clamp((texture_luma - 0.82) * 4.0, 0.0, 1.0),
        is_cloth && !has_source_base_color,
    );
    let cloth_texture_boost = select(
        0.0,
        mix(0.03, -0.02, cloth_high_luma_guard),
        is_cloth && !has_source_base_color,
    );
    let authored_base_scale = select(1.03, 1.0, authored_cloth_or_leather);
    var material_reference_albedo = clamp(
        shaded_albedo * (authored_base_scale + cloth_texture_boost)
            + vec3<f32>(material_lift * clamp(1.0 - texture_luma, 0.0, 1.0)),
        vec3<f32>(0.0),
        vec3<f32>(1.0),
    );
    if is_skin {
        material_reference_albedo = clamp(
            material_reference_albedo * 1.04 + vec3<f32>(0.004, 0.002, 0.001),
            vec3<f32>(0.0),
            vec3<f32>(1.0),
        );
    }
    if is_cloth && cloth_high_luma_guard > 0.001 {
        let cloth_highlight_cap = vec3<f32>(0.94, 0.91, 0.84);
        material_reference_albedo = mix(
            material_reference_albedo,
            min(material_reference_albedo, cloth_highlight_cap),
            cloth_high_luma_guard * 0.35,
        );
    }
    let conservative_nonmetal = is_leather || is_wood || is_cloth || is_skin
        || is_hair || is_stone || is_tooth;
    let nonmetal_texture_scale = select(
        1.0,
        1.03,
        conservative_nonmetal && !authored_cloth_or_leather);
    var diffuse = material_reference_albedo
        * occlusion
        * diffuse_depth
        * body_scale
        * nonmetal_texture_scale;

    var dielectric_f0 = 0.04;
    if is_glass { dielectric_f0 = 0.08; }
    if is_gem { dielectric_f0 = 0.10; }
    if is_eye { dielectric_f0 = 0.065; }
    if is_leather { dielectric_f0 = 0.045; }
    if is_tooth { dielectric_f0 = 0.05; }
    dielectric_f0 = mix(0.04, dielectric_f0, category_confidence);
    var f0 = mix(
        vec3<f32>(dielectric_f0),
        material_reference_albedo,
        vec3<f32>(metalness),
    );
    let source_stable_f0 = f0;
    if (material.flags & MATERIAL_SPECULAR) != 0u && !is_skin {
        let mapped_specular = textureSampleBias(specular_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS).rgb;
        let source_weight = max(metalness, select(0.0, 0.75, is_glossy));
        f0 = mix(f0, max(f0, mapped_specular), vec3<f32>(source_weight));
    }
    if (material.flags & MATERIAL_SPECULAR_FACTOR) != 0u
        && material.surface_factors.z > 0.02 {
        let factored_specular = mix(
            dielectric_f0,
            material.surface_factors.z,
            max(metalness, select(0.35, 0.75, is_glossy)));
        let authored_metal_f0 =
            (material.flags & MATERIAL_BASE_COLOR) != 0u
            && has_source_metalness
            && metalness > 0.02;
        if !authored_metal_f0 {
            let fallback_metal_f0 =
                (material.flags & MATERIAL_BASE_COLOR) != 0u && metalness > 0.02;
            if fallback_metal_f0 {
                let source_peak = max(f0.r, max(f0.g, f0.b));
                if source_peak > 1e-5 {
                    let target_peak = max(source_peak, factored_specular);
                    f0 = clamp(
                        f0 * (target_peak / source_peak),
                        vec3<f32>(0.0),
                        vec3<f32>(1.0));
                }
            } else {
                f0 = max(f0, vec3<f32>(factored_specular));
            }
        }
    }
    if camera.view_mode == 6u {
        return present_srgb(vec3<f32>(metalness, roughness, max(f0.r, max(f0.g, f0.b))), 1.0);
    }
    var specular = vec3<f32>(0.0);
    if is_metal {
        var metal_normal = surface_normal;
        if dot(metal_normal, view_direction) < 0.0 {
            metal_normal = -metal_normal;
        }
        let metal_ndotl = clamp(dot(metal_normal, key_direction), 0.0, 1.0);
        let metal_ndotv = max(clamp(dot(metal_normal, view_direction), 0.0, 1.0), 1e-4);
        let metal_half_vector = safe_normalize(
            key_direction + view_direction,
            view_direction,
        );
        let metal_hdotv = clamp(dot(metal_half_vector, view_direction), 0.0, 1.0);
        let metal_distribution = distribution_ggx(metal_normal, metal_half_vector, roughness);
        let metal_geometry = geometry_smith(
            metal_normal,
            view_direction,
            key_direction,
            roughness,
        );
        let metal_fresnel = fresnel_schlick(metal_hdotv, source_stable_f0);
        let metal_denominator = max(4.0 * metal_ndotv * metal_ndotl, 1e-4);
        let metal_cook_torrance = metal_distribution
            * metal_geometry
            * metal_fresnel
            / metal_denominator;
        let metal_direct_specular_scale = select(
            0.35 + metalness * 0.35,
            1.0,
            has_source_metalness,
        );
        specular = min(
            metal_cook_torrance * metal_ndotl * metal_direct_specular_scale,
            vec3<f32>(0.85),
        );
    } else {
        let specular_power = mix(96.0, 8.0, roughness);
        let key_specular = pow(max(dot(surface_normal, key_half_vector), 0.0), specular_power);
        let fill_specular = pow(max(dot(surface_normal, fill_half_vector), 0.0), max(specular_power * 0.55, 4.0));
        specular = f0
            * (key_specular + fill_specular * 0.16)
            * (0.20 + 0.80 * (1.0 - roughness))
            * 0.62;
        if (material.flags & MATERIAL_HAIR_FLOW) != 0u {
            let flow = textureSampleBias(flow_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS).xy * 2.0
                - vec2<f32>(1.0);
            var flow_direction = vec2<f32>(0.0, 1.0);
            let flow_length_squared = dot(flow, flow);
            if flow_length_squared > 0.0004 {
                flow_direction = flow * inverseSqrt(flow_length_squared);
            }
            let strand_tangent = normalize(
                tangent * flow_direction.x + bitangent * flow_direction.y);
            let primary_exponent = mix(24.0, 96.0, 1.0 - roughness);
            let secondary_exponent = max(primary_exponent * 0.35, 8.0);
            let primary_tangent = normalize(strand_tangent - surface_normal * 0.06);
            let secondary_tangent = normalize(strand_tangent + surface_normal * 0.105);
            let primary_alignment = dot(primary_tangent, key_half_vector);
            let secondary_alignment = dot(secondary_tangent, key_half_vector);
            let primary_band = pow(
                sqrt(clamp(1.0 - primary_alignment * primary_alignment, 0.0, 1.0)),
                primary_exponent);
            let secondary_band = pow(
                sqrt(clamp(1.0 - secondary_alignment * secondary_alignment, 0.0, 1.0)),
                secondary_exponent);
            specular = key_light
                * (f0 * primary_band + material_reference_albedo * secondary_band * 0.55)
                * (0.20 + 0.80 * (1.0 - roughness))
                * 0.62;
        }
    }
    var environment_scale = 0.08;
    if is_metal { environment_scale = 0.94; }
    if is_glass { environment_scale = 0.26; }
    if is_gem { environment_scale = 0.30; }
    if is_eye { environment_scale = 0.24; }
    if is_leather || is_wood { environment_scale = 0.06; }
    if is_cloth { environment_scale = 0.025; }
    if is_skin { environment_scale = 0.075; }
    if is_hair { environment_scale = 0.08; }
    if is_stone { environment_scale = 0.04; }
    if is_tooth { environment_scale = 0.08; }
    if has_source_roughness && !is_metal && !is_skin {
        environment_scale = max(environment_scale, mix(0.06, 0.30, 1.0 - roughness));
    }
    let smoothness = clamp(1.0 - roughness, 0.0, 1.0);
    let reflected_view = safe_normalize(
        reflect(-view_direction, surface_normal),
        view_direction,
    );
    let environment_reflection = safe_normalize(vec3<f32>(
        dot(reflected_view, camera_right),
        dot(reflected_view, camera_up),
        -dot(reflected_view, view_direction),
    ), vec3<f32>(0.0, 0.0, -1.0));
    let environment_normal = safe_normalize(vec3<f32>(
        dot(surface_normal, camera_right),
        dot(surface_normal, camera_up),
        -dot(surface_normal, view_direction),
    ), vec3<f32>(0.0, 1.0, 0.0));
    let environment_radiance = preview_environment_radiance(environment_reflection, roughness);
    let environment_irradiance = preview_environment_irradiance(environment_normal);
    let environment_brdf = environment_brdf_approx(f0, roughness, ndotv);
    let environment_specular_occlusion = mix(occlusion, 1.0, smoothness * 0.55);
    var environment_specular = environment_radiance
        * environment_brdf
        * environment_scale
        * environment_specular_occlusion;

    // A real metal channel removes diffuse energy even when a mixed-material
    // part was not classified as metal. Give that authored fraction a coloured
    // environment response, keyed to source F0 rather than a white scalar.
    let metal_reflection_weight = select(
        select(0.0, clamp(metalness, 0.0, 1.0), has_source_metalness),
        1.0,
        is_metal,
    );
    if metal_reflection_weight > 0.001 {
        let metal_environment_scale = select(
            0.55 + metalness * mix(0.45, 1.10, smoothness),
            mix(0.82, 1.0, smoothness),
            has_source_metalness,
        );
        let metal_environment_brdf = environment_brdf_approx(
            source_stable_f0,
            roughness,
            clamp(abs(dot(surface_normal, view_direction)), 0.0, 1.0),
        );
        let metal_environment_specular = environment_radiance
            * metal_environment_brdf
            * metal_environment_scale
            * environment_specular_occlusion;
        environment_specular = mix(
            environment_specular,
            metal_environment_specular,
            metal_reflection_weight,
        );

        // Recover only the energy a rough conductor loses to single scattering.
        // Irradiance is bounded and the term remains tinted by authored metal F0,
        // so this improves source readability without a flat white/exposure lift.
        let metal_multiple_scattering = environment_irradiance
            * source_stable_f0
            * metalness
            * (roughness * roughness * 0.18)
            * occlusion;
        environment_specular += metal_multiple_scattering;
    }

    let environment_diffuse_energy = clamp(
        vec3<f32>(1.0) - environment_brdf,
        vec3<f32>(0.0),
        vec3<f32>(1.0),
    ) * (1.0 - clamp(metalness, 0.0, 1.0));
    let environment_diffuse_scale = select(0.24, 0.18, conservative_nonmetal);
    let environment_diffuse = material_reference_albedo
        * environment_irradiance
        * environment_diffuse_energy
        * occlusion
        * environment_diffuse_scale;
    let metal_cue = select(
        0.0,
        clamp(metalness * mix(0.18, 0.58, smoothness), 0.0, 1.0),
        is_metal,
    );
    let resolved_specular = max(f0.r, max(f0.g, f0.b));
    let glossy_cue = select(
        0.0,
        clamp(resolved_specular * mix(0.06, 0.20, smoothness), 0.0, 1.0),
        is_glossy,
    );
    diffuse += material_reference_albedo * metal_cue * 0.16;
    diffuse += material_reference_albedo * glossy_cue * 0.22;
    let metallic_source_anchor = select(
        material_reference_albedo
            * metalness
            * (0.14 + roughness * 0.06 + (1.0 - ndotv) * 0.30)
            * occlusion,
        vec3<f32>(0.0),
        has_source_metalness,
    );
    let category_feedback = select(1.0, 0.30, has_source_roughness);
    let leather_band = pow(max(dot(surface_normal, key_half_vector), 0.0), 12.0);
    let leather_sheen = select(
        vec3<f32>(0.0),
        vec3<f32>(0.16, 0.085, 0.045) * leather_band * category_feedback,
        is_leather);
    let cloth_sheen = select(
        vec3<f32>(0.0),
        material_reference_albedo * pow(1.0 - ndotv, 2.0) * 0.10 * category_feedback,
        is_cloth);
    let skin_scatter = select(
        vec3<f32>(0.0),
        material_reference_albedo
            * vec3<f32>(0.10, 0.035, 0.025)
            * (1.0 - key_light)
            * category_feedback
            * skin_subsurface_multiplier,
        is_skin);
    let glass_edge = select(
        vec3<f32>(0.0),
        vec3<f32>(0.18, 0.21, 0.24)
            * pow(1.0 - ndotv, 2.0)
            * category_feedback,
        is_glass);
    var emissive = vec3<f32>(0.0);
    if (material.flags & MATERIAL_EMISSIVE) != 0u {
        let emissive_sample = textureSampleBias(
            emissive_texture, material_sampler, input.uv, MATERIAL_MIP_LOD_BIAS);
        let emissive_rgb = select(
            emissive_sample.rgb,
            emissive_sample.rrr,
            (material.flags & MATERIAL_EMISSIVE_INTENSITY_MASK) != 0u);
        emissive = emissive_rgb
            * material.emissive_color_and_intensity.rgb
            * material.emissive_color_and_intensity.a
            * 2.2;
    }
    let exposure = select(1.0, 1.06, game_outdoor);
    let shaded = workbench_tone(
        diffuse
            + environment_diffuse
            + metallic_source_anchor
            + specular
            + environment_specular
            + leather_sheen
            + cloth_sheen
            + skin_scatter
            + glass_edge
            + emissive,
        exposure);
    return present(shaded, 1.0);
}

@fragment
fn fs_wire(_input: VertexOut) -> @location(0) vec4<f32> {
    return present(camera.wire_colour.rgb, camera.wire_colour.a);
}

@fragment
fn fs_point(_input: VertexOut) -> @location(0) vec4<f32> {
    return present(camera.point_colour.rgb, camera.point_colour.a);
}

@fragment
fn fs_xray(_input: VertexOut) -> @location(0) vec4<f32> {
    return present_srgb(vec3<f32>(0.20, 0.55, 0.92), 0.24);
}

@fragment
fn fs_normal(_input: VertexOut) -> @location(0) vec4<f32> {
    return present_srgb(vec3<f32>(0.15, 0.90, 0.75), 1.0);
}

@fragment
fn fs_bounds(_input: VertexOut) -> @location(0) vec4<f32> {
    return present_srgb(vec3<f32>(1.0, 0.70, 0.15), 1.0);
}

@fragment
fn fs_bone(_input: VertexOut) -> @location(0) vec4<f32> {
    return present_srgb(vec3<f32>(0.35, 0.82, 1.0), 1.0);
}
"#;

const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ViewMode {
    TexturedSolid,
    GameOutdoor,
    BaseColor,
    NormalMap,
    UvChecker,
    BaseAlpha,
    PartId,
    MaterialResponse,
    LayerMask,
    Solid,
    SolidWire,
    Wireframe,
    Vertices,
    WireVertices,
    XRay,
}

impl ViewMode {
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::TexturedSolid => "Textured",
            Self::GameOutdoor => "Game Outdoor",
            Self::BaseColor => "Base Color",
            Self::NormalMap => "Normal Map",
            Self::UvChecker => "UV Checker",
            Self::BaseAlpha => "Base Alpha",
            Self::PartId => "Part ID",
            Self::MaterialResponse => "Material Response",
            Self::LayerMask => "Layer Mask",
            Self::Solid => "Solid Faces",
            Self::SolidWire => "Solid + Wire",
            Self::Wireframe => "Wireframe",
            Self::Vertices => "Vertices",
            Self::WireVertices => "Wire + Vertices",
            Self::XRay => "X-Ray",
        }
    }

    const fn shader_mode(self) -> u32 {
        match self {
            Self::TexturedSolid => 0,
            Self::GameOutdoor => 9,
            Self::BaseColor => 2,
            Self::NormalMap => 3,
            Self::UvChecker => 4,
            Self::BaseAlpha => 5,
            Self::PartId => 8,
            Self::MaterialResponse => 6,
            Self::LayerMask => 7,
            Self::Solid
            | Self::SolidWire
            | Self::Wireframe
            | Self::Vertices
            | Self::WireVertices
            | Self::XRay => 1,
        }
    }
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct CameraUniform {
    view_projection: [[f32; 4]; 4],
    view_mode: u32,
    output_is_srgb: u32,
    _padding: [u32; 2],
    wire_colour: [f32; 4],
    point_colour: [f32; 4],
    view_direction: [f32; 4],
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct MaterialUniform {
    flags: u32,
    skin_detail_scale: f32,
    skin_detail_opacity: f32,
    _padding: u32,
    emissive_color_and_intensity: [f32; 4],
    surface_factors: [f32; 4],
    relief_factors: [f32; 4],
    texture_tint_and_strength: [f32; 4],
}

const MATERIAL_BASE_COLOR: u32 = 1;
const MATERIAL_NORMAL: u32 = 2;
const MATERIAL_SURFACE: u32 = 4;
const MATERIAL_ROUGHNESS: u32 = 8;
const MATERIAL_METALNESS: u32 = 16;
const MATERIAL_OCCLUSION: u32 = 32;
const MATERIAL_EMISSIVE: u32 = 64;
const MATERIAL_ROUGHNESS_FACTOR: u32 = 128;
const MATERIAL_METALNESS_FACTOR: u32 = 256;
const MATERIAL_SPECULAR_FACTOR: u32 = 512;
const MATERIAL_SPECULAR: u32 = 1024;
const MATERIAL_OPACITY: u32 = 2048;
const MATERIAL_ALPHA_CUTOUT: u32 = 4096;
const MATERIAL_HEIGHT: u32 = 8192;
const MATERIAL_HAIR_FLOW: u32 = 16384;
const MATERIAL_LAYER_MASK: u32 = 32768;
const MATERIAL_NORMAL_Y_INVERTED: u32 = 65536;
const MATERIAL_CATEGORY: u32 = 131072;
const MATERIAL_EMISSIVE_INTENSITY_MASK: u32 = 262144;
const MATERIAL_SKIN_DETAIL_MASK: u32 = 524288;
const MATERIAL_SKIN_DETAIL_NORMAL: u32 = 1048576;
const MATERIAL_SKIN_DETAIL_MATERIAL: u32 = 2097152;
const MATERIAL_GLOSSINESS: u32 = 4194304;
const MATERIAL_TEXTURE_TINT: u32 = 8388608;
const NEUTRAL_MISSING_BASE_COLOR_SRGB: [u8; 4] = [144, 144, 144, 255];

impl CameraUniform {
    fn new(output_is_srgb: bool) -> Self {
        Self {
            view_projection: Mat4::IDENTITY.to_cols_array_2d(),
            view_mode: 0,
            output_is_srgb: u32::from(output_is_srgb),
            _padding: [0; 2],
            wire_colour: srgb_rgba_to_linear([0.72, 0.78, 0.88, 1.0]),
            point_colour: srgb_rgba_to_linear([0.92, 0.94, 1.0, 1.0]),
            view_direction: [0.0, 0.0, -1.0, 0.0],
        }
    }
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct GpuVertex {
    position: [f32; 3],
    normal: [f32; 3],
    uv: [f32; 2],
    tangent: [f32; 4],
    deformation: [f32; 4],
}

impl GpuVertex {
    const ATTRIBUTES: [wgpu::VertexAttribute; 5] = wgpu::vertex_attr_array![
        0 => Float32x3,
        1 => Float32x3,
        2 => Float32x2,
        3 => Float32x4,
        4 => Float32x4
    ];

    fn layout() -> wgpu::VertexBufferLayout<'static> {
        wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<Self>() as wgpu::BufferAddress,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &Self::ATTRIBUTES,
        }
    }

    fn overlay(position: Vec3) -> Self {
        Self {
            position: position.to_array(),
            normal: Vec3::Y.to_array(),
            uv: [0.0, 0.0],
            tangent: [1.0, 0.0, 0.0, 1.0],
            deformation: [0.0; 4],
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdapterReport {
    pub name: String,
    pub backend: String,
    pub device_type: String,
    pub driver: String,
    pub driver_info: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RendererQualityReport {
    pub sample_count: u32,
    pub anisotropy_clamp: u16,
    pub present_mode: String,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct MeshUploadStats {
    pub full_uploads: u64,
    pub in_place_geometry_updates: u64,
    pub unchanged_reuses: u64,
}

#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct MaterialPreviewFactors {
    pub emissive_color: Option<[f32; 3]>,
    pub emissive_intensity: Option<f32>,
    pub roughness: Option<f32>,
    pub metalness: Option<f32>,
    pub specular: Option<f32>,
    pub height_scale: Option<f32>,
    pub texture_tint: Option<[f32; 3]>,
    pub base_tint_strength: Option<f32>,
    pub alpha_cutoff: Option<f32>,
    pub hair_anisotropy: Option<bool>,
    pub layer_mask_channel: Option<u32>,
    pub category_code: Option<u32>,
    pub category_confidence: Option<f32>,
    pub normal_y_inverted: Option<bool>,
    pub skin_detail_scale: Option<f32>,
    pub skin_detail_opacity: Option<f32>,
}

const INTEGRATED_DEPTH_ELONGATION_RATIO: f32 = 1.5;
const INTEGRATED_BROADSIDE_PITCH: f32 = -35.0 * std::f32::consts::PI / 180.0;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct IntegratedStartupView {
    pub yaw: f32,
    pub pitch: f32,
}

impl IntegratedStartupView {
    #[must_use]
    pub fn eye_direction(self) -> Vec3 {
        (Quat::from_rotation_y(self.yaw) * Quat::from_rotation_x(self.pitch)) * Vec3::Z
    }

    #[must_use]
    pub fn up_direction(self) -> Vec3 {
        let forward = -self.eye_direction();
        let right = forward.cross(Vec3::Y).normalize_or(Vec3::X);
        right.cross(forward).normalize_or(Vec3::Y)
    }
}

#[must_use]
pub fn integrated_startup_view(extent: Vec3) -> IntegratedStartupView {
    let transverse_extent = extent.x.max(extent.y).max(1.0e-4);
    if extent.z > transverse_extent * INTEGRATED_DEPTH_ELONGATION_RATIO {
        IntegratedStartupView {
            yaw: std::f32::consts::FRAC_PI_2,
            pitch: INTEGRATED_BROADSIDE_PITCH,
        }
    } else {
        IntegratedStartupView {
            yaw: std::f32::consts::PI,
            pitch: 0.0,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HeadlessRenderReport {
    pub adapter: AdapterReport,
    pub sample_count: u32,
    pub anisotropy_clamp: u16,
    pub frames_rendered: u32,
    pub modes_rendered: u32,
    pub viewport_sizes_rendered: u32,
    pub dds_textures_uploaded: u32,
    pub sampled_material_roles: u32,
    pub material_ranges_rendered: u32,
    pub composed_material_pixels_changed: usize,
    pub emissive_factor_pixels_changed: usize,
    pub roughness_factor_pixels_changed: usize,
    pub metalness_factor_pixels_changed: usize,
    pub specular_factor_pixels_changed: usize,
    pub specular_texture_pixels_changed: usize,
    pub dielectric_specular_pixels_changed: usize,
    pub glossiness_texture_pixels_changed: usize,
    pub dielectric_glossiness_pixels_changed: usize,
    pub height_texture_pixels_changed: usize,
    pub disabled_height_pixels_changed: usize,
    pub hair_flow_pixels_changed: usize,
    pub non_hair_flow_pixels_changed: usize,
    pub layer_mask_pixels_changed: usize,
    pub layer_mask_channel_pixels_changed: usize,
    pub part_id_colors_rendered: usize,
    pub outdoor_lighting_pixels_changed: usize,
    pub bone_overlay_pixels_changed: usize,
    pub opacity_cutout_pixels_removed: usize,
    pub opaque_opacity_pixels_changed: usize,
    pub non_background_pixels: usize,
    pub base_color_round_trip_pixels: usize,
    pub front_lighting_luma_percent: u32,
    pub category_materials_distinguished: usize,
}

#[derive(Debug, Clone, Copy)]
pub struct HeadlessMaterialTexture<'a> {
    pub bytes: &'a [u8],
    pub role: TextureRole,
    pub material_indices_by_lod: &'a [Vec<u32>],
}

#[derive(Debug, Clone, Copy)]
pub struct HeadlessMaterialFactors<'a> {
    pub factors: MaterialPreviewFactors,
    pub material_indices_by_lod: &'a [Vec<u32>],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HeadlessMaterialCaptureOptions {
    pub width: u32,
    pub height: u32,
    pub lod_index: usize,
}

impl Default for HeadlessMaterialCaptureOptions {
    fn default() -> Self {
        Self {
            width: 1_024,
            height: 1_024,
            lod_index: 0,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct HeadlessMaterialCaptureOutput<'a> {
    pub textured_bmp: &'a Path,
    pub base_color_bmp: &'a Path,
    pub part_id_bmp: &'a Path,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HeadlessFrameStats {
    pub non_background_pixels: usize,
    pub mean_luma_255: f32,
    pub p05_luma_255: f32,
    pub p50_luma_255: f32,
    pub p95_luma_255: f32,
    pub mean_chroma_255: f32,
    pub near_white_percent: f32,
    pub light_pixel_percent: f32,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HeadlessMaterialOwnerCoverage {
    pub material_index: u32,
    pub part_id: u32,
    pub pixel_count: usize,
    pub frame_percent: f32,
    pub textured_mean_luma_255: f32,
    pub textured_mean_chroma_255: f32,
    pub base_color_mean_luma_255: f32,
    pub base_color_mean_chroma_255: f32,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HeadlessMaterialCaptureReport {
    pub adapter: AdapterReport,
    pub sample_count: u32,
    pub anisotropy_clamp: u16,
    pub width: u32,
    pub height: u32,
    pub lod_index: usize,
    pub dds_textures_uploaded: u32,
    pub texture_bound_materials: u32,
    pub active_material_bindings: u32,
    pub material_ranges_rendered: u32,
    pub textured: HeadlessFrameStats,
    pub base_color: HeadlessFrameStats,
    pub part_id: HeadlessFrameStats,
    pub owner_coverage: Vec<HeadlessMaterialOwnerCoverage>,
}

#[derive(Debug, Error)]
pub enum RenderError {
    #[error("no Direct3D 12 adapter is available")]
    NoAdapter,
    #[error("wgpu device request failed: {0}")]
    Device(String),
    #[error("window surface creation failed: {0}")]
    Surface(String),
    #[error("window surface has no supported format")]
    SurfaceFormat,
    #[error("surface frame failed: {0}")]
    SurfaceFrame(String),
    #[error("draw snapshot exceeds GPU index limits")]
    ResourceLimit,
    #[error("draw snapshot material ownership is invalid: {0}")]
    InvalidSnapshot(String),
    #[error("overlay line geometry is invalid: {0}")]
    InvalidOverlay(String),
    #[error("DDS texture upload failed: {0}")]
    Texture(String),
}

pub struct GpuMeshBuffers {
    vertex: wgpu::Buffer,
    triangle_index: wgpu::Buffer,
    wire_index: wgpu::Buffer,
    normal_lines: wgpu::Buffer,
    bounds_lines: wgpu::Buffer,
    material_ranges: Vec<GpuMaterialRange>,
    triangle_index_count: u32,
    wire_index_count: u32,
    vertex_count: u32,
    normal_line_vertex_count: u32,
    bounds_line_vertex_count: u32,
    mesh_identity: u64,
    topology_signature: u64,
    deformation_signature: u64,
    tangents: Vec<[f32; 4]>,
    tangents_exact: bool,
    pub draw_revision: u64,
    pub topology_generation: u64,
}

struct GpuOverlayLines {
    vertices: wgpu::Buffer,
    vertex_count: u32,
}

impl GpuOverlayLines {
    fn upload(device: &wgpu::Device, positions: &[[f32; 3]]) -> Result<Option<Self>, RenderError> {
        if positions.is_empty() {
            return Ok(None);
        }
        if !positions.len().is_multiple_of(2) {
            return Err(RenderError::InvalidOverlay(
                "line-list vertex count must be even".to_owned(),
            ));
        }
        if positions.iter().flatten().any(|value| !value.is_finite()) {
            return Err(RenderError::InvalidOverlay(
                "line-list positions must be finite".to_owned(),
            ));
        }
        let vertices = positions
            .iter()
            .copied()
            .map(Vec3::from_array)
            .map(GpuVertex::overlay)
            .collect::<Vec<_>>();
        let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab skeleton lines"),
            contents: bytemuck::cast_slice(&vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        Ok(Some(Self {
            vertices: buffer,
            vertex_count: u32::try_from(vertices.len()).map_err(|_| RenderError::ResourceLimit)?,
        }))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct GpuMaterialRange {
    material: u32,
    part_id: u32,
    first_index: u32,
    index_count: u32,
}

struct GpuMaterialTexture {
    _texture: wgpu::Texture,
    role: TextureRole,
    single_channel: bool,
    material_indices_by_lod: Vec<Vec<u32>>,
}

struct MaterialFactorOwnership {
    factors: MaterialPreviewFactors,
    material_indices_by_lod: Vec<Vec<u32>>,
}

struct DefaultMaterialTextures {
    base_color: wgpu::Texture,
    normal: wgpu::Texture,
    surface: wgpu::Texture,
    roughness: wgpu::Texture,
    metalness: wgpu::Texture,
    occlusion: wgpu::Texture,
    emissive: wgpu::Texture,
    specular: wgpu::Texture,
    glossiness: wgpu::Texture,
    opacity: wgpu::Texture,
    height: wgpu::Texture,
    flow: wgpu::Texture,
    layer_mask: wgpu::Texture,
}

struct GpuMaterialBinding {
    bind_group: wgpu::BindGroup,
    _uniform_buffer: wgpu::Buffer,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct MaterialTextureIndices {
    base_color: Option<usize>,
    normal: Option<usize>,
    surface: Option<usize>,
    roughness: Option<usize>,
    metalness: Option<usize>,
    occlusion: Option<usize>,
    emissive: Option<usize>,
    specular: Option<usize>,
    glossiness: Option<usize>,
    opacity: Option<usize>,
    height: Option<usize>,
    flow: Option<usize>,
    layer_mask: Option<usize>,
    skin_detail_mask: Option<usize>,
    skin_detail_normal: Option<usize>,
    skin_detail_material: Option<usize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum MeshUploadAction {
    Reuse,
    UpdateGeometry,
    Replace,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum GeometryUpdateMode {
    // Preserve a stable orthogonal basis during pointer-rate preview frames. The final frame
    // always recomputes the exact position/UV-derived basis before the gesture is published.
    Interactive,
    Final,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct MeshUploadKey {
    mesh_identity: u64,
    draw_revision: u64,
    topology_generation: u64,
    topology_signature: u64,
    deformation_signature: u64,
}

fn classify_mesh_upload(current: MeshUploadKey, next: MeshUploadKey) -> MeshUploadAction {
    if current.mesh_identity != next.mesh_identity
        || current.topology_generation != next.topology_generation
        || current.topology_signature != next.topology_signature
    {
        MeshUploadAction::Replace
    } else if current.draw_revision == next.draw_revision
        && current.deformation_signature == next.deformation_signature
    {
        MeshUploadAction::Reuse
    } else {
        MeshUploadAction::UpdateGeometry
    }
}

fn resolve_mesh_upload_action(
    action: MeshUploadAction,
    update_mode: GeometryUpdateMode,
    tangents_exact: bool,
) -> MeshUploadAction {
    if action == MeshUploadAction::Reuse
        && update_mode == GeometryUpdateMode::Final
        && !tangents_exact
    {
        MeshUploadAction::UpdateGeometry
    } else {
        action
    }
}

fn topology_signature(snapshot: &DrawSnapshot) -> u64 {
    let mut hasher = DefaultHasher::new();
    snapshot.positions.len().hash(&mut hasher);
    snapshot.normals.len().hash(&mut hasher);
    snapshot.uvs.len().hash(&mut hasher);
    snapshot.indices.hash(&mut hasher);
    snapshot.triangle_materials.hash(&mut hasher);
    hasher.finish()
}

fn deformation_signature(reference: Option<&[[f32; 3]]>) -> Result<u64, RenderError> {
    let Some(reference) = reference else {
        return Ok(0);
    };
    let mut hasher = DefaultHasher::new();
    1_u8.hash(&mut hasher);
    reference.len().hash(&mut hasher);
    for position in reference {
        for coordinate in position {
            if !coordinate.is_finite() {
                return Err(RenderError::InvalidSnapshot(
                    "deformation reference contains a non-finite coordinate".to_owned(),
                ));
            }
            coordinate.to_bits().hash(&mut hasher);
        }
    }
    Ok(hasher.finish())
}

fn mix_rgb(left: Vec3, right: Vec3, amount: f32) -> Vec3 {
    left + (right - left) * amount.clamp(0.0, 1.0)
}

fn deformation_colours(
    snapshot: &DrawSnapshot,
    reference: Option<&[[f32; 3]]>,
) -> Result<Vec<[f32; 4]>, RenderError> {
    let Some(reference) = reference else {
        return Ok(vec![[0.0; 4]; snapshot.positions.len()]);
    };
    if reference.len() != snapshot.positions.len() {
        return Err(RenderError::InvalidSnapshot(format!(
            "deformation reference has {} positions for {} current vertices",
            reference.len(),
            snapshot.positions.len()
        )));
    }
    let mut reference_min = Vec3::splat(f32::INFINITY);
    let mut reference_max = Vec3::splat(f32::NEG_INFINITY);
    let magnitudes = snapshot
        .positions
        .iter()
        .zip(reference)
        .map(|(current, original)| {
            let current = Vec3::from_array(*current);
            let original = Vec3::from_array(*original);
            if !current.is_finite() || !original.is_finite() {
                return Err(RenderError::InvalidSnapshot(
                    "deformation positions must be finite".to_owned(),
                ));
            }
            reference_min = reference_min.min(original);
            reference_max = reference_max.max(original);
            Ok(current.distance(original))
        })
        .collect::<Result<Vec<_>, RenderError>>()?;
    let reference_extent = if reference.is_empty() {
        0.0
    } else {
        reference_min.distance(reference_max)
    };
    // A fixed topology-relative scale keeps old edit colours stable when a later
    // stroke creates a larger displacement elsewhere on the mesh.
    let full_scale = (reference_extent * 0.05).max(1.0e-4);

    Ok(magnitudes
        .into_iter()
        .map(|magnitude| {
            if magnitude <= 1.0e-7 {
                return [0.0; 4];
            }
            let normalized = (magnitude / full_scale).clamp(0.0, 1.0);
            let green = Vec3::new(0.08, 0.85, 0.20);
            let yellow = Vec3::new(1.00, 0.85, 0.05);
            let red = Vec3::new(1.00, 0.08, 0.03);
            let colour = if normalized <= 0.5 {
                mix_rgb(green, yellow, normalized * 2.0)
            } else {
                mix_rgb(yellow, red, (normalized - 0.5) * 2.0)
            };
            [colour.x, colour.y, colour.z, 0.30 + normalized * 0.58]
        })
        .collect())
}

fn gpu_vertices_with_tangents(
    snapshot: &DrawSnapshot,
    deformation_reference: Option<&[[f32; 3]]>,
    tangents: &[[f32; 4]],
) -> Result<Vec<GpuVertex>, RenderError> {
    if tangents.len() != snapshot.positions.len() {
        return Err(RenderError::InvalidSnapshot(format!(
            "{} positions have {} tangents",
            snapshot.positions.len(),
            tangents.len()
        )));
    }
    let deformation = deformation_colours(snapshot, deformation_reference)?;
    Ok(snapshot
        .positions
        .iter()
        .enumerate()
        .map(|(index, position)| {
            let normal = snapshot
                .normals
                .get(index)
                .copied()
                .unwrap_or([0.0, 1.0, 0.0]);
            let uv = snapshot.uvs.get(index).copied().unwrap_or([0.0, 0.0]);
            let tangent = tangents[index];
            GpuVertex {
                position: *position,
                normal,
                uv,
                tangent,
                deformation: deformation[index],
            }
        })
        .collect())
}

impl GpuMeshBuffers {
    pub fn upload(device: &wgpu::Device, snapshot: &DrawSnapshot) -> Result<Self, RenderError> {
        Self::upload_with_deformation(device, snapshot, None)
    }

    fn upload_with_deformation(
        device: &wgpu::Device,
        snapshot: &DrawSnapshot,
        deformation_reference: Option<&[[f32; 3]]>,
    ) -> Result<Self, RenderError> {
        let tangents = vertex_tangents(snapshot)?;
        let vertices =
            gpu_vertices_with_tangents(snapshot, deformation_reference, tangents.as_slice())?;
        let vertex = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab vertices"),
            contents: bytemuck::cast_slice(&vertices),
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
        });
        let (material_indices, material_ranges) = material_index_batches(snapshot)?;
        let triangle_index = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab triangle indices"),
            contents: bytemuck::cast_slice(&material_indices),
            usage: wgpu::BufferUsages::INDEX,
        });
        let wire_indices = unique_wire_indices(&snapshot.indices);
        let wire_index = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab wire indices"),
            contents: bytemuck::cast_slice(&wire_indices),
            usage: wgpu::BufferUsages::INDEX,
        });
        let normal_line_vertices = normal_line_vertices(snapshot);
        let normal_lines = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab normal lines"),
            contents: bytemuck::cast_slice(&normal_line_vertices),
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
        });
        let bounds_line_vertices = bounds_line_vertices(&snapshot.positions);
        let bounds_lines = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab bounds lines"),
            contents: bytemuck::cast_slice(&bounds_line_vertices),
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
        });
        Ok(Self {
            vertex,
            triangle_index,
            wire_index,
            normal_lines,
            bounds_lines,
            material_ranges,
            triangle_index_count: u32::try_from(snapshot.indices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            wire_index_count: u32::try_from(wire_indices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            vertex_count: u32::try_from(vertices.len()).map_err(|_| RenderError::ResourceLimit)?,
            normal_line_vertex_count: u32::try_from(normal_line_vertices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            bounds_line_vertex_count: u32::try_from(bounds_line_vertices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            mesh_identity: snapshot.mesh_identity,
            topology_signature: topology_signature(snapshot),
            deformation_signature: deformation_signature(deformation_reference)?,
            tangents,
            tangents_exact: true,
            draw_revision: snapshot.draw_revision,
            topology_generation: snapshot.topology_generation,
        })
    }

    fn upload_action(
        &self,
        snapshot: &DrawSnapshot,
        deformation_signature: u64,
    ) -> MeshUploadAction {
        classify_mesh_upload(
            MeshUploadKey {
                mesh_identity: self.mesh_identity,
                draw_revision: self.draw_revision,
                topology_generation: self.topology_generation,
                topology_signature: self.topology_signature,
                deformation_signature: self.deformation_signature,
            },
            MeshUploadKey {
                mesh_identity: snapshot.mesh_identity,
                draw_revision: snapshot.draw_revision,
                topology_generation: snapshot.topology_generation,
                topology_signature: topology_signature(snapshot),
                deformation_signature,
            },
        )
    }

    fn matches_snapshot(&self, snapshot: &DrawSnapshot) -> bool {
        self.upload_action(snapshot, 0) == MeshUploadAction::Reuse
    }

    fn refresh_geometry(
        &mut self,
        queue: &wgpu::Queue,
        snapshot: &DrawSnapshot,
        deformation_reference: Option<&[[f32; 3]]>,
        deformation_signature: u64,
        update_mode: GeometryUpdateMode,
    ) -> Result<(), RenderError> {
        let tangents = match update_mode {
            GeometryUpdateMode::Interactive => {
                reproject_vertex_tangents(&snapshot.normals, &self.tangents)?
            }
            GeometryUpdateMode::Final => vertex_tangents(snapshot)?,
        };
        let vertices =
            gpu_vertices_with_tangents(snapshot, deformation_reference, tangents.as_slice())?;
        let normal_line_vertices = normal_line_vertices(snapshot);
        let bounds_line_vertices = bounds_line_vertices(&snapshot.positions);
        if u32::try_from(vertices.len()).ok() != Some(self.vertex_count)
            || u32::try_from(normal_line_vertices.len()).ok() != Some(self.normal_line_vertex_count)
            || u32::try_from(bounds_line_vertices.len()).ok() != Some(self.bounds_line_vertex_count)
        {
            return Err(RenderError::InvalidSnapshot(
                "same-topology geometry refresh changed a GPU buffer length".to_owned(),
            ));
        }
        queue.write_buffer(&self.vertex, 0, bytemuck::cast_slice(&vertices));
        queue.write_buffer(
            &self.normal_lines,
            0,
            bytemuck::cast_slice(&normal_line_vertices),
        );
        queue.write_buffer(
            &self.bounds_lines,
            0,
            bytemuck::cast_slice(&bounds_line_vertices),
        );
        self.draw_revision = snapshot.draw_revision;
        self.deformation_signature = deformation_signature;
        self.tangents = tangents;
        self.tangents_exact = update_mode == GeometryUpdateMode::Final;
        Ok(())
    }
}

struct DepthTarget {
    _texture: wgpu::Texture,
    view: wgpu::TextureView,
}

struct MultisampleTarget {
    _texture: wgpu::Texture,
    view: wgpu::TextureView,
}

fn requested_renderer_features(supported: wgpu::Features) -> wgpu::Features {
    supported & (wgpu::Features::TEXTURE_COMPRESSION_BC | wgpu::Features::FLOAT32_FILTERABLE)
}

fn preferred_sample_count_from_flags(
    color: wgpu::TextureFormatFeatureFlags,
    depth: wgpu::TextureFormatFeatureFlags,
) -> u32 {
    let color_required = wgpu::TextureFormatFeatureFlags::MULTISAMPLE_X4
        | wgpu::TextureFormatFeatureFlags::MULTISAMPLE_RESOLVE;
    if color.contains(color_required)
        && depth.contains(wgpu::TextureFormatFeatureFlags::MULTISAMPLE_X4)
    {
        4
    } else {
        1
    }
}

fn preferred_sample_count(adapter: &wgpu::Adapter, format: wgpu::TextureFormat) -> u32 {
    preferred_sample_count_from_flags(
        adapter.get_texture_format_features(format).flags,
        adapter.get_texture_format_features(DEPTH_FORMAT).flags,
    )
}

fn preferred_present_mode(modes: &[wgpu::PresentMode]) -> Option<wgpu::PresentMode> {
    modes
        .iter()
        .copied()
        .find(|mode| *mode == wgpu::PresentMode::Mailbox)
        .or_else(|| {
            modes
                .iter()
                .copied()
                .find(|mode| *mode == wgpu::PresentMode::Fifo)
        })
        .or_else(|| modes.first().copied())
}

fn preferred_surface_format(formats: &[wgpu::TextureFormat]) -> Option<wgpu::TextureFormat> {
    formats
        .iter()
        .copied()
        .find(|format| {
            matches!(
                format,
                wgpu::TextureFormat::Bgra8UnormSrgb | wgpu::TextureFormat::Rgba8UnormSrgb
            )
        })
        .or_else(|| {
            formats.iter().copied().find(|format| {
                matches!(
                    format,
                    wgpu::TextureFormat::Bgra8Unorm | wgpu::TextureFormat::Rgba8Unorm
                )
            })
        })
        .or_else(|| formats.first().copied())
}

fn preferred_anisotropy_clamp(downlevel_flags: wgpu::DownlevelFlags) -> u16 {
    if downlevel_flags.contains(wgpu::DownlevelFlags::ANISOTROPIC_FILTERING) {
        16
    } else {
        1
    }
}

fn bounded_rgba(colour: [f32; 4]) -> Option<[f32; 4]> {
    colour
        .iter()
        .all(|component| component.is_finite())
        .then(|| colour.map(|component| component.clamp(0.0, 1.0)))
}

fn srgb_channel_to_linear(value: f32) -> f32 {
    let value = value.clamp(0.0, 1.0);
    if value <= 0.040_45 {
        value / 12.92
    } else {
        ((value + 0.055) / 1.055).powf(2.4)
    }
}

fn srgb_rgba_to_linear(colour: [f32; 4]) -> [f32; 4] {
    [
        srgb_channel_to_linear(colour[0]),
        srgb_channel_to_linear(colour[1]),
        srgb_channel_to_linear(colour[2]),
        colour[3].clamp(0.0, 1.0),
    ]
}

fn clear_colour_for_target(colour: [f32; 4], output_is_srgb: bool) -> wgpu::Color {
    let colour = if output_is_srgb {
        srgb_rgba_to_linear(colour)
    } else {
        colour
    };
    wgpu::Color {
        r: f64::from(colour[0]),
        g: f64::from(colour[1]),
        b: f64::from(colour[2]),
        a: f64::from(colour[3]),
    }
}

fn view_direction_from_view_projection(view_projection: Mat4) -> Vec3 {
    let inverse = view_projection.inverse();
    if !inverse.is_finite() {
        return -Vec3::Z;
    }
    let unproject = |depth: f32| {
        let point = inverse * glam::Vec4::new(0.0, 0.0, depth, 1.0);
        (point.w.abs() > 1.0e-6).then(|| point.truncate() / point.w)
    };
    let Some(near) = unproject(0.0) else {
        return -Vec3::Z;
    };
    let Some(far) = unproject(1.0) else {
        return -Vec3::Z;
    };
    (near - far).normalize_or(-Vec3::Z)
}

pub struct WindowRenderer {
    _instance: wgpu::Instance,
    surface: wgpu::Surface<'static>,
    adapter: wgpu::Adapter,
    device: wgpu::Device,
    queue: wgpu::Queue,
    config: wgpu::SurfaceConfiguration,
    solid_pipeline: wgpu::RenderPipeline,
    wire_pipeline: wgpu::RenderPipeline,
    xray_wire_pipeline: wgpu::RenderPipeline,
    point_pipeline: wgpu::RenderPipeline,
    xray_pipeline: wgpu::RenderPipeline,
    normal_pipeline: wgpu::RenderPipeline,
    bounds_pipeline: wgpu::RenderPipeline,
    bone_pipeline: wgpu::RenderPipeline,
    mesh: Option<GpuMeshBuffers>,
    skeleton_lines: Option<GpuOverlayLines>,
    preview_lines: Option<GpuOverlayLines>,
    egui_renderer: egui_wgpu::Renderer,
    texture_bind_group_layout: wgpu::BindGroupLayout,
    default_material_binding: GpuMaterialBinding,
    default_material_textures: DefaultMaterialTextures,
    material_sampler: wgpu::Sampler,
    material_textures: Vec<GpuMaterialTexture>,
    material_factors: Vec<MaterialFactorOwnership>,
    active_material_bindings: BTreeMap<u32, GpuMaterialBinding>,
    mesh_viewport: Option<[f32; 4]>,
    depth_target: DepthTarget,
    multisample_target: Option<MultisampleTarget>,
    sample_count: u32,
    anisotropy_clamp: u16,
    upload_stats: MeshUploadStats,
    camera_uniform: CameraUniform,
    camera_buffer: wgpu::Buffer,
    camera_bind_group: wgpu::BindGroup,
    view_mode: ViewMode,
    show_normals: bool,
    show_bounds: bool,
    show_bones: bool,
    clear_colour: wgpu::Color,
}

impl WindowRenderer {
    pub async fn new(window: Arc<Window>) -> Result<Self, RenderError> {
        let mut instance_descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
        instance_descriptor.backends = wgpu::Backends::DX12;
        let instance = wgpu::Instance::new(instance_descriptor);
        let surface = instance
            .create_surface(window.clone())
            .map_err(|error| RenderError::Surface(error.to_string()))?;
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                force_fallback_adapter: false,
                compatible_surface: Some(&surface),
                apply_limit_buckets: false,
            })
            .await
            .map_err(|_| RenderError::NoAdapter)?;
        let required_features = requested_renderer_features(adapter.features());
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("CDMW Rust Mesh Lab device"),
                required_features,
                required_limits: wgpu::Limits::default(),
                experimental_features: wgpu::ExperimentalFeatures::disabled(),
                memory_hints: wgpu::MemoryHints::Performance,
                trace: wgpu::Trace::Off,
            })
            .await
            .map_err(|error| RenderError::Device(error.to_string()))?;
        let size = window.inner_size();
        let capabilities = surface.get_capabilities(&adapter);
        let format =
            preferred_surface_format(&capabilities.formats).ok_or(RenderError::SurfaceFormat)?;
        let present_mode = preferred_present_mode(&capabilities.present_modes)
            .ok_or(RenderError::SurfaceFormat)?;
        let alpha_mode = capabilities
            .alpha_modes
            .first()
            .copied()
            .ok_or(RenderError::SurfaceFormat)?;
        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            color_space: wgpu::SurfaceColorSpace::Auto,
            width: size.width.max(1),
            height: size.height.max(1),
            present_mode,
            alpha_mode,
            view_formats: Vec::new(),
            desired_maximum_frame_latency: 2,
        };
        surface.configure(&device, &config);
        let sample_count = preferred_sample_count(&adapter, format);
        let anisotropy_clamp =
            preferred_anisotropy_clamp(adapter.get_downlevel_capabilities().flags);
        let texture_bind_group_layout = create_texture_bind_group_layout(&device);
        let default_material_textures = create_default_material_textures(&device, &queue);
        let material_sampler = create_material_sampler(&device, anisotropy_clamp);
        let default_material_binding = create_material_bind_group(
            &device,
            &texture_bind_group_layout,
            &material_sampler,
            &default_material_textures,
            &[],
            MaterialTextureIndices::default(),
            MaterialPreviewFactors::default(),
        );
        let camera_bind_group_layout = create_camera_bind_group_layout(&device);
        let camera_uniform = CameraUniform::new(format.is_srgb());
        let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab camera uniform"),
            contents: bytemuck::bytes_of(&camera_uniform),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let camera_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("CDMW Rust Mesh Lab camera bind group"),
            layout: &camera_bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: camera_buffer.as_entire_binding(),
            }],
        });
        let pipelines = create_pipelines_with_sample_count(
            &device,
            format,
            &texture_bind_group_layout,
            &camera_bind_group_layout,
            sample_count,
        );
        let depth_target = create_depth_target_with_sample_count(
            &device,
            config.width,
            config.height,
            sample_count,
        );
        let multisample_target =
            create_multisample_target(&device, format, config.width, config.height, sample_count);
        let egui_renderer =
            egui_wgpu::Renderer::new(&device, format, egui_wgpu::RendererOptions::default());
        let clear_colour = clear_colour_for_target([0.025, 0.03, 0.04, 1.0], format.is_srgb());
        Ok(Self {
            _instance: instance,
            surface,
            adapter,
            device,
            queue,
            config,
            solid_pipeline: pipelines.solid,
            wire_pipeline: pipelines.wire,
            xray_wire_pipeline: pipelines.xray_wire,
            point_pipeline: pipelines.point,
            xray_pipeline: pipelines.xray,
            normal_pipeline: pipelines.normal,
            bounds_pipeline: pipelines.bounds,
            bone_pipeline: pipelines.bone,
            mesh: None,
            skeleton_lines: None,
            preview_lines: None,
            egui_renderer,
            texture_bind_group_layout,
            default_material_binding,
            default_material_textures,
            material_sampler,
            material_textures: Vec::new(),
            material_factors: Vec::new(),
            active_material_bindings: BTreeMap::new(),
            mesh_viewport: None,
            depth_target,
            multisample_target,
            sample_count,
            anisotropy_clamp,
            upload_stats: MeshUploadStats::default(),
            camera_uniform,
            camera_buffer,
            camera_bind_group,
            view_mode: ViewMode::TexturedSolid,
            show_normals: false,
            show_bounds: false,
            show_bones: false,
            clear_colour,
        })
    }

    #[must_use]
    pub fn adapter_report(&self) -> AdapterReport {
        adapter_report(&self.adapter)
    }

    #[must_use]
    pub fn quality_report(&self) -> RendererQualityReport {
        RendererQualityReport {
            sample_count: self.sample_count,
            anisotropy_clamp: self.anisotropy_clamp,
            present_mode: format!("{:?}", self.config.present_mode),
        }
    }

    #[must_use]
    pub fn upload_stats(&self) -> MeshUploadStats {
        self.upload_stats
    }

    pub fn set_snapshot(&mut self, snapshot: &DrawSnapshot) -> Result<(), RenderError> {
        self.set_snapshot_with_deformation(snapshot, None)
    }

    pub fn set_snapshot_with_deformation(
        &mut self,
        snapshot: &DrawSnapshot,
        deformation_reference: Option<&[[f32; 3]]>,
    ) -> Result<(), RenderError> {
        self.set_snapshot_with_deformation_mode(
            snapshot,
            deformation_reference,
            GeometryUpdateMode::Final,
        )
    }

    pub fn set_snapshot_with_deformation_interactive(
        &mut self,
        snapshot: &DrawSnapshot,
        deformation_reference: Option<&[[f32; 3]]>,
    ) -> Result<(), RenderError> {
        self.set_snapshot_with_deformation_mode(
            snapshot,
            deformation_reference,
            GeometryUpdateMode::Interactive,
        )
    }

    fn set_snapshot_with_deformation_mode(
        &mut self,
        snapshot: &DrawSnapshot,
        deformation_reference: Option<&[[f32; 3]]>,
        update_mode: GeometryUpdateMode,
    ) -> Result<(), RenderError> {
        let deformation_signature = deformation_signature(deformation_reference)?;
        let mut action = self
            .mesh
            .as_ref()
            .map_or(MeshUploadAction::Replace, |mesh| {
                mesh.upload_action(snapshot, deformation_signature)
            });
        action = resolve_mesh_upload_action(
            action,
            update_mode,
            self.mesh.as_ref().is_none_or(|mesh| mesh.tangents_exact),
        );
        match action {
            MeshUploadAction::Reuse => {
                self.upload_stats.unchanged_reuses =
                    self.upload_stats.unchanged_reuses.saturating_add(1);
            }
            MeshUploadAction::UpdateGeometry => {
                self.mesh
                    .as_mut()
                    .expect("geometry update requires an existing GPU mesh")
                    .refresh_geometry(
                        &self.queue,
                        snapshot,
                        deformation_reference,
                        deformation_signature,
                        update_mode,
                    )?;
                self.upload_stats.in_place_geometry_updates = self
                    .upload_stats
                    .in_place_geometry_updates
                    .saturating_add(1);
            }
            MeshUploadAction::Replace => {
                self.mesh = Some(GpuMeshBuffers::upload_with_deformation(
                    &self.device,
                    snapshot,
                    deformation_reference,
                )?);
                self.upload_stats.full_uploads = self.upload_stats.full_uploads.saturating_add(1);
            }
        }
        Ok(())
    }

    pub fn set_camera(&mut self, view_projection: Mat4) {
        let view_direction = view_direction_from_view_projection(view_projection)
            .extend(0.0)
            .to_array();
        let view_projection = view_projection.to_cols_array_2d();
        if self.camera_uniform.view_projection == view_projection
            && self.camera_uniform.view_direction == view_direction
        {
            return;
        }
        self.camera_uniform.view_projection = view_projection;
        self.camera_uniform.view_direction = view_direction;
        self.queue.write_buffer(
            &self.camera_buffer,
            0,
            bytemuck::bytes_of(&self.camera_uniform),
        );
    }

    pub fn set_view_mode(&mut self, view_mode: ViewMode) {
        if self.view_mode == view_mode {
            return;
        }
        self.view_mode = view_mode;
        self.camera_uniform.view_mode = view_mode.shader_mode();
        self.queue.write_buffer(
            &self.camera_buffer,
            0,
            bytemuck::bytes_of(&self.camera_uniform),
        );
    }

    pub fn set_overlays(&mut self, show_normals: bool, show_bounds: bool) {
        self.show_normals = show_normals;
        self.show_bounds = show_bounds;
    }

    pub fn set_overlay_colours(&mut self, wire_colour: [f32; 4], point_colour: [f32; 4]) {
        let Some(wire_colour) = bounded_rgba(wire_colour) else {
            return;
        };
        let Some(point_colour) = bounded_rgba(point_colour) else {
            return;
        };
        let wire_colour = srgb_rgba_to_linear(wire_colour);
        let point_colour = srgb_rgba_to_linear(point_colour);
        if self.camera_uniform.wire_colour == wire_colour
            && self.camera_uniform.point_colour == point_colour
        {
            return;
        }
        self.camera_uniform.wire_colour = wire_colour;
        self.camera_uniform.point_colour = point_colour;
        self.queue.write_buffer(
            &self.camera_buffer,
            0,
            bytemuck::bytes_of(&self.camera_uniform),
        );
    }

    pub fn set_skeleton_lines(&mut self, positions: &[[f32; 3]]) -> Result<(), RenderError> {
        self.skeleton_lines = GpuOverlayLines::upload(&self.device, positions)?;
        if self.skeleton_lines.is_none() {
            self.show_bones = false;
        }
        Ok(())
    }

    /// Set transient Archive Preview guides (grid, cloth, gizmo and effects).
    /// They share the depth-independent overlay pipeline with skeleton guides,
    /// but are owned separately so toggling bones never removes scene aids.
    pub fn set_preview_lines(&mut self, positions: &[[f32; 3]]) -> Result<(), RenderError> {
        self.preview_lines = GpuOverlayLines::upload(&self.device, positions)?;
        Ok(())
    }

    pub fn set_bone_overlay(&mut self, show_bones: bool) {
        self.show_bones = show_bones && self.skeleton_lines.is_some();
    }

    pub fn set_clear_colour(&mut self, colour: [f32; 4]) {
        if let Some(colour) = bounded_rgba(colour) {
            self.clear_colour = clear_colour_for_target(colour, self.config.format.is_srgb());
        }
    }

    pub fn add_dds_texture(
        &mut self,
        bytes: &[u8],
        role: TextureRole,
        material_indices_by_lod: &[Vec<u32>],
    ) -> Result<(), RenderError> {
        validate_material_texture_ownership(role, material_indices_by_lod)?;
        let uploaded = upload_dds_texture(&self.device, &self.queue, bytes, role)?;
        self.material_textures.push(GpuMaterialTexture {
            _texture: uploaded.texture,
            role,
            single_channel: uploaded.single_channel,
            material_indices_by_lod: material_indices_by_lod.to_vec(),
        });
        Ok(())
    }

    pub fn add_material_factors(
        &mut self,
        factors: MaterialPreviewFactors,
        material_indices_by_lod: &[Vec<u32>],
    ) -> Result<(), RenderError> {
        validate_material_factor_ownership(factors, material_indices_by_lod)?;
        self.material_factors.push(MaterialFactorOwnership {
            factors,
            material_indices_by_lod: material_indices_by_lod.to_vec(),
        });
        Ok(())
    }

    pub fn reset_material_factors(&mut self) {
        self.material_factors.clear();
        self.active_material_bindings.clear();
    }

    pub fn set_material_lod(&mut self, lod_index: usize) -> Result<usize, RenderError> {
        let mut active = match resolve_material_bindings(
            self.material_textures
                .iter()
                .map(|texture| (texture.role, texture.material_indices_by_lod.as_slice())),
            lod_index,
        ) {
            Ok(active) => active,
            Err(error) => {
                self.active_material_bindings.clear();
                return Err(error);
            }
        };
        let factors = match resolve_material_factors(
            self.material_factors
                .iter()
                .map(|owned| (owned.factors, owned.material_indices_by_lod.as_slice())),
            lod_index,
        ) {
            Ok(factors) => factors,
            Err(error) => {
                self.active_material_bindings.clear();
                return Err(error);
            }
        };
        let bound = active.len();
        for material in factors.keys() {
            active.entry(*material).or_default();
        }
        self.active_material_bindings = active
            .into_iter()
            .map(|(material, indices)| {
                let binding = create_material_bind_group(
                    &self.device,
                    &self.texture_bind_group_layout,
                    &self.material_sampler,
                    &self.default_material_textures,
                    &self.material_textures,
                    indices,
                    factors.get(&material).copied().unwrap_or_default(),
                );
                (material, binding)
            })
            .collect();
        Ok(bound)
    }

    pub fn reset_texture(&mut self) {
        self.material_textures.clear();
        self.reset_material_factors();
    }

    pub fn set_mesh_viewport(&mut self, viewport: Option<[f32; 4]>) {
        self.mesh_viewport = viewport;
    }

    pub fn resize(&mut self, size: PhysicalSize<u32>) {
        if size.width == 0 || size.height == 0 {
            return;
        }
        if self.config.width == size.width && self.config.height == size.height {
            return;
        }
        self.config.width = size.width;
        self.config.height = size.height;
        self.surface.configure(&self.device, &self.config);
        self.depth_target = create_depth_target_with_sample_count(
            &self.device,
            size.width,
            size.height,
            self.sample_count,
        );
        self.multisample_target = create_multisample_target(
            &self.device,
            self.config.format,
            size.width,
            size.height,
            self.sample_count,
        );
    }

    pub fn render(&mut self) -> Result<(), RenderError> {
        self.render_frame(&[], None)
    }

    pub fn render_egui(
        &mut self,
        paint_jobs: &[egui::ClippedPrimitive],
        textures: &egui::TexturesDelta,
        pixels_per_point: f32,
    ) -> Result<(), RenderError> {
        self.render_frame(paint_jobs, Some((textures, pixels_per_point)))
    }

    fn render_frame(
        &mut self,
        paint_jobs: &[egui::ClippedPrimitive],
        egui_frame: Option<(&egui::TexturesDelta, f32)>,
    ) -> Result<(), RenderError> {
        let frame = match self.surface.get_current_texture() {
            wgpu::CurrentSurfaceTexture::Success(frame) => frame,
            wgpu::CurrentSurfaceTexture::Suboptimal(frame) => {
                self.surface.configure(&self.device, &self.config);
                frame
            }
            wgpu::CurrentSurfaceTexture::Timeout => {
                return Err(RenderError::SurfaceFrame("timeout".to_owned()));
            }
            wgpu::CurrentSurfaceTexture::Occluded => {
                return Err(RenderError::SurfaceFrame("occluded".to_owned()));
            }
            wgpu::CurrentSurfaceTexture::Outdated => {
                self.surface.configure(&self.device, &self.config);
                return Err(RenderError::SurfaceFrame("outdated".to_owned()));
            }
            wgpu::CurrentSurfaceTexture::Lost => {
                return Err(RenderError::SurfaceFrame("lost".to_owned()));
            }
            wgpu::CurrentSurfaceTexture::Validation => {
                return Err(RenderError::SurfaceFrame("validation".to_owned()));
            }
        };
        let view = frame
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("CDMW Rust Mesh Lab frame"),
            });
        let screen_descriptor =
            egui_frame.map(|(_, pixels_per_point)| egui_wgpu::ScreenDescriptor {
                size_in_pixels: [self.config.width, self.config.height],
                pixels_per_point,
            });
        let mut command_buffers = Vec::new();
        if let Some((textures, _)) = egui_frame {
            for (id, deltas) in &textures.set {
                for delta in deltas {
                    self.egui_renderer
                        .update_texture(&self.device, &self.queue, *id, delta);
                }
            }
            if let Some(descriptor) = &screen_descriptor {
                command_buffers = self.egui_renderer.update_buffers(
                    &self.device,
                    &self.queue,
                    &mut encoder,
                    paint_jobs,
                    descriptor,
                );
            }
        }
        {
            let (mesh_color_view, resolve_target, store) =
                if let Some(target) = &self.multisample_target {
                    (&target.view, Some(&view), wgpu::StoreOp::Discard)
                } else {
                    (&view, None, wgpu::StoreOp::Store)
                };
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("CDMW Rust Mesh Lab viewport"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: mesh_color_view,
                    resolve_target,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(self.clear_colour),
                        store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth_target.view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            if let Some(mesh) = &self.mesh {
                if let Some([x, y, width, height]) = self.mesh_viewport {
                    let maximum_x = self.config.width.saturating_sub(1) as f32;
                    let maximum_y = self.config.height.saturating_sub(1) as f32;
                    let x = x.clamp(0.0, maximum_x);
                    let y = y.clamp(0.0, maximum_y);
                    let width = width.max(1.0).min(self.config.width as f32 - x);
                    let height = height.max(1.0).min(self.config.height as f32 - y);
                    pass.set_viewport(x, y, width, height, 0.0, 1.0);
                    let scissor_x = x.floor() as u32;
                    let scissor_y = y.floor() as u32;
                    let scissor_right = (x + width).ceil().min(self.config.width as f32) as u32;
                    let scissor_bottom = (y + height).ceil().min(self.config.height as f32) as u32;
                    pass.set_scissor_rect(
                        scissor_x,
                        scissor_y,
                        scissor_right.saturating_sub(scissor_x).max(1),
                        scissor_bottom.saturating_sub(scissor_y).max(1),
                    );
                }
                draw_mesh(
                    &mut pass,
                    mesh,
                    &self.default_material_binding.bind_group,
                    &self.active_material_bindings,
                    &self.camera_bind_group,
                    &self.solid_pipeline,
                    &self.wire_pipeline,
                    &self.xray_wire_pipeline,
                    &self.point_pipeline,
                    &self.xray_pipeline,
                    &self.normal_pipeline,
                    &self.bounds_pipeline,
                    &self.bone_pipeline,
                    self.skeleton_lines.as_ref(),
                    self.preview_lines.as_ref(),
                    self.view_mode,
                    self.show_normals,
                    self.show_bounds,
                    self.show_bones,
                );
            }
        }
        if let Some(descriptor) = &screen_descriptor {
            let ui_pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("CDMW Rust Mesh Lab egui"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            self.egui_renderer
                .render(&mut ui_pass.forget_lifetime(), paint_jobs, descriptor);
        }
        command_buffers.push(encoder.finish());
        self.queue.submit(command_buffers);
        self.queue.present(frame);
        if let Some((textures, _)) = egui_frame {
            for id in &textures.free {
                self.egui_renderer.free_texture(id);
            }
        }
        Ok(())
    }
}

fn material_texture_role_is_sampled(role: TextureRole) -> bool {
    matches!(
        role,
        TextureRole::BaseColor
            | TextureRole::Normal
            | TextureRole::Material
            | TextureRole::Roughness
            | TextureRole::Metalness
            | TextureRole::Occlusion
            | TextureRole::Emissive
            | TextureRole::Specular
            | TextureRole::Glossiness
            | TextureRole::Opacity
            | TextureRole::Height
            | TextureRole::Flow
            | TextureRole::LayerMask
            | TextureRole::SkinDetailMask
            | TextureRole::SkinDetailNormal
            | TextureRole::SkinDetailMaterial
    )
}

fn validate_material_texture_ownership(
    role: TextureRole,
    material_indices_by_lod: &[Vec<u32>],
) -> Result<(), RenderError> {
    if material_indices_by_lod.iter().all(Vec::is_empty) {
        return Err(RenderError::Texture(
            "DDS texture has no owning material range".to_owned(),
        ));
    }
    if !material_texture_role_is_sampled(role) {
        return Err(RenderError::Texture(format!(
            "the {role:?} role is classified but is not sampled by the current material approximation"
        )));
    }
    Ok(())
}

fn validate_material_factor_ownership(
    factors: MaterialPreviewFactors,
    material_indices_by_lod: &[Vec<u32>],
) -> Result<(), RenderError> {
    if material_indices_by_lod.iter().all(Vec::is_empty) {
        return Err(RenderError::Texture(
            "material factors have no owning material range".to_owned(),
        ));
    }
    if factors.emissive_color.is_none()
        && factors.emissive_intensity.is_none()
        && factors.roughness.is_none()
        && factors.metalness.is_none()
        && factors.specular.is_none()
        && factors.height_scale.is_none()
        && factors.texture_tint.is_none()
        && factors.alpha_cutoff.is_none()
        && factors.hair_anisotropy.is_none()
        && factors.layer_mask_channel.is_none()
        && factors.category_code.is_none()
        && factors.category_confidence.is_none()
        && factors.normal_y_inverted.is_none()
        && factors.skin_detail_scale.is_none()
        && factors.skin_detail_opacity.is_none()
    {
        return Err(RenderError::Texture(
            "material factor set contains no sampled value".to_owned(),
        ));
    }
    if factors.emissive_color.is_some_and(|color| {
        color
            .into_iter()
            .any(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
    }) || factors.texture_tint.is_some_and(|color| {
        color
            .into_iter()
            .any(|value| !value.is_finite() || !(0.0..=2.0).contains(&value))
    }) || factors
        .emissive_intensity
        .is_some_and(|value| !value.is_finite() || !(0.0..=32.0).contains(&value))
        || [
            factors.roughness,
            factors.metalness,
            factors.specular,
            factors.height_scale,
            factors.base_tint_strength,
            factors.alpha_cutoff,
            factors.category_confidence,
        ]
        .into_iter()
        .flatten()
        .any(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
    {
        return Err(RenderError::Texture(
            "material factors contain a non-finite or out-of-range value".to_owned(),
        ));
    }
    if factors.category_code.is_some_and(|code| code > 11) {
        return Err(RenderError::Texture(
            "material category code is outside the shared CDMW contract".to_owned(),
        ));
    }
    if factors
        .skin_detail_scale
        .is_some_and(|value| !value.is_finite() || !(0.001..=1.0).contains(&value))
    {
        return Err(RenderError::Texture(
            "skin detail scale is outside 0.001..=1".to_owned(),
        ));
    }
    if factors
        .skin_detail_opacity
        .is_some_and(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
    {
        return Err(RenderError::Texture(
            "skin detail opacity is outside 0..=1".to_owned(),
        ));
    }
    Ok(())
}

pub async fn run_headless_render_smoke(
    snapshot: &DrawSnapshot,
) -> Result<HeadlessRenderReport, RenderError> {
    run_headless_render_smoke_internal(snapshot, None).await
}

pub async fn run_headless_render_smoke_with_material_proof(
    snapshot: &DrawSnapshot,
    proof_path: &Path,
) -> Result<HeadlessRenderReport, RenderError> {
    run_headless_render_smoke_internal(snapshot, Some(proof_path)).await
}

pub async fn run_headless_material_capture(
    snapshot: &DrawSnapshot,
    textures: &[HeadlessMaterialTexture<'_>],
    factors: &[HeadlessMaterialFactors<'_>],
    options: HeadlessMaterialCaptureOptions,
    output: HeadlessMaterialCaptureOutput<'_>,
) -> Result<HeadlessMaterialCaptureReport, RenderError> {
    if options.width == 0 || options.height == 0 || options.width > 4_096 || options.height > 4_096
    {
        return Err(RenderError::ResourceLimit);
    }
    let mut instance_descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    instance_descriptor.backends = wgpu::Backends::DX12;
    let instance = wgpu::Instance::new(instance_descriptor);
    let adapter = instance
        .request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: false,
            compatible_surface: None,
            apply_limit_buckets: false,
        })
        .await
        .map_err(|_| RenderError::NoAdapter)?;
    let required_features = requested_renderer_features(adapter.features());
    let (device, queue) = adapter
        .request_device(&wgpu::DeviceDescriptor {
            label: Some("CDMW Rust Mesh Lab material capture device"),
            required_features,
            required_limits: wgpu::Limits::default(),
            experimental_features: wgpu::ExperimentalFeatures::disabled(),
            memory_hints: wgpu::MemoryHints::Performance,
            trace: wgpu::Trace::Off,
        })
        .await
        .map_err(|error| RenderError::Device(error.to_string()))?;
    let error_scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
    let format = wgpu::TextureFormat::Bgra8UnormSrgb;
    let sample_count = preferred_sample_count(&adapter, format);
    let anisotropy_clamp = preferred_anisotropy_clamp(adapter.get_downlevel_capabilities().flags);
    let texture_layout = create_texture_bind_group_layout(&device);
    let default_material_textures = create_default_material_textures(&device, &queue);
    let material_sampler = create_material_sampler(&device, anisotropy_clamp);
    let default_material_binding = create_material_bind_group(
        &device,
        &texture_layout,
        &material_sampler,
        &default_material_textures,
        &[],
        MaterialTextureIndices::default(),
        MaterialPreviewFactors::default(),
    );

    let mut material_textures = Vec::with_capacity(textures.len());
    for texture in textures {
        validate_material_texture_ownership(texture.role, texture.material_indices_by_lod)?;
        let uploaded = upload_dds_texture(&device, &queue, texture.bytes, texture.role)?;
        material_textures.push(GpuMaterialTexture {
            _texture: uploaded.texture,
            role: texture.role,
            single_channel: uploaded.single_channel,
            material_indices_by_lod: texture.material_indices_by_lod.to_vec(),
        });
    }
    let mut material_factors = Vec::with_capacity(factors.len());
    for factor in factors {
        validate_material_factor_ownership(factor.factors, factor.material_indices_by_lod)?;
        material_factors.push(MaterialFactorOwnership {
            factors: factor.factors,
            material_indices_by_lod: factor.material_indices_by_lod.to_vec(),
        });
    }
    let mut resolved = resolve_material_bindings(
        material_textures
            .iter()
            .map(|texture| (texture.role, texture.material_indices_by_lod.as_slice())),
        options.lod_index,
    )?;
    let texture_bound_materials = resolved.len();
    let resolved_factors = resolve_material_factors(
        material_factors
            .iter()
            .map(|factor| (factor.factors, factor.material_indices_by_lod.as_slice())),
        options.lod_index,
    )?;
    for material in resolved_factors.keys() {
        resolved.entry(*material).or_default();
    }
    let active_material_bindings = resolved
        .into_iter()
        .map(|(material, indices)| {
            let binding = create_material_bind_group(
                &device,
                &texture_layout,
                &material_sampler,
                &default_material_textures,
                &material_textures,
                indices,
                resolved_factors.get(&material).copied().unwrap_or_default(),
            );
            (material, binding)
        })
        .collect::<BTreeMap<_, _>>();

    let camera_layout = create_camera_bind_group_layout(&device);
    let mut camera_uniform = CameraUniform::new(format.is_srgb());
    let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("CDMW Rust Mesh Lab material capture camera uniform"),
        contents: bytemuck::bytes_of(&camera_uniform),
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
    });
    let camera_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("CDMW Rust Mesh Lab material capture camera bind group"),
        layout: &camera_layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: camera_buffer.as_entire_binding(),
        }],
    });
    let pipelines = create_pipelines_with_sample_count(
        &device,
        format,
        &texture_layout,
        &camera_layout,
        sample_count,
    );
    let mesh = GpuMeshBuffers::upload(&device, snapshot)?;
    let view_projection = headless_capture_view_projection(snapshot, options.width, options.height);
    let mut render = |view_mode| {
        render_headless_readback_at(
            &device,
            &queue,
            format,
            &mesh,
            &default_material_binding.bind_group,
            &active_material_bindings,
            &camera_bind_group,
            &pipelines,
            &mut camera_uniform,
            &camera_buffer,
            view_mode,
            options.width,
            options.height,
            view_projection,
            None,
            false,
        )
    };
    let textured_readback = render(ViewMode::TexturedSolid);
    let base_color_readback = render(ViewMode::BaseColor);
    let part_id_readback = render(ViewMode::PartId);
    if let Some(error) = error_scope.pop().await {
        return Err(RenderError::Device(format!(
            "material capture validation failed: {error}"
        )));
    }
    let textured_pixels = read_headless_pixels(
        &device,
        &textured_readback.0,
        textured_readback.1,
        textured_readback.2,
    )?;
    let base_color_pixels = read_headless_pixels(
        &device,
        &base_color_readback.0,
        base_color_readback.1,
        base_color_readback.2,
    )?;
    let part_id_pixels = read_headless_pixels(
        &device,
        &part_id_readback.0,
        part_id_readback.1,
        part_id_readback.2,
    )?;
    write_bgra_bmp(
        output.textured_bmp,
        options.width,
        options.height,
        &textured_pixels,
    )?;
    write_bgra_bmp(
        output.base_color_bmp,
        options.width,
        options.height,
        &base_color_pixels,
    )?;
    write_bgra_bmp(
        output.part_id_bmp,
        options.width,
        options.height,
        &part_id_pixels,
    )?;
    let textured = headless_frame_stats(&textured_pixels)?;
    let base_color = headless_frame_stats(&base_color_pixels)?;
    let part_id = headless_frame_stats(&part_id_pixels)?;
    if textured.non_background_pixels == 0
        || base_color.non_background_pixels == 0
        || part_id.non_background_pixels == 0
    {
        return Err(RenderError::Device(
            "material capture contained only the clear color".to_owned(),
        ));
    }
    let owner_coverage = headless_material_owner_coverage(
        &mesh.material_ranges,
        &textured_pixels,
        &base_color_pixels,
        &part_id_pixels,
    )?;
    Ok(HeadlessMaterialCaptureReport {
        adapter: adapter_report(&adapter),
        sample_count,
        anisotropy_clamp,
        width: options.width,
        height: options.height,
        lod_index: options.lod_index,
        dds_textures_uploaded: u32::try_from(material_textures.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        texture_bound_materials: u32::try_from(texture_bound_materials)
            .map_err(|_| RenderError::ResourceLimit)?,
        active_material_bindings: u32::try_from(active_material_bindings.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        material_ranges_rendered: u32::try_from(mesh.material_ranges.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        textured,
        base_color,
        part_id,
        owner_coverage,
    })
}

async fn run_headless_render_smoke_internal(
    snapshot: &DrawSnapshot,
    proof_path: Option<&Path>,
) -> Result<HeadlessRenderReport, RenderError> {
    let mut instance_descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    instance_descriptor.backends = wgpu::Backends::DX12;
    let instance = wgpu::Instance::new(instance_descriptor);
    let adapter = instance
        .request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: false,
            compatible_surface: None,
            apply_limit_buckets: false,
        })
        .await
        .map_err(|_| RenderError::NoAdapter)?;
    let required_features = requested_renderer_features(adapter.features());
    let (device, queue) = adapter
        .request_device(&wgpu::DeviceDescriptor {
            label: Some("CDMW Rust Mesh Lab headless device"),
            required_features,
            required_limits: wgpu::Limits::default(),
            experimental_features: wgpu::ExperimentalFeatures::disabled(),
            memory_hints: wgpu::MemoryHints::Performance,
            trace: wgpu::Trace::Off,
        })
        .await
        .map_err(|error| RenderError::Device(error.to_string()))?;
    let error_scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
    let format = wgpu::TextureFormat::Bgra8UnormSrgb;
    let sample_count = preferred_sample_count(&adapter, format);
    let anisotropy_clamp = preferred_anisotropy_clamp(adapter.get_downlevel_capabilities().flags);
    let texture_layout = create_texture_bind_group_layout(&device);
    let default_material_textures = create_default_material_textures(&device, &queue);
    let material_sampler = create_material_sampler(&device, anisotropy_clamp);
    let default_material_binding = create_material_bind_group(
        &device,
        &texture_layout,
        &material_sampler,
        &default_material_textures,
        &[],
        MaterialTextureIndices::default(),
        MaterialPreviewFactors::default(),
    );
    let synthetic_dds = |color: [u8; 4]| {
        let mut bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        if let Some(pixels) = bytes.get_mut(148..164) {
            for pixel in pixels.chunks_exact_mut(4) {
                pixel.copy_from_slice(&color);
            }
        }
        bytes
    };
    let synthetic_opacity_dds = || {
        let mut bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        if let Some(pixels) = bytes.get_mut(148..164) {
            for (index, pixel) in pixels.chunks_exact_mut(4).enumerate() {
                let opacity = if index.is_multiple_of(2) { 0 } else { 255 };
                pixel.copy_from_slice(&[opacity, opacity, opacity, 255]);
            }
        }
        bytes
    };
    let synthetic_flow_dds = || {
        let mut bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        if let Some(pixels) = bytes.get_mut(148..164) {
            for (pixel, flow) in pixels.chunks_exact_mut(4).zip([
                [255, 128, 0, 255],
                [128, 255, 0, 255],
                [0, 128, 0, 255],
                [128, 0, 0, 255],
            ]) {
                pixel.copy_from_slice(&flow);
            }
        }
        bytes
    };
    let synthetic_layer_mask_dds = || {
        let mut bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        if let Some(pixels) = bytes.get_mut(148..164) {
            for (pixel, mask) in pixels.chunks_exact_mut(4).zip([
                [32, 0, 224, 255],
                [224, 0, 32, 255],
                [64, 0, 192, 255],
                [192, 0, 64, 255],
            ]) {
                pixel.copy_from_slice(&mask);
            }
        }
        bytes
    };
    let mut material_textures = Vec::new();
    for (material, role, bytes) in [
        (
            0_u32,
            TextureRole::BaseColor,
            synthetic_dds([210, 70, 55, 255]),
        ),
        (
            0_u32,
            TextureRole::Normal,
            // Bias the probe strongly along tangent X.  The previous, mild
            // bitangent-only tilt could quantize to the same final colour as
            // the neutral normal under the camera-relative fill lights on
            // some D3D12 drivers, which made the GPU contract flaky even
            // though normal sampling was active.
            synthetic_dds([230, 128, 204, 255]),
        ),
        (
            0_u32,
            TextureRole::Material,
            synthetic_dds([255, 70, 230, 255]),
        ),
        (
            0_u32,
            TextureRole::Roughness,
            synthetic_dds([20, 0, 0, 255]),
        ),
        (
            0_u32,
            TextureRole::Metalness,
            synthetic_dds([235, 0, 0, 255]),
        ),
        (
            0_u32,
            TextureRole::Occlusion,
            synthetic_dds([30, 0, 0, 255]),
        ),
        (
            0_u32,
            TextureRole::Emissive,
            synthetic_dds([90, 30, 10, 255]),
        ),
        (
            0_u32,
            TextureRole::Specular,
            synthetic_dds([250, 180, 60, 255]),
        ),
        (0_u32, TextureRole::Opacity, synthetic_opacity_dds()),
        (
            0_u32,
            TextureRole::Height,
            cdmw_texture::synthetic::rgba8_checker_dds(),
        ),
        (0_u32, TextureRole::Flow, synthetic_flow_dds()),
        (0_u32, TextureRole::LayerMask, synthetic_layer_mask_dds()),
        (
            1_u32,
            TextureRole::BaseColor,
            synthetic_dds([128, 128, 128, 255]),
        ),
        (
            1_u32,
            TextureRole::Metalness,
            synthetic_dds([220, 0, 0, 255]),
        ),
        (
            1_u32,
            TextureRole::Glossiness,
            synthetic_dds([230, 160, 40, 255]),
        ),
        (
            2_u32,
            TextureRole::BaseColor,
            synthetic_dds([184, 78, 32, 255]),
        ),
    ] {
        let uploaded = upload_dds_texture(&device, &queue, &bytes, role)?;
        material_textures.push(GpuMaterialTexture {
            _texture: uploaded.texture,
            role,
            single_channel: uploaded.single_channel,
            material_indices_by_lod: vec![vec![material]],
        });
    }
    let resolved_bindings = resolve_material_bindings(
        material_textures
            .iter()
            .map(|texture| (texture.role, texture.material_indices_by_lod.as_slice())),
        0,
    )?;
    let bindings_for_roles = |roles: &[TextureRole], factors: MaterialPreviewFactors| {
        resolved_bindings
            .iter()
            .map(|(material, indices)| {
                let selected = MaterialTextureIndices {
                    base_color: if roles.contains(&TextureRole::BaseColor) {
                        indices.base_color
                    } else {
                        None
                    },
                    normal: if roles.contains(&TextureRole::Normal) {
                        indices.normal
                    } else {
                        None
                    },
                    surface: if roles.contains(&TextureRole::Material) {
                        indices.surface
                    } else {
                        None
                    },
                    roughness: if roles.contains(&TextureRole::Roughness) {
                        indices.roughness
                    } else {
                        None
                    },
                    metalness: if roles.contains(&TextureRole::Metalness) {
                        indices.metalness
                    } else {
                        None
                    },
                    occlusion: if roles.contains(&TextureRole::Occlusion) {
                        indices.occlusion
                    } else {
                        None
                    },
                    emissive: if roles.contains(&TextureRole::Emissive) {
                        indices.emissive
                    } else {
                        None
                    },
                    specular: indices
                        .specular
                        .filter(|index| roles.contains(&material_textures[*index].role)),
                    glossiness: if roles.contains(&TextureRole::Glossiness) {
                        indices.glossiness
                    } else {
                        None
                    },
                    opacity: if roles.contains(&TextureRole::Opacity) {
                        indices.opacity
                    } else {
                        None
                    },
                    height: if roles.contains(&TextureRole::Height) {
                        indices.height
                    } else {
                        None
                    },
                    flow: if roles.contains(&TextureRole::Flow) {
                        indices.flow
                    } else {
                        None
                    },
                    layer_mask: if roles.contains(&TextureRole::LayerMask) {
                        indices.layer_mask
                    } else {
                        None
                    },
                    skin_detail_mask: if roles.contains(&TextureRole::SkinDetailMask) {
                        indices.skin_detail_mask
                    } else {
                        None
                    },
                    skin_detail_normal: if roles.contains(&TextureRole::SkinDetailNormal) {
                        indices.skin_detail_normal
                    } else {
                        None
                    },
                    skin_detail_material: if roles.contains(&TextureRole::SkinDetailMaterial) {
                        indices.skin_detail_material
                    } else {
                        None
                    },
                };
                (
                    *material,
                    create_material_bind_group(
                        &device,
                        &texture_layout,
                        &material_sampler,
                        &default_material_textures,
                        &material_textures,
                        selected,
                        factors,
                    ),
                )
            })
            .collect::<BTreeMap<_, _>>()
    };
    let base_only_material_bindings =
        bindings_for_roles(&[TextureRole::BaseColor], MaterialPreviewFactors::default());
    let category_material_bindings = [
        ("metal", 1_u32),
        ("leather", 2_u32),
        ("cloth", 4_u32),
        ("skin", 5_u32),
        ("glass", 7_u32),
    ]
    .map(|(label, category_code)| {
        (
            label,
            bindings_for_roles(
                &[TextureRole::BaseColor],
                MaterialPreviewFactors {
                    metalness: (category_code == 1).then_some(1.0),
                    specular: (category_code == 1).then_some(0.9),
                    category_code: Some(category_code),
                    category_confidence: Some(1.0),
                    ..MaterialPreviewFactors::default()
                },
            ),
        )
    });
    let layer_mask_fallback_material_bindings =
        bindings_for_roles(&[TextureRole::BaseColor], MaterialPreviewFactors::default());
    let base_normal_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Normal],
        MaterialPreviewFactors::default(),
    );
    let base_surface_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Material],
        MaterialPreviewFactors::default(),
    );
    let base_roughness_material_bindings = bindings_for_roles(
        &[
            TextureRole::BaseColor,
            TextureRole::Metalness,
            TextureRole::Roughness,
        ],
        MaterialPreviewFactors::default(),
    );
    let base_metalness_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Metalness],
        MaterialPreviewFactors::default(),
    );
    let base_occlusion_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Occlusion],
        MaterialPreviewFactors::default(),
    );
    let base_emissive_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Emissive],
        MaterialPreviewFactors::default(),
    );
    let base_specular_material_bindings = bindings_for_roles(
        &[
            TextureRole::BaseColor,
            TextureRole::Metalness,
            TextureRole::Specular,
        ],
        MaterialPreviewFactors::default(),
    );
    let dielectric_specular_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Specular],
        MaterialPreviewFactors::default(),
    );
    let glossiness_material_bindings = bindings_for_roles(
        &[
            TextureRole::BaseColor,
            TextureRole::Metalness,
            TextureRole::Glossiness,
        ],
        MaterialPreviewFactors::default(),
    );
    let dielectric_glossiness_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Glossiness],
        MaterialPreviewFactors::default(),
    );
    let opaque_opacity_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Opacity],
        MaterialPreviewFactors::default(),
    );
    let opacity_cutout_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Opacity],
        MaterialPreviewFactors {
            alpha_cutoff: Some(0.5),
            ..MaterialPreviewFactors::default()
        },
    );
    let height_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Height],
        MaterialPreviewFactors {
            height_scale: Some(0.85),
            ..MaterialPreviewFactors::default()
        },
    );
    let disabled_height_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Height],
        MaterialPreviewFactors {
            height_scale: Some(0.0),
            ..MaterialPreviewFactors::default()
        },
    );
    let non_hair_flow_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Flow],
        MaterialPreviewFactors::default(),
    );
    let hair_flow_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Flow],
        MaterialPreviewFactors {
            hair_anisotropy: Some(true),
            ..MaterialPreviewFactors::default()
        },
    );
    let layer_mask_red_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::LayerMask],
        MaterialPreviewFactors {
            layer_mask_channel: Some(0),
            ..MaterialPreviewFactors::default()
        },
    );
    let layer_mask_blue_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::LayerMask],
        MaterialPreviewFactors {
            layer_mask_channel: Some(2),
            ..MaterialPreviewFactors::default()
        },
    );
    let factored_emissive_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Emissive],
        MaterialPreviewFactors {
            emissive_color: Some([0.05, 0.8, 0.2]),
            emissive_intensity: Some(3.0),
            ..MaterialPreviewFactors::default()
        },
    );
    let roughness_factor_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor],
        MaterialPreviewFactors {
            roughness: Some(0.05),
            metalness: Some(0.85),
            ..MaterialPreviewFactors::default()
        },
    );
    let metalness_factor_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor],
        MaterialPreviewFactors {
            metalness: Some(0.85),
            ..MaterialPreviewFactors::default()
        },
    );
    let metal_specular_factor_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor],
        MaterialPreviewFactors {
            metalness: Some(0.85),
            specular: Some(1.0),
            ..MaterialPreviewFactors::default()
        },
    );
    let active_material_bindings = bindings_for_roles(
        &[
            TextureRole::BaseColor,
            TextureRole::Normal,
            TextureRole::Material,
            TextureRole::Roughness,
            TextureRole::Metalness,
            TextureRole::Occlusion,
            TextureRole::Emissive,
            TextureRole::Specular,
            TextureRole::Glossiness,
            TextureRole::Opacity,
            TextureRole::Height,
            TextureRole::Flow,
            TextureRole::LayerMask,
        ],
        MaterialPreviewFactors {
            alpha_cutoff: Some(0.5),
            hair_anisotropy: Some(true),
            layer_mask_channel: Some(2),
            ..MaterialPreviewFactors::default()
        },
    );
    let camera_layout = create_camera_bind_group_layout(&device);
    let mut camera_uniform = CameraUniform::new(format.is_srgb());
    let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("CDMW Rust Mesh Lab headless camera uniform"),
        contents: bytemuck::bytes_of(&camera_uniform),
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
    });
    let camera_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("CDMW Rust Mesh Lab headless camera bind group"),
        layout: &camera_layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: camera_buffer.as_entire_binding(),
        }],
    });
    let pipelines = create_pipelines_with_sample_count(
        &device,
        format,
        &texture_layout,
        &camera_layout,
        sample_count,
    );
    let mut render_snapshot = snapshot.clone();
    render_snapshot.triangle_materials.fill(0);
    let first_triangle = render_snapshot.indices.get(..3).ok_or_else(|| {
        RenderError::InvalidSnapshot(
            "headless material proof requires at least one triangle".to_owned(),
        )
    })?;
    let source_indices = [
        usize::try_from(first_triangle[0]).map_err(|_| RenderError::ResourceLimit)?,
        usize::try_from(first_triangle[1]).map_err(|_| RenderError::ResourceLimit)?,
        usize::try_from(first_triangle[2]).map_err(|_| RenderError::ResourceLimit)?,
    ];
    let mut copied_positions = Vec::with_capacity(3);
    let mut copied_normals = Vec::with_capacity(3);
    let mut copied_uvs = Vec::with_capacity(3);
    for index in source_indices {
        let position = render_snapshot
            .positions
            .get(index)
            .copied()
            .ok_or_else(|| {
                RenderError::InvalidSnapshot(format!(
                    "triangle index {index} exceeds the vertex count"
                ))
            })?;
        let normal = render_snapshot.normals.get(index).copied().ok_or_else(|| {
            RenderError::InvalidSnapshot(format!("triangle index {index} exceeds the normal count"))
        })?;
        let uv = render_snapshot.uvs.get(index).copied().ok_or_else(|| {
            RenderError::InvalidSnapshot(format!(
                "triangle index {index} exceeds the texture-coordinate count"
            ))
        })?;
        copied_positions.push([position[0] + 1.25, position[1], position[2]]);
        copied_normals.push(normal);
        copied_uvs.push(uv);
    }
    let first_new_index =
        u32::try_from(render_snapshot.positions.len()).map_err(|_| RenderError::ResourceLimit)?;
    render_snapshot.positions.extend(copied_positions);
    render_snapshot.normals.extend(copied_normals);
    render_snapshot.uvs.extend(copied_uvs);
    render_snapshot.indices.extend_from_slice(&[
        first_new_index,
        first_new_index.saturating_add(1),
        first_new_index.saturating_add(2),
    ]);
    render_snapshot.triangle_materials.push(1);
    let mut mesh = GpuMeshBuffers::upload(&device, &render_snapshot)?;
    if !mesh.matches_snapshot(&render_snapshot) {
        return Err(RenderError::Device(
            "headless mesh cache rejected its current snapshot".to_owned(),
        ));
    }
    let mut different_mesh = render_snapshot.clone();
    different_mesh.mesh_identity = different_mesh.mesh_identity.wrapping_add(1);
    if mesh.matches_snapshot(&different_mesh) {
        return Err(RenderError::Device(
            "headless mesh cache reused buffers for a different mesh with equal revisions"
                .to_owned(),
        ));
    }
    let mut refreshed_mesh = render_snapshot.clone();
    refreshed_mesh.draw_revision = refreshed_mesh.draw_revision.wrapping_add(1);
    if let Some(position) = refreshed_mesh.positions.first_mut() {
        position[0] += 0.001;
    }
    if mesh.upload_action(&refreshed_mesh, 0) != MeshUploadAction::UpdateGeometry {
        return Err(RenderError::Device(
            "headless mesh cache did not choose an in-place same-topology refresh".to_owned(),
        ));
    }
    mesh.refresh_geometry(&queue, &refreshed_mesh, None, 0, GeometryUpdateMode::Final)?;
    if !mesh.matches_snapshot(&refreshed_mesh) {
        return Err(RenderError::Device(
            "headless in-place geometry refresh did not advance the cached revision".to_owned(),
        ));
    }
    let mut changed_topology = refreshed_mesh.clone();
    changed_topology.indices.swap(0, 1);
    if mesh.upload_action(&changed_topology, 0) != MeshUploadAction::Replace {
        return Err(RenderError::Device(
            "headless mesh cache did not replace buffers after topology changed".to_owned(),
        ));
    }
    let mut reversed_winding_snapshot = render_snapshot.clone();
    for triangle in reversed_winding_snapshot.indices.chunks_exact_mut(3) {
        triangle.swap(1, 2);
    }
    let reversed_winding_mesh = GpuMeshBuffers::upload(&device, &reversed_winding_snapshot)?;
    let material_proof_snapshot = material_proof_sphere_snapshot();
    let material_proof_mesh = GpuMeshBuffers::upload(&device, &material_proof_snapshot)?;
    let (overlay_minimum, overlay_maximum) =
        mesh_bounds(&render_snapshot.positions).ok_or_else(|| {
            RenderError::InvalidSnapshot(
                "headless bone overlay proof requires mesh bounds".to_owned(),
            )
        })?;
    let overlay_center = (overlay_minimum + overlay_maximum) * 0.5;
    let overlay_depth = overlay_maximum.z;
    let skeleton_lines = GpuOverlayLines::upload(
        &device,
        &[
            [overlay_center.x, overlay_minimum.y, overlay_depth],
            [overlay_center.x, overlay_maximum.y, overlay_depth],
            [overlay_minimum.x, overlay_center.y, overlay_depth],
            [overlay_maximum.x, overlay_center.y, overlay_depth],
        ],
    )?
    .ok_or_else(|| RenderError::InvalidOverlay("headless skeleton lines are empty".to_owned()))?;
    let modes = [
        ViewMode::TexturedSolid,
        ViewMode::GameOutdoor,
        ViewMode::BaseColor,
        ViewMode::NormalMap,
        ViewMode::UvChecker,
        ViewMode::BaseAlpha,
        ViewMode::PartId,
        ViewMode::MaterialResponse,
        ViewMode::LayerMask,
        ViewMode::Solid,
        ViewMode::SolidWire,
        ViewMode::Wireframe,
        ViewMode::Vertices,
        ViewMode::WireVertices,
        ViewMode::XRay,
    ];
    let sizes = [(640_u32, 480_u32), (480, 640), (1_280, 720)];
    let mut frames_rendered = 0_u32;
    for (width, height) in sizes {
        let color = create_headless_color_target(&device, format, width, height);
        let view = color.create_view(&wgpu::TextureViewDescriptor::default());
        let multisample = create_multisample_target(&device, format, width, height, sample_count);
        let depth = create_depth_target_with_sample_count(&device, width, height, sample_count);
        for mode in modes {
            let view_projection = headless_view_projection(&render_snapshot, width, height);
            camera_uniform.view_projection = view_projection.to_cols_array_2d();
            camera_uniform.view_direction = view_direction_from_view_projection(view_projection)
                .extend(0.0)
                .to_array();
            camera_uniform.view_mode = mode.shader_mode();
            queue.write_buffer(&camera_buffer, 0, bytemuck::bytes_of(&camera_uniform));
            let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("CDMW Rust Mesh Lab headless frame"),
            });
            record_headless_pass(
                &mut encoder,
                multisample.as_ref().map_or(&view, |target| &target.view),
                multisample.as_ref().map(|_| &view),
                &depth.view,
                &mesh,
                &default_material_binding.bind_group,
                &active_material_bindings,
                &camera_bind_group,
                &pipelines,
                mode,
                true,
                None,
                false,
            );
            queue.submit([encoder.finish()]);
            frames_rendered = frames_rendered.saturating_add(1);
        }
    }
    let outdoor_readback = render_headless_readback(
        &device,
        &queue,
        format,
        &mesh,
        &default_material_binding.bind_group,
        &base_only_material_bindings,
        &camera_bind_group,
        &pipelines,
        &render_snapshot,
        &mut camera_uniform,
        &camera_buffer,
        ViewMode::GameOutdoor,
    );
    let base_color_readback = render_headless_readback(
        &device,
        &queue,
        format,
        &mesh,
        &default_material_binding.bind_group,
        &base_only_material_bindings,
        &camera_bind_group,
        &pipelines,
        &render_snapshot,
        &mut camera_uniform,
        &camera_buffer,
        ViewMode::BaseColor,
    );
    let generic_material_readback = render_headless_readback(
        &device,
        &queue,
        format,
        &material_proof_mesh,
        &default_material_binding.bind_group,
        &base_only_material_bindings,
        &camera_bind_group,
        &pipelines,
        &material_proof_snapshot,
        &mut camera_uniform,
        &camera_buffer,
        ViewMode::TexturedSolid,
    );
    let category_readbacks = category_material_bindings
        .iter()
        .map(|(label, bindings)| {
            (
                *label,
                render_headless_readback(
                    &device,
                    &queue,
                    format,
                    &material_proof_mesh,
                    &default_material_binding.bind_group,
                    bindings,
                    &camera_bind_group,
                    &pipelines,
                    &material_proof_snapshot,
                    &mut camera_uniform,
                    &camera_buffer,
                    ViewMode::TexturedSolid,
                ),
            )
        })
        .collect::<Vec<_>>();
    let probe_bindings = [
        ("unresolved", BTreeMap::new()),
        ("base color", base_only_material_bindings),
        ("normal", base_normal_material_bindings),
        ("packed material", base_surface_material_bindings),
        ("roughness", base_roughness_material_bindings),
        ("metalness", base_metalness_material_bindings),
        ("specular", base_specular_material_bindings),
        ("dielectric specular", dielectric_specular_material_bindings),
        ("glossiness", glossiness_material_bindings),
        (
            "dielectric glossiness",
            dielectric_glossiness_material_bindings,
        ),
        ("opaque opacity", opaque_opacity_material_bindings),
        ("opacity cutout", opacity_cutout_material_bindings),
        ("height", height_material_bindings),
        ("disabled height", disabled_height_material_bindings),
        ("non-hair flow", non_hair_flow_material_bindings),
        ("hair flow", hair_flow_material_bindings),
        ("occlusion", base_occlusion_material_bindings),
        ("emissive", base_emissive_material_bindings),
        ("emissive factors", factored_emissive_material_bindings),
        ("roughness factor", roughness_factor_material_bindings),
        ("metalness factor", metalness_factor_material_bindings),
        (
            "metalness and specular factors",
            metal_specular_factor_material_bindings,
        ),
        ("composed", active_material_bindings),
    ];
    let readbacks = probe_bindings
        .iter()
        .map(|(_, bindings)| {
            render_headless_readback(
                &device,
                &queue,
                format,
                &mesh,
                &default_material_binding.bind_group,
                bindings,
                &camera_bind_group,
                &pipelines,
                &render_snapshot,
                &mut camera_uniform,
                &camera_buffer,
                ViewMode::TexturedSolid,
            )
        })
        .collect::<Vec<_>>();
    let layer_mask_readbacks = [
        (
            "fallback",
            render_headless_readback(
                &device,
                &queue,
                format,
                &mesh,
                &default_material_binding.bind_group,
                &layer_mask_fallback_material_bindings,
                &camera_bind_group,
                &pipelines,
                &render_snapshot,
                &mut camera_uniform,
                &camera_buffer,
                ViewMode::LayerMask,
            ),
        ),
        (
            "red",
            render_headless_readback(
                &device,
                &queue,
                format,
                &mesh,
                &default_material_binding.bind_group,
                &layer_mask_red_material_bindings,
                &camera_bind_group,
                &pipelines,
                &render_snapshot,
                &mut camera_uniform,
                &camera_buffer,
                ViewMode::LayerMask,
            ),
        ),
        (
            "blue",
            render_headless_readback(
                &device,
                &queue,
                format,
                &mesh,
                &default_material_binding.bind_group,
                &layer_mask_blue_material_bindings,
                &camera_bind_group,
                &pipelines,
                &render_snapshot,
                &mut camera_uniform,
                &camera_buffer,
                ViewMode::LayerMask,
            ),
        ),
    ];
    let part_id_readback = render_headless_readback(
        &device,
        &queue,
        format,
        &mesh,
        &default_material_binding.bind_group,
        &BTreeMap::new(),
        &camera_bind_group,
        &pipelines,
        &render_snapshot,
        &mut camera_uniform,
        &camera_buffer,
        ViewMode::PartId,
    );
    let bone_overlay_base_readback = render_headless_readback(
        &device,
        &queue,
        format,
        &mesh,
        &default_material_binding.bind_group,
        &BTreeMap::new(),
        &camera_bind_group,
        &pipelines,
        &render_snapshot,
        &mut camera_uniform,
        &camera_buffer,
        ViewMode::Solid,
    );
    let bone_overlay_readback = render_headless_readback_with_skeleton(
        &device,
        &queue,
        format,
        &mesh,
        &default_material_binding.bind_group,
        &BTreeMap::new(),
        &camera_bind_group,
        &pipelines,
        &render_snapshot,
        &mut camera_uniform,
        &camera_buffer,
        ViewMode::Solid,
        Some(&skeleton_lines),
        true,
    );
    let reversed_winding_readback = render_headless_readback(
        &device,
        &queue,
        format,
        &reversed_winding_mesh,
        &default_material_binding.bind_group,
        &BTreeMap::new(),
        &camera_bind_group,
        &pipelines,
        &reversed_winding_snapshot,
        &mut camera_uniform,
        &camera_buffer,
        ViewMode::Solid,
    );
    frames_rendered = frames_rendered
        .saturating_add(u32::try_from(readbacks.len()).map_err(|_| RenderError::ResourceLimit)?)
        .saturating_add(
            u32::try_from(layer_mask_readbacks.len()).map_err(|_| RenderError::ResourceLimit)?,
        )
        .saturating_add(
            u32::try_from(category_readbacks.len()).map_err(|_| RenderError::ResourceLimit)?,
        )
        .saturating_add(7);
    device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|error| RenderError::Device(format!("headless GPU wait failed: {error}")))?;
    if let Some(error) = error_scope.pop().await {
        return Err(RenderError::Device(format!(
            "headless GPU validation failed: {error}"
        )));
    }
    let probe_pixels = readbacks
        .iter()
        .map(|(readback, width, height)| read_headless_pixels(&device, readback, *width, *height))
        .collect::<Result<Vec<_>, _>>()?;
    let layer_mask_pixels = layer_mask_readbacks
        .iter()
        .map(|(label, (readback, width, height))| {
            read_headless_pixels(&device, readback, *width, *height).map(|pixels| (*label, pixels))
        })
        .collect::<Result<BTreeMap<_, _>, _>>()?;
    let part_id_pixels = read_headless_pixels(
        &device,
        &part_id_readback.0,
        part_id_readback.1,
        part_id_readback.2,
    )?;
    let outdoor_pixels = read_headless_pixels(
        &device,
        &outdoor_readback.0,
        outdoor_readback.1,
        outdoor_readback.2,
    )?;
    let base_color_pixels = read_headless_pixels(
        &device,
        &base_color_readback.0,
        base_color_readback.1,
        base_color_readback.2,
    )?;
    let generic_material_pixels = read_headless_pixels(
        &device,
        &generic_material_readback.0,
        generic_material_readback.1,
        generic_material_readback.2,
    )?;
    let category_pixels = category_readbacks
        .iter()
        .map(|(label, (readback, width, height))| {
            read_headless_pixels(&device, readback, *width, *height).map(|pixels| (*label, pixels))
        })
        .collect::<Result<BTreeMap<_, _>, _>>()?;
    let bone_overlay_base_pixels = read_headless_pixels(
        &device,
        &bone_overlay_base_readback.0,
        bone_overlay_base_readback.1,
        bone_overlay_base_readback.2,
    )?;
    let bone_overlay_pixels = read_headless_pixels(
        &device,
        &bone_overlay_readback.0,
        bone_overlay_readback.1,
        bone_overlay_readback.2,
    )?;
    let reversed_winding_pixels = read_headless_pixels(
        &device,
        &reversed_winding_readback.0,
        reversed_winding_readback.1,
        reversed_winding_readback.2,
    )?;
    let reversed_winding_background = reversed_winding_pixels.get(..4).ok_or_else(|| {
        RenderError::Device("headless reversed-winding frame has no complete pixel".to_owned())
    })?;
    let background_peak = reversed_winding_background[..3]
        .iter()
        .copied()
        .max()
        .unwrap_or(0);
    let lit_back_face_pixels = reversed_winding_pixels
        .chunks_exact(4)
        .filter(|pixel| {
            *pixel != reversed_winding_background
                && pixel[..3].iter().copied().max().unwrap_or(0)
                    > background_peak.saturating_add(16)
        })
        .count();
    if lit_back_face_pixels == 0 {
        return Err(RenderError::Device(
            "headless reversed-winding surfaces were culled or rendered completely dark".to_owned(),
        ));
    }
    let bone_overlay_pixels_changed =
        changed_pixel_count(&bone_overlay_base_pixels, &bone_overlay_pixels)?;
    if bone_overlay_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless Bones overlay did not change any rendered pixel".to_owned(),
        ));
    }
    let probe_index = |label: &str| {
        probe_bindings
            .iter()
            .position(|(candidate, _)| *candidate == label)
            .ok_or_else(|| RenderError::Device(format!("headless {label} probe is missing")))
    };
    let unresolved_pixels = &probe_pixels[probe_index("unresolved")?];
    let unresolved_background = unresolved_pixels.get(..4).ok_or_else(|| {
        RenderError::Device("headless unresolved-material frame has no complete pixel".to_owned())
    })?;
    let unresolved_surface_pixels = unresolved_pixels
        .chunks_exact(4)
        .filter(|pixel| *pixel != unresolved_background)
        .collect::<Vec<_>>();
    if unresolved_surface_pixels.is_empty() {
        return Err(RenderError::Device(
            "headless unresolved material rendered no surface pixels".to_owned(),
        ));
    }
    let non_neutral_pixels = unresolved_surface_pixels
        .iter()
        .filter(|pixel| {
            let minimum = pixel[..3].iter().copied().min().unwrap_or(0);
            let maximum = pixel[..3].iter().copied().max().unwrap_or(255);
            maximum.saturating_sub(minimum) > 48 || pixel[3] != 255
        })
        .count();
    if non_neutral_pixels > 0 {
        return Err(RenderError::Device(format!(
            "headless unresolved material rendered {non_neutral_pixels} non-neutral or translucent surface pixels"
        )));
    }
    let base_only_pixels = &probe_pixels[probe_index("base color")?];
    let expected_base_colors = [[55_u8, 70, 210, 255], [128_u8, 128, 128, 255]];
    let matches_expected_base = |pixel: &[u8]| {
        expected_base_colors.iter().any(|expected| {
            pixel
                .iter()
                .zip(expected)
                .all(|(actual, expected)| actual.abs_diff(*expected) <= 2)
        })
    };
    let base_color_round_trip_pixels = base_color_pixels
        .chunks_exact(4)
        .filter(|pixel| matches_expected_base(pixel))
        .count();
    if base_color_round_trip_pixels == 0 {
        return Err(RenderError::Device(
            "headless Base Color view did not preserve any source sRGB texels through the GPU output path"
                .to_owned(),
        ));
    }
    let mid_gray_round_trip_pixels = base_color_pixels
        .chunks_exact(4)
        .filter(|pixel| {
            pixel
                .iter()
                .zip([128_u8, 128, 128, 255])
                .all(|(actual, expected)| actual.abs_diff(expected) <= 2)
        })
        .count();
    if mid_gray_round_trip_pixels == 0 {
        return Err(RenderError::Device(
            "headless Base Color view changed a mid-gray sRGB texture during GPU sampling or presentation"
                .to_owned(),
        ));
    }
    let display_luma = |pixel: &[u8]| {
        u64::from(pixel[2]) * 21 + u64::from(pixel[1]) * 72 + u64::from(pixel[0]) * 7
    };
    let (base_luma_sum, lit_luma_sum, luma_samples) = base_color_pixels
        .chunks_exact(4)
        .zip(base_only_pixels.chunks_exact(4))
        .filter(|(base, lit)| matches_expected_base(base) && *lit != unresolved_background)
        .fold(
            (0_u64, 0_u64, 0_u64),
            |(base_sum, lit_sum, count), (base, lit)| {
                (
                    base_sum.saturating_add(display_luma(base)),
                    lit_sum.saturating_add(display_luma(lit)),
                    count.saturating_add(1),
                )
            },
        );
    if luma_samples == 0 || base_luma_sum == 0 {
        return Err(RenderError::Device(
            "headless Textured view had no source-color surface samples for readability proof"
                .to_owned(),
        ));
    }
    let front_lighting_luma_percent = u32::try_from(
        lit_luma_sum
            .saturating_mul(100)
            .saturating_add(base_luma_sum / 2)
            / base_luma_sum,
    )
    .map_err(|_| RenderError::ResourceLimit)?;
    if !(35..=175).contains(&front_lighting_luma_percent) {
        return Err(RenderError::Device(format!(
            "headless front-facing textured readability was {front_lighting_luma_percent}% of Base Color; expected 35%..=175%"
        )));
    }
    let category_materials_distinguished = category_pixels
        .values()
        .map(|pixels| changed_pixel_count(&generic_material_pixels, pixels))
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .filter(|changed| *changed > 0)
        .count();
    if category_materials_distinguished != category_pixels.len() {
        return Err(RenderError::Device(format!(
            "headless material categories distinguished {category_materials_distinguished} of {} non-generic responses",
            category_pixels.len()
        )));
    }
    let source_chroma_survives = |pixels: &[u8]| {
        let surface_pixels = pixels
            .chunks_exact(4)
            .filter(|pixel| *pixel != unresolved_background)
            .collect::<Vec<_>>();
        let chromatic_pixels = surface_pixels
            .iter()
            .filter(|pixel| {
                pixel[2].saturating_sub(pixel[1]) >= 12 && pixel[2].saturating_sub(pixel[0]) >= 24
            })
            .count();
        !surface_pixels.is_empty() && chromatic_pixels.saturating_mul(5) >= surface_pixels.len()
    };
    let category_materials_preserving_chroma = category_pixels
        .values()
        .filter(|pixels| source_chroma_survives(pixels))
        .count();
    if category_materials_preserving_chroma != category_pixels.len() {
        return Err(RenderError::Device(format!(
            "headless material categories preserved source chroma for {category_materials_preserving_chroma} of {} responses",
            category_pixels.len()
        )));
    }
    if let Some(proof_path) = proof_path {
        let panels = [
            generic_material_pixels.as_slice(),
            category_pixels
                .get("metal")
                .ok_or_else(|| RenderError::Device("headless metal proof is missing".to_owned()))?
                .as_slice(),
            category_pixels
                .get("leather")
                .ok_or_else(|| RenderError::Device("headless leather proof is missing".to_owned()))?
                .as_slice(),
            category_pixels
                .get("cloth")
                .ok_or_else(|| RenderError::Device("headless cloth proof is missing".to_owned()))?
                .as_slice(),
            category_pixels
                .get("skin")
                .ok_or_else(|| RenderError::Device("headless skin proof is missing".to_owned()))?
                .as_slice(),
            category_pixels
                .get("glass")
                .ok_or_else(|| RenderError::Device("headless glass proof is missing".to_owned()))?
                .as_slice(),
        ];
        write_bgra_material_proof_bmp(
            proof_path,
            generic_material_readback.1,
            generic_material_readback.2,
            &panels,
        )?;
    }
    let outdoor_lighting_pixels_changed = changed_pixel_count(base_only_pixels, &outdoor_pixels)?;
    if outdoor_lighting_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless Game Outdoor lighting matched the standard Textured frame".to_owned(),
        ));
    }
    let composed_pixels = &probe_pixels[probe_index("composed")?];
    let background = composed_pixels.get(..4).ok_or_else(|| {
        RenderError::Device("headless GPU frame has no complete pixel".to_owned())
    })?;
    let non_background_pixels = composed_pixels
        .chunks_exact(4)
        .filter(|pixel| *pixel != background)
        .count();
    if non_background_pixels == 0 {
        return Err(RenderError::Device(
            "headless GPU frame contained only the clear color".to_owned(),
        ));
    }
    let layer_mask_fallback_pixels = layer_mask_pixels.get("fallback").ok_or_else(|| {
        RenderError::Device("headless layer-mask fallback probe is missing".to_owned())
    })?;
    let layer_mask_red_pixels = layer_mask_pixels.get("red").ok_or_else(|| {
        RenderError::Device("headless layer-mask red-channel probe is missing".to_owned())
    })?;
    let layer_mask_blue_pixels = layer_mask_pixels.get("blue").ok_or_else(|| {
        RenderError::Device("headless layer-mask blue-channel probe is missing".to_owned())
    })?;
    let layer_mask_pixels_changed =
        changed_pixel_count(layer_mask_fallback_pixels, layer_mask_blue_pixels)?;
    let layer_mask_channel_pixels_changed =
        changed_pixel_count(layer_mask_red_pixels, layer_mask_blue_pixels)?;
    if layer_mask_channel_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless layer-mask channel selector did not change any rendered pixel".to_owned(),
        ));
    }
    let part_id_background = part_id_pixels.get(..4).ok_or_else(|| {
        RenderError::Device("headless Part ID frame has no complete pixel".to_owned())
    })?;
    let part_id_colors_rendered = mesh
        .material_ranges
        .iter()
        .filter(|range| {
            let expected = part_id_bgra(range.part_id);
            part_id_pixels.chunks_exact(4).any(|pixel| {
                pixel != part_id_background
                    && pixel
                        .iter()
                        .zip(expected)
                        .all(|(actual, expected)| actual.abs_diff(expected) <= 2)
            })
        })
        .count();
    if part_id_colors_rendered < mesh.material_ranges.len() {
        return Err(RenderError::Device(format!(
            "headless Part ID view rendered {} distinct owner colors for {} material ranges",
            part_id_colors_rendered,
            mesh.material_ranges.len()
        )));
    }

    let mut role_changes = Vec::with_capacity(13);
    for (role, reference) in [
        ("base color", "unresolved"),
        ("normal", "base color"),
        ("packed material", "base color"),
        // Compare roughness against the otherwise-identical metalness pass.
        // A dielectric highlight can quantize away at this small probe size,
        // while the authored conductor response gives the roughness channel a
        // stable, directly observable contribution on every supported driver.
        ("roughness", "metalness"),
        ("metalness", "base color"),
        ("specular", "metalness"),
        ("glossiness", "metalness"),
        ("opacity cutout", "opaque opacity"),
        ("height", "base color"),
        ("hair flow", "non-hair flow"),
        ("occlusion", "base color"),
        ("emissive", "base color"),
    ] {
        let role_index = probe_index(role)?;
        let reference_index = probe_index(reference)?;
        role_changes.push((
            role,
            changed_pixel_count(&probe_pixels[reference_index], &probe_pixels[role_index])?,
        ));
    }
    role_changes.push(("layer mask", layer_mask_pixels_changed));
    for (role, changed) in &role_changes {
        if *changed == 0 {
            return Err(RenderError::Device(format!(
                "headless {role} sampling did not change any rendered pixel"
            )));
        }
    }
    let composed_material_pixels_changed = changed_pixel_count(base_only_pixels, composed_pixels)?;
    if composed_material_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless material roles did not change any rendered pixel from the base-only pass"
                .to_owned(),
        ));
    }
    let emissive_pixels = &probe_pixels[probe_index("emissive")?];
    let factored_emissive_pixels = &probe_pixels[probe_index("emissive factors")?];
    let emissive_factor_pixels_changed =
        changed_pixel_count(emissive_pixels, factored_emissive_pixels)?;
    if emissive_factor_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless emissive color/intensity factors did not change any rendered pixel"
                .to_owned(),
        ));
    }
    let roughness_factor_pixels_changed = changed_pixel_count(
        &probe_pixels[probe_index("metalness factor")?],
        &probe_pixels[probe_index("roughness factor")?],
    )?;
    if roughness_factor_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless roughness factor did not change any rendered pixel".to_owned(),
        ));
    }
    let metalness_factor_pixels = &probe_pixels[probe_index("metalness factor")?];
    let metalness_factor_pixels_changed =
        changed_pixel_count(base_only_pixels, metalness_factor_pixels)?;
    if metalness_factor_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless metalness factor did not change any rendered pixel".to_owned(),
        ));
    }
    let specular_factor_pixels_changed = changed_pixel_count(
        metalness_factor_pixels,
        &probe_pixels[probe_index("metalness and specular factors")?],
    )?;
    if specular_factor_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless specular factor did not change any rendered pixel".to_owned(),
        ));
    }
    let specular_texture_pixels_changed = changed_pixel_count(
        &probe_pixels[probe_index("metalness")?],
        &probe_pixels[probe_index("specular")?],
    )?;
    if specular_texture_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless specular texture did not change any rendered pixel".to_owned(),
        ));
    }
    let dielectric_specular_pixels_changed = changed_pixel_count(
        base_only_pixels,
        &probe_pixels[probe_index("dielectric specular")?],
    )?;
    if dielectric_specular_pixels_changed != 0 {
        return Err(RenderError::Device(
            "headless specular texture changed a dielectric material".to_owned(),
        ));
    }
    let glossiness_texture_pixels_changed = changed_pixel_count(
        &probe_pixels[probe_index("metalness")?],
        &probe_pixels[probe_index("glossiness")?],
    )?;
    if glossiness_texture_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless glossiness texture did not change any rendered pixel".to_owned(),
        ));
    }
    // The metalness-matched comparison above is the stable GPU proof that the
    // glossiness channel is sampled.  On a plain dielectric probe the same
    // authored response can quantize to the base frame after tone mapping, so
    // equality is valid and remains visible in the report for the owning
    // contract assertion.
    let dielectric_glossiness_pixels_changed = changed_pixel_count(
        base_only_pixels,
        &probe_pixels[probe_index("dielectric glossiness")?],
    )?;
    let height_texture_pixels_changed =
        changed_pixel_count(base_only_pixels, &probe_pixels[probe_index("height")?])?;
    if height_texture_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless height texture did not change any rendered pixel".to_owned(),
        ));
    }
    let disabled_height_pixels_changed = changed_pixel_count(
        base_only_pixels,
        &probe_pixels[probe_index("disabled height")?],
    )?;
    if disabled_height_pixels_changed != 0 {
        return Err(RenderError::Device(
            "headless height texture changed pixels at an explicit zero scale".to_owned(),
        ));
    }
    let non_hair_flow_pixels_changed = changed_pixel_count(
        base_only_pixels,
        &probe_pixels[probe_index("non-hair flow")?],
    )?;
    if non_hair_flow_pixels_changed != 0 {
        return Err(RenderError::Device(
            "headless Flow texture changed a non-hair material".to_owned(),
        ));
    }
    let hair_flow_pixels_changed = changed_pixel_count(
        &probe_pixels[probe_index("non-hair flow")?],
        &probe_pixels[probe_index("hair flow")?],
    )?;
    if hair_flow_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless hair Flow texture did not change any rendered pixel".to_owned(),
        ));
    }
    let opaque_opacity_pixels = &probe_pixels[probe_index("opaque opacity")?];
    let opacity_cutout_pixels = &probe_pixels[probe_index("opacity cutout")?];
    let opaque_opacity_pixels_changed =
        changed_pixel_count(base_only_pixels, opaque_opacity_pixels)?;
    if opaque_opacity_pixels_changed != 0 {
        return Err(RenderError::Device(
            "headless opacity texture changed an explicitly opaque material".to_owned(),
        ));
    }
    let opacity_cutout_pixels_changed =
        changed_pixel_count(opaque_opacity_pixels, opacity_cutout_pixels)?;
    let opacity_cutout_pixels_removed = opaque_opacity_pixels
        .chunks_exact(4)
        .zip(opacity_cutout_pixels.chunks_exact(4))
        .filter(|(opaque, cutout)| *opaque != background && *cutout == background)
        .count();
    if opacity_cutout_pixels_removed == 0
        || opacity_cutout_pixels_removed != opacity_cutout_pixels_changed
    {
        return Err(RenderError::Device(format!(
            "headless opacity cutout removed {opacity_cutout_pixels_removed} of {opacity_cutout_pixels_changed} changed pixels"
        )));
    }
    Ok(HeadlessRenderReport {
        adapter: adapter_report(&adapter),
        sample_count,
        anisotropy_clamp,
        frames_rendered,
        modes_rendered: u32::try_from(modes.len()).map_err(|_| RenderError::ResourceLimit)?,
        viewport_sizes_rendered: u32::try_from(sizes.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        dds_textures_uploaded: u32::try_from(material_textures.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        sampled_material_roles: u32::try_from(role_changes.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        material_ranges_rendered: u32::try_from(mesh.material_ranges.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        composed_material_pixels_changed,
        emissive_factor_pixels_changed,
        roughness_factor_pixels_changed,
        metalness_factor_pixels_changed,
        specular_factor_pixels_changed,
        specular_texture_pixels_changed,
        dielectric_specular_pixels_changed,
        glossiness_texture_pixels_changed,
        dielectric_glossiness_pixels_changed,
        height_texture_pixels_changed,
        disabled_height_pixels_changed,
        hair_flow_pixels_changed,
        non_hair_flow_pixels_changed,
        layer_mask_pixels_changed,
        layer_mask_channel_pixels_changed,
        part_id_colors_rendered,
        outdoor_lighting_pixels_changed,
        bone_overlay_pixels_changed,
        opacity_cutout_pixels_removed,
        opaque_opacity_pixels_changed,
        non_background_pixels,
        base_color_round_trip_pixels,
        front_lighting_luma_percent,
        category_materials_distinguished,
    })
}

fn part_id_bgra(part_id: u32) -> [u8; 4] {
    let color = ((part_id as f32 + 1.0) * Vec3::new(0.618_033_9, 0.381_966, 0.754_877_7)).fract();
    let to_unorm8 = |value: f32| (value.clamp(0.0, 1.0) * 255.0).round() as u8;
    [
        to_unorm8(color.z),
        to_unorm8(color.y),
        to_unorm8(color.x),
        255,
    ]
}

fn bgra_luma_and_chroma(pixel: &[u8]) -> (f32, f32) {
    let blue = f32::from(pixel[0]);
    let green = f32::from(pixel[1]);
    let red = f32::from(pixel[2]);
    let luma = red * 0.2126 + green * 0.7152 + blue * 0.0722;
    let chroma = red.max(green).max(blue) - red.min(green).min(blue);
    (luma, chroma)
}

fn modal_bgra_pixel(pixels: &[u8]) -> Result<[u8; 4], RenderError> {
    if pixels.is_empty() || !pixels.len().is_multiple_of(4) {
        return Err(RenderError::Device(
            "headless frame has no complete BGRA pixels".to_owned(),
        ));
    }
    let mut counts = BTreeMap::<[u8; 4], usize>::new();
    for pixel in pixels.chunks_exact(4) {
        let value = [pixel[0], pixel[1], pixel[2], pixel[3]];
        *counts.entry(value).or_default() += 1;
    }
    counts
        .into_iter()
        .max_by_key(|(_, count)| *count)
        .map(|(pixel, _)| pixel)
        .ok_or_else(|| RenderError::Device("headless frame contains no pixels".to_owned()))
}

fn percentile(sorted: &[f32], fraction: f32) -> f32 {
    if sorted.is_empty() {
        return 0.0;
    }
    let position = (sorted.len().saturating_sub(1) as f32) * fraction.clamp(0.0, 1.0);
    let lower = position.floor() as usize;
    let upper = position.ceil() as usize;
    let amount = position - lower as f32;
    sorted[lower] + (sorted[upper] - sorted[lower]) * amount
}

fn headless_frame_stats(pixels: &[u8]) -> Result<HeadlessFrameStats, RenderError> {
    let background = modal_bgra_pixel(pixels)?;
    let mut luma = Vec::new();
    let mut chroma_sum = 0.0_f32;
    let mut near_white = 0_usize;
    let mut light = 0_usize;
    for pixel in pixels.chunks_exact(4) {
        if pixel == background {
            continue;
        }
        let (pixel_luma, pixel_chroma) = bgra_luma_and_chroma(pixel);
        luma.push(pixel_luma);
        chroma_sum += pixel_chroma;
        near_white += usize::from(pixel_luma >= 230.0 && pixel_chroma <= 15.0);
        light += usize::from(pixel_luma >= 200.0);
    }
    luma.sort_by(f32::total_cmp);
    let non_background_pixels = luma.len();
    if non_background_pixels == 0 {
        return Ok(HeadlessFrameStats {
            non_background_pixels: 0,
            mean_luma_255: 0.0,
            p05_luma_255: 0.0,
            p50_luma_255: 0.0,
            p95_luma_255: 0.0,
            mean_chroma_255: 0.0,
            near_white_percent: 0.0,
            light_pixel_percent: 0.0,
        });
    }
    let count = non_background_pixels as f32;
    Ok(HeadlessFrameStats {
        non_background_pixels,
        mean_luma_255: luma.iter().sum::<f32>() / count,
        p05_luma_255: percentile(&luma, 0.05),
        p50_luma_255: percentile(&luma, 0.50),
        p95_luma_255: percentile(&luma, 0.95),
        mean_chroma_255: chroma_sum / count,
        near_white_percent: near_white as f32 * 100.0 / count,
        light_pixel_percent: light as f32 * 100.0 / count,
    })
}

fn headless_material_owner_coverage(
    ranges: &[GpuMaterialRange],
    textured_pixels: &[u8],
    base_color_pixels: &[u8],
    part_id_pixels: &[u8],
) -> Result<Vec<HeadlessMaterialOwnerCoverage>, RenderError> {
    if textured_pixels.len() != base_color_pixels.len()
        || textured_pixels.len() != part_id_pixels.len()
        || !textured_pixels.len().is_multiple_of(4)
    {
        return Err(RenderError::Device(
            "material capture frame sizes do not match".to_owned(),
        ));
    }
    let frame_pixels = textured_pixels.len() / 4;
    let mut coverage = Vec::with_capacity(ranges.len());
    for range in ranges {
        let expected = part_id_bgra(range.part_id);
        let mut pixel_count = 0_usize;
        let mut textured_luma = 0.0_f32;
        let mut textured_chroma = 0.0_f32;
        let mut base_color_luma = 0.0_f32;
        let mut base_color_chroma = 0.0_f32;
        for ((part_id, textured), base_color) in part_id_pixels
            .chunks_exact(4)
            .zip(textured_pixels.chunks_exact(4))
            .zip(base_color_pixels.chunks_exact(4))
        {
            if !part_id
                .iter()
                .zip(expected)
                .all(|(actual, expected)| actual.abs_diff(expected) <= 2)
            {
                continue;
            }
            let (textured_pixel_luma, textured_pixel_chroma) = bgra_luma_and_chroma(textured);
            let (base_pixel_luma, base_pixel_chroma) = bgra_luma_and_chroma(base_color);
            pixel_count += 1;
            textured_luma += textured_pixel_luma;
            textured_chroma += textured_pixel_chroma;
            base_color_luma += base_pixel_luma;
            base_color_chroma += base_pixel_chroma;
        }
        let divisor = pixel_count.max(1) as f32;
        coverage.push(HeadlessMaterialOwnerCoverage {
            material_index: range.material,
            part_id: range.part_id,
            pixel_count,
            frame_percent: if frame_pixels == 0 {
                0.0
            } else {
                pixel_count as f32 * 100.0 / frame_pixels as f32
            },
            textured_mean_luma_255: textured_luma / divisor,
            textured_mean_chroma_255: textured_chroma / divisor,
            base_color_mean_luma_255: base_color_luma / divisor,
            base_color_mean_chroma_255: base_color_chroma / divisor,
        });
    }
    Ok(coverage)
}

fn adapter_report(adapter: &wgpu::Adapter) -> AdapterReport {
    let info = adapter.get_info();
    AdapterReport {
        name: info.name,
        backend: format!("{:?}", info.backend),
        device_type: format!("{:?}", info.device_type),
        driver: info.driver,
        driver_info: info.driver_info,
    }
}

fn create_headless_color_target(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    width: u32,
    height: u32,
) -> wgpu::Texture {
    device.create_texture(&wgpu::TextureDescriptor {
        label: Some("CDMW Rust Mesh Lab headless color target"),
        size: wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    })
}

fn headless_view_projection(snapshot: &DrawSnapshot, width: u32, height: u32) -> Mat4 {
    let (minimum, maximum) =
        mesh_bounds(&snapshot.positions).unwrap_or((Vec3::splat(-1.0), Vec3::ONE));
    let target = (minimum + maximum) * 0.5;
    let radius = ((maximum - minimum) * 0.5).length().max(1.0e-4);
    let field_of_view = 45.0_f32.to_radians();
    let aspect = (width as f32 / height.max(1) as f32).max(1.0e-4);
    let half_vertical = field_of_view * 0.5;
    let half_horizontal = (half_vertical.tan() * aspect).atan();
    let fit_half_angle = half_vertical.min(half_horizontal).max(1.0e-4);
    let distance = (radius / fit_half_angle.tan() * 1.25).max(radius * 1.5);
    let near = (distance * 0.001).max(1.0e-4);
    let far = (distance + radius * 8.0).max(near + 1.0);
    Mat4::perspective_rh(field_of_view, aspect, near, far)
        * Mat4::look_at_rh(target + Vec3::Z * distance, target, Vec3::Y)
}

fn headless_capture_view_projection(snapshot: &DrawSnapshot, width: u32, height: u32) -> Mat4 {
    let (minimum, maximum) =
        mesh_bounds(&snapshot.positions).unwrap_or((Vec3::splat(-1.0), Vec3::ONE));
    let target = (minimum + maximum) * 0.5;
    let extent = maximum - minimum;
    let startup_view = integrated_startup_view(extent);
    let view_axis = startup_view.eye_direction();
    let up_axis = startup_view.up_direction();
    let radius = (extent * 0.5).length().max(1.0e-4);
    let field_of_view = 45.0_f32.to_radians();
    let aspect = (width as f32 / height.max(1) as f32).max(1.0e-4);
    let half_vertical = field_of_view * 0.5;
    let half_horizontal = (half_vertical.tan() * aspect).atan();
    let fit_half_angle = half_vertical.min(half_horizontal).max(1.0e-4);
    let distance = (radius / fit_half_angle.tan() * 1.12).max(radius * 1.5);
    let near = (distance * 0.001).max(1.0e-4);
    let far = (distance + radius * 8.0).max(near + 1.0);
    Mat4::perspective_rh(field_of_view, aspect, near, far)
        * Mat4::look_at_rh(target + view_axis * distance, target, up_axis)
}

fn material_proof_sphere_snapshot() -> DrawSnapshot {
    const SEGMENTS: u32 = 48;
    const RINGS: u32 = 24;
    let mut positions = Vec::with_capacity(((SEGMENTS + 1) * (RINGS + 1)) as usize);
    let mut normals = Vec::with_capacity(positions.capacity());
    let mut uvs = Vec::with_capacity(positions.capacity());
    for ring in 0..=RINGS {
        let v = ring as f32 / RINGS as f32;
        let theta = v * std::f32::consts::PI;
        let sin_theta = theta.sin();
        let cos_theta = theta.cos();
        for segment in 0..=SEGMENTS {
            let u = segment as f32 / SEGMENTS as f32;
            let phi = u * std::f32::consts::TAU;
            let normal = Vec3::new(sin_theta * phi.cos(), cos_theta, sin_theta * phi.sin());
            positions.push(normal.to_array());
            normals.push(normal.normalize_or(Vec3::Y).to_array());
            uvs.push([u, v]);
        }
    }
    let row_width = SEGMENTS + 1;
    let mut indices = Vec::with_capacity((SEGMENTS * RINGS * 6) as usize);
    for ring in 0..RINGS {
        for segment in 0..SEGMENTS {
            let top_left = ring * row_width + segment;
            let top_right = top_left + 1;
            let bottom_left = top_left + row_width;
            let bottom_right = bottom_left + 1;
            indices.extend_from_slice(&[
                top_left,
                bottom_right,
                bottom_left,
                top_left,
                top_right,
                bottom_right,
            ]);
        }
    }
    let triangle_count = indices.len() / 3;
    DrawSnapshot {
        mesh_identity: u64::MAX - 17,
        draw_revision: 1,
        topology_generation: 1,
        positions,
        normals,
        uvs,
        indices,
        triangle_materials: vec![2; triangle_count],
        selected_vertices: Vec::new(),
        fingerprint: "synthetic-material-proof-sphere-v1".to_owned(),
    }
}

#[allow(clippy::too_many_arguments)]
fn record_headless_pass(
    encoder: &mut wgpu::CommandEncoder,
    color: &wgpu::TextureView,
    resolve_target: Option<&wgpu::TextureView>,
    depth: &wgpu::TextureView,
    mesh: &GpuMeshBuffers,
    default_material_bind_group: &wgpu::BindGroup,
    active_material_bindings: &BTreeMap<u32, GpuMaterialBinding>,
    camera_bind_group: &wgpu::BindGroup,
    pipelines: &Pipelines,
    mode: ViewMode,
    show_overlays: bool,
    skeleton_lines: Option<&GpuOverlayLines>,
    show_bones: bool,
) {
    let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
        label: Some("CDMW Rust Mesh Lab headless viewport"),
        color_attachments: &[Some(wgpu::RenderPassColorAttachment {
            view: color,
            resolve_target,
            ops: wgpu::Operations {
                load: wgpu::LoadOp::Clear(clear_colour_for_target([0.025, 0.03, 0.04, 1.0], true)),
                store: if resolve_target.is_some() {
                    wgpu::StoreOp::Discard
                } else {
                    wgpu::StoreOp::Store
                },
            },
            depth_slice: None,
        })],
        depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
            view: depth,
            depth_ops: Some(wgpu::Operations {
                load: wgpu::LoadOp::Clear(1.0),
                store: wgpu::StoreOp::Store,
            }),
            stencil_ops: None,
        }),
        timestamp_writes: None,
        occlusion_query_set: None,
        multiview_mask: None,
    });
    draw_mesh(
        &mut pass,
        mesh,
        default_material_bind_group,
        active_material_bindings,
        camera_bind_group,
        &pipelines.solid,
        &pipelines.wire,
        &pipelines.xray_wire,
        &pipelines.point,
        &pipelines.xray,
        &pipelines.normal,
        &pipelines.bounds,
        &pipelines.bone,
        skeleton_lines,
        None,
        mode,
        show_overlays,
        show_overlays,
        show_bones,
    );
}

#[allow(clippy::too_many_arguments)]
fn render_headless_readback(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    format: wgpu::TextureFormat,
    mesh: &GpuMeshBuffers,
    default_material_bind_group: &wgpu::BindGroup,
    active_material_bindings: &BTreeMap<u32, GpuMaterialBinding>,
    camera_bind_group: &wgpu::BindGroup,
    pipelines: &Pipelines,
    snapshot: &DrawSnapshot,
    camera_uniform: &mut CameraUniform,
    camera_buffer: &wgpu::Buffer,
    view_mode: ViewMode,
) -> (wgpu::Buffer, u32, u32) {
    render_headless_readback_with_skeleton(
        device,
        queue,
        format,
        mesh,
        default_material_bind_group,
        active_material_bindings,
        camera_bind_group,
        pipelines,
        snapshot,
        camera_uniform,
        camera_buffer,
        view_mode,
        None,
        false,
    )
}

#[allow(clippy::too_many_arguments)]
fn render_headless_readback_with_skeleton(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    format: wgpu::TextureFormat,
    mesh: &GpuMeshBuffers,
    default_material_bind_group: &wgpu::BindGroup,
    active_material_bindings: &BTreeMap<u32, GpuMaterialBinding>,
    camera_bind_group: &wgpu::BindGroup,
    pipelines: &Pipelines,
    snapshot: &DrawSnapshot,
    camera_uniform: &mut CameraUniform,
    camera_buffer: &wgpu::Buffer,
    view_mode: ViewMode,
    skeleton_lines: Option<&GpuOverlayLines>,
    show_bones: bool,
) -> (wgpu::Buffer, u32, u32) {
    let width = 640_u32;
    let height = 480_u32;
    let view_projection = headless_view_projection(snapshot, width, height);
    render_headless_readback_at(
        device,
        queue,
        format,
        mesh,
        default_material_bind_group,
        active_material_bindings,
        camera_bind_group,
        pipelines,
        camera_uniform,
        camera_buffer,
        view_mode,
        width,
        height,
        view_projection,
        skeleton_lines,
        show_bones,
    )
}

#[allow(clippy::too_many_arguments)]
fn render_headless_readback_at(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    format: wgpu::TextureFormat,
    mesh: &GpuMeshBuffers,
    default_material_bind_group: &wgpu::BindGroup,
    active_material_bindings: &BTreeMap<u32, GpuMaterialBinding>,
    camera_bind_group: &wgpu::BindGroup,
    pipelines: &Pipelines,
    camera_uniform: &mut CameraUniform,
    camera_buffer: &wgpu::Buffer,
    view_mode: ViewMode,
    width: u32,
    height: u32,
    view_projection: Mat4,
    skeleton_lines: Option<&GpuOverlayLines>,
    show_bones: bool,
) -> (wgpu::Buffer, u32, u32) {
    let color = create_headless_color_target(device, format, width, height);
    let view = color.create_view(&wgpu::TextureViewDescriptor::default());
    let multisample =
        create_multisample_target(device, format, width, height, pipelines.sample_count);
    let depth =
        create_depth_target_with_sample_count(device, width, height, pipelines.sample_count);
    camera_uniform.view_projection = view_projection.to_cols_array_2d();
    camera_uniform.view_direction = view_direction_from_view_projection(view_projection)
        .extend(0.0)
        .to_array();
    camera_uniform.view_mode = view_mode.shader_mode();
    queue.write_buffer(camera_buffer, 0, bytemuck::bytes_of(camera_uniform));
    let bytes_per_row = padded_headless_bytes_per_row(width);
    let readback = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("CDMW Rust Mesh Lab headless readback"),
        size: u64::from(bytes_per_row) * u64::from(height),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("CDMW Rust Mesh Lab headless readback frame"),
    });
    record_headless_pass(
        &mut encoder,
        multisample.as_ref().map_or(&view, |target| &target.view),
        multisample.as_ref().map(|_| &view),
        &depth.view,
        mesh,
        default_material_bind_group,
        active_material_bindings,
        camera_bind_group,
        pipelines,
        view_mode,
        false,
        skeleton_lines,
        show_bones,
    );
    encoder.copy_texture_to_buffer(
        wgpu::TexelCopyTextureInfo {
            texture: &color,
            mip_level: 0,
            origin: wgpu::Origin3d::ZERO,
            aspect: wgpu::TextureAspect::All,
        },
        wgpu::TexelCopyBufferInfo {
            buffer: &readback,
            layout: wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(bytes_per_row),
                rows_per_image: Some(height),
            },
        },
        wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
    );
    queue.submit([encoder.finish()]);
    (readback, width, height)
}

fn read_headless_pixels(
    device: &wgpu::Device,
    readback: &wgpu::Buffer,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, RenderError> {
    let (sender, receiver) = std::sync::mpsc::channel();
    readback
        .slice(..)
        .map_async(wgpu::MapMode::Read, move |result| {
            let _ = sender.send(result);
        });
    device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|error| RenderError::Device(format!("headless readback wait failed: {error}")))?;
    receiver
        .recv()
        .map_err(|error| {
            RenderError::Device(format!("headless readback callback failed: {error}"))
        })?
        .map_err(|error| {
            RenderError::Device(format!("headless readback mapping failed: {error}"))
        })?;
    let mapped = readback.slice(..).get_mapped_range().map_err(|error| {
        RenderError::Device(format!("headless readback access failed: {error}"))
    })?;
    let tight_bytes_per_row = width.checked_mul(4).ok_or(RenderError::ResourceLimit)?;
    let padded_bytes_per_row = padded_headless_bytes_per_row(width);
    let expected_len = usize::try_from(u64::from(padded_bytes_per_row) * u64::from(height))
        .map_err(|_| RenderError::ResourceLimit)?;
    if mapped.len() != expected_len || mapped.len() < 4 {
        return Err(RenderError::Device(format!(
            "headless readback size mismatch: expected {expected_len}, got {}",
            mapped.len()
        )));
    }
    let tight_len = usize::try_from(u64::from(tight_bytes_per_row) * u64::from(height))
        .map_err(|_| RenderError::ResourceLimit)?;
    let mut pixels = Vec::with_capacity(tight_len);
    let tight_bytes_per_row =
        usize::try_from(tight_bytes_per_row).map_err(|_| RenderError::ResourceLimit)?;
    let padded_bytes_per_row =
        usize::try_from(padded_bytes_per_row).map_err(|_| RenderError::ResourceLimit)?;
    for row in mapped.chunks_exact(padded_bytes_per_row) {
        pixels.extend_from_slice(&row[..tight_bytes_per_row]);
    }
    drop(mapped);
    readback.unmap();
    Ok(pixels)
}

fn padded_headless_bytes_per_row(width: u32) -> u32 {
    const ALIGNMENT: u32 = wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
    width.saturating_mul(4).saturating_add(ALIGNMENT - 1) / ALIGNMENT * ALIGNMENT
}

fn write_bgra_material_proof_bmp(
    path: &Path,
    panel_width: u32,
    panel_height: u32,
    panels: &[&[u8]],
) -> Result<(), RenderError> {
    const COLUMN_COUNT: u32 = 3;
    const ROW_COUNT: u32 = 2;
    if panels.len() != usize::try_from(COLUMN_COUNT * ROW_COUNT).unwrap_or(6) {
        return Err(RenderError::Device(format!(
            "material proof requires six panels, received {}",
            panels.len()
        )));
    }
    let panel_len = usize::try_from(
        u64::from(panel_width)
            .checked_mul(u64::from(panel_height))
            .and_then(|pixels| pixels.checked_mul(4))
            .ok_or(RenderError::ResourceLimit)?,
    )
    .map_err(|_| RenderError::ResourceLimit)?;
    if panels.iter().any(|panel| panel.len() != panel_len) {
        return Err(RenderError::Device(
            "material proof panel dimensions do not match the readback dimensions".to_owned(),
        ));
    }
    let atlas_width = panel_width
        .checked_mul(COLUMN_COUNT)
        .ok_or(RenderError::ResourceLimit)?;
    let atlas_height = panel_height
        .checked_mul(ROW_COUNT)
        .ok_or(RenderError::ResourceLimit)?;
    let atlas_len = usize::try_from(
        u64::from(atlas_width)
            .checked_mul(u64::from(atlas_height))
            .and_then(|pixels| pixels.checked_mul(4))
            .ok_or(RenderError::ResourceLimit)?,
    )
    .map_err(|_| RenderError::ResourceLimit)?;
    let panel_row_len =
        usize::try_from(u64::from(panel_width) * 4).map_err(|_| RenderError::ResourceLimit)?;
    let atlas_row_len =
        usize::try_from(u64::from(atlas_width) * 4).map_err(|_| RenderError::ResourceLimit)?;
    let panel_height_usize =
        usize::try_from(panel_height).map_err(|_| RenderError::ResourceLimit)?;
    let panel_width_usize = usize::try_from(panel_width).map_err(|_| RenderError::ResourceLimit)?;
    let mut atlas = vec![0_u8; atlas_len];
    for (panel_index, panel) in panels.iter().enumerate() {
        let column = panel_index % usize::try_from(COLUMN_COUNT).unwrap_or(3);
        let row = panel_index / usize::try_from(COLUMN_COUNT).unwrap_or(3);
        for panel_y in 0..panel_height_usize {
            let source_start = panel_y * panel_row_len;
            let destination_y = row * panel_height_usize + panel_y;
            let destination_start = destination_y * atlas_row_len + column * panel_width_usize * 4;
            atlas[destination_start..destination_start + panel_row_len]
                .copy_from_slice(&panel[source_start..source_start + panel_row_len]);
        }
    }

    write_bgra_bmp(path, atlas_width, atlas_height, &atlas)
}

fn write_bgra_bmp(path: &Path, width: u32, height: u32, pixels: &[u8]) -> Result<(), RenderError> {
    let expected_len = usize::try_from(
        u64::from(width)
            .checked_mul(u64::from(height))
            .and_then(|pixel_count| pixel_count.checked_mul(4))
            .ok_or(RenderError::ResourceLimit)?,
    )
    .map_err(|_| RenderError::ResourceLimit)?;
    if pixels.len() != expected_len {
        return Err(RenderError::Device(format!(
            "BMP dimensions require {expected_len} BGRA bytes, received {}",
            pixels.len()
        )));
    }
    let image_size = u32::try_from(pixels.len()).map_err(|_| RenderError::ResourceLimit)?;
    let file_size = image_size
        .checked_add(54)
        .ok_or(RenderError::ResourceLimit)?;
    let width_i32 = i32::try_from(width).map_err(|_| RenderError::ResourceLimit)?;
    let height_i32 = i32::try_from(height).map_err(|_| RenderError::ResourceLimit)?;
    let mut bmp =
        Vec::with_capacity(usize::try_from(file_size).map_err(|_| RenderError::ResourceLimit)?);
    bmp.extend_from_slice(b"BM");
    bmp.extend_from_slice(&file_size.to_le_bytes());
    bmp.extend_from_slice(&[0_u8; 4]);
    bmp.extend_from_slice(&54_u32.to_le_bytes());
    bmp.extend_from_slice(&40_u32.to_le_bytes());
    bmp.extend_from_slice(&width_i32.to_le_bytes());
    bmp.extend_from_slice(&(-height_i32).to_le_bytes());
    bmp.extend_from_slice(&1_u16.to_le_bytes());
    bmp.extend_from_slice(&32_u16.to_le_bytes());
    bmp.extend_from_slice(&0_u32.to_le_bytes());
    bmp.extend_from_slice(&image_size.to_le_bytes());
    bmp.extend_from_slice(&2_835_i32.to_le_bytes());
    bmp.extend_from_slice(&2_835_i32.to_le_bytes());
    bmp.extend_from_slice(&0_u32.to_le_bytes());
    bmp.extend_from_slice(&0_u32.to_le_bytes());
    bmp.extend_from_slice(pixels);
    std::fs::write(path, bmp).map_err(|error| {
        RenderError::Device(format!(
            "failed to write headless capture BMP {}: {error}",
            path.display()
        ))
    })
}

fn changed_pixel_count(reference: &[u8], candidate: &[u8]) -> Result<usize, RenderError> {
    if reference.len() != candidate.len() || !reference.len().is_multiple_of(4) {
        return Err(RenderError::Device(format!(
            "headless pixel comparison size mismatch: {} versus {} bytes",
            reference.len(),
            candidate.len()
        )));
    }
    Ok(reference
        .chunks_exact(4)
        .zip(candidate.chunks_exact(4))
        .filter(|(reference, candidate)| reference != candidate)
        .count())
}

struct Pipelines {
    sample_count: u32,
    solid: wgpu::RenderPipeline,
    wire: wgpu::RenderPipeline,
    xray_wire: wgpu::RenderPipeline,
    point: wgpu::RenderPipeline,
    xray: wgpu::RenderPipeline,
    normal: wgpu::RenderPipeline,
    bounds: wgpu::RenderPipeline,
    bone: wgpu::RenderPipeline,
}

fn create_pipelines_with_sample_count(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    texture_layout: &wgpu::BindGroupLayout,
    camera_layout: &wgpu::BindGroupLayout,
    sample_count: u32,
) -> Pipelines {
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("CDMW Rust Mesh Lab shader"),
        source: wgpu::ShaderSource::Wgsl(SHADER.into()),
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("CDMW Rust Mesh Lab pipeline layout"),
        bind_group_layouts: &[Some(texture_layout), Some(camera_layout)],
        immediate_size: 0,
    });
    Pipelines {
        sample_count,
        solid: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "solid",
            wgpu::PrimitiveTopology::TriangleList,
            "fs_solid",
            solid_cull_mode(),
            PipelineDepth::Write,
            Some(wgpu::BlendState::REPLACE),
            sample_count,
        ),
        wire: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "wire",
            wgpu::PrimitiveTopology::LineList,
            "fs_wire",
            None,
            PipelineDepth::Test,
            Some(wgpu::BlendState::ALPHA_BLENDING),
            sample_count,
        ),
        xray_wire: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "xray wire",
            wgpu::PrimitiveTopology::LineList,
            "fs_wire",
            None,
            PipelineDepth::Ignore,
            Some(wgpu::BlendState::ALPHA_BLENDING),
            sample_count,
        ),
        point: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "points",
            wgpu::PrimitiveTopology::PointList,
            "fs_point",
            None,
            PipelineDepth::Write,
            Some(wgpu::BlendState::ALPHA_BLENDING),
            sample_count,
        ),
        xray: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "xray",
            wgpu::PrimitiveTopology::TriangleList,
            "fs_xray",
            None,
            PipelineDepth::Ignore,
            Some(wgpu::BlendState::ALPHA_BLENDING),
            sample_count,
        ),
        normal: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "normal overlay",
            wgpu::PrimitiveTopology::LineList,
            "fs_normal",
            None,
            PipelineDepth::Write,
            Some(wgpu::BlendState::ALPHA_BLENDING),
            sample_count,
        ),
        bounds: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "bounds overlay",
            wgpu::PrimitiveTopology::LineList,
            "fs_bounds",
            None,
            PipelineDepth::Ignore,
            Some(wgpu::BlendState::ALPHA_BLENDING),
            sample_count,
        ),
        bone: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "bone overlay",
            wgpu::PrimitiveTopology::LineList,
            "fs_bone",
            None,
            PipelineDepth::Ignore,
            Some(wgpu::BlendState::ALPHA_BLENDING),
            sample_count,
        ),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum PipelineDepth {
    Write,
    Test,
    Ignore,
}

const fn solid_cull_mode() -> Option<wgpu::Face> {
    // Authoring meshes can contain intentional interior shells or inconsistent
    // source winding. Keep both sides opaque; the depth buffer still selects
    // the nearest surface instead of making back-facing areas see-through.
    None
}

fn pipeline_depth_state(
    depth: PipelineDepth,
) -> (bool, wgpu::CompareFunction, wgpu::DepthBiasState) {
    match depth {
        PipelineDepth::Write => (
            true,
            wgpu::CompareFunction::LessEqual,
            wgpu::DepthBiasState::default(),
        ),
        PipelineDepth::Test => (
            false,
            wgpu::CompareFunction::LessEqual,
            wgpu::DepthBiasState::default(),
        ),
        PipelineDepth::Ignore => (
            false,
            wgpu::CompareFunction::Always,
            wgpu::DepthBiasState::default(),
        ),
    }
}

fn pipeline_vertex_entry(depth: PipelineDepth) -> &'static str {
    let _ = depth;
    "vs_main"
}

#[allow(clippy::too_many_arguments)]
fn create_pipeline(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    layout: &wgpu::PipelineLayout,
    shader: &wgpu::ShaderModule,
    label: &str,
    topology: wgpu::PrimitiveTopology,
    fragment_entry: &str,
    cull_mode: Option<wgpu::Face>,
    depth: PipelineDepth,
    blend: Option<wgpu::BlendState>,
    sample_count: u32,
) -> wgpu::RenderPipeline {
    let (depth_write_enabled, depth_compare, bias) = pipeline_depth_state(depth);
    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some(format!("CDMW Rust Mesh Lab {label} pipeline").as_str()),
        layout: Some(layout),
        vertex: wgpu::VertexState {
            module: shader,
            entry_point: Some(pipeline_vertex_entry(depth)),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            buffers: &[Some(GpuVertex::layout())],
        },
        primitive: wgpu::PrimitiveState {
            topology,
            cull_mode,
            front_face: wgpu::FrontFace::Ccw,
            ..Default::default()
        },
        depth_stencil: Some(wgpu::DepthStencilState {
            format: DEPTH_FORMAT,
            depth_write_enabled: Some(depth_write_enabled),
            depth_compare: Some(depth_compare),
            stencil: wgpu::StencilState::default(),
            bias,
        }),
        multisample: wgpu::MultisampleState {
            count: sample_count,
            ..Default::default()
        },
        fragment: Some(wgpu::FragmentState {
            module: shader,
            entry_point: Some(fragment_entry),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            targets: &[Some(wgpu::ColorTargetState {
                format,
                blend,
                write_mask: wgpu::ColorWrites::ALL,
            })],
        }),
        multiview_mask: None,
        cache: None,
    })
}

fn create_camera_bind_group_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
    device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("CDMW Rust Mesh Lab camera layout"),
        entries: &[wgpu::BindGroupLayoutEntry {
            binding: 0,
            visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
            ty: wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Uniform,
                has_dynamic_offset: false,
                min_binding_size: None,
            },
            count: None,
        }],
    })
}

fn create_depth_target_with_sample_count(
    device: &wgpu::Device,
    width: u32,
    height: u32,
    sample_count: u32,
) -> DepthTarget {
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("CDMW Rust Mesh Lab depth target"),
        size: wgpu::Extent3d {
            width: width.max(1),
            height: height.max(1),
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count,
        dimension: wgpu::TextureDimension::D2,
        format: DEPTH_FORMAT,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
        view_formats: &[],
    });
    let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
    DepthTarget {
        _texture: texture,
        view,
    }
}

fn create_multisample_target(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    width: u32,
    height: u32,
    sample_count: u32,
) -> Option<MultisampleTarget> {
    if sample_count <= 1 {
        return None;
    }
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("CDMW Rust Mesh Lab multisample color target"),
        size: wgpu::Extent3d {
            width: width.max(1),
            height: height.max(1),
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
        view_formats: &[],
    });
    let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
    Some(MultisampleTarget {
        _texture: texture,
        view,
    })
}

fn draw_solid<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    pipeline: &'a wgpu::RenderPipeline,
) {
    pass.set_pipeline(pipeline);
    pass.set_index_buffer(mesh.triangle_index.slice(..), wgpu::IndexFormat::Uint32);
    pass.draw_indexed(0..mesh.triangle_index_count, 0, 0..1);
}

fn draw_textured_solid<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    default_material_bind_group: &'a wgpu::BindGroup,
    active_material_bindings: &'a BTreeMap<u32, GpuMaterialBinding>,
    pipeline: &'a wgpu::RenderPipeline,
) {
    pass.set_pipeline(pipeline);
    pass.set_index_buffer(mesh.triangle_index.slice(..), wgpu::IndexFormat::Uint32);
    for range in &mesh.material_ranges {
        let bind_group = active_material_bindings
            .get(&range.material)
            .map_or(default_material_bind_group, |binding| &binding.bind_group);
        pass.set_bind_group(0, bind_group, &[]);
        pass.draw_indexed(
            range.first_index..range.first_index.saturating_add(range.index_count),
            0,
            range.part_id..range.part_id + 1,
        );
    }
}

fn draw_wire<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    pipeline: &'a wgpu::RenderPipeline,
) {
    pass.set_pipeline(pipeline);
    pass.set_index_buffer(mesh.wire_index.slice(..), wgpu::IndexFormat::Uint32);
    pass.draw_indexed(0..mesh.wire_index_count, 0, 0..1);
}

fn draw_points<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    pipeline: &'a wgpu::RenderPipeline,
) {
    pass.set_pipeline(pipeline);
    pass.draw(0..mesh.vertex_count, 0..1);
}

fn draw_overlay_lines<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    vertices: &'a wgpu::Buffer,
    vertex_count: u32,
    pipeline: &'a wgpu::RenderPipeline,
) {
    if vertex_count == 0 {
        return;
    }
    pass.set_pipeline(pipeline);
    pass.set_vertex_buffer(0, vertices.slice(..));
    pass.draw(0..vertex_count, 0..1);
}

#[allow(clippy::too_many_arguments)]
fn draw_mesh<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    default_material_bind_group: &'a wgpu::BindGroup,
    active_material_bindings: &'a BTreeMap<u32, GpuMaterialBinding>,
    camera_bind_group: &'a wgpu::BindGroup,
    solid_pipeline: &'a wgpu::RenderPipeline,
    wire_pipeline: &'a wgpu::RenderPipeline,
    xray_wire_pipeline: &'a wgpu::RenderPipeline,
    point_pipeline: &'a wgpu::RenderPipeline,
    xray_pipeline: &'a wgpu::RenderPipeline,
    normal_pipeline: &'a wgpu::RenderPipeline,
    bounds_pipeline: &'a wgpu::RenderPipeline,
    bone_pipeline: &'a wgpu::RenderPipeline,
    skeleton_lines: Option<&'a GpuOverlayLines>,
    preview_lines: Option<&'a GpuOverlayLines>,
    view_mode: ViewMode,
    show_normals: bool,
    show_bounds: bool,
    show_bones: bool,
) {
    pass.set_bind_group(0, default_material_bind_group, &[]);
    pass.set_bind_group(1, camera_bind_group, &[]);
    pass.set_vertex_buffer(0, mesh.vertex.slice(..));
    match view_mode {
        ViewMode::TexturedSolid
        | ViewMode::GameOutdoor
        | ViewMode::BaseColor
        | ViewMode::NormalMap
        | ViewMode::UvChecker
        | ViewMode::BaseAlpha
        | ViewMode::PartId
        | ViewMode::MaterialResponse
        | ViewMode::LayerMask => draw_textured_solid(
            pass,
            mesh,
            default_material_bind_group,
            active_material_bindings,
            solid_pipeline,
        ),
        ViewMode::Solid => draw_solid(pass, mesh, solid_pipeline),
        ViewMode::SolidWire => {
            draw_solid(pass, mesh, solid_pipeline);
            draw_wire(pass, mesh, wire_pipeline);
        }
        ViewMode::Wireframe => draw_wire(pass, mesh, wire_pipeline),
        ViewMode::Vertices => draw_points(pass, mesh, point_pipeline),
        ViewMode::WireVertices => {
            draw_wire(pass, mesh, wire_pipeline);
            draw_points(pass, mesh, point_pipeline);
        }
        ViewMode::XRay => {
            draw_solid(pass, mesh, xray_pipeline);
            draw_wire(pass, mesh, xray_wire_pipeline);
        }
    }
    if show_normals {
        draw_overlay_lines(
            pass,
            &mesh.normal_lines,
            mesh.normal_line_vertex_count,
            normal_pipeline,
        );
    }
    if show_bounds {
        draw_overlay_lines(
            pass,
            &mesh.bounds_lines,
            mesh.bounds_line_vertex_count,
            bounds_pipeline,
        );
    }
    if show_bones && let Some(lines) = skeleton_lines {
        draw_overlay_lines(pass, &lines.vertices, lines.vertex_count, bone_pipeline);
    }
    if let Some(lines) = preview_lines {
        draw_overlay_lines(pass, &lines.vertices, lines.vertex_count, bone_pipeline);
    }
}

const NORMAL_OVERLAY_MAX_LINES: usize = 2_500;
const NORMAL_OVERLAY_LENGTH_FACTOR: f32 = 0.006;

fn normal_line_vertices(snapshot: &DrawSnapshot) -> Vec<GpuVertex> {
    let Some((minimum, maximum)) = mesh_bounds(&snapshot.positions) else {
        return Vec::new();
    };
    let normal_length = (maximum - minimum).length().max(1.0e-3) * NORMAL_OVERLAY_LENGTH_FACTOR;
    let sample_stride = snapshot
        .positions
        .len()
        .div_ceil(NORMAL_OVERLAY_MAX_LINES)
        .max(1);
    let sampled_count = snapshot.positions.len().div_ceil(sample_stride);
    let mut lines = Vec::with_capacity(sampled_count.saturating_mul(2));
    for index in (0..snapshot.positions.len()).step_by(sample_stride) {
        let position = snapshot.positions[index];
        let origin = Vec3::from_array(position);
        if !origin.is_finite() {
            continue;
        }
        let normal = snapshot
            .normals
            .get(index)
            .copied()
            .map(Vec3::from_array)
            .filter(|normal| normal.is_finite())
            .and_then(Vec3::try_normalize)
            .unwrap_or(Vec3::Y);
        lines.push(GpuVertex::overlay(origin));
        lines.push(GpuVertex::overlay(origin + normal * normal_length));
    }
    lines
}

fn bounds_line_vertices(positions: &[[f32; 3]]) -> Vec<GpuVertex> {
    let Some((minimum, maximum)) = mesh_bounds(positions) else {
        return Vec::new();
    };
    let corners = [
        Vec3::new(minimum.x, minimum.y, minimum.z),
        Vec3::new(maximum.x, minimum.y, minimum.z),
        Vec3::new(maximum.x, maximum.y, minimum.z),
        Vec3::new(minimum.x, maximum.y, minimum.z),
        Vec3::new(minimum.x, minimum.y, maximum.z),
        Vec3::new(maximum.x, minimum.y, maximum.z),
        Vec3::new(maximum.x, maximum.y, maximum.z),
        Vec3::new(minimum.x, maximum.y, maximum.z),
    ];
    let edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ];
    edges
        .into_iter()
        .flat_map(|(first, second)| {
            [
                GpuVertex::overlay(corners[first]),
                GpuVertex::overlay(corners[second]),
            ]
        })
        .collect()
}

fn mesh_bounds(positions: &[[f32; 3]]) -> Option<(Vec3, Vec3)> {
    let mut finite = positions
        .iter()
        .copied()
        .map(Vec3::from_array)
        .filter(|position| position.is_finite());
    let first = finite.next()?;
    Some(finite.fold((first, first), |(minimum, maximum), position| {
        (minimum.min(position), maximum.max(position))
    }))
}

fn resolve_material_bindings<'a>(
    material_indices_by_texture: impl IntoIterator<Item = (TextureRole, &'a [Vec<u32>])>,
    lod_index: usize,
) -> Result<BTreeMap<u32, MaterialTextureIndices>, RenderError> {
    let mut active = BTreeMap::<u32, MaterialTextureIndices>::new();
    for (texture_index, (role, ownership)) in material_indices_by_texture.into_iter().enumerate() {
        let Some(materials) = ownership.get(lod_index) else {
            continue;
        };
        for material in materials {
            let slots = active.entry(*material).or_default();
            let slot = match role {
                TextureRole::BaseColor => &mut slots.base_color,
                TextureRole::Normal => &mut slots.normal,
                TextureRole::Material => &mut slots.surface,
                TextureRole::Roughness => &mut slots.roughness,
                TextureRole::Metalness => &mut slots.metalness,
                TextureRole::Occlusion => &mut slots.occlusion,
                TextureRole::Emissive => &mut slots.emissive,
                TextureRole::Specular => &mut slots.specular,
                TextureRole::Glossiness => &mut slots.glossiness,
                TextureRole::Opacity => &mut slots.opacity,
                TextureRole::Height => &mut slots.height,
                TextureRole::Flow => &mut slots.flow,
                TextureRole::LayerMask => &mut slots.layer_mask,
                TextureRole::SkinDetailMask => &mut slots.skin_detail_mask,
                TextureRole::SkinDetailNormal => &mut slots.skin_detail_normal,
                TextureRole::SkinDetailMaterial => &mut slots.skin_detail_material,
                _ => {
                    return Err(RenderError::Texture(format!(
                        "the {role:?} role is not sampled by the current material approximation"
                    )));
                }
            };
            if slot.replace(texture_index).is_some() {
                return Err(RenderError::Texture(format!(
                    "material {material} has more than one {role:?} texture in LOD {lod_index}"
                )));
            }
        }
    }
    Ok(active)
}

fn resolve_material_factors<'a>(
    factors_by_owner: impl IntoIterator<Item = (MaterialPreviewFactors, &'a [Vec<u32>])>,
    lod_index: usize,
) -> Result<BTreeMap<u32, MaterialPreviewFactors>, RenderError> {
    let mut active = BTreeMap::<u32, MaterialPreviewFactors>::new();
    for (factors, ownership) in factors_by_owner {
        let Some(materials) = ownership.get(lod_index) else {
            continue;
        };
        for material in materials {
            let resolved = active.entry(*material).or_default();
            if let Some(color) = factors.emissive_color {
                if resolved.emissive_color.is_some_and(|existing| {
                    existing
                        .into_iter()
                        .zip(color)
                        .any(|(left, right)| left.to_bits() != right.to_bits())
                }) {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting emissive colors in LOD {lod_index}"
                    )));
                }
                resolved.emissive_color = Some(color);
            }
            if let Some(texture_tint) = factors.texture_tint {
                if resolved.texture_tint.is_some_and(|existing| {
                    existing
                        .into_iter()
                        .zip(texture_tint)
                        .any(|(left, right)| left.to_bits() != right.to_bits())
                }) {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting texture tints in LOD {lod_index}"
                    )));
                }
                resolved.texture_tint = Some(texture_tint);
            }
            if let Some(base_tint_strength) = factors.base_tint_strength {
                if resolved
                    .base_tint_strength
                    .is_some_and(|existing| existing.to_bits() != base_tint_strength.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting base tint strengths in LOD {lod_index}"
                    )));
                }
                resolved.base_tint_strength = Some(base_tint_strength);
            }
            if let Some(intensity) = factors.emissive_intensity {
                if resolved
                    .emissive_intensity
                    .is_some_and(|existing| existing.to_bits() != intensity.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting emissive intensities in LOD {lod_index}"
                    )));
                }
                resolved.emissive_intensity = Some(intensity);
            }
            if let Some(roughness) = factors.roughness {
                if resolved
                    .roughness
                    .is_some_and(|existing| existing.to_bits() != roughness.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting roughness factors in LOD {lod_index}"
                    )));
                }
                resolved.roughness = Some(roughness);
            }
            if let Some(metalness) = factors.metalness {
                if resolved
                    .metalness
                    .is_some_and(|existing| existing.to_bits() != metalness.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting metalness factors in LOD {lod_index}"
                    )));
                }
                resolved.metalness = Some(metalness);
            }
            if let Some(specular) = factors.specular {
                if resolved
                    .specular
                    .is_some_and(|existing| existing.to_bits() != specular.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting specular factors in LOD {lod_index}"
                    )));
                }
                resolved.specular = Some(specular);
            }
            if let Some(height_scale) = factors.height_scale {
                if resolved
                    .height_scale
                    .is_some_and(|existing| existing.to_bits() != height_scale.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting height scales in LOD {lod_index}"
                    )));
                }
                resolved.height_scale = Some(height_scale);
            }
            if let Some(alpha_cutoff) = factors.alpha_cutoff {
                if resolved
                    .alpha_cutoff
                    .is_some_and(|existing| existing.to_bits() != alpha_cutoff.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting alpha cutoffs in LOD {lod_index}"
                    )));
                }
                resolved.alpha_cutoff = Some(alpha_cutoff);
            }
            if let Some(hair_anisotropy) = factors.hair_anisotropy {
                if resolved
                    .hair_anisotropy
                    .is_some_and(|existing| existing != hair_anisotropy)
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting hair anisotropy policies in LOD {lod_index}"
                    )));
                }
                resolved.hair_anisotropy = Some(hair_anisotropy);
            }
            if let Some(category_code) = factors.category_code {
                if resolved
                    .category_code
                    .is_some_and(|existing| existing != category_code)
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting category codes in LOD {lod_index}"
                    )));
                }
                resolved.category_code = Some(category_code);
            }
            if let Some(category_confidence) = factors.category_confidence {
                if resolved
                    .category_confidence
                    .is_some_and(|existing| existing.to_bits() != category_confidence.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting category confidence in LOD {lod_index}"
                    )));
                }
                resolved.category_confidence = Some(category_confidence);
            }
            if let Some(normal_y_inverted) = factors.normal_y_inverted {
                if resolved
                    .normal_y_inverted
                    .is_some_and(|existing| existing != normal_y_inverted)
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting normal-Y policies in LOD {lod_index}"
                    )));
                }
                resolved.normal_y_inverted = Some(normal_y_inverted);
            }
            if let Some(skin_detail_scale) = factors.skin_detail_scale {
                if resolved
                    .skin_detail_scale
                    .is_some_and(|existing| existing.to_bits() != skin_detail_scale.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting skin detail scales in LOD {lod_index}"
                    )));
                }
                resolved.skin_detail_scale = Some(skin_detail_scale);
            }
            if let Some(skin_detail_opacity) = factors.skin_detail_opacity {
                if resolved
                    .skin_detail_opacity
                    .is_some_and(|existing| existing.to_bits() != skin_detail_opacity.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting skin detail opacities in LOD {lod_index}"
                    )));
                }
                resolved.skin_detail_opacity = Some(skin_detail_opacity);
            }
            if let Some(layer_mask_channel) = factors.layer_mask_channel {
                if layer_mask_channel > 3 {
                    return Err(RenderError::Texture(format!(
                        "material {material} has invalid layer-mask channel {layer_mask_channel} in LOD {lod_index}"
                    )));
                }
                if resolved
                    .layer_mask_channel
                    .is_some_and(|existing| existing != layer_mask_channel)
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting layer-mask channels in LOD {lod_index}"
                    )));
                }
                resolved.layer_mask_channel = Some(layer_mask_channel);
            }
        }
    }
    Ok(active)
}

fn reproject_vertex_tangents(
    normals: &[[f32; 3]],
    tangents: &[[f32; 4]],
) -> Result<Vec<[f32; 4]>, RenderError> {
    if normals.len() != tangents.len() {
        return Err(RenderError::InvalidSnapshot(format!(
            "{} normals have {} cached tangents",
            normals.len(),
            tangents.len()
        )));
    }
    normals
        .iter()
        .zip(tangents)
        .map(|(normal, tangent)| {
            let normal = Vec3::from_array(*normal).try_normalize().unwrap_or(Vec3::Y);
            let tangent_vector = Vec3::from_array([tangent[0], tangent[1], tangent[2]]);
            let projected = tangent_vector - normal * normal.dot(tangent_vector);
            let fallback_axis = if normal.x.abs() < 0.9 {
                Vec3::X
            } else {
                Vec3::Y
            };
            let fallback = (fallback_axis - normal * normal.dot(fallback_axis))
                .try_normalize()
                .unwrap_or(Vec3::Z);
            let projected = projected.try_normalize().unwrap_or(fallback);
            let handedness = if tangent[3].is_finite() && tangent[3] < 0.0 {
                -1.0
            } else {
                1.0
            };
            Ok([projected.x, projected.y, projected.z, handedness])
        })
        .collect()
}

fn vertex_tangents(snapshot: &DrawSnapshot) -> Result<Vec<[f32; 4]>, RenderError> {
    if snapshot.positions.len() != snapshot.normals.len()
        || snapshot.positions.len() != snapshot.uvs.len()
    {
        return Err(RenderError::InvalidSnapshot(format!(
            "{} positions have {} normals and {} texture coordinates",
            snapshot.positions.len(),
            snapshot.normals.len(),
            snapshot.uvs.len()
        )));
    }
    if !snapshot.indices.len().is_multiple_of(3) {
        return Err(RenderError::InvalidSnapshot(
            "triangle index count is not divisible by three".to_owned(),
        ));
    }
    let mut accumulated_tangent = vec![Vec3::ZERO; snapshot.positions.len()];
    let mut accumulated_bitangent = vec![Vec3::ZERO; snapshot.positions.len()];
    for triangle in snapshot.indices.chunks_exact(3) {
        let indices = [
            usize::try_from(triangle[0]).map_err(|_| RenderError::ResourceLimit)?,
            usize::try_from(triangle[1]).map_err(|_| RenderError::ResourceLimit)?,
            usize::try_from(triangle[2]).map_err(|_| RenderError::ResourceLimit)?,
        ];
        let mut positions = [Vec3::ZERO; 3];
        let mut uvs = [Vec2::ZERO; 3];
        for (corner, index) in indices.iter().copied().enumerate() {
            positions[corner] = snapshot
                .positions
                .get(index)
                .copied()
                .map(Vec3::from_array)
                .ok_or_else(|| {
                    RenderError::InvalidSnapshot(format!(
                        "triangle index {index} exceeds the vertex count"
                    ))
                })?;
            uvs[corner] = Vec2::from_array(snapshot.uvs[index]);
        }
        let edge_one = positions[1] - positions[0];
        let edge_two = positions[2] - positions[0];
        let uv_one = uvs[1] - uvs[0];
        let uv_two = uvs[2] - uvs[0];
        let determinant = uv_one.x * uv_two.y - uv_one.y * uv_two.x;
        if !determinant.is_finite() || determinant.abs() <= 1.0e-12 {
            continue;
        }
        let reciprocal = determinant.recip();
        let tangent = (edge_one * uv_two.y - edge_two * uv_one.y) * reciprocal;
        let bitangent = (edge_two * uv_one.x - edge_one * uv_two.x) * reciprocal;
        if !tangent.is_finite() || !bitangent.is_finite() {
            continue;
        }
        for index in indices {
            accumulated_tangent[index] += tangent;
            accumulated_bitangent[index] += bitangent;
        }
    }
    Ok(snapshot
        .normals
        .iter()
        .enumerate()
        .map(|(index, normal)| {
            let normal = Vec3::from_array(*normal).try_normalize().unwrap_or(Vec3::Y);
            let projected =
                accumulated_tangent[index] - normal * normal.dot(accumulated_tangent[index]);
            let fallback_axis = if normal.x.abs() < 0.9 {
                Vec3::X
            } else {
                Vec3::Y
            };
            let fallback = (fallback_axis - normal * normal.dot(fallback_axis))
                .try_normalize()
                .unwrap_or(Vec3::Z);
            let tangent = projected.try_normalize().unwrap_or(fallback);
            let handedness = if normal.cross(tangent).dot(accumulated_bitangent[index]) < 0.0 {
                -1.0
            } else {
                1.0
            };
            [tangent.x, tangent.y, tangent.z, handedness]
        })
        .collect())
}

fn material_index_batches(
    snapshot: &DrawSnapshot,
) -> Result<(Vec<u32>, Vec<GpuMaterialRange>), RenderError> {
    if !snapshot.indices.len().is_multiple_of(3) {
        return Err(RenderError::InvalidSnapshot(
            "triangle index count is not divisible by three".to_owned(),
        ));
    }
    let triangle_count = snapshot.indices.len() / 3;
    if snapshot.triangle_materials.len() != triangle_count {
        return Err(RenderError::InvalidSnapshot(format!(
            "{} triangles have {} material owners",
            triangle_count,
            snapshot.triangle_materials.len()
        )));
    }
    let mut grouped = BTreeMap::<u32, Vec<u32>>::new();
    for (triangle, material) in snapshot
        .indices
        .chunks_exact(3)
        .zip(snapshot.triangle_materials.iter().copied())
    {
        grouped
            .entry(material)
            .or_default()
            .extend_from_slice(triangle);
    }
    let mut indices = Vec::with_capacity(snapshot.indices.len());
    let mut ranges = Vec::with_capacity(grouped.len());
    for (material, material_indices) in grouped {
        let part_id = u32::try_from(ranges.len()).map_err(|_| RenderError::ResourceLimit)?;
        let first_index = u32::try_from(indices.len()).map_err(|_| RenderError::ResourceLimit)?;
        let index_count =
            u32::try_from(material_indices.len()).map_err(|_| RenderError::ResourceLimit)?;
        indices.extend(material_indices);
        ranges.push(GpuMaterialRange {
            material,
            part_id,
            first_index,
            index_count,
        });
    }
    Ok((indices, ranges))
}

fn unique_wire_indices(indices: &[u32]) -> Vec<u32> {
    let mut edge_set = HashSet::new();
    let mut wire_indices = Vec::with_capacity(indices.len().saturating_mul(2));
    for triangle in indices.chunks_exact(3) {
        for (first, second) in [
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ] {
            let edge = if first <= second {
                (first, second)
            } else {
                (second, first)
            };
            if edge_set.insert(edge) {
                wire_indices.extend_from_slice(&[first, second]);
            }
        }
    }
    wire_indices
}

fn create_texture_bind_group_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
    device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("CDMW Rust Mesh Lab texture layout"),
        entries: &[
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 2,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 3,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 4,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 5,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 6,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 7,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 8,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 9,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 10,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 11,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 12,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 13,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 14,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 15,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 16,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 17,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
        ],
    })
}

fn create_material_sampler(device: &wgpu::Device, anisotropy_clamp: u16) -> wgpu::Sampler {
    device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("CDMW Rust Mesh Lab material sampler"),
        address_mode_u: wgpu::AddressMode::Repeat,
        address_mode_v: wgpu::AddressMode::Repeat,
        address_mode_w: wgpu::AddressMode::Repeat,
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        mipmap_filter: wgpu::MipmapFilterMode::Linear,
        anisotropy_clamp,
        ..Default::default()
    })
}

fn create_solid_texture(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    label: &str,
    format: wgpu::TextureFormat,
    pixel: [u8; 4],
) -> wgpu::Texture {
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some(label),
        size: wgpu::Extent3d {
            width: 1,
            height: 1,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    queue.write_texture(
        wgpu::TexelCopyTextureInfo {
            texture: &texture,
            mip_level: 0,
            origin: wgpu::Origin3d::ZERO,
            aspect: wgpu::TextureAspect::All,
        },
        &pixel,
        wgpu::TexelCopyBufferLayout {
            offset: 0,
            bytes_per_row: Some(4),
            rows_per_image: Some(1),
        },
        wgpu::Extent3d {
            width: 1,
            height: 1,
            depth_or_array_layers: 1,
        },
    );
    texture
}

fn create_default_material_textures(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
) -> DefaultMaterialTextures {
    DefaultMaterialTextures {
        base_color: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default base color",
            wgpu::TextureFormat::Rgba8UnormSrgb,
            NEUTRAL_MISSING_BASE_COLOR_SRGB,
        ),
        normal: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default tangent normal",
            wgpu::TextureFormat::Rgba8Unorm,
            [128, 128, 255, 255],
        ),
        surface: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default material surface",
            wgpu::TextureFormat::Rgba8Unorm,
            [255, 166, 0, 255],
        ),
        roughness: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default roughness",
            wgpu::TextureFormat::Rgba8Unorm,
            [166, 0, 0, 255],
        ),
        metalness: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default metalness",
            wgpu::TextureFormat::Rgba8Unorm,
            [0, 0, 0, 255],
        ),
        occlusion: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default occlusion",
            wgpu::TextureFormat::Rgba8Unorm,
            [255, 0, 0, 255],
        ),
        emissive: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default emissive",
            wgpu::TextureFormat::Rgba8UnormSrgb,
            [0, 0, 0, 255],
        ),
        specular: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default specular",
            wgpu::TextureFormat::Rgba8Unorm,
            [0, 0, 0, 255],
        ),
        glossiness: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default glossiness",
            wgpu::TextureFormat::Rgba8Unorm,
            [0, 0, 0, 255],
        ),
        opacity: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default opacity",
            wgpu::TextureFormat::Rgba8Unorm,
            [255, 255, 255, 255],
        ),
        height: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default height",
            wgpu::TextureFormat::Rgba8Unorm,
            [128, 128, 128, 255],
        ),
        flow: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default hair flow",
            wgpu::TextureFormat::Rgba8Unorm,
            [128, 255, 0, 255],
        ),
        layer_mask: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default layer mask",
            wgpu::TextureFormat::Rgba8Unorm,
            [255, 255, 255, 255],
        ),
    }
}

fn material_texture_tint_uniform(factors: MaterialPreviewFactors) -> Option<[f32; 4]> {
    factors.texture_tint.map(|tint| {
        [
            tint[0],
            tint[1],
            tint[2],
            factors.base_tint_strength.unwrap_or(0.0),
        ]
    })
}

fn create_material_bind_group(
    device: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    sampler: &wgpu::Sampler,
    defaults: &DefaultMaterialTextures,
    textures: &[GpuMaterialTexture],
    indices: MaterialTextureIndices,
    factors: MaterialPreviewFactors,
) -> GpuMaterialBinding {
    let base_texture = indices
        .base_color
        .and_then(|index| textures.get(index))
        .map_or(&defaults.base_color, |texture| &texture._texture);
    let normal_texture = indices
        .normal
        .and_then(|index| textures.get(index))
        .map_or(&defaults.normal, |texture| &texture._texture);
    let surface_texture = indices
        .surface
        .and_then(|index| textures.get(index))
        .map_or(&defaults.surface, |texture| &texture._texture);
    let roughness_texture = indices
        .roughness
        .and_then(|index| textures.get(index))
        .map_or(&defaults.roughness, |texture| &texture._texture);
    let metalness_texture = indices
        .metalness
        .and_then(|index| textures.get(index))
        .map_or(&defaults.metalness, |texture| &texture._texture);
    let occlusion_texture = indices
        .occlusion
        .and_then(|index| textures.get(index))
        .map_or(&defaults.occlusion, |texture| &texture._texture);
    let emissive_texture = indices
        .emissive
        .and_then(|index| textures.get(index))
        .map_or(&defaults.emissive, |texture| &texture._texture);
    let specular_texture = indices
        .specular
        .and_then(|index| textures.get(index))
        .map_or(&defaults.specular, |texture| &texture._texture);
    let glossiness_texture = indices
        .glossiness
        .and_then(|index| textures.get(index))
        .map_or(&defaults.glossiness, |texture| &texture._texture);
    let opacity_texture = indices
        .opacity
        .and_then(|index| textures.get(index))
        .map_or(&defaults.opacity, |texture| &texture._texture);
    let height_texture = indices
        .height
        .and_then(|index| textures.get(index))
        .map_or(&defaults.height, |texture| &texture._texture);
    let flow_texture = indices
        .flow
        .and_then(|index| textures.get(index))
        .map_or(&defaults.flow, |texture| &texture._texture);
    let layer_mask_texture = indices
        .layer_mask
        .and_then(|index| textures.get(index))
        .map_or(&defaults.layer_mask, |texture| &texture._texture);
    let skin_detail_mask_texture = indices
        .skin_detail_mask
        .and_then(|index| textures.get(index))
        .map_or(&defaults.layer_mask, |texture| &texture._texture);
    let skin_detail_normal_texture = indices
        .skin_detail_normal
        .and_then(|index| textures.get(index))
        .map_or(&defaults.normal, |texture| &texture._texture);
    let skin_detail_material_texture = indices
        .skin_detail_material
        .and_then(|index| textures.get(index))
        .map_or(&defaults.surface, |texture| &texture._texture);
    let base_view = base_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let normal_view = normal_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let surface_view = surface_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let roughness_view = roughness_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let metalness_view = metalness_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let occlusion_view = occlusion_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let emissive_view = emissive_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let specular_view = specular_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let glossiness_view = glossiness_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let opacity_view = opacity_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let height_view = height_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let flow_view = flow_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let layer_mask_view = layer_mask_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let skin_detail_mask_view =
        skin_detail_mask_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let skin_detail_normal_view =
        skin_detail_normal_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let skin_detail_material_view =
        skin_detail_material_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let mut flags = 0;
    if indices.base_color.is_some() {
        flags |= MATERIAL_BASE_COLOR;
    }
    if indices.normal.is_some() {
        flags |= MATERIAL_NORMAL;
    }
    if indices.surface.is_some() {
        flags |= MATERIAL_SURFACE;
    }
    if indices.roughness.is_some() {
        flags |= MATERIAL_ROUGHNESS;
    }
    if indices.metalness.is_some() {
        flags |= MATERIAL_METALNESS;
    }
    if indices.occlusion.is_some() {
        flags |= MATERIAL_OCCLUSION;
    }
    if indices.emissive.is_some() {
        flags |= MATERIAL_EMISSIVE;
    }
    if indices
        .emissive
        .and_then(|index| textures.get(index))
        .is_some_and(|texture| texture.single_channel)
    {
        flags |= MATERIAL_EMISSIVE_INTENSITY_MASK;
    }
    if indices.specular.is_some() {
        flags |= MATERIAL_SPECULAR;
    }
    if indices.glossiness.is_some() {
        flags |= MATERIAL_GLOSSINESS;
    }
    if indices.opacity.is_some() {
        flags |= MATERIAL_OPACITY;
    }
    if indices.height.is_some() {
        flags |= MATERIAL_HEIGHT;
    }
    if indices.flow.is_some() && factors.hair_anisotropy == Some(true) {
        flags |= MATERIAL_HAIR_FLOW;
    }
    if indices.layer_mask.is_some() {
        flags |= MATERIAL_LAYER_MASK;
    }
    let skin_detail_ready =
        factors.skin_detail_scale.is_some() && factors.skin_detail_opacity.is_some();
    if skin_detail_ready && indices.skin_detail_mask.is_some() {
        flags |= MATERIAL_SKIN_DETAIL_MASK;
    }
    if skin_detail_ready && indices.skin_detail_normal.is_some() {
        flags |= MATERIAL_SKIN_DETAIL_NORMAL;
    }
    if skin_detail_ready && indices.skin_detail_material.is_some() {
        flags |= MATERIAL_SKIN_DETAIL_MATERIAL;
    }
    if factors.roughness.is_some() {
        flags |= MATERIAL_ROUGHNESS_FACTOR;
    }
    if factors.metalness.is_some() {
        flags |= MATERIAL_METALNESS_FACTOR;
    }
    if factors.specular.is_some() {
        flags |= MATERIAL_SPECULAR_FACTOR;
    }
    if factors.alpha_cutoff.is_some_and(|cutoff| cutoff > 0.0) {
        flags |= MATERIAL_ALPHA_CUTOUT;
    }
    if factors.normal_y_inverted == Some(true) {
        flags |= MATERIAL_NORMAL_Y_INVERTED;
    }
    if factors.category_code.is_some() {
        flags |= MATERIAL_CATEGORY;
    }
    let texture_tint_and_strength = material_texture_tint_uniform(factors);
    if texture_tint_and_strength.is_some() {
        flags |= MATERIAL_TEXTURE_TINT;
    }
    let uniform = MaterialUniform {
        flags,
        skin_detail_scale: factors.skin_detail_scale.unwrap_or(1.0),
        skin_detail_opacity: factors.skin_detail_opacity.unwrap_or(0.0),
        _padding: 0,
        emissive_color_and_intensity: {
            let color = factors.emissive_color.unwrap_or([1.0; 3]);
            [
                color[0],
                color[1],
                color[2],
                factors.emissive_intensity.unwrap_or(1.0),
            ]
        },
        surface_factors: [
            factors.roughness.unwrap_or(0.0),
            factors.metalness.unwrap_or(0.0),
            factors.specular.unwrap_or(0.0),
            factors.alpha_cutoff.unwrap_or(0.0),
        ],
        relief_factors: [
            factors.height_scale.unwrap_or(0.025),
            factors.layer_mask_channel.unwrap_or(0) as f32,
            factors.category_code.unwrap_or(0) as f32,
            factors.category_confidence.unwrap_or(0.35),
        ],
        texture_tint_and_strength: texture_tint_and_strength.unwrap_or([1.0, 1.0, 1.0, 0.0]),
    };
    let uniform_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("CDMW Rust Mesh Lab material uniform"),
        contents: bytemuck::bytes_of(&uniform),
        usage: wgpu::BufferUsages::UNIFORM,
    });
    let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("CDMW Rust Mesh Lab texture bind group"),
        layout,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(&base_view),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::TextureView(&normal_view),
            },
            wgpu::BindGroupEntry {
                binding: 2,
                resource: wgpu::BindingResource::TextureView(&surface_view),
            },
            wgpu::BindGroupEntry {
                binding: 3,
                resource: wgpu::BindingResource::TextureView(&roughness_view),
            },
            wgpu::BindGroupEntry {
                binding: 4,
                resource: wgpu::BindingResource::TextureView(&metalness_view),
            },
            wgpu::BindGroupEntry {
                binding: 5,
                resource: wgpu::BindingResource::TextureView(&occlusion_view),
            },
            wgpu::BindGroupEntry {
                binding: 6,
                resource: wgpu::BindingResource::TextureView(&emissive_view),
            },
            wgpu::BindGroupEntry {
                binding: 7,
                resource: wgpu::BindingResource::Sampler(sampler),
            },
            wgpu::BindGroupEntry {
                binding: 8,
                resource: uniform_buffer.as_entire_binding(),
            },
            wgpu::BindGroupEntry {
                binding: 9,
                resource: wgpu::BindingResource::TextureView(&specular_view),
            },
            wgpu::BindGroupEntry {
                binding: 10,
                resource: wgpu::BindingResource::TextureView(&opacity_view),
            },
            wgpu::BindGroupEntry {
                binding: 11,
                resource: wgpu::BindingResource::TextureView(&height_view),
            },
            wgpu::BindGroupEntry {
                binding: 12,
                resource: wgpu::BindingResource::TextureView(&flow_view),
            },
            wgpu::BindGroupEntry {
                binding: 13,
                resource: wgpu::BindingResource::TextureView(&layer_mask_view),
            },
            wgpu::BindGroupEntry {
                binding: 14,
                resource: wgpu::BindingResource::TextureView(&skin_detail_mask_view),
            },
            wgpu::BindGroupEntry {
                binding: 15,
                resource: wgpu::BindingResource::TextureView(&skin_detail_normal_view),
            },
            wgpu::BindGroupEntry {
                binding: 16,
                resource: wgpu::BindingResource::TextureView(&skin_detail_material_view),
            },
            wgpu::BindGroupEntry {
                binding: 17,
                resource: wgpu::BindingResource::TextureView(&glossiness_view),
            },
        ],
    });
    GpuMaterialBinding {
        bind_group,
        _uniform_buffer: uniform_buffer,
    }
}

struct UploadedDdsTexture {
    texture: wgpu::Texture,
    single_channel: bool,
}

fn dds_format_is_single_channel(format: &DdsFormat) -> bool {
    matches!(
        format,
        DdsFormat::Bc4Unorm | DdsFormat::Bc4Snorm | DdsFormat::R8Unorm
    )
}

fn upload_dds_texture(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    bytes: &[u8],
    role: TextureRole,
) -> Result<UploadedDdsTexture, RenderError> {
    let plan =
        plan_2d_upload(bytes, role).map_err(|error| RenderError::Texture(error.to_string()))?;
    let single_channel = dds_format_is_single_channel(&plan.metadata.format);
    let format = map_dds_format(&plan.metadata.format, plan.metadata.color_space)?;
    validate_dds_upload_requirements(&plan, format, &device.limits(), device.features())?;
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("CDMW Rust Mesh Lab DDS"),
        size: wgpu::Extent3d {
            width: plan.metadata.width,
            height: plan.metadata.height,
            depth_or_array_layers: 1,
        },
        mip_level_count: plan.metadata.mip_count,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    for level in &plan.levels {
        let data = bytes
            .get(level.byte_offset..level.byte_offset.saturating_add(level.byte_length))
            .ok_or_else(|| RenderError::Texture("DDS upload slice is truncated".to_owned()))?;
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &texture,
                mip_level: level.level,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            data,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(level.bytes_per_row),
                rows_per_image: Some(level.rows_per_image),
            },
            dds_mip_upload_extent(level.width, level.height, format),
        );
    }
    Ok(UploadedDdsTexture {
        texture,
        single_channel,
    })
}

fn validate_dds_upload_requirements(
    plan: &cdmw_texture::DdsUploadPlan,
    format: wgpu::TextureFormat,
    limits: &wgpu::Limits,
    features: wgpu::Features,
) -> Result<(), RenderError> {
    if format.is_compressed() && !features.contains(wgpu::Features::TEXTURE_COMPRESSION_BC) {
        return Err(RenderError::Texture(
            "selected adapter does not support BC texture upload".to_owned(),
        ));
    }
    if format == wgpu::TextureFormat::Rgba32Float
        && !features.contains(wgpu::Features::FLOAT32_FILTERABLE)
    {
        return Err(RenderError::Texture(
            "selected adapter does not support filterable RGBA32F texture upload".to_owned(),
        ));
    }

    let base_extent = wgpu::Extent3d {
        width: plan.metadata.width,
        height: plan.metadata.height,
        depth_or_array_layers: 1,
    };
    let maximum_dimension = limits.max_texture_dimension_2d;
    if base_extent.width > maximum_dimension || base_extent.height > maximum_dimension {
        return Err(RenderError::Texture(format!(
            "DDS dimensions {}x{} exceed the selected device 2D texture limit of {}",
            base_extent.width, base_extent.height, maximum_dimension
        )));
    }
    let maximum_mips = base_extent.max_mips(wgpu::TextureDimension::D2);
    if plan.metadata.mip_count == 0 || plan.metadata.mip_count > maximum_mips {
        return Err(RenderError::Texture(format!(
            "DDS mip count {} exceeds the {} mip levels available for {}x{}",
            plan.metadata.mip_count, maximum_mips, base_extent.width, base_extent.height
        )));
    }
    if plan.levels.len() != plan.metadata.mip_count as usize {
        return Err(RenderError::Texture(format!(
            "DDS upload plan contains {} mip levels for a declared count of {}",
            plan.levels.len(),
            plan.metadata.mip_count
        )));
    }
    for level in &plan.levels {
        if level.level >= plan.metadata.mip_count {
            return Err(RenderError::Texture(format!(
                "DDS upload plan contains out-of-range mip level {}",
                level.level
            )));
        }
        let expected = base_extent.mip_level_size(level.level, wgpu::TextureDimension::D2);
        if level.width != expected.width || level.height != expected.height {
            return Err(RenderError::Texture(format!(
                "DDS mip {} dimensions {}x{} do not match the expected {}x{}",
                level.level, level.width, level.height, expected.width, expected.height
            )));
        }
        let upload_extent = dds_mip_upload_extent(level.width, level.height, format);
        if upload_extent.width > maximum_dimension || upload_extent.height > maximum_dimension {
            return Err(RenderError::Texture(format!(
                "DDS mip {} upload extent {}x{} exceeds the selected device 2D texture limit of {}",
                level.level, upload_extent.width, upload_extent.height, maximum_dimension
            )));
        }
    }
    Ok(())
}

fn dds_mip_upload_extent(width: u32, height: u32, format: wgpu::TextureFormat) -> wgpu::Extent3d {
    wgpu::Extent3d {
        width,
        height,
        depth_or_array_layers: 1,
    }
    .physical_size(format)
}

fn map_dds_format(
    format: &DdsFormat,
    color_space: ColorSpace,
) -> Result<wgpu::TextureFormat, RenderError> {
    let supports_srgb = matches!(
        format,
        DdsFormat::Bc1Unorm
            | DdsFormat::Bc1Srgb
            | DdsFormat::Bc2Unorm
            | DdsFormat::Bc2Srgb
            | DdsFormat::Bc3Unorm
            | DdsFormat::Bc3Srgb
            | DdsFormat::Bc7Unorm
            | DdsFormat::Bc7Srgb
            | DdsFormat::Rgba8Unorm
            | DdsFormat::Rgba8Srgb
            | DdsFormat::Bgra8Unorm
            | DdsFormat::Bgra8Srgb
    );
    if color_space == ColorSpace::Srgb && !supports_srgb {
        return Err(RenderError::Texture(format!(
            "DDS format {format:?} has no sRGB wgpu sampling variant"
        )));
    }
    let mapped = match format {
        DdsFormat::Bc1Unorm | DdsFormat::Bc1Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bc1RgbaUnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bc1RgbaUnorm,
        },
        DdsFormat::Bc2Unorm | DdsFormat::Bc2Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bc2RgbaUnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bc2RgbaUnorm,
        },
        DdsFormat::Bc3Unorm | DdsFormat::Bc3Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bc3RgbaUnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bc3RgbaUnorm,
        },
        DdsFormat::Bc4Unorm => wgpu::TextureFormat::Bc4RUnorm,
        DdsFormat::Bc4Snorm => wgpu::TextureFormat::Bc4RSnorm,
        DdsFormat::Bc5Unorm => wgpu::TextureFormat::Bc5RgUnorm,
        DdsFormat::Bc5Snorm => wgpu::TextureFormat::Bc5RgSnorm,
        DdsFormat::Bc6hUnsignedFloat => wgpu::TextureFormat::Bc6hRgbUfloat,
        DdsFormat::Bc6hSignedFloat => wgpu::TextureFormat::Bc6hRgbFloat,
        DdsFormat::Bc7Unorm | DdsFormat::Bc7Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bc7RgbaUnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bc7RgbaUnorm,
        },
        DdsFormat::R8Unorm => wgpu::TextureFormat::R8Unorm,
        DdsFormat::Rg8Unorm => wgpu::TextureFormat::Rg8Unorm,
        DdsFormat::Rgba8Unorm | DdsFormat::Rgba8Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Rgba8UnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Rgba8Unorm,
        },
        DdsFormat::Bgra8Unorm | DdsFormat::Bgra8Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bgra8UnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bgra8Unorm,
        },
        DdsFormat::Rgba16Float => wgpu::TextureFormat::Rgba16Float,
        DdsFormat::Rgba32Float => wgpu::TextureFormat::Rgba32Float,
        DdsFormat::Unknown { .. } => {
            return Err(RenderError::Texture(
                "DDS format is not mapped to wgpu".to_owned(),
            ));
        }
    };
    Ok(mapped)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn legacy_dxt1() -> Vec<u8> {
        let mut bytes = vec![0_u8; 128 + 8];
        bytes[..4].copy_from_slice(b"DDS ");
        bytes[4..8].copy_from_slice(&124_u32.to_le_bytes());
        bytes[12..16].copy_from_slice(&4_u32.to_le_bytes());
        bytes[16..20].copy_from_slice(&4_u32.to_le_bytes());
        bytes[28..32].copy_from_slice(&1_u32.to_le_bytes());
        bytes[76..80].copy_from_slice(&32_u32.to_le_bytes());
        bytes[84..88].copy_from_slice(b"DXT1");
        bytes
    }

    fn dx10_rgba32_float() -> Vec<u8> {
        let mut bytes = vec![0_u8; 148 + 4 * 4 * 16];
        bytes[..4].copy_from_slice(b"DDS ");
        bytes[4..8].copy_from_slice(&124_u32.to_le_bytes());
        bytes[12..16].copy_from_slice(&4_u32.to_le_bytes());
        bytes[16..20].copy_from_slice(&4_u32.to_le_bytes());
        bytes[28..32].copy_from_slice(&1_u32.to_le_bytes());
        bytes[76..80].copy_from_slice(&32_u32.to_le_bytes());
        bytes[84..88].copy_from_slice(b"DX10");
        bytes[128..132].copy_from_slice(&2_u32.to_le_bytes());
        bytes[140..144].copy_from_slice(&1_u32.to_le_bytes());
        bytes
    }

    #[test]
    fn compressed_dds_mip_uploads_use_physical_block_extents() {
        let format = wgpu::TextureFormat::Bc1RgbaUnormSrgb;
        assert_eq!(
            dds_mip_upload_extent(8, 8, format),
            wgpu::Extent3d {
                width: 8,
                height: 8,
                depth_or_array_layers: 1,
            }
        );
        assert_eq!(
            dds_mip_upload_extent(2, 1, format),
            wgpu::Extent3d {
                width: 4,
                height: 4,
                depth_or_array_layers: 1,
            },
            "the final compressed mip still occupies one complete BC block"
        );
        assert_eq!(
            dds_mip_upload_extent(2, 1, wgpu::TextureFormat::Rgba8Unorm),
            wgpu::Extent3d {
                width: 2,
                height: 1,
                depth_or_array_layers: 1,
            },
            "uncompressed uploads retain their logical extent"
        );
    }

    #[test]
    fn dds_upload_preflight_rejects_device_dimension_and_physical_mip_overruns() {
        let features = wgpu::Features::TEXTURE_COMPRESSION_BC;
        let limits = wgpu::Limits {
            max_texture_dimension_2d: 2,
            ..Default::default()
        };
        let plan = plan_2d_upload(&legacy_dxt1(), TextureRole::BaseColor)
            .expect("legacy DXT1 upload plan");
        let error = validate_dds_upload_requirements(
            &plan,
            wgpu::TextureFormat::Bc1RgbaUnormSrgb,
            &limits,
            features,
        )
        .expect_err("4x4 DDS must exceed a 2D texture limit of 2");
        assert!(error.to_string().contains("DDS dimensions 4x4"));

        let mut sub_block_dds = legacy_dxt1();
        sub_block_dds[12..16].copy_from_slice(&1_u32.to_le_bytes());
        sub_block_dds[16..20].copy_from_slice(&2_u32.to_le_bytes());
        let plan = plan_2d_upload(&sub_block_dds, TextureRole::BaseColor)
            .expect("sub-block DXT1 upload plan");
        let error = validate_dds_upload_requirements(
            &plan,
            wgpu::TextureFormat::Bc1RgbaUnormSrgb,
            &limits,
            features,
        )
        .expect_err("the physical 4x4 BC block must exceed a 2D texture limit of 2");
        assert!(error.to_string().contains("mip 0 upload extent 4x4"));
    }

    #[test]
    fn rgba32_float_upload_requires_filterable_float_support() {
        let plan =
            plan_2d_upload(&dx10_rgba32_float(), TextureRole::Normal).expect("RGBA32F upload plan");
        let format = map_dds_format(&plan.metadata.format, plan.metadata.color_space)
            .expect("RGBA32F format mapping");
        assert_eq!(format, wgpu::TextureFormat::Rgba32Float);
        let error = validate_dds_upload_requirements(
            &plan,
            format,
            &wgpu::Limits::default(),
            wgpu::Features::empty(),
        )
        .expect_err("RGBA32F must be rejected without filterable-float support");
        assert!(error.to_string().contains("filterable RGBA32F"));
        validate_dds_upload_requirements(
            &plan,
            format,
            &wgpu::Limits::default(),
            wgpu::Features::FLOAT32_FILTERABLE,
        )
        .expect("RGBA32F is safe when filterable-float support is enabled");
    }

    #[test]
    fn shared_triangle_edges_are_uploaded_once() {
        let wire = unique_wire_indices(&[0, 1, 2, 2, 1, 3]);
        assert_eq!(wire.len(), 10);
        let edges = wire
            .chunks_exact(2)
            .map(|edge| {
                if edge[0] <= edge[1] {
                    (edge[0], edge[1])
                } else {
                    (edge[1], edge[0])
                }
            })
            .collect::<HashSet<_>>();
        assert_eq!(edges.len(), 5);
    }

    #[test]
    fn camera_uniform_matches_the_wgsl_scalar_padding_contract() {
        assert_eq!(std::mem::size_of::<CameraUniform>(), 128);
        let uniform = CameraUniform::new(true);
        assert_eq!(uniform.output_is_srgb, 1);
        assert_eq!(uniform.view_direction, [0.0, 0.0, -1.0, 0.0]);
        assert!(uniform.wire_colour[0] < 0.72);
        assert!(uniform.point_colour[0] < 0.92);
        assert_eq!(uniform.wire_colour[3], 1.0);
        assert_eq!(uniform.point_colour[3], 1.0);
        assert!(SHADER.contains("return present(camera.wire_colour.rgb"));
        assert!(SHADER.contains("return present(camera.point_colour.rgb"));
    }

    #[test]
    fn renderer_prefers_srgb_output_and_tracks_camera_facing_direction() {
        assert_eq!(
            preferred_surface_format(&[
                wgpu::TextureFormat::Bgra8Unorm,
                wgpu::TextureFormat::Rgba8UnormSrgb,
            ]),
            Some(wgpu::TextureFormat::Rgba8UnormSrgb)
        );
        assert_eq!(
            preferred_surface_format(&[wgpu::TextureFormat::Bgra8Unorm]),
            Some(wgpu::TextureFormat::Bgra8Unorm)
        );

        let projection = Mat4::perspective_rh(45_f32.to_radians(), 1.0, 0.1, 100.0);
        let front = projection * Mat4::look_at_rh(Vec3::new(0.0, 0.0, -5.0), Vec3::ZERO, Vec3::Y);
        let side = projection * Mat4::look_at_rh(Vec3::new(5.0, 0.0, 0.0), Vec3::ZERO, Vec3::Y);
        assert!(view_direction_from_view_projection(front).dot(-Vec3::Z) > 0.999);
        assert!(view_direction_from_view_projection(side).dot(Vec3::X) > 0.999);
    }

    #[test]
    fn integrated_startup_view_is_shared_by_front_and_depth_elongated_assets() {
        let character = integrated_startup_view(Vec3::new(1.0, 2.0, 0.5));
        assert!(character.eye_direction().dot(-Vec3::Z) > 0.999);
        assert!(character.up_direction().dot(Vec3::Y) > 0.999);

        let weapon = integrated_startup_view(Vec3::new(0.2, 0.08, 2.0));
        assert!(weapon.eye_direction().x > 0.75);
        assert!(weapon.eye_direction().y > 0.40);
        assert!(weapon.eye_direction().z.abs() < 1.0e-5);
        assert!(weapon.up_direction().z.abs() < 1.0e-5);
    }

    #[test]
    fn overlay_colours_are_finite_and_bounded_before_gpu_upload() {
        assert_eq!(
            bounded_rgba([1.5, -0.25, 0.5, 2.0]),
            Some([1.0, 0.0, 0.5, 1.0])
        );
        assert_eq!(bounded_rgba([f32::NAN, 0.0, 0.0, 1.0]), None);
    }

    #[test]
    fn material_uniform_and_vertex_match_the_wgsl_layout_contracts() {
        assert_eq!(std::mem::size_of::<MaterialUniform>(), 80);
        assert_eq!(std::mem::size_of::<GpuVertex>(), 64);
    }

    #[test]
    fn texture_tint_is_optional_owner_scoped_gpu_state() {
        assert_eq!(MATERIAL_TEXTURE_TINT, 8_388_608);
        assert_eq!(
            material_texture_tint_uniform(MaterialPreviewFactors {
                texture_tint: Some([0.73, 0.44, 0.24]),
                base_tint_strength: Some(0.85),
                ..MaterialPreviewFactors::default()
            }),
            Some([0.73, 0.44, 0.24, 0.85])
        );
        assert_eq!(
            material_texture_tint_uniform(MaterialPreviewFactors::default()),
            None
        );
        assert!(SHADER.contains("const MATERIAL_TEXTURE_TINT: u32 = 8388608u;"));
        assert!(SHADER.contains("if (material.flags & MATERIAL_TEXTURE_TINT) != 0u"));
        assert!(SHADER.contains("texel.rgb * texture_tint"));
        assert!(SHADER.contains("else if min(u32(material.relief_factors.z + 0.5), 11u) == 6u"));
        assert!(SHADER.contains("let linear_tint = srgb_to_linear(texture_tint);"));
        assert!(SHADER.contains("linear_tint / tint_luma"));
        assert!(SHADER.contains("mix(texel.rgb, dyed, tint_strength)"));
        assert!(SHADER.contains(
            "if is_hair && (material.flags & MATERIAL_TEXTURE_TINT) != 0u { material_lift = 0.0; }"
        ));
        assert!(SHADER.contains("texture_tint / tint_luma"));
        assert!(SHADER.contains("mix(texel.rgb, tinted, tint_strength)"));
    }

    #[test]
    fn material_fallback_and_shader_preserve_source_material_colour() {
        assert_eq!(
            NEUTRAL_MISSING_BASE_COLOR_SRGB,
            [144, 144, 144, 255],
            "factor-only materials must not sample a pale white fallback"
        );
        assert!(SHADER.contains("max(metalness, declared_metalness), has_source_metalness"));
        assert!(SHADER.contains("f0 * (target_peak / source_peak)"));
        let authored_guard = SHADER
            .find("let authored_metal_f0 =")
            .expect("authored metal F0 guard");
        let scalar_fallback = SHADER
            .find("if !authored_metal_f0 {")
            .expect("scalar specular fallback branch");
        let scalar_boost = SHADER
            .find("let target_peak = max(source_peak, factored_specular);")
            .expect("fallback metal scalar boost");
        assert!(SHADER[authored_guard..scalar_fallback].contains("has_source_metalness"));
        assert!(authored_guard < scalar_fallback && scalar_fallback < scalar_boost);
        let alpha_cutout = SHADER
            .find("if (material.flags & MATERIAL_ALPHA_CUTOUT) != 0u")
            .expect("alpha-cutout branch");
        let part_id = SHADER[alpha_cutout..]
            .find("if camera.view_mode == 8u")
            .map(|offset| alpha_cutout + offset)
            .expect("Part ID branch after alpha cutout");
        assert!(part_id > alpha_cutout);
    }

    #[test]
    fn authored_metal_response_uses_the_bounded_vortice_studio_environment() {
        assert!(!SHADER.contains("studio_metal_reflection_profile"));
        assert!(!SHADER.contains("studio_metal_profile"));
        assert!(!SHADER.contains("studio_metal_weight"));
        assert!(SHADER.contains("fn preview_environment_radiance("));
        assert!(SHADER.contains("fn preview_environment_irradiance("));
        assert!(SHADER.contains("fn environment_brdf_approx("));
        assert!(SHADER.contains("radiance = radiance / (1.0 + radiance_peak);"));
        assert!(SHADER.contains(
            "var environment_specular = environment_radiance\n        * environment_brdf"
        ));
        assert!(SHADER.contains(
            "let metal_multiple_scattering = environment_irradiance\n            * source_stable_f0\n            * metalness\n            * (roughness * roughness * 0.18)"
        ));
        assert!(SHADER.contains("let environment_diffuse_energy = clamp("));
        let source_stable_f0 = SHADER
            .find("let source_stable_f0 = f0;")
            .expect("authored source F0 anchor");
        let mapped_specular = SHADER
            .find("let mapped_specular = textureSampleBias(")
            .expect("optional mapped specular");
        let metal_environment = SHADER
            .find("let metal_environment_brdf = environment_brdf_approx(")
            .expect("metal environment BRDF");
        assert!(source_stable_f0 < mapped_specular && mapped_specular < metal_environment);
        assert!(SHADER.contains("let specular_power = mix(96.0, 8.0, roughness);"));
    }

    #[test]
    fn vortice_metal_readability_path_uses_source_coloured_bounded_ggx() {
        assert!(SHADER.contains("fn distribution_ggx("));
        assert!(SHADER.contains("fn geometry_smith("));
        assert!(SHADER.contains("fn fresnel_schlick("));
        assert!(SHADER.contains(
            "let metal_cook_torrance = metal_distribution\n            * metal_geometry\n            * metal_fresnel"
        ));
        assert!(
            SHADER.contains("let metal_fresnel = fresnel_schlick(metal_hdotv, source_stable_f0);")
        );
        assert!(SHADER.contains("vec3<f32>(0.85),"));
        assert!(SHADER.contains("shaded_albedo * (authored_base_scale + cloth_texture_boost)"));
        assert!(SHADER.contains("has_source_base_color && (is_cloth || is_leather)"));
        assert!(
            SHADER.contains("let metal_body_scale = select(0.34, 0.20, has_source_metalness);")
        );
        assert!(SHADER.contains("diffuse += material_reference_albedo * metal_cue * 0.16;"));
        assert!(!SHADER.contains("metal_cook_torrance + vec3<f32>"));

        fn fresnel_reference(cos_theta: f32, f0: Vec3) -> Vec3 {
            f0 + (Vec3::ONE - f0) * (1.0 - cos_theta.clamp(0.0, 1.0)).powi(5)
        }

        fn ggx_direct_reference(f0: Vec3, roughness: f32) -> Vec3 {
            let normal = Vec3::Z;
            let view = Vec3::Z;
            let light = Vec3::new(0.35, 0.20, 1.0).normalize();
            let half_vector = (light + view).normalize();
            let ndotl = normal.dot(light).clamp(0.0, 1.0);
            let ndotv = normal.dot(view).clamp(0.0, 1.0).max(1e-4);
            let ndoth = normal.dot(half_vector).clamp(0.0, 1.0);
            let hdotv = half_vector.dot(view).clamp(0.0, 1.0);
            let alpha = roughness * roughness;
            let alpha_squared = alpha * alpha;
            let denominator = ndoth * ndoth * (alpha_squared - 1.0) + 1.0;
            let distribution =
                alpha_squared / (std::f32::consts::PI * denominator * denominator).max(1e-5);
            let k = (roughness + 1.0).powi(2) / 8.0;
            let geometry_component = |ndot: f32| ndot / (ndot * (1.0 - k) + k).max(1e-5);
            let geometry = geometry_component(ndotv) * geometry_component(ndotl);
            let fresnel = fresnel_reference(hdotv, f0);
            (distribution * geometry * fresnel / (4.0 * ndotv * ndotl).max(1e-4) * ndotl)
                .min(Vec3::splat(0.85))
        }

        let authored_gold = Vec3::new(0.72, 0.30, 0.07);
        let response = ggx_direct_reference(authored_gold, 0.32);
        assert!(response.is_finite() && response.min_element() > 0.0);
        assert!(response.max_element() <= 0.85);
        assert!(response.x > response.y && response.y > response.z);

        let dark_source = Vec3::new(0.25, 0.12, 0.04);
        let source_luma = dark_source.dot(Vec3::new(0.299, 0.587, 0.114));
        let lifted = (dark_source * 1.03 + Vec3::splat(0.020 * (1.0 - source_luma)))
            .clamp(Vec3::ZERO, Vec3::ONE);
        assert!(lifted.dot(Vec3::new(0.299, 0.587, 0.114)) > source_luma);
        assert!(lifted.x > lifted.y && lifted.y > lifted.z);
    }

    #[test]
    fn environment_brdf_fit_stays_bounded_and_preserves_authored_metal_hue_order() {
        fn environment_brdf_reference(f0: Vec3, roughness: f32, ndotv: f32) -> Vec3 {
            let c0 = glam::Vec4::new(-1.0, -0.0275, -0.572, 0.022);
            let c1 = glam::Vec4::new(1.0, 0.0425, 1.04, -0.04);
            let fit = roughness.clamp(0.0, 1.0) * c0 + c1;
            let a004 =
                (fit.x * fit.x).min(2.0_f32.powf(-9.28 * ndotv.clamp(0.0, 1.0))) * fit.x + fit.y;
            let scale = -1.04 * a004 + fit.z;
            let bias = 1.04 * a004 + fit.w;
            (f0 * scale + Vec3::splat(bias)).clamp(Vec3::ZERO, Vec3::ONE)
        }

        let authored_gold = Vec3::new(0.82, 0.34, 0.08);
        for roughness in [0.04, 0.35, 0.75, 1.0] {
            for ndotv in [0.0, 0.25, 0.75, 1.0] {
                let response = environment_brdf_reference(authored_gold, roughness, ndotv);
                assert!(response.is_finite());
                assert!(response.min_element() >= 0.0 && response.max_element() <= 1.0);
                assert!(response.x >= response.y && response.y >= response.z);
            }
        }

        for radiance in [
            Vec3::new(7.5, 6.2, 4.6),
            Vec3::new(0.55, 0.65, 0.82),
            Vec3::new(0.32, 0.28, 0.24),
        ] {
            let peak = radiance.max_element();
            let compressed = radiance / (1.0 + peak);
            assert!(compressed.min_element() >= 0.0 && compressed.max_element() < 1.0);
            assert!((compressed.x / compressed.y - radiance.x / radiance.y).abs() < 1e-5);
        }
    }

    #[test]
    fn renderer_quality_prefers_supported_msaa_anisotropy_and_low_latency_vsync() {
        let color = wgpu::TextureFormatFeatureFlags::MULTISAMPLE_X4
            | wgpu::TextureFormatFeatureFlags::MULTISAMPLE_RESOLVE;
        let depth = wgpu::TextureFormatFeatureFlags::MULTISAMPLE_X4;
        assert_eq!(preferred_sample_count_from_flags(color, depth), 4);
        assert_eq!(
            preferred_sample_count_from_flags(
                wgpu::TextureFormatFeatureFlags::MULTISAMPLE_X4,
                depth
            ),
            1
        );
        assert_eq!(
            preferred_sample_count_from_flags(color, wgpu::TextureFormatFeatureFlags::empty()),
            1
        );
        assert_eq!(
            preferred_anisotropy_clamp(wgpu::DownlevelFlags::ANISOTROPIC_FILTERING),
            16
        );
        assert_eq!(preferred_anisotropy_clamp(wgpu::DownlevelFlags::empty()), 1);
        assert!(SHADER.contains("const MATERIAL_MIP_LOD_BIAS: f32 = -2.0;"));
        assert!(SHADER.contains("textureSampleBias(base_texture"));
        assert!(!SHADER.contains("textureSample("));
        assert_eq!(
            preferred_present_mode(&[
                wgpu::PresentMode::Immediate,
                wgpu::PresentMode::Fifo,
                wgpu::PresentMode::Mailbox,
            ]),
            Some(wgpu::PresentMode::Mailbox)
        );
        assert_eq!(
            preferred_present_mode(&[wgpu::PresentMode::Immediate, wgpu::PresentMode::Fifo]),
            Some(wgpu::PresentMode::Fifo)
        );
        assert_eq!(
            requested_renderer_features(
                wgpu::Features::TEXTURE_COMPRESSION_BC
                    | wgpu::Features::FLOAT32_FILTERABLE
                    | wgpu::Features::TIMESTAMP_QUERY
            ),
            wgpu::Features::TEXTURE_COMPRESSION_BC | wgpu::Features::FLOAT32_FILTERABLE
        );
    }

    #[test]
    fn scalar_emissive_maps_modulate_the_authored_emissive_colour() {
        assert!(dds_format_is_single_channel(&DdsFormat::Bc4Unorm));
        assert!(dds_format_is_single_channel(&DdsFormat::Bc4Snorm));
        assert!(dds_format_is_single_channel(&DdsFormat::R8Unorm));
        assert!(!dds_format_is_single_channel(&DdsFormat::Bc1Unorm));
        assert_eq!(MATERIAL_EMISSIVE_INTENSITY_MASK, 262_144);
        assert!(SHADER.contains("const MATERIAL_EMISSIVE_INTENSITY_MASK: u32 = 262144u;"));
        assert!(SHADER.contains("emissive_sample.rrr"));
    }

    #[test]
    fn skin_detail_uses_authored_scale_mask_channel_and_support_maps() {
        assert_eq!(std::mem::size_of::<MaterialUniform>(), 80);
        assert_eq!(MATERIAL_SKIN_DETAIL_MASK, 524_288);
        assert_eq!(MATERIAL_SKIN_DETAIL_NORMAL, 1_048_576);
        assert_eq!(MATERIAL_SKIN_DETAIL_MATERIAL, 2_097_152);
        assert!(SHADER.contains("skin_detail_mask_texture"));
        assert!(SHADER.contains("input.uv / max(material.skin_detail_scale, 0.001)"));
        assert!(SHADER.contains("skin_detail_mask_texture,"));
        assert!(SHADER.contains("MATERIAL_MIP_LOD_BIAS).r * material.skin_detail_opacity"));
        assert!(SHADER.contains("tangent_normal.xy + detail_normal.xy"));
        assert!(SHADER.contains("mix(roughness, skin_detail_surface.g, skin_detail_weight)"));
        assert!(SHADER.contains("if is_skin {\n        metalness = 0.0;"));
    }

    #[test]
    fn skin_specular_response_uses_green_roughness_and_red_scatter_without_equipment_drift() {
        fn apply_skin_specular_reference(
            is_skin: bool,
            has_specular: bool,
            sample: Vec3,
            roughness: f32,
            metalness: f32,
        ) -> (f32, f32, f32) {
            if !is_skin || !has_specular {
                return (roughness, metalness, 1.0);
            }
            (
                sample.y.clamp(0.04, 1.0),
                0.0,
                0.65 + (1.10 - 0.65) * sample.x.clamp(0.0, 1.0),
            )
        }

        let authored_skin =
            apply_skin_specular_reference(true, true, Vec3::new(0.77, 0.42, 0.997), 0.66, 0.81);
        assert!((authored_skin.0 - 0.42).abs() < 1e-6);
        assert_eq!(authored_skin.1, 0.0, "skin blue never becomes metalness");
        assert!((0.65..=1.10).contains(&authored_skin.2));

        let standard =
            apply_skin_specular_reference(false, true, Vec3::new(0.12, 0.91, 0.84), 0.28, 0.73);
        assert_eq!(
            standard,
            (0.28, 0.73, 1.0),
            "equipment surface channels remain outside the skin-only response"
        );

        let skin_gate = SHADER
            .find("let has_skin_specular_response =")
            .expect("skin/specular gate");
        let category_fallback = SHADER[skin_gate..]
            .find("if !has_source_roughness {")
            .map(|offset| skin_gate + offset)
            .expect("category roughness fallback");
        let skin_response = &SHADER[skin_gate..category_fallback];
        assert!(skin_response.contains("is_skin && (material.flags & MATERIAL_SPECULAR) != 0u"));
        assert!(skin_response.contains("|| has_skin_specular_response;"));
        assert!(skin_response.contains("roughness = clamp(skin_specular_response.g, 0.04, 1.0);"));
        assert!(skin_response.contains("clamp(skin_specular_response.r, 0.0, 1.0)"));
        assert!(!skin_response.contains("skin_specular_response.b"));
        assert!(SHADER.contains("* skin_subsurface_multiplier,"));
        assert!(SHADER.contains("if (material.flags & MATERIAL_SPECULAR) != 0u && !is_skin {"));
        assert!(
            SHADER.contains("let source_weight = max(metalness, select(0.0, 0.75, is_glossy));")
        );
        assert!(SHADER.contains("if is_skin {\n        metalness = 0.0;"));
    }

    #[test]
    fn same_topology_updates_geometry_in_place_and_topology_changes_replace_buffers() {
        let current = MeshUploadKey {
            mesh_identity: 7,
            draw_revision: 10,
            topology_generation: 3,
            topology_signature: 99,
            deformation_signature: 0,
        };
        assert_eq!(
            classify_mesh_upload(current, current),
            MeshUploadAction::Reuse
        );
        assert_eq!(
            classify_mesh_upload(
                current,
                MeshUploadKey {
                    draw_revision: 11,
                    ..current
                }
            ),
            MeshUploadAction::UpdateGeometry
        );
        assert_eq!(
            classify_mesh_upload(
                current,
                MeshUploadKey {
                    deformation_signature: 42,
                    ..current
                }
            ),
            MeshUploadAction::UpdateGeometry
        );
        for changed in [
            MeshUploadKey {
                mesh_identity: 8,
                ..current
            },
            MeshUploadKey {
                topology_generation: 4,
                ..current
            },
            MeshUploadKey {
                topology_signature: 100,
                ..current
            },
        ] {
            assert_eq!(
                classify_mesh_upload(current, changed),
                MeshUploadAction::Replace
            );
        }
        assert_eq!(
            resolve_mesh_upload_action(
                MeshUploadAction::Reuse,
                GeometryUpdateMode::Interactive,
                false,
            ),
            MeshUploadAction::Reuse,
            "an unchanged interactive sample must not force duplicate work"
        );
        assert_eq!(
            resolve_mesh_upload_action(MeshUploadAction::Reuse, GeometryUpdateMode::Final, false,),
            MeshUploadAction::UpdateGeometry,
            "gesture completion must restore an exact tangent basis"
        );
    }

    #[test]
    fn deformation_heatmap_uses_green_yellow_red_magnitude_scale() {
        let snapshot = DrawSnapshot {
            mesh_identity: 1,
            draw_revision: 1,
            topology_generation: 1,
            positions: vec![
                [0.0, 0.0, 0.1],
                [20.0, 0.0, -0.5],
                [1.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
            ],
            normals: vec![[0.0, 0.0, 1.0]; 4],
            uvs: vec![[0.0, 0.0]; 4],
            indices: Vec::new(),
            triangle_materials: Vec::new(),
            selected_vertices: Vec::new(),
            fingerprint: String::new(),
        };
        let reference = vec![
            [0.0, 0.0, 0.0],
            [20.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ];
        let colours = deformation_colours(&snapshot, Some(&reference)).expect("heatmap colours");
        let mut small_only = snapshot.clone();
        small_only.positions[1] = reference[1];
        small_only.positions[2] = reference[2];
        let small_only_colours =
            deformation_colours(&small_only, Some(&reference)).expect("small heatmap colours");
        assert_eq!(
            colours[0], small_only_colours[0],
            "a larger edit elsewhere must not recolour an earlier displacement"
        );
        assert!(
            colours[0][1] > colours[0][0] && colours[0][1] > colours[0][2],
            "small deformation is green"
        );
        assert!(
            colours[1][0] > 0.9 && colours[1][1] > 0.8 && colours[1][2] < 0.1,
            "medium deformation is yellow"
        );
        assert!(
            colours[2][0] > colours[2][1] && colours[2][0] > colours[2][2],
            "large deformation is red"
        );
        assert!(colours[0][3] < colours[1][3] && colours[1][3] < colours[2][3]);
        assert_eq!(colours[3], [0.0; 4], "zero displacement stays untouched");
        assert!(
            deformation_colours(&snapshot, Some(&reference[..3])).is_err(),
            "mismatched references fail closed"
        );
    }

    #[test]
    fn solid_wire_is_exactly_depth_tested_and_xray_wire_explicitly_ignores_depth() {
        let (writes_depth, compare, bias) = pipeline_depth_state(PipelineDepth::Test);
        assert!(!writes_depth);
        assert_eq!(compare, wgpu::CompareFunction::LessEqual);
        assert_eq!(bias, wgpu::DepthBiasState::default());
        assert_eq!(pipeline_vertex_entry(PipelineDepth::Test), "vs_main");
        assert!(!SHADER.contains("out.position.z -= out.position.w"));

        let (xray_writes_depth, xray_compare, _) = pipeline_depth_state(PipelineDepth::Ignore);
        assert!(!xray_writes_depth);
        assert_eq!(xray_compare, wgpu::CompareFunction::Always);
    }

    #[test]
    fn solid_surface_is_two_sided_and_remains_depth_writing() {
        assert_eq!(solid_cull_mode(), None);
        let (writes_depth, compare, _) = pipeline_depth_state(PipelineDepth::Write);
        assert!(writes_depth);
        assert_eq!(compare, wgpu::CompareFunction::LessEqual);
    }

    #[test]
    fn material_texture_sampling_accepts_layer_masks_and_rejects_unknown_roles() {
        assert!(material_texture_role_is_sampled(TextureRole::LayerMask));
        assert!(!material_texture_role_is_sampled(TextureRole::Unknown));
    }

    #[test]
    fn every_view_mode_has_a_distinct_user_label() {
        let labels = [
            ViewMode::TexturedSolid,
            ViewMode::GameOutdoor,
            ViewMode::BaseColor,
            ViewMode::NormalMap,
            ViewMode::UvChecker,
            ViewMode::BaseAlpha,
            ViewMode::PartId,
            ViewMode::MaterialResponse,
            ViewMode::LayerMask,
            ViewMode::Solid,
            ViewMode::SolidWire,
            ViewMode::Wireframe,
            ViewMode::Vertices,
            ViewMode::WireVertices,
            ViewMode::XRay,
        ]
        .map(ViewMode::label)
        .into_iter()
        .collect::<HashSet<_>>();
        assert_eq!(labels.len(), 15);
    }

    #[test]
    fn legacy_dxt1_base_color_uses_the_srgb_gpu_format() {
        let plan = plan_2d_upload(&legacy_dxt1(), TextureRole::BaseColor)
            .expect("legacy DXT1 upload plan");
        assert_eq!(plan.metadata.color_space, ColorSpace::Srgb);
        assert_eq!(
            map_dds_format(&plan.metadata.format, plan.metadata.color_space)
                .expect("sRGB BC1 mapping"),
            wgpu::TextureFormat::Bc1RgbaUnormSrgb
        );
    }

    #[test]
    fn an_srgb_normal_map_is_sampled_as_linear() {
        assert_eq!(
            map_dds_format(&DdsFormat::Bc7Srgb, ColorSpace::Linear).expect("linear BC7 mapping"),
            wgpu::TextureFormat::Bc7RgbaUnorm
        );
    }

    #[test]
    fn formats_without_an_srgb_variant_are_rejected_for_srgb_sampling() {
        assert!(map_dds_format(&DdsFormat::Bc5Unorm, ColorSpace::Srgb).is_err());
    }

    #[test]
    fn material_batches_group_noncontiguous_triangles_without_losing_indices() {
        let snapshot = DrawSnapshot {
            mesh_identity: 1,
            draw_revision: 1,
            topology_generation: 1,
            positions: vec![[0.0, 0.0, 0.0]; 4],
            normals: vec![[0.0, 1.0, 0.0]; 4],
            uvs: vec![[0.0, 0.0]; 4],
            indices: vec![0, 1, 2, 1, 3, 2, 2, 3, 0],
            triangle_materials: vec![7, 3, 7],
            selected_vertices: Vec::new(),
            fingerprint: String::new(),
        };
        let (indices, ranges) = material_index_batches(&snapshot).expect("material batches");
        assert_eq!(indices, vec![1, 3, 2, 0, 1, 2, 2, 3, 0]);
        assert_eq!(
            ranges,
            vec![
                GpuMaterialRange {
                    material: 3,
                    part_id: 0,
                    first_index: 0,
                    index_count: 3,
                },
                GpuMaterialRange {
                    material: 7,
                    part_id: 1,
                    first_index: 3,
                    index_count: 6,
                },
            ]
        );
    }

    #[test]
    fn glossiness_is_a_scalar_roughness_fallback_with_an_independent_binding() {
        fn resolved_roughness(
            authoritative_roughness: Option<f32>,
            glossiness: Option<f32>,
            category_fallback: f32,
        ) -> f32 {
            authoritative_roughness.unwrap_or_else(|| {
                glossiness
                    .map(|gloss| (1.0 - gloss.clamp(0.0, 1.0)).clamp(0.04, 1.0))
                    .unwrap_or(category_fallback)
            })
        }

        let gloss_only = [(TextureRole::Glossiness, vec![vec![3_u32]])];
        assert_eq!(
            resolve_material_bindings(
                gloss_only
                    .iter()
                    .map(|(role, ownership)| (*role, ownership.as_slice())),
                0,
            )
            .expect("gloss-only binding"),
            BTreeMap::from([(
                3,
                MaterialTextureIndices {
                    glossiness: Some(0),
                    ..MaterialTextureIndices::default()
                },
            )]),
        );
        assert!((resolved_roughness(None, Some(0.8), 0.66) - 0.2).abs() < 1e-6);
        assert_eq!(resolved_roughness(Some(0.72), Some(0.8), 0.66), 0.72);

        assert_eq!(MATERIAL_GLOSSINESS, 4_194_304);
        assert!(SHADER.contains("@group(0) @binding(17) var glossiness_texture"));
        assert!(SHADER.contains("const MATERIAL_GLOSSINESS: u32 = 4194304u;"));
        assert!(SHADER.contains(
            "(material.flags & MATERIAL_GLOSSINESS) != 0u\n        && !has_authoritative_roughness"
        ));
        assert!(SHADER.contains("roughness = clamp(1.0 - authored_glossiness, 0.04, 1.0);"));
        assert!(SHADER.contains(
            "textureSampleBias(\n            glossiness_texture,\n            material_sampler,\n            input.uv,\n            MATERIAL_MIP_LOD_BIAS).r"
        ));

        let authority_declaration = SHADER
            .find("let has_authoritative_roughness =")
            .expect("authoritative roughness declaration");
        let gloss_fallback_declaration = SHADER
            .find("let has_source_glossiness =")
            .expect("gloss fallback declaration");
        let skin_roughness_application = SHADER
            .find("roughness = clamp(skin_specular_response.g, 0.04, 1.0);")
            .expect("packed skin roughness application");
        let gloss_application = SHADER
            .find("roughness = clamp(1.0 - authored_glossiness, 0.04, 1.0);")
            .expect("gloss inversion");
        let category_fallback = SHADER
            .find("if !has_source_roughness {")
            .expect("category roughness fallback");
        let rgb_specular_application = SHADER
            .find("let mapped_specular = textureSampleBias(specular_texture")
            .expect("RGB specular application");
        assert!(authority_declaration < gloss_fallback_declaration);
        assert!(gloss_fallback_declaration < skin_roughness_application);
        assert!(skin_roughness_application < gloss_application);
        assert!(gloss_application < category_fallback);
        assert!(category_fallback < rgb_specular_application);
    }

    #[test]
    fn material_binding_conflicts_fail_instead_of_retaining_a_previous_guess() {
        let distinct = [
            (TextureRole::BaseColor, vec![vec![0_u32]]),
            (TextureRole::Normal, vec![vec![0_u32]]),
            (TextureRole::Material, vec![vec![0_u32]]),
            (TextureRole::Roughness, vec![vec![0_u32]]),
            (TextureRole::Metalness, vec![vec![0_u32]]),
            (TextureRole::Occlusion, vec![vec![0_u32]]),
            (TextureRole::Emissive, vec![vec![0_u32]]),
            (TextureRole::Specular, vec![vec![0_u32]]),
            (TextureRole::Glossiness, vec![vec![0_u32]]),
            (TextureRole::Opacity, vec![vec![0_u32]]),
            (TextureRole::Height, vec![vec![0_u32]]),
            (TextureRole::Flow, vec![vec![0_u32]]),
            (TextureRole::LayerMask, vec![vec![0_u32]]),
            (TextureRole::SkinDetailMask, vec![vec![0_u32]]),
            (TextureRole::SkinDetailNormal, vec![vec![0_u32]]),
            (TextureRole::SkinDetailMaterial, vec![vec![0_u32]]),
            (TextureRole::BaseColor, vec![vec![1_u32]]),
        ];
        let bindings = resolve_material_bindings(
            distinct
                .iter()
                .map(|(role, ownership)| (*role, ownership.as_slice())),
            0,
        )
        .expect("distinct material-role bindings");
        assert_eq!(
            bindings,
            BTreeMap::from([
                (
                    0,
                    MaterialTextureIndices {
                        base_color: Some(0),
                        normal: Some(1),
                        surface: Some(2),
                        roughness: Some(3),
                        metalness: Some(4),
                        occlusion: Some(5),
                        emissive: Some(6),
                        specular: Some(7),
                        glossiness: Some(8),
                        opacity: Some(9),
                        height: Some(10),
                        flow: Some(11),
                        layer_mask: Some(12),
                        skin_detail_mask: Some(13),
                        skin_detail_normal: Some(14),
                        skin_detail_material: Some(15),
                    }
                ),
                (
                    1,
                    MaterialTextureIndices {
                        base_color: Some(16),
                        ..MaterialTextureIndices::default()
                    }
                ),
            ])
        );

        let conflicting = [
            (TextureRole::BaseColor, vec![vec![0_u32]]),
            (TextureRole::BaseColor, vec![vec![0_u32]]),
        ];
        assert!(
            resolve_material_bindings(
                conflicting
                    .iter()
                    .map(|(role, ownership)| (*role, ownership.as_slice())),
                0
            )
            .is_err()
        );
        let conflicting_specular = [
            (TextureRole::Specular, vec![vec![0_u32]]),
            (TextureRole::Specular, vec![vec![0_u32]]),
        ];
        assert!(
            resolve_material_bindings(
                conflicting_specular
                    .iter()
                    .map(|(role, ownership)| (*role, ownership.as_slice())),
                0
            )
            .is_err()
        );
        let simultaneous_specular_and_glossiness = [
            (TextureRole::Specular, vec![vec![0_u32]]),
            (TextureRole::Glossiness, vec![vec![0_u32]]),
        ];
        assert_eq!(
            resolve_material_bindings(
                simultaneous_specular_and_glossiness
                    .iter()
                    .map(|(role, ownership)| (*role, ownership.as_slice())),
                0,
            )
            .expect("specular and glossiness use independent slots"),
            BTreeMap::from([(
                0,
                MaterialTextureIndices {
                    specular: Some(0),
                    glossiness: Some(1),
                    ..MaterialTextureIndices::default()
                },
            )])
        );
        let conflicting_opacity = [
            (TextureRole::Opacity, vec![vec![0_u32]]),
            (TextureRole::Opacity, vec![vec![0_u32]]),
        ];
        assert!(
            resolve_material_bindings(
                conflicting_opacity
                    .iter()
                    .map(|(role, ownership)| (*role, ownership.as_slice())),
                0
            )
            .is_err()
        );
        let conflicting_layer_mask = [
            (TextureRole::LayerMask, vec![vec![0_u32]]),
            (TextureRole::LayerMask, vec![vec![0_u32]]),
        ];
        assert!(
            resolve_material_bindings(
                conflicting_layer_mask
                    .iter()
                    .map(|(role, ownership)| (*role, ownership.as_slice())),
                0
            )
            .is_err()
        );
    }

    #[test]
    fn material_factors_merge_distinct_fields_and_reject_conflicts() {
        let ownership = vec![vec![2_u32]];
        let distinct = [
            (
                MaterialPreviewFactors {
                    emissive_color: Some([0.1, 0.2, 0.3]),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    emissive_intensity: Some(4.0),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    roughness: Some(0.7),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    metalness: Some(0.8),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    specular: Some(0.9),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    height_scale: Some(0.09),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    texture_tint: Some([0.73, 0.44, 0.24]),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    base_tint_strength: Some(0.85),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    alpha_cutoff: Some(0.08),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    hair_anisotropy: Some(true),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    layer_mask_channel: Some(2),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
        ];
        let resolved = resolve_material_factors(
            distinct
                .iter()
                .map(|(factors, ownership)| (*factors, ownership.as_slice())),
            0,
        )
        .expect("distinct material factors");
        assert_eq!(
            resolved.get(&2),
            Some(&MaterialPreviewFactors {
                emissive_color: Some([0.1, 0.2, 0.3]),
                emissive_intensity: Some(4.0),
                roughness: Some(0.7),
                metalness: Some(0.8),
                specular: Some(0.9),
                height_scale: Some(0.09),
                texture_tint: Some([0.73, 0.44, 0.24]),
                base_tint_strength: Some(0.85),
                alpha_cutoff: Some(0.08),
                hair_anisotropy: Some(true),
                layer_mask_channel: Some(2),
                ..MaterialPreviewFactors::default()
            })
        );

        let conflicting = [
            (
                MaterialPreviewFactors {
                    emissive_intensity: Some(1.0),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    emissive_intensity: Some(2.0),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
        ];
        assert!(
            resolve_material_factors(
                conflicting
                    .iter()
                    .map(|(factors, ownership)| (*factors, ownership.as_slice())),
                0,
            )
            .is_err()
        );
        let surface_conflicts = [
            (
                MaterialPreviewFactors {
                    roughness: Some(0.1),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    roughness: Some(0.2),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    metalness: Some(0.1),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    metalness: Some(0.2),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    specular: Some(0.1),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    specular: Some(0.2),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    height_scale: Some(0.1),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    height_scale: Some(0.2),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    texture_tint: Some([0.1, 0.2, 0.3]),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    texture_tint: Some([0.3, 0.2, 0.1]),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    base_tint_strength: Some(0.4),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    base_tint_strength: Some(0.8),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    alpha_cutoff: Some(0.1),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    alpha_cutoff: Some(0.2),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    hair_anisotropy: Some(true),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    hair_anisotropy: Some(false),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    layer_mask_channel: Some(0),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    layer_mask_channel: Some(2),
                    ..MaterialPreviewFactors::default()
                },
            ),
        ];
        for (left, right) in surface_conflicts {
            let claims = [(left, ownership.clone()), (right, ownership.clone())];
            assert!(
                resolve_material_factors(
                    claims
                        .iter()
                        .map(|(factors, ownership)| (*factors, ownership.as_slice())),
                    0,
                )
                .is_err()
            );
        }
    }

    #[test]
    fn tangent_basis_is_derived_from_positions_and_texture_coordinates() {
        let snapshot = DrawSnapshot {
            mesh_identity: 1,
            draw_revision: 1,
            topology_generation: 1,
            positions: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            normals: vec![[0.0, 0.0, 1.0]; 3],
            uvs: vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
            indices: vec![0, 1, 2],
            triangle_materials: vec![0],
            selected_vertices: Vec::new(),
            fingerprint: String::new(),
        };
        let tangents = vertex_tangents(&snapshot).expect("tangent basis");
        assert_eq!(tangents, vec![[1.0, 0.0, 0.0, 1.0]; 3]);
    }

    #[test]
    fn interactive_tangent_refresh_reprojects_cached_basis_without_triangle_rebuild() {
        let tangents = reproject_vertex_tangents(
            &[[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            &[[1.0, 0.2, 0.0, 1.0], [1.0, 0.0, 0.4, -1.0]],
        )
        .expect("interactive tangent projection");
        assert_eq!(tangents, vec![[1.0, 0.0, 0.0, 1.0], [1.0, 0.0, 0.0, -1.0]]);
        assert!(reproject_vertex_tangents(&[[0.0, 1.0, 0.0]], &[]).is_err());
    }

    #[test]
    fn normal_and_bounds_overlays_build_persistent_line_vertices() {
        let snapshot = DrawSnapshot {
            mesh_identity: 1,
            draw_revision: 1,
            topology_generation: 1,
            positions: vec![[0.0, 0.0, 0.0], [2.0, 4.0, 6.0]],
            normals: vec![[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]],
            uvs: vec![[0.0, 0.0]; 2],
            indices: Vec::new(),
            triangle_materials: Vec::new(),
            selected_vertices: Vec::new(),
            fingerprint: String::new(),
        };
        let normals = normal_line_vertices(&snapshot);
        assert_eq!(normals.len(), 4);
        assert_eq!(normals[0].position, snapshot.positions[0]);
        assert!(normals[1].position[1] > normals[0].position[1]);
        assert!(normals[3].position[0] > normals[2].position[0]);

        let bounds = bounds_line_vertices(&snapshot.positions);
        assert_eq!(bounds.len(), 24);
        assert!(
            bounds
                .iter()
                .any(|vertex| vertex.position == [0.0, 0.0, 0.0])
        );
        assert!(
            bounds
                .iter()
                .any(|vertex| vertex.position == [2.0, 4.0, 6.0])
        );

        let dense_positions = (0..10_000)
            .map(|index| [index as f32 * 0.001, 0.0, 0.0])
            .collect::<Vec<_>>();
        let dense = DrawSnapshot {
            mesh_identity: 2,
            draw_revision: 1,
            topology_generation: 1,
            positions: dense_positions.clone(),
            normals: vec![[0.0, 1.0, 0.0]; dense_positions.len()],
            uvs: vec![[0.0, 0.0]; dense_positions.len()],
            indices: Vec::new(),
            triangle_materials: Vec::new(),
            selected_vertices: Vec::new(),
            fingerprint: String::new(),
        };
        let sampled = normal_line_vertices(&dense);
        assert!(sampled.len() <= NORMAL_OVERLAY_MAX_LINES * 2);
        assert_eq!(sampled.len() % 2, 0);
        assert!(sampled.len() < dense.positions.len() * 2);
    }

    #[test]
    fn headless_capture_stats_ignore_the_modal_clear_colour() {
        let pixels = [
            [7, 6, 5, 255],
            [7, 6, 5, 255],
            [7, 6, 5, 255],
            [30, 60, 90, 255],
            [240, 240, 240, 255],
        ]
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();

        let stats = headless_frame_stats(&pixels).expect("capture stats");

        assert_eq!(stats.non_background_pixels, 2);
        assert!(stats.p50_luma_255 > 100.0);
        assert_eq!(stats.near_white_percent, 50.0);
        assert_eq!(stats.light_pixel_percent, 50.0);
        assert!(stats.mean_chroma_255 > 20.0);
    }

    #[test]
    fn headless_readback_rows_are_padded_to_the_wgpu_copy_alignment() {
        assert_eq!(padded_headless_bytes_per_row(1), 256);
        assert_eq!(padded_headless_bytes_per_row(63), 256);
        assert_eq!(padded_headless_bytes_per_row(64), 256);
        assert_eq!(padded_headless_bytes_per_row(65), 512);
        assert_eq!(padded_headless_bytes_per_row(1_024), 4_096);
    }

    #[test]
    fn headless_capture_correlates_part_colours_with_material_owners() {
        let background = [7, 6, 5, 255];
        let part_zero = part_id_bgra(0);
        let part_one = part_id_bgra(1);
        let part_id_pixels = [background, part_zero, part_zero, part_one]
            .into_iter()
            .flatten()
            .collect::<Vec<_>>();
        let textured_pixels = [
            background,
            [10, 20, 30, 255],
            [20, 30, 40, 255],
            [100, 120, 140, 255],
        ]
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();
        let base_color_pixels = [
            background,
            [30, 40, 50, 255],
            [40, 50, 60, 255],
            [150, 160, 170, 255],
        ]
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();
        let ranges = [
            GpuMaterialRange {
                material: 4,
                part_id: 0,
                first_index: 0,
                index_count: 3,
            },
            GpuMaterialRange {
                material: 9,
                part_id: 1,
                first_index: 3,
                index_count: 3,
            },
        ];

        let coverage = headless_material_owner_coverage(
            &ranges,
            &textured_pixels,
            &base_color_pixels,
            &part_id_pixels,
        )
        .expect("owner coverage");

        assert_eq!(coverage.len(), 2);
        assert_eq!(coverage[0].material_index, 4);
        assert_eq!(coverage[0].pixel_count, 2);
        assert_eq!(coverage[0].frame_percent, 50.0);
        assert_eq!(coverage[1].material_index, 9);
        assert_eq!(coverage[1].pixel_count, 1);
        assert_eq!(coverage[1].frame_percent, 25.0);
        assert!(coverage[1].base_color_mean_luma_255 > coverage[1].textured_mean_luma_255);
    }
}
