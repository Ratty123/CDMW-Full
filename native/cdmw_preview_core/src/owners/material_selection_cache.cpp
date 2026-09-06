static std::uint64_t sidecar_parse_cache_hits() {
    return g_sidecar_parse_cache_hits;
}

static std::uint64_t sidecar_parse_cache_misses() {
    return g_sidecar_parse_cache_misses;
}

static std::map<std::string, ParsedMaterialSidecar>& resident_parsed_material_sidecar_cache() {
    static std::map<std::string, ParsedMaterialSidecar> cache;
    return cache;
}

static size_t resident_parsed_material_sidecar_cache_count() {
    return resident_parsed_material_sidecar_cache().size();
}

static void release_resident_parsed_material_sidecar_cache() {
    std::map<std::string, ParsedMaterialSidecar> empty;
    resident_parsed_material_sidecar_cache().swap(empty);
}

// Parsed sidecars are small (extracted refs and hints, not the XML), but a
// long session can accumulate one per model. Keep them resident so repeat
// previews skip the decode+parse, and clear only past a generous bound.
static constexpr size_t kResidentParsedMaterialSidecarMaxCount = 4096;

static void trim_resident_parsed_material_sidecar_cache() {
    if (resident_parsed_material_sidecar_cache().size() > kResidentParsedMaterialSidecarMaxCount) {
        release_resident_parsed_material_sidecar_cache();
    }
}

static const ParsedMaterialSidecar& cached_parsed_material_sidecar(
    const ArchiveEntryRef& sidecar,
    int model_property_index
) {
    auto& cache = resident_parsed_material_sidecar_cache();
    const std::string key = archive_ref_identity(sidecar)
        + "|model-property:" + std::to_string(model_property_index);
    auto found = cache.find(key);
    if (found != cache.end()) {
        ++g_sidecar_parse_cache_hits;
        return found->second;
    }
    ++g_sidecar_parse_cache_misses;
    std::vector<char> sidecar_bytes = read_archive_ref_decoded_bytes(sidecar);
    std::string sidecar_text(sidecar_bytes.begin(), sidecar_bytes.end());
    const std::string material_scope = material_sidecar_scope_for_model_property(
        sidecar_text,
        model_property_index);
    ParsedMaterialSidecar parsed;
    parsed.shader_family = extract_shader_family_hint(material_scope);
    if (parsed.shader_family.empty()) {
        parsed.shader_family = sidecar.extension == ".pami" ? "StaticMaterial" : "";
    }
    parsed.shader_rule = shader_rule_for_family(parsed.shader_family);
    parsed.parameter_summary = summarize_sidecar_parameters(material_scope);
    parsed.pbd_hints = extract_native_pbd_sidecar_hints(material_scope, sidecar.path);
    parsed.refs = extract_sidecar_texture_refs(
        material_scope, model_property_index, &parsed.declarations);
    parsed.material_wrapper_count = 0;
    for (const MaterialWrapperDeclaration& declaration : parsed.declarations) {
        if (declaration.material_wrapper_index >= 0) {
            parsed.material_wrapper_count = std::max(
                parsed.material_wrapper_count,
                declaration.material_wrapper_index + 1);
        }
    }
    if (parsed.refs.empty()) {
        const std::vector<MaterialParameterRecord> material_parameters = extract_material_parameters(material_scope);
        for (const std::string& token : extract_dds_tokens(material_scope)) {
            parsed.refs.push_back(SidecarTextureRef{
                token, "", "", parsed.shader_family, "unscoped-material", -1, material_parameters});
        }
    }
    return cache.emplace(key, std::move(parsed)).first->second;
}

