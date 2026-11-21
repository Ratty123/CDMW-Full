struct StudioTerms {
    direct_diffuse: vec3<f32>,
    direct_specular: vec3<f32>,
    indirect_diffuse: vec3<f32>,
    indirect_specular: vec3<f32>,
};

struct StudioSurface {
    albedo: vec3<f32>,
    normal: vec3<f32>,
    geo_normal: vec3<f32>,
    view: vec3<f32>,
    tangent: vec3<f32>,
    bitangent: vec3<f32>,
    roughness: f32,
    metalness: f32,
    specular: f32,
    occlusion: f32,
    sss_strength: f32,
    is_skin: bool,
    is_hair: bool,
    is_cloth: bool,
    is_leather: bool,
    is_eye: bool,
    is_aniso: bool,
    outdoor: bool,
    shadow: f32,
};

fn studio_sg_convolve(R: vec3<f32>, axis: vec3<f32>, sharpness: f32, kernel: f32, radiance: vec3<f32>) -> vec3<f32> {
    let blurred = sharpness * kernel / (sharpness + kernel);
    let integral_ratio = (blurred / sharpness)
        * ((1.0 - exp(-2.0 * sharpness)) / max(1.0 - exp(-2.0 * blurred), 1e-5));
    return radiance * integral_ratio * exp(blurred * (dot(R, axis) - 1.0));
}

// Analytical HDR fallback used only when the device texture limit is below 18.
fn studio_hdr_environment(R: vec3<f32>, rough: f32, outdoor: bool) -> vec3<f32> {
    let alpha = max(rough * rough, 0.0025);
    let kernel = 0.5 / max(alpha * alpha, 1e-5);
    let blur = clamp(rough * rough, 0.0, 1.0);

    if outdoor {
        let horizon = exp(-abs(R.y) * mix(5.5, 1.3, blur));
        let sky_grad = clamp(R.y * 0.5 + 0.5, 0.0, 1.0);
        let zenith = vec3<f32>(0.18, 0.38, 0.76);
        let haze = vec3<f32>(0.86, 0.80, 0.72);
        let ground = vec3<f32>(0.18, 0.145, 0.11);
        var env = mix(ground, zenith, smoothstep(0.32 - blur * 0.25, 0.72 + blur * 0.2, sky_grad));
        env = mix(env, haze, horizon * mix(0.72, 0.38, blur));
        let sun_dir = normalize(vec3<f32>(-0.45, 0.8, -0.55));
        env += studio_sg_convolve(R, sun_dir, 90.0, kernel, vec3<f32>(14.0, 12.6, 10.4));
        env += studio_sg_convolve(R, sun_dir, 9.0, kernel, vec3<f32>(1.50, 1.34, 1.12));
        env += studio_sg_convolve(R, normalize(vec3<f32>(0.55, 0.45, 0.70)), 4.5, kernel, vec3<f32>(0.48, 0.62, 0.86));
        return max(env, vec3<f32>(0.02));
    }

    let up = clamp(R.y * 0.5 + 0.5, 0.0, 1.0);
    let floor_col = vec3<f32>(0.115, 0.110, 0.106);
    let mid_wall = vec3<f32>(0.245, 0.252, 0.275);
    let ceiling_col = vec3<f32>(0.39, 0.43, 0.50);
    var env = mix(floor_col, ceiling_col, smoothstep(0.16, 0.86, up));
    let horizon_band = exp(-abs(R.y) * mix(6.5, 1.5, blur));
    env = mix(env, mid_wall * 1.25, horizon_band * mix(0.48, 0.22, blur));

    let flag_a = pow(clamp(1.0 - abs(R.x * 1.5 - R.z * 0.65), 0.0, 1.0), 2.6) * clamp(1.0 - abs(R.y) * 1.05, 0.0, 1.0);
    let flag_b = pow(clamp(1.0 - abs(R.x * 0.65 + R.z * 1.45), 0.0, 1.0), 2.6) * clamp(0.65 - R.y, 0.0, 1.0);
    env *= mix(1.0, 0.24, clamp(flag_a + flag_b * 0.72, 0.0, 1.0) * mix(0.92, 0.25, blur));

    let key_axis = normalize(vec3<f32>(-0.45, 0.8, -0.55));
    let fill_axis = normalize(vec3<f32>(0.70, 0.26, 0.44));
    let rim_axis = normalize(vec3<f32>(0.22, 0.60, 0.76));
    let top_axis = normalize(vec3<f32>(-0.06, 0.98, -0.18));
    let low_bounce = normalize(vec3<f32>(-0.35, -0.70, -0.52));

    env += studio_sg_convolve(R, key_axis, 18.0, kernel, vec3<f32>(4.65, 4.42, 4.02));
    env += studio_sg_convolve(R, top_axis, 14.0, kernel, vec3<f32>(2.10, 2.15, 2.26));
    env += studio_sg_convolve(R, fill_axis, 10.0, kernel, vec3<f32>(1.12, 1.28, 1.58));
    env += studio_sg_convolve(R, rim_axis, 16.0, kernel, vec3<f32>(1.42, 1.26, 1.06));
    env += studio_sg_convolve(R, low_bounce, 4.0, kernel, vec3<f32>(0.26, 0.23, 0.20));
    return max(env, vec3<f32>(0.02));
}

