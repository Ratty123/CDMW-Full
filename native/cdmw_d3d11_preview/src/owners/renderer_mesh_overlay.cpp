bool Renderer::mesh_edit_overlay_active_for_view(const PreviewRenderView& view) const {
        return mesh_edit_.enabled
            && !icon_capture_mode_
            && view.role != PreviewViewRole::Reference
            && width_ > 0
            && height_ > 0;
    }

bool Renderer::mesh_edit_source_allowed(int source_submesh_index) const {
        return source_submesh_index >= 0
            && (mesh_edit_.source_submesh_indices.empty()
                || mesh_edit_.source_submesh_indices.find(source_submesh_index) != mesh_edit_.source_submesh_indices.end());
    }

bool Renderer::mesh_edit_batch_editable_in_view(const PreviewBatch& batch, const PreviewRenderView& view) const {
        return mesh_edit_overlay_active_for_view(view)
            && batch_visible_in_view(batch, view.role)
            && batch.editor_editable
            && !batch_is_reference(batch)
            && batch.source_submesh_index >= 0
            && mesh_edit_source_allowed(batch.source_submesh_index)
            && !batch.cpu_positions.empty();
    }

bool Renderer::mesh_edit_preserve_materials_for_batch(const PreviewBatch& batch) {
        (void)batch;
        return false;
    }

std::pair<int, int> Renderer::mesh_edit_source_key(const PreviewBatch& batch, size_t vertex_index) const {
        const int source_submesh = vertex_index < batch.cpu_source_submeshes.size()
            ? batch.cpu_source_submeshes[vertex_index]
            : batch.source_submesh_index;
        const int source_vertex = vertex_index < batch.cpu_source_vertices.size()
            ? batch.cpu_source_vertices[vertex_index]
            : static_cast<int>(vertex_index);
        return std::pair<int, int>(source_submesh, source_vertex);
    }

void Renderer::rebuild_batch_source_vertex_lookup(PreviewBatch& batch) const {
        batch.cpu_source_vertex_lookup.clear();
        const size_t vertex_limit = std::min(
            batch.cpu_positions.size(),
            batch.cpu_vertices.size() / (kVertexStrideBytes / sizeof(float)));
        for (size_t vertex_index = 0; vertex_index < vertex_limit; ++vertex_index) {
            const std::pair<int, int> key = mesh_edit_source_key(batch, vertex_index);
            if (key.first >= 0 && key.second >= 0) {
                batch.cpu_source_vertex_lookup[key].push_back(vertex_index);
            }
        }
    }

void Renderer::rebuild_batch_source_face_vertex_lookup(PreviewBatch& batch) const {
        batch.cpu_source_face_vertex_lookup.clear();
        const size_t vertex_limit = std::min(batch.cpu_source_faces.size(), batch.cpu_source_vertices.size());
        for (size_t vertex_index = 0; vertex_index < vertex_limit; ++vertex_index) {
            const int source_face = batch.cpu_source_faces[vertex_index];
            const int source_vertex = batch.cpu_source_vertices[vertex_index];
            const int source_submesh = vertex_index < batch.cpu_source_submeshes.size()
                ? batch.cpu_source_submeshes[vertex_index]
                : batch.source_submesh_index;
            if (source_submesh >= 0 && source_face >= 0 && source_vertex >= 0) {
                batch.cpu_source_face_vertex_lookup[std::pair<int, int>(source_submesh, source_face)].insert(source_vertex);
            }
        }
    }

bool Renderer::mesh_edit_source_vertex_selected(const PreviewBatch& batch, size_t vertex_index) const {
        const std::pair<int, int> key = mesh_edit_source_key(batch, vertex_index);
        return key.first >= 0
            && key.second >= 0
            && mesh_edit_.selected_vertices.find(key) != mesh_edit_.selected_vertices.end();
    }

std::pair<int, int> Renderer::mesh_edit_source_face_key(const PreviewBatch& batch, size_t triangle_index, size_t base_vertex_index) const {
        int source_submesh = batch.source_submesh_index;
        int source_face = static_cast<int>(triangle_index);
        for (size_t corner = 0; corner < 3u; ++corner) {
            const size_t vertex_index = base_vertex_index + corner;
            const std::pair<int, int> source_key = mesh_edit_source_key(batch, vertex_index);
            if (source_submesh < 0 && source_key.first >= 0) {
                source_submesh = source_key.first;
            }
            if (vertex_index < batch.cpu_source_faces.size() && batch.cpu_source_faces[vertex_index] >= 0) {
                source_face = batch.cpu_source_faces[vertex_index];
                break;
            }
        }
        return std::pair<int, int>(source_submesh, source_face);
    }

bool Renderer::mesh_edit_source_face_selected(const PreviewBatch& batch, size_t triangle_index, size_t base_vertex_index) const {
        const std::pair<int, int> key = mesh_edit_source_face_key(batch, triangle_index, base_vertex_index);
        return key.first >= 0
            && key.second >= 0
            && mesh_edit_.selected_faces.find(key) != mesh_edit_.selected_faces.end();
    }

bool Renderer::mesh_edit_source_edge_selected(const std::pair<int, int>& left, const std::pair<int, int>& right) const {
        return left.first >= 0
            && right.first >= 0
            && left.first == right.first
            && left.second >= 0
            && right.second >= 0
            && left.second != right.second
            && mesh_edit_.selected_edges.find(mesh_edit_edge_key(left.first, left.second, right.second)) != mesh_edit_.selected_edges.end();
    }

