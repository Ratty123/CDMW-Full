static void run_base_layer_material_companion_contract_self_test() {
    TextureBinding layer_base;
    layer_base.role = "base";
    layer_base.source_path = "cd_metal_rust_01.dds";
    layer_base.archive_path = "character/texture/cd_metal_rust_01.dds";
    layer_base.parameter_name = "_grimeDiffuseTextureB";
    layer_base.layer_role = "grime";
    layer_base.layer_channel = "b";
    layer_base.sidecar_path = "character/modelproperty/sword_0002.pac_xml";
    layer_base.material_wrapper_index = 1;
    layer_base.shader_rule = "standard_v2";

    TextureBinding color_selector;
    color_selector.role = "material";
    color_selector.source_path = "cd_phm_01_handle_0023_ma.dds";
    color_selector.archive_path = "character/texture/cd_phm_01_handle_0023_ma.dds";
    color_selector.parameter_name = "_colorBlendingMaskTexture";
    color_selector.layer_role = "material_response";
    color_selector.layer_channel = "b";
    color_selector.sidecar_path = layer_base.sidecar_path;
    color_selector.material_wrapper_index = layer_base.material_wrapper_index;

    TextureBinding wrong_wrapper_surface;
    wrong_wrapper_surface.role = "material";
    wrong_wrapper_surface.source_path = "wrong_wrapper_sp.dds";
    wrong_wrapper_surface.parameter_name = "_grimeMaterialTextureB";
    wrong_wrapper_surface.layer_role = layer_base.layer_role;
    wrong_wrapper_surface.layer_channel = layer_base.layer_channel;
    wrong_wrapper_surface.sidecar_path = layer_base.sidecar_path;
    wrong_wrapper_surface.material_wrapper_index = 2;

    TextureBinding wrong_channel_surface = wrong_wrapper_surface;
    wrong_channel_surface.source_path = "wrong_channel_sp.dds";
    wrong_channel_surface.layer_channel = "r";
    wrong_channel_surface.material_wrapper_index = layer_base.material_wrapper_index;

    TextureBinding exact_surface = wrong_wrapper_surface;
    exact_surface.source_path = "cd_metal_rust_01_sp.dds";
    exact_surface.archive_path = "character/texture/cd_metal_rust_01_sp.dds";
    exact_surface.material_wrapper_index = layer_base.material_wrapper_index;

    TextureBinding owner_normal;
    owner_normal.role = "normal";
    owner_normal.source_path = "cd_phm_01_handle_0023_n.dds";
    owner_normal.archive_path = "character/texture/cd_phm_01_handle_0023_n.dds";
    owner_normal.parameter_name = "_normalTexture";
    owner_normal.layer_role = "normal";
    owner_normal.sidecar_path = layer_base.sidecar_path;
    owner_normal.material_wrapper_index = layer_base.material_wrapper_index;

    TextureBinding exact_normal = owner_normal;
    exact_normal.source_path = "cd_metal_rust_01_n.dds";
    exact_normal.archive_path = "character/texture/cd_metal_rust_01_n.dds";
    exact_normal.parameter_name = "_grimeNormalTextureB";
    exact_normal.layer_role = layer_base.layer_role;
    exact_normal.layer_channel = layer_base.layer_channel;

    TextureBinding owner_height;
    owner_height.role = "height";
    owner_height.source_path = "cd_phm_01_handle_0023_disp.dds";
    owner_height.archive_path = "character/texture/cd_phm_01_handle_0023_disp.dds";
    owner_height.parameter_name = "_heightTexture";
    owner_height.layer_role = "height";
    owner_height.sidecar_path = layer_base.sidecar_path;
    owner_height.material_wrapper_index = layer_base.material_wrapper_index;

    TextureBinding exact_height = owner_height;
    exact_height.source_path = "cd_metal_rust_01_disp.dds";
    exact_height.archive_path = "character/texture/cd_metal_rust_01_disp.dds";
    exact_height.parameter_name = "_grimeHeightTextureB";
    exact_height.layer_role = layer_base.layer_role;
    exact_height.layer_channel = layer_base.layer_channel;

    const std::vector<TextureBinding> layer_bindings{
        layer_base,
        color_selector,
        wrong_wrapper_surface,
        wrong_channel_surface,
        exact_surface,
        owner_normal,
        exact_normal,
        owner_height,
        exact_height,
    };
    std::vector<const TextureBinding*> layer_refs;
    for (const TextureBinding& binding : layer_bindings) layer_refs.push_back(&binding);
    NativeSubmesh mesh;
    NativeMaterialHints hints;
    const std::vector<MaterialLayer> compiled = compile_material_layers(
        layer_refs,
        mesh,
        &layer_bindings[0],
        &layer_bindings[5],
        &layer_bindings[1],
        &layer_bindings[7],
        nullptr,
        hints,
        "mesh_base_first");
    require_material_contract(
        !compiled.empty()
            && compiled.front().material_source == exact_surface.source_path
            && compiled.front().material_archive_path == exact_surface.archive_path
            && compiled.front().normal_source == exact_normal.source_path
            && compiled.front().normal_archive_path == exact_normal.archive_path
            && compiled.front().height_source == exact_height.source_path
            && compiled.front().height_archive_path == exact_height.archive_path,
        "layer-channel base did not select its exact same-wrapper auxiliary companions");

    run_layer_base_rejects_global_auxiliaries_self_test(layer_bindings, mesh, hints);

    TextureBinding direct_base = layer_base;
    direct_base.source_path = "direct_base.dds";
    direct_base.parameter_name = "_baseColorTexture";
    direct_base.layer_role = "base";
    direct_base.layer_channel.clear();
    TextureBinding direct_surface = color_selector;
    direct_surface.source_path = "direct_sp.dds";
    direct_surface.archive_path = "character/texture/direct_sp.dds";
    direct_surface.parameter_name = "_materialTexture";
    direct_surface.layer_role = "material_response";
    direct_surface.layer_channel.clear();
    const std::vector<const TextureBinding*> direct_refs{
        &direct_base, &direct_surface, &owner_normal, &owner_height};
    const std::vector<MaterialLayer> direct = compile_material_layers(
        direct_refs,
        mesh,
        &direct_base,
        &owner_normal,
        &direct_surface,
        &owner_height,
        nullptr,
        hints,
        "mesh_base_first");
    require_material_contract(
        !direct.empty()
            && direct.front().material_source == direct_surface.source_path
            && direct.front().normal_source == owner_normal.source_path
            && direct.front().height_source == owner_height.source_path,
        "ordinary direct surface inputs were displaced by layer companion selection");
}