fn studio_hdr_irradiance(N: vec3<f32>, outdoor: bool) -> vec3<f32> {
    let sky = clamp(N.y * 0.5 + 0.5, 0.0, 1.0);
    if outdoor {
        let ground = vec3<f32>(0.18, 0.145, 0.11);
        let sky_col = vec3<f32>(0.42, 0.54, 0.76);
        let sun_wrap = pow(clamp(dot(N, normalize(vec3<f32>(-0.45, 0.8, -0.55))) * 0.5 + 0.5, 0.0, 1.0), 2.0);
        return mix(ground, sky_col, sky) + vec3<f32>(0.22, 0.19, 0.15) * sun_wrap;
    }
    let floor_fill = vec3<f32>(0.20, 0.19, 0.18);
    let sky_fill = vec3<f32>(0.44, 0.48, 0.56);
    let side_cool = pow(clamp(dot(N, normalize(vec3<f32>(0.70, 0.26, 0.44))) * 0.5 + 0.5, 0.0, 1.0), 2.0);
    let key_warm = pow(clamp(dot(N, normalize(vec3<f32>(-0.45, 0.8, -0.55))) * 0.5 + 0.5, 0.0, 1.0), 2.0);
    return mix(floor_fill, sky_fill, sky)
        + vec3<f32>(0.08, 0.10, 0.14) * side_cool
        + vec3<f32>(0.15, 0.135, 0.12) * key_warm;
}

fn studio_charlie_d(roughness: f32, ndoth: f32) -> f32 {
    let inv_r = 1.0 / max(roughness * roughness, 0.05);
    let cos2h = ndoth * ndoth;
    let sin2h = max(1.0 - cos2h, 0.0078125);
    return (2.0 + inv_r) * pow(sin2h, inv_r * 0.5) / 6.28318530718;
}

fn studio_aniso_ggx_d(at: f32, ab: f32, ndoth: f32, tdoth: f32, bdoth: f32) -> f32 {
    let a2 = at * ab;
    let d = vec3<f32>(ab * tdoth, at * bdoth, a2 * ndoth);
    let d2 = dot(d, d);
    let b2 = a2 / max(d2, 1e-6);
    return a2 * b2 * b2 / 3.14159265359;
}

fn studio_env_brdf_scale_bias(roughness: f32, ndotv: f32) -> vec2<f32> {
    let c0 = vec4<f32>(-1.0, -0.0275, -0.572, 0.022);
    let c1 = vec4<f32>(1.0, 0.0425, 1.04, -0.04);
    let fit = clamp(roughness, 0.0, 1.0) * c0 + c1;
    let a004 = min(fit.x * fit.x, exp2(-9.28 * clamp(ndotv, 0.0, 1.0))) * fit.x + fit.y;
    return max(vec2<f32>(-1.04, 1.04) * a004 + fit.zw, vec2<f32>(0.0));
}

