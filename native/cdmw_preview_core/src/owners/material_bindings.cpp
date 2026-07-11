
static void append_mesh_reference_bindings(
    const EntryJob& job,
    const PamtIndex& index,
    const std::vector<NativeSubmesh>& meshes,
    std::vector<TextureBinding>& bindings,
    NativePackage& package
) {
    std::set<std::string> seen;
    for (const TextureBinding& binding : bindings) {
        seen.insert(lower_copy(binding.role + "|" + binding.archive_path + "|" + binding.parameter_name + "|" + binding.material_name));
    }
    std::vector<std::string> notes;
    for (const NativeSubmesh& mesh : meshes) {
        std::vector<std::string> raw_names = {mesh.material, mesh.name};
        for (const std::string& raw_name : raw_names) {
            std::string stem = stem_from_path(raw_name);
            if (stem.empty()) stem = raw_name;
            if (stem.empty()) continue;
            const std::string basename = lower_copy(stem) + ".dds";
            std::vector<ArchiveEntryRef> candidates = lookup_basename_candidates_across_package(job, index, basename, 32);
            if (candidates.empty()) continue;
            const ArchiveEntryRef* selected = nullptr;
            int best_score = -100000;
            const std::string mesh_source_path = mesh.source_model_path.empty() ? job.path : mesh.source_model_path;
            const std::string model_dir = lower_copy(dirname_from_path(mesh_source_path));
            for (const ArchiveEntryRef& ref : candidates) {
                int score = 20;
                const std::string ref_path = lower_copy(ref.path);
                const std::string ref_dir = lower_copy(dirname_from_path(ref.path));
                if (ref.extension == ".dds") score += 40;
                if (!model_dir.empty() && ref_dir == model_dir) score += 30;
                if (ref_path.find("/texture/") != std::string::npos) score += 18;
                if (lower_copy(stem_from_path(ref.path)) == lower_copy(stem)) score += 60;
                if (score > best_score) {
                    best_score = score;
                    selected = &ref;
                }
            }
            if (selected == nullptr || selected->extension != ".dds") continue;
            const std::string extracted = extracted_dds_path_for_entry(*selected, job.cache_root, notes);
            if (extracted.empty()) continue;
            TextureBinding binding;
            binding.role = texture_role_from_name(selected->basename);
            binding.source_path = extracted;
            binding.archive_path = selected->path;
            binding.texture_name = selected->basename;
            binding.parameter_name = "embedded_mesh_reference";
            binding.semantic_type = semantic_type_for_role(binding.role);
            binding.semantic_subtype = semantic_subtype_for_role(binding.role);
            binding.shader_family = "";
            binding.shader_rule = "embedded_mesh";
            binding.material_name = mesh.material.empty() ? mesh.name : mesh.material;
            binding.sidecar_path = "";
            binding.sidecar_kind = "embedded_mesh";
            binding.linked_mesh_path = mesh_source_path;
            binding.packed_channels = packed_channels_for_role(binding.role, binding.texture_name, binding.parameter_name);
            binding.srgb_mode = srgb_mode_for_role(binding.role, nullptr);
            binding.parameter_declared_by = "mesh";
            binding.visible_class = visible_class_for_binding(binding.parameter_name, binding.archive_path, binding.role);
            binding.source_authority = "embedded_mesh";
            binding.relation_confidence = role_is_technical_for_base(binding.role) ? "derived_same_stem" : "exact_path";
            binding.relation_reason = role_is_technical_for_base(binding.role)
                ? "Embedded mesh reference resolved to a technical/support texture."
                : "Embedded mesh material/base name resolved directly to DDS.";
            const DdsHeaderInfo dds_info = inspect_dds_header_file(extracted);
            binding.dds_width = dds_info.width;
            binding.dds_height = dds_info.height;
            binding.dds_format = dds_info.format;
            binding.material_output_quality = role_is_technical_for_base(binding.role) ? "inferred" : "exact";
            const std::string key = lower_copy(binding.role + "|" + binding.archive_path + "|" + binding.parameter_name + "|" + binding.material_name);
            if (!seen.insert(key).second) continue;
            bindings.push_back(binding);
            add_asset_family_row(package, NativeAssetFamilyRow{
                "Textures",
                "Texture",
                selected->basename.empty() ? basename_from_path(selected->path) : selected->basename,
                selected->path,
                "Resolved",
                "Embedded Mesh",
                binding.relation_confidence,
                role_is_technical_for_base(binding.role) ? "manual" : "required",
                binding.relation_reason,
                "texture",
                binding.semantic_type,
                binding.parameter_name,
                binding.parameter_name,
                binding.material_name,
                package_label_for_ref(*selected),
                "embedded_mesh",
                binding.shader_family,
                binding.role,
                "",
                ""
            });
        }
    }
    for (const std::string& note : notes) {
        package.notes.push_back(note);
    }
}
