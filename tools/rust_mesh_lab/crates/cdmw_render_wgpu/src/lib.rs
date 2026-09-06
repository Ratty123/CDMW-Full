#![forbid(unsafe_code)]

mod effect_depth;
mod effect_particle_proof;
mod effect_particle_shader;
mod selection_overlay;
pub use selection_overlay::verify_face_selection_depth;

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
    lighting_preset: u32,
    _padding_2: u32,
    wire_colour: vec4<f32>,
    point_colour: vec4<f32>,
    view_direction: vec4<f32>,
    camera_right: vec4<f32>,
    camera_up: vec4<f32>,
    scene_model: mat4x4<f32>,
    scene_normal: mat4x4<f32>,
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
    opacity: f32,
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
const MATERIAL_FLIP_V: u32 = 16777216u;
const MATERIAL_ALPHA_BLEND: u32 = 33554432u;
const MATERIAL_GLTF_PBR: u32 = 67108864u;
const MATERIAL_MIP_LOD_BIAS: f32 = -2.0;

fn make_vertex_out(
    position: vec3<f32>,
    normal: vec3<f32>,
    uv: vec2<f32>,
    tangent: vec4<f32>,
    deformation: vec4<f32>,
    editable_role: u32,
    instance_index: u32,
) -> VertexOut {
    var out: VertexOut;
    var world_position = position;
    var world_normal = normal;
    var world_tangent = tangent;
    if editable_role != 0u {
        world_position = (camera.scene_model * vec4<f32>(position, 1.0)).xyz;
        world_normal = safe_normalize(
            (camera.scene_normal * vec4<f32>(normal, 0.0)).xyz,
            vec3<f32>(0.0, 1.0, 0.0));
        world_tangent = vec4<f32>(safe_normalize(
            (camera.scene_model * vec4<f32>(tangent.xyz, 0.0)).xyz,
            vec3<f32>(1.0, 0.0, 0.0)), tangent.w);
    }
    out.position = camera.view_projection * vec4<f32>(world_position, 1.0);
    out.color = world_normal * 0.35 + vec3<f32>(0.55, 0.58, 0.65);
    out.uv = uv;
    out.normal = world_normal;
    out.tangent = world_tangent;
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
    @location(5) editable_role: u32,
    @builtin(instance_index) instance_index: u32,
) -> VertexOut {
    return make_vertex_out(position, normal, uv, tangent, deformation, editable_role, instance_index);
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
    if camera.lighting_preset == 0u {
        // Neutral Studio preserves chroma and applies one bounded luminance
        // compression in linear space. The sRGB target performs the sole
        // output conversion in `present`.
        let mapped_luma = exposed_luma / (1.0 + exposed_luma);
        return clamp(
            exposed * (mapped_luma / max(exposed_luma, 1e-5)),
            vec3<f32>(0.0),
            vec3<f32>(1.0));
    }
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

fn preview_environment_radiance(reflected_view: vec3<f32>, roughness: f32, gltf_pbr: bool) -> vec3<f32> {
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

    // Archive material approximations retain their bounded warm/cool studio.
    // Imported PBR uses neutral HDR light and a single final tone map instead.
    var radiance = vec3<f32>(0.070, 0.065, 0.060);
    radiance += horizon_band * vec3<f32>(0.55, 0.46, 0.38);
    radiance += front_softbox * vec3<f32>(7.50, 6.20, 4.60);
    radiance += back_softbox * vec3<f32>(3.20, 2.35, 1.55);
    radiance += top_softbox * vec3<f32>(4.60, 4.30, 3.80);
    radiance += side_softbox * vec3<f32>(3.00, 2.65, 2.20);
    radiance += opposite_side_softbox * vec3<f32>(0.55, 0.65, 0.82);
    if gltf_pbr && camera.lighting_preset == 0u {
        // Neutral lights preserve the authored hue of imported conductors.
        radiance = vec3<f32>(0.035 + horizon_band * 0.18
            + front_softbox * 7.50 + back_softbox * 3.20
            + top_softbox * 4.60 + side_softbox * 3.00)
            + opposite_side_softbox * vec3<f32>(0.55, 0.65, 0.82);
    }
    radiance *= mix(1.0, 0.16, dark_band * mix(0.96, 0.38, safe_roughness));
    radiance = mix(radiance, vec3<f32>(0.32, 0.28, 0.24), roughness_squared * 0.34);
    let radiance_peak = max(radiance.r, max(radiance.g, radiance.b));
    // Imported PBR reflections remain HDR until the final surface tone map.
    // Keep the existing bounded response for archive material approximations.
    if !gltf_pbr { radiance = radiance / (1.0 + radiance_peak); }
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
    var sample_uv = input.uv;
    if (material.flags & MATERIAL_FLIP_V) != 0u {
        sample_uv.y = 1.0 - sample_uv.y;
    }
    if camera.view_mode == 4u {
        let checker = (u32(floor(sample_uv.x * 16.0)) + u32(floor(sample_uv.y * 16.0))) & 1u;
        let value = select(0.08, 0.88, checker != 0u);
        return present_srgb(vec3<f32>(value), 1.0);
    }
    let has_emission = material.emissive_color_and_intensity.a > 0.0
        && any(material.emissive_color_and_intensity.rgb > vec3<f32>(0.0));
    if material.flags == 0u && !has_emission {
        if camera.view_mode == 8u {
            let part_id = f32(input.part_id) + 1.0;
            return present_srgb(fract(part_id * vec3<f32>(0.6180339, 0.3819660, 0.7548777)), 1.0);
        }
        return present(neutral_surface(input.normal, front_facing), 1.0);
    }

    var texel = textureSampleBias(base_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS);
    if (material.flags & MATERIAL_TEXTURE_TINT) != 0u {
        let texture_tint = max(
            material.texture_tint_and_strength.rgb,
            vec3<f32>(0.0));
        let tint_strength = clamp(material.texture_tint_and_strength.w, 0.0, 1.0);
        if tint_strength <= 0.001 {
            // A zero base-tint strength is the imported glTF baseColorFactor
            // contract: multiply the sampled texture exactly.
            texel = vec4<f32>(
                clamp(select(vec3<f32>(1.0), texel.rgb, (material.flags & MATERIAL_BASE_COLOR) != 0u) * texture_tint, vec3<f32>(0.0), vec3<f32>(1.0)),
                texel.a);
        } else if min(u32(material.relief_factors.z + 0.5), 14u) == 6u {
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
        material_alpha = textureSampleBias(opacity_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS).r;
    }
    material_alpha = clamp(material_alpha * material.opacity, 0.0, 1.0);
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
        return present(texel.rgb, select(1.0, material_alpha, (material.flags & MATERIAL_ALPHA_BLEND) != 0u));
    }
    if camera.view_mode == 5u {
        return present_srgb(vec3<f32>(material_alpha), 1.0);
    }
    if camera.view_mode == 7u {
        var layer_mask = texel.a;
        if (material.flags & MATERIAL_LAYER_MASK) != 0u {
            let mask = textureSampleBias(layer_mask_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS);
            layer_mask = mask[min(u32(material.relief_factors.y), 3u)];
        }
        return present_srgb(vec3<f32>(layer_mask), 1.0);
    }
    let geometry_normal = facing_normal(input.normal, front_facing);
    let tangent = normalize(input.tangent.xyz - geometry_normal * dot(geometry_normal, input.tangent.xyz));
    let bitangent = normalize(cross(geometry_normal, tangent)) * input.tangent.w;
    var tangent_normal = vec3<f32>(0.0, 0.0, 1.0);
    if (material.flags & MATERIAL_NORMAL) != 0u {
        var tangent_xy = textureSampleBias(normal_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS).xy * 2.0 - vec2<f32>(1.0);
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
                sample_uv,
                MATERIAL_MIP_LOD_BIAS).r * material.skin_detail_opacity,
            0.0,
            1.0);
    }
    let skin_detail_uv = sample_uv / max(material.skin_detail_scale, 0.001);
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
        height_value = textureSampleBias(height_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS).r;
        var height_uv_x = dpdx(sample_uv);
        var height_uv_y = dpdy(sample_uv);
        if dot(height_uv_x, height_uv_x) < 1e-8 {
            height_uv_x = vec2<f32>(1.0 / 1024.0, 0.0);
        }
        if dot(height_uv_y, height_uv_y) < 1e-8 {
            height_uv_y = vec2<f32>(0.0, 1.0 / 1024.0);
        }
        let height_x = textureSampleBias(height_texture, material_sampler, sample_uv + height_uv_x, MATERIAL_MIP_LOD_BIAS).r
            - textureSampleBias(height_texture, material_sampler, sample_uv - height_uv_x, MATERIAL_MIP_LOD_BIAS).r;
        let height_y = textureSampleBias(height_texture, material_sampler, sample_uv + height_uv_y, MATERIAL_MIP_LOD_BIAS).r
            - textureSampleBias(height_texture, material_sampler, sample_uv - height_uv_y, MATERIAL_MIP_LOD_BIAS).r;
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

    let gltf_pbr = (material.flags & MATERIAL_GLTF_PBR) != 0u;
    let category_code = select(min(u32(material.relief_factors.z + 0.5), 14u), 0u, gltf_pbr);
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
    let is_bone = category_code == 12u;
    let is_organic = category_code == 13u;
    let is_foliage = category_code == 14u;
    let is_glossy = is_glass || is_gem || is_eye;
    let conservative_nonmetal = is_leather || is_wood || is_cloth || is_skin
        || is_hair || is_stone || is_tooth || is_bone || is_organic || is_foliage;
    let has_skin_specular_response =
        is_skin && !gltf_pbr && (material.flags & MATERIAL_SPECULAR) != 0u;
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
        let packed = textureSampleBias(material_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS);
        roughness = clamp(packed.g, 0.04, 1.0);
        metalness = clamp(packed.b, 0.0, 1.0);
    }
    if (material.flags & MATERIAL_ROUGHNESS) != 0u {
        roughness = clamp(textureSampleBias(roughness_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS).r, 0.04, 1.0);
    }
    if (material.flags & MATERIAL_METALNESS) != 0u {
        metalness = clamp(textureSampleBias(metalness_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS).r, 0.0, 1.0);
    }
    if has_skin_specular_response {
        let skin_specular_response = textureSampleBias(
            specular_texture,
            material_sampler,
            sample_uv,
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
            sample_uv,
            MATERIAL_MIP_LOD_BIAS).r, 0.0, 1.0);
        roughness = clamp(1.0 - authored_glossiness, 0.04, 1.0);
    }
    if !has_source_roughness && !gltf_pbr {
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
    if !has_source_metalness && is_metal && !gltf_pbr {
        metalness = mix(0.28, 0.62, category_confidence);
    }
    if gltf_pbr {
        roughness = select(1.0, roughness, has_source_roughness);
        metalness = select(1.0, metalness, has_source_metalness);
    }
    if (material.flags & MATERIAL_ROUGHNESS_FACTOR) != 0u && gltf_pbr {
        roughness = clamp(roughness * material.surface_factors.x, 0.04, 1.0);
    } else if (material.flags & MATERIAL_ROUGHNESS_FACTOR) != 0u {
        let factor_weight = select(0.55, 0.15, has_source_roughness);
        roughness = clamp(mix(roughness, material.surface_factors.x, factor_weight), 0.04, 1.0);
    }
    if (material.flags & MATERIAL_METALNESS_FACTOR) != 0u {
        let declared_metalness = clamp(material.surface_factors.y, 0.0, 1.0);
        if gltf_pbr {
            metalness *= declared_metalness;
        } else {
            metalness = select(declared_metalness, max(metalness, declared_metalness), has_source_metalness);
        }
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
    if is_skin && !gltf_pbr {
        metalness = 0.0;
    }
    if (material.flags & MATERIAL_HEIGHT) != 0u {
        let height_relief = (height_value - 0.5) * clamp(material.relief_factors.x, 0.0, 1.0);
        roughness = clamp(roughness - height_relief * 0.10, 0.04, 1.0);
    }
    var raw_occlusion = 1.0;
    if (material.flags & MATERIAL_OCCLUSION) != 0u {
        raw_occlusion = clamp(textureSampleBias(occlusion_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS).r, 0.0, 1.0);
    }
    var occlusion_category_weight = 0.78;
    if is_metal { occlusion_category_weight = 1.0; }
    if is_glossy { occlusion_category_weight = 0.82; }
    if is_skin { occlusion_category_weight = 0.58; }
    if is_hair { occlusion_category_weight = 0.62; }
    if is_cloth || is_leather || is_wood || is_stone { occlusion_category_weight = 0.68; }
    let occlusion = mix(1.0, raw_occlusion, 0.45 * occlusion_category_weight);

    let game_outdoor = camera.view_mode == 9u;
    let showcase = camera.lighting_preset == 1u && !game_outdoor;
    let view_direction = safe_normalize(camera.view_direction.xyz, vec3<f32>(0.0, 0.0, -1.0));
    let camera_right = safe_normalize(camera.camera_right.xyz, vec3<f32>(1.0, 0.0, 0.0));
    let camera_up = safe_normalize(camera.camera_up.xyz, vec3<f32>(0.0, 1.0, 0.0));
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
    if !showcase && !game_outdoor {
        ambient_floor *= 0.62;
        depth_authority = min(1.0, depth_authority + 0.12);
    }
    let shaped_light = ambient_floor * 0.84
        + 0.62 * (key_light * 0.72 + fill_light * 0.18 + rim_light * 0.10);
    let diffuse_depth = mix(1.0, shaped_light, depth_authority);
    // The Vortice path retains a small source-coloured body term beneath its
    // HDR studio reflections. Rust uses a bounded procedural environment, so a
    // 0.20 floor preserves the same albedo readability without adding neutral
    // light or changing the authored metal hue.
    let metal_body_scale = select(0.34, 0.20, has_source_metalness);
    var body_scale = mix(1.0, metal_body_scale, metalness);
    if gltf_pbr { body_scale = 1.0 - metalness; }
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
    if !showcase && !game_outdoor {
        // The sampled base is already decoded by an sRGB texture view. Do not
        // add category tint, a dark-colour lift, or a second gamma-like boost.
        material_reference_albedo = clamp(texel.rgb, vec3<f32>(0.0), vec3<f32>(1.0));
    }
    let nonmetal_texture_scale = select(
        1.0,
        1.03,
        conservative_nonmetal && !authored_cloth_or_leather);
    let resolved_nonmetal_texture_scale = select(1.0, nonmetal_texture_scale, showcase || game_outdoor);
    var diffuse = material_reference_albedo
        * occlusion
        * diffuse_depth
        * body_scale
        * resolved_nonmetal_texture_scale;

    var dielectric_f0 = 0.04;
    if is_glass { dielectric_f0 = 0.08; }
    if is_gem { dielectric_f0 = 0.10; }
    if is_eye { dielectric_f0 = 0.065; }
    if is_leather { dielectric_f0 = 0.045; }
    if is_tooth { dielectric_f0 = 0.05; }
    dielectric_f0 = mix(0.04, dielectric_f0, category_confidence);
    dielectric_f0 = select(dielectric_f0, 0.04, gltf_pbr);
    var f0 = mix(
        vec3<f32>(dielectric_f0),
        material_reference_albedo,
        vec3<f32>(metalness),
    );
    if gltf_pbr && (material.flags & MATERIAL_SPECULAR_FACTOR) != 0u {
        f0 = mix(vec3<f32>(0.04 * material.surface_factors.z), material_reference_albedo, vec3<f32>(metalness));
    }
    let source_stable_f0 = f0;
    if (material.flags & MATERIAL_SPECULAR) != 0u && !is_skin {
        let mapped_specular = textureSampleBias(specular_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS).rgb;
        let source_weight = max(metalness, select(0.0, 0.75, is_glossy));
        f0 = mix(f0, max(f0, mapped_specular), vec3<f32>(source_weight));
    }
    if !gltf_pbr && (material.flags & MATERIAL_SPECULAR_FACTOR) != 0u
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
    if is_metal || gltf_pbr {
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
        specular = metal_cook_torrance * metal_ndotl
            * select(metal_direct_specular_scale, 1.0, gltf_pbr);
        if !gltf_pbr { specular = min(specular, vec3<f32>(0.85)); }
    } else {
        let specular_power = mix(96.0, 8.0, roughness);
        let key_specular = pow(max(dot(surface_normal, key_half_vector), 0.0), specular_power);
        let fill_specular = pow(max(dot(surface_normal, fill_half_vector), 0.0), max(specular_power * 0.55, 4.0));
        specular = f0
            * (key_specular + fill_specular * 0.16)
            * (0.20 + 0.80 * (1.0 - roughness))
            * 0.62;
        if (material.flags & MATERIAL_HAIR_FLOW) != 0u {
            let flow = textureSampleBias(flow_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS).xy * 2.0
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
    if !showcase && !game_outdoor { environment_scale *= 0.68; }
    if gltf_pbr { environment_scale = 1.0; }
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
    let environment_radiance = preview_environment_radiance(environment_reflection, roughness, gltf_pbr);
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
    var environment_diffuse_scale = select(0.24, 0.18, conservative_nonmetal);
    if !showcase && !game_outdoor { environment_diffuse_scale *= 0.62; }
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
    let cue_weight = select(0.0, 1.0, showcase || game_outdoor);
    diffuse += material_reference_albedo * metal_cue * 0.16 * cue_weight;
    diffuse += material_reference_albedo * glossy_cue * 0.22 * cue_weight;
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
    var emissive = material.emissive_color_and_intensity.rgb
        * material.emissive_color_and_intensity.a * select(2.2, 1.0, gltf_pbr);
    if (material.flags & MATERIAL_EMISSIVE) != 0u {
        let emissive_sample = textureSampleBias(
            emissive_texture, material_sampler, sample_uv, MATERIAL_MIP_LOD_BIAS);
        let emissive_rgb = select(
            emissive_sample.rgb,
            emissive_sample.rrr,
            (material.flags & MATERIAL_EMISSIVE_INTENSITY_MASK) != 0u);
        emissive *= emissive_rgb;
    }
    let showcase_warmth = select(vec3<f32>(1.0), vec3<f32>(1.08, 0.99, 0.90), showcase);
    let exposure = select(select(0.90, 1.0, showcase), 1.06, game_outdoor);
    let shaded = workbench_tone(
        diffuse
            + environment_diffuse
            + metallic_source_anchor
            + specular * showcase_warmth
            + environment_specular * showcase_warmth
            + leather_sheen
            + cloth_sheen
            + skin_scatter
            + glass_edge
            + emissive,
        exposure);
    return present(shaded, select(1.0, material_alpha, (material.flags & MATERIAL_ALPHA_BLEND) != 0u));
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

@fragment
fn fs_effect(input: VertexOut) -> @location(0) vec4<f32> {
    let authored_color = clamp(input.normal, vec3<f32>(0.0), vec3<f32>(1.0));
    let alpha = clamp(input.deformation.x, 0.0, 1.0);
    return present_srgb(authored_color, alpha);
}

@fragment
fn fs_selection(input: VertexOut) -> @location(0) vec4<f32> {
    return present_srgb(input.deformation.rgb, input.deformation.a);
}


"#;

const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LightingPreset {
    NeutralStudio,
    Showcase,
}

impl LightingPreset {
    const fn shader_value(self) -> u32 {
        match self {
            Self::NeutralStudio => 0,
            Self::Showcase => 1,
        }
    }
}

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
    lighting_preset: u32,
    _padding: u32,
    wire_colour: [f32; 4],
    point_colour: [f32; 4],
    view_direction: [f32; 4],
    camera_right: [f32; 4],
    camera_up: [f32; 4],
    scene_model: [[f32; 4]; 4],
    scene_normal: [[f32; 4]; 4],
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct MaterialUniform {
    flags: u32,
    skin_detail_scale: f32,
    skin_detail_opacity: f32,
    opacity: f32,
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
const MATERIAL_FLIP_V: u32 = 16777216;
const MATERIAL_ALPHA_BLEND: u32 = 33554432;
const MATERIAL_GLTF_PBR: u32 = 67108864;
const NEUTRAL_MISSING_BASE_COLOR_SRGB: [u8; 4] = [144, 144, 144, 255];

impl CameraUniform {
    fn new(output_is_srgb: bool) -> Self {
        Self {
            view_projection: Mat4::IDENTITY.to_cols_array_2d(),
            view_mode: 0,
            output_is_srgb: u32::from(output_is_srgb),
            lighting_preset: 0,
            _padding: 0,
            wire_colour: srgb_rgba_to_linear([0.72, 0.78, 0.88, 1.0]),
            point_colour: srgb_rgba_to_linear([0.92, 0.94, 1.0, 1.0]),
            view_direction: [0.0, 0.0, -1.0, 0.0],
            camera_right: [1.0, 0.0, 0.0, 0.0],
            camera_up: [0.0, 1.0, 0.0, 0.0],
            scene_model: Mat4::IDENTITY.to_cols_array_2d(),
            scene_normal: Mat4::IDENTITY.to_cols_array_2d(),
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
    editable_role: u32,
}

impl GpuVertex {
    const ATTRIBUTES: [wgpu::VertexAttribute; 6] = wgpu::vertex_attr_array![
        0 => Float32x3,
        1 => Float32x3,
        2 => Float32x2,
        3 => Float32x4,
        4 => Float32x4,
        5 => Uint32
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
            editable_role: 0,
        }
    }

    fn effect_overlay(vertex: EffectLineVertex) -> Self {
        Self {
            position: vertex.position,
            normal: [
                vertex.colour[0].clamp(0.0, 1.0),
                vertex.colour[1].clamp(0.0, 1.0),
                vertex.colour[2].clamp(0.0, 1.0),
            ],
            uv: [0.0, 0.0],
            tangent: [1.0, 0.0, 0.0, 1.0],
            deformation: [vertex.colour[3].clamp(0.0, 1.0), 0.0, 0.0, 0.0],
            editable_role: 0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct EffectLineVertex {
    pub position: [f32; 3],
    pub colour: [f32; 4],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum EffectBlendMode {
    Additive,
    Alpha,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct EffectBillboardInstance {
    pub center: [f32; 3],
    pub axis_right: [f32; 3],
    pub axis_up: [f32; 3],
    pub colour: [f32; 4],
    pub uv_rect: [f32; 4],
    /// -1 for colour, 0..3 for the selected packed coverage channel.
    pub texture_channel: i32,
    pub frame_blend: f32,
    /// Mesh triangles share the instanced stream. The second quad triangle is
    /// collapsed; center/right/up encode vertex 0 and its two edge vectors.
    pub triangle_uvs: Option<[[f32; 2]; 3]>,
    /// Zero selects the procedural soft sprite; uploaded package sprites begin at one.
    pub texture_index: usize,
    pub blend: EffectBlendMode,
    /// Camera-space sorting key. Larger values are drawn first for alpha blending.
    pub depth: f32,
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct EffectQuadVertex {
    corner: [f32; 2],
    uv: [f32; 2],
}

impl EffectQuadVertex {
    const ATTRIBUTES: [wgpu::VertexAttribute; 2] =
        wgpu::vertex_attr_array![0 => Float32x2, 1 => Float32x2];

    fn layout() -> wgpu::VertexBufferLayout<'static> {
        wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<Self>() as wgpu::BufferAddress,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &Self::ATTRIBUTES,
        }
    }
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct GpuEffectBillboardInstance {
    center: [f32; 3],
    axis_right: [f32; 3],
    axis_up: [f32; 3],
    colour: [f32; 4],
    uv_rect: [f32; 4],
    sprite_options: [f32; 4],
    third_uv: [f32; 2],
}

impl GpuEffectBillboardInstance {
    const ATTRIBUTES: [wgpu::VertexAttribute; 7] = wgpu::vertex_attr_array![
        2 => Float32x3,
        3 => Float32x3,
        4 => Float32x3,
        5 => Float32x4,
        6 => Float32x4,
        7 => Float32x4,
        8 => Float32x2
    ];

    fn layout() -> wgpu::VertexBufferLayout<'static> {
        wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<Self>() as wgpu::BufferAddress,
            step_mode: wgpu::VertexStepMode::Instance,
            attributes: &Self::ATTRIBUTES,
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
    pub scene_transform_updates: u64,
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
    pub alpha_blend: Option<bool>,
    pub opacity: Option<f32>,
    pub gltf_metallic_roughness: Option<bool>,
    pub hair_anisotropy: Option<bool>,
    pub layer_mask_channel: Option<u32>,
    pub category_code: Option<u32>,
    pub category_confidence: Option<f32>,
    pub normal_y_inverted: Option<bool>,
    pub texture_flip_vertical: Option<bool>,
    pub skin_detail_scale: Option<f32>,
    pub skin_detail_opacity: Option<f32>,
}

pub type OwnedMaterialFactors = (MaterialPreviewFactors, Vec<Vec<u32>>);

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
    pub effect_overlay_pixels_changed: usize,
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

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct HeadlessMaterialCaptureCamera {
    pub yaw_degrees: f32,
    pub pitch_degrees: f32,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct HeadlessMaterialCaptureOptions {
    pub width: u32,
    pub height: u32,
    pub lod_index: usize,
    pub camera: Option<HeadlessMaterialCaptureCamera>,
    pub isolated_material_index: Option<u32>,
}

impl Default for HeadlessMaterialCaptureOptions {
    fn default() -> Self {
        Self {
            width: 1_024,
            height: 1_024,
            lod_index: 0,
            camera: None,
            isolated_material_index: None,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct HeadlessMaterialCaptureOutput<'a> {
    pub textured_bmp: &'a Path,
    pub base_color_bmp: &'a Path,
    pub part_id_bmp: &'a Path,
    pub normal_map: Option<&'a Path>,
    pub material_response: Option<&'a Path>,
    pub layer_mask: Option<&'a Path>,
}

#[derive(Debug, Clone, Copy)]
pub struct HeadlessMaterialCaptureRequest<'a> {
    pub options: HeadlessMaterialCaptureOptions,
    pub output: HeadlessMaterialCaptureOutput<'a>,
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
    pub camera_yaw_degrees: f32,
    pub camera_pitch_degrees: f32,
    pub isolated_material_index: Option<u32>,
    pub dds_textures_uploaded: u32,
    pub texture_bound_materials: u32,
    pub active_material_bindings: u32,
    pub material_ranges_rendered: u32,
    pub renderer_device_ready_ms: f64,
    pub texture_resources_ready_ms: f64,
    pub first_textured_frame_ms: f64,
    pub wall_ms: f64,
    pub textured: HeadlessFrameStats,
    pub base_color: HeadlessFrameStats,
    pub part_id: HeadlessFrameStats,
    pub normal_map: Option<HeadlessFrameStats>,
    pub material_response: Option<HeadlessFrameStats>,
    pub layer_mask: Option<HeadlessFrameStats>,
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
    sort_triangles: Vec<material_transparency::SortTriangle>,
    triangle_index_count: u32,
    wire_index_count: u32,
    vertex_count: u32,
    normal_line_vertex_count: u32,
    bounds_line_vertex_count: u32,
    mesh_identity: u64,
    topology_signature: u64,
    deformation_signature: u64,
    role_signature: u64,
    tangents: Vec<[f32; 4]>,
    tangents_exact: bool,
    pub draw_revision: u64,
    pub topology_generation: u64,
}

struct GpuOverlayLines {
    vertices: wgpu::Buffer,
    vertex_count: u32,
    signature: u64,
}

struct GpuEffectTexture {
    srgb: bool,
    source_sha256: String,
    _texture: Arc<wgpu::Texture>,
    bind_group: wgpu::BindGroup,
}

struct GpuEffectBatch {
    texture_index: usize,
    blend: EffectBlendMode,
    instances: Arc<wgpu::Buffer>,
    first_instance: u32,
    instance_count: u32,
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
            signature: overlay_position_signature(positions),
        }))
    }

    fn upload_effects(
        device: &wgpu::Device,
        vertices: &[EffectLineVertex],
    ) -> Result<Option<Self>, RenderError> {
        if vertices.is_empty() {
            return Ok(None);
        }
        let gpu_vertices = effect_gpu_vertices(vertices)?;
        let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab effect lines"),
            contents: bytemuck::cast_slice(&gpu_vertices),
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
        });
        Ok(Some(Self {
            vertices: buffer,
            vertex_count: u32::try_from(gpu_vertices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            signature: effect_line_signature(vertices),
        }))
    }

    fn update_effects(
        &mut self,
        queue: &wgpu::Queue,
        vertices: &[EffectLineVertex],
    ) -> Result<bool, RenderError> {
        if usize::try_from(self.vertex_count).ok() != Some(vertices.len()) {
            return Ok(false);
        }
        let gpu_vertices = effect_gpu_vertices(vertices)?;
        queue.write_buffer(&self.vertices, 0, bytemuck::cast_slice(&gpu_vertices));
        self.signature = effect_line_signature(vertices);
        Ok(true)
    }
}

fn effect_gpu_vertices(vertices: &[EffectLineVertex]) -> Result<Vec<GpuVertex>, RenderError> {
    if !vertices.len().is_multiple_of(2) {
        return Err(RenderError::InvalidOverlay(
            "effect line-list vertex count must be even".to_owned(),
        ));
    }
    if vertices.iter().any(|vertex| {
        vertex.position.iter().any(|value| !value.is_finite())
            || vertex.colour.iter().any(|value| !value.is_finite())
    }) {
        return Err(RenderError::InvalidOverlay(
            "effect line-list positions and colours must be finite".to_owned(),
        ));
    }
    Ok(vertices
        .iter()
        .copied()
        .map(GpuVertex::effect_overlay)
        .collect())
}

fn overlay_position_signature(positions: &[[f32; 3]]) -> u64 {
    let mut hasher = DefaultHasher::new();
    positions.len().hash(&mut hasher);
    for position in positions {
        for component in position {
            component.to_bits().hash(&mut hasher);
        }
    }
    hasher.finish()
}

fn effect_line_signature(vertices: &[EffectLineVertex]) -> u64 {
    let mut hasher = DefaultHasher::new();
    vertices.len().hash(&mut hasher);
    for vertex in vertices {
        for component in vertex.position.iter().chain(vertex.colour.iter()) {
            component.to_bits().hash(&mut hasher);
        }
    }
    hasher.finish()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct GpuMaterialRange {
    material: u32,
    part_id: u32,
    first_index: u32,
    index_count: u32,
}

struct GpuMaterialTexture {
    texture: Arc<wgpu::Texture>,
    view_format: wgpu::TextureFormat,
    source_sha256: String,
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
    alpha_blend: bool,
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
    role_signature: u64,
}

fn classify_mesh_upload(current: MeshUploadKey, next: MeshUploadKey) -> MeshUploadAction {
    if current.mesh_identity != next.mesh_identity
        || current.topology_generation != next.topology_generation
        || current.topology_signature != next.topology_signature
        || current.role_signature != next.role_signature
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

fn scene_role_signature(roles: Option<&[u32]>, vertex_count: usize) -> Result<u64, RenderError> {
    let Some(roles) = roles else {
        return Ok(0);
    };
    if roles.len() != vertex_count {
        return Err(RenderError::InvalidSnapshot(format!(
            "scene role list has {} entries for {vertex_count} vertices",
            roles.len()
        )));
    }
    let mut hasher = DefaultHasher::new();
    1_u8.hash(&mut hasher);
    roles.hash(&mut hasher);
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
    scene_roles: Option<&[u32]>,
    tangents: &[[f32; 4]],
) -> Result<Vec<GpuVertex>, RenderError> {
    if tangents.len() != snapshot.positions.len() {
        return Err(RenderError::InvalidSnapshot(format!(
            "{} positions have {} tangents",
            snapshot.positions.len(),
            tangents.len()
        )));
    }
    if scene_roles.is_some_and(|roles| roles.len() != snapshot.positions.len()) {
        return Err(RenderError::InvalidSnapshot(format!(
            "scene role list has {} entries for {} positions",
            scene_roles.map_or(0, <[u32]>::len),
            snapshot.positions.len()
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
                editable_role: scene_roles.map_or(0, |roles| roles[index]),
            }
        })
        .collect())
}

impl GpuMeshBuffers {
    pub fn upload(device: &wgpu::Device, snapshot: &DrawSnapshot) -> Result<Self, RenderError> {
        Self::upload_with_deformation(device, snapshot, None, None)
    }

    fn upload_with_deformation(
        device: &wgpu::Device,
        snapshot: &DrawSnapshot,
        deformation_reference: Option<&[[f32; 3]]>,
        scene_roles: Option<&[u32]>,
    ) -> Result<Self, RenderError> {
        let tangents = vertex_tangents(snapshot)?;
        let vertices = gpu_vertices_with_tangents(
            snapshot,
            deformation_reference,
            scene_roles,
            tangents.as_slice(),
        )?;
        let vertex = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab vertices"),
            contents: bytemuck::cast_slice(&vertices),
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
        });
        let (material_indices, material_ranges) = material_index_batches(snapshot)?;
        let sort_triangles = material_transparency::sort_triangles(&vertices, &material_indices);
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
            sort_triangles,
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
            role_signature: scene_role_signature(scene_roles, snapshot.positions.len())?,
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
        role_signature: u64,
    ) -> MeshUploadAction {
        classify_mesh_upload(
            MeshUploadKey {
                mesh_identity: self.mesh_identity,
                draw_revision: self.draw_revision,
                topology_generation: self.topology_generation,
                topology_signature: self.topology_signature,
                deformation_signature: self.deformation_signature,
                role_signature: self.role_signature,
            },
            MeshUploadKey {
                mesh_identity: snapshot.mesh_identity,
                draw_revision: snapshot.draw_revision,
                topology_generation: snapshot.topology_generation,
                topology_signature: topology_signature(snapshot),
                deformation_signature,
                role_signature,
            },
        )
    }

    fn matches_snapshot(&self, snapshot: &DrawSnapshot) -> bool {
        self.upload_action(snapshot, 0, 0) == MeshUploadAction::Reuse
    }

    fn refresh_geometry(
        &mut self,
        queue: &wgpu::Queue,
        snapshot: &DrawSnapshot,
        deformation_reference: Option<&[[f32; 3]]>,
        deformation_signature: u64,
        scene_roles: Option<&[u32]>,
        role_signature: u64,
        update_mode: GeometryUpdateMode,
    ) -> Result<(), RenderError> {
        let tangents = match update_mode {
            GeometryUpdateMode::Interactive => {
                reproject_vertex_tangents(&snapshot.normals, &self.tangents)?
            }
            GeometryUpdateMode::Final => vertex_tangents(snapshot)?,
        };
        let vertices = gpu_vertices_with_tangents(
            snapshot,
            deformation_reference,
            scene_roles,
            tangents.as_slice(),
        )?;
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
        for triangle in &mut self.sort_triangles {
            triangle.refresh(&vertices);
        }
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
        self.role_signature = role_signature;
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

/// A submitted frame. GPU waiting and file encoding belong on a worker.
pub struct PendingFrameCapture {
    device: wgpu::Device,
    readback: wgpu::Buffer,
    width: u32,
    height: u32,
    format: wgpu::TextureFormat,
}
impl PendingFrameCapture {
    /// Read the rendered frame as tightly packed RGBA8 pixels. Like `write`,
    /// this waits for the submitted frame and belongs on a worker.
    pub fn read_rgba(self) -> Result<Vec<u8>, RenderError> {
        let mut pixels =
            read_headless_pixels(&self.device, &self.readback, self.width, self.height)?;
        if matches!(
            self.format,
            wgpu::TextureFormat::Bgra8Unorm | wgpu::TextureFormat::Bgra8UnormSrgb
        ) {
            for pixel in pixels.chunks_exact_mut(4) {
                pixel.swap(0, 2);
            }
        }
        Ok(pixels)
    }

    pub fn write(self, path: &Path) -> Result<(), RenderError> {
        let mut pixels =
            read_headless_pixels(&self.device, &self.readback, self.width, self.height)?;
        if matches!(
            self.format,
            wgpu::TextureFormat::Rgba8Unorm | wgpu::TextureFormat::Rgba8UnormSrgb
        ) {
            for pixel in pixels.chunks_exact_mut(4) {
                pixel.swap(0, 2);
            }
        }
        write_bgra_image(path, self.width, self.height, &pixels)
    }
}

pub struct WindowRenderer {
    _instance: wgpu::Instance,
    surface: wgpu::Surface<'static>,
    adapter: wgpu::Adapter,
    device: wgpu::Device,
    queue: wgpu::Queue,
    config: wgpu::SurfaceConfiguration,
    solid_pipeline: wgpu::RenderPipeline,
    blended_pipeline: wgpu::RenderPipeline,
    wire_pipeline: wgpu::RenderPipeline,
    xray_wire_pipeline: wgpu::RenderPipeline,
    point_pipeline: wgpu::RenderPipeline,
    xray_pipeline: wgpu::RenderPipeline,
    normal_pipeline: wgpu::RenderPipeline,
    bounds_pipeline: wgpu::RenderPipeline,
    bone_pipeline: wgpu::RenderPipeline,
    guide_pipeline: wgpu::RenderPipeline,
    effect_pipeline: wgpu::RenderPipeline,
    face_selection: selection_overlay::FaceSelectionRenderer,
    rig_weights: selection_overlay::FaceSelectionRenderer,
    face_selection_xray: bool,
    effect_particle_alpha_pipeline: wgpu::RenderPipeline,
    effect_particle_additive_pipeline: wgpu::RenderPipeline,
    effect_quad: wgpu::Buffer,
    effect_texture_bind_group_layout: wgpu::BindGroupLayout,
    effect_depth_layout: wgpu::BindGroupLayout,
    effect_sampler: wgpu::Sampler,
    effect_textures: Vec<GpuEffectTexture>,
    effect_batches: Vec<GpuEffectBatch>,
    effect_instance_buffer: Option<(Arc<wgpu::Buffer>, usize)>,
    mesh: Option<GpuMeshBuffers>,
    skeleton_lines: Option<GpuOverlayLines>,
    preview_lines: Option<GpuOverlayLines>,
    effect_lines: Option<GpuOverlayLines>,
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
    /// Replace resources as one transaction. A failed upload must leave the
    /// resident scene usable, including its bindings and live transform.
    pub fn replace_preview_scene<T>(
        &mut self,
        apply: impl FnOnce(&mut Self) -> Result<T, RenderError>,
    ) -> Result<T, RenderError> {
        let mesh = self.mesh.take();
        let textures = std::mem::take(&mut self.material_textures);
        let factors = std::mem::take(&mut self.material_factors);
        let bindings = std::mem::take(&mut self.active_material_bindings);
        let effects = self.effect_textures.split_off(1);
        let batches = std::mem::take(&mut self.effect_batches);
        let instance_buffer = self.effect_instance_buffer.take();
        let camera = self.camera_uniform;
        let stats = self.upload_stats;
        let result = apply(self);
        if result.is_err() {
            self.mesh = mesh;
            self.material_textures = textures;
            self.material_factors = factors;
            self.active_material_bindings = bindings;
            self.effect_textures.truncate(1);
            self.effect_textures.extend(effects);
            self.effect_batches = batches;
            self.effect_instance_buffer = instance_buffer;
            self.camera_uniform = camera;
            self.upload_stats = stats;
            self.queue
                .write_buffer(&self.camera_buffer, 0, bytemuck::bytes_of(&camera));
        }
        result
    }

    pub fn replace_material_factors(
        &mut self,
        factors: &[OwnedMaterialFactors],
        lod: usize,
    ) -> Result<(), RenderError> {
        for (factor, owners) in factors {
            validate_material_factor_ownership(*factor, owners)?;
        }
        resolve_material_factors(factors.iter().map(|(f, o)| (*f, o.as_slice())), lod)?;
        let old = std::mem::replace(
            &mut self.material_factors,
            factors
                .iter()
                .map(|(f, o)| MaterialFactorOwnership {
                    factors: *f,
                    material_indices_by_lod: o.clone(),
                })
                .collect(),
        );
        if let Err(error) = self.set_material_lod(lod) {
            self.material_factors = old;
            return Err(error);
        }
        Ok(())
    }

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
        let effect_texture_bind_group_layout = create_effect_texture_bind_group_layout(&device);
        let effect_sampler = create_effect_sampler(&device);
        let effect_textures = vec![create_procedural_effect_texture(
            &device,
            &queue,
            &effect_texture_bind_group_layout,
            &effect_sampler,
        )];
        let effect_depth_layout = effect_depth::layout(&device, sample_count);
        let effect_particle_alpha_pipeline = create_effect_particle_pipeline(
            &device,
            format,
            &camera_bind_group_layout,
            &effect_texture_bind_group_layout,
            &effect_depth_layout,
            sample_count,
            wgpu::BlendState::ALPHA_BLENDING,
            "CDMW Rust Preview alpha effect particles",
        );
        let effect_particle_additive_pipeline = create_effect_particle_pipeline(
            &device,
            format,
            &camera_bind_group_layout,
            &effect_texture_bind_group_layout,
            &effect_depth_layout,
            sample_count,
            wgpu::BlendState {
                color: wgpu::BlendComponent {
                    src_factor: wgpu::BlendFactor::SrcAlpha,
                    dst_factor: wgpu::BlendFactor::One,
                    operation: wgpu::BlendOperation::Add,
                },
                alpha: wgpu::BlendComponent {
                    src_factor: wgpu::BlendFactor::One,
                    dst_factor: wgpu::BlendFactor::One,
                    operation: wgpu::BlendOperation::Add,
                },
            },
            "CDMW Rust Preview additive effect particles",
        );
        let effect_quad_vertices = [
            EffectQuadVertex {
                corner: [-1.0, -1.0],
                uv: [0.0, 1.0],
            },
            EffectQuadVertex {
                corner: [1.0, -1.0],
                uv: [1.0, 1.0],
            },
            EffectQuadVertex {
                corner: [1.0, 1.0],
                uv: [1.0, 0.0],
            },
            EffectQuadVertex {
                corner: [-1.0, -1.0],
                uv: [0.0, 1.0],
            },
            EffectQuadVertex {
                corner: [1.0, 1.0],
                uv: [1.0, 0.0],
            },
            EffectQuadVertex {
                corner: [-1.0, 1.0],
                uv: [0.0, 0.0],
            },
        ];
        let effect_quad = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Preview effect billboard quad"),
            contents: bytemuck::cast_slice(&effect_quad_vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
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
        let face_selection = selection_overlay::FaceSelectionRenderer::new(
            &device,
            format,
            &texture_bind_group_layout,
            &camera_bind_group_layout,
            sample_count,
        );
        let rig_weights = selection_overlay::FaceSelectionRenderer::new(
            &device,
            format,
            &texture_bind_group_layout,
            &camera_bind_group_layout,
            sample_count,
        );
        Ok(Self {
            _instance: instance,
            surface,
            adapter,
            device,
            queue,
            config,
            solid_pipeline: pipelines.solid,
            blended_pipeline: pipelines.blended,
            wire_pipeline: pipelines.wire,
            xray_wire_pipeline: pipelines.xray_wire,
            point_pipeline: pipelines.point,
            xray_pipeline: pipelines.xray,
            normal_pipeline: pipelines.normal,
            bounds_pipeline: pipelines.bounds,
            bone_pipeline: pipelines.bone,
            guide_pipeline: pipelines.guide,
            effect_pipeline: pipelines.effect,
            face_selection,
            rig_weights,
            face_selection_xray: false,
            effect_particle_alpha_pipeline,
            effect_particle_additive_pipeline,
            effect_quad,
            effect_texture_bind_group_layout,
            effect_depth_layout,
            effect_sampler,
            effect_textures,
            effect_batches: Vec::new(),
            effect_instance_buffer: None,
            mesh: None,
            skeleton_lines: None,
            preview_lines: None,
            effect_lines: None,
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

    /// Uploads a scene once while tagging vertices that should receive the live
    /// placement transform. Role zero is static; any non-zero role is editable.
    pub fn set_snapshot_with_scene_roles(
        &mut self,
        snapshot: &DrawSnapshot,
        scene_roles: &[u32],
    ) -> Result<(), RenderError> {
        self.set_snapshot_with_deformation_mode(
            snapshot,
            None,
            Some(scene_roles),
            GeometryUpdateMode::Final,
        )
    }

    pub fn set_snapshot_with_deformation(
        &mut self,
        snapshot: &DrawSnapshot,
        deformation_reference: Option<&[[f32; 3]]>,
    ) -> Result<(), RenderError> {
        self.set_snapshot_with_deformation_mode(
            snapshot,
            deformation_reference,
            None,
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
            None,
            GeometryUpdateMode::Interactive,
        )
    }

    fn set_snapshot_with_deformation_mode(
        &mut self,
        snapshot: &DrawSnapshot,
        deformation_reference: Option<&[[f32; 3]]>,
        scene_roles: Option<&[u32]>,
        update_mode: GeometryUpdateMode,
    ) -> Result<(), RenderError> {
        let deformation_signature = deformation_signature(deformation_reference)?;
        let role_signature = scene_role_signature(scene_roles, snapshot.positions.len())?;
        let mut action = self
            .mesh
            .as_ref()
            .map_or(MeshUploadAction::Replace, |mesh| {
                mesh.upload_action(snapshot, deformation_signature, role_signature)
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
                        scene_roles,
                        role_signature,
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
                    scene_roles,
                )?);
                self.upload_stats.full_uploads = self.upload_stats.full_uploads.saturating_add(1);
            }
        }
        Ok(())
    }

    /// Updates only the small camera/scene uniform used by editable-role
    /// vertices. This deliberately leaves all mesh buffers untouched.
    pub fn set_scene_transform(&mut self, model: Mat4) -> Result<(), RenderError> {
        let determinant = model.determinant();
        let normal = model.inverse().transpose();
        if !model.is_finite()
            || determinant == 0.0
            || !determinant.is_finite()
            || !normal.is_finite()
        {
            return Err(RenderError::InvalidSnapshot(
                "scene transform must be finite and invertible".to_owned(),
            ));
        }
        let model_columns = model.to_cols_array_2d();
        let normal_columns = normal.to_cols_array_2d();
        if self.camera_uniform.scene_model == model_columns
            && self.camera_uniform.scene_normal == normal_columns
        {
            return Ok(());
        }
        self.camera_uniform.scene_model = model_columns;
        self.camera_uniform.scene_normal = normal_columns;
        self.queue.write_buffer(
            &self.camera_buffer,
            0,
            bytemuck::bytes_of(&self.camera_uniform),
        );
        self.upload_stats.scene_transform_updates =
            self.upload_stats.scene_transform_updates.saturating_add(1);
        Ok(())
    }

    pub fn set_camera(&mut self, view_projection: Mat4) {
        self.set_camera_with_basis(view_projection, Vec3::X, Vec3::Y);
    }

    pub fn set_camera_with_basis(
        &mut self,
        view_projection: Mat4,
        camera_right: Vec3,
        camera_up: Vec3,
    ) {
        let view_direction = view_direction_from_view_projection(view_projection)
            .extend(0.0)
            .to_array();
        let camera_right = camera_right.normalize_or(Vec3::X).extend(0.0).to_array();
        let camera_up = camera_up.normalize_or(Vec3::Y).extend(0.0).to_array();
        let view_projection = view_projection.to_cols_array_2d();
        if self.camera_uniform.view_projection == view_projection
            && self.camera_uniform.view_direction == view_direction
            && self.camera_uniform.camera_right == camera_right
            && self.camera_uniform.camera_up == camera_up
        {
            return;
        }
        self.camera_uniform.view_projection = view_projection;
        self.camera_uniform.view_direction = view_direction;
        self.camera_uniform.camera_right = camera_right;
        self.camera_uniform.camera_up = camera_up;
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

    pub fn set_lighting_preset(&mut self, preset: LightingPreset) {
        let value = preset.shader_value();
        if self.camera_uniform.lighting_preset == value {
            return;
        }
        self.camera_uniform.lighting_preset = value;
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

    pub fn set_face_selection(
        &mut self,
        positions: &[[f32; 3]],
        colour: [f32; 4],
    ) -> Result<(), RenderError> {
        self.face_selection
            .upload(&self.device, &self.queue, positions, colour)
    }

    pub fn set_face_selection_xray(&mut self, xray: bool) {
        self.face_selection_xray = xray;
    }

    /// Display-only, interpolated skin weights; independent of edit selection.
    pub fn set_rig_weights(
        &mut self,
        positions: &[[f32; 3]],
        colours: &[[f32; 4]],
    ) -> Result<(), RenderError> {
        self.rig_weights
            .upload_coloured(&self.device, &self.queue, positions, colours)
    }

    pub fn set_skeleton_lines(&mut self, positions: &[[f32; 3]]) -> Result<(), RenderError> {
        self.skeleton_lines = GpuOverlayLines::upload(&self.device, positions)?;
        if self.skeleton_lines.is_none() {
            self.show_bones = false;
        }
        Ok(())
    }

    /// Set depth-aware, individually coloured scene guides such as the grid and
    /// reference wire. Mesh depth occludes these lines instead of painting them
    /// through the solid item.
    pub fn set_preview_lines(&mut self, vertices: &[EffectLineVertex]) -> Result<(), RenderError> {
        let signature = effect_line_signature(vertices);
        if self
            .preview_lines
            .as_ref()
            .is_some_and(|lines| lines.signature == signature)
            || (vertices.is_empty() && self.preview_lines.is_none())
        {
            return Ok(());
        }
        if let Some(lines) = self.preview_lines.as_mut()
            && lines.update_effects(&self.queue, vertices)?
        {
            return Ok(());
        }
        self.preview_lines = GpuOverlayLines::upload_effects(&self.device, vertices)?;
        Ok(())
    }

    /// Set animated Archive Preview effect guides. Effects use authored colour
    /// and a dedicated high-visibility pipeline instead of sharing skeleton cyan.
    pub fn set_effect_lines(&mut self, vertices: &[EffectLineVertex]) -> Result<(), RenderError> {
        let signature = effect_line_signature(vertices);
        if self
            .effect_lines
            .as_ref()
            .is_some_and(|lines| lines.signature == signature)
            || (vertices.is_empty() && self.effect_lines.is_none())
        {
            return Ok(());
        }
        if let Some(lines) = self.effect_lines.as_mut()
            && lines.update_effects(&self.queue, vertices)?
        {
            return Ok(());
        }
        self.effect_lines = GpuOverlayLines::upload_effects(&self.device, vertices)?;
        Ok(())
    }

    /// Remove package-authored sprites while retaining the built-in soft
    /// procedural fallback at texture index zero.
    pub fn reset_effect_textures(&mut self) {
        self.effect_textures.truncate(1);
        self.effect_batches.clear();
    }

    /// Upload one validated package DDS. Identical bytes share the same GPU
    /// texture even when several archive paths refer to them.
    pub fn add_effect_dds_texture(&mut self, bytes: &[u8]) -> Result<usize, RenderError> {
        let identity = dds_texture_identity(bytes, TextureRole::BaseColor)?;
        if let Some(index) = self
            .effect_textures
            .iter()
            .position(|texture| texture.source_sha256 == identity.source_sha256)
        {
            return Ok(index);
        }
        let uploaded =
            upload_dds_texture(&self.device, &self.queue, bytes, TextureRole::BaseColor)?;
        let texture = effect_texture_binding(
            &self.device,
            &self.effect_texture_bind_group_layout,
            &self.effect_sampler,
            uploaded.texture,
            uploaded.view_format,
            uploaded.source_sha256,
        );
        self.effect_textures.push(texture);
        Ok(self.effect_textures.len() - 1)
    }

    /// Publish bounded billboard/ribbon instances. Alpha particles retain a
    /// global far-to-near order; contiguous texture runs become instanced draws.
    pub fn set_effect_particles(
        &mut self,
        instances: &[EffectBillboardInstance],
    ) -> Result<(), RenderError> {
        const MAX_EFFECT_INSTANCES: usize = 32_768;
        if instances.len() > MAX_EFFECT_INSTANCES {
            return Err(RenderError::ResourceLimit);
        }
        if instances.iter().any(|instance| {
            instance.texture_index >= self.effect_textures.len()
                || !instance.depth.is_finite()
                || !(-1..=3).contains(&instance.texture_channel)
                || !instance.frame_blend.is_finite()
                || !(0.0..=1.0).contains(&instance.frame_blend)
                || instance
                    .triangle_uvs
                    .is_some_and(|uvs| uvs.iter().flatten().any(|v| !v.is_finite()))
                || !instance
                    .center
                    .iter()
                    .chain(instance.axis_right.iter())
                    .chain(instance.axis_up.iter())
                    .chain(instance.colour.iter())
                    .chain(instance.uv_rect.iter())
                    .all(|value| value.is_finite())
        }) {
            return Err(RenderError::InvalidOverlay(
                "effect billboard instance is non-finite or names an unavailable texture"
                    .to_owned(),
            ));
        }
        let mut ordered = instances.to_vec();
        // Smoke and additive light must share depth order: distant smoke must
        // not cover a nearer flame merely because it uses a different blend.
        ordered.sort_by(|left, right| right.depth.total_cmp(&left.depth));
        self.effect_batches.clear();
        if ordered.is_empty() {
            return Ok(());
        }
        let required = ordered.len();
        if self
            .effect_instance_buffer
            .as_ref()
            .is_none_or(|(_, capacity)| *capacity < required)
        {
            let capacity = required.next_power_of_two().min(MAX_EFFECT_INSTANCES);
            let buffer = self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("CDMW reusable effect instances"),
                size: (capacity * std::mem::size_of::<GpuEffectBillboardInstance>()) as u64,
                usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            self.effect_instance_buffer = Some((Arc::new(buffer), capacity));
        }
        let buffer = &self
            .effect_instance_buffer
            .as_ref()
            .expect("allocated instances")
            .0;
        let gpu = ordered
            .iter()
            .map(|instance| GpuEffectBillboardInstance {
                center: instance.center,
                axis_right: instance.axis_right,
                axis_up: instance.axis_up,
                colour: instance.colour,
                uv_rect: instance
                    .triangle_uvs
                    .map(|uv| [uv[0][0], uv[0][1], uv[1][0], uv[1][1]])
                    .unwrap_or(instance.uv_rect),
                sprite_options: [
                    instance.texture_channel as f32,
                    instance.frame_blend,
                    if instance.triangle_uvs.is_some() {
                        1.0
                    } else {
                        0.0
                    },
                    if self.effect_textures[instance.texture_index].srgb {
                        0.0
                    } else {
                        1.0
                    },
                ],
                third_uv: instance.triangle_uvs.map(|uv| uv[2]).unwrap_or([0.0; 2]),
            })
            .collect::<Vec<_>>();
        self.queue
            .write_buffer(buffer, 0, bytemuck::cast_slice(&gpu));
        let mut start = 0usize;
        while start < ordered.len() {
            let texture_index = ordered[start].texture_index;
            let blend = ordered[start].blend;
            let mut end = start + 1;
            while end < ordered.len()
                && ordered[end].texture_index == texture_index
                && ordered[end].blend == blend
            {
                end += 1;
            }
            self.effect_batches.push(GpuEffectBatch {
                texture_index,
                blend,
                instances: Arc::clone(buffer),
                first_instance: start as u32,
                instance_count: (end - start) as u32,
            });
            start = end;
        }
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
        let identity = dds_texture_identity(bytes, role)?;
        let shared_texture = self
            .material_textures
            .iter()
            .find(|texture| texture.source_sha256 == identity.source_sha256)
            .map(|texture| Arc::clone(&texture.texture));
        let uploaded = if let Some(texture) = shared_texture {
            UploadedDdsTexture {
                texture,
                view_format: identity.view_format,
                source_sha256: identity.source_sha256,
                single_channel: identity.single_channel,
            }
        } else {
            upload_dds_texture(&self.device, &self.queue, bytes, role)?
        };
        self.material_textures.push(GpuMaterialTexture {
            texture: uploaded.texture,
            view_format: uploaded.view_format,
            source_sha256: uploaded.source_sha256,
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

    // Shared by the window and capture: identical mesh, transforms, materials,
    // lighting, depth, MSAA and effects, with an explicit output target.
    #[allow(clippy::too_many_arguments)]
    fn record_scene(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        view: &wgpu::TextureView,
        depth: &wgpu::TextureView,
        multisample: Option<&MultisampleTarget>,
        output_width: u32,
        output_height: u32,
        viewport: Option<[f32; 4]>,
    ) {
        let transparency = self.mesh.as_ref().and_then(|mesh| {
            material_transparency::prepare(
                &self.device,
                mesh,
                &self.active_material_bindings,
                &self.camera_uniform,
                self.view_mode,
            )
        });
        {
            let (mesh_color_view, resolve_target, store) = if let Some(target) = multisample {
                (&target.view, Some(view), wgpu::StoreOp::Store)
            } else {
                (view, None, wgpu::StoreOp::Store)
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
            if let Some(mesh) = &self.mesh {
                if let Some([x, y, width, height]) = viewport {
                    let maximum_x = output_width.saturating_sub(1) as f32;
                    let maximum_y = output_height.saturating_sub(1) as f32;
                    let x = x.clamp(0.0, maximum_x);
                    let y = y.clamp(0.0, maximum_y);
                    let width = width.max(1.0).min(output_width as f32 - x);
                    let height = height.max(1.0).min(output_height as f32 - y);
                    pass.set_viewport(x, y, width, height, 0.0, 1.0);
                    let scissor_x = x.floor() as u32;
                    let scissor_y = y.floor() as u32;
                    let scissor_right = (x + width).ceil().min(output_width as f32) as u32;
                    let scissor_bottom = (y + height).ceil().min(output_height as f32) as u32;
                    pass.set_scissor_rect(
                        scissor_x,
                        scissor_y,
                        scissor_right.saturating_sub(scissor_x).max(1),
                        scissor_bottom.saturating_sub(scissor_y).max(1),
                    );
                }
                self.face_selection.prepare_depth(
                    &mut pass,
                    mesh,
                    &self.default_material_binding.bind_group,
                    &self.camera_bind_group,
                    self.view_mode,
                    self.face_selection_xray,
                );
                self.rig_weights.prepare_depth(
                    &mut pass,
                    mesh,
                    &self.default_material_binding.bind_group,
                    &self.camera_bind_group,
                    self.view_mode,
                    self.view_mode == ViewMode::XRay,
                );
                draw_mesh(
                    &mut pass,
                    mesh,
                    &self.default_material_binding.bind_group,
                    &self.active_material_bindings,
                    &self.camera_bind_group,
                    &self.solid_pipeline,
                    &self.blended_pipeline,
                    transparency.as_ref(),
                    &self.wire_pipeline,
                    &self.xray_wire_pipeline,
                    &self.point_pipeline,
                    &self.xray_pipeline,
                    &self.normal_pipeline,
                    &self.bounds_pipeline,
                    &self.bone_pipeline,
                    &self.guide_pipeline,
                    &self.effect_pipeline,
                    self.skeleton_lines.as_ref(),
                    self.preview_lines.as_ref(),
                    self.effect_lines.as_ref(),
                    self.view_mode,
                    self.show_normals,
                    self.show_bounds,
                    false, // Skeleton context is drawn above weight and selection colours below.
                );
                if self.effect_batches.is_empty() {
                    self.rig_weights.draw(
                        &mut pass,
                        &self.default_material_binding.bind_group,
                        &self.camera_bind_group,
                        self.view_mode == ViewMode::XRay,
                    );
                    self.face_selection.draw(
                        &mut pass,
                        &self.default_material_binding.bind_group,
                        &self.camera_bind_group,
                        self.face_selection_xray,
                    );
                }
                if self.show_bones
                    && let Some(lines) = &self.skeleton_lines
                {
                    pass.set_bind_group(0, &self.default_material_binding.bind_group, &[]);
                    pass.set_bind_group(1, &self.camera_bind_group, &[]);
                    draw_overlay_lines(
                        &mut pass,
                        &lines.vertices,
                        lines.vertex_count,
                        &self.bone_pipeline,
                    );
                }
            }
        }
        effect_depth::render(
            self,
            encoder,
            view,
            depth,
            multisample,
            output_width,
            output_height,
            viewport,
        );
    }

    pub fn capture_frame(
        &mut self,
        width: u32,
        height: u32,
        material: Option<u32>,
    ) -> Result<PendingFrameCapture, RenderError> {
        if width == 0 || height == 0 || width > 2048 || height > 2048 {
            return Err(RenderError::ResourceLimit);
        }
        let saved_ranges = if let Some(material) = material {
            let mesh = self
                .mesh
                .as_mut()
                .ok_or_else(|| RenderError::InvalidSnapshot("No resident mesh".into()))?;
            let filtered: Vec<_> = mesh
                .material_ranges
                .iter()
                .filter(|range| range.material == material)
                .copied()
                .collect();
            if filtered.is_empty() {
                return Err(RenderError::InvalidSnapshot(
                    "Capture material owns no visible triangles".into(),
                ));
            }
            Some(std::mem::replace(&mut mesh.material_ranges, filtered))
        } else {
            None
        };
        let color = create_headless_color_target(&self.device, self.config.format, width, height);
        let view = color.create_view(&wgpu::TextureViewDescriptor::default());
        let depth =
            create_depth_target_with_sample_count(&self.device, width, height, self.sample_count);
        let multisample = create_multisample_target(
            &self.device,
            self.config.format,
            width,
            height,
            self.sample_count,
        );
        let bytes_per_row = padded_headless_bytes_per_row(width);
        let readback = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("CDMW resident preview capture"),
            size: u64::from(bytes_per_row) * u64::from(height),
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        self.record_scene(
            &mut encoder,
            &view,
            &depth.view,
            multisample.as_ref(),
            width,
            height,
            None,
        );
        if let Some(ranges) = saved_ranges {
            self.mesh.as_mut().expect("resident mesh").material_ranges = ranges;
        }
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
        self.queue.submit([encoder.finish()]);
        Ok(PendingFrameCapture {
            device: self.device.clone(),
            readback,
            width,
            height,
            format: self.config.format,
        })
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
                self.surface.configure(&self.device, &self.config);
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
        self.record_scene(
            &mut encoder,
            &view,
            &self.depth_target.view,
            self.multisample_target.as_ref(),
            self.config.width,
            self.config.height,
            self.mesh_viewport,
        );
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
        && factors.base_tint_strength.is_none()
        && factors.alpha_cutoff.is_none()
        && factors.alpha_blend.is_none()
        && factors.opacity.is_none()
        && factors.gltf_metallic_roughness.is_none()
        && factors.hair_anisotropy.is_none()
        && factors.layer_mask_channel.is_none()
        && factors.category_code.is_none()
        && factors.category_confidence.is_none()
        && factors.normal_y_inverted.is_none()
        && factors.texture_flip_vertical.is_none()
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
            factors.opacity,
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
    if factors.category_code.is_some_and(|code| code > 14) {
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
    let request = HeadlessMaterialCaptureRequest { options, output };
    run_headless_material_capture_batch(snapshot, textures, factors, &[request])
        .await?
        .pop()
        .ok_or_else(|| RenderError::Device("material capture returned no report".to_owned()))
}

pub async fn run_headless_material_capture_batch(
    snapshot: &DrawSnapshot,
    textures: &[HeadlessMaterialTexture<'_>],
    factors: &[HeadlessMaterialFactors<'_>],
    requests: &[HeadlessMaterialCaptureRequest<'_>],
) -> Result<Vec<HeadlessMaterialCaptureReport>, RenderError> {
    let batch_started = std::time::Instant::now();
    let Some(first_request) = requests.first() else {
        return Err(RenderError::InvalidSnapshot(
            "headless material capture batch has no requests".to_owned(),
        ));
    };
    if requests.iter().any(|request| {
        let options = request.options;
        options.width == 0
            || options.height == 0
            || options.width > 4_096
            || options.height > 4_096
            || options.lod_index != first_request.options.lod_index
    }) {
        return Err(RenderError::ResourceLimit);
    }
    let lod_index = first_request.options.lod_index;
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
    let renderer_device_ready_ms = batch_started.elapsed().as_secs_f64() * 1_000.0;
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
    let mut uploaded_textures = BTreeMap::<String, Arc<wgpu::Texture>>::new();
    for texture in textures {
        validate_material_texture_ownership(texture.role, texture.material_indices_by_lod)?;
        let identity = dds_texture_identity(texture.bytes, texture.role)?;
        let uploaded = if let Some(existing) = uploaded_textures.get(&identity.source_sha256) {
            UploadedDdsTexture {
                texture: Arc::clone(existing),
                view_format: identity.view_format,
                source_sha256: identity.source_sha256,
                single_channel: identity.single_channel,
            }
        } else {
            let uploaded = upload_dds_texture(&device, &queue, texture.bytes, texture.role)?;
            uploaded_textures.insert(
                uploaded.source_sha256.clone(),
                Arc::clone(&uploaded.texture),
            );
            uploaded
        };
        material_textures.push(GpuMaterialTexture {
            texture: uploaded.texture,
            view_format: uploaded.view_format,
            source_sha256: uploaded.source_sha256,
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
        lod_index,
    )?;
    let texture_bound_materials = resolved.len();
    let resolved_factors = resolve_material_factors(
        material_factors
            .iter()
            .map(|factor| (factor.factors, factor.material_indices_by_lod.as_slice())),
        lod_index,
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
    if let Some(error) = error_scope.pop().await {
        return Err(RenderError::Device(format!(
            "material capture setup validation failed: {error}"
        )));
    }
    let texture_resources_ready_ms = batch_started.elapsed().as_secs_f64() * 1_000.0;
    let dds_textures_uploaded =
        u32::try_from(uploaded_textures.len()).map_err(|_| RenderError::ResourceLimit)?;
    let texture_bound_materials =
        u32::try_from(texture_bound_materials).map_err(|_| RenderError::ResourceLimit)?;
    let active_material_bindings_count =
        u32::try_from(active_material_bindings.len()).map_err(|_| RenderError::ResourceLimit)?;
    let mut reports = Vec::with_capacity(requests.len());
    let mut first_textured_frame_ms = None;
    for request in requests {
        let capture_started = std::time::Instant::now();
        let options = request.options;
        let output = request.output;
        let isolated_snapshot = options
            .isolated_material_index
            .map(|material_index| isolate_material_snapshot(snapshot, material_index))
            .transpose()?;
        let capture_snapshot = isolated_snapshot.as_ref().unwrap_or(snapshot);
        let capture_view = resolved_headless_capture_view(capture_snapshot, options.camera)?;
        let capture_error_scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
        let mesh = GpuMeshBuffers::upload(&device, capture_snapshot)?;
        let view_projection = headless_capture_view_projection(
            capture_snapshot,
            options.width,
            options.height,
            capture_view,
        );
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
                None,
            )
        };
        let textured_readback = render(ViewMode::TexturedSolid);
        let base_color_readback = render(ViewMode::BaseColor);
        let part_id_readback = render(ViewMode::PartId);
        let normal_map_readback = output.normal_map.map(|_| render(ViewMode::NormalMap));
        let material_response_readback = output
            .material_response
            .map(|_| render(ViewMode::MaterialResponse));
        let layer_mask_readback = output.layer_mask.map(|_| render(ViewMode::LayerMask));
        if let Some(error) = capture_error_scope.pop().await {
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
        let first_textured_frame_ms = *first_textured_frame_ms
            .get_or_insert_with(|| batch_started.elapsed().as_secs_f64() * 1_000.0);
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
        let normal_map_pixels = normal_map_readback
            .map(|readback| read_headless_pixels(&device, &readback.0, readback.1, readback.2))
            .transpose()?;
        let material_response_pixels = material_response_readback
            .map(|readback| read_headless_pixels(&device, &readback.0, readback.1, readback.2))
            .transpose()?;
        let layer_mask_pixels = layer_mask_readback
            .map(|readback| read_headless_pixels(&device, &readback.0, readback.1, readback.2))
            .transpose()?;
        write_bgra_image(
            output.textured_bmp,
            options.width,
            options.height,
            &textured_pixels,
        )?;
        write_bgra_image(
            output.base_color_bmp,
            options.width,
            options.height,
            &base_color_pixels,
        )?;
        write_bgra_image(
            output.part_id_bmp,
            options.width,
            options.height,
            &part_id_pixels,
        )?;
        for (path, pixels) in [
            (output.normal_map, normal_map_pixels.as_deref()),
            (
                output.material_response,
                material_response_pixels.as_deref(),
            ),
            (output.layer_mask, layer_mask_pixels.as_deref()),
        ] {
            if let (Some(path), Some(pixels)) = (path, pixels) {
                write_bgra_image(path, options.width, options.height, pixels)?;
            }
        }
        let textured = headless_frame_stats(&textured_pixels)?;
        let base_color = headless_frame_stats(&base_color_pixels)?;
        let part_id = headless_frame_stats(&part_id_pixels)?;
        let normal_map = normal_map_pixels
            .as_deref()
            .map(headless_frame_stats)
            .transpose()?;
        let material_response = material_response_pixels
            .as_deref()
            .map(headless_frame_stats)
            .transpose()?;
        let layer_mask = layer_mask_pixels
            .as_deref()
            .map(headless_frame_stats)
            .transpose()?;
        if textured.non_background_pixels == 0
            || base_color.non_background_pixels == 0
            || part_id.non_background_pixels == 0
            || normal_map
                .as_ref()
                .is_some_and(|stats| stats.non_background_pixels == 0)
            || material_response
                .as_ref()
                .is_some_and(|stats| stats.non_background_pixels == 0)
            || layer_mask
                .as_ref()
                .is_some_and(|stats| stats.non_background_pixels == 0)
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
        reports.push(HeadlessMaterialCaptureReport {
            adapter: adapter_report(&adapter),
            sample_count,
            anisotropy_clamp,
            width: options.width,
            height: options.height,
            lod_index: options.lod_index,
            camera_yaw_degrees: capture_view.yaw.to_degrees(),
            camera_pitch_degrees: capture_view.pitch.to_degrees(),
            isolated_material_index: options.isolated_material_index,
            dds_textures_uploaded,
            texture_bound_materials,
            active_material_bindings: active_material_bindings_count,
            material_ranges_rendered: u32::try_from(mesh.material_ranges.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            renderer_device_ready_ms,
            texture_resources_ready_ms,
            first_textured_frame_ms,
            wall_ms: capture_started.elapsed().as_secs_f64() * 1_000.0,
            textured,
            base_color,
            part_id,
            normal_map,
            material_response,
            layer_mask,
            owner_coverage,
        });
    }
    Ok(reports)
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
            texture: uploaded.texture,
            view_format: uploaded.view_format,
            source_sha256: uploaded.source_sha256,
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
    let constant_emissive_material_bindings = bindings_for_roles(
        &[],
        MaterialPreviewFactors {
            emissive_color: Some([1.0, 0.0, 0.0]),
            emissive_intensity: Some(10.0),
            ..MaterialPreviewFactors::default()
        },
    );
    let zero_emissive_material_bindings = bindings_for_roles(
        &[],
        MaterialPreviewFactors {
            emissive_color: Some([1.0, 0.0, 0.0]),
            emissive_intensity: Some(0.0),
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
    // Pipeline construction alone missed particles disappearing on D3D12.
    // Assert actual pixels through the production bindings and vertex layout.
    effect_particle_proof::verify(&device, &queue)?;
    material_transparency::verify(
        &device,
        &queue,
        format,
        &pipelines,
        &camera_bind_group,
        &mut camera_uniform,
        &camera_buffer,
        &default_material_binding.bind_group,
        |factors| {
            let roles: &[TextureRole] =
                if factors.gltf_metallic_roughness == Some(true) && factors.metalness.is_some() {
                    &[TextureRole::Material]
                } else {
                    &[]
                };
            bindings_for_roles(roles, factors)
                .into_values()
                .next()
                .expect("material proof binding")
        },
    )?;
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
    if mesh.upload_action(&refreshed_mesh, 0, 0) != MeshUploadAction::UpdateGeometry {
        return Err(RenderError::Device(
            "headless mesh cache did not choose an in-place same-topology refresh".to_owned(),
        ));
    }
    mesh.refresh_geometry(
        &queue,
        &refreshed_mesh,
        None,
        0,
        None,
        0,
        GeometryUpdateMode::Final,
    )?;
    if !mesh.matches_snapshot(&refreshed_mesh) {
        return Err(RenderError::Device(
            "headless in-place geometry refresh did not advance the cached revision".to_owned(),
        ));
    }
    let mut changed_topology = refreshed_mesh.clone();
    changed_topology.indices.swap(0, 1);
    if mesh.upload_action(&changed_topology, 0, 0) != MeshUploadAction::Replace {
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
    let effect_lines = GpuOverlayLines::upload_effects(
        &device,
        &[
            EffectLineVertex {
                position: [overlay_minimum.x, overlay_minimum.y, overlay_depth],
                colour: [1.0, 0.08, 0.42, 0.9],
            },
            EffectLineVertex {
                position: [overlay_maximum.x, overlay_maximum.y, overlay_depth],
                colour: [1.0, 0.08, 0.42, 0.9],
            },
            EffectLineVertex {
                position: [overlay_minimum.x, overlay_maximum.y, overlay_depth],
                colour: [0.1, 0.75, 1.0, 0.8],
            },
            EffectLineVertex {
                position: [overlay_maximum.x, overlay_minimum.y, overlay_depth],
                colour: [0.1, 0.75, 1.0, 0.8],
            },
        ],
    )?
    .ok_or_else(|| RenderError::InvalidOverlay("headless effect lines are empty".to_owned()))?;
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
                &device,
                &camera_uniform,
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
                None,
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
        ("constant emissive", constant_emissive_material_bindings),
        ("zero emissive", zero_emissive_material_bindings),
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
    let effect_overlay_readback = render_headless_readback_with_effects(
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
        Some(&effect_lines),
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
        .saturating_add(8);
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
    let effect_overlay_pixels = read_headless_pixels(
        &device,
        &effect_overlay_readback.0,
        effect_overlay_readback.1,
        effect_overlay_readback.2,
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
    let effect_overlay_pixels_changed =
        changed_pixel_count(&bone_overlay_base_pixels, &effect_overlay_pixels)?;
    if effect_overlay_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless authored-colour effect overlay did not change any rendered pixel".to_owned(),
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
    let constant_emissive_pixels = &probe_pixels[probe_index("constant emissive")?];
    let zero_emissive_pixels = &probe_pixels[probe_index("zero emissive")?];
    if changed_pixel_count(constant_emissive_pixels, zero_emissive_pixels)? == 0 {
        return Err(RenderError::Device(
            "constant emissive factors without a texture did not change any rendered pixel"
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
        effect_overlay_pixels_changed,
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

fn resolved_headless_capture_view(
    snapshot: &DrawSnapshot,
    camera: Option<HeadlessMaterialCaptureCamera>,
) -> Result<IntegratedStartupView, RenderError> {
    let Some(camera) = camera else {
        let (minimum, maximum) =
            mesh_bounds(&snapshot.positions).unwrap_or((Vec3::splat(-1.0), Vec3::ONE));
        return Ok(integrated_startup_view(maximum - minimum));
    };
    if !camera.yaw_degrees.is_finite()
        || !camera.pitch_degrees.is_finite()
        || camera.pitch_degrees.abs() > 89.0
    {
        return Err(RenderError::InvalidSnapshot(
            "headless capture camera must use finite yaw and pitch within -89..89 degrees"
                .to_owned(),
        ));
    }
    Ok(IntegratedStartupView {
        yaw: camera.yaw_degrees.to_radians(),
        pitch: camera.pitch_degrees.to_radians(),
    })
}

fn headless_capture_view_projection(
    snapshot: &DrawSnapshot,
    width: u32,
    height: u32,
    capture_view: IntegratedStartupView,
) -> Mat4 {
    let (minimum, maximum) =
        mesh_bounds(&snapshot.positions).unwrap_or((Vec3::splat(-1.0), Vec3::ONE));
    let target = (minimum + maximum) * 0.5;
    let extent = maximum - minimum;
    let view_axis = capture_view.eye_direction();
    let up_axis = capture_view.up_direction();
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

fn isolate_material_snapshot(
    snapshot: &DrawSnapshot,
    material_index: u32,
) -> Result<DrawSnapshot, RenderError> {
    if snapshot.positions.len() != snapshot.normals.len()
        || snapshot.positions.len() != snapshot.uvs.len()
        || !snapshot.indices.len().is_multiple_of(3)
        || snapshot.triangle_materials.len() != snapshot.indices.len() / 3
    {
        return Err(RenderError::InvalidSnapshot(
            "material isolation requires aligned positions, normals, UVs, and triangle owners"
                .to_owned(),
        ));
    }
    let mut remapped_vertices = BTreeMap::<u32, u32>::new();
    let mut positions = Vec::new();
    let mut normals = Vec::new();
    let mut uvs = Vec::new();
    let mut indices = Vec::new();
    let mut triangle_materials = Vec::new();
    for (triangle, owner) in snapshot
        .indices
        .chunks_exact(3)
        .zip(snapshot.triangle_materials.iter().copied())
    {
        if owner != material_index {
            continue;
        }
        for source_index in triangle.iter().copied() {
            let source = usize::try_from(source_index).map_err(|_| RenderError::ResourceLimit)?;
            let position = snapshot.positions.get(source).copied().ok_or_else(|| {
                RenderError::InvalidSnapshot(format!(
                    "material {material_index} references vertex {source_index} outside the snapshot"
                ))
            })?;
            let destination = if let Some(destination) = remapped_vertices.get(&source_index) {
                *destination
            } else {
                let destination =
                    u32::try_from(positions.len()).map_err(|_| RenderError::ResourceLimit)?;
                positions.push(position);
                normals.push(snapshot.normals[source]);
                uvs.push(snapshot.uvs[source]);
                remapped_vertices.insert(source_index, destination);
                destination
            };
            indices.push(destination);
        }
        triangle_materials.push(owner);
    }
    if indices.is_empty() {
        return Err(RenderError::InvalidSnapshot(format!(
            "material {material_index} owns no triangles in the capture snapshot"
        )));
    }
    let selected_vertices = snapshot
        .selected_vertices
        .iter()
        .filter_map(|source| remapped_vertices.get(source).copied())
        .collect();
    Ok(DrawSnapshot {
        mesh_identity: snapshot.mesh_identity,
        draw_revision: snapshot.draw_revision,
        topology_generation: snapshot.topology_generation,
        positions,
        normals,
        uvs,
        indices,
        triangle_materials,
        selected_vertices,
        fingerprint: format!("{}|material:{material_index}", snapshot.fingerprint),
    })
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
    device: &wgpu::Device,
    camera_uniform: &CameraUniform,
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
    effect_lines: Option<&GpuOverlayLines>,
) {
    let transparency = material_transparency::prepare(
        device,
        mesh,
        active_material_bindings,
        camera_uniform,
        mode,
    );
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
        &pipelines.blended,
        transparency.as_ref(),
        &pipelines.wire,
        &pipelines.xray_wire,
        &pipelines.point,
        &pipelines.xray,
        &pipelines.normal,
        &pipelines.bounds,
        &pipelines.bone,
        &pipelines.guide,
        &pipelines.effect,
        skeleton_lines,
        None,
        effect_lines,
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
        None,
    )
}

#[allow(clippy::too_many_arguments)]
fn render_headless_readback_with_effects(
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
    effect_lines: Option<&GpuOverlayLines>,
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
        None,
        false,
        effect_lines,
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
    effect_lines: Option<&GpuOverlayLines>,
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
        device,
        camera_uniform,
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
        effect_lines,
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
        .poll(wgpu::PollType::Wait {
            submission_index: None,
            timeout: Some(std::time::Duration::from_secs(30)),
        })
        .map_err(|error| RenderError::Device(format!("headless readback wait failed: {error}")))?;
    receiver
        .recv_timeout(std::time::Duration::from_secs(1))
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

fn write_bgra_image(
    path: &Path,
    width: u32,
    height: u32,
    pixels: &[u8],
) -> Result<(), RenderError> {
    if path
        .extension()
        .is_some_and(|extension| extension.eq_ignore_ascii_case("png"))
    {
        return write_bgra_png(path, width, height, pixels);
    }
    write_bgra_bmp(path, width, height, pixels)
}

fn write_bgra_png(path: &Path, width: u32, height: u32, pixels: &[u8]) -> Result<(), RenderError> {
    let expected_len = usize::try_from(
        u64::from(width)
            .checked_mul(u64::from(height))
            .and_then(|pixel_count| pixel_count.checked_mul(4))
            .ok_or(RenderError::ResourceLimit)?,
    )
    .map_err(|_| RenderError::ResourceLimit)?;
    if pixels.len() != expected_len {
        return Err(RenderError::Device(format!(
            "PNG dimensions require {expected_len} BGRA bytes, received {}",
            pixels.len()
        )));
    }
    let mut rgba = pixels.to_vec();
    for pixel in rgba.chunks_exact_mut(4) {
        pixel.swap(0, 2);
    }
    let file = std::fs::File::create(path).map_err(|error| {
        RenderError::Device(format!(
            "failed to create headless capture PNG {}: {error}",
            path.display()
        ))
    })?;
    let mut encoder = png::Encoder::new(std::io::BufWriter::new(file), width, height);
    encoder.set_color(png::ColorType::Rgba);
    encoder.set_depth(png::BitDepth::Eight);
    encoder.set_compression(png::Compression::Fast);
    encoder.set_filter(png::Filter::Sub);
    let mut writer = encoder.write_header().map_err(|error| {
        RenderError::Device(format!(
            "failed to write headless capture PNG header {}: {error}",
            path.display()
        ))
    })?;
    writer.write_image_data(&rgba).map_err(|error| {
        RenderError::Device(format!(
            "failed to write headless capture PNG {}: {error}",
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
    blended: wgpu::RenderPipeline,
    wire: wgpu::RenderPipeline,
    xray_wire: wgpu::RenderPipeline,
    point: wgpu::RenderPipeline,
    xray: wgpu::RenderPipeline,
    normal: wgpu::RenderPipeline,
    bounds: wgpu::RenderPipeline,
    bone: wgpu::RenderPipeline,
    guide: wgpu::RenderPipeline,
    effect: wgpu::RenderPipeline,
}

fn create_effect_texture_bind_group_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
    device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("CDMW Rust Preview effect sprite layout"),
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
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                count: None,
            },
        ],
    })
}

fn create_effect_sampler(device: &wgpu::Device) -> wgpu::Sampler {
    device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("CDMW Rust Preview effect sprite sampler"),
        address_mode_u: wgpu::AddressMode::ClampToEdge,
        address_mode_v: wgpu::AddressMode::ClampToEdge,
        address_mode_w: wgpu::AddressMode::ClampToEdge,
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        mipmap_filter: wgpu::MipmapFilterMode::Linear,
        ..wgpu::SamplerDescriptor::default()
    })
}

fn effect_texture_binding(
    device: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    sampler: &wgpu::Sampler,
    texture: Arc<wgpu::Texture>,
    view_format: wgpu::TextureFormat,
    source_sha256: String,
) -> GpuEffectTexture {
    let view = texture.create_view(&wgpu::TextureViewDescriptor {
        label: Some("CDMW Rust Preview effect sprite view"),
        format: Some(view_format),
        ..wgpu::TextureViewDescriptor::default()
    });
    let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("CDMW Rust Preview effect sprite binding"),
        layout,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(&view),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::Sampler(sampler),
            },
        ],
    });
    GpuEffectTexture {
        srgb: view_format.is_srgb(),
        source_sha256,
        _texture: texture,
        bind_group,
    }
}

fn create_procedural_effect_texture(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    layout: &wgpu::BindGroupLayout,
    sampler: &wgpu::Sampler,
) -> GpuEffectTexture {
    const SIZE: u32 = 64;
    let mut pixels = Vec::with_capacity((SIZE * SIZE * 4) as usize);
    for y in 0..SIZE {
        for x in 0..SIZE {
            let uv = Vec2::new(
                (x as f32 + 0.5) / SIZE as f32 * 2.0 - 1.0,
                (y as f32 + 0.5) / SIZE as f32 * 2.0 - 1.0,
            );
            let radius = uv.length();
            let core = (1.0 - radius).clamp(0.0, 1.0);
            let alpha = (core * core * (3.0 - 2.0 * core) * 255.0).round() as u8;
            pixels.extend_from_slice(&[255, 255, 255, alpha]);
        }
    }
    let texture = Arc::new(device.create_texture(&wgpu::TextureDescriptor {
        label: Some("CDMW Rust Preview procedural soft sprite"),
        size: wgpu::Extent3d {
            width: SIZE,
            height: SIZE,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8UnormSrgb,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    }));
    queue.write_texture(
        wgpu::TexelCopyTextureInfo {
            texture: &texture,
            mip_level: 0,
            origin: wgpu::Origin3d::ZERO,
            aspect: wgpu::TextureAspect::All,
        },
        &pixels,
        wgpu::TexelCopyBufferLayout {
            offset: 0,
            bytes_per_row: Some(SIZE * 4),
            rows_per_image: Some(SIZE),
        },
        wgpu::Extent3d {
            width: SIZE,
            height: SIZE,
            depth_or_array_layers: 1,
        },
    );
    effect_texture_binding(
        device,
        layout,
        sampler,
        texture,
        wgpu::TextureFormat::Rgba8UnormSrgb,
        "procedural-soft-sprite-v1".to_owned(),
    )
}

fn create_effect_particle_pipeline(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    camera_layout: &wgpu::BindGroupLayout,
    effect_layout: &wgpu::BindGroupLayout,
    depth_layout: &wgpu::BindGroupLayout,
    sample_count: u32,
    blend: wgpu::BlendState,
    label: &str,
) -> wgpu::RenderPipeline {
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("CDMW Rust Preview effect particle shader"),
        source: wgpu::ShaderSource::Wgsl(if sample_count > 1 {
            effect_particle_shader::SHADER
                .replace("texture_depth_2d", "texture_depth_multisampled_2d")
                .replace(
                    "textureLoad(effect_scene_depth, pixel, 0)",
                    "textureLoad(effect_scene_depth, pixel, i32(sample_index))",
                )
                .into()
        } else {
            effect_particle_shader::SHADER.into()
        }),
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("CDMW Rust Preview effect particle pipeline layout"),
        // Contiguous bindings are required for the particle camera on D3D12.
        // This dedicated shader never includes the 16-texture mesh material group.
        bind_group_layouts: &[Some(camera_layout), Some(effect_layout), Some(depth_layout)],
        immediate_size: 0,
    });
    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some(label),
        layout: Some(&layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: Some("vs_effect_particle"),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            buffers: &[
                Some(EffectQuadVertex::layout()),
                Some(GpuEffectBillboardInstance::layout()),
            ],
        },
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: Some("fs_effect_particle"),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            targets: &[Some(wgpu::ColorTargetState {
                format,
                blend: Some(blend),
                write_mask: wgpu::ColorWrites::ALL,
            })],
        }),
        primitive: wgpu::PrimitiveState {
            topology: wgpu::PrimitiveTopology::TriangleList,
            strip_index_format: None,
            front_face: wgpu::FrontFace::Ccw,
            cull_mode: None,
            unclipped_depth: false,
            polygon_mode: wgpu::PolygonMode::Fill,
            conservative: false,
        },
        depth_stencil: Some(wgpu::DepthStencilState {
            format: DEPTH_FORMAT,
            depth_write_enabled: Some(false),
            depth_compare: Some(wgpu::CompareFunction::LessEqual),
            stencil: wgpu::StencilState::default(),
            bias: wgpu::DepthBiasState::default(),
        }),
        multisample: wgpu::MultisampleState {
            count: sample_count,
            mask: !0,
            alpha_to_coverage_enabled: false,
        },
        multiview_mask: None,
        cache: None,
    })
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
        blended: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "blended material",
            wgpu::PrimitiveTopology::TriangleList,
            "fs_solid",
            solid_cull_mode(),
            PipelineDepth::Test,
            Some(wgpu::BlendState::ALPHA_BLENDING),
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
        guide: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "scene guide overlay",
            wgpu::PrimitiveTopology::LineList,
            "fs_effect",
            None,
            scene_guide_pipeline_depth(),
            Some(wgpu::BlendState::ALPHA_BLENDING),
            sample_count,
        ),
        effect: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "effect overlay",
            wgpu::PrimitiveTopology::LineList,
            "fs_effect",
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
    DepthOnly,
    Test,
    Ignore,
}

const fn scene_guide_pipeline_depth() -> PipelineDepth {
    PipelineDepth::Test
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
        PipelineDepth::Write | PipelineDepth::DepthOnly => (
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
                write_mask: if depth == PipelineDepth::DepthOnly {
                    wgpu::ColorWrites::empty()
                } else {
                    wgpu::ColorWrites::ALL
                },
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
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
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
    blended_pipeline: &'a wgpu::RenderPipeline,
    transparency: Option<&'a material_transparency::PreparedTransparency>,
) {
    pass.set_pipeline(pipeline);
    pass.set_index_buffer(mesh.triangle_index.slice(..), wgpu::IndexFormat::Uint32);
    for range in &mesh.material_ranges {
        if transparency.is_some()
            && active_material_bindings
                .get(&range.material)
                .is_some_and(|binding| binding.alpha_blend)
        {
            continue;
        }
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
    if let Some(transparency) = transparency {
        pass.set_pipeline(blended_pipeline);
        pass.set_index_buffer(transparency.index.slice(..), wgpu::IndexFormat::Uint32);
        for batch in &transparency.batches {
            let binding = &active_material_bindings[&batch.material];
            pass.set_bind_group(0, &binding.bind_group, &[]);
            pass.draw_indexed(
                batch.first_index..batch.end_index,
                0,
                batch.part_id..batch.part_id + 1,
            );
        }
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
    blended_pipeline: &'a wgpu::RenderPipeline,
    transparency: Option<&'a material_transparency::PreparedTransparency>,
    wire_pipeline: &'a wgpu::RenderPipeline,
    xray_wire_pipeline: &'a wgpu::RenderPipeline,
    point_pipeline: &'a wgpu::RenderPipeline,
    xray_pipeline: &'a wgpu::RenderPipeline,
    normal_pipeline: &'a wgpu::RenderPipeline,
    bounds_pipeline: &'a wgpu::RenderPipeline,
    bone_pipeline: &'a wgpu::RenderPipeline,
    guide_pipeline: &'a wgpu::RenderPipeline,
    effect_pipeline: &'a wgpu::RenderPipeline,
    skeleton_lines: Option<&'a GpuOverlayLines>,
    preview_lines: Option<&'a GpuOverlayLines>,
    effect_lines: Option<&'a GpuOverlayLines>,
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
            blended_pipeline,
            transparency,
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
        draw_overlay_lines(pass, &lines.vertices, lines.vertex_count, guide_pipeline);
    }
    if let Some(lines) = effect_lines {
        draw_overlay_lines(pass, &lines.vertices, lines.vertex_count, effect_pipeline);
    }
}

fn draw_effect_particles<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    quad: &'a wgpu::Buffer,
    batches: &'a [GpuEffectBatch],
    textures: &'a [GpuEffectTexture],
    camera_bind_group: &'a wgpu::BindGroup,
    depth_bind_group: &'a wgpu::BindGroup,
    alpha_pipeline: &'a wgpu::RenderPipeline,
    additive_pipeline: &'a wgpu::RenderPipeline,
) {
    if batches.is_empty() {
        return;
    }
    pass.set_vertex_buffer(0, quad.slice(..));
    for batch in batches {
        let Some(texture) = textures.get(batch.texture_index) else {
            continue;
        };
        pass.set_pipeline(match batch.blend {
            EffectBlendMode::Additive => additive_pipeline,
            EffectBlendMode::Alpha => alpha_pipeline,
        });
        pass.set_bind_group(0, camera_bind_group, &[]);
        pass.set_bind_group(1, &texture.bind_group, &[]);
        pass.set_bind_group(2, depth_bind_group, &[]);
        pass.set_vertex_buffer(1, batch.instances.slice(..));
        pass.draw(
            0..6,
            batch.first_instance..batch.first_instance + batch.instance_count,
        );
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

/// Resolve authored layers first, then apply explicit user overrides per material.
/// Conflicts within either input remain errors; an override replaces only its fields.
pub fn preview_material_factors(
    authored: &[OwnedMaterialFactors],
    overrides: &[OwnedMaterialFactors],
    lod: usize,
) -> Result<Vec<OwnedMaterialFactors>, RenderError> {
    for (factors, owners) in authored.iter().chain(overrides) {
        validate_material_factor_ownership(*factors, owners)?;
    }
    let mut resolved =
        resolve_material_factors(authored.iter().map(|(f, o)| (*f, o.as_slice())), lod)?;
    let changes = resolve_material_factors(overrides.iter().map(|(f, o)| (*f, o.as_slice())), lod)?;
    for (material, changes) in changes {
        let target = resolved.entry(material).or_default();
        if changes.emissive_color.is_some() {
            target.emissive_color = changes.emissive_color;
        }
        if changes.emissive_intensity.is_some() {
            target.emissive_intensity = changes.emissive_intensity;
        }
        if changes.roughness.is_some() {
            target.roughness = changes.roughness;
        }
        if changes.metalness.is_some() {
            target.metalness = changes.metalness;
        }
        if changes.specular.is_some() {
            target.specular = changes.specular;
        }
        if changes.height_scale.is_some() {
            target.height_scale = changes.height_scale;
        }
        if changes.texture_tint.is_some() {
            target.texture_tint = changes.texture_tint;
        }
        if changes.base_tint_strength.is_some() {
            target.base_tint_strength = changes.base_tint_strength;
        }
        if changes.alpha_cutoff.is_some() {
            target.alpha_cutoff = changes.alpha_cutoff;
        }
        if changes.alpha_blend.is_some() {
            target.alpha_blend = changes.alpha_blend;
        }
        if changes.opacity.is_some() {
            target.opacity = changes.opacity;
        }
        if changes.gltf_metallic_roughness.is_some() {
            target.gltf_metallic_roughness = changes.gltf_metallic_roughness;
        }
        if changes.hair_anisotropy.is_some() {
            target.hair_anisotropy = changes.hair_anisotropy;
        }
        if changes.layer_mask_channel.is_some() {
            target.layer_mask_channel = changes.layer_mask_channel;
        }
        if changes.category_code.is_some() {
            target.category_code = changes.category_code;
        }
        if changes.category_confidence.is_some() {
            target.category_confidence = changes.category_confidence;
        }
        if changes.normal_y_inverted.is_some() {
            target.normal_y_inverted = changes.normal_y_inverted;
        }
        if changes.texture_flip_vertical.is_some() {
            target.texture_flip_vertical = changes.texture_flip_vertical;
        }
        if changes.skin_detail_scale.is_some() {
            target.skin_detail_scale = changes.skin_detail_scale;
        }
        if changes.skin_detail_opacity.is_some() {
            target.skin_detail_opacity = changes.skin_detail_opacity;
        }
    }
    Ok(resolved
        .into_iter()
        .map(|(material, factors)| {
            let mut owners = vec![Vec::new(); lod + 1];
            owners[lod].push(material);
            (factors, owners)
        })
        .collect())
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
            if let Some(alpha_blend) = factors.alpha_blend {
                if resolved
                    .alpha_blend
                    .is_some_and(|existing| existing != alpha_blend)
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting alpha blend modes in LOD {lod_index}"
                    )));
                }
                resolved.alpha_blend = Some(alpha_blend);
            }
            if let Some(opacity) = factors.opacity {
                if resolved
                    .opacity
                    .is_some_and(|existing| existing.to_bits() != opacity.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting opacity factors in LOD {lod_index}"
                    )));
                }
                resolved.opacity = Some(opacity);
            }
            if let Some(gltf_pbr) = factors.gltf_metallic_roughness {
                if resolved
                    .gltf_metallic_roughness
                    .is_some_and(|existing| existing != gltf_pbr)
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting glTF PBR workflows in LOD {lod_index}"
                    )));
                }
                resolved.gltf_metallic_roughness = Some(gltf_pbr);
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
            if let Some(texture_flip_vertical) = factors.texture_flip_vertical {
                if resolved
                    .texture_flip_vertical
                    .is_some_and(|existing| existing != texture_flip_vertical)
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting texture V-flip policies in LOD {lod_index}"
                    )));
                }
                resolved.texture_flip_vertical = Some(texture_flip_vertical);
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

fn material_texture_view(
    textures: &[GpuMaterialTexture],
    index: Option<usize>,
    default: &wgpu::Texture,
) -> wgpu::TextureView {
    index.and_then(|index| textures.get(index)).map_or_else(
        || default.create_view(&wgpu::TextureViewDescriptor::default()),
        |texture| {
            texture.texture.create_view(&wgpu::TextureViewDescriptor {
                format: Some(texture.view_format),
                ..Default::default()
            })
        },
    )
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
    let base_view = material_texture_view(textures, indices.base_color, &defaults.base_color);
    let normal_view = material_texture_view(textures, indices.normal, &defaults.normal);
    let surface_view = material_texture_view(textures, indices.surface, &defaults.surface);
    let roughness_view = material_texture_view(textures, indices.roughness, &defaults.roughness);
    let metalness_view = material_texture_view(textures, indices.metalness, &defaults.metalness);
    let occlusion_view = material_texture_view(textures, indices.occlusion, &defaults.occlusion);
    let emissive_view = material_texture_view(textures, indices.emissive, &defaults.emissive);
    let specular_view = material_texture_view(textures, indices.specular, &defaults.specular);
    let glossiness_view = material_texture_view(textures, indices.glossiness, &defaults.glossiness);
    let opacity_view = material_texture_view(textures, indices.opacity, &defaults.opacity);
    let height_view = material_texture_view(textures, indices.height, &defaults.height);
    let flow_view = material_texture_view(textures, indices.flow, &defaults.flow);
    let layer_mask_view = material_texture_view(textures, indices.layer_mask, &defaults.layer_mask);
    let skin_detail_mask_view =
        material_texture_view(textures, indices.skin_detail_mask, &defaults.layer_mask);
    let skin_detail_normal_view =
        material_texture_view(textures, indices.skin_detail_normal, &defaults.normal);
    let skin_detail_material_view =
        material_texture_view(textures, indices.skin_detail_material, &defaults.surface);
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
    if factors.alpha_blend == Some(true) {
        flags |= MATERIAL_ALPHA_BLEND;
    }
    if factors.gltf_metallic_roughness == Some(true) {
        flags |= MATERIAL_GLTF_PBR;
    }
    if factors.normal_y_inverted == Some(true) {
        flags |= MATERIAL_NORMAL_Y_INVERTED;
    }
    if factors.texture_flip_vertical == Some(true) {
        flags |= MATERIAL_FLIP_V;
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
        opacity: factors.opacity.unwrap_or(1.0),
        emissive_color_and_intensity: {
            let color = factors
                .emissive_color
                .unwrap_or(if indices.emissive.is_some() {
                    [1.0; 3]
                } else {
                    [0.0; 3]
                });
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
        alpha_blend: factors.alpha_blend == Some(true),
    }
}

struct UploadedDdsTexture {
    texture: Arc<wgpu::Texture>,
    view_format: wgpu::TextureFormat,
    source_sha256: String,
    single_channel: bool,
}

struct DdsTextureIdentity {
    view_format: wgpu::TextureFormat,
    source_sha256: String,
    single_channel: bool,
}

fn dds_format_is_single_channel(format: &DdsFormat) -> bool {
    matches!(
        format,
        DdsFormat::Bc4Unorm | DdsFormat::Bc4Snorm | DdsFormat::R8Unorm
    )
}

fn dds_texture_identity(
    bytes: &[u8],
    role: TextureRole,
) -> Result<DdsTextureIdentity, RenderError> {
    let plan =
        plan_2d_upload(bytes, role).map_err(|error| RenderError::Texture(error.to_string()))?;
    Ok(DdsTextureIdentity {
        view_format: map_dds_format(&plan.metadata.format, plan.metadata.color_space)?,
        source_sha256: plan.metadata.source_sha256,
        single_channel: dds_format_is_single_channel(&plan.metadata.format),
    })
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
    let view_format = map_dds_format(&plan.metadata.format, plan.metadata.color_space)?;
    let format = map_dds_format(&plan.metadata.format, ColorSpace::Linear)?;
    validate_dds_upload_requirements(&plan, format, &device.limits(), device.features())?;
    let alternate_view_formats = map_dds_format(&plan.metadata.format, ColorSpace::Srgb)
        .ok()
        .filter(|candidate| *candidate != format)
        .into_iter()
        .collect::<Vec<_>>();
    let texture = Arc::new(device.create_texture(&wgpu::TextureDescriptor {
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
        view_formats: &alternate_view_formats,
    }));
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
        view_format,
        source_sha256: plan.metadata.source_sha256,
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

mod material_transparency {
    //! Draw authored blended surfaces after opaque geometry, ordered in the current view.
    use super::{CameraUniform, GpuMaterialBinding, GpuMeshBuffers, GpuVertex, ViewMode};
    use glam::{Mat4, Vec3};
    use std::collections::BTreeMap;
    use wgpu::util::DeviceExt;

    pub(super) struct SortTriangle {
        indices: [u32; 3],
        fixed_center: Vec3,
        editable_center: Vec3,
        editable_weight: f32,
    }

    impl SortTriangle {
        pub(super) fn refresh(&mut self, vertices: &[GpuVertex]) {
            self.fixed_center = Vec3::ZERO;
            self.editable_center = Vec3::ZERO;
            self.editable_weight = 0.0;
            for index in self.indices {
                let vertex = &vertices[index as usize];
                let position = Vec3::from_array(vertex.position) / 3.0;
                if vertex.editable_role == 0 {
                    self.fixed_center += position;
                } else {
                    self.editable_center += position;
                    self.editable_weight += 1.0 / 3.0;
                }
            }
        }

        fn depth(&self, view_projection: Mat4, scene_model: Mat4) -> f32 {
            let moved = scene_model * self.editable_center.extend(self.editable_weight);
            let clip = view_projection * (self.fixed_center + moved.truncate()).extend(1.0);
            if clip.w.abs() <= 1e-6 {
                f32::INFINITY
            } else {
                clip.z / clip.w
            }
        }
    }

    pub(super) fn sort_triangles(vertices: &[GpuVertex], indices: &[u32]) -> Vec<SortTriangle> {
        indices
            .chunks_exact(3)
            .map(|indices| {
                let mut triangle = SortTriangle {
                    indices: [indices[0], indices[1], indices[2]],
                    fixed_center: Vec3::ZERO,
                    editable_center: Vec3::ZERO,
                    editable_weight: 0.0,
                };
                triangle.refresh(vertices);
                triangle
            })
            .collect()
    }

    pub(super) struct DrawBatch {
        pub(super) material: u32,
        pub(super) part_id: u32,
        pub(super) first_index: u32,
        pub(super) end_index: u32,
    }

    pub(super) struct PreparedTransparency {
        pub(super) index: wgpu::Buffer,
        pub(super) batches: Vec<DrawBatch>,
    }

    pub(super) fn prepare(
        device: &wgpu::Device,
        mesh: &GpuMeshBuffers,
        bindings: &BTreeMap<u32, GpuMaterialBinding>,
        camera: &CameraUniform,
        mode: ViewMode,
    ) -> Option<PreparedTransparency> {
        if !matches!(
            mode,
            ViewMode::TexturedSolid | ViewMode::GameOutdoor | ViewMode::BaseColor
        ) || !bindings.values().any(|binding| binding.alpha_blend)
        {
            return None;
        }
        let view_projection = Mat4::from_cols_array_2d(&camera.view_projection);
        let scene_model = Mat4::from_cols_array_2d(&camera.scene_model);
        let mut ordered = Vec::new();
        for range in &mesh.material_ranges {
            if !bindings
                .get(&range.material)
                .is_some_and(|binding| binding.alpha_blend)
            {
                continue;
            }
            let first = (range.first_index / 3) as usize;
            let count = (range.index_count / 3) as usize;
            for (offset, triangle) in mesh.sort_triangles[first..first + count].iter().enumerate() {
                ordered.push((
                    triangle.depth(view_projection, scene_model),
                    first + offset,
                    range,
                ));
            }
        }
        if ordered.is_empty() {
            return None;
        }
        ordered.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
        let mut indices = Vec::with_capacity(ordered.len() * 3);
        let mut batches: Vec<DrawBatch> = Vec::new();
        for (_, triangle_index, range) in ordered {
            let first_index = indices.len() as u32;
            indices.extend_from_slice(&mesh.sort_triangles[triangle_index].indices);
            if let Some(last) = batches
                .last_mut()
                .filter(|last| last.material == range.material && last.part_id == range.part_id)
            {
                last.end_index += 3;
            } else {
                batches.push(DrawBatch {
                    material: range.material,
                    part_id: range.part_id,
                    first_index,
                    end_index: first_index + 3,
                });
            }
        }
        // Each recorded view owns its sorted indices. A later capture or split view
        // cannot overwrite indices still referenced by an earlier command buffer.
        let index = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW blended material indices"),
            contents: bytemuck::cast_slice(&indices),
            usage: wgpu::BufferUsages::INDEX,
        });
        Some(PreparedTransparency { index, batches })
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn verify(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        format: wgpu::TextureFormat,
        pipelines: &super::Pipelines,
        camera_binding: &wgpu::BindGroup,
        camera: &mut CameraUniform,
        camera_buffer: &wgpu::Buffer,
        default_binding: &wgpu::BindGroup,
        make_binding: impl Fn(super::MaterialPreviewFactors) -> GpuMaterialBinding,
    ) -> Result<(), super::RenderError> {
        let saved_camera = *camera;
        let mut snapshot = cdmw_mesh::DrawSnapshot {
            mesh_identity: u64::MAX - 19,
            draw_revision: 1,
            topology_generation: 1,
            positions: Vec::new(),
            normals: Vec::new(),
            uvs: Vec::new(),
            indices: Vec::new(),
            triangle_materials: Vec::new(),
            selected_vertices: Vec::new(),
            fingerprint: "blended-material-layer-proof-v1".to_owned(),
        };
        let mut roles = Vec::new();
        for (material, depth) in [(0, 0.8), (1, 0.2), (2, 0.5)] {
            let first = snapshot.positions.len() as u32;
            for [x, y] in [[-0.8, -0.8], [0.8, -0.8], [0.8, 0.8], [-0.8, 0.8]] {
                snapshot.positions.push([x, y, depth]);
                snapshot.normals.push([0.0, 0.0, -1.0]);
                snapshot.uvs.push([0.5, 0.5]);
                roles.push(u32::from(material == 1));
            }
            snapshot
                .indices
                .extend([first, first + 1, first + 2, first, first + 2, first + 3]);
            snapshot.triangle_materials.extend([material, material]);
        }
        let mesh = GpuMeshBuffers::upload_with_deformation(device, &snapshot, None, Some(&roles))?;
        let mut factors = [
            super::MaterialPreviewFactors {
                texture_tint: Some([0.0, 0.0, 1.0]),
                opacity: Some(0.5),
                ..Default::default()
            },
            super::MaterialPreviewFactors {
                texture_tint: Some([1.0, 0.0, 0.0]),
                opacity: Some(0.5),
                alpha_blend: Some(true),
                ..Default::default()
            },
            super::MaterialPreviewFactors {
                texture_tint: Some([0.0, 1.0, 0.0]),
                opacity: Some(0.5),
                alpha_blend: Some(true),
                ..Default::default()
            },
        ];
        for (case, expected) in [
            ("ordered layers", [137u8, 137, 188, 255]),
            ("opaque foreground", [255, 0, 0, 255]),
            ("moved transparent layer", [137, 188, 137, 255]),
            ("zero opacity", [255, 0, 0, 255]),
            ("cutout opacity", [255, 0, 0, 255]),
        ] {
            camera.scene_model = Mat4::IDENTITY.to_cols_array_2d();
            let projection = if case == "opaque foreground" {
                Mat4::from_translation(Vec3::Z) * Mat4::from_scale(Vec3::new(1.0, 1.0, -1.0))
            } else {
                Mat4::IDENTITY
            };
            if case == "moved transparent layer" {
                camera.scene_model =
                    Mat4::from_translation(Vec3::new(0.0, 0.0, 0.5)).to_cols_array_2d();
            }
            if case == "zero opacity" {
                factors[1].opacity = Some(0.0);
                factors[2].opacity = Some(0.0);
            }
            if case == "cutout opacity" {
                factors[1].alpha_blend = Some(false);
                factors[1].opacity = Some(0.1);
                factors[1].alpha_cutoff = Some(0.5);
            }
            let bindings = factors
                .iter()
                .copied()
                .enumerate()
                .map(|(i, factor)| (i as u32, make_binding(factor)))
                .collect();
            let (buffer, width, height) = super::render_headless_readback_at(
                device,
                queue,
                format,
                &mesh,
                default_binding,
                &bindings,
                camera_binding,
                pipelines,
                camera,
                camera_buffer,
                ViewMode::BaseColor,
                64,
                64,
                projection,
                None,
                false,
                None,
            );
            let pixels = super::read_headless_pixels(device, &buffer, width, height)?;
            let center = ((height / 2 * width + width / 2) * 4) as usize;
            let actual = &pixels[center..center + 4];
            if actual
                .iter()
                .zip(expected)
                .any(|(actual, expected)| actual.abs_diff(expected) > 3)
            {
                return Err(super::RenderError::Device(format!(
                    "blended material {case}: BGRA pixel {actual:?}, expected {expected:?}"
                )));
            }
        }
        for (case, expected) in [
            ("glTF defaults without maps", [255u8, 255, 255, 255]),
            ("glTF zero factors with a packed map", [0, 10, 0, 255]),
        ] {
            camera.scene_model = Mat4::IDENTITY.to_cols_array_2d();
            let zero_factors = case.contains("zero");
            for factor in &mut factors {
                factor.alpha_blend = Some(false);
                factor.alpha_cutoff = None;
                factor.opacity = Some(1.0);
                factor.gltf_metallic_roughness = Some(true);
                factor.roughness = zero_factors.then_some(0.0);
                factor.metalness = zero_factors.then_some(0.0);
                factor.specular = zero_factors.then_some(0.0);
            }
            let bindings = factors
                .iter()
                .copied()
                .enumerate()
                .map(|(i, factor)| (i as u32, make_binding(factor)))
                .collect();
            let (buffer, width, height) = super::render_headless_readback_at(
                device,
                queue,
                format,
                &mesh,
                default_binding,
                &bindings,
                camera_binding,
                pipelines,
                camera,
                camera_buffer,
                ViewMode::MaterialResponse,
                64,
                64,
                Mat4::IDENTITY,
                None,
                false,
                None,
            );
            let pixels = super::read_headless_pixels(device, &buffer, width, height)?;
            let center = ((height / 2 * width + width / 2) * 4) as usize;
            let actual = &pixels[center..center + 4];
            if actual
                .iter()
                .zip(expected)
                .any(|(actual, expected)| actual.abs_diff(expected) > 3)
            {
                return Err(super::RenderError::Device(format!(
                    "material response {case}: BGRA pixel {actual:?}, expected {expected:?}"
                )));
            }
        }
        // Test imported lighting with a neutral conductor under the key softbox.
        // The authored PBR values must win over an inferred material category.
        snapshot.normals.fill([-0.12, 0.14, -0.98285]);
        let lit_mesh =
            GpuMeshBuffers::upload_with_deformation(device, &snapshot, None, Some(&roles))?;
        let mut samples = Vec::new();
        for (tint, roughness, category) in [
            ([0.8, 0.8, 0.8], 0.18, 0),
            ([0.8, 0.8, 0.8], 0.18, 1),
            ([0.8, 0.8, 0.8], 0.9, 0),
            ([0.72, 0.30, 0.07], 0.18, 0),
            ([0.004, 0.004, 0.004], 0.18, 0),
        ] {
            let bindings = (0..3)
                .map(|material| {
                    (
                        material,
                        make_binding(super::MaterialPreviewFactors {
                            texture_tint: Some(tint),
                            base_tint_strength: Some(0.0),
                            roughness: Some(roughness),
                            category_code: Some(category),
                            category_confidence: Some(1.0),
                            gltf_metallic_roughness: Some(true),
                            ..Default::default()
                        }),
                    )
                })
                .collect();
            let (buffer, width, height) = super::render_headless_readback_at(
                device,
                queue,
                format,
                &lit_mesh,
                default_binding,
                &bindings,
                camera_binding,
                pipelines,
                camera,
                camera_buffer,
                ViewMode::TexturedSolid,
                64,
                64,
                Mat4::IDENTITY,
                None,
                false,
                None,
            );
            let pixels = super::read_headless_pixels(device, &buffer, width, height)?;
            let center = ((height / 2 * width + width / 2) * 4) as usize;
            samples.push(<[u8; 4]>::try_from(&pixels[center..center + 4]).expect("BGRA pixel"));
        }
        let [silver, classified_silver, rough, gold, dark] = samples.as_slice() else {
            unreachable!("five imported lighting samples");
        };
        if silver != classified_silver
            || silver[..3].iter().any(|value| *value < 220)
            || rough[2] >= silver[2]
            || gold[2] <= gold[1]
            || gold[1] <= gold[0]
            || dark[..3].iter().any(|value| *value > 100)
        {
            return Err(super::RenderError::Device(format!(
                "glTF HDR lighting lost highlights, roughness, hue, or category independence: {samples:?}"
            )));
        }
        *camera = saved_camera;
        queue.write_buffer(camera_buffer, 0, bytemuck::bytes_of(camera));
        Ok(())
    }
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
        assert_eq!(std::mem::size_of::<CameraUniform>(), 288);
        let uniform = CameraUniform::new(true);
        assert_eq!(uniform.output_is_srgb, 1);
        assert_eq!(uniform.lighting_preset, 0);
        assert_eq!(uniform.view_direction, [0.0, 0.0, -1.0, 0.0]);
        assert_eq!(uniform.camera_right, [1.0, 0.0, 0.0, 0.0]);
        assert_eq!(uniform.camera_up, [0.0, 1.0, 0.0, 0.0]);
        assert_eq!(uniform.scene_model, Mat4::IDENTITY.to_cols_array_2d());
        assert_eq!(uniform.scene_normal, Mat4::IDENTITY.to_cols_array_2d());
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
        assert_eq!(std::mem::size_of::<GpuVertex>(), 68);
        assert_eq!(GpuVertex::ATTRIBUTES[5].shader_location, 5);
        assert_eq!(GpuVertex::ATTRIBUTES[5].format, wgpu::VertexFormat::Uint32);
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
        assert!(SHADER.contains("select(vec3<f32>(1.0), texel.rgb, (material.flags & MATERIAL_BASE_COLOR) != 0u) * texture_tint"));
        assert!(SHADER.contains("else if min(u32(material.relief_factors.z + 0.5), 14u) == 6u"));
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
    fn renderer_accepts_the_complete_shared_material_category_contract() {
        let ownership = [vec![0_u32]];
        for category_code in 0..=14 {
            validate_material_factor_ownership(
                MaterialPreviewFactors {
                    category_code: Some(category_code),
                    category_confidence: Some(1.0),
                    ..MaterialPreviewFactors::default()
                },
                &ownership,
            )
            .unwrap_or_else(|error| {
                panic!("shared material category {category_code} was rejected: {error}")
            });
        }
        let error = validate_material_factor_ownership(
            MaterialPreviewFactors {
                category_code: Some(15),
                category_confidence: Some(1.0),
                ..MaterialPreviewFactors::default()
            },
            &ownership,
        )
        .expect_err("category 15 is outside the shared contract");
        assert!(
            error
                .to_string()
                .contains("material category code is outside the shared CDMW contract")
        );

        assert!(SHADER.contains("min(u32(material.relief_factors.z + 0.5), 14u)"));
        for (name, code) in [("bone", 12), ("organic", 13), ("foliage", 14)] {
            assert!(
                SHADER.contains(&format!("let is_{name} = category_code == {code}u;")),
                "WGSL does not decode shared category {name}={code}"
            );
        }
        assert!(
            SHADER
                .contains("is_hair || is_stone || is_tooth || is_bone || is_organic || is_foliage")
        );
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
    fn neutral_metal_readability_uses_source_coloured_bounded_ggx_without_cue_lift() {
        assert!(SHADER.contains("fn distribution_ggx("));
        assert!(SHADER.contains("fn geometry_smith("));
        assert!(SHADER.contains("fn fresnel_schlick("));
        assert!(SHADER.contains(
            "let metal_cook_torrance = metal_distribution\n            * metal_geometry\n            * metal_fresnel"
        ));
        assert!(
            SHADER.contains("let metal_fresnel = fresnel_schlick(metal_hdotv, source_stable_f0);")
        );
        assert!(SHADER.contains("if !gltf_pbr { specular = min(specular, vec3<f32>(0.85)); }"));
        assert!(SHADER.contains("shaded_albedo * (authored_base_scale + cloth_texture_boost)"));
        assert!(SHADER.contains("has_source_base_color && (is_cloth || is_leather)"));
        assert!(
            SHADER.contains("let metal_body_scale = select(0.34, 0.20, has_source_metalness);")
        );
        assert!(
            SHADER
                .contains("diffuse += material_reference_albedo * metal_cue * 0.16 * cue_weight;")
        );
        assert!(SHADER.contains("let cue_weight = select(0.0, 1.0, showcase || game_outdoor);"));
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

        assert!(SHADER.contains("if camera.lighting_preset == 0u"));
        assert!(SHADER.contains("let mapped_luma = exposed_luma / (1.0 + exposed_luma);"));
        assert!(SHADER.contains(
            "material_reference_albedo = clamp(texel.rgb, vec3<f32>(0.0), vec3<f32>(1.0));"
        ));
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
        assert!(!SHADER.contains("textureSample(base_texture"));
        // Effect texture sampling is verified by effect_particle_proof::verify;
        // matching a shader string never proved that a particle produced pixels.
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
        assert!(SHADER.contains("sample_uv / max(material.skin_detail_scale, 0.001)"));
        assert!(SHADER.contains("skin_detail_mask_texture,"));
        assert!(SHADER.contains("MATERIAL_MIP_LOD_BIAS).r * material.skin_detail_opacity"));
        assert!(SHADER.contains("tangent_normal.xy + detail_normal.xy"));
        assert!(SHADER.contains("mix(roughness, skin_detail_surface.g, skin_detail_weight)"));
        assert!(SHADER.contains("if is_skin && !gltf_pbr {\n        metalness = 0.0;"));
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
            .find("if !has_source_roughness && !gltf_pbr {")
            .map(|offset| skin_gate + offset)
            .expect("category roughness fallback");
        let skin_response = &SHADER[skin_gate..category_fallback];
        assert!(
            skin_response
                .contains("is_skin && !gltf_pbr && (material.flags & MATERIAL_SPECULAR) != 0u")
        );
        assert!(skin_response.contains("|| has_skin_specular_response;"));
        assert!(skin_response.contains("roughness = clamp(skin_specular_response.g, 0.04, 1.0);"));
        assert!(skin_response.contains("clamp(skin_specular_response.r, 0.0, 1.0)"));
        assert!(!skin_response.contains("skin_specular_response.b"));
        assert!(SHADER.contains("* skin_subsurface_multiplier,"));
        assert!(SHADER.contains("if (material.flags & MATERIAL_SPECULAR) != 0u && !is_skin {"));
        assert!(
            SHADER.contains("let source_weight = max(metalness, select(0.0, 0.75, is_glossy));")
        );
        assert!(SHADER.contains("if is_skin && !gltf_pbr {\n        metalness = 0.0;"));
    }

    #[test]
    fn same_topology_updates_geometry_in_place_and_topology_changes_replace_buffers() {
        let current = MeshUploadKey {
            mesh_identity: 7,
            draw_revision: 10,
            topology_generation: 3,
            topology_signature: 99,
            deformation_signature: 0,
            role_signature: 0,
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
            MeshUploadKey {
                role_signature: 101,
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
        assert_eq!(scene_guide_pipeline_depth(), PipelineDepth::Test);
        assert!(!SHADER.contains("out.position.z -= out.position.w"));

        let (xray_writes_depth, xray_compare, _) = pipeline_depth_state(PipelineDepth::Ignore);
        assert!(!xray_writes_depth);
        assert_eq!(xray_compare, wgpu::CompareFunction::Always);
    }

    #[test]
    fn imported_texture_v_flip_is_owner_scoped_gpu_state() {
        let factors = MaterialPreviewFactors {
            texture_flip_vertical: Some(true),
            ..MaterialPreviewFactors::default()
        };
        assert!(validate_material_factor_ownership(factors, &[vec![0]]).is_ok());
        assert_eq!(MATERIAL_FLIP_V, 16_777_216);
        assert!(SHADER.contains("const MATERIAL_FLIP_V: u32 = 16777216u;"));
        assert!(SHADER.contains("sample_uv.y = 1.0 - sample_uv.y;"));
        assert!(SHADER.contains("textureSampleBias(base_texture, material_sampler, sample_uv"));
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
    fn one_binary_identity_supports_role_specific_sampling_views() -> Result<(), RenderError> {
        let bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        let base_color = dds_texture_identity(&bytes, TextureRole::BaseColor)?;
        let layer_mask = dds_texture_identity(&bytes, TextureRole::LayerMask)?;

        assert_eq!(base_color.source_sha256, layer_mask.source_sha256);
        assert_eq!(base_color.view_format, wgpu::TextureFormat::Rgba8UnormSrgb);
        assert_eq!(layer_mask.view_format, wgpu::TextureFormat::Rgba8Unorm);
        assert_ne!(base_color.view_format, layer_mask.view_format);
        Ok(())
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
    fn material_isolation_compacts_owned_triangles_and_preserves_the_owner() {
        let snapshot = DrawSnapshot {
            mesh_identity: 17,
            draw_revision: 4,
            topology_generation: 2,
            positions: vec![
                [-10.0, 0.0, 0.0],
                [-9.0, 0.0, 0.0],
                [-10.0, 1.0, 0.0],
                [4.0, 0.0, 0.0],
                [5.0, 0.0, 0.0],
                [4.0, 1.0, 0.0],
            ],
            normals: vec![[0.0, 0.0, 1.0]; 6],
            uvs: vec![[0.0, 0.0]; 6],
            indices: vec![0, 1, 2, 3, 4, 5],
            triangle_materials: vec![3, 7],
            selected_vertices: vec![1, 4],
            fingerprint: "two-owner".to_owned(),
        };
        let isolated = isolate_material_snapshot(&snapshot, 7).expect("material isolation");
        assert_eq!(isolated.positions, snapshot.positions[3..].to_vec());
        assert_eq!(isolated.indices, vec![0, 1, 2]);
        assert_eq!(isolated.triangle_materials, vec![7]);
        assert_eq!(isolated.selected_vertices, vec![1]);
        assert_eq!(isolated.fingerprint, "two-owner|material:7");
        assert!(isolate_material_snapshot(&snapshot, 99).is_err());
    }

    #[test]
    fn explicit_headless_capture_camera_preserves_the_requested_audit_angles() {
        let snapshot = material_proof_sphere_snapshot();
        let view = resolved_headless_capture_view(
            &snapshot,
            Some(HeadlessMaterialCaptureCamera {
                yaw_degrees: -35.0,
                pitch_degrees: 20.0,
            }),
        )
        .expect("audit camera");
        assert!((view.yaw.to_degrees() + 35.0).abs() < 1.0e-4);
        assert!((view.pitch.to_degrees() - 20.0).abs() < 1.0e-4);
        assert!(
            resolved_headless_capture_view(
                &snapshot,
                Some(HeadlessMaterialCaptureCamera {
                    yaw_degrees: 0.0,
                    pitch_degrees: 90.0,
                }),
            )
            .is_err()
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
            "textureSampleBias(\n            glossiness_texture,\n            material_sampler,\n            sample_uv,\n            MATERIAL_MIP_LOD_BIAS).r"
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
            .find("if !has_source_roughness && !gltf_pbr {")
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
    fn preview_overrides_replace_authored_fields_without_losing_other_fields() {
        let authored = [(
            MaterialPreviewFactors {
                roughness: Some(0.2),
                metalness: Some(0.8),
                ..Default::default()
            },
            vec![vec![2, 3]],
        )];
        let overrides = [(
            MaterialPreviewFactors {
                roughness: Some(0.7),
                ..Default::default()
            },
            vec![vec![2]],
        )];
        let merged = preview_material_factors(&authored, &overrides, 0).expect("valid override");
        let resolved = resolve_material_factors(merged.iter().map(|(f, o)| (*f, o.as_slice())), 0)
            .expect("one owner per material");
        assert_eq!(resolved[&2].roughness, Some(0.7));
        assert_eq!(resolved[&2].metalness, Some(0.8));
        assert_eq!(resolved[&3].roughness, Some(0.2));
        let invalid = [(
            MaterialPreviewFactors {
                roughness: Some(f32::NAN),
                ..Default::default()
            },
            vec![vec![2]],
        )];
        assert!(preview_material_factors(&authored, &invalid, 0).is_err());
        let conflicting = [
            overrides[0].clone(),
            (
                MaterialPreviewFactors {
                    roughness: Some(0.9),
                    ..Default::default()
                },
                vec![vec![2]],
            ),
        ];
        assert!(preview_material_factors(&authored, &conflicting, 0).is_err());
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
