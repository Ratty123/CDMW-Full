static void add_sidecar_candidate(
    std::vector<ArchiveEntryRef>& out,
    std::set<std::string>& seen,
    const ArchiveEntryRef& ref
) {
    if (ref.path.empty() || ref.comp_size == 0) return;
    const std::string key = lower_copy(ref.path);
    if (seen.insert(key).second) out.push_back(ref);
}

static void add_sidecar_basename_candidates(
    std::vector<ArchiveEntryRef>& out,
    std::set<std::string>& seen,
    const PamtIndex& index,
    const std::string& basename,
    const std::string& preferred_dir
) {
    auto it = index.by_basename.find(lower_copy(basename));
    if (it == index.by_basename.end()) return;
    std::vector<std::pair<int, ArchiveEntryRef>> scored;
    for (const ArchiveEntryRef& ref : it->second) {
        int score = 10;
        const std::string path = lower_copy(ref.path);
        const std::string dir = lower_copy(dirname_from_path(ref.path));
        if (!preferred_dir.empty() && dir == lower_copy(preferred_dir)) score += 80;
        if (path.find("/modelproperty/") != std::string::npos) score += 30;
        if (path.find("/model/") != std::string::npos) score += 10;
        scored.emplace_back(score, ref);
    }
    std::sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
        return a.first > b.first;
    });
    for (const auto& item : scored) add_sidecar_candidate(out, seen, item.second);
}

static std::vector<ArchiveEntryRef> lookup_basename_candidates_across_package(
    const EntryJob& job,
    const PamtIndex& primary_index,
    const std::string& basename,
    size_t max_count = 64
) {
    std::vector<ArchiveEntryRef> result;
    std::set<std::string> seen;
    auto add_from_index = [&](const PamtIndex& index) {
        auto found = index.by_basename.find(lower_copy(basename));
        if (found == index.by_basename.end()) return;
        for (const ArchiveEntryRef& ref : found->second) {
            const std::string key = lower_copy(ref.pamt_path.string() + "|" + ref.path);
            if (seen.insert(key).second) result.push_back(ref);
            if (result.size() >= max_count) return;
        }
    };
    add_from_index(primary_index);
    if (!result.empty()) {
        record_archive_lite_dependency_query(basename, max_count, "primary_pamt");
        return result;
    }
    std::vector<ArchiveEntryRef> bounded_candidates;
    if (lookup_bounded_archive_dependency_basename(job, basename, max_count, bounded_candidates)) {
        for (const ArchiveEntryRef& ref : bounded_candidates) {
            const std::string key = lower_copy(ref.pamt_path.string() + "|" + ref.path);
            if (seen.insert(key).second) result.push_back(ref);
            if (result.size() >= max_count) break;
        }
        return result;
    }
    if (job.package_root.empty()) {
        record_archive_lite_dependency_query(basename, max_count, "package_scan_fallback");
    }
    if (!result.empty() || job.package_root.empty()) return result;
    std::vector<ArchiveEntryRef> indexed_candidates;
    if (lookup_archive_lite_basename(job, basename, max_count, indexed_candidates)) {
        for (const ArchiveEntryRef& ref : indexed_candidates) {
            const std::string key = lower_copy(ref.pamt_path.string() + "|" + ref.path);
            if (seen.insert(key).second) result.push_back(ref);
            if (result.size() >= max_count) break;
        }
        return result;
    }
    std::set<std::string> seen_pamts;
    seen_pamts.insert(fs::absolute(primary_index.pamt_path).string());
    for (const fs::path& pamt_path : package_root_pamt_paths(job.package_root)) {
        if (result.size() >= max_count) break;
        const std::string pamt_key = fs::absolute(pamt_path).string();
        if (!seen_pamts.insert(pamt_key).second) continue;
        try {
            add_from_index(cached_pamt_index(pamt_path));
        } catch (...) {
        }
    }
    return result;
}

