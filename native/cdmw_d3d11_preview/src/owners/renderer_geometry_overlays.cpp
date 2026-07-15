DirectX::XMFLOAT3 Renderer::transformed_batch_position(const PreviewBatch& batch, const DirectX::XMFLOAT3& position) const {
        DirectX::XMVECTOR source = DirectX::XMLoadFloat3(&position);
        DirectX::XMVECTOR transformed = DirectX::XMVector3TransformCoord(source, alignment_preview_transform_for_batch(batch));
        DirectX::XMFLOAT3 output{};
        DirectX::XMStoreFloat3(&output, transformed);
        return output;
    }

void Renderer::append_line_vertex(
        std::vector<float>& vertices,
        float x,
        float y,
        float z,
        float r,
        float g,
        float b
    ) {
        vertices.insert(
            vertices.end(),
            {
                x, y, z,
                0.0f, 1.0f, 0.0f,
                r, g, b,
                0.0f, 0.0f,
                1.0f, 0.0f, 0.0f,
                0.0f, 0.0f, 1.0f,
                0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f
            });
    }

void Renderer::draw_colored_lines(const std::vector<float>& vertices, const DirectX::XMMATRIX& mvp, bool no_depth) {
        if (vertices.empty() || vertices.size() % 23u != 0u) return;
        D3D11_BUFFER_DESC desc{};
        desc.ByteWidth = static_cast<UINT>(vertices.size() * sizeof(float));
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_VERTEX_BUFFER;
        D3D11_SUBRESOURCE_DATA init{};
        init.pSysMem = vertices.data();
        ComPtr<ID3D11Buffer> buffer;
        if (FAILED(device_->CreateBuffer(&desc, &init, buffer.GetAddressOf()))) return;
        UINT stride = kVertexStrideBytes;
        UINT offset = 0;
        context_->IASetInputLayout(input_layout_.Get());
        context_->IASetVertexBuffers(0, 1, buffer.GetAddressOf(), &stride, &offset);
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_LINELIST);
        context_->VSSetShader(vertex_shader_.Get(), nullptr, 0);
        if (overlay_pixel_shader_) {
            context_->PSSetShader(overlay_pixel_shader_.Get(), nullptr, 0);
        }
        context_->OMSetDepthStencilState(no_depth && overlay_depth_state_ ? overlay_depth_state_.Get() : depth_state_.Get(), 0);
        ConstantBuffer constants{};
        DirectX::XMStoreFloat4x4(&constants.mvp, mvp);
        DirectX::XMStoreFloat4x4(&constants.normal_world, DirectX::XMMatrixIdentity());
        constants.light_dir = DirectX::XMFLOAT4(-0.35f, 0.45f, -0.82f, 0.0f);
        constants.base_color_flip = DirectX::XMFLOAT4(0.0f, 0.0f, 0.0f, 0.0f);
        constants.render_tuning = DirectX::XMFLOAT4(0.85f, 0.15f, 0.0f, 0.0f);
        constants.render_tuning2 = DirectX::XMFLOAT4(8.0f, 16.0f, 0.0f, 0.0f);
        constants.editor_tint = DirectX::XMFLOAT4(0.0f, 0.0f, 0.0f, 0.0f);
        context_->UpdateSubresource(constants_.Get(), 0, nullptr, &constants, 0, 0);
        context_->VSSetConstantBuffers(0, 1, constants_.GetAddressOf());
        context_->PSSetConstantBuffers(0, 1, constants_.GetAddressOf());
        ID3D11ShaderResourceView* clear_srvs[kTotalSrvCount] = {};
        context_->PSSetShaderResources(0, kTotalSrvCount, clear_srvs);
        context_->Draw(static_cast<UINT>(vertices.size() / 23u), 0);
        context_->PSSetShader(pixel_shader_.Get(), nullptr, 0);
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    }

