// Island settings are evaluated as temporary fitting domains. Session Part and
// vertex identities, topology, skinning and output records are never split.
MeshRefitGarmentSettingsRuntime mesh_editor_refit_settings_from_json(
    const JsonValue&, MeshRefitGarmentSettingsRuntime, bool);
std::vector<std::vector<int>> mesh_editor_refit_islands(const MeshSessionSubmesh& part) {
    std::vector<std::size_t> roots(part.vertices.size());
    std::iota(roots.begin(), roots.end(), 0);
    const auto root = [&](std::size_t i) {
        while (roots[i] != i) { roots[i] = roots[roots[i]]; i = roots[i]; }
        return i;
    };
    std::map<std::tuple<long long,long long,long long>,std::size_t> positions;
    for (std::size_t i = 0; i < part.vertices.size(); ++i) {
        const auto& p = part.vertices[i];
        const auto key = std::make_tuple(std::llround(p[0]*100000.), std::llround(p[1]*100000.), std::llround(p[2]*100000.));
        const auto inserted = positions.emplace(key, i);
        if (!inserted.second) roots[root(i)] = root(inserted.first->second);
    }
    for (const auto& face : part.faces) for (int c = 1; c < 3; ++c)
        roots[root(face[c])] = root(face[0]);
    std::map<std::size_t,std::vector<int>> grouped;
    for (std::size_t i = 0; i < part.faces.size(); ++i) grouped[root(part.faces[i][0])].push_back(static_cast<int>(i));
    std::vector<std::vector<int>> groups;
    for (auto& row : grouped) groups.push_back(std::move(row.second));
    std::sort(groups.begin(), groups.end());
    return groups;
}

void mesh_editor_validate_refit_islands(const MeshSessionSubmesh& part, const MeshRefitGarmentSettingsRuntime& settings) {
    if (settings.island_settings.empty()) return;
    const auto groups = mesh_editor_refit_islands(part);
    std::set<std::vector<int>> seen;
    for (const auto& island : settings.island_settings)
        if (!seen.insert(island.face_indices).second
            || std::find(groups.begin(), groups.end(), island.face_indices) == groups.end())
            throw std::runtime_error("Island fitting requires distinct whole source mesh islands");
}

void mesh_editor_write_refit_island_settings(std::ostream& out, const MeshRefitGarmentSettingsRuntime& settings) {
    if (settings.island_settings.empty()) return;
    out << ",\"island_settings\":[";
    bool comma = false;
    for (const auto& island : settings.island_settings) {
        if (comma) out << ',';
        comma = true;
        out << "{\"face_indices\":[";
        for (std::size_t i = 0; i < island.face_indices.size(); ++i) {
            if (i) out << ',';
            out << island.face_indices[i];
        }
        out << "],\"enabled\":" << (island.enabled ? "true" : "false")
            << ",\"intensity_percent\":" << std::setprecision(17) << island.intensity_percent << ",\"mode\":";
        write_escaped(out, island.mode);
        out << ",\"clearance_percent\":" << island.clearance_percent
            << ",\"tightness_percent\":" << island.tightness_percent << '}';
    }
    out << ']';
}