static std::optional<ArchiveEntryRef> resolve_archive_path_across_package(
    const EntryJob& job,
    const PamtIndex& primary_index,
    std::string archive_path
) {
    std::replace(archive_path.begin(), archive_path.end(), '\\', '/');
    const std::string wanted = lower_copy(archive_path);
    if (wanted.empty()) return std::nullopt;
    std::vector<ArchiveEntryRef> candidates;
    std::set<std::string> seen;
    const std::string wanted_basename = lower_copy(basename_from_path(archive_path));
    auto add_from_index = [&](const PamtIndex& pamt_index) {
        auto found = pamt_index.by_basename.find(wanted_basename);
        if (found == pamt_index.by_basename.end()) return;
        for (const ArchiveEntryRef& ref : found->second) {
            const std::string key = lower_copy(ref.pamt_path.string() + "|" + ref.path);
            if (seen.insert(key).second) candidates.push_back(ref);
        }
    };
    add_from_index(primary_index);
    std::vector<ArchiveEntryRef> bounded_candidates;
    const bool used_bounded_dependencies = lookup_bounded_archive_dependency_basename(
        job,
        wanted_basename,
        64,
        bounded_candidates);
    if (used_bounded_dependencies) {
        for (const ArchiveEntryRef& ref : bounded_candidates) {
            const std::string key = lower_copy(ref.pamt_path.string() + "|" + ref.path);
            if (seen.insert(key).second) candidates.push_back(ref);
        }
    } else {
        std::vector<ArchiveEntryRef> indexed_candidates;
        const bool used_archive_lite_index = lookup_archive_lite_basename(
            job,
            wanted_basename,
            64,
            indexed_candidates);
        if (used_archive_lite_index) {
            for (const ArchiveEntryRef& ref : indexed_candidates) {
                const std::string key = lower_copy(ref.pamt_path.string() + "|" + ref.path);
                if (seen.insert(key).second) candidates.push_back(ref);
            }
        } else if (!job.package_root.empty()) {
            std::set<std::string> seen_pamts;
            seen_pamts.insert(fs::absolute(primary_index.pamt_path).string());
            for (const fs::path& pamt_path : package_root_pamt_paths(job.package_root)) {
                const std::string pamt_key = fs::absolute(pamt_path).string();
                if (!seen_pamts.insert(pamt_key).second) continue;
                try {
                    add_from_index(cached_pamt_index(pamt_path));
                } catch (...) {
                }
            }
        }
    }
    const ArchiveEntryRef* best = nullptr;
    int best_score = -100000;
    for (const ArchiveEntryRef& candidate : candidates) {
        int score = 0;
        const std::string candidate_path = lower_copy(candidate.path);
        if (candidate_path == wanted) score += 10000;
        if (candidate_path.find(wanted) != std::string::npos || wanted.find(candidate_path) != std::string::npos) score += 600;
        if (candidate.extension == extension_from_path(archive_path)) score += 50;
        if (candidate.pamt_path == job.entry.pamt_path) score += 12;
        if (score > best_score) {
            best_score = score;
            best = &candidate;
        }
    }
    if (best == nullptr || best_score < 500) return std::nullopt;
    return *best;
}

static NativePbdMaterialSettings default_native_pbd_material_settings(const NativePbdSidecarHint& hint) {
    NativePbdMaterialSettings settings;
    settings.material_name = hint.simulation_material_name;
    settings.simulation_kind = hint.simulation_kind.empty() ? "unknown" : hint.simulation_kind;
    const std::string kind = lower_copy(settings.simulation_kind);
    if (kind == "leather") {
        settings.stretching_stiffness = 0.55f;
        settings.bending_stiffness = 0.34f;
        settings.damping = 0.82f;
        settings.wind_response = 0.22f;
    } else if (kind == "hair") {
        settings.stretching_stiffness = 0.24f;
        settings.bending_stiffness = 0.08f;
        settings.damping = 1.15f;
        settings.gravity = -6.5f;
        settings.air_resistance = 1.8f;
        settings.wind_response = 0.75f;
        settings.solver_iterations = 24;
        settings.collision_enabled = false;
    } else if (kind == "rope" || kind == "spline") {
        settings.stretching_stiffness = 0.82f;
        settings.bending_stiffness = 0.12f;
        settings.damping = 0.78f;
        settings.wind_response = 0.24f;
        settings.solver_iterations = 36;
    } else if (kind == "body_soft") {
        settings.stretching_stiffness = 0.45f;
        settings.bending_stiffness = 0.12f;
        settings.damping = 1.35f;
        settings.gravity = -4.0f;
        settings.wind_response = 0.10f;
        settings.solver_iterations = 20;
    }
    settings.is_cloak = native_cloth_token_match(
        hint.simulation_material_name + " " + hint.material_name + " " + hint.submesh_name
    );
    return settings;
}