static const NativePbdSidecarHint* best_native_pbd_hint_for_binding(
    const std::vector<NativePbdSidecarHint>& hints,
    const std::string& binding_material_name,
    const std::string& texture_ref_material_name,
    const std::string& texture_parameter_name
) {
    const NativePbdSidecarHint* best = nullptr;
    int best_score = 0;
    const std::string material_key = normalized_material_key(binding_material_name);
    const std::string ref_material_key = normalized_material_key(texture_ref_material_name);
    const std::string parameter_key = normalized_key(texture_parameter_name);
    const std::string binding_context = binding_material_name + " " + texture_ref_material_name + " " + texture_parameter_name;
    const bool binding_looks_like_soft_physics = native_soft_pbd_token_match(binding_context);
    if (native_rigid_pbd_token_match(binding_context) && !binding_looks_like_soft_physics) {
        return nullptr;
    }
    const bool binding_looks_like_cloth = native_cloth_token_match(
        binding_material_name + " " + texture_ref_material_name + " " + texture_parameter_name
    );
    for (const NativePbdSidecarHint& hint : hints) {
        if (hint.simulation_material_name.empty()) continue;
        if (!native_pbd_hint_is_soft_physics(hint)) continue;
        int score = 0;
        const std::string hint_material_key = normalized_material_key(hint.material_name);
        const std::string hint_submesh_key = normalized_material_key(hint.submesh_name);
        const std::string hint_pbd_key = normalized_material_key(hint.simulation_material_name);
        if (!hint_material_key.empty() && (hint_material_key == material_key || hint_material_key == ref_material_key)) score += 100;
        if (!hint_submesh_key.empty() && (hint_submesh_key == material_key || hint_submesh_key == ref_material_key)) score += 90;
        if (!hint_pbd_key.empty() && (material_key.find(hint_pbd_key) != std::string::npos || ref_material_key.find(hint_pbd_key) != std::string::npos)) score += 40;
        if (binding_looks_like_soft_physics) score += 20;
        if (binding_looks_like_cloth) score += 20;
        if (!parameter_key.empty() && native_soft_pbd_token_match(parameter_key)) score += 20;
        if (score > best_score) {
            best_score = score;
            best = &hint;
        }
    }
    return best_score >= 80 ? best : nullptr;
}

// Crimson's `_sp` maps carry their surface response in G and B, read out of the
// shipped shaders rather than inferred from the filename suffix:
//
//   Standard/Cloth/Fur/Emissive/...  sample G and B only. G is roughness,
//                                    B is metalness. R and A are never sampled.
//   Skin/SkinWrinkle/EyeCover        sample R, G and B. R is the subsurface
//                                    term, which the preview has no lobe for,
//                                    so it is dropped rather than folded into
//                                    occlusion. G is roughness, B is metalness.
//   Hair/AnimalHair/WhiteHornHair    sample G alone; hair carries no metal.
//
// R is *not* occlusion in any family. It is the most spatially detailed channel,
// which is why it reads like a baked AO map, but only the skin shaders sample it
// and they use it as subsurface. `_sp` files are BC1, so alpha is synthesised
// opaque and never carries data; nothing may read it.
static std::string material_response_channel_layout(const std::string& shader_rule) {
    if (shader_rule == "hair") return "g=roughness";
    // Skin packs its `_sp` differently and blue is not metal there. On equipment
    // the red channel is a constant 1.0 filler and blue is metalness, varying by
    // material -- cd_phm_03_handle_0004_sp measures B 0.005 and
    // cd_phm_03_shield_0090_sp measures 0.877. A skin map does neither:
    // cd_phm_00_head_0001_sp measures R 0.770, the subsurface term the skin
    // shaders sample, and B 0.997 flat across the whole face.
    //
    // Read as metalness that says a face is 100% metal, which is what it did:
    // 24 of 72 sampled heads classified metal rather than skin, and a metal
    // classification takes the lower ambient floor and the cut diffuse, so the
    // face rendered at 0.45 of the brightness its own albedo carries. Declaring
    // only what the channel actually holds keeps the classifier, and the
    // renderer, from reading a number that is not there.
    if (shader_rule == "skin") return "g=roughness";
    return "g=roughness,b=metalness";
}

