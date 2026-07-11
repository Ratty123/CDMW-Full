struct Renderer::PositionUpdate {
    int source_vertex = -1;
    DirectX::XMFLOAT3 value;
};
struct Renderer::NormalUpdate {
    int source_vertex = -1;
    DirectX::XMFLOAT3 value;
};
struct Renderer::UvUpdate {
    int source_vertex = -1;
    DirectX::XMFLOAT2 value;
};
struct Renderer::ParsedUpdateGroup {
    int source_submesh = -1;
    int source_vertex_start = 0;
    int source_vertex_count = 0;
    bool source_vertex_range = false;
    bool native_core_source_positions = false;
    std::vector<PositionUpdate> positions;
    std::vector<NormalUpdate> normals;
    std::vector<UvUpdate> uvs;
};

auto Renderer::parse_mesh_vertex_update_groups(
        const std::string& payload,
        std::set<int>& group_source_submeshes) const -> std::vector<ParsedUpdateGroup> {
        std::vector<ParsedUpdateGroup> groups;
        for (const std::string& group : json_object_array_field(payload, "groups")) {
            const int source_submesh = static_cast<int>(json_float_field(group, "source_submesh_index", -1.0f));
            if (source_submesh < 0) continue;
            group_source_submeshes.insert(source_submesh);
            const int source_vertex_start = json_int_field(group, "source_vertex_start", 0);
            const int source_vertex_count = json_int_field(group, "source_vertex_count", 0);
            const bool has_source_vertex_values =
                json_has_field(group, "source_vertex_indices_binary")
                || json_has_field(group, "source_vertex_indices");
            const bool source_vertex_range =
                !has_source_vertex_values && source_vertex_start >= 0 && source_vertex_count > 0;
            std::vector<int> source_vertices;
            if (!source_vertex_range) {
                source_vertices = json_i32_array_or_json_field(group, "source_vertex_indices_binary", "source_vertex_indices");
            }
            const std::vector<float> positions = json_f64_array_or_json_field(group, "positions_binary", "positions", 3);
            const std::vector<float> normals = json_f64_array_or_json_field(group, "normals_binary", "normals", 3);
            const std::vector<float> uvs = json_f64_array_or_json_field(group, "uvs_binary", "uvs", 2);
            const std::string position_space = lower_copy(json_string_field(group, "position_space"));
            const bool source_space_positions = position_space == "source";
            const bool source_affine_positions = position_space == "source_affine";
            const bool native_core_source_positions =
                position_space.empty()
                && lower_copy(json_string_field(group, "preview_backend")) == "cdmw_mesh_core";
            const std::vector<float> position_transform = json_float_array_field(group, "position_transform");
            const std::vector<float> normal_transform = json_float_array_field(group, "normal_transform");
            const std::vector<float> normalization_center = json_float_array_field(group, "normalization_center");
            float normalization_scale = json_float_field(group, "normalization_scale", 1.0f);
            if (!std::isfinite(normalization_scale) || std::abs(normalization_scale) <= 1e-8f) {
                normalization_scale = 1.0f;
            }
            const size_t count = source_vertex_range ? static_cast<size_t>(source_vertex_count) : source_vertices.size();
            ParsedUpdateGroup parsed;
            parsed.source_submesh = source_submesh;
            parsed.source_vertex_start = source_vertex_start;
            parsed.source_vertex_count = source_vertex_count;
            parsed.source_vertex_range = source_vertex_range;
            parsed.native_core_source_positions = native_core_source_positions;
            for (size_t index = 0; index < count; ++index) {
                const int source_vertex = source_vertex_range
                    ? source_vertex_start + static_cast<int>(index)
                    : source_vertices[index];
                if (source_vertex < 0) continue;
                if (positions.size() >= (index + 1u) * 3u) {
                    float x = positions[index * 3u];
                    float y = positions[index * 3u + 1u];
                    float z = positions[index * 3u + 2u];
                    if (source_affine_positions && position_transform.size() >= 12u) {
                        const float sx = x;
                        const float sy = y;
                        const float sz = z;
                        x = position_transform[0] * sx + position_transform[1] * sy + position_transform[2] * sz + position_transform[3];
                        y = position_transform[4] * sx + position_transform[5] * sy + position_transform[6] * sz + position_transform[7];
                        z = position_transform[8] * sx + position_transform[9] * sy + position_transform[10] * sz + position_transform[11];
                    } else if (source_space_positions) {
                        const float cx = normalization_center.size() > 0u ? normalization_center[0] : 0.0f;
                        const float cy = normalization_center.size() > 1u ? normalization_center[1] : 0.0f;
                        const float cz = normalization_center.size() > 2u ? normalization_center[2] : 0.0f;
                        x = (x - cx) * normalization_scale;
                        y = (y - cy) * normalization_scale;
                        z = (z - cz) * normalization_scale;
                    }
                    parsed.positions.push_back(PositionUpdate{source_vertex, DirectX::XMFLOAT3(x, y, z)});
                }
                if (normals.size() >= (index + 1u) * 3u) {
                    float nx = normals[index * 3u];
                    float ny = normals[index * 3u + 1u];
                    float nz = normals[index * 3u + 2u];
                    if (normal_transform.size() >= 9u) {
                        const float sx = nx;
                        const float sy = ny;
                        const float sz = nz;
                        nx = normal_transform[0] * sx + normal_transform[1] * sy + normal_transform[2] * sz;
                        ny = normal_transform[3] * sx + normal_transform[4] * sy + normal_transform[5] * sz;
                        nz = normal_transform[6] * sx + normal_transform[7] * sy + normal_transform[8] * sz;
                        const float length = std::sqrt(nx * nx + ny * ny + nz * nz);
                        if (std::isfinite(length) && length > 1e-8f) {
                            nx /= length;
                            ny /= length;
                            nz /= length;
                        } else {
                            nx = 0.0f;
                            ny = 1.0f;
                            nz = 0.0f;
                        }
                    }
                    parsed.normals.push_back(NormalUpdate{source_vertex, DirectX::XMFLOAT3(nx, ny, nz)});
                }
                if (uvs.size() >= (index + 1u) * 2u) {
                    parsed.uvs.push_back(UvUpdate{source_vertex, DirectX::XMFLOAT2(uvs[index * 2u], uvs[index * 2u + 1u])});
                }
            }
            if (!parsed.positions.empty() || !parsed.normals.empty() || !parsed.uvs.empty()) {
                groups.push_back(std::move(parsed));
            }
        }
        return groups;
    }

