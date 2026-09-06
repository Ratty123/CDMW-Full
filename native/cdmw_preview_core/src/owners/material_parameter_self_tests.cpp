static void require_material_contract(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(std::string("material contract self-test failed: ") + message);
    }
}

static MaterialParameterRecord authored_color(const char* name, const char* value) {
        MaterialParameterRecord parameter;
        parameter.kind = "color";
        parameter.name = name;
        parameter.value = value;
        return parameter;
}

static MaterialParameterRecord authored_integer(const char* kind, const char* name, const char* value) {
        MaterialParameterRecord parameter;
        parameter.kind = kind;
        parameter.name = name;
        parameter.value = value;
        parameter.integer_value = integer_parameter_value(value, &parameter.has_integer);
        return parameter;
}

static void run_material_declaration_conservation_self_test() {
    const std::string shared_variant_sidecar =
        "<Root>"
        "<ModelProperty Index=\"0\"><SkinnedMeshMaterialWrapper _subMeshName=\"vest\">"
        "<MaterialParameterTexture _name=\"_baseColorTexture\" Value=\"variant_zero.dds\"/>"
        "</SkinnedMeshMaterialWrapper></ModelProperty>"
        "<ModelProperty Index=\"1\"><SkinnedMeshMaterialWrapper _subMeshName=\"vest\">"
        "<MaterialParameterTexture _name=\"_baseColorTexture\" Value=\"variant_one.dds\"/>"
        "</SkinnedMeshMaterialWrapper></ModelProperty>"
        "</Root>";
    const std::vector<SidecarTextureRef> variant_one_refs =
        extract_sidecar_texture_refs(shared_variant_sidecar, 1);
    require_material_contract(
        variant_one_refs.size() == 1
            && lower_copy(variant_one_refs.front().path).find("variant_one.dds") != std::string::npos,
        "shared PAC material-property selection ignored the item prefab index");

    const std::string shared_logical_edge_sidecar =
        "<Root><ModelProperty Index=\"0\"><SkinnedMeshMaterialWrapper ItemID=\"712\" _subMeshName=\"grip\">"
        "<MaterialParameterTexture _name=\"_detailMaskTexture\" Value=\"shared_mask.dds\"/>"
        "<MaterialParameterTexture _name=\"_grimeDiffuseTextureR\" Value=\"shared_mask.dds\"/>"
        "<MaterialParameterTexture _name=\"_detailDiffuseMaskB\" Value=\"shared_mask.dds\"/>"
        "<MaterialParameterByte4 _name=\"_dyeingTransformProperty0\" _value=\"4294967295\"/>"
        "</SkinnedMeshMaterialWrapper></ModelProperty></Root>";
    std::vector<MaterialWrapperDeclaration> shared_logical_declarations;
    const std::vector<SidecarTextureRef> shared_logical_refs =
        extract_sidecar_texture_refs(
            shared_logical_edge_sidecar, 0, &shared_logical_declarations);
    require_material_contract(
        shared_logical_refs.size() == 3
            && std::all_of(shared_logical_refs.begin(), shared_logical_refs.end(), [](const SidecarTextureRef& ref) {
                return ref.owner_wrapper_item_id == "712"
                    && ref.path == "shared_mask.dds"
                    && sidecar_ref_has_exact_wrapper_identity(ref);
            }),
        "same-DDS logical PAC parameters collapsed or lost wrapper identity");
    require_material_contract(
        shared_logical_declarations.size() == 1
            && shared_logical_declarations.front().owner_wrapper_item_id == "712"
            && shared_logical_declarations.front().material_parameters.size() == 4,
        "source parameter declaration inventory is incomplete");
    require_material_contract(
        layer_channel_from_parameter("_detailMaskTexture").empty()
            && layer_channel_from_parameter("_colorBlendingMaskTexture").empty()
            && layer_channel_from_parameter("_grimeDiffuseTextureR") == "r"
            && layer_channel_from_parameter("_detailDiffuseMaskB") == "b",
        "selector masks or labelled layer parameters lost exact channel semantics");
    require_material_contract(
        !shared_logical_refs.front().material_parameters.empty()
            && std::any_of(
                shared_logical_refs.front().material_parameters.begin(),
                shared_logical_refs.front().material_parameters.end(),
                [](const MaterialParameterRecord& parameter) {
                    return parameter.name == "_dyeingTransformProperty0"
                        && parameter.has_integer
                        && parameter.integer_value == "4294967295"
                        && !parameter.has_numeric;
                })
            && std::any_of(
                shared_logical_refs.front().material_parameters.begin(),
                shared_logical_refs.front().material_parameters.end(),
                [](const MaterialParameterRecord& parameter) {
                    return parameter.kind == "texture"
                        && parameter.name == "_detailMaskTexture"
                        && parameter.texture_path == "shared_mask.dds";
                }),
        "Byte4 PAC value travelled through lossy floating-point transport");

    MaterialParameterRecord duplicate_texture;
    duplicate_texture.kind = "texture";
    duplicate_texture.name = "_detailMaskTexture";
    duplicate_texture.texture_path = "character/texture/shared_mask.dds";
    require_material_contract(
        material_conservation_parameter_key(
            "character/model/component_a.pac#model_property=0",
            shared_logical_declarations.front(),
            duplicate_texture)
            == material_conservation_parameter_key(
                "character/model/component_a.pac#model_property=0",
                shared_logical_declarations.front(),
                duplicate_texture),
        "logical texture edge dedupe still depended on duplicate sidecar provenance");
    require_material_contract(
        material_conservation_parameter_key(
            "character/model/component_a.pac#model_property=0",
            shared_logical_declarations.front(),
            duplicate_texture)
            != material_conservation_parameter_key(
                "character/model/component_b.pac#model_property=0",
                shared_logical_declarations.front(),
                duplicate_texture),
        "component-local material wrapper identities were collapsed across physical models");
}

