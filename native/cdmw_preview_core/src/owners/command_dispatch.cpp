static void require_material_contract(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(std::string("material contract self-test failed: ") + message);
    }
}

static void run_material_contract_self_test() {
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
}

int run_cli(int argc, char** argv) {
    CommonArgs common_args = parse_common_args(argc, argv);
    cdmw_native_diag::init("cdmw-preview-core", common_args.crash_dir, common_args.diagnostic_log);
    try {
        if (argc >= 2 && std::string(argv[1]) == "self-test") {
            run_material_contract_self_test();
            cdmw_native_diag::event("self_test_ok");
            std::cout << "{\"event\":\"self_test\",\"ok\":true,\"backend\":\"cdmw_preview_core_0.1\",\"material_contracts\":true}\n";
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