static std::string packed_channels_for_role(
    const std::string& role,
    const std::string& name,
    const std::string& parameter_name,
    const std::string& shader_rule
) {
    const std::string lower = lower_copy(name + " " + parameter_name);
    const std::string parameter_key = normalized_key(parameter_name);
    if (role == "material") {
        if (lower.find("orm") != std::string::npos) return "r=occlusion,g=roughness,b=metalness";
        if (lower.find("rma") != std::string::npos) return "r=roughness,g=metalness,b=occlusion";
        if (lower.find("mra") != std::string::npos) return "r=metalness,g=roughness,b=occlusion";
        if (lower.find("arm") != std::string::npos) return "r=occlusion,g=roughness,b=metalness";
        if (parameter_key == "colorblendingmasktexture" && lower.find("_ma") != std::string::npos) {
            // A colour-blending mask selects which authored colour layer owns a
            // texel. Declaring it as packed occlusion/roughness/metal made the
            // consumer read a layer weight as a surface property, which is how
            // dyed cloth and leather picked up a metal response they never had.
            return "layer:color_blending_mask";
        }
        if (parameter_key == "detailmasktexture" || lower.find("_mg") != std::string::npos) {
            return "layer:detail_grime_dye_mask";
        }
        if (
            lower.find("_sp") != std::string::npos
            || parameter_key.find("grimematerialtexture") != std::string::npos
            || parameter_key.find("detailmaterialmask") != std::string::npos
            || parameter_key == "materialtexture"
        ) {
            // Keep the layer marker for consumers that decode the map themselves,
            // and declare the component layout so a consumer that samples the DDS
            // directly binds roughness and metal to the channels the game reads.
            return "layer:material_response," + material_response_channel_layout(shader_rule);
        }
        if (lower.find("_ma") != std::string::npos) return "diagnostic:crimson_material_mask";
        if (lower.find("_m") != std::string::npos) return "diagnostic:packed_material_mask";
    }
    if (role == "detail") return "layer:detail_grime_dye_mask";
    if (role == "specular") {
        // Only Crimson's `_sp` maps carry the G/B surface layout. A gloss or
        // smoothness map that also lands in this slot is a different contract,
        // so it keeps the bare marker and no component claim.
        if (lower.find("_sp") != std::string::npos) {
            return "layer:material_response," + material_response_channel_layout(shader_rule);
        }
        return "layer:material_response";
    }
    if (role == "height") return "height";
    if (role == "normal") return "normal_xy";
    if (role == "emissive" && parameter_is_emissive_intensity_texture(parameter_name)) {
        return "r=emissive_intensity";
    }
    if (role == "opacity") {
        // R, G and B are three alternative tear shapes and the game picks one per
        // character. A preview has no such choice, so it shows the first, which is
        // the primary channel everywhere else in this format. Alpha is a broad
        // unrelated field covering 42% of the sheet and is not coverage.
        return lower.find("_m") != std::string::npos ? "r=opacity" : "";
    }
    return "";
}

static std::string layer_channel_from_parameter(const std::string& parameter_name) {
    const std::string key = normalized_key(parameter_name);
    // SkinnedMeshSkin explicitly uses a red-channel mask. Generic selector
    // textures do not name one fixed layer channel: the associated labelled
    // grime/detail parameters own their R/G/B channel identity instead.
    if (key == "skindetailmasktexture") return "r";
    if (key == "detailmasktexture" || key == "colorblendingmasktexture") return "";
    if (key.ends_with("r")) return "r";
    if (key.ends_with("g")) return "g";
    if (key.ends_with("b")) return "b";
    if (key.ends_with("a")) return "a";
    return "";
}

// Whether the parameter itself names the mask channel that selects its layer.
// `_detailDiffuseMaskR/G/B` do; selector textures are masks, not layers.
static bool layer_parameter_names_channel(const std::string& parameter_name) {
    const std::string key = normalized_key(parameter_name);
    if (key.find("detailmasktexture") != std::string::npos) return false;
    return key.ends_with("r") || key.ends_with("g") || key.ends_with("b") || key.ends_with("a");
}