static NativePbdMaterialSettings resolve_native_pbd_material_settings(
    const EntryJob& job,
    const PamtIndex& primary_index,
    const NativePbdSidecarHint& hint
) {
    NativePbdMaterialSettings fallback = default_native_pbd_material_settings(hint);
    if (hint.simulation_material_name.empty()) return fallback;
    std::vector<ArchiveEntryRef> config_candidates = lookup_basename_candidates_across_package(job, primary_index, "pbdconfig.xml", 16);
    std::sort(config_candidates.begin(), config_candidates.end(), [](const ArchiveEntryRef& a, const ArchiveEntryRef& b) {
        const std::string ap = lower_copy(a.path);
        const std::string bp = lower_copy(b.path);
        const int as = (ap.find("/descriptors/pbd/") != std::string::npos ? 80 : 0) + (ap.find("pbdconfig.xml") != std::string::npos ? 20 : 0);
        const int bs = (bp.find("/descriptors/pbd/") != std::string::npos ? 80 : 0) + (bp.find("pbdconfig.xml") != std::string::npos ? 20 : 0);
        if (as != bs) return as > bs;
        return ap < bp;
    });
    for (const ArchiveEntryRef& config_ref : config_candidates) {
        std::vector<char> config_bytes;
        try {
            config_bytes = read_archive_ref_decoded_bytes(config_ref);
        } catch (...) {
            continue;
        }
        const std::string config_text(config_bytes.begin(), config_bytes.end());
        const auto materials = parse_native_pbd_config_materials(config_text);
        auto found = materials.find(normalized_key(hint.simulation_material_name));
        if (found == materials.end()) continue;
        NativePbdConfigMaterial config_material = found->second;
        std::optional<ArchiveEntryRef> material_ref = resolve_archive_path_across_package(job, primary_index, config_material.filename);
        if (!material_ref.has_value()) {
            const std::string basename = basename_from_path(config_material.filename);
            for (const ArchiveEntryRef& candidate : lookup_basename_candidates_across_package(job, primary_index, basename, 24)) {
                const std::string candidate_path = lower_copy(candidate.path);
                if (candidate.extension != ".xml") continue;
                if (candidate_path.find("/descriptors/pbd/") == std::string::npos) continue;
                material_ref = candidate;
                break;
            }
        }
        if (!material_ref.has_value()) {
            fallback.material_path = config_material.filename;
            fallback.material_name = config_material.name.empty() ? fallback.material_name : config_material.name;
            fallback.simulation_kind = native_pbd_simulation_kind({fallback.material_name, fallback.material_path, config_material.mode, config_material.pbd_part});
            fallback.is_cloak = fallback.is_cloak || native_cloth_token_match(fallback.material_name + " " + fallback.material_path);
            return fallback;
        }
        std::vector<char> material_bytes;
        try {
            material_bytes = read_archive_ref_decoded_bytes(*material_ref);
        } catch (...) {
            fallback.material_path = config_material.filename;
            fallback.material_name = config_material.name.empty() ? fallback.material_name : config_material.name;
            return fallback;
        }
        const std::string material_text(material_bytes.begin(), material_bytes.end());
        NativePbdMaterialSettings settings = parse_native_pbd_material_settings(material_text, config_material, material_ref->path);
        if (settings.material_name.empty()) settings.material_name = hint.simulation_material_name;
        if (settings.simulation_kind.empty()) settings.simulation_kind = hint.simulation_kind.empty() ? "cloth" : hint.simulation_kind;
        settings.is_cloak = settings.is_cloak || fallback.is_cloak;
        return settings;
    }
    return fallback;
}

static std::vector<std::string> extract_prefab_model_paths(const std::vector<char>& bytes) {
    std::vector<std::string> paths;
    std::set<std::string> seen;
    if (bytes.empty()) return paths;
    const std::string text(bytes.begin(), bytes.end());
    const std::regex model_path_pattern(
        "((?:character|object|vehicle|environment|effect)/[A-Za-z0-9_./\\\\-]+\\.(?:pac|pam|pamlod))",
        std::regex_constants::icase);
    auto begin = std::sregex_iterator(text.begin(), text.end(), model_path_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        std::string path = (*it)[1].str();
        std::replace(path.begin(), path.end(), '\\', '/');
        const std::string key = lower_copy(path);
        if (seen.insert(key).second) {
            paths.push_back(path);
            if (paths.size() >= 32) break;
        }
    }
    return paths;
}

