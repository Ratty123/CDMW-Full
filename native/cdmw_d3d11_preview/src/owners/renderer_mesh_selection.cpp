std::string Renderer::mesh_edit_screen_drag_json(int start_x, int start_y, int end_x, int end_y) const {
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        DirectX::XMFLOAT4X4 world_view_projection{};
        DirectX::XMStoreFloat4x4(&world_view_projection, current_mvp_matrix());
        std::ostringstream out;
        out << "{\"start_x\":" << start_x
            << ",\"start_y\":" << start_y
            << ",\"end_x\":" << end_x
            << ",\"end_y\":" << end_y
            << ",\"viewport_x\":" << viewport.TopLeftX
            << ",\"viewport_y\":" << viewport.TopLeftY
            << ",\"viewport_width\":" << std::max(1.0f, viewport.Width)
            << ",\"viewport_height\":" << std::max(1.0f, viewport.Height)
            << ",\"world_view_projection\":" << matrix4x4_json(world_view_projection);
        out << mesh_edit_source_projection_overrides_json();
        out << "}";
        return out.str();
    }

std::string Renderer::mesh_edit_screen_radius_json(float radius_pixels) const {
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        DirectX::XMFLOAT4X4 world_view_projection{};
        DirectX::XMStoreFloat4x4(&world_view_projection, current_mvp_matrix());
        std::ostringstream out;
        out << "{\"radius_pixels\":" << std::max(0.0f, radius_pixels)
            << ",\"viewport_x\":" << viewport.TopLeftX
            << ",\"viewport_y\":" << viewport.TopLeftY
            << ",\"viewport_width\":" << std::max(1.0f, viewport.Width)
            << ",\"viewport_height\":" << std::max(1.0f, viewport.Height)
            << ",\"world_view_projection\":" << matrix4x4_json(world_view_projection)
            << ",\"amount_scale\":0.08";
        out << mesh_edit_source_projection_overrides_json();
        out << "}";
        return out.str();
    }

std::string Renderer::mesh_edit_source_projection_overrides_json() const {
        if (!alignment_preview_transform_active()
            && std::none_of(batches_.begin(), batches_.end(), [this](const PreviewBatch& batch) {
                return batch.editor_editable
                    && !batch_is_reference(batch)
                    && batch.source_submesh_index >= 0
                    && batch_uses_source_normalization(batch);
            })) {
            return "";
        }
        std::ostringstream out;
        std::set<int> emitted;
        bool wrote_any = false;
        for (const PreviewBatch& batch : batches_) {
            if (!batch.editor_editable
                || batch_is_reference(batch)
                || batch.source_submesh_index < 0
                || !mesh_edit_source_allowed(batch.source_submesh_index)
                || batch.cpu_positions.empty()
                || emitted.find(batch.source_submesh_index) != emitted.end()) {
                continue;
            }
            DirectX::XMFLOAT4X4 world_transform{};
            DirectX::XMStoreFloat4x4(&world_transform, mesh_edit_source_world_transform_for_batch(batch));
            out << (wrote_any ? "," : ",\"source_submesh_world_transforms\":[")
                << "{\"source_submesh_index\":" << batch.source_submesh_index
                << ",\"world_transform\":" << matrix4x4_json(world_transform)
                << "}";
            emitted.insert(batch.source_submesh_index);
            wrote_any = true;
        }
        if (!wrote_any) {
            return "";
        }
        out << "]";
        return out.str();
    }

std::string Renderer::mesh_edit_screen_brush_json(int x, int y, float radius_pixels, bool include_source_filter) const {
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        DirectX::XMFLOAT4X4 world_view_projection{};
        DirectX::XMStoreFloat4x4(&world_view_projection, current_mvp_matrix());
        std::ostringstream out;
        out << "{\"x\":" << x
            << ",\"y\":" << y
            << ",\"radius_pixels\":" << std::max(0.0f, radius_pixels)
            << ",\"viewport_x\":" << viewport.TopLeftX
            << ",\"viewport_y\":" << viewport.TopLeftY
            << ",\"viewport_width\":" << std::max(1.0f, viewport.Width)
            << ",\"viewport_height\":" << std::max(1.0f, viewport.Height)
            << ",\"world_view_projection\":" << matrix4x4_json(world_view_projection);
        if (include_source_filter && !mesh_edit_.source_submesh_indices.empty()) {
            out << ",\"source_submesh_indices\":[";
            size_t index = 0;
            for (int source_index : mesh_edit_.source_submesh_indices) {
                if (index++) out << ",";
                out << source_index;
            }
            out << "]";
        }
        out << mesh_edit_source_projection_overrides_json();
        out << "}";
        return out.str();
    }

