// Skin weights for Fit to reference body.
//
// Fitting moves a garment onto the driver, but its skin weights still describe
// the body it was authored on, so in motion the cloth follows that body's
// joints. Garment vertices near the driver therefore take the driver's own
// weights beneath them: fully within WEIGHT_FULL of its surface, fading back to
// their own weights by WEIGHT_FADE. A rigid piece, or a small closed island,
// follows one bone for all its vertices, the strongest of the driver's beneath
// its point nearest the body, so it cannot bend; one farther out keeps its own.
// Pieces joined into one rigid assembly by the fit each take their own: one set
// for a whole chain of studs left it behind a twisting torso (23002: 62 garment
// points pushed into the body over five poses became 504), and a blend of hip
// and thigh still squashed a 24 cm piece by 10 mm in a crouch. Masks scale the
// share as they scale the fit.
//
// The transfer also follows the outfit's design. On the body it was authored
// for, a garment point that moves with the skin beneath it in a few test poses
// was made to follow that skin, and takes the driver's weights; one that stays
// behind (a cape hanging beside the arm, weighted to the shoulder) keeps its
// own, or raising the arm would drag it into the body. Its share is full while
// its worst gap to the skin stays within WEIGHT_FOLLOW and gone by WEIGHT_STRAY.
// Comparing bone names instead read a garment weighted to a parent bone, where
// the body uses its twist helper, as disagreeing, and gave back half the gain.
//
// The driver's bones reach each garment Part only through the slot table the
// caller resolved for that Part's own palette (by bone name, else the nearest
// named ancestor), so palettes never grow. Rows keep at most each vertex's
// capacity of strongest influences and drop shares below half a byte step,
// which would otherwise round up to a whole one.

constexpr double REFIT_REFERENCE_WEIGHT_FULL = 0.01;
constexpr double REFIT_REFERENCE_WEIGHT_FADE = 0.03;
constexpr double REFIT_REFERENCE_WEIGHT_FLOOR = 1.0 / 510.0;
constexpr double REFIT_REFERENCE_WEIGHT_FOLLOW = 0.025;
constexpr double REFIT_REFERENCE_WEIGHT_STRAY = 0.075;