bool Renderer::project_batch_position_for_view(
        const PreviewBatch& batch,
        const DirectX::XMFLOAT3& position,
        const PreviewRenderView& view,
        float& screen_x,
        float& screen_y,
        float* depth_z) const {
        const DirectX::XMMATRIX alignment_transform =
            view.role == PreviewViewRole::Reference ? DirectX::XMMatrixIdentity() : alignment_preview_transform_for_batch(batch);
        const DirectX::XMMATRIX camera_world = world_matrix_for_view_role(view.role);
        const DirectX::XMMATRIX view_projection = view_projection_matrix_for_viewport(view.viewport, distance_for_view_role(view.role));
        DirectX::XMVECTOR source = DirectX::XMLoadFloat3(&position);
        DirectX::XMVECTOR projected = DirectX::XMVector3TransformCoord(source, alignment_transform * camera_world * view_projection);
        DirectX::XMFLOAT3 clip{};
        DirectX::XMStoreFloat3(&clip, projected);
        if (!std::isfinite(clip.x) || !std::isfinite(clip.y) || !std::isfinite(clip.z)) return false;
        if (clip.z < 0.0f || clip.z > 1.0f) return false;
        screen_x = view.viewport.TopLeftX + (clip.x * 0.5f + 0.5f) * view.viewport.Width;
        screen_y = view.viewport.TopLeftY + (0.5f - clip.y * 0.5f) * view.viewport.Height;
        if (depth_z) *depth_z = clip.z;
        return std::isfinite(screen_x) && std::isfinite(screen_y);
    }

std::string Renderer::mesh_edit_screen_vertex_cache_key(const PreviewRenderView& view) const {
        std::ostringstream out;
        out << static_cast<int>(view.role)
            << "|" << view.viewport.TopLeftX << "," << view.viewport.TopLeftY << "," << view.viewport.Width << "," << view.viewport.Height
            << "|" << model_generation_
            << "|" << mesh_edit_cache_generation_
            << "|" << yaw_ << "," << pitch_ << "," << distance_ << "," << pan_x_ << "," << pan_y_ << "," << pan_z_
            << "|" << alignment_.translation_total.x << "," << alignment_.translation_total.y << "," << alignment_.translation_total.z
            << "|" << alignment_.rotation_total.x << "," << alignment_.rotation_total.y << "," << alignment_.rotation_total.z
            << "|" << alignment_.scale_total.x << "," << alignment_.scale_total.y << "," << alignment_.scale_total.z
            << "|" << batches_.size() << "|";
        for (int source_index : mesh_edit_.source_submesh_indices) out << source_index << ",";
        out << "|";
        for (int source_index : hidden_source_submeshes_) out << source_index << ",";
        return out.str();
    }

void Renderer::invalidate_mesh_edit_caches() const {
        ++mesh_edit_cache_generation_;
        mesh_edit_screen_vertex_cache_.valid = false;
        mesh_edit_screen_vertex_cache_.vertices.clear();
        mesh_edit_depth_mask_cache_.valid = false;
        mesh_edit_depth_mask_cache_.depths.clear();
    }

bool Renderer::mesh_edit_depth_filter_enabled() const {
        return lower_copy(mesh_edit_.selection_depth_mode) != "xray";
    }

const std::vector<MeshEditScreenVertex>& Renderer::mesh_edit_screen_vertices_for_view(const PreviewRenderView& view) const {
        const std::string key = mesh_edit_screen_vertex_cache_key(view);
        if (mesh_edit_screen_vertex_cache_.valid && mesh_edit_screen_vertex_cache_.key == key) {
            return mesh_edit_screen_vertex_cache_.vertices;
        }
        mesh_edit_screen_vertex_cache_.valid = true;
        mesh_edit_screen_vertex_cache_.key = key;
        mesh_edit_screen_vertex_cache_.vertices.clear();
        std::set<std::pair<int, int>> emitted;
        for (const PreviewBatch& batch : batches_) {
            if (!mesh_edit_batch_editable_in_view(batch, view)) continue;
            for (size_t vertex_index = 0; vertex_index < batch.cpu_positions.size(); ++vertex_index) {
                std::pair<int, int> key_pair = mesh_edit_source_key(batch, vertex_index);
                if (key_pair.first < 0 || key_pair.second < 0) continue;
                if (emitted.find(key_pair) != emitted.end()) continue;
                emitted.insert(key_pair);
                float screen_x = 0.0f;
                float screen_y = 0.0f;
                float depth_z = 1.0f;
                if (!project_batch_position_for_view(batch, batch.cpu_positions[vertex_index], view, screen_x, screen_y, &depth_z)) continue;
                MeshEditScreenVertex screen_vertex;
                screen_vertex.batch_index = batch.index;
                screen_vertex.source_submesh_index = key_pair.first;
                screen_vertex.source_vertex_index = key_pair.second;
                screen_vertex.position = transformed_batch_position(batch, batch.cpu_positions[vertex_index]);
                screen_vertex.screen_x = screen_x;
                screen_vertex.screen_y = screen_y;
                screen_vertex.depth_z = depth_z;
                mesh_edit_screen_vertex_cache_.vertices.push_back(screen_vertex);
            }
        }
        return mesh_edit_screen_vertex_cache_.vertices;
    }