static std::vector<std::string> prefab_candidate_basenames_for_model_stem(const std::string& model_stem) {
    std::vector<std::string> stems;
    std::set<std::string> seen_stems;
    auto add_stem = [&](const std::string& stem) {
        if (stem.empty()) return;
        if (seen_stems.insert(lower_copy(stem)).second) {
            stems.push_back(stem);
        }
    };
    add_stem(model_stem);
    if (!lower_copy(model_stem).ends_with("_v")) {
        add_stem(model_stem + "_v");
    }

    std::smatch match;
    const std::regex submesh_suffix_pattern(R"(^(.+)_sub[0-9]+$)", std::regex_constants::icase);
    if (std::regex_match(model_stem, match, submesh_suffix_pattern) && match.size() >= 2) {
        add_stem(match[1].str());
    }

    const std::string part_token =
        R"(body|head|hair|chain|cloth|acc|belt|sho|shoulder|ub|lb|hel|hand|foot|blade|guard|handle|core|tail|wing|horn|fur)";
    const std::regex part_before_number_pattern(
        "^(.+)_(" + part_token + ")_([0-9].*)$",
        std::regex_constants::icase);
    if (std::regex_match(model_stem, match, part_before_number_pattern) && match.size() >= 4) {
        add_stem(match[1].str() + "_" + match[3].str());
    }

    const std::regex part_after_number_pattern(
        "^(.+_[0-9].*)_(" + part_token + ")$",
        std::regex_constants::icase);
    if (std::regex_match(model_stem, match, part_after_number_pattern) && match.size() >= 2) {
        add_stem(match[1].str());
    }

    const std::regex compound_part_pattern(
        R"(^(.+)_(ub|lb|sho|hel|hand|foot|cloak)_(acc|belt|hair|cloth)_([0-9].*)$)",
        std::regex_constants::icase);
    if (std::regex_match(model_stem, match, compound_part_pattern) && match.size() >= 5) {
        add_stem(match[1].str() + "_" + match[2].str() + "_" + match[4].str());
        add_stem(match[1].str() + "_" + match[4].str());
    }

    std::vector<std::string> basenames;
    std::set<std::string> seen_basenames;
    auto add_basename = [&](const std::string& basename) {
        if (seen_basenames.insert(lower_copy(basename)).second) {
            basenames.push_back(basename);
        }
    };
    for (const std::string& stem : stems) {
        add_basename(stem + "_s.prefab");
        add_basename(stem + "_l.prefab");
        add_basename(stem + "_r.prefab");
        add_basename(stem + ".prefab");
    }
    return basenames;
}

static std::string prefab_component_match_stem(std::string stem) {
    stem = lower_copy(stem);
    for (const std::string& suffix : {"_op_s", "_op_v", "_v", "_s"}) {
        if (stem.size() > suffix.size() && stem.ends_with(suffix)) {
            return stem.substr(0, stem.size() - suffix.size());
        }
    }
    return stem;
}

static bool prefab_model_path_matches_job(const std::string& model_path, const EntryJob& job) {
    std::string normalized_model_path = model_path;
    std::replace(normalized_model_path.begin(), normalized_model_path.end(), '\\', '/');
    std::string normalized_job_path = job.path;
    std::replace(normalized_job_path.begin(), normalized_job_path.end(), '\\', '/');
    const std::string model_lower = lower_copy(normalized_model_path);
    const std::string job_lower = lower_copy(normalized_job_path);
    if (model_lower == job_lower) return true;

    const std::string model_stem = prefab_component_match_stem(stem_from_path(model_lower));
    const std::string job_stem = prefab_component_match_stem(stem_from_path(job_lower));
    if (model_stem.empty() || model_stem != job_stem) return false;

    const std::string model_dir = lower_copy(dirname_from_path(model_lower));
    const std::string job_dir = lower_copy(dirname_from_path(job_lower));
    return model_dir.empty() || job_dir.empty() || model_dir == job_dir;
}

static std::string prefab_component_path_key(std::string path) {
    std::replace(path.begin(), path.end(), '\\', '/');
    return lower_copy(path);
}