fn studio_specular_occlusion(ndotv: f32, ao: f32, roughness: f32) -> f32 {
    return clamp(pow(ndotv + ao, exp2(-16.0 * roughness - 1.0)) - 1.0 + ao, 0.0, 1.0);
}

// Jimenez et al. (2016) multi-bounce ambient occlusion: preserves natural chroma
// inside skin pores, cloth folds, leather crevices, and embossed metalwork.
fn studio_multi_bounce_ao(ao: f32, albedo: vec3<f32>) -> vec3<f32> {
    let x = clamp(ao, 0.0, 1.0);
    let a = 2.0404 * albedo - vec3<f32>(0.3324);
    let b = -4.7951 * albedo + vec3<f32>(0.6417);
    let c = 2.7552 * albedo + vec3<f32>(0.6903);
    return max(vec3<f32>(x), ((x * a + b) * x + c) * x);
}

fn studio_rotate_world_light(dir: vec3<f32>) -> vec3<f32> {
    let sc = studio_env_rotation();
    return vec3<f32>(dir.x * sc.y + dir.z * sc.x, dir.y, -dir.x * sc.x + dir.z * sc.y);
}

fn studio_direct_brdf(
    s: StudioSurface,
    albedo: vec3<f32>,
    eff_rough: f32,
    L: vec3<f32>,
    F0: vec3<f32>,
    F90: vec3<f32>,
    ms_comp: vec3<f32>,
) -> StudioTerms {
    let N = s.normal;
    let V = s.view;
    let H = safe_normalize(V + L, N);
    let NV = max(dot(N, V), 0.001);
    let NL_raw = dot(N, L);
    let NL = clamp(NL_raw, 0.0, 1.0);
    let NH = clamp(dot(N, H), 0.0, 1.0);
    let VH = clamp(dot(V, H), 0.0, 1.0);

    let a = max(eff_rough * eff_rough, 0.002);
    let a2 = a * a;
    var D = 0.0;
    if s.is_aniso {
        let at = max(a * 1.6, 0.01);
        let ab = max(a * 0.42, 0.005);
        D = studio_aniso_ggx_d(at, ab, NH, dot(s.tangent, H), dot(s.bitangent, H));
    } else {
        let d = NH * NH * (a2 - 1.0) + 1.0;
        D = a2 / (3.14159265359 * d * d + 1e-7);
    }
    let Gv = NL * sqrt(NV * NV * (1.0 - a2) + a2);
    let Gl = NV * sqrt(NL * NL * (1.0 - a2) + a2);
    let vis = 0.5 / max(Gv + Gl, 1e-5);
    // Roughness/microfiber-attenuated Fresnel: F90 drops cleanly on rough non-metals
    // so grazing cloth folds and matte leather never flare into white/vinyl bands.
    let Fr = F0 + max(F90 - F0, vec3<f32>(0.0)) * pow(1.0 - VH, 5.0);

    var diffuse_term = vec3<f32>(0.0);
    if s.is_skin {
        let sss = clamp(s.sss_strength, 0.4, 1.2);
        let wrap = vec3<f32>(0.42, 0.16, 0.05) * sss;
        let wrapped = clamp((vec3<f32>(NL_raw) + wrap) / (vec3<f32>(1.0) + wrap), vec3<f32>(0.0), vec3<f32>(1.0));
        let terminator = clamp(1.0 - abs(NL_raw * 2.2), 0.0, 1.0) * smoothstep(-0.45, 0.35, NL_raw);
        let sss_tint = vec3<f32>(0.18, 0.045, 0.02) * terminator * sss;
        diffuse_term = (vec3<f32>(1.0) - Fr) * albedo / 3.14159265359 * (wrapped + sss_tint);
    } else {
        diffuse_term = (vec3<f32>(1.0) - Fr) * (1.0 - s.metalness) * albedo / 3.14159265359 * NL;
    }

    var spec_term = D * vis * Fr * ms_comp * NL;

    if s.is_skin {
        let broad_r = mix(eff_rough, 0.82, 0.45);
        let ba = broad_r * broad_r;
        let ba2 = ba * ba;
        let bd = NH * NH * (ba2 - 1.0) + 1.0;
        let bD = ba2 / (3.14159265359 * bd * bd + 1e-7);
        let bvis = 0.5 / max(NL * sqrt(NV * NV * (1.0 - ba2) + ba2) + NV * sqrt(NL * NL * (1.0 - ba2) + ba2), 1e-5);
        spec_term = spec_term * 0.72 + (bD * bvis * Fr * NL) * 0.22;
    }

    if s.is_cloth {
        // Soft, strictly albedo-tinted microfiber nap on high-roughness weaves;
        // never mix toward white so fabric silhouettes never develop a grey halo.
        let cloth_nap = smoothstep(0.48, 0.92, eff_rough);
        let sheen_r = clamp(mix(0.48, 0.88, eff_rough), 0.40, 0.92);
        let sheen_col = albedo * 0.26 * (1.0 - s.metalness);
        let sheen_d = studio_charlie_d(sheen_r, NH);
        let sheen_v = 1.0 / max(4.0 * (NL + NV - NL * NV), 0.20);
        spec_term += sheen_col * sheen_d * sheen_v * NL * (0.045 * cloth_nap);
    }

    if s.is_eye {
        let CN = s.geo_normal;
        let CNV = max(dot(CN, V), 0.001);
        let CNL = clamp(dot(CN, L), 0.0, 1.0);
        let CNH = clamp(dot(CN, H), 0.0, 1.0);
        let ca = 0.042 * 0.042;
        let ca2 = ca * ca;
        let cd = CNH * CNH * (ca2 - 1.0) + 1.0;
        let cD = ca2 / (3.14159265359 * cd * cd + 1e-7);
        let cvis = 0.5 / max(CNL * sqrt(CNV * CNV * (1.0 - ca2) + ca2) + CNV * sqrt(CNL * CNL * (1.0 - ca2) + ca2), 1e-5);
        let cFr = vec3<f32>(0.032) + vec3<f32>(0.968) * pow(1.0 - VH, 5.0);
        spec_term = spec_term * 0.35 + cD * cvis * cFr * CNL;
        let caustic = clamp(dot(-N, L) * 0.5 + 0.5, 0.0, 1.0) * CNL;
        diffuse_term += albedo * caustic * 0.18;
    }

    if s.is_hair {
        let T1 = safe_normalize(s.tangent - N * 0.06, s.tangent);
        let T2 = safe_normalize(s.tangent + N * 0.105, s.tangent);
        let a1 = dot(T1, H);
        let a2_align = dot(T2, H);
        let exp1 = mix(28.0, 110.0, clamp(1.0 - eff_rough, 0.0, 1.0));
        let exp2 = max(exp1 * 0.38, 10.0);
        let band1 = pow(sqrt(clamp(1.0 - a1 * a1, 0.0, 1.0)), exp1);
        let band2 = pow(sqrt(clamp(1.0 - a2_align * a2_align, 0.0, 1.0)), exp2);
        let strand_wrap = clamp((NL_raw + 0.35) / 1.35, 0.0, 1.0);
        let primary_col = mix(vec3<f32>(0.86, 0.84, 0.82), albedo, 0.30);
        let hair_spec = (primary_col * band1 * 0.16 + albedo * band2 * 0.28) * s.specular * strand_wrap;
        let back_scatter = pow(clamp(dot(V, -L) * 0.5 + 0.5, 0.0, 1.0), 2.5) * pow(1.0 - NV, 1.8);
        diffuse_term = diffuse_term * 0.85 + albedo * back_scatter * 0.14;
        spec_term = spec_term * 0.18 + hair_spec;
    }

    return StudioTerms(diffuse_term, spec_term, vec3<f32>(0.0), vec3<f32>(0.0));
}