float Renderer::edge_function(float ax, float ay, float bx, float by, float cx, float cy) {
        return (cx - ax) * (by - ay) - (cy - ay) * (bx - ax);
    }

const MeshEditDepthMaskCache& Renderer::mesh_edit_depth_mask_for_view(const PreviewRenderView& view) const {
        const std::string key = mesh_edit_screen_vertex_cache_key(view) + "|depth";
        if (mesh_edit_depth_mask_cache_.valid && mesh_edit_depth_mask_cache_.key == key) {
            return mesh_edit_depth_mask_cache_;
        }
        constexpr float kMaxDepthMaskDimension = 1024.0f;
        const float viewport_width = std::max(1.0f, view.viewport.Width);
        const float viewport_height = std::max(1.0f, view.viewport.Height);
        const float scale = std::min(1.0f, kMaxDepthMaskDimension / std::max(viewport_width, viewport_height));
        const int mask_width = std::max(1, static_cast<int>(std::ceil(viewport_width * scale)));
        const int mask_height = std::max(1, static_cast<int>(std::ceil(viewport_height * scale)));
        mesh_edit_depth_mask_cache_.valid = true;
        mesh_edit_depth_mask_cache_.key = key;
        mesh_edit_depth_mask_cache_.width = mask_width;
        mesh_edit_depth_mask_cache_.height = mask_height;
        mesh_edit_depth_mask_cache_.viewport_x = view.viewport.TopLeftX;
        mesh_edit_depth_mask_cache_.viewport_y = view.viewport.TopLeftY;
        mesh_edit_depth_mask_cache_.scale_x = static_cast<float>(mask_width) / viewport_width;
        mesh_edit_depth_mask_cache_.scale_y = static_cast<float>(mask_height) / viewport_height;
        mesh_edit_depth_mask_cache_.depths.assign(
            static_cast<size_t>(mask_width) * static_cast<size_t>(mask_height),
            std::numeric_limits<float>::infinity());

        auto rasterize_triangle = [&](const DirectX::XMFLOAT3& p0, const DirectX::XMFLOAT3& p1, const DirectX::XMFLOAT3& p2) {
            const float area = edge_function(p0.x, p0.y, p1.x, p1.y, p2.x, p2.y);
            if (std::abs(area) <= 1.0e-6f) return;
            int min_x = static_cast<int>(std::floor(std::min({p0.x, p1.x, p2.x})));
            int max_x = static_cast<int>(std::ceil(std::max({p0.x, p1.x, p2.x})));
            int min_y = static_cast<int>(std::floor(std::min({p0.y, p1.y, p2.y})));
            int max_y = static_cast<int>(std::ceil(std::max({p0.y, p1.y, p2.y})));
            min_x = std::max(0, std::min(mask_width - 1, min_x));
            max_x = std::max(0, std::min(mask_width - 1, max_x));
            min_y = std::max(0, std::min(mask_height - 1, min_y));
            max_y = std::max(0, std::min(mask_height - 1, max_y));
            if (min_x > max_x || min_y > max_y) return;
            for (int py = min_y; py <= max_y; ++py) {
                const float y = static_cast<float>(py) + 0.5f;
                for (int px = min_x; px <= max_x; ++px) {
                    const float x = static_cast<float>(px) + 0.5f;
                    const float w0 = edge_function(p1.x, p1.y, p2.x, p2.y, x, y) / area;
                    const float w1 = edge_function(p2.x, p2.y, p0.x, p0.y, x, y) / area;
                    const float w2 = edge_function(p0.x, p0.y, p1.x, p1.y, x, y) / area;
                    if (w0 < -0.001f || w1 < -0.001f || w2 < -0.001f) continue;
                    const float depth = w0 * p0.z + w1 * p1.z + w2 * p2.z;
                    if (!std::isfinite(depth)) continue;
                    const size_t offset = static_cast<size_t>(py) * static_cast<size_t>(mask_width) + static_cast<size_t>(px);
                    mesh_edit_depth_mask_cache_.depths[offset] = std::min(mesh_edit_depth_mask_cache_.depths[offset], depth);
                }
            }
        };

        for (const PreviewBatch& batch : batches_) {
            if (!mesh_edit_batch_editable_in_view(batch, view)) continue;
            const size_t triangle_count = batch.cpu_positions.size() / 3u;
            for (size_t triangle_index = 0; triangle_index < triangle_count; ++triangle_index) {
                const size_t base = triangle_index * 3u;
                DirectX::XMFLOAT3 projected[3]{};
                bool valid = true;
                for (size_t corner = 0; corner < 3u; ++corner) {
                    float screen_x = 0.0f;
                    float screen_y = 0.0f;
                    float depth_z = 1.0f;
                    if (!project_batch_position_for_view(batch, batch.cpu_positions[base + corner], view, screen_x, screen_y, &depth_z)) {
                        valid = false;
                        break;
                    }
                    projected[corner] = DirectX::XMFLOAT3(
                        (screen_x - view.viewport.TopLeftX) * mesh_edit_depth_mask_cache_.scale_x,
                        (screen_y - view.viewport.TopLeftY) * mesh_edit_depth_mask_cache_.scale_y,
                        depth_z);
                }
                if (valid) rasterize_triangle(projected[0], projected[1], projected[2]);
            }
        }
        return mesh_edit_depth_mask_cache_;
    }