void mesh_editor_apply_island_refit_corrections(
    const MeshMorphRuntime& morph, const std::map<int,MeshSessionSubmesh>& submeshes,
    const std::map<int,std::vector<Vec3>>& residual, std::map<int,std::vector<Vec3>>& layer,
    const std::map<int,std::vector<Vec3>>& post
) {
    auto fit = std::make_shared<MeshRefitRuntime>(*morph.refit);
    auto parts = submeshes;
    auto rest = residual;
    auto result = layer;
    auto corrections = post;
    struct Domain { int source; std::vector<int> vertices; int island; };
    std::map<int,Domain> domains;
    std::map<std::pair<int,int>,std::pair<int,int>> owners;
    int next = parts.rbegin()->first + 1;
    for (const auto& item : morph.refit->garment_settings) {
        if (item.second.island_settings.empty()) continue;
        const auto& source = submeshes.at(item.first);
        std::set<int> covered_faces, covered_vertices;
        auto topology = source;
        const auto neutral = morph.neutral_positions.find(item.first);
        if (neutral != morph.neutral_positions.end()) topology.vertices = neutral->second;
        const auto source_groups = mesh_editor_refit_islands(topology);
        const auto add_domain = [&](const std::vector<int>& faces, const MeshRefitGarmentSettingsRuntime& settings,
                                    int ordinal, bool remainder) {
            Domain domain{item.first, {}, ordinal};
            std::set<int> used;
            for (const int f : faces) for (const int v : source.faces.at(f)) used.insert(v);
            if (remainder) for (std::size_t v = 0; v < source.vertices.size(); ++v)
                if (!covered_vertices.count(static_cast<int>(v))) used.insert(static_cast<int>(v));
            if (used.empty()) return;
            const int id = next++;
            MeshSessionSubmesh part;
            std::map<int,int> local;
            for (const int v : used) {
                if (owners.count({item.first,v})) throw std::runtime_error("Fitting islands share a source vertex");
                const int index = static_cast<int>(part.vertices.size());
                owners[{item.first,v}] = {id,index}; local[v] = index;
                domain.vertices.push_back(v); covered_vertices.insert(v);
                part.vertices.push_back(source.vertices.at(v)); rest[id].push_back(residual.at(item.first).at(v));
                result[id].push_back(layer.count(item.first) ? layer.at(item.first).at(v) : Vec3{});
                if (post.count(item.first)) corrections[id].push_back(post.at(item.first).at(v));
            }
            for (const int f : faces) {
                const auto& face = source.faces.at(f);
                part.faces.push_back({local.at(face[0]),local.at(face[1]),local.at(face[2])});
            }
            parts[id] = std::move(part); domains[id] = std::move(domain);
            fit->garment_submesh_indices.insert(id);
            fit->garment_settings[id] = settings;
            fit->garment_settings[id].island_settings.clear();
            if (ordinal) fit->independent_island_parts.insert(id);
            const auto mask = morph.refit->vertex_masks.find(item.first);
            if (mask != morph.refit->vertex_masks.end()) {
                auto& target = fit->vertex_masks[id];
                for (const auto& vertex : local) {
                    const auto weight = mask->second.find(vertex.first);
                    if (weight != mask->second.end()) target[vertex.second] = weight->second;
                }
            }
            const auto region = morph.refit->garment_regions.find(item.first);
            if (region != morph.refit->garment_regions.end()) fit->garment_regions[id] = region->second;
        };
        for (const auto& island : item.second.island_settings) {
            auto settings = item.second;
            settings.enabled = island.enabled; settings.mode = island.mode;
            settings.intensity_percent = island.intensity_percent; settings.clearance_percent = island.clearance_percent;
            settings.tightness_percent = island.tightness_percent;
            const auto found = std::find(source_groups.begin(),source_groups.end(),island.face_indices);
            add_domain(island.face_indices,settings,static_cast<int>(found-source_groups.begin())+1,false);
            covered_faces.insert(island.face_indices.begin(),island.face_indices.end());
        }
        std::vector<int> remaining;
        for (std::size_t f = 0; f < source.faces.size(); ++f)
            if (!covered_faces.count(static_cast<int>(f))) remaining.push_back(static_cast<int>(f));
        add_domain(remaining,item.second,0,true);
        parts.erase(item.first); rest.erase(item.first); result.erase(item.first); corrections.erase(item.first);
        fit->garment_submesh_indices.erase(item.first); fit->garment_settings.erase(item.first);
        fit->vertex_masks.erase(item.first); fit->garment_regions.erase(item.first);
    }
    for (auto& binding : fit->bindings) {
        const auto owner = owners.find({binding.garment_submesh_index,binding.garment_vertex_index});
        if (owner == owners.end()) continue;
        binding.garment_submesh_index = owner->second.first;
        binding.garment_vertex_index = owner->second.second;
    }
    MeshMorphRuntime logical = morph;
    logical.refit = fit;
    try {
        mesh_editor_apply_refit_corrections(logical,parts,rest,result,corrections);
    } catch (const std::runtime_error& error) {
        std::string message = error.what();
        const auto label = [&](int id) {
            const auto found = domains.find(id);
            return found == domains.end() ? std::to_string(id) : std::to_string(found->second.source)
                + (found->second.island ? " island " + std::to_string(found->second.island) : "");
        };
        for (std::size_t at = 0; (at = message.find("Parts ",at)) != std::string::npos;) {
            at += 6;
            while (at < message.size() && std::isdigit(static_cast<unsigned char>(message[at]))) {
                const auto end = message.find_first_not_of("0123456789",at);
                const auto count = end == std::string::npos ? message.size()-at : end-at;
                const auto replacement = label(std::stoi(message.substr(at,count)));
                message.replace(at,count,replacement); at += replacement.size();
                if (message.substr(at,2) != ", ") break;
                at += 2;
            }
        }
        for (const auto& domain : domains) {
            const std::string key = "Part " + std::to_string(domain.first);
            const std::string label = "Part " + std::to_string(domain.second.source)
                + (domain.second.island ? " island " + std::to_string(domain.second.island) : "");
            for (std::size_t at = 0; (at = message.find(key,at)) != std::string::npos; at += label.size()) {
                if (at+key.size() < message.size() && std::isdigit(static_cast<unsigned char>(message[at+key.size()])))
                    { at += key.size(); continue; }
                message.replace(at,key.size(),label);
            }
        }
        throw std::runtime_error(message);
    }
    for (const auto& item : morph.refit->garment_settings) {
        if (item.second.island_settings.empty()) {
            const auto value = result.find(item.first);
            if (value != result.end()) layer[item.first] = value->second;
            continue;
        }
        auto& target = layer[item.first];
        target.resize(submeshes.at(item.first).vertices.size());
        for (const auto& domain : domains) if (domain.second.source == item.first)
            for (std::size_t v = 0; v < domain.second.vertices.size(); ++v)
                target[domain.second.vertices[v]] = result.at(domain.first)[v];
    }
}