int Renderer::apply_mesh_vertex_update_groups(
        const std::vector<ParsedUpdateGroup>& groups,
        const std::set<int>& group_source_submeshes) {
        int changed_vertices = 0;
        for (PreviewBatch& batch : batches_) {
            if (!batch.editor_editable || batch_is_reference(batch) || !batch.vertex_buffer || batch.cpu_positions.empty()) continue;
            if (batch.source_submesh_index >= 0 && group_source_submeshes.find(batch.source_submesh_index) == group_source_submeshes.end()) continue;
            bool batch_changed = false;
            size_t min_changed_vertex = std::numeric_limits<size_t>::max();
            size_t max_changed_vertex = 0;
            auto mark_changed_vertex = [&](size_t vertex_index) {
                min_changed_vertex = std::min(min_changed_vertex, vertex_index);
                max_changed_vertex = std::max(max_changed_vertex, vertex_index);
            };
            auto apply_position_update = [&](size_t vertex_index, const DirectX::XMFLOAT3& position) {
                const size_t float_offset = vertex_index * (kVertexStrideBytes / sizeof(float));
                if (vertex_index < batch.cpu_positions.size() && float_offset + 2u < batch.cpu_vertices.size()) {
                    batch.cpu_positions[vertex_index] = position;
                    batch.cpu_vertices[float_offset] = position.x;
                    batch.cpu_vertices[float_offset + 1u] = position.y;
                    batch.cpu_vertices[float_offset + 2u] = position.z;
                    batch_changed = true;
                    mark_changed_vertex(vertex_index);
                    ++changed_vertices;
                }
            };
            auto apply_normal_update = [&](size_t vertex_index, const DirectX::XMFLOAT3& normal) {
                const size_t float_offset = vertex_index * (kVertexStrideBytes / sizeof(float));
                if (float_offset + 19u < batch.cpu_vertices.size()) {
                    batch.cpu_vertices[float_offset + 3u] = normal.x;
                    batch.cpu_vertices[float_offset + 4u] = normal.y;
                    batch.cpu_vertices[float_offset + 5u] = normal.z;
                    batch.cpu_vertices[float_offset + 17u] = normal.x;
                    batch.cpu_vertices[float_offset + 18u] = normal.y;
                    batch.cpu_vertices[float_offset + 19u] = normal.z;
                    batch_changed = true;
                    mark_changed_vertex(vertex_index);
                    ++changed_vertices;
                }
            };
            auto apply_uv_update = [&](size_t vertex_index, const DirectX::XMFLOAT2& uv) {
                const size_t float_offset = vertex_index * (kVertexStrideBytes / sizeof(float));
                if (float_offset + 10u < batch.cpu_vertices.size()) {
                    batch.cpu_vertices[float_offset + 9u] = uv.x;
                    batch.cpu_vertices[float_offset + 10u] = uv.y;
                    batch_changed = true;
                    mark_changed_vertex(vertex_index);
                    ++changed_vertices;
                }
            };
            auto batch_source_submesh_at = [&](size_t vertex_index) {
                return vertex_index < batch.cpu_source_submeshes.size()
                    ? batch.cpu_source_submeshes[vertex_index]
                    : batch.source_submesh_index;
            };
            auto supports_direct_source_range = [&](const ParsedUpdateGroup& parsed) {
                if (!parsed.source_vertex_range || parsed.source_vertex_start < 0 || parsed.source_vertex_count <= 0) return false;
                const size_t start = static_cast<size_t>(parsed.source_vertex_start);
                const size_t count = static_cast<size_t>(parsed.source_vertex_count);
                if (start > batch.cpu_positions.size() || count > batch.cpu_positions.size() - start) return false;
                if (start > batch.cpu_source_vertices.size() || count > batch.cpu_source_vertices.size() - start) return false;
                for (size_t offset = 0; offset < count; ++offset) {
                    const size_t vertex_index = start + offset;
                    if (batch.cpu_source_vertices[vertex_index] != static_cast<int>(vertex_index)) return false;
                    if (batch_source_submesh_at(vertex_index) != parsed.source_submesh) return false;
                }
                return true;
            };
            bool lookup_ready = false;
            auto ensure_lookup = [&]() {
                if (!lookup_ready && batch.cpu_source_vertex_lookup.empty()) {
                    rebuild_batch_source_vertex_lookup(batch);
                }
                lookup_ready = true;
            };
            for (const ParsedUpdateGroup& parsed : groups) {
                if (supports_direct_source_range(parsed)) {
                    for (const PositionUpdate& update : parsed.positions) {
                        DirectX::XMFLOAT3 position = update.value;
                        if (parsed.native_core_source_positions) {
                            position = source_to_preview_position_for_batch(batch, position);
                        }
                        apply_position_update(static_cast<size_t>(update.source_vertex), position);
                    }
                    for (const NormalUpdate& update : parsed.normals) {
                        apply_normal_update(static_cast<size_t>(update.source_vertex), update.value);
                    }
                    for (const UvUpdate& update : parsed.uvs) {
                        apply_uv_update(static_cast<size_t>(update.source_vertex), update.value);
                    }
                    continue;
                }
                ensure_lookup();
                for (const PositionUpdate& update : parsed.positions) {
                    const std::pair<int, int> key(parsed.source_submesh, update.source_vertex);
                    auto lookup = batch.cpu_source_vertex_lookup.find(key);
                    if (lookup == batch.cpu_source_vertex_lookup.end()) continue;
                    DirectX::XMFLOAT3 position = update.value;
                    if (parsed.native_core_source_positions) {
                        position = source_to_preview_position_for_batch(batch, position);
                    }
                    for (size_t vertex_index : lookup->second) {
                        apply_position_update(vertex_index, position);
                    }
                }
                for (const NormalUpdate& update : parsed.normals) {
                    const std::pair<int, int> key(parsed.source_submesh, update.source_vertex);
                    auto lookup = batch.cpu_source_vertex_lookup.find(key);
                    if (lookup == batch.cpu_source_vertex_lookup.end()) continue;
                    for (size_t vertex_index : lookup->second) {
                        apply_normal_update(vertex_index, update.value);
                    }
                }
                for (const UvUpdate& update : parsed.uvs) {
                    const std::pair<int, int> key(parsed.source_submesh, update.source_vertex);
                    auto lookup = batch.cpu_source_vertex_lookup.find(key);
                    if (lookup == batch.cpu_source_vertex_lookup.end()) continue;
                    for (size_t vertex_index : lookup->second) {
                        apply_uv_update(vertex_index, update.value);
                    }
                }
            }
            if (batch_changed && min_changed_vertex != std::numeric_limits<size_t>::max()) {
                batch.pending_vertex_upload = true;
                batch.pending_vertex_upload_min = std::min(batch.pending_vertex_upload_min, min_changed_vertex);
                batch.pending_vertex_upload_max = std::max(batch.pending_vertex_upload_max, max_changed_vertex);
            }
        }
        if (changed_vertices > 0) {
            invalidate_mesh_edit_caches();
        }
        return changed_vertices;
    }