static void run_authored_dye_palette_self_test() {
    TextureBinding dyed_base;
    dyed_base.role = "base";
    dyed_base.source_path = "vest_base.dds";
    dyed_base.archive_path = "character/texture/vest_base.dds";
    dyed_base.parameter_name = "_baseColorTexture";
    dyed_base.sidecar_path = "character/modelproperty/vest.pac_xml";
    dyed_base.material_wrapper_index = 9;
    dyed_base.material_parameter_names =
        "_dyeingColorMaskR,_dyeingColorMaskG,_dyeingColorMaskB";
    TextureBinding dye_selector;
    dye_selector.role = "material";
    dye_selector.source_path = "vest_ma.dds";
    dye_selector.archive_path = "character/texture/vest_ma.dds";
    dye_selector.parameter_name = "_colorBlendingMaskTexture";
    dye_selector.sidecar_path = dyed_base.sidecar_path;
    dye_selector.material_wrapper_index = dyed_base.material_wrapper_index;
    dye_selector.material_output_quality = "exact";
    const std::array<std::array<float, 4>, 3> dye_colors{{
        {0.10f, 0.75f, 0.20f, 1.0f},
        {0.75f, 0.60f, 0.25f, 1.0f},
        {0.90f, 0.90f, 0.90f, 1.0f},
    }};
    dyed_base.color_blending_tints = dye_colors;
    std::vector<TextureBinding> dyed_bindings{dyed_base, dye_selector};
    std::vector<const TextureBinding*> dyed_binding_refs;
    for (const TextureBinding& binding : dyed_bindings) dyed_binding_refs.push_back(&binding);
    const std::vector<MaterialLayer> dye_seeds = compile_color_blending_seed_layers(
        dyed_binding_refs, &dyed_bindings.front(), NativeSubmesh{});
    require_material_contract(
        dye_seeds.size() == 3,
        "color blending palette did not publish three selector channels");
    require_material_contract(
        dye_seeds[0].layer_role == "color_seed"
            && dye_seeds[0].layer_channel == "r"
            && dye_seeds[1].layer_channel == "g"
            && dye_seeds[2].layer_channel == "b"
            && dye_seeds[0].mask_source == dye_selector.source_path
            && dye_seeds[1].tint == dye_colors[1],
        "color blending palette seed contract changed");

    dyed_bindings.front().material_parameter_names = "_dyeingColorMaskG";
    const std::vector<MaterialLayer> partial_dye_seeds = compile_color_blending_seed_layers(
        dyed_binding_refs, &dyed_bindings.front(), NativeSubmesh{});
    require_material_contract(
        partial_dye_seeds.size() == 3
            && partial_dye_seeds[0].diffuse_source.empty()
            && partial_dye_seeds[0].tint[3] == 0.0f
            && partial_dye_seeds[1].layer_channel == "g"
            && partial_dye_seeds[1].source_parameter == "_dyeingColorMaskG"
            && !partial_dye_seeds[1].diffuse_source.empty()
            && partial_dye_seeds[2].diffuse_source.empty()
            && partial_dye_seeds[2].tint[3] == 0.0f,
        "color blending palette exposed an unauthored channel resource");

    const std::vector<MaterialParameterRecord> cloth_0350_parameters{
        authored_color("_tintColorR", "#ffcaa3ff"),
        authored_color("_tintColorG", "#ffd455ff"),
        authored_color("_tintColorB", "#ffd455ff"),
        authored_color("_dyeingColorMaskG", "#ee5f5fff"),
        authored_color("_dyeingDetailLayerColorMaskG", "#ffd06cff"),
        authored_color("_dyeingDetailLayerColorMaskB", "#ffd06cff"),
    };
    TextureBinding cloth_0350_base = dyed_base;
    cloth_0350_base.material_parameter_names =
        joined_parameter_names_with_color_seed_sources(cloth_0350_parameters);
    for (size_t channel = 0; channel < cloth_0350_base.color_blending_tints.size(); ++channel) {
        cloth_0350_base.color_blending_tints[channel] = tint_for_layer(
            cloth_0350_parameters, "color_seed", std::string(1, "rgb"[channel]));
    }
    TextureBinding cloth_0350_selector = dye_selector;
    std::vector<TextureBinding> cloth_0350_bindings{cloth_0350_base, cloth_0350_selector};
    std::vector<const TextureBinding*> cloth_0350_refs;
    for (const TextureBinding& binding : cloth_0350_bindings) cloth_0350_refs.push_back(&binding);
    const std::vector<MaterialLayer> cloth_0350_seeds = compile_color_blending_seed_layers(
        cloth_0350_refs, &cloth_0350_bindings.front(), NativeSubmesh{});
    require_material_contract(
        cloth_0350_seeds.size() == 3
            && cloth_0350_seeds[0].source_parameter.empty()
            && cloth_0350_seeds[1].source_parameter == "_dyeingColorMaskG"
            && cloth_0350_seeds[2].source_parameter.empty()
            && cloth_0350_seeds[0].tint[3] == 0.0f
            && cloth_0350_seeds[2].tint[3] == 0.0f
            && cloth_0350_seeds[1].tint[0] > 0.92f
            && cloth_0350_seeds[1].tint[1] < 0.38f,
        "0350 cloth did not keep absent base dyes transparent around its authored red channel");

    const std::vector<MaterialParameterRecord> plate_0350_parameters{
        authored_color("_dyeingDetailLayerColorMaskR", "#ffdc85ff"),
        authored_color("_dyeingDetailLayerColorMaskG", "#ffdc85ff"),
        authored_color("_dyeingDetailLayerColorMaskB", "#ffdc85ff"),
    };
    TextureBinding plate_0350_base = dyed_base;
    plate_0350_base.material_parameter_names =
        joined_parameter_names_with_color_seed_sources(plate_0350_parameters);
    for (size_t channel = 0; channel < plate_0350_base.color_blending_tints.size(); ++channel) {
        plate_0350_base.color_blending_tints[channel] = tint_for_layer(
            plate_0350_parameters, "color_seed", std::string(1, "rgb"[channel]));
    }
    TextureBinding plate_0350_selector = dye_selector;
    std::vector<TextureBinding> plate_0350_bindings{plate_0350_base, plate_0350_selector};
    std::vector<const TextureBinding*> plate_0350_refs;
    for (const TextureBinding& binding : plate_0350_bindings) plate_0350_refs.push_back(&binding);
    const std::vector<MaterialLayer> plate_0350_seeds = compile_color_blending_seed_layers(
        plate_0350_refs, &plate_0350_bindings.front(), NativeSubmesh{});
    require_material_contract(
        plate_0350_seeds.empty(),
        "0350 plate detail dyes were promoted into the base colour selector");

    const std::vector<MaterialParameterRecord> zero_alpha_parameters{
        authored_color("_dyeingColorMaskG", "#ee5f5f00"),
    };
    require_material_contract(
        tint_for_layer(zero_alpha_parameters, "color_seed", "g")[3] == 0.0f
            && color_seed_parameter_name_for_channel(
                zero_alpha_parameters, "g").empty(),
        "zero-alpha base dye remained visible in the colour selector");
}