std::string Renderer::mesh_edit_screen_region_json(int x, int y) const {
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        DirectX::XMFLOAT4X4 world_view_projection{};
        DirectX::XMStoreFloat4x4(&world_view_projection, current_mvp_matrix());
        std::ostringstream out;
        out << "{\"mode\":\"" << json_escape(mesh_edit_.selection_mode) << "\""
            << ",\"start_x\":" << mesh_edit_.start_x
            << ",\"start_y\":" << mesh_edit_.start_y
            << ",\"end_x\":" << x
            << ",\"end_y\":" << y
            << ",\"viewport_x\":" << viewport.TopLeftX
            << ",\"viewport_y\":" << viewport.TopLeftY
            << ",\"viewport_width\":" << std::max(1.0f, viewport.Width)
            << ",\"viewport_height\":" << std::max(1.0f, viewport.Height)
            << ",\"world_view_projection\":" << matrix4x4_json(world_view_projection);
        if (!mesh_edit_.selection_lasso_points.empty()) {
            out << ",\"points\":[";
            for (size_t index = 0; index < mesh_edit_.selection_lasso_points.size(); ++index) {
                if (index) out << ",";
                out << "[" << mesh_edit_.selection_lasso_points[index].x << "," << mesh_edit_.selection_lasso_points[index].y << "]";
            }
            out << "]";
        }
        if (!mesh_edit_.source_submesh_indices.empty()) {
            out << ",\"source_submesh_indices\":[";
            size_t index = 0;
            for (int source_index : mesh_edit_.source_submesh_indices) {
                if (index++) out << ",";
                out << source_index;
            }
            out << "]";
        }
        out << mesh_edit_source_projection_overrides_json();
        out << "}";
        return out.str();
    }

std::string Renderer::mesh_edit_payload_json(
        int x,
        int y,
        bool invert,
        bool include_screen_selection) const {
        const std::string tool = mesh_edit_.tool;
        const bool transform_tool = tool == "move" || tool == "vertex";
        const bool grab_tool = tool == "grab";
        const bool smooth_tool = tool == "smooth";
        const bool amount_tool = tool == "inflate" || tool == "pinch";
        const bool remove_screen_tool = tool == "remove" && mesh_edit_.delete_mode != "selection";
        const bool grab_screen_brush_tool = grab_tool && mesh_edit_.target_mode != "selection";
        const bool screen_brush_tool = grab_screen_brush_tool || smooth_tool || amount_tool || remove_screen_tool;
        std::ostringstream out;
        if (transform_tool) {
            out << "{\"stroke_id\":" << mesh_edit_.stroke_id
                << ",\"frame_count\":" << frame_count_
                << ",\"tool\":\"" << json_escape(tool) << "\""
                << ",\"screen_drag\":" << mesh_edit_screen_drag_json(mesh_edit_.last_x, mesh_edit_.last_y, x, y);
            if (include_screen_selection) {
                const std::string target_mode = mesh_edit_.target_mode == "selection" ? "vertex" : mesh_edit_.target_mode;
                out << ",\"target_mode\":\"" << json_escape(target_mode) << "\""
                    << ",\"selection_depth_mode\":\"" << json_escape(mesh_edit_.selection_depth_mode) << "\""
                    << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, mesh_edit_.radius_pixels)
                    << ",\"falloff\":\"" << json_escape(mesh_edit_.falloff) << "\"";
            }
            out << "}";
            return out.str();
        }
        out << "{\"stroke_id\":" << mesh_edit_.stroke_id
            << ",\"frame_count\":" << frame_count_
            << ",\"tool\":\"" << json_escape(tool) << "\"";
        if (screen_brush_tool || include_screen_selection) {
            const std::string target_mode = remove_screen_tool ? "face" : (include_screen_selection && mesh_edit_.target_mode == "selection" ? "vertex" : mesh_edit_.target_mode);
            out << ",\"target_mode\":\"" << json_escape(target_mode) << "\""
                << ",\"selection_depth_mode\":\"" << json_escape(mesh_edit_.selection_depth_mode) << "\"";
        }
        if (grab_tool) {
            out << ",\"screen_drag\":" << mesh_edit_screen_drag_json(mesh_edit_.last_x, mesh_edit_.last_y, x, y)
                << ",\"strength\":" << std::clamp(mesh_edit_.strength, 0.0f, 1.0f);
            if (grab_screen_brush_tool || include_screen_selection) {
                out << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, mesh_edit_.radius_pixels)
                    << ",\"falloff\":\"" << json_escape(mesh_edit_.falloff) << "\"";
            }
        } else if (smooth_tool) {
            out << ",\"strength\":" << std::clamp(mesh_edit_.strength, 0.0f, 1.0f)
                << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, mesh_edit_.radius_pixels)
                << ",\"smooth_iterations\":" << std::clamp(mesh_edit_.smooth_iterations, 1, 12);
        } else if (amount_tool) {
            out << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, mesh_edit_.radius_pixels)
                << ",\"screen_radius\":" << mesh_edit_screen_radius_json(mesh_edit_.radius_pixels)
                << ",\"strength\":" << std::clamp(mesh_edit_.strength, 0.0f, 1.0f)
                << ",\"invert\":" << (invert ? "true" : "false");
        } else if (remove_screen_tool) {
            out << ",\"delete_mode\":\"" << json_escape(mesh_edit_.delete_mode) << "\""
                << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, mesh_edit_.radius_pixels)
                << ",\"falloff\":\"" << json_escape(mesh_edit_.falloff) << "\"";
        }
        out << "}";
        return out.str();
    }

