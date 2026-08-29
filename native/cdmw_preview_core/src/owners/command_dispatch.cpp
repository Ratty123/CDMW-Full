static void require_material_contract(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(std::string("material contract self-test failed: ") + message);
    }
}

static void run_color_blending_palette_contract_self_test() {
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

    TextureBinding dyed_base;
    dyed_base.role = "base";
    dyed_base.source_path = "vest_base.dds";
    dyed_base.archive_path = "character/texture/vest_base.dds";
    dyed_base.parameter_name = "_baseColorTexture";
    dyed_base.sidecar_path = "character/modelproperty/vest.pac_xml";
    dyed_base.material_wrapper_index = 9;
    dyed_base.material_parameter_names = "_tintColorR,_tintColorG,_tintColorB";
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
        dyed_binding_refs, &dyed_bindings.front());
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

static void run_material_contract_self_test() {
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

    NativeSubmesh head_0028_eye_cover;
    head_0028_eye_cover.name = "CD_PHW_00_Head_00_0028_EyeCover";
    head_0028_eye_cover.material = "cd_phw_00_head_00_0028_eyecover";
    head_0028_eye_cover.source_local_submesh_index = 0;
    NativeSubmesh head_0028_skin;
    head_0028_skin.name = "CD_PHW_00_Head_00_0028";
    head_0028_skin.material = "CD_PHW_00_Head_00_0028";
    head_0028_skin.source_local_submesh_index = 1;
    TextureBinding head_0028_eye_surface;
    head_0028_eye_surface.role = "material";
    head_0028_eye_surface.source_path = "cd_phw_00_eyecovermaterial_0001_sp.dds";
    head_0028_eye_surface.archive_path = "character/texture/cd_phw_00_eyecovermaterial_0001_sp.dds";
    head_0028_eye_surface.texture_name = "cd_phw_00_eyecovermaterial_0001_sp.dds";
    head_0028_eye_surface.material_name = "cd_phw_00_head_00_0028_eyecover";
    head_0028_eye_surface.material_wrapper_order_authoritative = true;
    head_0028_eye_surface.material_wrapper_index = 0;
    const std::vector<NativeSubmesh> head_0028_parts{head_0028_eye_cover, head_0028_skin};
    const std::vector<TextureBinding> head_0028_bindings{head_0028_eye_surface};
    require_material_contract(
        material_identity_match_score(head_0028_bindings.front(), head_0028_skin) == 0,
        "0028 eye-cover response matched the skin wrapper");
    require_material_contract(
        best_binding_for_role(head_0028_bindings, head_0028_skin, "material") == nullptr,
        "0028 skin selected the eye-cover response map");
    const auto head_0028_skin_bindings = relevant_bindings_for_mesh(
        head_0028_bindings,
        head_0028_parts,
        head_0028_skin,
        {});
    require_material_contract(
        head_0028_skin_bindings.empty(),
        "0028 skin retained the eye-cover response binding");
    require_material_contract(
        best_binding_for_role(head_0028_bindings, head_0028_eye_cover, "material") == &head_0028_bindings.front(),
        "0028 eye-cover lost its own response map");

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
}

int run_cli(int argc, char** argv) {
    CommonArgs common_args = parse_common_args(argc, argv);
    cdmw_native_diag::init("cdmw-preview-core", common_args.crash_dir, common_args.diagnostic_log);
    try {
        if (argc >= 2 && std::string(argv[1]) == "self-test") {
            run_material_contract_self_test();
            run_presentation_geometry_contract_self_test();
            cdmw_native_diag::event("self_test_ok");
            std::cout << "{\"event\":\"self_test\",\"ok\":true,\"backend\":\"cdmw_preview_core_0.1\",\"material_contracts\":true,\"presentation_geometry\":true}\n";
            return 0;
        }
        if (argc >= 2 && std::string(argv[1]) == "--service") {
            return run_service();
        }
        if (argc >= 4 && std::string(argv[1]) == "preview-job") {
            return run_preview_job(fs::path(argv[2]), fs::path(argv[3]));
        }
        if (argc >= 4 && std::string(argv[1]) == "mesh-audit-job") {
            return run_mesh_audit_job(fs::path(argv[2]), fs::path(argv[3]), argc >= 5 ? std::string(argv[4]) : std::string());
        }
        if (argc >= 4 && std::string(argv[1]) == "mesh-parse-job") {
            return run_mesh_parse_job(fs::path(argv[2]), fs::path(argv[3]), argc >= 5 ? std::string(argv[4]) : std::string());
        }
        if (argc >= 5 && std::string(argv[1]) == "mesh-rebuild-job") {
            return run_mesh_rebuild_job(fs::path(argv[2]), fs::path(argv[3]), fs::path(argv[4]));
        }
        if (argc >= 5 && std::string(argv[1]) == "name-index-job") {
            return run_name_index_job(
                fs::path(argv[2]),
                fs::path(argv[3]),
                fs::path(argv[4]),
                argc >= 6 ? fs::path(argv[5]) : fs::path()
            );
        }
        std::cerr << "usage: cdmw-preview-core self-test | --service | preview-job <job.json> <report.json> | mesh-audit-job <input> <report.json> [filename] | mesh-parse-job <input> <report.json> [filename] | mesh-rebuild-job <job.json> <output.bin> <report.json> | name-index-job <input.tsv> <output.bin> <report.json> [progress.json]\n";
        return 1;
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << "\n";
        return 2;
    }
}