static int layer_channel_index(const std::string& channel) {
    const std::string value = lower_copy(channel);
    if (value == "g") return 1;
    if (value == "b") return 2;
    if (value == "a") return 3;
    return 0;
}

static float skin_detail_scale_from_parameters(
    const std::vector<MaterialParameterRecord>& parameters
) {
    const MaterialParameterRecord* scale = find_material_parameter(
        parameters, {"_skinDetailScale"});
    if (scale == nullptr
        || normalized_key(scale->name) != "skindetailscale"
        || !scale->has_numeric) return 0.0f;
    return std::max(0.0f, scale->numeric_value);
}

static std::string layer_role_from_parameter(const std::string& parameter_name, const std::string& role) {
    const std::string key = normalized_key(parameter_name);
    // Coverage is never a colour layer. The tear shell's mask arrives on
    // `_baseColorTexture`, whose name matches the "colortexture" layer rule
    // below, and a consumer that filters layer-only roles then discarded the
    // one input that says which part of the shell is a tear.
    if (role == "opacity") return "opacity";
    if (key.find("grime") != std::string::npos) return "grime";
    if (key.find("detail") != std::string::npos || key.find("dyeing") != std::string::npos) return "detail";
    if (key.find("damage") != std::string::npos) return "damage";
    if (key.find("overlay") != std::string::npos) return "overlay";
    if (key.find("layer") != std::string::npos || key.find("colortexture") != std::string::npos) return "layer";
    if (role == "base") return "base";
    if (role == "detail") return "detail_mask";
    if (role == "material") return "material_response";
    if (role == "specular") return "specular_response";
    return role.empty() ? "material" : role;
}

static float layer_weight_from_parameters(
    const std::vector<MaterialParameterRecord>& parameters,
    const std::string& layer_role,
    const std::string& channel
) {
    const int channel_index = layer_channel_index(channel);
    if (layer_role == "base") return 1.0f;
    if (layer_role == "overlay") return 0.24f;
    if (layer_role == "grime") {
        const auto opacity = byte4_parameter_channels(parameters, {"grimeBlendingOpacityParameter", "grimeOpacity"});
        float value = opacity[std::min(channel_index, 3)];
        if (value <= 0.01f) value = 0.34f;
        return std::clamp(value, 0.03f, 0.72f);
    }
    if (layer_role == "detail") {
        const MaterialParameterRecord* skin_opacity = find_material_parameter(
            parameters, {"_skinDetailOpacity"});
        if (skin_opacity != nullptr
            && normalized_key(skin_opacity->name) == "skindetailopacity"
            && skin_opacity->has_numeric) {
            return std::clamp(skin_opacity->numeric_value, 0.0f, 1.0f);
        }
        const auto global = byte4_parameter_channels(parameters, {"dyeingGlobalOpacity"});
        float value = global[std::min(channel_index, 3)];
        if (value <= 0.01f) value = 0.42f;
        const auto property = byte4_parameter_channels(parameters, {"dyeingPropertyBlend"});
        value *= std::max(0.25f, std::max({property[0], property[1], property[2], value}));
        return std::clamp(value, 0.04f, 0.68f);
    }
    if (layer_role == "damage") {
        const auto damage = byte4_parameter_channels(parameters, {"damageBlendingParameter"});
        float value = std::max({damage[0], damage[1], damage[2], damage[3], 0.18f});
        return std::clamp(value, 0.04f, 0.58f);
    }
    return 0.28f;
}

static const MaterialParameterRecord* exact_visible_color_parameter(
    const std::vector<MaterialParameterRecord>& parameters,
    const std::string& parameter_name
) {
    const std::string wanted = normalized_key(parameter_name);
    for (const MaterialParameterRecord& parameter : parameters) {
        if (parameter.kind == "color"
            && normalized_key(parameter.name) == wanted
            && color_parameter_value_has_visible_alpha(parameter.value)) {
            return &parameter;
        }
    }
    return nullptr;
}

