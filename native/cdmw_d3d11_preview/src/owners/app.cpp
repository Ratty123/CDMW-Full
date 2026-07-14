static LRESULT CALLBACK window_proc(HWND hwnd, UINT msg, WPARAM wparam, LPARAM lparam) {
    Renderer* renderer = reinterpret_cast<Renderer*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (renderer) {
        LRESULT handled_result = 0;
        if (renderer->handle_window_message(msg, wparam, lparam, handled_result)) {
            return handled_result;
        }
    }
    if (msg == WM_DESTROY) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wparam, lparam);
}

static std::string run_host_message_loop(
    Renderer& renderer,
    HWND hwnd,
    HWND parent_hwnd,
    int window_width,
    int window_height,
    RendererStats& stats) {
    MSG msg{};
    bool running = true;
    std::string close_reason = "shutdown";
    auto last_parent_sync = std::chrono::steady_clock::now();
    auto last_parent_health_check = std::chrono::steady_clock::now();
    std::chrono::steady_clock::time_point parent_unresponsive_since{};
    std::uint64_t parent_unresponsive_count = 0;
    int last_parent_width = window_width;
    int last_parent_height = window_height;
    bool parent_renderable = true;
    while (running) {
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) {
                running = false;
                break;
            }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        if (running && parent_hwnd) {
            auto now = std::chrono::steady_clock::now();
            if (std::chrono::duration<double, std::milli>(now - last_parent_sync).count() >= 100.0) {
                last_parent_sync = now;
                RECT rect{};
                if (!IsWindow(parent_hwnd)) {
                    close_reason = "parent_window_gone";
                    cdmw_native_diag::event("parent_window_gone");
                    running = false;
                } else if (GetClientRect(parent_hwnd, &rect)) {
                    const LONG raw_width = rect.right - rect.left;
                    const LONG raw_height = rect.bottom - rect.top;
                    parent_renderable = raw_width > 0 && raw_height > 0 && IsWindowVisible(parent_hwnd) && !IsIconic(parent_hwnd);
                    int width = std::max<LONG>(1, raw_width);
                    int height = std::max<LONG>(1, raw_height);
                    if (width != last_parent_width || height != last_parent_height) {
                        last_parent_width = width;
                        last_parent_height = height;
                        SetWindowPos(hwnd, nullptr, 0, 0, width, height, SWP_NOZORDER | SWP_NOACTIVATE);
                        renderer.request_render();
                    }
                } else {
                    parent_renderable = false;
                }
            }
            if (running && std::chrono::duration<double, std::milli>(now - last_parent_health_check).count() >= kParentHealthCheckMs) {
                last_parent_health_check = now;
                DWORD_PTR ping_result = 0;
                const BOOL responsive = SendMessageTimeoutW(
                    parent_hwnd,
                    WM_NULL,
                    0,
                    0,
                    SMTO_ABORTIFHUNG | SMTO_BLOCK,
                    kParentHealthTimeoutMs,
                    &ping_result);
                if (!responsive) {
                    if (parent_unresponsive_since.time_since_epoch().count() == 0) {
                        parent_unresponsive_since = now;
                    }
                    ++parent_unresponsive_count;
                    renderer.set_parent_health("parent_unresponsive", parent_unresponsive_count);
                    const double unresponsive_ms = std::chrono::duration<double, std::milli>(now - parent_unresponsive_since).count();
                    if (unresponsive_ms >= kParentHangExitMs) {
                        close_reason = "parent_unresponsive";
                        cdmw_native_diag::event(
                            "parent_unresponsive_exit",
                            {
                                {"parent_unresponsive_ms", std::to_string(unresponsive_ms)},
                                {"parent_unresponsive_count", std::to_string(parent_unresponsive_count)},
                                {"frame_count", std::to_string(stats.frame_count)},
                                {"render_request_count", std::to_string(stats.render_request_count)}
                            });
                        running = false;
                    }
                } else {
                    if (parent_unresponsive_count > 0) {
                        cdmw_native_diag::event(
                            "parent_responsive",
                            {{"parent_unresponsive_count", std::to_string(parent_unresponsive_count)}});
                    }
                    parent_unresponsive_count = 0;
                    parent_unresponsive_since = std::chrono::steady_clock::time_point{};
                    renderer.set_parent_health("ok", 0);
                }
            }
        }
        if (!running) {
            continue;
        }
        renderer.process_pending_commands();
        if (!renderer.should_render()) {
            MsgWaitForMultipleObjects(0, nullptr, FALSE, kIdleWaitMs, QS_ALLINPUT);
            continue;
        }
        const bool window_renderable = IsWindowVisible(hwnd) && !IsIconic(hwnd);
        if (parent_renderable && window_renderable) {
            renderer.render();
            if (renderer.device_lost()) {
                close_reason = "device_lost";
                running = false;
            }
        } else {
            renderer.note_render_suppressed(parent_renderable ? "window_not_visible" : "parent_not_renderable");
            MsgWaitForMultipleObjects(0, nullptr, FALSE, kIdleWaitMs, QS_ALLINPUT);
        }
    }
    return close_reason;
}