int Renderer::update_mesh_edit_vertices_from_payload(const std::string& payload) {
        std::set<int> group_source_submeshes;
        const std::vector<ParsedUpdateGroup> groups = parse_mesh_vertex_update_groups(payload, group_source_submeshes);
        if (groups.empty()) return 0;
        return apply_mesh_vertex_update_groups(groups, group_source_submeshes);
    }

void Renderer::flush_pending_mesh_edit_vertex_uploads() {
        if (!context_) return;
        for (PreviewBatch& batch : batches_) {
            if (!batch.pending_vertex_upload || !batch.vertex_buffer || batch.cpu_vertices.empty()) continue;
            const size_t vertex_limit = std::min(
                batch.cpu_positions.size(),
                batch.cpu_vertices.size() / (kVertexStrideBytes / sizeof(float)));
            if (vertex_limit == 0) {
                batch.pending_vertex_upload = false;
                batch.pending_vertex_upload_min = std::numeric_limits<size_t>::max();
                batch.pending_vertex_upload_max = 0;
                continue;
            }
            const size_t min_changed_vertex = std::min(batch.pending_vertex_upload_min, vertex_limit - 1u);
            const size_t max_changed_vertex = std::min(batch.pending_vertex_upload_max, vertex_limit - 1u);
            const bool full_buffer_update = min_changed_vertex == 0u && max_changed_vertex + 1u >= vertex_limit;
            if (full_buffer_update) {
                context_->UpdateSubresource(batch.vertex_buffer.Get(), 0, nullptr, batch.cpu_vertices.data(), 0, 0);
            } else {
                D3D11_BOX box{};
                box.left = static_cast<UINT>(min_changed_vertex * kVertexStrideBytes);
                box.right = static_cast<UINT>((max_changed_vertex + 1u) * kVertexStrideBytes);
                box.top = 0;
                box.bottom = 1;
                box.front = 0;
                box.back = 1;
                context_->UpdateSubresource(
                    batch.vertex_buffer.Get(),
                    0,
                    &box,
                    batch.cpu_vertices.data() + min_changed_vertex * (kVertexStrideBytes / sizeof(float)),
                    0,
                    0);
            }
            batch.pending_vertex_upload = false;
            batch.pending_vertex_upload_min = std::numeric_limits<size_t>::max();
            batch.pending_vertex_upload_max = 0;
        }
    }

static int triangle_source_vertex_id(const TriangleReplacementGroup& group, size_t source_slot) {
        if (group.source_vertex_range && source_slot < static_cast<size_t>(group.source_vertex_range_count)) {
            return group.source_vertex_start + static_cast<int>(source_slot);
        }
        return source_slot < group.source_vertices.size()
            ? group.source_vertices[source_slot]
            : static_cast<int>(source_slot);
}

static int triangle_source_face_id(const TriangleReplacementGroup& group, size_t face_slot) {
        if (group.source_face_range && face_slot < static_cast<size_t>(group.source_face_range_count)) {
            return group.source_face_start + static_cast<int>(face_slot);
        }
        return face_slot < group.source_faces.size()
            ? group.source_faces[face_slot]
            : static_cast<int>(face_slot);
}

static TriangleReplacementGroup parse_triangle_replacement_group(const std::string& payload) {
        TriangleReplacementGroup group;
        group.payload = payload;
        group.source_submesh = static_cast<int>(json_float_field(payload, "source_submesh_index", -1.0f));
        group.positions = json_f64_array_or_json_field(payload, "positions_binary", "positions", 3);
        group.normals = json_f64_array_or_json_field(payload, "normals_binary", "normals", 3);
        group.uvs = json_f64_array_or_json_field(payload, "uvs_binary", "uvs", 2);
        group.source_vertex_start = json_int_field(payload, "source_vertex_start", -1);
        group.source_vertex_range_count = json_int_field(payload, "source_vertex_count", 0);
        group.source_face_start = json_int_field(payload, "source_face_start", -1);
        group.source_face_range_count = json_int_field(payload, "source_face_count", 0);
        const bool has_source_vertex_values =
            json_has_field(payload, "source_vertex_indices_binary")
            || json_has_field(payload, "source_vertex_indices");
        const bool has_source_face_values =
            json_has_field(payload, "source_face_indices_binary")
            || json_has_field(payload, "source_face_indices");
        group.source_vertex_range =
            !has_source_vertex_values && group.source_vertex_start >= 0 && group.source_vertex_range_count > 0;
        group.source_face_range =
            !has_source_face_values && group.source_face_start >= 0 && group.source_face_range_count > 0;
        if (!group.source_vertex_range) {
            group.source_vertices = json_i32_array_or_json_field(
                payload, "source_vertex_indices_binary", "source_vertex_indices");
        }
        if (!group.source_face_range) {
            group.source_faces = json_i32_array_or_json_field(payload, "source_face_indices_binary", "source_face_indices");
        }
        group.indices = json_i32_array_or_json_field(payload, "indices_binary", "indices");
        group.indexed_payload = json_has_field(payload, "indices") || json_has_field(payload, "indices_binary");
        const std::string position_space = lower_copy(json_string_field(payload, "position_space"));
        group.source_space_positions = position_space == "source";
        group.source_affine_positions = position_space == "source_affine";
        group.native_core_source_positions =
            position_space.empty()
            && lower_copy(json_string_field(payload, "preview_backend")) == "cdmw_mesh_core";
        group.position_transform = json_float_array_field(payload, "position_transform");
        group.normal_transform = json_float_array_field(payload, "normal_transform");
        group.normalization_center = json_float_array_field(payload, "normalization_center");
        group.normalization_scale = json_float_field(payload, "normalization_scale", 1.0f);
        if (!std::isfinite(group.normalization_scale) || std::abs(group.normalization_scale) <= 1e-8f) {
            group.normalization_scale = 1.0f;
        }
        group.source_vertex_count = group.positions.size() / 3u;
        group.source_vertex_identity_count = static_cast<int>(group.source_vertex_count);
        if (group.source_vertex_range) {
            group.source_vertex_identity_count = std::max(
                group.source_vertex_identity_count,
                group.source_vertex_start + group.source_vertex_range_count);
        } else {
            for (const int source_vertex : group.source_vertices) {
                group.source_vertex_identity_count = std::max(group.source_vertex_identity_count, source_vertex + 1);
            }
        }
        const size_t face_count = group.indexed_payload
            ? group.indices.size() / 3u
            : group.source_vertex_count / 3u;
        group.source_face_identity_count = static_cast<int>(face_count);
        if (group.source_face_range) {
            group.source_face_identity_count = std::max(
                group.source_face_identity_count,
                group.source_face_start + group.source_face_range_count);
        } else {
            for (const int source_face : group.source_faces) {
                group.source_face_identity_count = std::max(group.source_face_identity_count, source_face + 1);
            }
        }
        return group;
}