std::map<int, BoneAssignments> mesh_editor_refit_transfer_weights(
    const MeshMorphRuntime& morph,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const RefitReferenceSurface& driver,
    const RefitReferenceSurface& authored,
    const std::map<int, std::vector<int>>& particles,
    const std::vector<Vec3>& start,
    const std::vector<Vec3>& x,
    const std::vector<std::vector<int>>& pieces,
    const RefitMaskWeightsNative& masks,
    double scale,
    std::ostream& report
) {
    std::map<int, BoneAssignments> result;
    const MeshRefitRuntime& refit = *morph.refit;
    if (!refit.weight_transfer) return result;
    const MeshRefitWeightTransferRuntime& transfer = *refit.weight_transfer;

    // Driver rows in driver bones, in the order the driver surface was built.
    std::vector<std::vector<std::pair<int, double>>> body;
    for (const int part : refit.driver_submesh_indices) {
        const auto& submesh = submeshes.at(part);
        const auto bones = transfer.driver_bones.find(part);
        for (std::size_t v = 0; v < submesh.vertices.size(); ++v) {
            std::vector<std::pair<int, double>> row;
            if (bones != transfer.driver_bones.end() && v < submesh.bone_indices.size() && v < submesh.bone_weights.size()) {
                const auto& slots = submesh.bone_indices[v];
                const auto& weights = submesh.bone_weights[v];
                for (std::size_t k = 0; k < slots.size() && k < weights.size(); ++k) {
                    const int slot = slots[k];
                    if (slot < 0 || static_cast<std::size_t>(slot) >= bones->second.size() || !(weights[k] > 0.0)) continue;
                    if (bones->second[static_cast<std::size_t>(slot)] >= 0)
                        row.emplace_back(bones->second[static_cast<std::size_t>(slot)], weights[k]);
                }
            }
            body.push_back(std::move(row));
        }
    }

    std::vector<char> needed(x.size(), 0);
    for (const auto& item : transfer.garment_slots) {
        const auto map = particles.find(item.first);
        if (map != particles.end()) for (const int i : map->second) if (i >= 0) needed[static_cast<std::size_t>(i)] = 1;
    }
    std::vector<double> distance(x.size(), std::numeric_limits<double>::infinity());
    std::vector<std::map<int, double>> beneath(x.size());
    for (std::size_t i = 0; i < x.size(); ++i) {
        if (!needed[i]) continue;
        const auto hit = driver.index.closest(x[i]);
        if (hit.triangle < 0) continue;
        distance[i] = std::sqrt(hit.distance_squared);
        const auto& face = driver.faces[static_cast<std::size_t>(hit.triangle)];
        for (int c = 0; c < 3; ++c)
            for (const auto& item : body[static_cast<std::size_t>(face[static_cast<std::size_t>(c)])])
                beneath[i][item.first] += hit.barycentric[static_cast<std::size_t>(c)] * item.second;
    }
    const double full = REFIT_REFERENCE_WEIGHT_FULL * scale;
    const double fade = REFIT_REFERENCE_WEIGHT_FADE * scale;
    std::vector<int> group_of(x.size(), -1), anchor(pieces.size(), -1);
    long long rigid = 0;
    for (std::size_t g = 0; g < pieces.size(); ++g) {
        int best = -1;
        for (const int i : pieces[g]) {
            group_of[static_cast<std::size_t>(i)] = static_cast<int>(g);
            if (needed[static_cast<std::size_t>(i)] && (best < 0 || distance[static_cast<std::size_t>(i)] < distance[static_cast<std::size_t>(best)]))
                best = i;
        }
        if (best >= 0 && distance[static_cast<std::size_t>(best)] <= fade) {
            anchor[g] = best;
            ++rigid;
        }
    }

    // Whether a garment point, as authored, moves with the authored skin beneath it.
    const std::size_t poses = transfer.motion_poses;
    std::vector<std::vector<double>> authored_beneath(x.size());
    const double follow = REFIT_REFERENCE_WEIGHT_FOLLOW * scale;
    const double stray = REFIT_REFERENCE_WEIGHT_STRAY * scale;
    const auto agreement = [&](int part, int i, std::size_t v) {
        const auto motion = transfer.garment_motion.find(part);
        if (!poses || transfer.reference_motion.empty() || motion == transfer.garment_motion.end()) return 1.0;
        auto& beneath_motion = authored_beneath[static_cast<std::size_t>(i)];
        if (beneath_motion.empty()) {
            beneath_motion.assign(poses * 3, 0.0);
            const auto hit = authored.index.closest(start[static_cast<std::size_t>(i)]);
            if (hit.triangle >= 0) {
                const auto& face = authored.faces[static_cast<std::size_t>(hit.triangle)];
                for (int c = 0; c < 3; ++c)
                    for (std::size_t k = 0; k < poses * 3; ++k)
                        beneath_motion[k] += hit.barycentric[static_cast<std::size_t>(c)]
                            * transfer.reference_motion[static_cast<std::size_t>(face[static_cast<std::size_t>(c)]) * poses * 3 + k];
            }
        }
        double gap = 0.0;
        for (std::size_t k = 0; k < poses; ++k) {
            Vec3 difference{};
            for (int axis = 0; axis < 3; ++axis)
                difference[axis] = motion->second[(v * poses + k) * 3 + static_cast<std::size_t>(axis)]
                    - beneath_motion[k * 3 + static_cast<std::size_t>(axis)];
            gap = std::max(gap, length_vec3(difference));
        }
        return 1.0 - std::clamp((gap - follow) / (stray - follow), 0.0, 1.0);
    };
    std::vector<double> piece_share(pieces.size(), -1.0);

    long long changed = 0;
    double dropped = 0.0;
    std::vector<int> changed_parts;
    for (const auto& item : transfer.garment_slots) {
        const int part = item.first;
        const auto& slots = item.second;
        const auto map = particles.find(part);
        const auto capacity = transfer.capacities.find(part);
        const auto submesh = submeshes.find(part);
        if (map == particles.end() || capacity == transfer.capacities.end() || submesh == submeshes.end()) continue;
        const auto neutral = morph.neutral_bones.find(part);
        const BoneAssignments own = neutral != morph.neutral_bones.end()
            ? *neutral->second : BoneAssignments{submesh->second.bone_indices, submesh->second.bone_weights};
        const std::size_t count = submesh->second.vertices.size();
        if (own.indices.size() != count || own.weights.size() != count || capacity->second.size() != count
            || map->second.size() != count)
            continue;
        BoneAssignments rows = own;
        long long part_changed = 0;
        for (std::size_t v = 0; v < count; ++v) {
            const int i = map->second[v];
            if (i < 0) continue;
            const int g = group_of[static_cast<std::size_t>(i)];
            int source = i;
            double share = 0.0;
            if (g >= 0) {
                if (anchor[static_cast<std::size_t>(g)] < 0) continue;
                source = anchor[static_cast<std::size_t>(g)];
                // One agreement for the whole piece, so it still takes one set.
                auto& piece = piece_share[static_cast<std::size_t>(g)];
                if (piece < 0.0) piece = agreement(part, source, v);
                share = piece;
            } else {
                share = 1.0 - std::clamp((distance[static_cast<std::size_t>(i)] - full) / (fade - full), 0.0, 1.0);
                if (share > 0.0) share *= agreement(part, i, v);
            }
            share *= mesh_editor_refit_mask_weight(masks, part, v);
            if (!(share > 0.0)) continue;
            std::map<int, double> body_slots;
            double kept = 0.0, lost = 0.0;
            for (const auto& bone : beneath[static_cast<std::size_t>(source)]) {
                const int slot = bone.first >= 0 && static_cast<std::size_t>(bone.first) < slots.size()
                    ? slots[static_cast<std::size_t>(bone.first)] : -1;
                if (slot < 0) lost += bone.second;
                else {
                    body_slots[slot] += bone.second;
                    kept += bone.second;
                }
            }
            if (!(kept > 0.0)) continue;
            dropped += share * lost / (kept + lost);
            if (g >= 0) {
                // A piece follows the strongest bone beneath it alone: a blend of
                // hip and thigh still squashed a 24 cm piece by 10 mm in a crouch.
                const auto strongest = std::max_element(body_slots.begin(), body_slots.end(), [](const auto& a, const auto& b) {
                    return a.second != b.second ? a.second < b.second : a.first > b.first;
                });
                body_slots = {{strongest->first, kept}};
            }
            std::map<int, double> mixed;
            for (std::size_t k = 0; k < own.indices[v].size() && k < own.weights[v].size(); ++k)
                if (own.weights[v][k] > 0.0) mixed[own.indices[v][k]] += (1.0 - share) * own.weights[v][k];
            for (const auto& slot : body_slots) mixed[slot.first] += share * slot.second / kept;
            std::vector<std::pair<int, double>> ordered(mixed.begin(), mixed.end());
            std::sort(ordered.begin(), ordered.end(), [](const auto& a, const auto& b) {
                return a.second != b.second ? a.second > b.second : a.first < b.first;
            });
            const std::size_t limit = static_cast<std::size_t>(std::clamp(capacity->second[v], 1, static_cast<int>(MESH_MAX_SKIN_INFLUENCES)));
            if (ordered.size() > limit) ordered.resize(limit);
            double total = 0.0;
            for (const auto& entry : ordered) total += entry.second;
            std::size_t keep = 1;
            while (keep < ordered.size() && ordered[keep].second / total >= REFIT_REFERENCE_WEIGHT_FLOOR) ++keep;
            ordered.resize(keep);
            total = 0.0;
            for (const auto& entry : ordered) total += entry.second;
            std::vector<int> indices;
            std::vector<double> weights;
            for (const auto& entry : ordered) {
                indices.push_back(entry.first);
                weights.push_back(entry.second / total);
            }
            if (indices == own.indices[v] && weights == own.weights[v]) continue;
            rows.indices[v] = std::move(indices);
            rows.weights[v] = std::move(weights);
            ++part_changed;
        }
        changed += part_changed;
        if (part_changed) changed_parts.push_back(part);
        result[part] = std::move(rows);
    }
    report << ",\"weights\":{\"parts\":" << result.size() << ",\"changed_vertices\":" << changed
           << ",\"rigid_pieces\":" << rigid << ",\"dropped_bone_mass\":" << std::setprecision(17) << dropped
           << ",\"changed_parts\":[";
    for (std::size_t k = 0; k < changed_parts.size(); ++k) report << (k ? "," : "") << changed_parts[k];
    report << "]}";
    return result;
}