fn fixed_studio_lighting(s: StudioSurface) -> StudioTerms {
    let directions = array<vec3<f32>, 3>(
        studio_rotate_world_light(normalize(vec3<f32>(-0.45, 0.8, -0.55))),
        studio_rotate_world_light(normalize(vec3<f32>(0.70, 0.26, 0.44))),
        studio_rotate_world_light(normalize(vec3<f32>(0.22, 0.60, 0.76))),
    );
    var colours = array<vec3<f32>, 3>(
        vec3<f32>(1.00, 0.95, 0.88) * 2.85 * s.shadow,
        vec3<f32>(0.64, 0.76, 0.94) * 0.78,
        vec3<f32>(0.96, 0.85, 0.74) * 0.62,
    );
    if s.outdoor {
        colours = array<vec3<f32>, 3>(
            vec3<f32>(1.00, 0.94, 0.84) * 3.45 * s.shadow,
            vec3<f32>(0.54, 0.70, 0.96) * 0.68,
            vec3<f32>(0.84, 0.88, 0.94) * 0.42,
        );
    }

    let wetness = studio_wetness();
    // Per Ver2 shader dataflow: wetness lowers roughness up to 70% and darkens porous matte albedo.
    let eff_rough = clamp(mix(s.roughness, s.roughness * 0.30, wetness), 0.06, 1.0);
    let porous_mask = (1.0 - s.metalness) * smoothstep(0.32, 0.85, s.roughness);
    let wet_darken = mix(1.0, 0.68, wetness * porous_mask);
    let eff_albedo = s.albedo * wet_darken;

    let spec = clamp(s.specular, 0.0, 1.5);
    var dielectric_f0 = 0.04 * spec;
    if s.is_cloth {
        dielectric_f0 = 0.015 * spec;
    } else if s.is_skin {
        dielectric_f0 = 0.028 * spec;
    } else if s.is_leather {
        dielectric_f0 = 0.030 * spec;
    } else if s.is_eye {
        dielectric_f0 = 0.026 * spec;
    } else {
        // Even unclassified matte surfaces (roughness > 0.55) have porous micro-gap depolarization.
        dielectric_f0 = mix(0.04, 0.022, smoothstep(0.55, 0.88, eff_rough)) * spec;
    }
    if wetness > 0.0 {
        dielectric_f0 = mix(dielectric_f0, max(dielectric_f0, 0.038 * select(1.0, spec, s.specular <= 0.0)), wetness * 0.75);
    }

    var dielectric_f90 = mix(1.0, 0.12, smoothstep(0.28, 0.85, eff_rough));
    if s.is_cloth {
        dielectric_f90 = min(dielectric_f90, mix(0.20, 0.04, smoothstep(0.20, 0.78, eff_rough)));
    } else if s.is_skin {
        dielectric_f90 = min(dielectric_f90, 0.35);
    } else if s.is_hair {
        dielectric_f90 = min(dielectric_f90, 0.22);
    } else if s.is_leather {
        dielectric_f90 = min(dielectric_f90, mix(0.50, 0.09, smoothstep(0.25, 0.82, eff_rough)));
    }
    if wetness > 0.0 {
        dielectric_f90 = mix(dielectric_f90, 0.90, wetness * 0.75);
    }

    let NV = clamp(dot(s.normal, s.view), 0.0, 1.0);
    let F0 = mix(vec3<f32>(dielectric_f0), eff_albedo, s.metalness);
    let F90 = mix(vec3<f32>(dielectric_f90), vec3<f32>(1.0), s.metalness);

    let brdf_white = environment_brdf_approx(vec3<f32>(1.0), eff_rough, NV);
    let ess = max(brdf_white.r, 0.08);
    let ms_comp = vec3<f32>(1.0) + F0 * (1.0 / ess - 1.0);

    var result = StudioTerms(vec3<f32>(0.0), vec3<f32>(0.0), vec3<f32>(0.0), vec3<f32>(0.0));
    for (var i = 0u; i < 3u; i++) {
        let light = studio_direct_brdf(s, eff_albedo, eff_rough, directions[i], F0, F90, ms_comp);
        result.direct_diffuse += light.direct_diffuse * colours[i];
        result.direct_specular += light.direct_specular * colours[i];
    }

    let R = reflect(-s.view, s.normal);
    let irradiance = studio_env_irradiance(s.normal, s.outdoor);
    let env_radiance = studio_env_radiance(R, eff_rough, s.outdoor);
    let env_ab = studio_env_brdf_scale_bias(eff_rough, NV);
    let env_brdf = clamp(F0 * env_ab.x + F90 * env_ab.y, vec3<f32>(0.0), vec3<f32>(1.0)) * ms_comp;
    let kd_env = clamp(vec3<f32>(1.0) - env_brdf, vec3<f32>(0.0), vec3<f32>(1.0)) * (1.0 - s.metalness);

    let cavity = mix(0.40, 1.0, s.occlusion);
    let spec_cavity = studio_specular_occlusion(NV, cavity, eff_rough);

    let env_diff_gain = select(0.84, 0.92, s.outdoor);
    let env_spec_gain = select(0.88, 0.94, s.outdoor);
    let hair_env_scale = select(1.0, 0.25, s.is_hair);
    let skin_env_scale = select(1.0, 0.56, s.is_skin);

    result.indirect_diffuse = eff_albedo * kd_env * irradiance * cavity * env_diff_gain;
    result.indirect_specular = env_radiance * env_brdf * spec_cavity * env_spec_gain * hair_env_scale * skin_env_scale;

    if s.is_eye {
        let R_cornea = reflect(-s.view, s.geo_normal);
        let cornea_env = studio_env_radiance(R_cornea, 0.045, s.outdoor);
        let cnv = clamp(dot(s.geo_normal, s.view), 0.0, 1.0);
        let cornea_brdf = environment_brdf_approx(vec3<f32>(0.032), 0.045, cnv);
        result.indirect_specular = result.indirect_specular * 0.25 + cornea_env * cornea_brdf * 0.85;
    }

    if s.is_skin {
        let fuzz = pow(1.0 - NV, 4.0) * clamp(s.sss_strength, 0.5, 1.1);
        result.indirect_diffuse += eff_albedo * vec3<f32>(1.08, 0.92, 0.84) * irradiance * fuzz * 0.14 * cavity;
    }

    return result;
}

