void Renderer::reset_camera(PreviewCameraState& camera) {
        camera = PreviewCameraState{};
    }

void Renderer::reset_replacement_camera() {
        PreviewCameraState camera;
        reset_camera(camera);
        set_replacement_camera(camera);
    }

void Renderer::reset_camera_for_role(PreviewViewRole role) {
        if (role == PreviewViewRole::Reference) {
            reset_camera(reference_camera_);
            send_view_event("reset", role);
            return;
        }
        if (role == PreviewViewRole::All) {
            reset_camera(reference_camera_);
        }
        reset_replacement_camera();
        send_view_event("reset", role);
    }

void Renderer::reset_view() {
        reset_replacement_camera();
        reset_camera(reference_camera_);
        drag_mode_ = 0;
        drag_button_ = 0;
        if (GetCapture() == hwnd_) ReleaseCapture();
        send_view_event("reset", PreviewViewRole::All);
    }

void Renderer::cancel_mouse_interaction(bool release_capture) {
        cancel_mesh_edit_drag();
        cancel_alignment_drag();
        side_by_side_split_drag_active_ = false;
        side_by_side_split_hover_ = false;
        source_part_.click_pending = false;
        drag_mode_ = 0;
        drag_button_ = 0;
        drag_view_role_ = PreviewViewRole::All;
        if (release_capture && GetCapture() == hwnd_) ReleaseCapture();
    }

void Renderer::set_zoom_factor(float zoom_factor) {
        zoom_factor_ = std::clamp(zoom_factor, 0.1f, kMaxZoomFactor);
        fit_to_view_ = false;
        distance_ = kFitDistance / zoom_factor_;
        send_view_event("zoom", PreviewViewRole::Replacement);
    }

void Renderer::set_fit_to_view(bool fit_to_view) {
        fit_to_view_ = fit_to_view;
        distance_ = fit_to_view_ ? kFitDistance : kFitDistance / std::max(zoom_factor_, 0.1f);
        send_view_event("fit", PreviewViewRole::Replacement);
    }

void Renderer::begin_mouse_drag(UINT msg, WPARAM wparam, int x, int y) {
        if (mesh_edit_.drag_active || mesh_edit_.selection_drag_active || alignment_.drag_active || alignment_.rotation_drag_active) {
            return;
        }
        if (drag_mode_ != 0) {
            last_mouse_x_ = x;
            last_mouse_y_ = y;
            if (GetCapture() != hwnd_) SetCapture(hwnd_);
            return;
        }
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool pan_requested = msg == WM_MBUTTONDOWN || msg == WM_RBUTTONDOWN || (msg == WM_LBUTTONDOWN && shift_down);
        drag_mode_ = pan_requested ? 2 : (msg == WM_LBUTTONDOWN ? 1 : 0);
        drag_button_ = msg;
        drag_view_role_ = input_view_role_at(x, y);
        last_mouse_x_ = x;
        last_mouse_y_ = y;
        if (drag_mode_ != 0) SetCapture(hwnd_);
    }

bool Renderer::begin_side_by_side_split_drag(int x, int y) {
        if (!side_by_side_splitter_hit_test(x, y)) return false;
        side_by_side_split_drag_active_ = true;
        side_by_side_split_hover_ = true;
        set_side_by_side_split_from_x(x);
        SetCursor(LoadCursor(nullptr, IDC_SIZEWE));
        if (GetCapture() != hwnd_) SetCapture(hwnd_);
        return true;
    }

bool Renderer::update_side_by_side_split_drag(int x, int y) {
        if (side_by_side_split_drag_active_) {
            set_side_by_side_split_from_x(x);
            SetCursor(LoadCursor(nullptr, IDC_SIZEWE));
            return true;
        }
        const bool hovered = side_by_side_splitter_hit_test(x, y);
        if (hovered != side_by_side_split_hover_) {
            side_by_side_split_hover_ = hovered;
            request_render();
        }
        if (hovered) SetCursor(LoadCursor(nullptr, IDC_SIZEWE));
        return false;
    }

void Renderer::update_mouse_drag(int x, int y) {
        if (drag_mode_ == 0) return;
        int delta_x = x - last_mouse_x_;
        int delta_y = y - last_mouse_y_;
        last_mouse_x_ = x;
        last_mouse_y_ = y;
        if (delta_x == 0 && delta_y == 0) return;
        PreviewCameraState camera = camera_for_view_role(drag_view_role_);
        if (drag_mode_ == 1) {
            float orbit_sign_x = view_settings_.invert_orbit_x ? -1.0f : 1.0f;
            float orbit_sign_y = view_settings_.invert_orbit_y ? -1.0f : 1.0f;
            camera.yaw += static_cast<float>(delta_x) * view_settings_.orbit_sensitivity * orbit_sign_x;
            camera.pitch = std::clamp(
                camera.pitch + static_cast<float>(delta_y) * view_settings_.orbit_sensitivity * orbit_sign_y,
                -89.0f,
                89.0f);
        } else if (drag_mode_ == 2) {
            float units_per_pixel = world_units_per_pixel_for_role(drag_view_role_);
            float horizontal_sign = view_settings_.invert_pan_x ? -1.0f : 1.0f;
            float vertical_sign = view_settings_.invert_pan_y ? 1.0f : -1.0f;
            camera.pan_x += static_cast<float>(delta_x) * units_per_pixel * view_settings_.pan_sensitivity * horizontal_sign;
            camera.pan_y += static_cast<float>(delta_y) * units_per_pixel * view_settings_.pan_sensitivity * vertical_sign;
        }
        set_camera_for_role(drag_view_role_, camera);
    }

void Renderer::end_mouse_drag(UINT msg) {
        bool release = false;
        if (drag_button_ == WM_LBUTTONDOWN && msg == WM_LBUTTONUP) release = true;
        if (drag_button_ == WM_MBUTTONDOWN && msg == WM_MBUTTONUP) release = true;
        if (drag_button_ == WM_RBUTTONDOWN && msg == WM_RBUTTONUP) release = true;
        if (!release) return;
        drag_mode_ = 0;
        drag_button_ = 0;
        const PreviewViewRole completed_role = drag_view_role_;
        drag_view_role_ = PreviewViewRole::All;
        if (GetCapture() == hwnd_) ReleaseCapture();
        send_view_event("drag", completed_role);
    }

bool Renderer::finish_side_by_side_split_drag(int x, int y) {
        if (!side_by_side_split_drag_active_) return false;
        set_side_by_side_split_from_x(x);
        side_by_side_split_drag_active_ = false;
        side_by_side_split_hover_ = side_by_side_splitter_hit_test(x, y);
        if (GetCapture() == hwnd_) ReleaseCapture();
        if (side_by_side_split_hover_) SetCursor(LoadCursor(nullptr, IDC_SIZEWE));
        send_side_by_side_split_event("drag");
        return true;
    }

void Renderer::apply_wheel_delta(int wheel_delta, int x, int y) {
        if (wheel_delta == 0) return;
        const PreviewViewRole role = input_view_role_at(x, y);
        PreviewCameraState camera = camera_for_view_role(role);
        int step = wheel_delta > 0 ? 1 : -1;
        float current_zoom = camera.fit_to_view ? current_display_scale(camera.distance) : camera.zoom_factor;
        size_t closest = 0;
        float best_distance = std::abs(kZoomSteps[0] - current_zoom);
        for (size_t index = 1; index < ARRAYSIZE(kZoomSteps); ++index) {
            float candidate = std::abs(kZoomSteps[index] - current_zoom);
            if (candidate < best_distance) {
                best_distance = candidate;
                closest = index;
            }
        }
        int next_index = std::clamp(static_cast<int>(closest) + step, 0, static_cast<int>(ARRAYSIZE(kZoomSteps)) - 1);
        camera.fit_to_view = false;
        camera.zoom_factor = kZoomSteps[next_index];
        camera.distance = kFitDistance / camera.zoom_factor;
        set_camera_for_role(role, camera);
        send_view_event("wheel", role);
    }