// Writes transferred rows, keeping each Part's own rows to restore, and gives
// Parts whose transfer has ended their own rows back.
void mesh_editor_apply_refit_weights(
    MeshMorphRuntime& next,
    std::map<int, MeshSessionSubmesh>& submeshes,
    std::map<int, BoneAssignments> transferred
) {
    for (auto item = next.neutral_bones.begin(); item != next.neutral_bones.end();) {
        if (transferred.count(item->first)) {
            ++item;
            continue;
        }
        const auto found = submeshes.find(item->first);
        if (found != submeshes.end() && found->second.vertices.size() == item->second->indices.size()) {
            found->second.bone_indices = item->second->indices;
            found->second.bone_weights = item->second->weights;
        }
        item = next.neutral_bones.erase(item);
    }
    for (auto& item : transferred) {
        auto& submesh = submeshes.at(item.first);
        if (!next.neutral_bones.count(item.first))
            next.neutral_bones[item.first] = std::make_shared<const BoneAssignments>(
                BoneAssignments{submesh.bone_indices, submesh.bone_weights});
        submesh.bone_indices = std::move(item.second.indices);
        submesh.bone_weights = std::move(item.second.weights);
    }
}

std::vector<int> mesh_editor_refit_weight_ints(const JsonValue* raw, const char* what, int minimum, int maximum) {
    if (!raw || raw->type != JsonValue::Type::Array) throw std::runtime_error(std::string("Fit weight transfer requires ") + what);
    std::vector<int> values;
    values.reserve(raw->array_value.size());
    for (const auto& item : raw->array_value) {
        int value = 0;
        if (!strict_int_or(&item, value) || value < minimum || value > maximum)
            throw std::runtime_error(std::string("Fit weight transfer has an invalid entry in ") + what);
        values.push_back(value);
    }
    return values;
}