static bool prefab_component_enabled_for_job(
    const ArchiveEntryRef& component,
    const EntryJob& job
) {
    const std::string component_key = prefab_component_path_key(component.path);
    return std::any_of(
        job.enabled_prefab_component_paths.begin(),
        job.enabled_prefab_component_paths.end(),
        [&](const std::string& enabled_path) {
            return prefab_component_path_key(enabled_path) == component_key;
        });
}

static std::vector<ArchiveEntryRef> prefab_model_component_refs_for_job(
    const EntryJob& job,
    const PamtIndex& index,
    size_t max_components = 8
) {
    std::vector<ArchiveEntryRef> components;
    if (job.extension != ".pac" || job.path.empty()) return components;
    const std::string model_stem = stem_from_path(job.path);
    if (model_stem.empty()) return components;

    std::vector<ArchiveEntryRef> prefab_candidates;
    std::set<std::string> seen_prefabs;
    for (const std::string& basename : prefab_candidate_basenames_for_model_stem(model_stem)) {
        std::vector<ArchiveEntryRef> candidates = lookup_basename_candidates_across_package(job, index, basename, 8);
        std::sort(candidates.begin(), candidates.end(), [](const ArchiveEntryRef& a, const ArchiveEntryRef& b) {
            const std::string ap = lower_copy(a.path);
            const std::string bp = lower_copy(b.path);
            const int as = (ap.find("/bin__/prefab/") != std::string::npos ? 30 : 0) + (ap.find("/prefab/") != std::string::npos ? 20 : 0);
            const int bs = (bp.find("/bin__/prefab/") != std::string::npos ? 30 : 0) + (bp.find("/prefab/") != std::string::npos ? 20 : 0);
            if (as != bs) return as > bs;
            return ap < bp;
        });
        for (const ArchiveEntryRef& candidate : candidates) {
            const std::string key = lower_copy(candidate.pamt_path.string() + "|" + candidate.path);
            if (seen_prefabs.insert(key).second) prefab_candidates.push_back(candidate);
        }
    }

    std::set<std::string> seen_components;
    for (const ArchiveEntryRef& prefab : prefab_candidates) {
        std::vector<char> prefab_bytes;
        try {
            prefab_bytes = read_archive_ref_decoded_bytes(prefab);
        } catch (...) {
            continue;
        }
        const std::vector<std::string> model_paths = extract_prefab_model_paths(prefab_bytes);
        std::vector<ArchiveEntryRef> resolved_for_prefab;
        bool references_selected_model = false;
        for (const std::string& model_path : model_paths) {
            std::optional<ArchiveEntryRef> resolved = resolve_archive_path_across_package(job, index, model_path);
            if (!resolved.has_value()) continue;
            if (prefab_model_path_matches_job(resolved->path, job)) references_selected_model = true;
            resolved_for_prefab.push_back(*resolved);
        }
        if (!references_selected_model || resolved_for_prefab.size() <= 1) continue;
        for (const ArchiveEntryRef& resolved : resolved_for_prefab) {
            if (resolved.extension != ".pac" && resolved.extension != ".pam" && resolved.extension != ".pamlod") continue;
            const std::string key = lower_copy(resolved.pamt_path.string() + "|" + resolved.path);
            if (!seen_components.insert(key).second) continue;
            components.push_back(resolved);
            if (components.size() >= max_components) return components;
        }
    }
    return components;
}

static bool direct_sibling_sidecar_variant_allowed_for_fuzzy_match(
    const std::string& model_stem_lower,
    const std::string& ref_stem_lower
) {
    if (model_stem_lower.empty() || ref_stem_lower.empty() || ref_stem_lower == model_stem_lower) return true;
    const std::string prefix = model_stem_lower + "_";
    if (ref_stem_lower.rfind(prefix, 0) != 0) return true;
    const std::string suffix = ref_stem_lower.substr(prefix.size());
    if (suffix == "in" || suffix.rfind("in_", 0) == 0) return false;
    return true;
}