static DirectX::XMFLOAT3 transform_replacement_normal(
        const TriangleReplacementGroup& group,
        DirectX::XMFLOAT3 normal) {
        if (group.normal_transform.size() < 9u) return normal;
        const float sx = normal.x;
        const float sy = normal.y;
        const float sz = normal.z;
        normal.x = group.normal_transform[0] * sx + group.normal_transform[1] * sy + group.normal_transform[2] * sz;
        normal.y = group.normal_transform[3] * sx + group.normal_transform[4] * sy + group.normal_transform[5] * sz;
        normal.z = group.normal_transform[6] * sx + group.normal_transform[7] * sy + group.normal_transform[8] * sz;
        const float length = std::sqrt(normal.x * normal.x + normal.y * normal.y + normal.z * normal.z);
        if (std::isfinite(length) && length > 1e-8f) {
            normal.x /= length;
            normal.y /= length;
            normal.z /= length;
        } else {
            normal = DirectX::XMFLOAT3(0.0f, 1.0f, 0.0f);
        }
        return normal;
}

DirectX::XMFLOAT3 Renderer::transform_replacement_position(
        const PreviewBatch& batch,
        const TriangleReplacementGroup& group,
        DirectX::XMFLOAT3 position) const {
        if (group.source_affine_positions && group.position_transform.size() >= 12u) {
            const float sx = position.x;
            const float sy = position.y;
            const float sz = position.z;
            position.x = group.position_transform[0] * sx + group.position_transform[1] * sy + group.position_transform[2] * sz + group.position_transform[3];
            position.y = group.position_transform[4] * sx + group.position_transform[5] * sy + group.position_transform[6] * sz + group.position_transform[7];
            position.z = group.position_transform[8] * sx + group.position_transform[9] * sy + group.position_transform[10] * sz + group.position_transform[11];
        } else if (group.source_space_positions) {
            const float cx = group.normalization_center.size() > 0u ? group.normalization_center[0] : 0.0f;
            const float cy = group.normalization_center.size() > 1u ? group.normalization_center[1] : 0.0f;
            const float cz = group.normalization_center.size() > 2u ? group.normalization_center[2] : 0.0f;
            position.x = (position.x - cx) * group.normalization_scale;
            position.y = (position.y - cy) * group.normalization_scale;
            position.z = (position.z - cz) * group.normalization_scale;
        } else if (group.native_core_source_positions) {
            position = source_to_preview_position_for_batch(batch, position);
        }
        return position;
}