void Renderer::draw_colored_triangles(const std::vector<float>& vertices, const DirectX::XMMATRIX& mvp, bool no_depth) {
        if (vertices.empty() || vertices.size() % 23u != 0u) return;
        D3D11_BUFFER_DESC desc{};
        desc.ByteWidth = static_cast<UINT>(vertices.size() * sizeof(float));
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_VERTEX_BUFFER;
        D3D11_SUBRESOURCE_DATA init{};
        init.pSysMem = vertices.data();
        ComPtr<ID3D11Buffer> buffer;
        if (FAILED(device_->CreateBuffer(&desc, &init, buffer.GetAddressOf()))) return;
        UINT stride = kVertexStrideBytes;
        UINT offset = 0;
        context_->IASetInputLayout(input_layout_.Get());
        context_->IASetVertexBuffers(0, 1, buffer.GetAddressOf(), &stride, &offset);
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->VSSetShader(vertex_shader_.Get(), nullptr, 0);
        if (overlay_pixel_shader_) {
            context_->PSSetShader(overlay_pixel_shader_.Get(), nullptr, 0);
        }
        context_->OMSetDepthStencilState(no_depth && overlay_depth_state_ ? overlay_depth_state_.Get() : depth_state_.Get(), 0);
        ConstantBuffer constants{};
        DirectX::XMStoreFloat4x4(&constants.mvp, mvp);
        DirectX::XMStoreFloat4x4(&constants.normal_world, DirectX::XMMatrixIdentity());
        constants.light_dir = DirectX::XMFLOAT4(-0.35f, 0.45f, -0.82f, 0.0f);
        constants.base_color_flip = DirectX::XMFLOAT4(0.0f, 0.0f, 0.0f, 0.0f);
        constants.render_tuning = DirectX::XMFLOAT4(1.0f, 0.0f, 0.0f, 0.0f);
        constants.render_tuning2 = DirectX::XMFLOAT4(8.0f, 16.0f, 0.0f, 0.0f);
        constants.editor_tint = DirectX::XMFLOAT4(0.0f, 0.0f, 0.0f, 0.0f);
        context_->UpdateSubresource(constants_.Get(), 0, nullptr, &constants, 0, 0);
        context_->VSSetConstantBuffers(0, 1, constants_.GetAddressOf());
        context_->PSSetConstantBuffers(0, 1, constants_.GetAddressOf());
        ID3D11ShaderResourceView* clear_srvs[kTotalSrvCount] = {};
        context_->PSSetShaderResources(0, kTotalSrvCount, clear_srvs);
        context_->Draw(static_cast<UINT>(vertices.size() / 23u), 0);
        context_->PSSetShader(pixel_shader_.Get(), nullptr, 0);
    }

bool Renderer::manifest_original_frame_grid_active() const {
        return stats_.placement_grid_valid
            && stats_.grid_mode == "original_frame"
            && std::isfinite(stats_.grid_y);
    }

float Renderer::workspace_grid_y_for_view(const PreviewRenderView& view) const {
        if (manifest_original_frame_grid_active()) {
            return stats_.grid_y;
        }
        float min_y = std::numeric_limits<float>::infinity();
        for (const PreviewBatch& batch : batches_) {
            if (!batch_visible_in_view(batch, view.role)) continue;
            for (const DirectX::XMFLOAT3& position : batch.cpu_positions) {
                if (std::isfinite(position.y)) {
                    min_y = std::min(min_y, position.y);
                }
            }
        }
        if (!std::isfinite(min_y)) {
            return 0.0f;
        }
        return min_y - 0.035f;
    }

void Renderer::draw_workspace_grid(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) {
        std::vector<float> vertices;
        vertices.reserve(23u * 4u * 41u);
        constexpr int kGridHalfSteps = 12;
        constexpr float kGridStep = 0.25f;
        constexpr float kMajorEvery = 4.0f;
        const float grid_y = workspace_grid_y_for_view(view);
        for (int index = -kGridHalfSteps; index <= kGridHalfSteps; ++index) {
            const float value = static_cast<float>(index) * kGridStep;
            const bool major = std::fmod(std::abs(static_cast<float>(index)), kMajorEvery) < 0.001f;
            float r = major ? 0.24f : 0.14f;
            float g = major ? 0.28f : 0.17f;
            float b = major ? 0.34f : 0.22f;
            if (index == 0) {
                append_line_vertex(vertices, -kGridHalfSteps * kGridStep, grid_y, value, 0.55f, 0.12f, 0.12f);
                append_line_vertex(vertices,  kGridHalfSteps * kGridStep, grid_y, value, 0.55f, 0.12f, 0.12f);
                append_line_vertex(vertices, value, grid_y, -kGridHalfSteps * kGridStep, 0.10f, 0.48f, 0.24f);
                append_line_vertex(vertices, value, grid_y,  kGridHalfSteps * kGridStep, 0.10f, 0.48f, 0.24f);
                continue;
            }
            append_line_vertex(vertices, -kGridHalfSteps * kGridStep, grid_y, value, r, g, b);
            append_line_vertex(vertices,  kGridHalfSteps * kGridStep, grid_y, value, r, g, b);
            append_line_vertex(vertices, value, grid_y, -kGridHalfSteps * kGridStep, r, g, b);
            append_line_vertex(vertices, value, grid_y,  kGridHalfSteps * kGridStep, r, g, b);
        }
        draw_colored_lines(vertices, world_view_projection, false);
    }