std::vector<double> mesh_editor_refit_weight_doubles(const JsonValue* raw, const char* what) {
    if (!raw || raw->type != JsonValue::Type::Array) throw std::runtime_error(std::string("Fit weight transfer requires ") + what);
    std::vector<double> values;
    values.reserve(raw->array_value.size());
    for (const auto& item : raw->array_value) {
        if (item.type != JsonValue::Type::Number || !std::isfinite(item.number_value))
            throw std::runtime_error(std::string("Fit weight transfer has a non-finite entry in ") + what);
        values.push_back(item.number_value);
    }
    return values;
}

std::shared_ptr<const MeshRefitWeightTransferRuntime> mesh_editor_refit_weight_transfer_from_json(
    const JsonValue& raw,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const MeshRefitRuntime& refit
) {
    if (raw.type == JsonValue::Type::Null) return nullptr;
    const auto* drivers = raw.get("driver_bones");
    const auto* garments = raw.get("garments");
    if (raw.type != JsonValue::Type::Object || !drivers || !garments
        || drivers->type != JsonValue::Type::Array || garments->type != JsonValue::Type::Array)
        throw std::runtime_error("Fit weight transfer requires driver_bones and garments arrays");
    auto transfer = std::make_shared<MeshRefitWeightTransferRuntime>();
    for (const auto& row : drivers->array_value) {
        int index = -1;
        if (row.type != JsonValue::Type::Object || !strict_int_or(row.get("submesh_index"), index)
            || !refit.driver_submesh_indices.count(index) || transfer->driver_bones.count(index))
            throw std::runtime_error("Fit weight transfer names a Part that is not a driver");
        transfer->driver_bones[index] = mesh_editor_refit_weight_ints(row.get("bones"), "driver bones", -1, 1 << 20);
    }
    for (const auto& row : garments->array_value) {
        int index = -1;
        if (row.type != JsonValue::Type::Object || !strict_int_or(row.get("submesh_index"), index)
            || !refit.garment_submesh_indices.count(index) || transfer->garment_slots.count(index))
            throw std::runtime_error("Fit weight transfer names a Part that is not a bound garment");
        transfer->garment_slots[index] = mesh_editor_refit_weight_ints(row.get("slots"), "garment slots", -1, 1023);
        auto capacities = mesh_editor_refit_weight_ints(
            row.get("capacities"), "influence capacities", 1, static_cast<int>(MESH_MAX_SKIN_INFLUENCES));
        if (capacities.size() != submeshes.at(index).vertices.size())
            throw std::runtime_error("Fit weight transfer capacities must cover every garment vertex");
        transfer->capacities[index] = std::move(capacities);
        if (const auto* motion = row.get("motion"))
            transfer->garment_motion[index] = mesh_editor_refit_weight_doubles(motion, "garment motion");
    }
    if (const auto* motion = raw.get("reference_motion")) {
        int poses = 0;
        if (!strict_int_or(raw.get("motion_poses"), poses) || poses < 1 || poses > 16 || !refit.reference_body)
            throw std::runtime_error("Fit weight transfer motion requires 1..16 poses and a reference body");
        transfer->motion_poses = static_cast<std::size_t>(poses);
        transfer->reference_motion = mesh_editor_refit_weight_doubles(motion, "reference motion");
        if (transfer->reference_motion.size() != refit.reference_body->source_positions.size() * transfer->motion_poses * 3)
            throw std::runtime_error("Fit weight transfer reference motion must cover every reference body vertex");
        for (const auto& item : transfer->garment_motion)
            if (item.second.size() != submeshes.at(item.first).vertices.size() * transfer->motion_poses * 3)
                throw std::runtime_error("Fit weight transfer garment motion must cover every garment vertex");
    } else {
        transfer->garment_motion.clear();
    }
    if (transfer->garment_slots.empty()) return nullptr;
    return transfer;
}