static int run_host(const Args& args) {
    auto start = std::chrono::steady_clock::now();
    cdmw_native_diag::event("startup", {{"backend", "D3D11"}, {"package_dir", cdmw_native_diag::path_to_utf8(args.preview_package)}, {"status_file", cdmw_native_diag::path_to_utf8(args.status_file)}});
    ComInitScope com;
    if (!com.ok()) {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"native D3D11 COM initialization failed\"}");
        cdmw_native_diag::event("startup_error", {{"reason", "COM initialization failed"}, {"hresult", std::to_string(static_cast<unsigned int>(com.hr))}});
        return 5;
    }
    if (args.preview_package.empty() || !fs::is_directory(args.preview_package)) {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"preview package directory is missing\"}");
        cdmw_native_diag::event("startup_error", {{"reason", "preview package directory is missing"}});
        return 2;
    }
    write_status(args.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"manifest\",\"percent\":85,\"current\":85,\"total\":100,\"message\":\"Loading native D3D11 preview package...\"}");
    std::string manifest = read_text(args.preview_package / L"manifest.json");
    RendererStats stats;
    std::vector<PreviewBatch> batches = parse_manifest_batches(args.preview_package, manifest, stats);
    SkeletonOverlayState skeleton_overlay = parse_skeleton_overlay_state(manifest, stats);
    std::vector<ClothCollider> cloth_colliders = parse_cloth_colliders(args.preview_package, manifest);
    stats.cloth_collider_count = static_cast<int>(cloth_colliders.size());
    ViewSettings view_settings = parse_view_settings(manifest);
    RenderTuning render_tuning = parse_render_tuning(manifest);
    std::string display_mode = parse_display_mode(manifest, "replacement_only");
    stats.manifest_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();

    WNDCLASSW wc{};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"CDMWNativeD3D11PreviewWindow";
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.style = CS_DBLCLKS;
    RegisterClassW(&wc);

    HWND parent_hwnd = reinterpret_cast<HWND>(args.parent_hwnd);
    RECT parent_rect{};
    int window_x = CW_USEDEFAULT;
    int window_y = CW_USEDEFAULT;
    int window_width = 980;
    int window_height = 720;
    DWORD window_style = args.hidden ? WS_POPUP : (WS_OVERLAPPEDWINDOW | WS_VISIBLE);
    if (parent_hwnd && IsWindow(parent_hwnd)) {
        GetClientRect(parent_hwnd, &parent_rect);
        window_x = 0;
        window_y = 0;
        window_width = std::max<LONG>(1, parent_rect.right - parent_rect.left);
        window_height = std::max<LONG>(1, parent_rect.bottom - parent_rect.top);
        window_style = WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN;
        if (!args.hidden) window_style |= WS_VISIBLE;
    } else {
        parent_hwnd = nullptr;
    }

    HWND hwnd = CreateWindowExW(
        0,
        wc.lpszClassName,
        L"CDMW Native D3D11 Preview",
        window_style,
        window_x,
        window_y,
        window_width,
        window_height,
        parent_hwnd,
        nullptr,
        wc.hInstance,
        nullptr);
    if (!hwnd) {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"failed to create preview window\"}");
        cdmw_native_diag::event("startup_error", {{"reason", "failed to create preview window"}});
        return 3;
    }

    write_status(args.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"upload\",\"percent\":90,\"current\":90,\"total\":100,\"message\":\"Uploading D3D11 geometry and DDS textures...\"}");
    Renderer renderer(
        hwnd,
        args,
        std::move(batches),
        std::move(cloth_colliders),
        std::move(skeleton_overlay),
        stats,
        view_settings,
        render_tuning,
        display_mode);
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(&renderer));
    if (!renderer.initialize()) {
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
        write_status(args.status_file, error_payload("native D3D11 renderer initialization failed", stats));
        cdmw_native_diag::event("startup_error", {{"reason", "renderer initialization failed"}});
        return 4;
    }
    write_status(args.status_file, resources_loaded_payload(stats));
    renderer.request_render();
    cdmw_native_diag::event("renderer_initialized", {{"batches", std::to_string(stats.batch_count)}, {"vertices", std::to_string(stats.vertex_count)}, {"display_mode", display_mode}});

    const std::string close_reason = run_host_message_loop(
        renderer,
        hwnd,
        parent_hwnd,
        window_width,
        window_height,
        stats);
    renderer.release_model_resources(close_reason.c_str());
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
    write_status(args.status_file, closed_payload(stats, close_reason));
    cdmw_native_diag::event("clean_shutdown", {{"reason", close_reason}});
    return close_reason == "device_lost" ? 6 : 0;
}