bool Renderer::mesh_edit_screen_vertex_visible_in_depth_mask(
        const MeshEditScreenVertex& screen_vertex,
        const MeshEditDepthMaskCache& depth_mask
    ) const {
        if (!mesh_edit_depth_filter_enabled()) return true;
        if (!depth_mask.valid || depth_mask.width <= 0 || depth_mask.height <= 0 || depth_mask.depths.empty()) return true;
        const int x = static_cast<int>(std::floor((screen_vertex.screen_x - depth_mask.viewport_x) * depth_mask.scale_x));
        const int y = static_cast<int>(std::floor((screen_vertex.screen_y - depth_mask.viewport_y) * depth_mask.scale_y));
        if (x < 0 || y < 0 || x >= depth_mask.width || y >= depth_mask.height) return false;
        const size_t offset = static_cast<size_t>(y) * static_cast<size_t>(depth_mask.width) + static_cast<size_t>(x);
        if (offset >= depth_mask.depths.size()) return true;
        const float front_depth = depth_mask.depths[offset];
        if (!std::isfinite(front_depth)) return true;
        return screen_vertex.depth_z <= front_depth + 0.0035f;
    }

void Renderer::draw_mesh_edit_vertex_dots_instanced(
        const PreviewRenderView& view,
        const std::vector<MeshEditScreenVertex>& screen_vertices,
        bool no_depth) {
        if (!mesh_edit_.show_vertices || screen_vertices.empty() || !vertex_dot_shader_ || !vertex_dot_pixel_shader_ || !vertex_dot_input_layout_) return;
        std::vector<VertexDotInstance> instances;
        instances.reserve(screen_vertices.size() * 3u);
        auto add_instance = [&](float screen_x, float screen_y, float depth_z, float radius, float r, float g, float b, float a = 1.0f) {
            const float local_x = screen_x - view.viewport.TopLeftX;
            const float local_y = screen_y - view.viewport.TopLeftY;
            VertexDotInstance instance;
            instance.clip_x = (local_x / std::max(1.0f, view.viewport.Width)) * 2.0f - 1.0f;
            instance.clip_y = 1.0f - (local_y / std::max(1.0f, view.viewport.Height)) * 2.0f;
            instance.clip_z = std::clamp(depth_z, 0.0f, 1.0f);
            instance.radius_x = (radius / std::max(1.0f, view.viewport.Width)) * 2.0f;
            instance.radius_y = (radius / std::max(1.0f, view.viewport.Height)) * 2.0f;
            instance.r = r;
            instance.g = g;
            instance.b = b;
            instance.a = a;
            instances.push_back(instance);
        };
        for (const MeshEditScreenVertex& screen_vertex : screen_vertices) {
            std::pair<int, int> key(screen_vertex.source_submesh_index, screen_vertex.source_vertex_index);
            const bool selected = mesh_edit_.selected_vertices.find(key) != mesh_edit_.selected_vertices.end();
            if (selected) {
                add_instance(screen_vertex.screen_x, screen_vertex.screen_y, screen_vertex.depth_z, 6.0f, 0.0f, 0.0f, 0.0f);
                add_instance(screen_vertex.screen_x, screen_vertex.screen_y, screen_vertex.depth_z, 4.5f, 1.0f, 0.52f, 0.12f);
                add_instance(screen_vertex.screen_x, screen_vertex.screen_y, screen_vertex.depth_z, 2.0f, 1.0f, 0.92f, 0.28f);
            } else {
                add_instance(screen_vertex.screen_x, screen_vertex.screen_y, screen_vertex.depth_z, 4.2f, 0.0f, 0.0f, 0.0f);
                add_instance(screen_vertex.screen_x, screen_vertex.screen_y, screen_vertex.depth_z, 2.8f, 0.18f, 0.82f, 1.0f);
            }
        }
        if (instances.empty()) return;
        D3D11_BUFFER_DESC desc{};
        desc.ByteWidth = static_cast<UINT>(instances.size() * sizeof(VertexDotInstance));
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_VERTEX_BUFFER;
        D3D11_SUBRESOURCE_DATA init{};
        init.pSysMem = instances.data();
        ComPtr<ID3D11Buffer> buffer;
        if (FAILED(device_->CreateBuffer(&desc, &init, buffer.GetAddressOf()))) return;
        UINT stride = sizeof(VertexDotInstance);
        UINT offset = 0;
        context_->IASetInputLayout(vertex_dot_input_layout_.Get());
        context_->IASetVertexBuffers(0, 1, buffer.GetAddressOf(), &stride, &offset);
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->VSSetShader(vertex_dot_shader_.Get(), nullptr, 0);
        context_->PSSetShader(vertex_dot_pixel_shader_.Get(), nullptr, 0);
        context_->OMSetDepthStencilState(no_depth && overlay_depth_state_ ? overlay_depth_state_.Get() : depth_state_.Get(), 0);
        ID3D11ShaderResourceView* clear_srvs[kTotalSrvCount] = {};
        context_->PSSetShaderResources(0, kTotalSrvCount, clear_srvs);
        context_->DrawInstanced(6u, static_cast<UINT>(instances.size()), 0u, 0u);
        context_->IASetInputLayout(input_layout_.Get());
        context_->VSSetShader(vertex_shader_.Get(), nullptr, 0);
        context_->PSSetShader(pixel_shader_.Get(), nullptr, 0);
    }