static std::vector<ArchiveEntryRef> material_sidecar_candidates_for_job(
    const EntryJob& job,
    const PamtIndex& index
) {
    std::vector<ArchiveEntryRef> candidates;
    std::set<std::string> seen;
    add_sidecar_candidate(candidates, seen, job.companion_entry);

    const std::string model_stem = stem_from_path(job.path);
    const std::string model_stem_lower = lower_copy(model_stem);
    const std::string model_dir = dirname_from_path(job.path);
    std::vector<std::string> basenames;
    if (job.extension == ".pac") {
        basenames = {model_stem + ".pac_xml", model_stem + ".material", model_stem + ".technique", model_stem + ".meshinfo"};
    } else if (job.extension == ".pam") {
        basenames = {model_stem + ".pami", model_stem + ".pam_xml", model_stem + ".material", model_stem + ".technique", model_stem + ".meshinfo"};
    } else if (job.extension == ".pamlod") {
        basenames = {model_stem + ".pamlod_xml", model_stem + ".pami", model_stem + ".pam_xml", model_stem + ".material", model_stem + ".technique", model_stem + ".meshinfo"};
    }
    if (!job.enabled_prefab_component_paths.empty()) {
        basenames.push_back(model_stem + ".prefab");
        basenames.push_back(model_stem + ".prefabdata_xml");
    }
    for (const std::string& base : basenames) {
        const size_t before_primary = candidates.size();
        add_sidecar_basename_candidates(candidates, seen, index, base, model_dir);
        if (candidates.size() == before_primary) {
            for (const ArchiveEntryRef& ref : lookup_basename_candidates_across_package(job, index, base, 24)) {
                add_sidecar_candidate(candidates, seen, ref);
            }
        }
    }
    if (job.extension == ".pac" && !job.enabled_prefab_component_paths.empty()) {
        for (const ArchiveEntryRef& component : prefab_model_component_refs_for_job(job, index, 12)) {
            if (lower_copy(component.path) == lower_copy(job.path)) continue;
            if (!prefab_component_enabled_for_job(component, job)) continue;
            const std::string component_stem = stem_from_path(component.path);
            const std::string component_dir = dirname_from_path(component.path);
            for (const std::string& base : {
                component_stem + ".pac_xml",
                component_stem + ".material",
                component_stem + ".technique",
                component_stem + ".prefab",
                component_stem + ".prefabdata_xml",
                component_stem + ".meshinfo",
            }) {
                const size_t before_component = candidates.size();
                add_sidecar_basename_candidates(candidates, seen, index, base, component_dir);
                if (candidates.size() == before_component) {
                    for (const ArchiveEntryRef& ref : lookup_basename_candidates_across_package(job, index, base, 24)) {
                        add_sidecar_candidate(candidates, seen, ref);
                    }
                }
            }
        }
    }
    if ((job.extension == ".pam" || job.extension == ".pamlod") && !candidates.empty()) {
        return candidates;
    }

    std::vector<std::pair<int, ArchiveEntryRef>> scored;
    const std::string model_dir_lower = lower_copy(model_dir);
    const std::string model_property_dir = lower_copy([&]() {
        std::string converted = model_dir;
        const std::string marker = "/model/";
        const size_t pos = lower_copy(converted).find(marker);
        if (pos != std::string::npos) {
            converted.replace(pos, marker.size(), "/modelproperty/");
        }
        return converted;
    }());
    for (const ArchiveEntryRef& ref : index.material_sidecars) {
        if (seen.find(lower_copy(ref.path)) != seen.end()) continue;
        const std::string ref_stem = lower_copy(stem_from_path(ref.path));
        const std::string ref_path = lower_copy(ref.path);
        const std::string ref_dir = lower_copy(dirname_from_path(ref.path));
        if (!direct_sibling_sidecar_variant_allowed_for_fuzzy_match(model_stem_lower, ref_stem)) continue;
        int score = 0;
        if (!model_stem_lower.empty() && ref_stem == model_stem_lower) score += 100;
        if (!model_stem_lower.empty() && ref_path.find(model_stem_lower) != std::string::npos) score += 40;
        if (!model_dir_lower.empty() && ref_dir == model_dir_lower) score += 25;
        if (!model_property_dir.empty() && ref_dir == model_property_dir) score += 45;
        if (ref.extension == ".pami" && (job.extension == ".pam" || job.extension == ".pamlod")) score += 20;
        if ((ref.extension == ".pac_xml" || ref.extension == ".pam_xml" || ref.extension == ".pamlod_xml") && ref_path.find("/modelproperty/") != std::string::npos) score += 15;
        if (score >= 80) scored.emplace_back(score, ref);
    }
    std::sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
        return a.first > b.first;
    });
    for (const auto& item : scored) {
        if (candidates.size() >= 24) break;
        add_sidecar_candidate(candidates, seen, item.second);
    }
    return candidates;
}