static void run_material_parameter_transport_self_test() {
    const std::vector<MaterialParameterRecord> transport_parameters{
        authored_color("_dyeingColorMaskG", "#ee5f5fff"),
        authored_integer("byte4", "_dyeingTransformProperty0", "4294967295"),
        authored_integer("byte4", "_dyeingTransformProperty1", "16777215"),
        authored_integer("byte4", "_dyeingTransformProperty3", "65535"),
        authored_integer("byte4", "_dyeingPropertyBlend", "16843009"),
        authored_integer("byte4", "_dyeingGlobalOpacity", "16777215"),
        authored_integer("bitflag32", "_colorBlendingFlag", "4095"),
        authored_integer("bitflag32", "_grimeBlendingFlag", "7"),
        {"float", "_unrelatedPhysicsValue", "2", 2.0f, true},
    };
    const std::vector<MaterialParameterRecord> filtered =
        filtered_preview_material_parameters(transport_parameters);
    require_material_contract(
        filtered.size() == transport_parameters.size()
            && std::any_of(filtered.begin(), filtered.end(), [](const MaterialParameterRecord& parameter) {
                return parameter.name == "_unrelatedPhysicsValue";
            }),
        "PAC material parameter transport did not conserve every declared field");
    std::ostringstream parameter_json;
    append_material_parameter_records_json(parameter_json, filtered);
    require_material_contract(
        parameter_json.str().find("\"parameter_kind\":\"color\"") != std::string::npos
            && parameter_json.str().find("\"parameter_name\":\"_dyeingTransformProperty3\"")
                != std::string::npos
            && parameter_json.str().find("\"integer_value\":4294967295") != std::string::npos
            && parameter_json.str().find("\"color_value\":[0.933") != std::string::npos,
        "PAC material parameter JSON no longer matches the Python consumer shape");

    NativePackage unresolved_texture_package;
    NativeMaterialConservationRow unresolved_texture_row;
    unresolved_texture_row.logical_graph_edge = true;
    unresolved_texture_row.parameter.kind = "texture";
    unresolved_texture_row.parameter.name = "_baseColorTexture";
    unresolved_texture_row.parameter.texture_path = "missing.dds";
    unresolved_texture_package.material_conservation_rows.push_back(unresolved_texture_row);
    const std::string unresolved_texture_json =
        native_material_conservation_json(unresolved_texture_package);
    require_material_contract(
        unresolved_texture_json.find("\"unresolved_texture_count\":1") != std::string::npos
            && unresolved_texture_json.find("\"conserved\":false") != std::string::npos,
        "unresolved source DDS was reported as a conserved material graph");
}

static void run_material_source_resolution_self_test() {
    EntryJob source_resolution_job;
    ArchiveEntryRef source_resolution_sidecar;
    source_resolution_sidecar.path = "character/modelproperty/samuel.pac_xml";
    PamtIndex corrected_source_index;
    ArchiveEntryRef corrected_source;
    corrected_source.path = "character/texture/cd_phw_00_sho_belt_00_0161_disp.dds";
    corrected_source.basename = "cd_phw_00_sho_belt_00_0161_disp.dds";
    corrected_source.extension = ".dds";
    corrected_source_index.by_basename[lower_copy(corrected_source.basename)].push_back(
        corrected_source);
    SidecarTextureRef malformed_source_ref;
    malformed_source_ref.path =
        "character/texturecd_phw_00_sho_belt_00_0161_disp.dds";
    const std::optional<ResolvedSidecarTextureCandidate> corrected_resolution =
        resolve_sidecar_texture_candidate(
            source_resolution_job,
            corrected_source_index,
            source_resolution_sidecar,
            malformed_source_ref,
            nullptr);
    require_material_contract(
        corrected_resolution.has_value()
            && corrected_resolution->entry.path == corrected_source.path
            && corrected_resolution->resolution == "corrected_missing_separator"
            && corrected_resolution->declared_source_missing,
        "source-authored missing texture separator was not corrected explicitly");

    TechniqueIndex family_default_index;
    const std::string cloth_family = "skinnedmeshcloth_ver2";
    const std::string emissive_family = "skinnedmeshemissive_ver2";
    const std::string standard_group = "skinnedmeshstandardparameterset_ver2";
    family_default_index.family_source_by_name[cloth_family] =
        "material/dist/skinnedmeshcloth_ver2.material";
    family_default_index.family_source_by_name[emissive_family] =
        "material/dist/skinnedmeshemissive_ver2.material";
    family_default_index.group_source_by_name[standard_group] =
        "material/dist/skinnedmeshparameters.xml";
    family_default_index.group_names_by_family[cloth_family].push_back(standard_group);
    TechniqueParameterInfo family_overlay_parameter;
    family_overlay_parameter.name = "_overlayColorTexture";
    family_overlay_parameter.type = "Texture";
    family_overlay_parameter.default_value = "texture/nonetexture0xff888888.dds";
    family_overlay_parameter.default_source_path =
        "material/dist/skinnedmeshparameters.xml";
    family_overlay_parameter.declaration_source_path =
        "material/dist/skinnedmeshparameters.xml";
    family_overlay_parameter.parameter_group_name = standard_group;
    family_overlay_parameter.declared = true;
    family_default_index.parameter_groups_by_name[standard_group].emplace(
        lower_copy(family_overlay_parameter.name), family_overlay_parameter);
    rebuild_resolved_technique_parameters(family_default_index);
    const TechniqueParameterInfo* exact_cloth_overlay = technique_parameter_for_name(
        family_default_index, "_overlayColorTexture", "SkinnedMeshCloth_Ver2");
    require_material_contract(
        exact_cloth_overlay != nullptr
            && exact_cloth_overlay->default_value
                == "texture/nonetexture0xff888888.dds"
            && exact_cloth_overlay->included_by_source_path
                == "material/dist/skinnedmeshcloth_ver2.material"
            && technique_parameter_for_name(
                family_default_index,
                "_overlayColorTexture",
                "SkinnedMeshEmissive_Ver2") == nullptr,
        "material defaults were not restricted to the exact active family and its groups");

    PamtIndex technique_default_index;
    ArchiveEntryRef technique_default_source;
    technique_default_source.path = "texture/nonetexture0xff888888.dds";
    technique_default_source.basename = "nonetexture0xff888888.dds";
    technique_default_source.extension = ".dds";
    technique_default_index.by_basename[lower_copy(technique_default_source.basename)].push_back(
        technique_default_source);
    SidecarTextureRef missing_overlay_ref;
    missing_overlay_ref.path = "character/texture/missing_overlay.dds";
    TechniqueParameterInfo overlay_parameter;
    overlay_parameter.name = "_overlayColorTexture";
    overlay_parameter.type = "Texture";
    overlay_parameter.default_value = "texture/nonetexture0xff888888.dds";
    overlay_parameter.default_source_path = "material/dist/standard_ver2.material";
    overlay_parameter.declared = true;
    const std::optional<ResolvedSidecarTextureCandidate> default_resolution =
        resolve_sidecar_texture_candidate(
            source_resolution_job,
            technique_default_index,
            source_resolution_sidecar,
            missing_overlay_ref,
            &overlay_parameter);
    require_material_contract(
        default_resolution.has_value()
            && default_resolution->entry.path == technique_default_source.path
            && default_resolution->resolution
                == "technique_default_after_missing_declared_source"
            && default_resolution->detail.find(
                "technique_source:material/dist/standard_ver2.material")
                != std::string::npos
            && default_resolution->declared_source_missing,
        "missing declared DDS did not resolve through its authored technique default");

    NativePackage resolved_source_package;
    NativeMaterialConservationRow resolved_source_row;
    resolved_source_row.logical_graph_edge = true;
    resolved_source_row.texture_resolved = true;
    resolved_source_row.parameter.kind = "texture";
    resolved_source_row.parameter.name = "_overlayColorTexture";
    resolved_source_row.parameter.texture_path = missing_overlay_ref.path;
    resolved_source_row.resolved_source_path = "C:/cache/default.dds";
    resolved_source_row.resolved_archive_path = technique_default_source.path;
    resolved_source_row.source_resolution = default_resolution->resolution;
    resolved_source_row.source_resolution_detail = default_resolution->detail;
    resolved_source_row.declared_source_missing = true;
    resolved_source_package.material_conservation_rows.push_back(resolved_source_row);
    const std::string resolved_source_json =
        native_material_conservation_json(resolved_source_package);
    require_material_contract(
        resolved_source_json.find(
            "\"resolved_archive_path\":\"texture/nonetexture0xff888888.dds\"")
                != std::string::npos
            && resolved_source_json.find(
                "\"source_resolution\":\"technique_default_after_missing_declared_source\"")
                != std::string::npos
            && resolved_source_json.find("\"declared_source_missing\":true")
                != std::string::npos
            && resolved_source_json.find("\"conserved\":true") != std::string::npos,
        "resolved logical edge omitted declared-versus-actual source provenance");
}