void Renderer::draw_alignment_axes(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) {
        if (!alignment_.enabled || view.role == PreviewViewRole::Reference) return;
        (void)world_view_projection;
        auto axis_points = alignment_axis_points();
        if (axis_points.empty()) return;

        constexpr float kAlignmentGizmoVisualScale = 0.65f;

        std::vector<float> vertices;
        vertices.reserve(23u * 512u);
        DirectX::XMMATRIX identity = DirectX::XMMatrixIdentity();

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
            width_pixels *= kAlignmentGizmoVisualScale;
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
            radius *= kAlignmentGizmoVisualScale;
            constexpr int kSegments = 28;
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
            width_pixels *= kAlignmentGizmoVisualScale;
            constexpr int kSegments = 64;
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
        auto add_axis_label = [&](const char* label, ScreenPoint end, ScreenPoint center, const DirectX::XMFLOAT3& color, bool active) {
            if (!label || !label[0]) return;
            const float dx = end.x - center.x;
            const float dy = end.y - center.y;
            const float length = std::max(1.0f, std::hypot(dx, dy));
            const float ux = dx / length;
            const float uy = dy / length;
            const float size = active ? 20.0f : 18.0f;
            ScreenPoint label_center{
                std::clamp(end.x + ux * 28.0f, view.viewport.TopLeftX + size, view.viewport.TopLeftX + view.viewport.Width - size),
                std::clamp(end.y + uy * 28.0f, view.viewport.TopLeftY + size, view.viewport.TopLeftY + view.viewport.Height - size)
            };
            auto glyph_point = [&](float x, float y) -> ScreenPoint {
                return ScreenPoint{
                    label_center.x + (x - 0.5f) * size,
                    label_center.y + (y - 0.5f) * size
                };
            };
            auto add_label_line = [&](float x0, float y0, float x1, float y1, float width, float r, float g, float blue) {
                add_thick_line(glyph_point(x0, y0), glyph_point(x1, y1), width, r, g, blue);
            };
            auto draw_pass = [&](float width, float r, float g, float blue) {
                if (label[0] == 'X') {
                    add_label_line(0.08f, 0.08f, 0.92f, 0.92f, width, r, g, blue);
                    add_label_line(0.92f, 0.08f, 0.08f, 0.92f, width, r, g, blue);
                } else if (label[0] == 'Y') {
                    add_label_line(0.08f, 0.08f, 0.50f, 0.48f, width, r, g, blue);
                    add_label_line(0.92f, 0.08f, 0.50f, 0.48f, width, r, g, blue);
                    add_label_line(0.50f, 0.48f, 0.50f, 0.92f, width, r, g, blue);
                } else if (label[0] == 'Z') {
                    add_label_line(0.10f, 0.10f, 0.90f, 0.10f, width, r, g, blue);
                    add_label_line(0.90f, 0.10f, 0.10f, 0.90f, width, r, g, blue);
                    add_label_line(0.10f, 0.90f, 0.90f, 0.90f, width, r, g, blue);
                }
            };
            draw_pass(active ? 9.0f : 8.0f, 0.92f, 0.96f, 1.0f);
            draw_pass(active ? 6.0f : 5.2f, 0.0f, 0.0f, 0.0f);
            draw_pass(active ? 3.8f : 3.2f, color.x, color.y, color.z);
        };
        auto axis_color = [](const std::string& axis) -> DirectX::XMFLOAT3 {
            if (axis == "x") return DirectX::XMFLOAT3(1.0f, 0.05f, 0.03f);
            if (axis == "y") return DirectX::XMFLOAT3(0.0f, 1.0f, 0.24f);
            return DirectX::XMFLOAT3(0.0f, 0.50f, 1.0f);
        };

        ScreenPoint origin = axis_points.begin()->second.first;
        for (const auto& [axis, segment] : axis_points) {
            const bool active = alignment_.drag_axis == axis || alignment_.hover_axis == axis;
            DirectX::XMFLOAT3 color = axis_color(axis);
            add_thick_line(segment.first, segment.second, active ? 11.0f : 9.2f, 0.92f, 0.96f, 1.0f);
            add_thick_line(segment.first, segment.second, active ? 8.4f : 7.0f, 0.0f, 0.0f, 0.0f);
            add_thick_line(segment.first, segment.second, active ? 6.4f : 5.4f, color.x, color.y, color.z);
            add_disc(segment.second, active ? 16.0f : 14.5f, 0.92f, 0.96f, 1.0f);
            add_disc(segment.second, active ? 13.0f : 11.7f, 0.0f, 0.0f, 0.0f);
            add_disc(segment.second, active ? 10.8f : 9.6f, color.x, color.y, color.z);
            add_axis_label(axis == "x" ? "X" : (axis == "y" ? "Y" : "Z"), segment.second, segment.first, color, active);
        }

        const bool screen_active = alignment_.drag_axis == "screen" || alignment_.hover_axis == "screen";
        add_disc(origin, screen_active ? 16.0f : 14.0f, 0.92f, 0.96f, 1.0f);
        add_disc(origin, screen_active ? 13.0f : 11.2f, 0.0f, 0.0f, 0.0f);
        add_disc(origin, screen_active ? 10.6f : 9.0f, 1.0f, 0.72f, 0.05f);
        const bool rotate_active = (alignment_.rotation_drag_active && !alignment_.rotation_drag_roll) || alignment_.hover_axis == "rotate";
        const bool roll_active = (alignment_.rotation_drag_active && alignment_.rotation_drag_roll) || alignment_.hover_axis == "roll";
        add_ring(origin, rotate_active ? 50.0f : 48.0f, rotate_active ? 8.6f : 7.0f, 0.92f, 0.96f, 1.0f);
        add_ring(origin, rotate_active ? 50.0f : 48.0f, rotate_active ? 6.6f : 5.4f, 0.0f, 0.0f, 0.0f);
        add_ring(origin, rotate_active ? 50.0f : 48.0f, rotate_active ? 5.2f : 4.2f, 1.0f, 0.72f, 0.05f);
        add_ring(origin, roll_active ? 76.0f : 74.0f, roll_active ? 8.6f : 7.0f, 0.92f, 0.96f, 1.0f);
        add_ring(origin, roll_active ? 76.0f : 74.0f, roll_active ? 6.6f : 5.4f, 0.0f, 0.0f, 0.0f);
        add_ring(origin, roll_active ? 76.0f : 74.0f, roll_active ? 5.2f : 4.2f, 1.0f, 0.18f, 1.0f);
        add_disc(ScreenPoint{origin.x + 48.0f, origin.y}, rotate_active ? 10.4f : 9.0f, 0.0f, 0.0f, 0.0f);
        add_disc(ScreenPoint{origin.x + 48.0f, origin.y}, rotate_active ? 8.0f : 6.8f, 1.0f, 0.72f, 0.05f);
        add_disc(ScreenPoint{origin.x + 74.0f, origin.y}, roll_active ? 10.4f : 9.0f, 0.0f, 0.0f, 0.0f);
        add_disc(ScreenPoint{origin.x + 74.0f, origin.y}, roll_active ? 8.0f : 6.8f, 1.0f, 0.18f, 1.0f);
        draw_colored_triangles(vertices, identity, true);
    }