int Renderer::remove_replaced_mesh_batches(
        const std::string& payload,
        const std::vector<std::string>& groups,
        bool replace_all) {
        std::set<int> requested_source_submeshes;
        std::set<int> group_source_submeshes;
        for (const int source_submesh : json_int_array_field(payload, "source_submesh_indices")) {
            if (source_submesh >= 0) requested_source_submeshes.insert(source_submesh);
        }
        for (const std::string& group : groups) {
            const int source_submesh = static_cast<int>(json_float_field(group, "source_submesh_index", -1.0f));
            if (source_submesh >= 0) {
                requested_source_submeshes.insert(source_submesh);
                group_source_submeshes.insert(source_submesh);
            }
        }
        const size_t before_count = batches_.size();
        batches_.erase(
            std::remove_if(
                batches_.begin(),
                batches_.end(),
                [&](const PreviewBatch& batch) {
                    if (!batch.editor_editable || batch_is_reference(batch) || batch.source_submesh_index < 0) {
                        return false;
                    }
                    const bool requested =
                        requested_source_submeshes.find(batch.source_submesh_index) != requested_source_submeshes.end();
                    return replace_all
                        ? !requested
                        : requested && group_source_submeshes.find(batch.source_submesh_index) == group_source_submeshes.end();
                }),
            batches_.end());
        for (size_t index = 0; index < batches_.size(); ++index) {
            batches_[index].index = static_cast<int>(index);
        }
        return static_cast<int>(before_count - batches_.size());
}