static void run_layer_selector_surface_authority_contract_self_test() {
    NativeSubmesh mesh;
    mesh.name = "CD_PHM_01_Handle_0023_mg";
    mesh.material = mesh.name;

    TextureBinding color_selector;
    color_selector.role = "material";
    color_selector.source_path = "cd_phm_01_handle_0023_ma.dds";
    color_selector.archive_path = "character/texture/cd_phm_01_handle_0023_ma.dds";
    color_selector.texture_name = "cd_phm_01_handle_0023_ma.dds";
    color_selector.parameter_name = "_colorBlendingMaskTexture";
    color_selector.packed_channels = "layer:color_blending_mask";
    color_selector.semantic_type = "packed_material";
    color_selector.semantic_subtype = "material_mask";
    color_selector.material_name = mesh.material;

    TextureBinding detail_selector = color_selector;
    detail_selector.source_path = "cd_phm_01_handle_0023_mg.dds";
    detail_selector.archive_path = "character/texture/cd_phm_01_handle_0023_mg.dds";
    detail_selector.texture_name = "cd_phm_01_handle_0023_mg.dds";
    detail_selector.parameter_name = "_detailMaskTexture";
    detail_selector.packed_channels = "layer:detail_grime_dye_mask";
    detail_selector.semantic_type = "detail_mask";
    detail_selector.semantic_subtype = "detail_mask";

    TextureBinding exact_layer_surface = color_selector;
    exact_layer_surface.source_path = "cd_metal_rust_01_sp.dds";
    exact_layer_surface.archive_path = "character/texture/cd_metal_rust_01_sp.dds";
    exact_layer_surface.texture_name = "cd_metal_rust_01_sp.dds";
    exact_layer_surface.parameter_name = "_grimeMaterialTextureB";
    exact_layer_surface.packed_channels = "layer:material_response,g=roughness,b=metalness";
    exact_layer_surface.semantic_subtype = "material_mask";
    exact_layer_surface.layer_role = "grime";
    exact_layer_surface.layer_channel = "b";

    TextureBinding global_surface = exact_layer_surface;
    global_surface.source_path = "authored_orm.dds";
    global_surface.archive_path = "character/texture/authored_orm.dds";
    global_surface.texture_name = "authored_orm.dds";
    global_surface.parameter_name = "_materialTexture";
    global_surface.packed_channels = "r=occlusion,g=roughness,b=metalness";
    global_surface.layer_role.clear();
    global_surface.layer_channel.clear();

    require_material_contract(
        binding_is_layer_selector_mask(color_selector)
            && binding_is_layer_selector_mask(detail_selector),
        "PAC _ma/_mg selector masks lost their layer-mask classification");
    require_material_contract(
        support_binding_rejected_before_scoring(
            color_selector, mesh, "material", false, nullptr)
            && support_binding_rejected_before_scoring(
                detail_selector, mesh, "material", false, nullptr),
        "PAC _ma/_mg selector masks remained eligible for the global material slot");
    require_material_contract(
        !promoted_global_material_response(&color_selector)
            && !promoted_global_material_response(&detail_selector)
            && material_response_disposition(&color_selector, nullptr, "metal") == "layer_only"
            && material_response_disposition(&detail_selector, nullptr, "metal") == "layer_only",
        "PAC layer selectors were promoted to roughness/metalness authority");
    require_material_contract(
        !binding_is_layer_selector_mask(exact_layer_surface)
            && !promoted_global_material_response(&exact_layer_surface)
            && binding_declares_readable_surface_response(&exact_layer_surface)
            && material_response_disposition(&exact_layer_surface, nullptr, "metal") == "layer_only",
        "exact _sp layer companion lost its packed-surface authority");
    require_material_contract(
        promoted_global_material_response(&global_surface)
            && material_response_disposition(&global_surface, nullptr, "metal")
                == "promoted_metallic_roughness",
        "authored global ORM response was rejected with the selector masks");

    const std::vector<TextureBinding> candidates{color_selector, exact_layer_surface};
    require_material_contract(
        best_binding_for_role(candidates, mesh, "material") == nullptr,
        "PAC masked _sp layer companion remained eligible for the global material slot");
}

static void run_embedded_mesh_owner_contract_self_test() {
    NativeSubmesh first;
    first.source_model_path = "character/model/component_a.pac";
    first.source_local_submesh_index = 3;
    NativeSubmesh second = first;
    second.source_local_submesh_index = 4;
    const std::string first_owner = embedded_mesh_owner_id(first, first.source_model_path);
    const std::string second_owner = embedded_mesh_owner_id(second, second.source_model_path);
    require_material_contract(
        !first_owner.empty()
            && first_owner.size() <= 64
            && first_owner != second_owner
            && embedded_mesh_owner_index(first) == 3,
        "embedded mesh texture lost its deterministic owning submesh identity");

    TextureBinding first_edge;
    first_edge.owner_wrapper_item_id = first_owner;
    first_edge.parameter_name = "embedded_mesh_reference";
    first_edge.archive_path = "character/texture/shared.dds";
    TextureBinding duplicate = first_edge;
    TextureBinding other_owner = first_edge;
    other_owner.owner_wrapper_item_id = second_owner;
    TextureBinding other_parameter = first_edge;
    other_parameter.parameter_name = "_detailDiffuseMaskR";
    TextureBinding other_path = first_edge;
    other_path.archive_path = "character/texture/other.dds";
    require_material_contract(
        native_texture_edge_key(first_edge) == native_texture_edge_key(duplicate)
            && native_texture_edge_key(first_edge) != native_texture_edge_key(other_owner)
            && native_texture_edge_key(first_edge) != native_texture_edge_key(other_parameter)
            && native_texture_edge_key(first_edge) != native_texture_edge_key(other_path),
        "native texture edge dedupe did not preserve owner, parameter, and DDS path");
}

static void run_skin_detail_support_contract_self_test() {
    require_material_contract(
        role_from_parameter_shader_and_name(
            "_skinDetailMaskTexture", "skin", "body_m.dds") == "detail"
            && role_from_parameter_shader_and_name(
                "_skinDetailNormalTexture", "skin", "skin_detail_n.dds") == "normal"
            && role_from_parameter_shader_and_name(
                "_skinDetailMaterialTexture", "skin", "skin_detail_sp.dds") == "specular",
        "skin detail parameters lost their exact support roles");
    require_material_contract(
        layer_channel_from_parameter("_skinDetailMaskTexture") == "r",
        "skin detail mask did not retain its authored red channel");

    const std::vector<MaterialParameterRecord> head_parameters{
        {"float", "_skinDetailOpacity", "1.0", 1.0f, true},
        {"float", "_skinDetailScale", ".05", 0.05f, true},
    };
    const std::vector<MaterialParameterRecord> body_parameters{
        {"float", "_skinDetailOpacity", "1.0", 1.0f, true},
        {"float", "_skinDetailScale", ".02", 0.02f, true},
    };
    require_material_contract(
        std::abs(layer_weight_from_parameters(head_parameters, "detail", "r") - 1.0f) < 0.0001f
            && std::abs(skin_detail_scale_from_parameters(head_parameters) - 0.05f) < 0.0001f
            && std::abs(skin_detail_scale_from_parameters(body_parameters) - 0.02f) < 0.0001f,
        "skin detail opacity and scale were merged or clamped to generic detail defaults");

    TextureBinding base;
    base.role = "base";
    base.source_path = "body.dds";
    base.archive_path = "character/texture/body.dds";
    base.parameter_name = "_baseColorTexture";
    base.shader_family = "SkinnedMeshSkin";
    base.shader_rule = "skin";
    base.sidecar_path = "character/modelproperty/body.pac_xml";
    base.material_wrapper_index = 2;

    TextureBinding selector = base;
    selector.role = "detail";
    selector.source_path = "body_m.dds";
    selector.archive_path = "character/texture/body_m.dds";
    selector.parameter_name = "_skinDetailMaskTexture";
    selector.layer_role = "detail";
    selector.layer_channel = "r";
    selector.layer_weight = 1.0f;
    selector.detail_scale = 0.02f;
    selector.material_output_quality = "exact";
    selector.source_authority = "exact_sidecar";
    selector.packed_channels = "layer:detail_grime_dye_mask";

    TextureBinding detail_normal = selector;
    detail_normal.role = "normal";
    detail_normal.source_path = "skin_detail_n.dds";
    detail_normal.archive_path = "character/texture/skin_detail_n.dds";
    detail_normal.parameter_name = "_skinDetailNormalTexture";
    detail_normal.packed_channels = "normal_xy";

    TextureBinding detail_material = selector;
    detail_material.role = "specular";
    detail_material.source_path = "skin_detail_sp.dds";
    detail_material.archive_path = "character/texture/skin_detail_sp.dds";
    detail_material.parameter_name = "_skinDetailMaterialTexture";
    detail_material.packed_channels = "layer:material_response,g=roughness";

    const std::vector<TextureBinding> bindings{base, selector, detail_normal, detail_material};
    std::vector<const TextureBinding*> refs;
    for (const TextureBinding& binding : bindings) refs.push_back(&binding);
    NativeSubmesh mesh;
    mesh.material = "CD_PHM_00_Nude_0001";
    NativeMaterialHints hints;
    const std::vector<MaterialLayer> layers = compile_material_layers(
        refs, mesh, &bindings[0], nullptr, nullptr, nullptr, nullptr, hints, "mesh_base_first");
    require_material_contract(
        layers.size() == 2
            && layers[1].layer_role == "skin_detail"
            && layers[1].layer_channel == "r"
            && layers[1].diffuse_source.empty()
            && layers[1].mask_source == selector.source_path
            && layers[1].normal_source == detail_normal.source_path
            && layers[1].material_source == detail_material.source_path
            && std::abs(layers[1].weight - 1.0f) < 0.0001f
            && std::abs(layers[1].detail_scale - 0.02f) < 0.0001f,
        "held skin shader did not publish its support-only detail layer");
    require_material_contract(
        binding_is_layer_selector_mask(selector)
            && best_binding_for_role(bindings, mesh, "normal") == nullptr
            && best_binding_for_role(bindings, mesh, "specular") == nullptr,
        "skin support inputs escaped into whole-surface material slots");
}

static TextureBinding exact_layer_contract_binding(
    const std::string& role,
    const std::string& parameter,
    const std::string& source,
    const std::string& layer_role,
    const std::string& layer_channel,
    const std::string& shader_rule,
    int wrapper_index
) {
    TextureBinding binding;
    binding.role = role;
    binding.parameter_name = parameter;
    binding.source_path = source;
    binding.archive_path = "character/texture/" + source;
    binding.texture_name = source;
    binding.layer_role = layer_role;
    binding.layer_channel = layer_channel;
    binding.shader_rule = shader_rule;
    binding.shader_family = shader_rule == "emissive"
        ? "SkinnedMeshEmissive_Ver2" : "SkinnedMeshStandard";
    binding.sidecar_path = "character/modelproperty/weapon/layered_owner.pac_xml";
    binding.sidecar_kind = ".pac_xml";
    binding.material_name = "layered_owner";
    binding.material_wrapper_index = wrapper_index;
    binding.material_wrapper_order_authoritative = true;
    binding.source_authority = "exact_sidecar";
    binding.material_output_quality = "exact";
    binding.layer_weight = 0.45f;
    if (normalized_key(parameter) == "colorblendingmasktexture") {
        binding.packed_channels = "layer:color_blending_mask";
    } else if (normalized_key(parameter) == "detailmasktexture") {
        binding.packed_channels = "layer:detail_grime_dye_mask";
    }
    return binding;
}

static void run_exact_layer_owner_stack_contract_self_test() {
    NativeSubmesh mesh;
    mesh.name = "CD_WP_02_2H_0001";
    mesh.material = "layered_owner";
    mesh.source_model_path = "character/model/weapon/layered_owner.pac";
    mesh.source_local_submesh_index = 0;

    std::vector<TextureBinding> bindings;
    bindings.push_back(exact_layer_contract_binding(
        "base", "_baseColorTexture", "owner_base.dds", "base", "r", "emissive", 0));
    bindings.push_back(exact_layer_contract_binding(
        "detail", "_detailMaskTexture", "owner_detail_mask.dds", "detail", "b", "emissive", 0));
    bindings.push_back(exact_layer_contract_binding(
        "material", "_colorBlendingMaskTexture", "owner_color_region_mask.dds", "material_response", "b", "emissive", 0));
    bindings.push_back(exact_layer_contract_binding(
        "height", "_heightTexture", "owner_global_height.dds", "height", "r", "emissive", 0));

    for (const std::string& role : {std::string("detail"), std::string("grime")}) {
        for (char channel_char : std::string("rgb")) {
            const std::string channel(1, channel_char);
            const std::string title_channel(1, static_cast<char>(std::toupper(
                static_cast<unsigned char>(channel_char))));
            bindings.push_back(exact_layer_contract_binding(
                "base", "_" + role + "DiffuseMask" + title_channel,
                role + "_diffuse_" + channel + ".dds", role, channel, "emissive", 0));
            bindings.push_back(exact_layer_contract_binding(
                "normal", "_" + role + "NormalMask" + title_channel,
                role + "_normal_" + channel + ".dds", role, channel, "emissive", 0));
            bindings.push_back(exact_layer_contract_binding(
                "material", "_" + role + "MaterialMask" + title_channel,
                role + "_material_" + channel + ".dds", role, channel, "emissive", 0));
            bindings.push_back(exact_layer_contract_binding(
                "height", "_" + role + "HeightMask" + title_channel,
                role + "_height_" + channel + ".dds", role, channel, "emissive", 0));
        }
    }
    bindings.push_back(exact_layer_contract_binding(
        "normal", "_detailNormalMaskG", "wrong_wrapper_normal.dds",
        "detail", "g", "emissive", 1));
    bindings.push_back(exact_layer_contract_binding(
        "height", "_detailHeightMaskR", "wrong_channel_height.dds",
        "detail", "r", "emissive", 0));
    bindings.push_back(exact_layer_contract_binding(
        "base", "_detailDiffuseMaskG", "wrong_wrapper_diffuse.dds",
        "detail", "g", "emissive", 1));

    std::vector<const TextureBinding*> refs;
    for (const TextureBinding& binding : bindings) refs.push_back(&binding);
    NativeMaterialHints hints;
    const std::vector<MaterialLayer> layers = compile_material_layers(
        refs, mesh, &bindings[0], nullptr, nullptr, &bindings[3], nullptr,
        hints, "mesh_base_first");
    require_material_contract(
        layers.size() == 7,
        "exact emissive owner stack did not preserve all six authored overlays");
    for (size_t index = 1; index < layers.size(); ++index) {
        const MaterialLayer& layer = layers[index];
        const bool detail_layer = layer.layer_role == "detail";
        require_material_contract(
            !layer.diffuse_source.empty()
                && !layer.normal_source.empty()
                && !layer.material_source.empty()
                && !layer.height_source.empty()
                && layer.height_source != bindings[3].source_path
                && layer.normal_source != "wrong_wrapper_normal.dds"
                && layer.diffuse_source != "wrong_wrapper_diffuse.dds"
                && (!detail_layer
                    || (layer.mask_source == bindings[2].source_path
                        && layer.mask_parameter == bindings[2].parameter_name)),
            "exact layer companion escaped its sidecar, wrapper, role, or channel");
    }
}