static std::array<float, 4> tint_for_layer(
    const std::vector<MaterialParameterRecord>& parameters,
    const std::string& layer_role,
    const std::string& channel
) {
    if (layer_role == "color_seed") {
        const MaterialParameterRecord* dye = exact_visible_color_parameter(
            parameters, "dyeingColorMask" + channel);
        if (dye == nullptr) return {0.0f, 0.0f, 0.0f, 0.0f};
        return color_parameter_value(dye->value);
    }
    std::vector<std::string> candidates;
    if (layer_role == "grime") {
        // _tintColor{R,G,B} is the base tint of the three layers the
        // _colorBlendingMaskTexture selects; it sits alongside
        // _grimeDiffuseTexture{R,G,B} one-for-one in the PAC.
        // _scratchTintColor{R,G,B} is the wear accent for the same channels and
        // carries a low alpha strength, so it is an overlay rather than the
        // surface colour. Preferring scratch here painted the blade of
        // cd_phm_02_sword_0014 near-white (#dbdbdb) and its grip yellow
        // (#dbc03e) instead of the authored #ae8c54 gold and #625142 brown.
        candidates = {"tintColor" + channel, "dyeingDetailLayerColorMask" + channel, "scratchTintColor" + channel};
    } else if (layer_role == "detail") {
        candidates = {"dyeingDetailLayerColorMask" + channel, "dyeingColorMask" + channel, "tintColor" + channel};
    } else if (layer_role == "overlay") {
        candidates = {"overlayColor", "tintColor" + channel, "tintColor"};
    } else {
        candidates = {
            "tintColor" + channel,
            "dyeingColorMask" + channel,
            "baseColor" + channel,
            "diffuseColor" + channel,
            "albedoColor" + channel,
            "materialColor" + channel,
            "baseColor",
            "diffuseColor",
            "albedoColor",
            "materialColor",
            "tintColor"
        };
    }
    for (const std::string& candidate : candidates) {
        const MaterialParameterRecord* parameter = find_material_parameter(parameters, {candidate.c_str()});
        if (parameter != nullptr && parameter->kind == "color") {
            return color_parameter_value(parameter->value);
        }
    }
    return {1.0f, 1.0f, 1.0f, 1.0f};
}

static std::string color_seed_parameter_name_for_channel(
    const std::vector<MaterialParameterRecord>& parameters,
    const std::string& channel
) {
    const MaterialParameterRecord* parameter = exact_visible_color_parameter(
        parameters, "dyeingColorMask" + channel);
    return parameter == nullptr ? "" : parameter->name;
}

static std::string joined_parameter_names_with_color_seed_sources(
    const std::vector<MaterialParameterRecord>& parameters
) {
    std::string result = joined_parameter_names(parameters);
    for (const char channel : std::string("rgb")) {
        const std::string source_parameter = color_seed_parameter_name_for_channel(
            parameters, std::string(1, channel));
        if (source_parameter.empty()) continue;
        if (!result.empty()) result += ",";
        result += source_parameter;
    }
    return result;
}

static std::string evidence_grade_for_binding(
    const TextureBinding& binding,
    const TechniqueParameterInfo* technique_parameter
) {
    if (binding.material_output_quality == "exact" && technique_parameter != nullptr && technique_parameter->declared) {
        return "corpus_inferred";
    }
    if (binding.material_output_quality == "exact") return "corpus_inferred";
    if (binding.material_output_quality == "inferred") return "approximate";
    return "approximate";
}