void Renderer::append_mesh_edit_topology_overlay(
        const PreviewRenderView& view,
        const MeshEditDepthMaskCache* depth_mask,
        std::vector<float>& vertices) {
        auto append_screen_vertex = [&](float x, float y, float depth_z, float r, float g, float b) {
            const float local_x = x - view.viewport.TopLeftX;
            const float local_y = y - view.viewport.TopLeftY;
            const float clip_x = (local_x / std::max(1.0f, view.viewport.Width)) * 2.0f - 1.0f;
            const float clip_y = 1.0f - (local_y / std::max(1.0f, view.viewport.Height)) * 2.0f;
            append_line_vertex(vertices, clip_x, clip_y, std::clamp(depth_z, 0.0f, 1.0f), r, g, b);
        };
        auto add_triangle_depth = [&](ScreenPoint a, float az, ScreenPoint b, float bz, ScreenPoint c, float cz, float r, float g, float blue) {
            append_screen_vertex(a.x, a.y, az, r, g, blue);
            append_screen_vertex(b.x, b.y, bz, r, g, blue);
            append_screen_vertex(c.x, c.y, cz, r, g, blue);
        };
        auto add_thick_line_depth = [&](ScreenPoint start, float start_z, ScreenPoint end, float end_z, float width_pixels, float r, float g, float blue) {
            const float dx = end.x - start.x;
            const float dy = end.y - start.y;
            const float length = std::max(1.0f, std::hypot(dx, dy));
            const float px = -dy / length * width_pixels * 0.5f;
            const float py = dx / length * width_pixels * 0.5f;
            ScreenPoint a{start.x + px, start.y + py};
            ScreenPoint b{end.x + px, end.y + py};
            ScreenPoint c{end.x - px, end.y - py};
            ScreenPoint d{start.x - px, start.y - py};
            add_triangle_depth(a, start_z, b, end_z, c, end_z, r, g, blue);
            add_triangle_depth(a, start_z, c, end_z, d, start_z, r, g, blue);
        };
        constexpr size_t kMaxMeshEditOverlayTriangles = 70000u;
        size_t overlay_triangle_count = 0;
        for (const PreviewBatch& batch : batches_) {
            if (!mesh_edit_batch_editable_in_view(batch, view)) continue;
            const size_t triangle_count = batch.cpu_positions.size() / 3u;
            const bool dense_topology_overlay = mesh_edit_preserve_materials_for_batch(batch);
            const size_t triangle_stride = std::max<size_t>(1u, triangle_count / std::max<size_t>(1u, kMaxMeshEditOverlayTriangles));
            for (size_t triangle_index = 0; triangle_index < triangle_count; triangle_index += triangle_stride) {
                if (overlay_triangle_count++ >= kMaxMeshEditOverlayTriangles) break;
                const size_t base = triangle_index * 3u;
                ScreenPoint p[3]{};
                float depth_z[3]{};
                bool projected = true;
                for (size_t corner = 0; corner < 3u; ++corner) {
                    float screen_x = 0.0f;
                    float screen_y = 0.0f;
                    if (!project_batch_position_for_view(batch, batch.cpu_positions[base + corner], view, screen_x, screen_y, &depth_z[corner])) {
                        projected = false;
                        break;
                    }
                    p[corner] = ScreenPoint{screen_x, screen_y};
                }
                if (!projected) continue;
                if (depth_mask) {
                    bool triangle_visible = false;
                    for (size_t corner = 0; corner < 3u; ++corner) {
                        MeshEditScreenVertex probe;
                        probe.screen_x = p[corner].x;
                        probe.screen_y = p[corner].y;
                        probe.depth_z = depth_z[corner];
                        if (mesh_edit_screen_vertex_visible_in_depth_mask(probe, *depth_mask)) {
                            triangle_visible = true;
                            break;
                        }
                    }
                    if (!triangle_visible) continue;
                }
                const std::pair<int, int> key0 = mesh_edit_source_key(batch, base);
                const std::pair<int, int> key1 = mesh_edit_source_key(batch, base + 1u);
                const std::pair<int, int> key2 = mesh_edit_source_key(batch, base + 2u);
                const bool selected_face = mesh_edit_source_face_selected(batch, triangle_index, base);
                const bool selected_edge_01 = mesh_edit_source_edge_selected(key0, key1);
                const bool selected_edge_12 = mesh_edit_source_edge_selected(key1, key2);
                const bool selected_edge_20 = mesh_edit_source_edge_selected(key2, key0);
                const bool selected_edge = selected_edge_01 || selected_edge_12 || selected_edge_20;
                const bool exact_selection = !mesh_edit_.selected_edges.empty() || !mesh_edit_.selected_faces.empty();
                const bool selected_vertex_triangle = !exact_selection
                    && (
                        mesh_edit_source_vertex_selected(batch, base)
                        || mesh_edit_source_vertex_selected(batch, base + 1u)
                        || mesh_edit_source_vertex_selected(batch, base + 2u));
                const bool selected_triangle = selected_face || selected_edge || selected_vertex_triangle;
                if (selected_face) {
                    add_triangle_depth(p[0], depth_z[0], p[1], depth_z[1], p[2], depth_z[2], 0.90f, 0.40f, 0.08f);
                    add_thick_line_depth(p[0], depth_z[0], p[1], depth_z[1], 4.4f, 0.0f, 0.0f, 0.0f);
                    add_thick_line_depth(p[1], depth_z[1], p[2], depth_z[2], 4.4f, 0.0f, 0.0f, 0.0f);
                    add_thick_line_depth(p[2], depth_z[2], p[0], depth_z[0], 4.4f, 0.0f, 0.0f, 0.0f);
                    add_thick_line_depth(p[0], depth_z[0], p[1], depth_z[1], 2.7f, 1.0f, 0.70f, 0.14f);
                    add_thick_line_depth(p[1], depth_z[1], p[2], depth_z[2], 2.7f, 1.0f, 0.70f, 0.14f);
                    add_thick_line_depth(p[2], depth_z[2], p[0], depth_z[0], 2.7f, 1.0f, 0.70f, 0.14f);
                } else if (selected_edge) {
                    if (selected_edge_01) add_thick_line_depth(p[0], depth_z[0], p[1], depth_z[1], 5.2f, 0.0f, 0.0f, 0.0f);
                    if (selected_edge_12) add_thick_line_depth(p[1], depth_z[1], p[2], depth_z[2], 5.2f, 0.0f, 0.0f, 0.0f);
                    if (selected_edge_20) add_thick_line_depth(p[2], depth_z[2], p[0], depth_z[0], 5.2f, 0.0f, 0.0f, 0.0f);
                    if (selected_edge_01) add_thick_line_depth(p[0], depth_z[0], p[1], depth_z[1], 3.0f, 1.0f, 0.82f, 0.18f);
                    if (selected_edge_12) add_thick_line_depth(p[1], depth_z[1], p[2], depth_z[2], 3.0f, 1.0f, 0.82f, 0.18f);
                    if (selected_edge_20) add_thick_line_depth(p[2], depth_z[2], p[0], depth_z[0], 3.0f, 1.0f, 0.82f, 0.18f);
                } else if (selected_triangle) {
                    add_thick_line_depth(p[0], depth_z[0], p[1], depth_z[1], 4.0f, 0.0f, 0.0f, 0.0f);
                    add_thick_line_depth(p[1], depth_z[1], p[2], depth_z[2], 4.0f, 0.0f, 0.0f, 0.0f);
                    add_thick_line_depth(p[2], depth_z[2], p[0], depth_z[0], 4.0f, 0.0f, 0.0f, 0.0f);
                    add_thick_line_depth(p[0], depth_z[0], p[1], depth_z[1], 2.4f, 1.0f, 0.48f, 0.12f);
                    add_thick_line_depth(p[1], depth_z[1], p[2], depth_z[2], 2.4f, 1.0f, 0.48f, 0.12f);
                    add_thick_line_depth(p[2], depth_z[2], p[0], depth_z[0], 2.4f, 1.0f, 0.48f, 0.12f);
                } else if (!dense_topology_overlay) {
                    add_thick_line_depth(p[0], depth_z[0], p[1], depth_z[1], 1.35f, 0.015f, 0.018f, 0.020f);
                    add_thick_line_depth(p[1], depth_z[1], p[2], depth_z[2], 1.35f, 0.015f, 0.018f, 0.020f);
                    add_thick_line_depth(p[2], depth_z[2], p[0], depth_z[0], 1.35f, 0.015f, 0.018f, 0.020f);
                }
            }
        }
}