void mesh_editor_write_refit_weight_transfer(std::ostream& out, const MeshRefitWeightTransferRuntime& transfer) {
    const auto list = [&](const std::vector<int>& values) {
        out << '[';
        for (std::size_t k = 0; k < values.size(); ++k) out << (k ? "," : "") << values[k];
        out << ']';
    };
    const auto doubles = [&](const std::vector<double>& values) {
        out << '[' << std::setprecision(17);
        for (std::size_t k = 0; k < values.size(); ++k) out << (k ? "," : "") << values[k];
        out << ']';
    };
    out << "{\"driver_bones\":[";
    bool first = true;
    for (const auto& item : transfer.driver_bones) {
        out << (first ? "" : ",") << "{\"submesh_index\":" << item.first << ",\"bones\":";
        list(item.second);
        out << '}';
        first = false;
    }
    out << "],\"garments\":[";
    first = true;
    for (const auto& item : transfer.garment_slots) {
        out << (first ? "" : ",") << "{\"submesh_index\":" << item.first << ",\"slots\":";
        list(item.second);
        out << ",\"capacities\":";
        list(transfer.capacities.at(item.first));
        if (const auto motion = transfer.garment_motion.find(item.first); motion != transfer.garment_motion.end()) {
            out << ",\"motion\":";
            doubles(motion->second);
        }
        out << '}';
        first = false;
    }
    out << ']';
    if (transfer.motion_poses) {
        out << ",\"motion_poses\":" << transfer.motion_poses << ",\"reference_motion\":";
        doubles(transfer.reference_motion);
    }
    out << '}';
}