DirectX::XMFLOAT3 Renderer::transform_coord(const DirectX::XMFLOAT3& point, const DirectX::XMMATRIX& matrix) {
        DirectX::XMFLOAT3 output{};
        DirectX::XMStoreFloat3(&output, DirectX::XMVector3TransformCoord(DirectX::XMLoadFloat3(&point), matrix));
        return output;
    }

void Renderer::append_debug_line(
        std::vector<float>& vertices,
        const DirectX::XMFLOAT3& a,
        const DirectX::XMFLOAT3& b,
        float r,
        float g,
        float blue
    ) {
        append_line_vertex(vertices, a.x, a.y, a.z, r, g, blue);
        append_line_vertex(vertices, b.x, b.y, b.z, r, g, blue);
    }

void Renderer::append_debug_cross(
        std::vector<float>& vertices,
        const DirectX::XMFLOAT3& point,
        float size,
        float r,
        float g,
        float blue
    ) {
        const float s = std::max(0.0025f, size);
        append_debug_line(vertices, DirectX::XMFLOAT3(point.x - s, point.y, point.z), DirectX::XMFLOAT3(point.x + s, point.y, point.z), r, g, blue);
        append_debug_line(vertices, DirectX::XMFLOAT3(point.x, point.y - s, point.z), DirectX::XMFLOAT3(point.x, point.y + s, point.z), r, g, blue);
        append_debug_line(vertices, DirectX::XMFLOAT3(point.x, point.y, point.z - s), DirectX::XMFLOAT3(point.x, point.y, point.z + s), r, g, blue);
    }