bool Renderer::create_render_targets() {
        ComPtr<ID3D11Texture2D> back_buffer;
        HRESULT hr = swap_chain_->GetBuffer(0, IID_PPV_ARGS(back_buffer.GetAddressOf()));
        if (FAILED(hr)) return false;
        hr = device_->CreateRenderTargetView(back_buffer.Get(), nullptr, render_target_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_TEXTURE2D_DESC depth_desc{};
        depth_desc.Width = static_cast<UINT>(width_);
        depth_desc.Height = static_cast<UINT>(height_);
        depth_desc.MipLevels = 1;
        depth_desc.ArraySize = 1;
        depth_desc.Format = DXGI_FORMAT_D24_UNORM_S8_UINT;
        depth_desc.SampleDesc.Count = msaa_sample_count_;
        depth_desc.SampleDesc.Quality = 0;
        depth_desc.BindFlags = D3D11_BIND_DEPTH_STENCIL;
        ComPtr<ID3D11Texture2D> depth_texture;
        hr = device_->CreateTexture2D(&depth_desc, nullptr, depth_texture.GetAddressOf());
        if (FAILED(hr)) return false;
        return SUCCEEDED(device_->CreateDepthStencilView(depth_texture.Get(), nullptr, depth_view_.GetAddressOf()));
    }

bool Renderer::resize_if_needed() {
        RECT rect{};
        GetClientRect(hwnd_, &rect);
        LONG next_width = std::max<LONG>(1, rect.right - rect.left);
        LONG next_height = std::max<LONG>(1, rect.bottom - rect.top);
        if (next_width == width_ && next_height == height_) {
            return true;
        }
        if (context_) {
            ID3D11RenderTargetView* null_target = nullptr;
            context_->OMSetRenderTargets(1, &null_target, nullptr);
        }
        render_target_.Reset();
        depth_view_.Reset();
        HRESULT hr = env_flag_enabled("CDMW_D3D11_PREVIEW_FORCE_RESIZE_FAILURE")
            ? DXGI_ERROR_DEVICE_RESET
            : swap_chain_->ResizeBuffers(0, static_cast<UINT>(next_width), static_cast<UINT>(next_height), DXGI_FORMAT_UNKNOWN, 0);
        if (FAILED(hr)) {
            ++stats_.resize_failure_count;
            stats_.resize_failure_hresult = hresult_hex(hr);
            stats_.resize_failure_reason = "resize_buffers_failed";
            stats_.skipped.push_back("swap chain resize failed:" + hresult_hex(hr));
            cdmw_native_diag::event(
                "d3d11_resize_failed",
                {{"hresult", hresult_hex(hr)}, {"width", std::to_string(next_width)}, {"height", std::to_string(next_height)}});
            if (is_device_loss_hresult(hr)) {
                handle_device_loss("ResizeBuffers", hr);
            }
            return false;
        }
        width_ = next_width;
        height_ = next_height;
        if (!create_render_targets()) {
            stats_.resize_failure_reason = "create_render_targets_failed";
            stats_.skipped.push_back("swap chain resize render-target recreation failed");
            return false;
        }
        return true;
    }

bool Renderer::create_pipeline() {
        clear_color_ = kFixedPreviewClearColor;
        std::string shader_error;
        ComPtr<ID3DBlob> vs_blob;
        ComPtr<ID3DBlob> ps_blob;
        ComPtr<ID3DBlob> overlay_ps_blob;
        if (FAILED(compile_shader(kShaderSource, "vs_main", "vs_4_0", vs_blob.GetAddressOf(), shader_error))) {
            stats_.skipped.push_back("vertex shader compile failed: " + shader_error);
            return false;
        }
        if (FAILED(compile_shader(kShaderSource, "ps_main", "ps_4_0", ps_blob.GetAddressOf(), shader_error))) {
            stats_.skipped.push_back("pixel shader compile failed: " + shader_error);
            return false;
        }
        const std::string overlay_shader_source = std::string(kShaderSourceCommon) + kOverlayPixelShaderSource;
        if (FAILED(compile_shader(overlay_shader_source, "ps_overlay", "ps_4_0", overlay_ps_blob.GetAddressOf(), shader_error))) {
            stats_.skipped.push_back("overlay pixel shader compile failed: " + shader_error);
            return false;
        }
        ComPtr<ID3DBlob> dot_vs_blob;
        ComPtr<ID3DBlob> dot_ps_blob;
        if (FAILED(compile_shader(kVertexDotShaderSource, "vs_dot", "vs_4_0", dot_vs_blob.GetAddressOf(), shader_error))) {
            stats_.skipped.push_back("vertex dot shader compile failed: " + shader_error);
            return false;
        }
        if (FAILED(compile_shader(kVertexDotShaderSource, "ps_dot", "ps_4_0", dot_ps_blob.GetAddressOf(), shader_error))) {
            stats_.skipped.push_back("vertex dot pixel shader compile failed: " + shader_error);
            return false;
        }
        HRESULT hr = device_->CreateVertexShader(vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), nullptr, vertex_shader_.GetAddressOf());
        if (FAILED(hr)) return false;
        hr = device_->CreatePixelShader(ps_blob->GetBufferPointer(), ps_blob->GetBufferSize(), nullptr, pixel_shader_.GetAddressOf());
        if (FAILED(hr)) return false;
        hr = device_->CreatePixelShader(overlay_ps_blob->GetBufferPointer(), overlay_ps_blob->GetBufferSize(), nullptr, overlay_pixel_shader_.GetAddressOf());
        if (FAILED(hr)) return false;
        hr = device_->CreateVertexShader(dot_vs_blob->GetBufferPointer(), dot_vs_blob->GetBufferSize(), nullptr, vertex_dot_shader_.GetAddressOf());
        if (FAILED(hr)) return false;
        hr = device_->CreatePixelShader(dot_ps_blob->GetBufferPointer(), dot_ps_blob->GetBufferSize(), nullptr, vertex_dot_pixel_shader_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_INPUT_ELEMENT_DESC layout[] = {
            {"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"NORMAL", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 3 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"COLOR", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 6 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT, 0, 9 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"TANGENT", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 11 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"BINORMAL", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 14 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
        };
        hr = device_->CreateInputLayout(layout, ARRAYSIZE(layout), vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), input_layout_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_INPUT_ELEMENT_DESC dot_layout[] = {
            {"TEXCOORD", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0, D3D11_INPUT_PER_INSTANCE_DATA, 1},
            {"TEXCOORD", 1, DXGI_FORMAT_R32G32_FLOAT, 0, 3 * 4, D3D11_INPUT_PER_INSTANCE_DATA, 1},
            {"COLOR", 0, DXGI_FORMAT_R32G32B32A32_FLOAT, 0, 5 * 4, D3D11_INPUT_PER_INSTANCE_DATA, 1},
        };
        hr = device_->CreateInputLayout(dot_layout, ARRAYSIZE(dot_layout), dot_vs_blob->GetBufferPointer(), dot_vs_blob->GetBufferSize(), vertex_dot_input_layout_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_BUFFER_DESC cb_desc{};
        cb_desc.ByteWidth = sizeof(ConstantBuffer);
        cb_desc.Usage = D3D11_USAGE_DEFAULT;
        cb_desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        hr = device_->CreateBuffer(&cb_desc, nullptr, constants_.GetAddressOf());
        if (FAILED(hr)) return false;
        if (!create_sampler_state()) return false;
        D3D11_RASTERIZER_DESC raster_desc{};
        raster_desc.FillMode = D3D11_FILL_SOLID;
        raster_desc.CullMode = D3D11_CULL_NONE;
        raster_desc.DepthClipEnable = TRUE;
        raster_desc.MultisampleEnable = msaa_sample_count_ > 1;
        raster_desc.AntialiasedLineEnable = TRUE;
        hr = device_->CreateRasterizerState(&raster_desc, rasterizer_.GetAddressOf());
        if (FAILED(hr)) return false;
        raster_desc.CullMode = D3D11_CULL_BACK;
        hr = device_->CreateRasterizerState(&raster_desc, cull_rasterizer_.GetAddressOf());
        if (FAILED(hr)) return false;
        raster_desc.CullMode = D3D11_CULL_NONE;
        raster_desc.FillMode = D3D11_FILL_WIREFRAME;
        hr = device_->CreateRasterizerState(&raster_desc, wireframe_rasterizer_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_DEPTH_STENCIL_DESC depth_desc{};
        depth_desc.DepthEnable = TRUE;
        depth_desc.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ALL;
        depth_desc.DepthFunc = D3D11_COMPARISON_LESS_EQUAL;
        hr = device_->CreateDepthStencilState(&depth_desc, depth_state_.GetAddressOf());
        if (FAILED(hr)) return false;
        depth_desc.DepthEnable = FALSE;
        depth_desc.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ZERO;
        return SUCCEEDED(device_->CreateDepthStencilState(&depth_desc, overlay_depth_state_.GetAddressOf()));
    }

bool Renderer::create_sampler_state() {
        if (!device_) return false;
        D3D11_SAMPLER_DESC sampler_desc{};
        sampler_desc.Filter = D3D11_FILTER_ANISOTROPIC;
        const D3D11_TEXTURE_ADDRESS_MODE address_mode =
            render_tuning_.texture_address_mode == "clamp" ? D3D11_TEXTURE_ADDRESS_CLAMP : D3D11_TEXTURE_ADDRESS_WRAP;
        sampler_desc.AddressU = address_mode;
        sampler_desc.AddressV = address_mode;
        sampler_desc.AddressW = address_mode;
        sampler_desc.MipLODBias = render_tuning_.mip_lod_bias;
        sampler_desc.MaxAnisotropy = static_cast<UINT>(std::clamp(render_tuning_.max_anisotropy, 1, 16));
        sampler_desc.MaxLOD = D3D11_FLOAT32_MAX;
        const bool replacing_existing_sampler = static_cast<bool>(sampler_);
        HRESULT hr = device_->CreateSamplerState(&sampler_desc, sampler_.ReleaseAndGetAddressOf());
        if (SUCCEEDED(hr)) {
            stats_.sampler_max_anisotropy = static_cast<int>(sampler_desc.MaxAnisotropy);
            stats_.sampler_mip_lod_bias = sampler_desc.MipLODBias;
            if (replacing_existing_sampler) {
                ++stats_.sampler_recreate_count;
            }
            return true;
        }
        return false;
    }