// Runtime snapshots carry the rows to restore, so Reset after a restore still
// gives garments back their own weights.
void mesh_editor_write_snapshot_neutral_bones(std::ostream& out, const MeshMorphRuntime& morph) {
    out << ",\"neutral_bones\":[";
    bool first = true;
    for (const auto& item : morph.neutral_bones) {
        out << (first ? "" : ",") << "{\"submesh_index\":" << item.first << ",\"counts\":[";
        first = false;
        const auto& rows = *item.second;
        for (std::size_t v = 0; v < rows.indices.size(); ++v) out << (v ? "," : "") << rows.indices[v].size();
        out << "],\"indices\":[";
        bool any = false;
        for (const auto& row : rows.indices) for (const int value : row) {
            out << (any ? "," : "") << value;
            any = true;
        }
        out << "],\"weights\":[" << std::setprecision(17);
        any = false;
        for (const auto& row : rows.weights) for (const double value : row) {
            out << (any ? "," : "") << value;
            any = true;
        }
        out << "]}";
    }
    out << ']';
}

void mesh_editor_read_snapshot_neutral_bones(
    const JsonValue* raw, const std::map<int, MeshSessionSubmesh>& submeshes, MeshMorphRuntime& morph
) {
    if (!raw) return;
    if (raw->type != JsonValue::Type::Array) throw std::runtime_error("morph runtime snapshot has invalid neutral bones");
    for (const auto& row : raw->array_value) {
        int index = -1;
        if (row.type != JsonValue::Type::Object || !strict_int_or(row.get("submesh_index"), index)
            || !submeshes.count(index) || morph.neutral_bones.count(index))
            throw std::runtime_error("morph runtime snapshot has invalid neutral bone Part");
        const auto counts = mesh_editor_refit_weight_ints(row.get("counts"), "neutral bone counts", 0, 64);
        const auto indices = mesh_editor_refit_weight_ints(row.get("indices"), "neutral bone indices", 0, 1 << 20);
        const auto* weights = row.get("weights");
        if (counts.size() != submeshes.at(index).vertices.size() || !weights || weights->type != JsonValue::Type::Array
            || weights->array_value.size() != indices.size())
            throw std::runtime_error("morph runtime snapshot neutral bone topology does not match");
        auto rows = std::make_shared<BoneAssignments>();
        std::size_t cursor = 0;
        for (const int width : counts) {
            if (cursor + static_cast<std::size_t>(width) > indices.size())
                throw std::runtime_error("morph runtime snapshot neutral bone rows are truncated");
            std::vector<int> slots(indices.begin() + static_cast<std::ptrdiff_t>(cursor),
                indices.begin() + static_cast<std::ptrdiff_t>(cursor + static_cast<std::size_t>(width)));
            std::vector<double> values;
            for (int k = 0; k < width; ++k) {
                const auto& value = weights->array_value[cursor + static_cast<std::size_t>(k)];
                if (value.type != JsonValue::Type::Number || !std::isfinite(value.number_value))
                    throw std::runtime_error("morph runtime snapshot neutral bone weights must be finite");
                values.push_back(value.number_value);
            }
            rows->indices.push_back(std::move(slots));
            rows->weights.push_back(std::move(values));
            cursor += static_cast<std::size_t>(width);
        }
        if (cursor != indices.size()) throw std::runtime_error("morph runtime snapshot neutral bone rows do not match");
        morph.neutral_bones[index] = std::move(rows);
    }
}