static void run_material_hint_authority_self_test() {
    TextureBinding authored_anisotropy_binding;
    MaterialParameterRecord authored_anisotropy_parameter;
    authored_anisotropy_parameter.kind = "float";
    authored_anisotropy_parameter.name = "_anisotropyStrength";
    authored_anisotropy_parameter.numeric_value = 0.0f;
    authored_anisotropy_parameter.has_numeric = true;
    authored_anisotropy_binding.material_parameters.push_back(
        authored_anisotropy_parameter);
    const NativeMaterialHints authored_anisotropy_hints =
        material_hints_for_bindings({&authored_anisotropy_binding});
    require_material_contract(
        authored_anisotropy_hints.anisotropy_authored,
        "authored zero anisotropy did not suppress family fallback");
    SurfaceProfile profile_authority;
    profile_authority.fallback_height_scale = 0.95f;
    profile_authority.fallback_anisotropy = 0.65f;
    profile_authority.anisotropy_authored = true;
    NativeMaterialHints profile_hints;
    profile_hints.height_scale = 0.37f;
    profile_hints = resolve_surface_profile_fallbacks(profile_hints, profile_authority);
    require_material_contract(
        std::abs(profile_hints.height_scale - 0.37f) < 0.0001f
            && !profile_authority.height_scale_fallback_applied
            && !profile_authority.anisotropy_fallback_applied,
        "surface profile exceeded authored roughness/metalness/specular/anisotropy authority");

    TextureBinding reliable_chainmail_base;
    reliable_chainmail_base.role = "base";
    reliable_chainmail_base.source_path = "chainmail.dds";
    reliable_chainmail_base.archive_path = "character/texture/chainmail.dds";
    reliable_chainmail_base.parameter_name = "_baseColorTexture";
    reliable_chainmail_base.visible_class = "primary_visible";
    reliable_chainmail_base.material_output_quality = "exact";
    reliable_chainmail_base.source_authority = "exact_sidecar";
    reliable_chainmail_base.tint_color = {0.71f, 0.47f, 0.17f, 1.0f};
    MaterialLayer masked_chainmail_tint;
    masked_chainmail_tint.layer_role = "grime";
    masked_chainmail_tint.mask_source = "chainmail_ma.dds";
    masked_chainmail_tint.tint = reliable_chainmail_base.tint_color;
    NativeSubmesh chainmail_mesh;
    chainmail_mesh.material = "FS_PHM_00_UB_0003_00_01_01";
    chainmail_mesh.source_model_path = "character/model/armor/9_upperbody/chainmail.pac";
    std::array<float, 4> promoted_chainmail_tint{1.0f, 1.0f, 1.0f, 1.0f};
    require_material_contract(
        !preview_sidecar_tint_for_surface(
            &reliable_chainmail_base,
            chainmail_mesh,
            {MaterialLayer{}, masked_chainmail_tint},
            &promoted_chainmail_tint),
        "masked apparel tint escaped into the reliable base texture");
}