void Renderer::send_mesh_edit_event(const char* event_name, const std::string& payload_json) const {
        std::ostringstream out;
        out << "{\"event\":\"" << json_escape(event_name ? event_name : "") << "\",\"payload\":" << payload_json << "}";
        send_json_event(out.str());
    }

void Renderer::add_mesh_edit_face_vertices_to_selection(int source_submesh, const std::set<int>& source_faces) {
        if (source_submesh < 0 || source_faces.empty()) return;
        for (PreviewBatch& batch : batches_) {
            if (!batch.editor_editable || batch_is_reference(batch) || batch.source_submesh_index != source_submesh) continue;
            if (batch.cpu_source_face_vertex_lookup.empty() && !batch.cpu_source_faces.empty() && !batch.cpu_source_vertices.empty()) {
                rebuild_batch_source_face_vertex_lookup(batch);
            }
            if (!batch.cpu_source_face_vertex_lookup.empty()) {
                for (int source_face : source_faces) {
                    auto lookup = batch.cpu_source_face_vertex_lookup.find(std::pair<int, int>(source_submesh, source_face));
                    if (lookup == batch.cpu_source_face_vertex_lookup.end()) continue;
                    for (int source_vertex : lookup->second) {
                        mesh_edit_.selected_vertices.insert(std::pair<int, int>(source_submesh, source_vertex));
                    }
                }
                continue;
            }
            const size_t vertex_limit = std::min(batch.cpu_source_faces.size(), batch.cpu_source_vertices.size());
            for (size_t vertex_index = 0; vertex_index < vertex_limit; ++vertex_index) {
                const int source_face = batch.cpu_source_faces[vertex_index];
                const int source_vertex = batch.cpu_source_vertices[vertex_index];
                if (source_vertex >= 0 && source_faces.find(source_face) != source_faces.end()) {
                    mesh_edit_.selected_vertices.insert(std::pair<int, int>(source_submesh, source_vertex));
                }
            }
        }
    }

void Renderer::add_mesh_edit_source_vertices_to_selection(int source_submesh) {
        if (source_submesh < 0) return;
        for (const PreviewBatch& batch : batches_) {
            if (!batch.editor_editable || batch_is_reference(batch) || batch.source_submesh_index != source_submesh) continue;
            if (!batch.cpu_source_vertex_lookup.empty()) {
                for (const auto& item : batch.cpu_source_vertex_lookup) {
                    if (item.first.first == source_submesh && item.first.second >= 0) {
                        mesh_edit_.selected_vertices.insert(item.first);
                    }
                }
                continue;
            }
            const size_t vertex_limit = std::min(
                batch.cpu_positions.size(),
                batch.cpu_vertices.size() / (kVertexStrideBytes / sizeof(float)));
            if (vertex_limit > 0) {
                for (size_t vertex_index = 0; vertex_index < vertex_limit; ++vertex_index) {
                    const std::pair<int, int> key = mesh_edit_source_key(batch, vertex_index);
                    if (key.first == source_submesh && key.second >= 0) {
                        mesh_edit_.selected_vertices.insert(key);
                    }
                }
                continue;
            }
            for (int source_vertex = 0; source_vertex < batch.source_vertex_count; ++source_vertex) {
                mesh_edit_.selected_vertices.insert(std::pair<int, int>(source_submesh, source_vertex));
            }
        }
    }

std::tuple<int, int, int> Renderer::mesh_edit_edge_key(int source_submesh, int left, int right) {
        if (right < left) std::swap(left, right);
        return std::tuple<int, int, int>(source_submesh, left, right);
    }

void Renderer::send_mesh_edit_screen_brush_selection_event(int x, int y) {
        ++stats_.mesh_edit_selection_event_count;
        std::ostringstream payload;
        payload << "{\"operation\":\"" << json_escape(mesh_edit_.selection_operation) << "\""
            << ",\"target_mode\":\"" << json_escape(mesh_edit_.target_mode) << "\""
            << ",\"selection_depth_mode\":\"" << json_escape(mesh_edit_.selection_depth_mode) << "\""
            << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, mesh_edit_.radius_pixels)
            << ",\"falloff\":\"" << json_escape(mesh_edit_.falloff) << "\"}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }

void Renderer::send_mesh_edit_screen_region_selection_event(int x, int y) {
        ++stats_.mesh_edit_selection_event_count;
        std::ostringstream payload;
        payload << "{\"operation\":\"" << json_escape(mesh_edit_.selection_operation) << "\""
            << ",\"target_mode\":\"" << json_escape(mesh_edit_.target_mode) << "\""
            << ",\"selection_depth_mode\":\"" << json_escape(mesh_edit_.selection_depth_mode) << "\""
            << ",\"screen_region\":" << mesh_edit_screen_region_json(x, y) << "}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }

void Renderer::send_mesh_edit_selection_event(bool include_screen_brush) {
        ++stats_.mesh_edit_selection_event_count;
        std::map<int, std::vector<int>> grouped;
        std::set<int> source_submeshes;
        for (const auto& key : mesh_edit_.selected_vertices) {
            grouped[key.first].push_back(key.second);
            source_submeshes.insert(key.first);
        }
        std::map<int, std::vector<std::pair<int, int>>> grouped_edges;
        for (const auto& key : mesh_edit_.selected_edges) {
            const int source_submesh = std::get<0>(key);
            grouped_edges[source_submesh].push_back(std::pair<int, int>(std::get<1>(key), std::get<2>(key)));
            source_submeshes.insert(source_submesh);
        }
        std::map<int, std::vector<int>> grouped_faces;
        for (const auto& key : mesh_edit_.selected_faces) {
            grouped_faces[key.first].push_back(key.second);
            source_submeshes.insert(key.first);
        }
        for (const int source_submesh : mesh_edit_.selected_sources) {
            source_submeshes.insert(source_submesh);
        }
        std::ostringstream payload;
        payload << "{\"selected_vertex_count\":" << mesh_edit_.selected_vertices.size()
            << ",\"selected_edge_count\":" << mesh_edit_.selected_edges.size()
            << ",\"selected_face_count\":" << mesh_edit_.selected_faces.size()
            << ",\"operation\":\"" << json_escape(mesh_edit_.selection_operation) << "\"";
        if (include_screen_brush) {
            payload << ",\"screen_brush\":" << mesh_edit_screen_brush_json(mesh_edit_.last_x, mesh_edit_.last_y, mesh_edit_.radius_pixels)
                << ",\"selection_depth_mode\":\"" << json_escape(mesh_edit_.selection_depth_mode) << "\""
                << ",\"falloff\":\"" << json_escape(mesh_edit_.falloff) << "\"";
        }
        payload << ",\"groups\":[";
        size_t group_index = 0;
        for (int source_submesh : source_submeshes) {
            if (group_index++) payload << ",";
            std::vector<int>& vertices = grouped[source_submesh];
            std::sort(vertices.begin(), vertices.end());
            payload << "{\"source_submesh_index\":" << source_submesh;
            if (mesh_edit_.selected_sources.find(source_submesh) != mesh_edit_.selected_sources.end()) {
                payload << ",\"source_selected\":true";
            } else {
                write_i32_range_or_descriptor_json(
                    payload,
                    vertices,
                    "source_vertex_indices",
                    "source_vertex_indices_binary",
                    "source_vertex_start",
                    "source_vertex_count",
                    L"selection_vertices");
            }
            std::vector<std::pair<int, int>>& edges = grouped_edges[source_submesh];
            if (!edges.empty()) {
                std::sort(edges.begin(), edges.end());
                std::vector<int> edge_values;
                edge_values.reserve(edges.size() * 2u);
                for (const auto& edge : edges) {
                    edge_values.push_back(edge.first);
                    edge_values.push_back(edge.second);
                }
                const std::string edge_descriptor = write_i32_temp_descriptor_json(edge_values, 2, L"selection_edges");
                if (!edge_descriptor.empty()) {
                    payload << ",\"source_edges_binary\":" << edge_descriptor;
                } else {
                    payload << ",\"source_edges\":[";
                    for (size_t index = 0; index < edges.size(); ++index) {
                        if (index) payload << ",";
                        payload << "[" << edges[index].first << "," << edges[index].second << "]";
                    }
                    payload << "]";
                }
            }
            std::vector<int>& faces = grouped_faces[source_submesh];
            std::sort(faces.begin(), faces.end());
            if (!faces.empty()) {
                write_i32_range_or_descriptor_json(
                    payload,
                    faces,
                    "source_face_indices",
                    "source_face_indices_binary",
                    "source_face_start",
                    "source_face_count",
                    L"selection_faces");
            }
            payload << "}";
        }
        payload << "]}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }
