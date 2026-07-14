static const char kShaderSourceCommon[] = R"(
cbuffer Constants : register(b0) {
    row_major float4x4 mvp;
    row_major float4x4 normal_world;
    float4 light_dir;
    float4 base_color_flip;
    float4 flags;
    float4 flags2;
    float4 material_params;
    float4 material_hints;
    float4 flags3;
    float4 render_tuning;
    float4 render_tuning2;
    float4 render_tuning3;
    float4 render_tuning4;
    float4 editor_tint;
    float4 flags4;
    float4 flags5;
    float4 emissive_params;
    float4 material_value_params;
    float4 material_color_params;
    float4 material_tint_params;
    float4 layer_params[4];
    float4 layer_tint[4];
    float4 layer_hints[4];
    float4 layer_flags[4];
};
Texture2D base_tex : register(t0);
Texture2D normal_tex : register(t1);
Texture2D material_tex : register(t2);
Texture2D occlusion_tex : register(t3);
Texture2D roughness_tex : register(t4);
Texture2D metalness_tex : register(t5);
Texture2D specular_tex : register(t6);
Texture2D height_tex : register(t7);
Texture2D detail_tex : register(t8);
Texture2D emissive_tex : register(t9);
Texture2D layer0_diffuse_tex : register(t10);
Texture2D layer1_diffuse_tex : register(t11);
Texture2D layer2_diffuse_tex : register(t12);
Texture2D layer3_diffuse_tex : register(t13);
Texture2D layer0_mask_tex : register(t14);
Texture2D layer1_mask_tex : register(t15);
Texture2D layer2_mask_tex : register(t16);
Texture2D layer3_mask_tex : register(t17);
Texture2D layer0_material_tex : register(t18);
Texture2D layer1_material_tex : register(t19);
Texture2D layer2_material_tex : register(t20);
Texture2D layer3_material_tex : register(t21);
Texture2D layer0_normal_tex : register(t22);
Texture2D layer1_normal_tex : register(t23);
Texture2D layer2_normal_tex : register(t24);
Texture2D layer3_normal_tex : register(t25);
Texture2D layer0_height_tex : register(t26);
Texture2D layer1_height_tex : register(t27);
Texture2D layer2_height_tex : register(t28);
Texture2D layer3_height_tex : register(t29);
SamplerState preview_sampler : register(s0);
struct VSIn {
    float3 position : POSITION;
    float3 normal : NORMAL;
    float3 color : COLOR0;
    float2 uv : TEXCOORD0;
    float3 tangent : TANGENT;
    float3 bitangent : BINORMAL;
};
struct VSOut {
    float4 position : SV_POSITION;
    float3 normal : NORMAL;
    float3 color : COLOR0;
    float2 uv : TEXCOORD0;
    float3 tangent : TANGENT;
    float3 bitangent : BINORMAL;
};
float3 srgb_to_linear(float3 color) {
    return pow(saturate(color), 2.2);
}
float3 linear_to_srgb(float3 color) {
    return pow(saturate(color), 1.0 / 2.2);
}
float3 aces_tonemap(float3 color) {
    color = max(color, float3(0.0, 0.0, 0.0));
    return saturate((color * (2.51 * color + 0.03)) / (color * (2.43 * color + 0.59) + 0.14));
}
float ggx_distribution(float ndoth, float roughness) {
    float a = max(roughness * roughness, 0.035);
    float a2 = a * a;
    float denom = (ndoth * ndoth) * (a2 - 1.0) + 1.0;
    return a2 / max(3.14159265 * denom * denom, 0.0001);
}
float geometry_schlick_ggx(float ndotv, float roughness) {
    float r = roughness + 1.0;
    float k = (r * r) * 0.125;
    return ndotv / max(ndotv * (1.0 - k) + k, 0.0001);
}
float geometry_smith(float ndotv, float ndotl, float roughness) {
    return geometry_schlick_ggx(ndotv, roughness) * geometry_schlick_ggx(ndotl, roughness);
}
float3 fresnel_schlick(float costheta, float3 f0) {
    return f0 + (1.0 - f0) * pow(1.0 - saturate(costheta), 5.0);
}
float preview_environment_intensity(float3 reflected_view, float roughness) {
    float env_lobe = saturate((reflected_view.y * 0.55) + (reflected_view.z * -0.14) + 0.58);
    float horizon_band = pow(saturate(1.0 - abs(reflected_view.y) * 1.12), 2.2);
    float front_softbox = pow(saturate(dot(reflected_view, normalize(float3(-0.18, 0.36, -0.92)))), lerp(14.0, 4.0, roughness));
    float top_softbox = pow(saturate(dot(reflected_view, normalize(float3(-0.32, 0.88, -0.34)))), lerp(28.0, 7.0, roughness));
    float side_softbox = pow(saturate(dot(reflected_view, normalize(float3(0.82, 0.20, -0.54)))), lerp(18.0, 5.0, roughness));
    float back_softbox = pow(saturate(dot(reflected_view, normalize(float3(-0.72, 0.26, 0.64)))), lerp(18.0, 5.0, roughness));
    float opposite_softbox = pow(saturate(dot(reflected_view, normalize(float3(0.58, 0.30, 0.76)))), lerp(20.0, 6.0, roughness));
    float dark_band = pow(saturate(1.0 - abs(reflected_view.x * 1.8 + reflected_view.y * 0.35)), 3.2) * saturate(0.85 - reflected_view.z);
    float intensity = lerp(0.48, 0.52, env_lobe);
    intensity *= lerp(1.0, 0.96, dark_band * (1.0 - roughness));
    intensity += horizon_band * 0.025;
    intensity += front_softbox * 0.04;
    intensity += top_softbox * 0.03;
    intensity += side_softbox * 0.025;
    intensity += back_softbox * 0.02;
    intensity += opposite_softbox * 0.018;
    return clamp(intensity, 0.46, 0.60);
}
float3 source_stable_fresnel(float costheta, float3 f0, float metallic) {
    float3 physical_fresnel = fresnel_schlick(costheta, f0);
    return lerp(physical_fresnel, f0, saturate(metallic * 0.88));
}
float wrapped_ndotl(float3 normal_value, float3 light_value, float wrap_amount) {
    float wrap = saturate(wrap_amount);
    return saturate((dot(normalize(normal_value), normalize(light_value)) + wrap) / (1.0 + wrap));
}
VSOut vs_main(VSIn input) {
    VSOut output;
    output.position = mul(float4(input.position, 1.0), mvp);
    output.normal = normalize(mul(float4(input.normal, 0.0), normal_world).xyz);
    output.color = input.color;
    output.uv = input.uv;
    output.tangent = normalize(mul(float4(input.tangent, 0.0), normal_world).xyz);
    output.bitangent = normalize(mul(float4(input.bitangent, 0.0), normal_world).xyz);
    return output;
}
float select_mask_channel(float4 sample_value, float channel_value) {
    int mask_channel = (int)round(saturate(channel_value / 3.0) * 3.0);
    return mask_channel == 1 ? sample_value.g : (mask_channel == 2 ? sample_value.b : (mask_channel == 3 ? sample_value.a : sample_value.r));
}
float3 blend_sampled_normal(float3 base_n, float3 tangent, float3 bitangent, float3 sampled, float strength, float invert_y) {
    float2 xy = sampled.xy * 2.0 - 1.0;
    if (invert_y > 0.5) {
        xy.y = -xy.y;
    }
    float z = sqrt(saturate(1.0 - dot(xy, xy)));
    float3 mapped = normalize(float3(xy, z));
    float3 normal_mapped = normalize(tangent * mapped.x + bitangent * mapped.y + base_n * mapped.z);
    return normalize(lerp(base_n, normal_mapped, saturate(strength)));
}
)";