static void run_layer_base_rejects_global_auxiliaries_self_test(const std::vector<TextureBinding>& layer_bindings, const NativeSubmesh& mesh, const NativeMaterialHints& hints) {
    const std::vector<const TextureBinding*> selector_only_refs{
        &layer_bindings[0], &layer_bindings[1], &layer_bindings[5], &layer_bindings[7]};
    const std::vector<MaterialLayer> selector_only = compile_material_layers(
        selector_only_refs,
        mesh,
        &layer_bindings[0],
        &layer_bindings[5],
        &layer_bindings[1],
        &layer_bindings[7],
        nullptr,
        hints,
        "mesh_base_first");
    require_material_contract(
        !selector_only.empty()
            && selector_only.front().material_source.empty()
            && selector_only.front().normal_source.empty()
            && selector_only.front().height_source.empty(),
        "owner-global inputs escaped into a layer-channel base surface");
}

static void run_bounded_material_dependencies_self_test() {
    EntryJob bounded_job;
    bounded_job.archive_dependency_entries_complete = true;
    bounded_job.entry.path = "character/model/example.pac";
    bounded_job.entry.basename = "example.pac";
    bounded_job.entry.extension = ".pac";
    bounded_job.entry.pamt_path = "missing/0.pamt";
    ArchiveEntryRef bounded_sidecar;
    bounded_sidecar.path = "character/model/example.pac_xml";
    bounded_sidecar.basename = "example.pac_xml";
    bounded_sidecar.extension = ".pac_xml";
    bounded_sidecar.pamt_path = "missing/0.pamt";
    bounded_job.archive_dependency_entries.push_back(bounded_sidecar);
    const PamtIndex bounded_index = build_bounded_pamt_index(bounded_job);
    require_material_contract(
        bounded_index.entry_count == 2 && bounded_index.material_sidecars.size() == 1,
        "bounded preview dependencies did not form a complete in-memory index");
    reset_archive_lite_lookup_diagnostics();
    const std::vector<ArchiveEntryRef> bounded_default_miss =
        lookup_basename_candidates_across_package(
            bounded_job,
            bounded_index,
            "nonetexture0xff888888.dds",
            96,
            true);
    const bool recorded_bounded_default_lookup = std::any_of(
        g_archive_lite_dependency_queries.begin(),
        g_archive_lite_dependency_queries.end(),
        [](const ArchiveLiteDependencyQuery& query) {
            return query.basename == "nonetexture0xff888888.dds"
                && query.scope == "bounded_dependencies";
        });
    const bool recorded_authoritative_default_fallback = std::any_of(
        g_archive_lite_dependency_queries.begin(),
        g_archive_lite_dependency_queries.end(),
        [](const ArchiveLiteDependencyQuery& query) {
            return query.basename == "nonetexture0xff888888.dds"
                && query.scope == "package_scan_fallback";
        });
    require_material_contract(
        bounded_default_miss.empty()
            && recorded_bounded_default_lookup
            && recorded_authoritative_default_fallback,
        "bounded dependency miss suppressed the authoritative technique-default lookup");
    reset_archive_lite_lookup_diagnostics();
}