void Renderer::draw_mesh_edit_overlay(const PreviewRenderView& view) {
        if (!mesh_edit_overlay_active_for_view(view)) return;

        std::vector<float> vertices;
        std::vector<float> screen_overlay_vertices;
        vertices.reserve(23u * 4096u);
        screen_overlay_vertices.reserve(23u * 512u);
        DirectX::XMMATRIX identity = DirectX::XMMatrixIdentity();
        const std::vector<MeshEditScreenVertex>& screen_vertices = mesh_edit_screen_vertices_for_view(view);
        const bool xray_mode = !mesh_edit_depth_filter_enabled();
        const MeshEditDepthMaskCache* depth_mask = xray_mode ? nullptr : &mesh_edit_depth_mask_for_view(view);
        std::vector<MeshEditScreenVertex> visible_screen_vertices;
        const std::vector<MeshEditScreenVertex>* dot_vertices = &screen_vertices;
        if (depth_mask) {
            visible_screen_vertices.reserve(screen_vertices.size());
            for (const MeshEditScreenVertex& screen_vertex : screen_vertices) {
                if (mesh_edit_screen_vertex_visible_in_depth_mask(screen_vertex, *depth_mask)) {
                    visible_screen_vertices.push_back(screen_vertex);
                }
            }
            dot_vertices = &visible_screen_vertices;
        }

        std::vector<float>* overlay_vertices = &vertices;
        auto append_screen_vertex = [&](float x, float y, float depth_z, float r, float g, float b) {
            const float local_x = x - view.viewport.TopLeftX;
            const float local_y = y - view.viewport.TopLeftY;
            const float clip_x = (local_x / std::max(1.0f, view.viewport.Width)) * 2.0f - 1.0f;
            const float clip_y = 1.0f - (local_y / std::max(1.0f, view.viewport.Height)) * 2.0f;
            append_line_vertex(*overlay_vertices, clip_x, clip_y, std::clamp(depth_z, 0.0f, 1.0f), r, g, b);
        };
        auto add_triangle = [&](ScreenPoint a, ScreenPoint b, ScreenPoint c, float r, float g, float blue) {
            append_screen_vertex(a.x, a.y, 0.0f, r, g, blue);
            append_screen_vertex(b.x, b.y, 0.0f, r, g, blue);
            append_screen_vertex(c.x, c.y, 0.0f, r, g, blue);
        };
        auto add_thick_line = [&](ScreenPoint start, ScreenPoint end, float width_pixels, float r, float g, float blue) {
            const float dx = end.x - start.x;
            const float dy = end.y - start.y;
            const float length = std::max(1.0f, std::hypot(dx, dy));
            const float px = -dy / length * width_pixels * 0.5f;
            const float py = dx / length * width_pixels * 0.5f;
            ScreenPoint a{start.x + px, start.y + py};
            ScreenPoint b{end.x + px, end.y + py};
            ScreenPoint c{end.x - px, end.y - py};
            ScreenPoint d{start.x - px, start.y - py};
            add_triangle(a, b, c, r, g, blue);
            add_triangle(a, c, d, r, g, blue);
        };
        auto add_disc = [&](ScreenPoint center, float radius, float r, float g, float blue) {
            constexpr int kSegments = 14;
            constexpr float kPi = 3.14159265358979323846f;
            for (int index = 0; index < kSegments; ++index) {
                const float a0 = (2.0f * kPi * static_cast<float>(index)) / static_cast<float>(kSegments);
                const float a1 = (2.0f * kPi * static_cast<float>(index + 1)) / static_cast<float>(kSegments);
                add_triangle(
                    center,
                    ScreenPoint{center.x + std::cos(a0) * radius, center.y + std::sin(a0) * radius},
                    ScreenPoint{center.x + std::cos(a1) * radius, center.y + std::sin(a1) * radius},
                    r, g, blue);
            }
        };
        auto add_ring = [&](ScreenPoint center, float radius, float width_pixels, float r, float g, float blue) {
            constexpr int kSegments = 80;
            constexpr float kPi = 3.14159265358979323846f;
            const float inner = std::max(1.0f, radius - width_pixels * 0.5f);
            const float outer = radius + width_pixels * 0.5f;
            for (int index = 0; index < kSegments; ++index) {
                const float a0 = (2.0f * kPi * static_cast<float>(index)) / static_cast<float>(kSegments);
                const float a1 = (2.0f * kPi * static_cast<float>(index + 1)) / static_cast<float>(kSegments);
                ScreenPoint o0{center.x + std::cos(a0) * outer, center.y + std::sin(a0) * outer};
                ScreenPoint o1{center.x + std::cos(a1) * outer, center.y + std::sin(a1) * outer};
                ScreenPoint i0{center.x + std::cos(a0) * inner, center.y + std::sin(a0) * inner};
                ScreenPoint i1{center.x + std::cos(a1) * inner, center.y + std::sin(a1) * inner};
                add_triangle(o0, o1, i1, r, g, blue);
                add_triangle(o0, i1, i0, r, g, blue);
            }
        };

        const bool cursor_in_view =
            static_cast<float>(cursor_x_) >= view.viewport.TopLeftX
            && static_cast<float>(cursor_x_) <= view.viewport.TopLeftX + view.viewport.Width
            && static_cast<float>(cursor_y_) >= view.viewport.TopLeftY
            && static_cast<float>(cursor_y_) <= view.viewport.TopLeftY + view.viewport.Height;
        overlay_vertices = &screen_overlay_vertices;
        if (cursor_in_view) {
            const bool remove_tool = mesh_edit_.tool == "remove";
            add_ring(ScreenPoint{static_cast<float>(cursor_x_), static_cast<float>(cursor_y_)}, mesh_edit_.radius_pixels + 2.0f, 3.8f, 0.0f, 0.0f, 0.0f);
            add_ring(
                ScreenPoint{static_cast<float>(cursor_x_), static_cast<float>(cursor_y_)},
                mesh_edit_.radius_pixels,
                2.2f,
                remove_tool ? 1.0f : 0.32f,
                remove_tool ? 0.28f : 0.86f,
                remove_tool ? 0.10f : 1.0f);
        }

        if (mesh_edit_.selection_drag_active && (mesh_edit_.selection_mode == "rectangle" || mesh_edit_.selection_mode == "lasso")) {
            if (mesh_edit_.selection_mode == "rectangle") {
                ScreenPoint a{static_cast<float>(mesh_edit_.start_x), static_cast<float>(mesh_edit_.start_y)};
                ScreenPoint c{static_cast<float>(mesh_edit_.last_x), static_cast<float>(mesh_edit_.last_y)};
                ScreenPoint b{c.x, a.y};
                ScreenPoint d{a.x, c.y};
                add_thick_line(a, b, 2.0f, 1.0f, 0.64f, 0.18f);
                add_thick_line(b, c, 2.0f, 1.0f, 0.64f, 0.18f);
                add_thick_line(c, d, 2.0f, 1.0f, 0.64f, 0.18f);
                add_thick_line(d, a, 2.0f, 1.0f, 0.64f, 0.18f);
            } else if (mesh_edit_.selection_lasso_points.size() > 1) {
                for (size_t index = 1; index < mesh_edit_.selection_lasso_points.size(); ++index) {
                    const DirectX::XMFLOAT2& prev = mesh_edit_.selection_lasso_points[index - 1u];
                    const DirectX::XMFLOAT2& next = mesh_edit_.selection_lasso_points[index];
                    add_thick_line(ScreenPoint{prev.x, prev.y}, ScreenPoint{next.x, next.y}, 2.0f, 1.0f, 0.64f, 0.18f);
                }
            }
        }

        overlay_vertices = &vertices;
        append_mesh_edit_topology_overlay(view, depth_mask, vertices);
        draw_colored_triangles(vertices, identity, xray_mode);
        draw_colored_triangles(screen_overlay_vertices, identity, true);
        draw_mesh_edit_vertex_dots_instanced(view, *dot_vertices, xray_mode);
    }