void Renderer::ensure_triangle_replacement_batch(const TriangleReplacementGroup& group) {
        if (group.source_vertex_count == 0) return;
        for (const PreviewBatch& batch : batches_) {
            if (batch.editor_editable && !batch_is_reference(batch) && batch.source_submesh_index == group.source_submesh) {
                return;
            }
        }
        const int material_source_submesh = static_cast<int>(json_float_field(
            group.payload, "material_source_submesh_index", static_cast<float>(group.source_submesh)));
        const PreviewBatch* material_template = nullptr;
        for (const PreviewBatch& batch : batches_) {
            if (batch.editor_editable && !batch_is_reference(batch)
                && batch.source_submesh_index == material_source_submesh) {
                material_template = &batch;
                break;
            }
        }
        PreviewBatch new_batch;
        if (material_template) {
            new_batch = *material_template;
            new_batch.cpu_positions.clear();
            new_batch.cpu_source_submeshes.clear();
            new_batch.cpu_source_vertices.clear();
            new_batch.cpu_source_faces.clear();
            new_batch.cpu_source_vertex_lookup.clear();
            new_batch.cpu_source_face_vertex_lookup.clear();
            new_batch.cpu_vertices.clear();
            new_batch.vertex_buffer.Reset();
            new_batch.identity_file.clear();
            new_batch.identity_offset = 0;
            new_batch.identity_size = 0;
            new_batch.identity_stride_bytes = 0;
        }
        new_batch.index = static_cast<int>(batches_.size());
        new_batch.source_submesh_index = group.source_submesh;
        new_batch.source_local_submesh_index = group.source_submesh;
        new_batch.source_vertex_count = group.source_vertex_identity_count;
        new_batch.source_face_count = group.source_face_identity_count;
        new_batch.editor_role = "replacement_preview";
        new_batch.editor_editable = true;
        new_batch.part_label = json_string_field(
            group.payload,
            "material_name",
            material_template ? material_template->part_label : "mesh_edit_part");
        new_batch.source_component_label = new_batch.part_label;
        const std::string alpha_mode = lower_copy(json_string_field(group.payload, "preview_alpha_mode"));
        if (!alpha_mode.empty()) {
            new_batch.alpha_cutout =
                alpha_mode == "mask" || alpha_mode == "alpha_cutout" || alpha_mode == "cutout";
        }
        new_batch.flip_v = json_bool_field(group.payload, "preview_texture_flip_vertical", new_batch.flip_v);
        new_batch.two_sided = json_bool_field(group.payload, "preview_double_sided", new_batch.two_sided);
        batches_.push_back(std::move(new_batch));
}