static void run_cloth_normal_support_contract_self_test() {
    NativeSubmesh mesh;
    mesh.name = "CD_PTM_01_UB_0001";
    mesh.material = "CD_PHM_00_UB_0001";
    mesh.source_model_path = "character/model/1_pc/14_ptm/armor/9_upperbody/cd_ptm_01_ub_0001.pac";
    mesh.source_local_submesh_index = 0;

    TextureBinding base = exact_layer_contract_binding(
        "base", "_baseColorTexture", "cloth_base.dds", "base", "r", "standard", 0);
    base.sidecar_path = "character/modelproperty/1_pc/14_ptm/armor/9_upperbody/cd_ptm_01_ub_0001.pac_xml";
    base.pbd_simulation_material_name = "Lower_Fabric";
    TextureBinding selector = exact_layer_contract_binding(
        "material", "_maskTexture", "cloth_mask.dds", "material_response", "r", "standard", 0);
    selector.sidecar_path = base.sidecar_path;
    selector.pbd_simulation_material_name = base.pbd_simulation_material_name;
    TextureBinding detail_normal = exact_layer_contract_binding(
        "normal", "_detailNormalMaskR", "cloth_detail_n.dds", "detail", "r", "standard", 0);
    detail_normal.sidecar_path = base.sidecar_path;
    detail_normal.pbd_simulation_material_name = base.pbd_simulation_material_name;
    detail_normal.layer_weight = 0.185836f;
    TextureBinding inferred_diffuse = base;
    inferred_diffuse.source_path = "texture_family_sibling.dds";
    inferred_diffuse.archive_path = "character/texture/texture_family_sibling.dds";
    inferred_diffuse.parameter_name = "_baseColorTexture";
    inferred_diffuse.layer_role = "layer";
    inferred_diffuse.source_authority = "inferred_sibling";
    inferred_diffuse.material_output_quality = "inferred";

    const std::vector<TextureBinding> bindings{base, selector, detail_normal, inferred_diffuse};
    std::vector<const TextureBinding*> refs;
    for (const TextureBinding& binding : bindings) refs.push_back(&binding);
    NativeMaterialHints hints;
    const std::vector<MaterialLayer> layers = compile_material_layers(
        refs, mesh, &bindings[0], nullptr, nullptr, nullptr, nullptr,
        hints, "mesh_base_first");
    require_material_contract(
        layers.size() == 2
            && layers[1].layer_role == "cloth_detail"
            && layers[1].layer_channel == "r"
            && layers[1].diffuse_source.empty()
            && layers[1].material_source.empty()
            && layers[1].height_source.empty()
            && layers[1].normal_source == detail_normal.source_path
            && layers[1].mask_source == selector.source_path,
        "cloth support-only normal was dropped or gained an inferred diffuse surface");
}

static void run_shared_hair_identity_contract_self_test() {
    NativeSubmesh hair_uptail;
    hair_uptail.name = "CD_PHW_00_Hair_Uptail_00_0006_02";
    hair_uptail.material = "CD_PHM_00_Hair_0003";
    hair_uptail.source_model_path = "character/model/1_pc/2_phw/head/hair/cd_phw_00_hair_uptail_00_0006_02.pac";
    hair_uptail.source_local_submesh_index = 0;
    TextureBinding shared_hair_base;
    shared_hair_base.role = "base";
    shared_hair_base.source_path = "cd_phm_00_hair_0003.dds";
    shared_hair_base.archive_path = "character/texture/cd_phm_00_hair_0003.dds";
    shared_hair_base.texture_name = "cd_phm_00_hair_0003.dds";
    shared_hair_base.material_name = "CD_PHM_00_Hair_0003";
    shared_hair_base.sidecar_path = "character/modelproperty/1_pc/2_phw/head/hair/cd_phw_00_hair_00_0006_02.pac_xml";
    shared_hair_base.source_authority = "exact_sidecar";
    shared_hair_base.material_wrapper_order_authoritative = true;
    shared_hair_base.material_wrapper_index = 2;
    require_material_contract(
        material_identity_match_score(shared_hair_base, hair_uptail) > 0,
        "exact shared hair material did not cross its authored sibling wrapper");
}

static void run_head_eye_cover_identity_contract_self_test() {
    NativeSubmesh eye_cover;
    eye_cover.name = "CD_PHW_00_Head_00_0028_EyeCover";
    eye_cover.material = "cd_phw_00_head_00_0028_eyecover";
    eye_cover.source_local_submesh_index = 0;
    NativeSubmesh skin;
    skin.name = "CD_PHW_00_Head_00_0028";
    skin.material = "CD_PHW_00_Head_00_0028";
    skin.source_local_submesh_index = 1;
    TextureBinding eye_surface;
    eye_surface.role = "material";
    eye_surface.source_path = "cd_phw_00_eyecovermaterial_0001_sp.dds";
    eye_surface.archive_path = "character/texture/cd_phw_00_eyecovermaterial_0001_sp.dds";
    eye_surface.texture_name = "cd_phw_00_eyecovermaterial_0001_sp.dds";
    eye_surface.material_name = "cd_phw_00_head_00_0028_eyecover";
    eye_surface.material_wrapper_order_authoritative = true;
    eye_surface.material_wrapper_index = 0;
    const std::vector<NativeSubmesh> parts{eye_cover, skin};
    const std::vector<TextureBinding> bindings{eye_surface};
    require_material_contract(
        material_identity_match_score(bindings.front(), skin) == 0,
        "0028 eye-cover response matched the skin wrapper");
    require_material_contract(
        best_binding_for_role(bindings, skin, "material") == nullptr,
        "0028 skin selected the eye-cover response map");
    require_material_contract(
        relevant_bindings_for_mesh(bindings, parts, skin, {}).empty(),
        "0028 skin retained the eye-cover response binding");
    require_material_contract(
        best_binding_for_role(bindings, eye_cover, "material") == &bindings.front(),
        "0028 eye-cover lost its own response map");
}

static void run_cached_material_owner_contract_self_test() {
    NativeSubmesh left;
    left.material = "shared_cloth";
    left.name = "left";
    left.source_local_submesh_index = 0;
    NativeSubmesh right = left;
    right.name = "right";
    right.source_local_submesh_index = 1;
    const std::vector<NativeSubmesh> meshes{left, right};
    TextureBinding shared;
    shared.material_name = "shared_cloth";
    shared.texture_name = "shared_cloth_n.dds";
    shared.source_path = "shared_cloth_n.dds";
    shared.role = "normal";
    shared.material_wrapper_order_authoritative = true;
    shared.material_wrapper_index = 0;
    const std::vector<TextureBinding> bindings(9, shared);
    std::unordered_map<const TextureBinding*, int> owners;
    for (const TextureBinding& binding : bindings) {
        owners.emplace(&binding, binding_owner_submesh_local_index(meshes, binding));
    }
    for (const NativeSubmesh& mesh : meshes) {
        const auto uncached = relevant_bindings_for_mesh(bindings, meshes, mesh, {});
        const auto cached = relevant_bindings_for_mesh(bindings, meshes, mesh, {}, &owners);
        require_material_contract(cached == uncached && cached.size() == bindings.size(),
            "cached ownership changed shared-material bindings");
    }
    std::string bytes;
    for (int value = 0; value < 256; ++value) bytes.push_back(static_cast<char>(value));
    require_material_contract(
        compact_material_ascii_key(bytes) == std::regex_replace(bytes, std::regex("[^a-z0-9]+"), ""),
        "compact material keys changed byte filtering");
}