static const char kShaderSourcePixelMaterial[] = R"(
float4 ps_main(VSOut input) : SV_TARGET {
    float2 uv = input.uv;
    if (base_color_flip.w > 0.5) {
        uv.y = 1.0 - uv.y;
    }
    uv *= max(material_value_params.xy, float2(0.05, 0.05));
    float preview_brightness = max(material_value_params.z, 0.1);
    float preview_contrast = max(material_color_params.x, 0.01);
    float preview_saturation = max(material_color_params.y, 0.0);
    float preview_gamma = max(material_color_params.z, 0.01);
    float3 preview_tint_color = max(material_tint_params.rgb, float3(0.0, 0.0, 0.0));
    float3 albedo = srgb_to_linear(max(input.color, base_color_flip.rgb));
    float base_alpha = 1.0;
    float early_category_code = flags5.x;
    bool early_category_metal = early_category_code > 0.5 && early_category_code < 1.5;
    if (flags.x > 0.5) {
        float4 base_sample = base_tex.Sample(preview_sampler, uv);
        albedo = saturate(base_sample.rgb);
        base_alpha = base_sample.a;
        if (flags4.x > 0.001) {
            float3 preview_tint = saturate(base_color_flip.rgb);
            float tint_luma = max(dot(preview_tint, float3(0.299, 0.587, 0.114)), 0.08);
            float3 tint_bias = clamp(preview_tint / tint_luma, float3(0.38, 0.38, 0.38), float3(1.72, 1.72, 1.72));
            float tint_chroma = max(preview_tint.r, max(preview_tint.g, preview_tint.b)) - min(preview_tint.r, min(preview_tint.g, preview_tint.b));
            float neutral_metal_tint = early_category_metal ? saturate((0.12 - tint_chroma) * 8.0) : 0.0;
            float strength = saturate(flags4.x * (early_category_metal ? lerp(0.05, 1.25, neutral_metal_tint) : 1.0));
            float albedo_luma = dot(albedo, float3(0.299, 0.587, 0.114));
            float lifted_luma = saturate(albedo_luma * (1.05 + strength * 0.35) + 0.10 * strength);
            float3 multiplied = saturate(albedo * tint_bias);
            float3 colorized = saturate(lifted_luma.xxx * tint_bias);
            float neutral_metal_luma = saturate(albedo_luma * (0.55 + tint_luma * 0.45) + 0.012);
            colorized = lerp(colorized, saturate(neutral_metal_luma.xxx * tint_bias), neutral_metal_tint);
            float colorize_strength = lerp(0.58, 0.96, neutral_metal_tint);
            albedo = lerp(albedo, lerp(multiplied, colorized, colorize_strength), strength);
        }
    }
    albedo = saturate(albedo * preview_brightness);
    albedo *= preview_tint_color;
    float albedo_luma_adjusted = dot(albedo, float3(0.299, 0.587, 0.114));
    albedo = saturate(albedo_luma_adjusted.xxx + (albedo - albedo_luma_adjusted.xxx) * preview_saturation);
    albedo = saturate((albedo - 0.5) * preview_contrast + 0.5);
    if (abs(preview_gamma - 1.0) > 0.001) {
        albedo = pow(saturate(albedo), float3(preview_gamma, preview_gamma, preview_gamma));
    }
    albedo = max(albedo, float3(0.012, 0.012, 0.012));
    if (flags3.z > 0.5 && base_alpha < max(flags3.w, 0.001)) {
        discard;
    }
    float debug_mode = flags4.y;
    if (debug_mode > 1.5 && debug_mode < 2.5) {
        float2 checker_uv = frac(uv * 16.0);
        float checker = abs((checker_uv.x > 0.5 ? 1.0 : 0.0) - (checker_uv.y > 0.5 ? 1.0 : 0.0));
        return float4(lerp(float3(0.04, 0.05, 0.06), float3(0.78, 0.88, 1.0), checker), 1.0);
    }
    if (debug_mode > 0.5 && debug_mode < 1.5) {
        float3 inspection_albedo = saturate(albedo * 1.18 + float3(0.018, 0.018, 0.018));
        return float4(linear_to_srgb(inspection_albedo), 1.0);
    }
    if (debug_mode > 2.5 && debug_mode < 3.5) {
        return float4(base_alpha.xxx, 1.0);
    }
    if (debug_mode > 3.5 && debug_mode < 4.5) {
        float seed = frac(flags4.z * 0.6180339 + 0.17);
        return float4(frac(seed + 0.23), frac(seed * 2.31 + 0.47), frac(seed * 3.73 + 0.71), 1.0);
    }
    float layer_alpha[4] = {0.0, 0.0, 0.0, 0.0};
#define APPLY_ALBEDO_LAYER(ID, DIFFUSE_TEX, MASK_TEX) \
    if (layer_flags[ID].x > 0.5) { \
        float4 mask_sample = float4(1.0, 1.0, 1.0, 1.0); \
        if (layer_flags[ID].y > 0.5) { \
            mask_sample = MASK_TEX.Sample(preview_sampler, uv); \
        } \
        float mask_value = select_mask_channel(mask_sample, layer_params[ID].x); \
        float tint_alpha = saturate(layer_tint[ID].a) * (early_category_metal ? 0.18 : 1.0); \
        layer_alpha[ID] = saturate(mask_value * layer_params[ID].y * tint_alpha); \
        float3 layer_sample = DIFFUSE_TEX.Sample(preview_sampler, uv).rgb; \
        float3 layer_tint_rgb = saturate(layer_tint[ID].rgb); \
        float layer_tint_luma = max(dot(layer_tint_rgb, float3(0.299, 0.587, 0.114)), 0.08); \
        float3 layer_tint_bias = clamp(layer_tint_rgb / layer_tint_luma, float3(0.32, 0.32, 0.32), float3(2.15, 2.15, 2.15)); \
        float layer_luma = dot(layer_sample, float3(0.299, 0.587, 0.114)); \
        float layer_lifted_luma = saturate(layer_luma * (1.08 + layer_params[ID].y * 0.24) + 0.06 * layer_params[ID].y); \
        float3 layer_multiplied = saturate(layer_sample * layer_tint_bias); \
        float3 layer_colorized = saturate(layer_lifted_luma.xxx * layer_tint_bias); \
        float layer_chroma = max(layer_tint_rgb.r, max(layer_tint_rgb.g, layer_tint_rgb.b)) - min(layer_tint_rgb.r, min(layer_tint_rgb.g, layer_tint_rgb.b)); \
        float layer_colorize_strength = saturate(0.18 + layer_chroma * 1.35) * (early_category_metal ? 0.08 : 1.0); \
        float strong_dye_strength = saturate((layer_chroma - 0.38) * 1.65) * (early_category_metal ? 0.05 : 1.0); \
        float3 dye_authority_color = saturate(layer_tint_rgb * (0.62 + layer_lifted_luma * 0.70)); \
        layer_alpha[ID] = saturate(layer_alpha[ID] * (1.0 + strong_dye_strength * 0.35)); \
        float3 layer_color = lerp(lerp(layer_multiplied, layer_colorized, layer_colorize_strength), dye_authority_color, strong_dye_strength); \
        albedo = lerp(albedo, layer_color, layer_alpha[ID]); \
    }
    APPLY_ALBEDO_LAYER(0, layer0_diffuse_tex, layer0_mask_tex)
    APPLY_ALBEDO_LAYER(1, layer1_diffuse_tex, layer1_mask_tex)
    APPLY_ALBEDO_LAYER(2, layer2_diffuse_tex, layer2_mask_tex)
    APPLY_ALBEDO_LAYER(3, layer3_diffuse_tex, layer3_mask_tex)
#undef APPLY_ALBEDO_LAYER
    if (debug_mode > 6.5 && debug_mode < 7.5) {
        return float4(layer_alpha[0], layer_alpha[1], layer_alpha[2], 1.0);
    }
    float3 n = normalize(input.normal);
    float3 t = input.tangent;
    float3 b = input.bitangent;
    if (dot(t, t) < 1e-5) {
        t = float3(1.0, 0.0, 0.0);
    } else {
        t = normalize(t);
    }
    if (dot(b, b) < 1e-5) {
        b = normalize(cross(n, t));
    } else {
        b = normalize(b);
    }
    if (flags.y > 0.5) {
        float3 sampled = normal_tex.Sample(preview_sampler, uv).xyz;
        float2 xy = sampled.xy * 2.0 - 1.0;
        if (flags3.y > 0.5) {
            xy.y = -xy.y;
        }
        float z = sqrt(saturate(1.0 - dot(xy, xy)));
        float3 mapped = normalize(float3(xy, z));
        float3 normal_mapped = normalize(t * mapped.x + b * mapped.y + n * mapped.z);
        n = normalize(lerp(n, normal_mapped, saturate(material_params.x)));
    }
#define APPLY_NORMAL_LAYER(ID, NORMAL_TEX) \
    if (layer_flags[ID].w > 0.5 && layer_alpha[ID] > 0.001) { \
        n = blend_sampled_normal(n, t, b, NORMAL_TEX.Sample(preview_sampler, uv).xyz, material_params.x * layer_alpha[ID] * 0.65, flags3.y); \
    }
    APPLY_NORMAL_LAYER(0, layer0_normal_tex)
    APPLY_NORMAL_LAYER(1, layer1_normal_tex)
    APPLY_NORMAL_LAYER(2, layer2_normal_tex)
    APPLY_NORMAL_LAYER(3, layer3_normal_tex)
#undef APPLY_NORMAL_LAYER
    if (debug_mode > 4.5 && debug_mode < 5.5) {
        return float4(n * 0.5 + 0.5, 1.0);
    }
    float ao = 1.0;
    float roughness = 0.55;
    float specular = 0.15;
    float metalness = 0.0;
    float user_metalness_scale = max(render_tuning3.z, 0.0);
    bool explicit_material_authority_hint = material_hints.x > 0.02 || material_hints.y > 0.02 || material_hints.z > 0.02 || material_hints.w > 0.02;
    if (material_hints.x > 0.02) {
        roughness = lerp(roughness, material_hints.x, 0.72);
    }
    if (material_hints.y > 0.02) {
        metalness = max(metalness, saturate(material_hints.y * user_metalness_scale));
    }
    if (material_hints.z > 0.02) {
        specular = max(specular, material_hints.z);
    }
    float family_code = flags4.w;
    float category_code = flags5.x;
    float category_confidence = saturate(flags5.y);
    bool category_metal = category_code > 0.5 && category_code < 1.5;
    bool category_leather = category_code > 1.5 && category_code < 2.5;
    bool category_wood = category_code > 2.5 && category_code < 3.5;
    bool category_cloth = category_code > 3.5 && category_code < 4.5;
    bool category_skin = category_code > 4.5 && category_code < 5.5;
    bool category_hair = category_code > 5.5 && category_code < 6.5;
    bool category_glass = category_code > 6.5 && category_code < 7.5;
    bool category_gem = category_code > 7.5 && category_code < 8.5;
    bool category_stone = category_code > 8.5 && category_code < 9.5;
    bool category_eye = category_code > 9.5 && category_code < 10.5;
    bool category_tooth = category_code > 10.5 && category_code < 11.5;
    bool glossy_nonmetal = category_glass || category_gem || category_eye;
    bool conservative_nonmetal = category_leather || category_wood || category_cloth || category_skin || category_hair || category_stone || category_tooth;
    bool known_nonmetal = conservative_nonmetal || glossy_nonmetal;
    float metal_scale = 1.0;
    float specular_scale = 1.0;
    float roughness_bias = 0.0;
)" R"(
    if (family_code > 0.5 && family_code < 1.5) {
        metal_scale = 0.12;
        specular_scale = 1.20;
        roughness_bias = 0.06;
    } else if (family_code > 1.5 && family_code < 2.5) {
        metal_scale = 0.05;
        specular_scale = 1.45;
        roughness_bias = -0.08;
    } else if (family_code > 2.5 && family_code < 3.5) {
        metal_scale = 0.28;
        specular_scale = 0.95;
        roughness_bias = 0.10;
    } else if (family_code > 3.5 && family_code < 4.5) {
        metal_scale = 1.15;
        specular_scale = 1.35;
        roughness_bias = -0.04;
    } else if (family_code > 4.5 && family_code < 5.5) {
        metal_scale = 1.05;
        specular_scale = 1.20;
        roughness_bias = -0.02;
    } else if (family_code > 5.5 && family_code < 6.5) {
        metal_scale = 0.55;
        specular_scale = 1.15;
        roughness_bias = -0.03;
    }
    float category_metal_cap = category_metal ? 1.0 : (known_nonmetal ? 0.0 : lerp(0.12, 0.32, category_confidence));
    float category_specular_cap = category_metal ? 1.0 : (category_glass ? 0.42 : (category_gem ? 0.48 : (category_eye ? 0.44 : (category_leather ? 0.14 : (category_wood ? 0.16 : (category_cloth ? 0.055 : (category_skin ? 0.20 : (category_hair ? 0.22 : (category_stone ? 0.10 : (category_tooth ? 0.18 : 0.18))))))))));
    float category_env_scale = category_metal ? 0.94 : (category_glass ? 0.26 : (category_gem ? 0.30 : (category_eye ? 0.24 : (category_leather ? 0.06 : (category_wood ? 0.06 : (category_cloth ? 0.025 : (category_skin ? 0.075 : (category_hair ? 0.08 : (category_stone ? 0.04 : (category_tooth ? 0.08 : 0.08))))))))));
    float category_roughness_floor = category_metal ? 0.16 : (category_glass ? 0.30 : (category_gem ? 0.26 : (category_eye ? 0.30 : (category_leather ? 0.76 : (category_wood ? 0.70 : (category_cloth ? 0.84 : (category_skin ? 0.58 : (category_hair ? 0.64 : (category_stone ? 0.82 : (category_tooth ? 0.58 : 0.66))))))))));
    if (explicit_material_authority_hint && !conservative_nonmetal) {
        float gloss_hint = saturate((1.0 - material_hints.x) * 0.85 + material_hints.z * 0.45);
        category_specular_cap = max(category_specular_cap, max(material_hints.z, gloss_hint));
        category_env_scale = max(category_env_scale, lerp(0.12, 0.42, gloss_hint));
        category_roughness_floor = min(category_roughness_floor, lerp(0.08, 0.42, saturate(material_hints.x)));
    }
    float category_metal_fallback = category_metal ? saturate(lerp(0.28, 0.62, category_confidence) * user_metalness_scale) : 0.0;
    if (category_metal && material_hints.y <= 0.02 && flags.z <= 0.5 && flags2.z <= 0.5) {
        metalness = max(metalness, category_metal_fallback);
        specular = max(specular, lerp(0.34, 0.62, category_confidence));
        roughness = min(roughness, lerp(0.46, 0.28, category_confidence));
    }
    metal_scale *= user_metalness_scale * category_metal_cap;
    specular_scale *= category_specular_cap;
    if (conservative_nonmetal) {
        roughness = max(roughness, category_roughness_floor);
        specular = min(specular, 0.28 * max(category_specular_cap, 0.20));
    }
    if (!conservative_nonmetal) {
        specular = max(specular, render_tuning.z);
    }
    if (flags.z > 0.5) {
        float4 m = material_tex.Sample(preview_sampler, uv);
        ao = min(ao, max(category_skin ? 0.72 : 0.58, m.r));
        roughness = saturate(m.g);
        metalness = max(metalness, saturate(m.b) * (category_metal ? 0.96 : 0.65) * metal_scale);
        specular = saturate(max(m.a, m.b * 0.55) * specular_scale);
    }
    if (flags2.x > 0.5) {
        ao = min(ao, max(category_skin ? 0.72 : 0.58, occlusion_tex.Sample(preview_sampler, uv).r));
    }
    if (flags2.y > 0.5) {
        roughness = saturate(roughness_tex.Sample(preview_sampler, uv).r);
    }
    if (flags2.z > 0.5) {
        metalness = saturate(metalness_tex.Sample(preview_sampler, uv).r * metal_scale);
    }
    if (flags2.w > 0.5) {
        float3 spec_sample = specular_tex.Sample(preview_sampler, uv).rgb;
        float spec_value = max(spec_sample.r, max(spec_sample.g, spec_sample.b));
        specular = saturate(max(specular, spec_value * 0.88 * specular_scale));
        if (flags2.y < 0.5) {
            roughness = min(roughness, lerp(0.72, 0.24, spec_value));
        }
    }
    if (flags3.x > 0.5) {
        float3 detail_sample = detail_tex.Sample(preview_sampler, uv).rgb;
        float detail_value = max(detail_sample.r, max(detail_sample.g, detail_sample.b));
        roughness = saturate(lerp(roughness, roughness * (0.86 + detail_value * 0.30), 0.36));
        if (flags2.w < 0.5) {
            specular = saturate(max(specular, detail_value * 0.16));
        }
    }
#define APPLY_MATERIAL_LAYER(ID, MATERIAL_TEX) \
    if (layer_flags[ID].z > 0.5 && layer_alpha[ID] > 0.001) { \
        float4 lm = MATERIAL_TEX.Sample(preview_sampler, uv); \
        roughness = lerp(roughness, saturate(max(lm.g, layer_hints[ID].x)), saturate(layer_alpha[ID] * 0.58)); \
        metalness = max(metalness, saturate(max(lm.b * 0.72, layer_hints[ID].y) * metal_scale) * layer_alpha[ID]); \
        specular = max(specular, saturate(max(max(lm.a, lm.b * 0.55), layer_hints[ID].z) * specular_scale) * layer_alpha[ID]); \
    }
    APPLY_MATERIAL_LAYER(0, layer0_material_tex)
    APPLY_MATERIAL_LAYER(1, layer1_material_tex)
    APPLY_MATERIAL_LAYER(2, layer2_material_tex)
    APPLY_MATERIAL_LAYER(3, layer3_material_tex)
#undef APPLY_MATERIAL_LAYER
    if (explicit_material_authority_hint) {
        if (material_hints.x > 0.02) {
            roughness = lerp(roughness, material_hints.x, 0.55);
        }
        if (material_hints.z > 0.02) {
            specular = max(specular, material_hints.z);
        }
    }
    if (debug_mode > 5.5 && debug_mode < 6.5) {
        return float4(saturate(ao), saturate(roughness), saturate(specular), 1.0);
    }
    bool promoted_material_response = flags5.z > 0.5;
    bool direct_metal_response = category_metal && (metalness > 0.12 || material_hints.y > 0.16 || flags2.z > 0.5 || promoted_material_response);
    if (direct_metal_response) {
        category_metal_cap = max(category_metal_cap, 0.96);
        category_env_scale = max(category_env_scale, 0.86);
        category_specular_cap = max(category_specular_cap, 0.82);
        category_roughness_floor = min(category_roughness_floor, 0.08);
        metalness = max(metalness, category_metal_fallback);
        specular = max(specular, lerp(0.42, 0.72, category_confidence));
        roughness = min(roughness, lerp(0.34, 0.16, category_confidence));
    }
    roughness = saturate(roughness + roughness_bias + render_tuning3.y);
    roughness = max(roughness, category_roughness_floor);
    metalness = min(metalness, category_metal_cap);
    ao = saturate(1.0 - ((1.0 - ao) * render_tuning3.x));
    float nonmetal_specular_cap = conservative_nonmetal ? category_specular_cap : max(0.18, category_specular_cap);
    specular = min(specular, min(max(max(render_tuning.w, render_tuning.z), lerp(0.30, 0.92, metalness)), category_metal ? 0.96 : nonmetal_specular_cap));
    float height_value = 0.5;
    if (flags.w > 0.5) {
        height_value = height_tex.Sample(preview_sampler, uv).r;
        float2 duv_x = ddx(uv);
        float2 duv_y = ddy(uv);
        if (dot(duv_x, duv_x) < 1e-8) {
            duv_x = float2(1.0 / 1024.0, 0.0);
        }
        if (dot(duv_y, duv_y) < 1e-8) {
            duv_y = float2(0.0, 1.0 / 1024.0);
        }
        float hx = height_tex.Sample(preview_sampler, uv + duv_x).r - height_tex.Sample(preview_sampler, uv - duv_x).r;
        float hy = height_tex.Sample(preview_sampler, uv + duv_y).r - height_tex.Sample(preview_sampler, uv - duv_y).r;
        float height_strength = saturate((material_params.y + material_hints.w * 0.04) * 8.0);
        float3 height_normal = normalize(n - t * hx * height_strength * 2.4 + b * hy * height_strength * 2.4);
        n = normalize(lerp(n, height_normal, height_strength));
        float relief = (height_value - 0.5) * saturate(material_params.y * 10.0);
        roughness = saturate(roughness - relief * 0.10);
    }
#define APPLY_HEIGHT_LAYER(ID, HEIGHT_TEX) \
    if (layer_params[ID].z > 0.5 && layer_alpha[ID] > 0.001) { \
        float layer_height_value = HEIGHT_TEX.Sample(preview_sampler, uv).r; \
        height_value = lerp(height_value, layer_height_value, layer_alpha[ID]); \
        roughness = saturate(roughness - (layer_height_value - 0.5) * saturate(layer_hints[ID].w * layer_alpha[ID]) * 0.12); \
    }
    APPLY_HEIGHT_LAYER(0, layer0_height_tex)
    APPLY_HEIGHT_LAYER(1, layer1_height_tex)
    APPLY_HEIGHT_LAYER(2, layer2_height_tex)
    APPLY_HEIGHT_LAYER(3, layer3_height_tex)
#undef APPLY_HEIGHT_LAYER
    if (conservative_nonmetal) {
        roughness = max(roughness, category_roughness_floor);
        metalness = min(metalness, category_metal_cap);
        specular = min(specular, category_specular_cap);
    }
    if (debug_mode > 7.5 && debug_mode < 8.5) {
        return float4(saturate(metalness).xxx, 1.0);
    }
    if (debug_mode > 8.5 && debug_mode < 9.5) {
        return float4(saturate(roughness).xxx, 1.0);
    }
    if (debug_mode > 9.5 && debug_mode < 10.5) {
        return float4(saturate(specular), saturate(1.0 - roughness), saturate(metalness), 1.0);
    }
)";