// Troy Sobotka's AgX default contrast polynomial (6th order).
fn studio_agx_contrast(x: vec3<f32>) -> vec3<f32> {
    let x2 = x * x;
    let x4 = x2 * x2;
    return 15.5 * x4 * x2
        - 40.14 * x4 * x
        + 31.96 * x4
        - 6.868 * x2 * x
        + 0.4298 * x2
        + 0.1191 * x
        - vec3<f32>(0.00232);
}

// AgX filmic tone mapping returning linear RGB for `present()`:
// preserves true cloth, leather, gold, and skin hues without yellow shift or chalky clipping.
fn fixed_studio_tone(colour: vec3<f32>) -> vec3<f32> {
    let agx_inset = mat3x3<f32>(
        vec3<f32>(0.842479062253094, 0.0423282422610123, 0.0423756549057051),
        vec3<f32>(0.0784335999999992, 0.878468636469772, 0.0784336),
        vec3<f32>(0.0792237451477643, 0.0791661274605434, 0.879142973793104),
    );
    let agx_outset = mat3x3<f32>(
        vec3<f32>(1.19687900512017, -0.0528968517574562, -0.0529716355144438),
        vec3<f32>(-0.0980208811401368, 1.15190312990417, -0.0980434501171241),
        vec3<f32>(-0.0990297440797205, -0.0989611768448433, 1.15107367264116),
    );
    let min_ev = -12.47393;
    let max_ev = 4.026069;
    let exposed = max(colour, vec3<f32>(0.0)) * (0.85 * studio_exposure());
    var val = agx_inset * max(exposed, vec3<f32>(1e-10));
    val = clamp((log2(max(val, vec3<f32>(1e-10))) - vec3<f32>(min_ev)) / (max_ev - min_ev), vec3<f32>(0.0), vec3<f32>(1.0));
    val = studio_agx_contrast(val);
    val = agx_outset * val;
    return srgb_to_linear(clamp(val, vec3<f32>(0.0), vec3<f32>(1.0)));
}