static void run_material_contract_self_test() {
    run_cached_material_owner_contract_self_test();
    run_embedded_mesh_owner_contract_self_test();
    run_bounded_material_dependencies_self_test();

    NativeSubmesh head;
    head.name = "head_skin";
    head.material = "head_skin";
    head.source_local_submesh_index = 0;
    NativeSubmesh hand;
    hand.name = "hand_skin";
    hand.material = "hand_skin";
    hand.source_local_submesh_index = 1;
    NativeSubmesh body;
    body.name = "body_skin";
    body.material = "body_skin";
    body.source_local_submesh_index = 2;
    const std::vector<NativeSubmesh> skin_parts{head, hand, body};

    TextureBinding head_surface;
    head_surface.role = "material";
    head_surface.source_path = "head_skin_sp.dds";
    head_surface.texture_name = "head_skin_sp.dds";
    head_surface.material_name = "head_skin";
    TextureBinding body_surface;
    body_surface.role = "material";
    body_surface.source_path = "body_skin_sp.dds";
    body_surface.texture_name = "body_skin_sp.dds";
    body_surface.material_name = "body_skin";
    const std::vector<TextureBinding> skin_bindings{head_surface, body_surface};

    require_material_contract(
        binding_owner_submesh_local_index(skin_parts, skin_bindings[0]) == 0,
        "head response did not resolve to head owner");
    require_material_contract(
        binding_owner_submesh_local_index(skin_parts, skin_bindings[1]) == 2,
        "body response did not resolve to body owner");
    const auto head_bindings = relevant_bindings_for_mesh(skin_bindings, skin_parts, head, {});
    require_material_contract(
        head_bindings.size() == 1 && head_bindings.front() == &skin_bindings[0],
        "cross-part response survived owner filtering");

    run_aliased_wrapper_support_self_test();

    NativeSubmesh shared_left;
    shared_left.name = "shared_left";
    shared_left.material = "shared_skin_m";
    shared_left.source_local_submesh_index = 3;
    NativeSubmesh shared_right;
    shared_right.name = "shared_right";
    shared_right.material = "shared_skin_m";
    shared_right.source_local_submesh_index = 4;
    TextureBinding shared_surface;
    shared_surface.role = "material";
    shared_surface.source_path = "shared_skin_m_sp.dds";
    shared_surface.texture_name = "shared_skin_m_sp.dds";
    shared_surface.material_name = "shared_skin_m";
    shared_surface.material_wrapper_order_authoritative = true;
    shared_surface.material_wrapper_index = 3;
    const std::vector<NativeSubmesh> shared_parts{shared_left, shared_right};
    require_material_contract(
        binding_owner_submesh_local_index(shared_parts, shared_surface) == -1,
        "shared material was assigned to one owner");
    const std::vector<TextureBinding> many_shared_bindings(9, shared_surface);
    const auto right_shared_bindings = relevant_bindings_for_mesh(
        many_shared_bindings,
        shared_parts,
        shared_right,
        {});
    require_material_contract(
        right_shared_bindings.size() == many_shared_bindings.size(),
        "shared material disappeared above the small-binding threshold");

    run_shared_hair_identity_contract_self_test();
    run_head_eye_cover_identity_contract_self_test();

    TextureBinding layer_height;
    layer_height.role = "height";
    layer_height.source_path = "detail_height.dds";
    layer_height.parameter_name = "_detailHeightMaskR";
    layer_height.layer_role = "detail";
    require_material_contract(
        support_binding_rejected_before_scoring(layer_height, body, "height", false, nullptr),
        "detail height was promoted to the global slot");
    TextureBinding authored_height;
    authored_height.role = "height";
    authored_height.source_path = "body_height.dds";
    authored_height.parameter_name = "_heightTexture";
    require_material_contract(
        !support_binding_rejected_before_scoring(authored_height, body, "height", false, nullptr),
        "authored global height was rejected");

    DecodedSurfaceEvidence decoded_metal;
    decoded_metal.decoded = true;
    decoded_metal.metal_coverage = 0.99f;
    MaterialCategoryEvidence skin_evidence;
    skin_evidence.strong_skin = true;
    skin_evidence.strong_nonmetal = true;
    require_material_contract(
        !decoded_surface_promotes_metal(decoded_metal, skin_evidence),
        "dominant packed blue overrode explicit skin evidence");
    MaterialCategoryEvidence metal_evidence;
    metal_evidence.strong_nonmetal = true;
    metal_evidence.cloth = true;
    require_material_contract(
        decoded_surface_promotes_metal(decoded_metal, metal_evidence),
        "incidental nonmetal evidence suppressed a metal-dominant control");

    run_color_blending_palette_contract_self_test();
    run_base_layer_material_companion_contract_self_test();
    run_layer_selector_surface_authority_contract_self_test();
    run_skin_detail_support_contract_self_test();
    run_exact_layer_owner_stack_contract_self_test();
    run_cloth_normal_support_contract_self_test();
}