void Renderer::draw_highlight_bounds_overlay(const PreviewRenderView& view) {
        if (icon_capture_mode_ || view.viewport.Width <= 4.0f || view.viewport.Height <= 4.0f) return;

        std::vector<float> vertices;
        vertices.reserve(batches_.size() * 48u);
        const DirectX::XMMATRIX identity = DirectX::XMMatrixIdentity();

        auto append_screen_vertex = [&](float x, float y, float r, float g, float b) {
            const float local_x = x - view.viewport.TopLeftX;
            const float local_y = y - view.viewport.TopLeftY;
            const float clip_x = (local_x / std::max(1.0f, view.viewport.Width)) * 2.0f - 1.0f;
            const float clip_y = 1.0f - (local_y / std::max(1.0f, view.viewport.Height)) * 2.0f;
            append_line_vertex(vertices, clip_x, clip_y, 0.0f, r, g, b);
        };
        auto add_triangle = [&](ScreenPoint a, ScreenPoint b, ScreenPoint c, float r, float g, float blue) {
            append_screen_vertex(a.x, a.y, r, g, blue);
            append_screen_vertex(b.x, b.y, r, g, blue);
            append_screen_vertex(c.x, c.y, r, g, blue);
        };
        auto add_thick_line = [&](ScreenPoint start, ScreenPoint end, float width_pixels, float r, float g, float blue) {
            const float dx = end.x - start.x;
            const float dy = end.y - start.y;
            const float length = std::max(1.0f, std::hypot(dx, dy));
            const float px = -dy / length * width_pixels * 0.5f;
            const float py = dx / length * width_pixels * 0.5f;
            ScreenPoint a{start.x + px, start.y + py};
            ScreenPoint b{end.x + px, end.y + py};
            ScreenPoint c{end.x - px, end.y - py};
            ScreenPoint d{start.x - px, start.y - py};
            add_triangle(a, b, c, r, g, blue);
            add_triangle(a, c, d, r, g, blue);
        };
        auto add_rect = [&](float left, float top, float right, float bottom, float width_pixels, float r, float g, float blue) {
            add_thick_line(ScreenPoint{left, top}, ScreenPoint{right, top}, width_pixels, r, g, blue);
            add_thick_line(ScreenPoint{right, top}, ScreenPoint{right, bottom}, width_pixels, r, g, blue);
            add_thick_line(ScreenPoint{right, bottom}, ScreenPoint{left, bottom}, width_pixels, r, g, blue);
            add_thick_line(ScreenPoint{left, bottom}, ScreenPoint{left, top}, width_pixels, r, g, blue);
        };

        const float viewport_left = view.viewport.TopLeftX;
        const float viewport_top = view.viewport.TopLeftY;
        const float viewport_right = view.viewport.TopLeftX + view.viewport.Width;
        const float viewport_bottom = view.viewport.TopLeftY + view.viewport.Height;
        for (const PreviewBatch& batch : batches_) {
            if (batch.highlight_strength <= 0.0f || !batch_visible_in_view(batch, view.role)) continue;
            bool projected = false;
            float min_x = 0.0f;
            float min_y = 0.0f;
            float max_x = 0.0f;
            float max_y = 0.0f;
            for (const DirectX::XMFLOAT3& position : batch.cpu_positions) {
                float screen_x = 0.0f;
                float screen_y = 0.0f;
                if (!project_batch_position_for_view(batch, position, view, screen_x, screen_y, nullptr)) continue;
                if (!projected) {
                    min_x = max_x = screen_x;
                    min_y = max_y = screen_y;
                    projected = true;
                } else {
                    min_x = std::min(min_x, screen_x);
                    max_x = std::max(max_x, screen_x);
                    min_y = std::min(min_y, screen_y);
                    max_y = std::max(max_y, screen_y);
                }
            }
            if (!projected) continue;

            float left = min_x - 7.0f;
            float top = min_y - 7.0f;
            float right = max_x + 7.0f;
            float bottom = max_y + 7.0f;
            const float center_x = (left + right) * 0.5f;
            const float center_y = (top + bottom) * 0.5f;
            if (right - left < 22.0f) {
                left = center_x - 11.0f;
                right = center_x + 11.0f;
            }
            if (bottom - top < 22.0f) {
                top = center_y - 11.0f;
                bottom = center_y + 11.0f;
            }
            left = std::clamp(left, viewport_left + 2.0f, viewport_right - 2.0f);
            right = std::clamp(right, viewport_left + 2.0f, viewport_right - 2.0f);
            top = std::clamp(top, viewport_top + 2.0f, viewport_bottom - 2.0f);
            bottom = std::clamp(bottom, viewport_top + 2.0f, viewport_bottom - 2.0f);
            if (right - left < 2.0f || bottom - top < 2.0f) continue;

            const bool reference = batch_is_reference(batch);
            add_rect(left, top, right, bottom, 6.0f, 0.0f, 0.0f, 0.0f);
            add_rect(
                left,
                top,
                right,
                bottom,
                3.0f,
                reference ? 1.0f : 0.0f,
                reference ? 0.78f : 0.88f,
                reference ? 0.10f : 1.0f);
        }

        draw_colored_triangles(vertices, identity, true);
    }