static const char kShaderSourcePixelLighting[] = R"(
    roughness = clamp(roughness, 0.035, 0.98);
    float smoothness = saturate(1.0 - roughness);
    float texture_luma = dot(albedo, float3(0.299, 0.587, 0.114));
    float ao_weight = saturate(render_tuning3.x) * (category_metal ? 1.00 : (glossy_nonmetal ? 0.82 : (category_skin ? 0.58 : (conservative_nonmetal ? 0.62 : 0.78))));
    float stable_ao = lerp(1.0, saturate(ao), ao_weight);
    float lift = category_metal ? 0.020 : (category_skin ? 0.025 : (category_hair ? 0.035 : 0.030));
    float cloth_high_luma_guard = category_cloth ? saturate((texture_luma - 0.82) * 4.0) : 0.0;
    float cloth_texture_boost = category_cloth ? lerp(0.03, -0.02, cloth_high_luma_guard) : 0.0;
    float3 material_reference_albedo = saturate(albedo * (1.03 + cloth_texture_boost) + lift.xxx * saturate(1.0 - texture_luma));
    if (category_skin) {
        material_reference_albedo = saturate(material_reference_albedo * 1.04 + float3(0.004, 0.002, 0.001));
    }
    if (category_cloth && cloth_high_luma_guard > 0.001) {
        float3 cloth_highlight_cap = float3(0.94, 0.91, 0.84);
        material_reference_albedo = lerp(material_reference_albedo, min(material_reference_albedo, cloth_highlight_cap), cloth_high_luma_guard * 0.35);
    }
    if (material_hints.w > 0.02 && flags.w <= 0.5) {
        float relief_edge = saturate((abs(ddx(texture_luma)) + abs(ddy(texture_luma))) * 34.0);
        material_reference_albedo = saturate(
            material_reference_albedo * (1.0 + relief_edge * saturate(material_hints.w) * 0.24)
            - (1.0 - relief_edge) * saturate(material_hints.w) * 0.018);
    }
    if (explicit_material_authority_hint && material_hints.x > 0.62 && !conservative_nonmetal) {
        float matte_preview = saturate((material_hints.x - 0.62) * 2.63);
        float luma = dot(material_reference_albedo, float3(0.299, 0.587, 0.114));
        float3 flattened = lerp(material_reference_albedo, luma.xxx, 0.42);
        material_reference_albedo = lerp(material_reference_albedo, flattened * 0.88 + 0.018.xxx, matte_preview * 0.58);
    }
    if (category_metal) {
        float3 metal_tint = saturate(base_color_flip.rgb);
        float metal_tint_luma = max(dot(metal_tint, float3(0.299, 0.587, 0.114)), 0.08);
        float3 metal_tint_bias = clamp(metal_tint / metal_tint_luma, float3(0.58, 0.58, 0.58), float3(1.42, 1.42, 1.42));
        material_reference_albedo = saturate(lerp(material_reference_albedo, material_reference_albedo * metal_tint_bias, 0.34));
    }
    float3 view_dir = normalize(float3(0.0, 0.0, -1.0));
    float3 key_dir = normalize(light_dir.xyz);
    float3 fill_dir = normalize(float3(-key_dir.x * 0.55, 0.55, -0.80));
    float3 half_dir = normalize(key_dir + view_dir);
    float key_light = wrapped_ndotl(n, key_dir, render_tuning2.z);
    float fill_light = wrapped_ndotl(n, fill_dir, 0.82);
    float camera_shape = saturate(abs(dot(n, view_dir)));
    float rim_shape = pow(saturate(1.0 - camera_shape), lerp(2.4, 1.2, smoothness));
    float ambient_floor = category_metal ? 0.24 : (category_skin ? 0.60 : (conservative_nonmetal ? 0.58 : 0.52));
    float diffuse_depth = saturate(ambient_floor * render_tuning.x + render_tuning.y * (key_light * 0.58 + fill_light * 0.30 + rim_shape * 0.12));
    float depth_authority = category_metal ? 1.00 : (glossy_nonmetal ? 0.72 : (category_skin ? 0.40 : (category_hair ? 0.38 : (category_cloth ? 0.46 : (category_leather ? 0.52 : 0.50)))));
    diffuse_depth = lerp(1.0, diffuse_depth, depth_authority);
    float metal_cue = category_metal ? saturate(metalness * lerp(0.18, 0.58, smoothness)) : 0.0;
    float glossy_cue = glossy_nonmetal ? saturate(specular * lerp(0.06, 0.20, smoothness)) : 0.0;
    float authority_gloss_cue = (explicit_material_authority_hint && !conservative_nonmetal)
        ? saturate((1.0 - material_hints.x) * 0.55 + material_hints.z * 0.75 + material_hints.y * 0.35)
        : 0.0;
    float nonmetal_texture_scale = conservative_nonmetal ? 1.03 : 1.0;
    float metal_strength = category_metal ? saturate(metalness) : 0.0;
    float metal_diffuse_scale = lerp(1.0, 0.34, metal_strength);
    float3 color = material_reference_albedo * stable_ao * nonmetal_texture_scale * diffuse_depth * metal_diffuse_scale;
    color += material_reference_albedo * metal_cue * 0.16;
    color += material_reference_albedo * metal_strength * stable_ao
        * (0.14 + roughness * 0.06 + (1.0 - camera_shape) * 0.30);
    color += material_reference_albedo * glossy_cue * 0.22;
    color += material_reference_albedo * authority_gloss_cue * (0.035 + rim_shape * 0.16);
    float ndotv = saturate(camera_shape);
    float ndoth = saturate(dot(n, half_dir));
    float spec_power = lerp(render_tuning2.x, render_tuning2.y, smoothness);
    float direct_lobe = pow(ndoth, spec_power) * saturate(key_light * 1.25);
    float broad_metal_lobe = category_metal ? pow(ndoth, lerp(7.0, 22.0, smoothness)) * saturate(key_light * 0.85 + rim_shape * 0.45) : 0.0;
    float3 f0 = lerp(float3(0.035, 0.035, 0.035), material_reference_albedo, saturate(metalness));
    float3 direct_specular = source_stable_fresnel(ndotv, f0, metalness) * (direct_lobe + broad_metal_lobe * 1.05) * render_tuning.w;
    float direct_specular_scale = category_metal ? (0.45 + metalness * 0.30) : (glossy_nonmetal ? 0.18 : (conservative_nonmetal ? 0.025 : 0.08));
    color += direct_specular * direct_specular_scale;
    float3 reflected_view = normalize(reflect(-view_dir, n));
    float env_reflection = preview_environment_intensity(reflected_view, roughness);
    float env_material_scale = category_metal ? (0.55 + metalness * lerp(0.45, 1.10, smoothness)) : (glossy_nonmetal ? 0.18 : (conservative_nonmetal ? 0.018 : 0.08));
    env_material_scale = max(env_material_scale, authority_gloss_cue * 0.32);
    float3 env_fresnel = source_stable_fresnel(ndotv, f0, metalness);
    color += env_reflection * env_fresnel * render_tuning3.w * category_env_scale * env_material_scale;
    if (emissive_params.a > 0.001) {
        float encoded_emissive = emissive_params.a;
        bool has_emissive_tex = encoded_emissive > 1.5;
        float emissive_intensity = saturate(has_emissive_tex ? encoded_emissive - 2.0 : encoded_emissive);
        float emissive_mask = 1.0;
        float3 emissive_color = emissive_params.rgb;
        if (has_emissive_tex) {
            float4 emissive_sample = emissive_tex.Sample(preview_sampler, uv);
            emissive_mask = max(emissive_sample.r, max(emissive_sample.g, emissive_sample.b));
            emissive_color = max(emissive_color, emissive_sample.rgb);
        }
        float emissive_strength = emissive_intensity * saturate(emissive_mask) * render_tuning4.x;
        color += emissive_color * emissive_strength * 0.85;
    }
    color = lerp(color, editor_tint.rgb, saturate(editor_tint.a));
    float tone_exposure = max(render_tuning4.y, 0.05);
    float tone_contrast = max(render_tuning4.z, 0.10);
    float tone_gamma = max(render_tuning4.w, 0.20);
    float3 exposed = max(color * tone_exposure, float3(0.0, 0.0, 0.0));
    float exposed_luma = dot(exposed, float3(0.2126, 0.7152, 0.0722));
    float mapped_luma = aces_tonemap(exposed_luma.xxx).r;
    float3 mapped = exposed * (mapped_luma / max(exposed_luma, 0.00001));
    float current_luma = dot(mapped, float3(0.2126, 0.7152, 0.0722));
    float contrasted_luma = (current_luma - 0.5) * tone_contrast + 0.5;
    contrasted_luma = max(contrasted_luma, current_luma * 0.55);
    mapped *= max(contrasted_luma, 0.0) / max(current_luma, 0.00001);
    mapped = saturate(mapped);
    mapped = pow(mapped, float3(tone_gamma, tone_gamma, tone_gamma));
    return float4(linear_to_srgb(mapped), 1.0);
}
)";