void Renderer::append_debug_aabb(
        std::vector<float>& vertices,
        const DirectX::XMFLOAT3& min_corner,
        const DirectX::XMFLOAT3& max_corner,
        float r,
        float g,
        float blue
    ) {
        DirectX::XMFLOAT3 corners[8] = {
            {min_corner.x, min_corner.y, min_corner.z},
            {max_corner.x, min_corner.y, min_corner.z},
            {max_corner.x, max_corner.y, min_corner.z},
            {min_corner.x, max_corner.y, min_corner.z},
            {min_corner.x, min_corner.y, max_corner.z},
            {max_corner.x, min_corner.y, max_corner.z},
            {max_corner.x, max_corner.y, max_corner.z},
            {min_corner.x, max_corner.y, max_corner.z},
        };
        constexpr int edges[12][2] = {
            {0, 1}, {1, 2}, {2, 3}, {3, 0},
            {4, 5}, {5, 6}, {6, 7}, {7, 4},
            {0, 4}, {1, 5}, {2, 6}, {3, 7},
        };
        for (const auto& edge : edges) {
            append_debug_line(vertices, corners[edge[0]], corners[edge[1]], r, g, blue);
        }
    }

void Renderer::draw_cloth_debug_overlays(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) {
        if (!cloth_state_.show_pins && !cloth_state_.show_colliders) return;
        std::vector<float> vertices;
        vertices.reserve(23u * 256u);
        if (cloth_state_.show_colliders) {
            for (const ClothCollider& collider : cloth_colliders_) {
                if (collider.type == 1) {
                    const float radius = std::max(0.012f, collider.radius);
                    append_debug_cross(vertices, collider.a, radius, 0.25f, 0.82f, 1.0f);
                    append_debug_line(vertices, DirectX::XMFLOAT3(collider.a.x - radius, collider.a.y, collider.a.z), DirectX::XMFLOAT3(collider.a.x + radius, collider.a.y, collider.a.z), 0.25f, 0.82f, 1.0f);
                    append_debug_line(vertices, DirectX::XMFLOAT3(collider.a.x, collider.a.y - radius, collider.a.z), DirectX::XMFLOAT3(collider.a.x, collider.a.y + radius, collider.a.z), 0.25f, 0.82f, 1.0f);
                    append_debug_line(vertices, DirectX::XMFLOAT3(collider.a.x, collider.a.y, collider.a.z - radius), DirectX::XMFLOAT3(collider.a.x, collider.a.y, collider.a.z + radius), 0.25f, 0.82f, 1.0f);
                } else if (collider.type == 2) {
                    append_debug_line(vertices, collider.a, collider.b, 0.25f, 0.82f, 1.0f);
                    append_debug_cross(vertices, collider.a, std::max(0.012f, collider.radius), 0.25f, 0.82f, 1.0f);
                    append_debug_cross(vertices, collider.b, std::max(0.012f, collider.radius), 0.25f, 0.82f, 1.0f);
                } else if (collider.type == 3) {
                    append_debug_aabb(vertices, collider.a, collider.b, 0.25f, 0.82f, 1.0f);
                }
            }
        }
        if (cloth_state_.show_pins) {
            for (PreviewBatch& batch : batches_) {
                if (!batch_visible_in_view(batch, view.role) || !batch.cloth.initialized) continue;
                const DirectX::XMMATRIX alignment_transform =
                    view.role == PreviewViewRole::Reference ? DirectX::XMMatrixIdentity() : alignment_preview_transform_for_batch(batch);
                const ClothRuntime& cloth = batch.cloth;
                for (size_t index = 0; index < cloth.positions.size(); ++index) {
                    const float pin = index < cloth.pin_weights.size() ? std::clamp(cloth.pin_weights[index], 0.0f, 1.0f) : 0.0f;
                    if (pin <= 0.02f) continue;
                    const DirectX::XMFLOAT3 point = transform_coord(cloth.positions[index], alignment_transform);
                    append_debug_cross(vertices, point, 0.010f + pin * 0.020f, 1.0f, 0.42f, 0.86f);
                }
            }
        }
        draw_colored_lines(vertices, world_view_projection, true);
    }