static std::string role_from_parameter_shader_and_name(
    const std::string& parameter_name,
    const std::string& shader_rule,
    const std::string& texture_name,
    const TechniqueParameterInfo* technique_parameter = nullptr
) {
    const std::string p = lower_copy(parameter_name);
    const std::string t = lower_copy(texture_name);
    const std::string parameter_key = normalized_key(parameter_name);
    // These three parameters are a support-only skin-detail stack.  The mask
    // selects the layer; it is never a global material response.  Exact roles
    // must precede both technique metadata and filename suffix inference because
    // real sidecars can omit these technique declarations and the mask ends `_m`.
    if (parameter_key == "skindetailmasktexture") return "detail";
    if (parameter_key == "skindetailnormaltexture") return "normal";
    if (parameter_key == "skindetailmaterialtexture") return "specular";
    if (p.find("emissive") != std::string::npos || p.find("glow") != std::string::npos || p.find("illum") != std::string::npos || t.find("_emi.dds") != std::string::npos || t.find("emissive") != std::string::npos) return "emissive";
    if (p.find("flow") != std::string::npos) return "flow";
    if (shader_rule == "hair" && (p == "_flowtexture" || p.find("flowtexture") != std::string::npos || t.find("_f.dds") != std::string::npos)) return "flow";
    if (p.find("ssdm") != std::string::npos || p.find("direction") != std::string::npos || t.find("_dr.dds") != std::string::npos) return "flow";
    if ((p.find("alpha") != std::string::npos || p.find("opacity") != std::string::npos) && p.find("base") == std::string::npos) return "opacity";
    // The tear shell's `_m` atlas arrives on a colour parameter, and the technique
    // declares that parameter, so this has to precede the declared-parameter block
    // below. Its three colour channels are tear-shape coverage, not albedo:
    // routing it to opacity clips the shell to the tear itself, where leaving it
    // rejected as a technical base drew the whole card as a grey sheet.
    if (shader_rule == "tear"
        && t.find("_m.dds") != std::string::npos
        && (p.find("basecolor") != std::string::npos
            || p.find("diffuse") != std::string::npos
            || p.find("albedo") != std::string::npos)) {
        return "opacity";
    }
    // `_tornPatternTexture` is the shape of a tear, not a surface input. It has
    // no colour role, no normal, no response -- it selects where a garment is
    // torn. Left to fall through it landed in the base role, and on
    // cd_m0001_00_so_pgm_ub_belt_42008 the shared library pattern it points at
    // became the albedo, rendering the garment as neon green and magenta
    // stripes. Naming its own role keeps the binding on record as evidence
    // while leaving it out of every channel the renderer samples.
    if (p.find("tornpattern") != std::string::npos || t.find("_tp.dds") != std::string::npos) {
        return "torn_pattern";
    }
    if (technique_parameter != nullptr && technique_parameter->declared) {
        const std::string declared_type = lower_copy(technique_parameter->type);
        const std::string declared_default = lower_copy(technique_parameter->default_value);
        const bool declared_texture = declared_type.find("texture") != std::string::npos || p.find("texture") != std::string::npos;
        if (declared_texture) {
            if (p.find("emissive") != std::string::npos || p.find("glow") != std::string::npos || p.find("illum") != std::string::npos) return "emissive";
            if (p.find("flow") != std::string::npos) return "flow";
            if (p.find("ssdm") != std::string::npos || p.find("direction") != std::string::npos) return "flow";
            if (p.find("normal") != std::string::npos || declared_default.find("0xff7f7f00") != std::string::npos) return "normal";
            if (p.find("height") != std::string::npos || p.find("displacement") != std::string::npos || p.find("disp") != std::string::npos) return "height";
            if (p.find("specular") != std::string::npos || p.find("gloss") != std::string::npos || p.find("smoothness") != std::string::npos) return "specular";
            if (p.find("roughness") != std::string::npos) return "roughness";
            if (p.find("metallic") != std::string::npos || p.find("metalness") != std::string::npos) return "metalness";
            if (p.find("occlusion") != std::string::npos || p.find("ambientocclusion") != std::string::npos) return "occlusion";
            if ((p.find("diffuse") != std::string::npos || p.find("basecolor") != std::string::npos || p.find("albedo") != std::string::npos) && p.find("mask") == std::string::npos) return "base";
            if (p.find("basecolor") != std::string::npos || p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos) return "base";
            if (p.find("overlaycolor") != std::string::npos || p.find("layerbasecolor") != std::string::npos || p.find("layercolor") != std::string::npos) return "base";
            if (p.find("mask") != std::string::npos && (p.find("detail") != std::string::npos || p.find("blend") != std::string::npos || p.find("layer") != std::string::npos)) return "detail";
            if (p.find("material") != std::string::npos || p.find("colorblendingmask") != std::string::npos || p == "_masktexture") return "material";
        }
    }
    if (p.find("normal") != std::string::npos || p == "n" || t.find("_n.dds") != std::string::npos) return "normal";
    if (p.find("height") != std::string::npos || p.find("displacement") != std::string::npos || p.find("disp") != std::string::npos || t.find("_disp.dds") != std::string::npos) return "height";
    if (p.find("roughness") != std::string::npos || t.find("roughness") != std::string::npos) return "roughness";
    if (p.find("metallic") != std::string::npos || p.find("metalness") != std::string::npos || t.find("metallic") != std::string::npos || t.find("metalness") != std::string::npos) return "metalness";
    if (p.find("occlusion") != std::string::npos || p.find("ambientocclusion") != std::string::npos || t.find("_ao.dds") != std::string::npos) return "occlusion";
    // The authored parameter outranks the file suffix: SkinnedMeshStandard writes its
    // packed roughness/metal map to _materialTexture and still names the file _sp.dds,
    // so matching the suffix first strands it in the specular slot and drops the batch
    // onto the legacy specular-gloss response. Skin keeps the suffix reading below.
    const bool parameter_declares_material_map =
        p.find("material") != std::string::npos && shader_rule != "skin";
    if (
        p.find("specular") != std::string::npos
        || p.find("_sp") != std::string::npos
        || (t.find("_sp.dds") != std::string::npos && !parameter_declares_material_map)
    ) return "specular";
    if (p.find("gloss") != std::string::npos || p.find("smoothness") != std::string::npos || t.find("gloss") != std::string::npos || t.find("smoothness") != std::string::npos) return "specular";
    if ((p.find("diffuse") != std::string::npos || p.find("basecolor") != std::string::npos || p.find("albedo") != std::string::npos) && p.find("mask") == std::string::npos) return "base";
    if (p.find("material") != std::string::npos || p.find("colorblendingmask") != std::string::npos || p.find("blending") != std::string::npos || t.find("_ma.dds") != std::string::npos || t.find("_m.dds") != std::string::npos) return "material";
    if (p.find("detail") != std::string::npos || p.find("grime") != std::string::npos || p.find("dye") != std::string::npos || p.find("mask") != std::string::npos || t.find("_mg.dds") != std::string::npos) {
        if (p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos || p.find("color") != std::string::npos) return "base";
        return "detail";
    }
    if (p.find("overlaycolor") != std::string::npos || p.find("layercolor") != std::string::npos) return "base";
    if (p.find("basecolor") != std::string::npos || p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos) return "base";
    if (shader_rule == "skin" && t.find("_sp.dds") != std::string::npos) return "specular";
    return texture_role_from_name(texture_name);
}

static std::string semantic_type_for_role(const std::string& role) {
    if (role == "base") return "albedo";
    if (role == "emissive") return "emissive";
    if (role == "normal") return "normal";
    if (role == "height") return "height";
    if (role == "specular") return "specular";
    if (role == "roughness") return "roughness";
    if (role == "metalness") return "metalness";
    if (role == "occlusion") return "ao";
    if (role == "detail") return "detail_mask";
    if (role == "flow") return "flow";
    if (role == "opacity") return "opacity";
    return "packed_material";
}