int run(int argc, wchar_t** argv) {
    Args args = parse_args(argc, argv);
    cdmw_native_diag::init("cdmw-d3d11-preview", args.crash_dir, args.diagnostic_log);
    if (args.self_test) {
        cdmw_native_diag::event("self_test_start");
        ComPtr<ID3D11Device> device;
        ComPtr<ID3D11DeviceContext> context;
        D3D_FEATURE_LEVEL feature{};
        HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, device.GetAddressOf(), &feature, context.GetAddressOf());
        std::string shader_error;
        ComPtr<ID3DBlob> vs_blob;
        ComPtr<ID3DBlob> ps_blob;
        ComPtr<ID3DBlob> overlay_ps_blob;
        ComPtr<ID3DBlob> dot_vs_blob;
        ComPtr<ID3DBlob> dot_ps_blob;
        const std::string overlay_shader_source = std::string(kShaderSourceCommon) + kOverlayPixelShaderSource;
        const bool shader_ok =
            SUCCEEDED(compile_shader(kShaderSource, "vs_main", "vs_4_0", vs_blob.GetAddressOf(), shader_error))
            && SUCCEEDED(compile_shader(kShaderSource, "ps_main", "ps_4_0", ps_blob.GetAddressOf(), shader_error))
            && SUCCEEDED(compile_shader(overlay_shader_source, "ps_overlay", "ps_4_0", overlay_ps_blob.GetAddressOf(), shader_error))
            && SUCCEEDED(compile_shader(kVertexDotShaderSource, "vs_dot", "vs_4_0", dot_vs_blob.GetAddressOf(), shader_error))
            && SUCCEEDED(compile_shader(kVertexDotShaderSource, "ps_dot", "ps_4_0", dot_ps_blob.GetAddressOf(), shader_error));
        const bool selection_binary_ok = self_test_i32_descriptor_reader();
        const bool revision_ordering_ok = self_test_mesh_edit_revision_ordering();
        const bool dds_slot_scoping_ok = self_test_dds_slot_scoping();
        if (FAILED(hr)) {
            cdmw_native_diag::event("self_test_error", {{"hresult", std::to_string(static_cast<unsigned int>(hr))}});
        } else if (!shader_ok) {
            cdmw_native_diag::event("self_test_error", {{"reason", "shader_compile_failed"}, {"message", shader_error}});
        } else if (!selection_binary_ok) {
            cdmw_native_diag::event("self_test_error", {{"reason", "selection_binary_descriptor_failed"}});
        } else if (!revision_ordering_ok) {
            cdmw_native_diag::event("self_test_error", {{"reason", "mesh_edit_revision_ordering_failed"}});
        } else if (!dds_slot_scoping_ok) {
            cdmw_native_diag::event("self_test_error", {{"reason", "dds_slot_scoping_failed"}});
        } else {
            cdmw_native_diag::event("self_test_ok", {{"feature_level", std::to_string(static_cast<unsigned int>(feature))}, {"shader", "ok"}, {"selection_binary", "ok"}, {"mesh_edit_revision_ordering", "ok"}, {"dds_slot_scoping", "ok"}});
        }
        const bool ok = SUCCEEDED(hr) && shader_ok && selection_binary_ok && revision_ordering_ok && dds_slot_scoping_ok;
        std::cout << "{\"event\":\"self_test\",\"backend\":\"D3D11\",\"ok\":" << (ok ? "true" : "false")
                  << ",\"mesh_edit_revision_ordering\":" << (revision_ordering_ok ? "true" : "false")
                  << ",\"dds_slot_scoping\":" << (dds_slot_scoping_ok ? "true" : "false") << "}\n";
        return ok ? 0 : 2;
    }
    if (args.backend != L"d3d11" && args.backend != L"D3D11") {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"only D3D11 backend is supported by this native host\"}");
        cdmw_native_diag::event("startup_error", {{"reason", "unsupported backend"}, {"backend", cdmw_native_diag::wide_to_utf8_diag(args.backend)}});
        return 1;
    }
    return run_host(args);
}