void Renderer::draw_skeleton_overlay(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) {
        if (icon_capture_mode_ || !skeleton_overlay_.enabled || skeleton_overlay_.bones.empty()) return;
        if (view.role == PreviewViewRole::Reference) return;
        std::vector<float> vertices;
        vertices.reserve(23u * skeleton_overlay_.bones.size() * 8u);
        for (const SkeletonOverlayBoneState& bone : skeleton_overlay_.bones) {
            if (!bone.has_position) continue;
            const bool selected = bone.index == skeleton_overlay_.selected_bone_index;
            const float line_r = selected ? 1.0f : 0.25f;
            const float line_g = selected ? 0.68f : 0.78f;
            const float line_b = selected ? 0.18f : 1.0f;
            if (bone.has_parent_position) {
                const float dx = bone.position.x - bone.parent_position.x;
                const float dy = bone.position.y - bone.parent_position.y;
                const float dz = bone.position.z - bone.parent_position.z;
                if ((dx * dx + dy * dy + dz * dz) > 0.000001f) {
                    append_debug_line(vertices, bone.parent_position, bone.position, line_r, line_g, line_b);
                }
            }
            append_debug_cross(vertices, bone.position, selected ? 0.032f : 0.018f, selected ? 1.0f : 0.88f, selected ? 0.78f : 0.95f, selected ? 0.16f : 1.0f);
        }
        draw_colored_lines(vertices, world_view_projection, true);
    }

void Renderer::set_preview_batch_lighting_constants(
        ConstantBuffer& constants,
        const PreviewBatch& batch,
        const DirectX::XMMATRIX& normal_source_world,
        bool mesh_edit_flat) const {
        DirectX::XMVECTOR normal_determinant{};
        const DirectX::XMMATRIX normal_world = DirectX::XMMatrixTranspose(
            DirectX::XMMatrixInverse(&normal_determinant, normal_source_world));
        DirectX::XMStoreFloat4x4(&constants.normal_world, normal_world);
        const float light_azimuth = DirectX::XMConvertToRadians(render_tuning_.light_azimuth_degrees);
        const float light_elevation = DirectX::XMConvertToRadians(render_tuning_.light_elevation_degrees);
        const float light_cos_elevation = std::cos(light_elevation);
        constants.light_dir = DirectX::XMFLOAT4(
            std::sin(light_azimuth) * light_cos_elevation,
            std::sin(light_elevation),
            -std::cos(light_azimuth) * light_cos_elevation,
            0.0f);
        constants.base_color_flip = mesh_edit_flat
            ? DirectX::XMFLOAT4(0.54f, 0.55f, 0.54f, 0.0f)
            : DirectX::XMFLOAT4(batch.base_color[0], batch.base_color[1], batch.base_color[2], batch.flip_v ? 1.0f : 0.0f);
        constants.flags = mesh_edit_flat
            ? DirectX::XMFLOAT4(0.0f, 0.0f, 0.0f, 0.0f)
            : DirectX::XMFLOAT4(
                batch.base_srv ? 1.0f : 0.0f,
                batch.normal_srv ? 1.0f : 0.0f,
                (batch.material_srv && batch.material_response_promoted) ? 1.0f : 0.0f,
                batch.height_srv ? 1.0f : 0.0f);
        constants.flags2 = mesh_edit_flat
            ? DirectX::XMFLOAT4(0.0f, 0.0f, 0.0f, 0.0f)
            : DirectX::XMFLOAT4(
                batch.occlusion_srv ? 1.0f : 0.0f,
                batch.roughness_srv ? 1.0f : 0.0f,
                batch.metalness_srv ? 1.0f : 0.0f,
                batch.specular_srv ? 1.0f : 0.0f);
}