static const std::string& shader_source() {
    static const std::string source =
        std::string(kShaderSourceCommon) + kShaderSourcePixelMaterial + kShaderSourcePixelLighting;
    return source;
}

static const std::string& kShaderSource = shader_source();

static const char* kVertexDotShaderSource = R"(
struct DotIn {
    float3 center : TEXCOORD0;
    float2 radius : TEXCOORD1;
    float4 color : COLOR0;
};
struct DotOut {
    float4 position : SV_POSITION;
    float4 color : COLOR0;
    float2 local : TEXCOORD0;
};
DotOut vs_dot(uint vertex_id : SV_VertexID, DotIn input) {
    float2 corners[6] = {
        float2(-1.0, -1.0), float2( 1.0, -1.0), float2( 1.0,  1.0),
        float2(-1.0, -1.0), float2( 1.0,  1.0), float2(-1.0,  1.0)
    };
    float2 local = corners[vertex_id];
    DotOut output;
    output.position = float4(input.center.xy + local * input.radius, input.center.z, 1.0);
    output.color = input.color;
    output.local = local;
    return output;
}
float4 ps_dot(DotOut input) : SV_Target {
    if (dot(input.local, input.local) > 1.0) discard;
    return input.color;
}
)";

static const char* kOverlayPixelShaderSource = R"(
float4 ps_overlay(VSOut input) : SV_Target {
    return float4(saturate(input.color), 1.0);
}
)";