int Renderer::apply_triangle_replacement_group(const TriangleReplacementGroup& group) {
        int replaced_batches = 0;
        for (PreviewBatch& batch : batches_) {
            if (!batch.editor_editable || batch_is_reference(batch)
                || batch.source_submesh_index != group.source_submesh) continue;
            batch.source_vertex_count = group.source_vertex_identity_count;
            batch.source_face_count = group.source_face_identity_count;
            batch.cpu_positions.clear();
            batch.cpu_source_submeshes.clear();
            batch.cpu_source_vertices.clear();
            batch.cpu_source_faces.clear();
            batch.cpu_source_vertex_lookup.clear();
            batch.cpu_source_face_vertex_lookup.clear();
            batch.cpu_vertices.clear();
            batch.vertex_buffer.Reset();
            const size_t output_vertex_count = group.indexed_payload
                ? group.indices.size()
                : group.source_vertex_count;
            batch.cpu_positions.reserve(output_vertex_count);
            batch.cpu_source_submeshes.reserve(output_vertex_count);
            batch.cpu_source_vertices.reserve(output_vertex_count);
            batch.cpu_source_faces.reserve(output_vertex_count);
            batch.cpu_vertices.reserve(output_vertex_count * (kVertexStrideBytes / sizeof(float)));
            const float color_r = std::clamp(batch.base_color[0], 0.0f, 1.0f);
            const float color_g = std::clamp(batch.base_color[1], 0.0f, 1.0f);
            const float color_b = std::clamp(batch.base_color[2], 0.0f, 1.0f);
            auto append_vertex = [&](size_t source_slot, int source_face) {
                if (source_slot >= group.source_vertex_count) return;
                DirectX::XMFLOAT3 position(
                    group.positions[source_slot * 3u],
                    group.positions[source_slot * 3u + 1u],
                    group.positions[source_slot * 3u + 2u]);
                DirectX::XMFLOAT3 normal(0.0f, 1.0f, 0.0f);
                if (group.normals.size() >= (source_slot + 1u) * 3u) {
                    normal = DirectX::XMFLOAT3(
                        group.normals[source_slot * 3u],
                        group.normals[source_slot * 3u + 1u],
                        group.normals[source_slot * 3u + 2u]);
                }
                position = transform_replacement_position(batch, group, position);
                normal = transform_replacement_normal(group, normal);
                DirectX::XMFLOAT2 uv(0.0f, 0.0f);
                if (group.uvs.size() >= (source_slot + 1u) * 2u) {
                    uv = DirectX::XMFLOAT2(
                        group.uvs[source_slot * 2u],
                        group.uvs[source_slot * 2u + 1u]);
                }
                batch.cpu_positions.push_back(position);
                batch.cpu_source_submeshes.push_back(group.source_submesh);
                batch.cpu_source_vertices.push_back(triangle_source_vertex_id(group, source_slot));
                batch.cpu_source_faces.push_back(
                    source_face >= 0 ? source_face : static_cast<int>(source_slot / 3u));
                const float values[23] = {
                    position.x, position.y, position.z,
                    normal.x, normal.y, normal.z,
                    color_r, color_g, color_b,
                    uv.x, uv.y,
                    1.0f, 0.0f, 0.0f,
                    0.0f, 1.0f, 0.0f,
                    normal.x, normal.y, normal.z,
                    0.0f, 0.0f, 0.0f,
                };
                batch.cpu_vertices.insert(batch.cpu_vertices.end(), values, values + 23);
            };
            if (group.indexed_payload) {
                for (size_t index_position = 0; index_position < group.indices.size(); ++index_position) {
                    const int raw_index = group.indices[index_position];
                    if (raw_index >= 0) {
                        append_vertex(
                            static_cast<size_t>(raw_index),
                            triangle_source_face_id(group, index_position / 3u));
                    }
                }
            } else {
                for (size_t index = 0; index < group.source_vertex_count; ++index) {
                    append_vertex(index, triangle_source_face_id(group, index / 3u));
                }
            }
            batch.vertex_count = static_cast<int>(batch.cpu_positions.size());
            rebuild_batch_source_vertex_lookup(batch);
            rebuild_batch_source_face_vertex_lookup(batch);
            if (batch.vertex_count > 0 && device_) {
                D3D11_BUFFER_DESC desc{};
                desc.ByteWidth = static_cast<UINT>(batch.cpu_vertices.size() * sizeof(float));
                desc.Usage = D3D11_USAGE_DEFAULT;
                desc.BindFlags = D3D11_BIND_VERTEX_BUFFER;
                D3D11_SUBRESOURCE_DATA init{};
                init.pSysMem = batch.cpu_vertices.data();
                if (FAILED(device_->CreateBuffer(&desc, &init, batch.vertex_buffer.GetAddressOf()))) {
                    batch.vertex_buffer.Reset();
                }
            }
            ++replaced_batches;
        }
        return replaced_batches;
}

std::pair<int, int> Renderer::replace_mesh_edit_triangles_from_payload(const std::string& payload) {
        const bool replace_all = json_bool_field(payload, "replace_all", false);
        const std::vector<std::string> groups = json_object_array_field(payload, "groups");
        int removed_batches = remove_replaced_mesh_batches(payload, groups, replace_all);
        int replaced_batches = 0;
        for (const std::string& payload_group : groups) {
            const TriangleReplacementGroup group = parse_triangle_replacement_group(payload_group);
            if (group.source_submesh < 0) continue;
            ensure_triangle_replacement_batch(group);
            replaced_batches += apply_triangle_replacement_group(group);
        }
        if (replaced_batches > 0 || removed_batches > 0) {
            invalidate_mesh_edit_caches();
        }
        return std::pair<int, int>(replaced_batches, removed_batches);
}