static void run_aliased_wrapper_support_self_test() {
    NativeSubmesh aliased_owner_mesh;
    aliased_owner_mesh.material = "owned_surface";
    aliased_owner_mesh.name = "owned_surface";
    aliased_owner_mesh.source_model_path = "character/model/component.pac";
    aliased_owner_mesh.source_local_submesh_index = 0;
    MaterialParameterRecord aliased_base_parameter;
    aliased_base_parameter.kind = "texture";
    aliased_base_parameter.name = "_baseColorTexture";
    aliased_base_parameter.texture_path = "character/texture/owned_surface.dds";
    MaterialParameterRecord aliased_support_parameter;
    aliased_support_parameter.kind = "texture";
    aliased_support_parameter.name = "_detailMaskTexture";
    aliased_support_parameter.texture_path = "character/texture/cd_common_default_mg.dds";
    MaterialWrapperDeclaration aliased_declaration;
    aliased_declaration.material_name = "legacy_alias";
    aliased_declaration.owner_wrapper_item_id = "42";
    aliased_declaration.material_wrapper_index = 0;
    aliased_declaration.material_parameters = {
        aliased_base_parameter,
        aliased_support_parameter,
    };
    SidecarTextureRef aliased_support_ref;
    aliased_support_ref.path = aliased_support_parameter.texture_path;
    aliased_support_ref.parameter_name = aliased_support_parameter.name;
    aliased_support_ref.material_name = aliased_declaration.material_name;
    aliased_support_ref.owner_wrapper_item_id = aliased_declaration.owner_wrapper_item_id;
    aliased_support_ref.material_wrapper_index = aliased_declaration.material_wrapper_index;
    ParsedMaterialSidecar aliased_parsed;
    aliased_parsed.declarations.push_back(aliased_declaration);
    const std::vector<NativeSubmesh> aliased_meshes{aliased_owner_mesh};
    require_material_contract(
        !sidecar_ref_matches_meshes(
            aliased_support_ref,
            "component",
            false,
            1,
            aliased_meshes,
            "component")
            && sidecar_ref_owner_declaration_matches_meshes(
                aliased_parsed,
                aliased_support_ref,
                "component",
                false,
                1,
                aliased_meshes,
                "component"),
        "an owned wrapper support texture was discarded by its generic DDS name");
}

static void run_color_blending_palette_contract_self_test() {
    run_material_declaration_conservation_self_test();

    run_authored_dye_palette_self_test();

    run_material_parameter_transport_self_test();

    run_material_source_resolution_self_test();

    run_material_hint_authority_self_test();
}