void Renderer::draw_preview_batch(
        PreviewBatch& batch,
        const DirectX::XMMATRIX& mvp,
        const DirectX::XMMATRIX& normal_source_world,
        const DirectX::XMFLOAT4& editor_tint,
        bool mesh_edit_flat
    ) {
        if (!batch.vertex_buffer || batch.vertex_count <= 0) return;
        UINT stride = kVertexStrideBytes;
        UINT offset = 0;
        context_->IASetVertexBuffers(0, 1, batch.vertex_buffer.GetAddressOf(), &stride, &offset);
        ConstantBuffer constants{};
        DirectX::XMStoreFloat4x4(&constants.mvp, mvp);
        set_preview_batch_lighting_constants(constants, batch, normal_source_world, mesh_edit_flat);
        constants.material_params = DirectX::XMFLOAT4(
            mesh_edit_flat ? 0.0f : batch.normal_strength,
            mesh_edit_flat ? 0.0f : batch.height_amount,
            mesh_edit_flat || !batch.emissive_color_authoritative ? 0.0f : 1.0f,
            mesh_edit_flat || !batch.emissive_scalar_mask ? 0.0f : 1.0f);
        constants.material_hints = DirectX::XMFLOAT4(
            mesh_edit_flat ? 0.0f : batch.roughness_hint,
            mesh_edit_flat ? 0.0f : batch.metalness_hint,
            mesh_edit_flat ? 0.0f : batch.specular_hint,
            mesh_edit_flat ? 0.0f : batch.height_scale_hint);
        constants.flags3 = mesh_edit_flat
            ? DirectX::XMFLOAT4(0.0f, 0.0f, 0.0f, 0.0f)
            : DirectX::XMFLOAT4(
                batch.detail_srv ? 1.0f : 0.0f,
                render_tuning_.normal_y_mode == 1 ? 1.0f : (render_tuning_.normal_y_mode == 2 ? 0.0f : (batch.invert_normal_y ? 1.0f : 0.0f)),
                batch.alpha_cutout ? 1.0f : 0.0f,
                batch.alpha_threshold);
        constants.render_tuning = mesh_edit_flat
            ? DirectX::XMFLOAT4(0.62f, 0.50f, 0.02f, 0.05f)
            : DirectX::XMFLOAT4(
                render_tuning_.ambient_strength,
                render_tuning_.diffuse_light_scale,
                render_tuning_.specular_base,
                render_tuning_.specular_max);
        constants.render_tuning2 = mesh_edit_flat
            ? DirectX::XMFLOAT4(18.0f, 28.0f, 0.0f, 0.0f)
            : DirectX::XMFLOAT4(
                render_tuning_.shininess_min,
                render_tuning_.shininess_max,
                render_tuning_.diffuse_wrap_bias,
                0.0f);
        constants.render_tuning3 = mesh_edit_flat
            ? DirectX::XMFLOAT4(0.0f, 0.30f, 0.0f, 0.05f)
            : DirectX::XMFLOAT4(
                render_tuning_.ao_strength,
                render_tuning_.roughness_bias,
                render_tuning_.metalness_scale,
                render_tuning_.environment_strength);
        constants.render_tuning4 = mesh_edit_flat
            ? DirectX::XMFLOAT4(0.0f, 0.0f, 0.0f, 0.0f)
            : DirectX::XMFLOAT4(
                render_tuning_.emissive_gain,
                render_tuning_.tone_exposure,
                render_tuning_.tone_contrast,
                render_tuning_.tone_gamma);
        constants.editor_tint = mesh_edit_flat ? DirectX::XMFLOAT4(0.50f, 0.51f, 0.50f, 0.42f) : editor_tint;
        constants.flags4 = DirectX::XMFLOAT4(
            mesh_edit_flat ? 0.0f : batch.base_tint_strength,
            mesh_edit_flat ? 0.0f : static_cast<float>(render_tuning_.diagnostic_mode),
            static_cast<float>(std::max(0, batch.source_submesh_index + 1)),
            mesh_edit_flat ? 0.0f : batch.material_family_code);
        constants.flags5 = mesh_edit_flat
            ? DirectX::XMFLOAT4(0.0f, 0.0f, 0.0f, batch.two_sided ? 1.0f : 0.0f)
            : DirectX::XMFLOAT4(
                batch.material_category_code,
                batch.material_category_confidence,
                batch.material_response_promoted ? 1.0f : 0.0f,
                batch.two_sided ? 1.0f : 0.0f);
        const float emissive_encoded = mesh_edit_flat ? 0.0f : ((batch.emissive_srv ? 2.0f : 0.0f) + std::clamp(batch.emissive_intensity / 12.0f, 0.0f, 1.0f));
        constants.emissive_params = DirectX::XMFLOAT4(
            mesh_edit_flat ? 0.0f : std::clamp(batch.emissive_color[0], 0.0f, 2.0f),
            mesh_edit_flat ? 0.0f : std::clamp(batch.emissive_color[1], 0.0f, 2.0f),
            mesh_edit_flat ? 0.0f : std::clamp(batch.emissive_color[2], 0.0f, 2.0f),
            emissive_encoded);
        constants.material_value_params = mesh_edit_flat
            ? DirectX::XMFLOAT4(1.0f, 1.0f, 1.0f, 0.0f)
            : DirectX::XMFLOAT4(
                std::clamp(batch.texture_uv_scale[0], 0.05f, 64.0f),
                std::clamp(batch.texture_uv_scale[1], 0.05f, 64.0f),
                std::clamp(batch.texture_brightness, 0.1f, 3.0f),
                (batch.roughness_hint_present ? 1.0f : 0.0f)
                    + (batch.metalness_hint_present ? 2.0f : 0.0f)
                    + (batch.specular_hint_present ? 4.0f : 0.0f));
        constants.material_color_params = mesh_edit_flat
            ? DirectX::XMFLOAT4(1.0f, 1.0f, 1.0f, 0.0f)
            : DirectX::XMFLOAT4(
                std::clamp(batch.texture_contrast, 0.25f, 2.5f),
                std::clamp(batch.texture_saturation, 0.0f, 4.0f),
                std::clamp(batch.texture_gamma, 0.25f, 4.0f),
                0.0f);
        constants.material_tint_params = mesh_edit_flat
            ? DirectX::XMFLOAT4(1.0f, 1.0f, 1.0f, 0.0f)
            : DirectX::XMFLOAT4(
                std::clamp(batch.texture_tint[0], 0.0f, 4.0f),
                std::clamp(batch.texture_tint[1], 0.0f, 4.0f),
                std::clamp(batch.texture_tint[2], 0.0f, 4.0f),
                0.0f);
        if (!mesh_edit_flat) {
            for (int layer_index = 0; layer_index < kMaxMaterialLayers; ++layer_index) {
                const PreviewMaterialLayer& layer = batch.material_layers[static_cast<size_t>(layer_index)];
                const bool draw_albedo_layer = lower_copy(layer.role) != "base";
                constants.layer_flags[layer_index] = DirectX::XMFLOAT4(
                    (draw_albedo_layer && layer.diffuse_srv) ? 1.0f : 0.0f,
                    layer.mask_srv ? 1.0f : 0.0f,
                    layer.material_srv ? 1.0f : 0.0f,
                    layer.normal_srv ? 1.0f : 0.0f);
                constants.layer_params[layer_index] = DirectX::XMFLOAT4(
                    layer.channel_index,
                    boosted_preview_layer_weight(layer, layer_index),
                    layer.height_srv ? 1.0f : 0.0f,
                    0.0f);
                constants.layer_tint[layer_index] = DirectX::XMFLOAT4(
                    layer.tint[0],
                    layer.tint[1],
                    layer.tint[2],
                    layer.tint[3]);
                constants.layer_hints[layer_index] = DirectX::XMFLOAT4(
                    layer.roughness_hint,
                    layer.metalness_hint,
                    layer.specular_hint,
                    layer.height_srv ? std::max(layer.height_scale_hint, 0.02f) : 0.0f);
            }
        }
        context_->UpdateSubresource(constants_.Get(), 0, nullptr, &constants, 0, 0);
        context_->VSSetConstantBuffers(0, 1, constants_.GetAddressOf());
        context_->PSSetConstantBuffers(0, 1, constants_.GetAddressOf());
        ID3D11ShaderResourceView* srvs[kTotalSrvCount] = {
            mesh_edit_flat ? nullptr : batch.base_srv.Get(),
            mesh_edit_flat ? nullptr : batch.normal_srv.Get(),
            mesh_edit_flat ? nullptr : batch.material_srv.Get(),
            mesh_edit_flat ? nullptr : batch.occlusion_srv.Get(),
            mesh_edit_flat ? nullptr : batch.roughness_srv.Get(),
            mesh_edit_flat ? nullptr : batch.metalness_srv.Get(),
            mesh_edit_flat ? nullptr : batch.specular_srv.Get(),
            mesh_edit_flat ? nullptr : batch.height_srv.Get(),
            mesh_edit_flat ? nullptr : batch.detail_srv.Get(),
            mesh_edit_flat ? nullptr : batch.emissive_srv.Get(),
        };
        if (!mesh_edit_flat) {
            for (int layer_index = 0; layer_index < kMaxMaterialLayers; ++layer_index) {
                const PreviewMaterialLayer& layer = batch.material_layers[static_cast<size_t>(layer_index)];
                srvs[10 + layer_index] = layer.diffuse_srv.Get();
                srvs[14 + layer_index] = layer.mask_srv.Get();
                srvs[18 + layer_index] = layer.material_srv.Get();
                srvs[22 + layer_index] = layer.normal_srv.Get();
                srvs[26 + layer_index] = layer.height_srv.Get();
            }
        }
        context_->PSSetShaderResources(0, kTotalSrvCount, srvs);
        context_->Draw(static_cast<UINT>(batch.vertex_count), 0);
        ID3D11ShaderResourceView* clear_srvs[kTotalSrvCount] = {};
        context_->PSSetShaderResources(0, kTotalSrvCount, clear_srvs);
    }
