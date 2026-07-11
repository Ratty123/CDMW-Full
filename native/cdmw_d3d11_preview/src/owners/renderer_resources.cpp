bool Renderer::upload_batches() {
        return upload_batches(batches_, stats_);
    }

bool Renderer::upload_batches(std::vector<PreviewBatch>& batches, RendererStats& stats) {
        prune_srv_cache_if_needed("pre_upload_soft_cap");
        auto geometry_start = std::chrono::steady_clock::now();
        bool uploaded_any_geometry = false;
        for (PreviewBatch& batch : batches) {
            const size_t expected = static_cast<size_t>(batch.vertex_count) * kVertexStrideBytes;
            const std::uint64_t vertex_read_size = batch.vertex_size > 0
                ? batch.vertex_size
                : static_cast<std::uint64_t>(expected);
            std::vector<uint8_t> data = (batch.vertex_offset > 0 || batch.vertex_size > 0)
                ? read_binary_range(batch.vertex_file, batch.vertex_offset, vertex_read_size)
                : read_binary(batch.vertex_file);
            if (data.size() < expected || expected == 0) {
                stats.skipped.push_back("geometry missing/truncated:" + wide_to_utf8(batch.vertex_file));
                continue;
            }
            batch.cpu_vertices.resize(expected / sizeof(float));
            std::memcpy(batch.cpu_vertices.data(), data.data(), expected);
            batch.cpu_positions.clear();
            batch.cpu_source_submeshes.clear();
            batch.cpu_source_vertices.clear();
            batch.cpu_source_faces.clear();
            batch.cpu_source_vertex_lookup.clear();
            batch.cpu_source_face_vertex_lookup.clear();
            batch.cpu_positions.reserve(static_cast<size_t>(batch.vertex_count));
            for (int vertex_index = 0; vertex_index < batch.vertex_count; ++vertex_index) {
                const float* values = reinterpret_cast<const float*>(data.data() + static_cast<size_t>(vertex_index) * kVertexStrideBytes);
                batch.cpu_positions.push_back(DirectX::XMFLOAT3(values[0], values[1], values[2]));
            }
            const std::uint64_t expected_identity_v1 = static_cast<std::uint64_t>(batch.vertex_count) * sizeof(int32_t) * 2u;
            const std::uint64_t expected_identity_v2 = static_cast<std::uint64_t>(batch.vertex_count) * sizeof(int32_t) * 3u;
            const std::uint64_t preferred_identity_size = batch.identity_stride_bytes >= sizeof(int32_t) * 3u
                ? expected_identity_v2
                : expected_identity_v1;
            std::vector<uint8_t> identity_data = batch.identity_file.empty()
                ? std::vector<uint8_t>()
                : ((batch.identity_offset > 0 || batch.identity_size > 0)
                    ? read_binary_range(
                        batch.identity_file,
                        batch.identity_offset,
                        batch.identity_size > 0 ? batch.identity_size : preferred_identity_size)
                    : read_binary(batch.identity_file));
            const size_t identity_stride_ints = (
                batch.identity_stride_bytes >= sizeof(int32_t) * 3u
                || identity_data.size() >= static_cast<size_t>(expected_identity_v2)
            ) ? 3u : 2u;
            if (identity_data.size() >= static_cast<size_t>(batch.vertex_count) * sizeof(int32_t) * identity_stride_ints) {
                batch.cpu_source_submeshes.reserve(static_cast<size_t>(batch.vertex_count));
                batch.cpu_source_vertices.reserve(static_cast<size_t>(batch.vertex_count));
                batch.cpu_source_faces.reserve(static_cast<size_t>(batch.vertex_count));
                const int32_t* identity = reinterpret_cast<const int32_t*>(identity_data.data());
                for (int vertex_index = 0; vertex_index < batch.vertex_count; ++vertex_index) {
                    const size_t base_index = static_cast<size_t>(vertex_index) * identity_stride_ints;
                    batch.cpu_source_submeshes.push_back(static_cast<int>(identity[base_index]));
                    batch.cpu_source_vertices.push_back(static_cast<int>(identity[base_index + 1u]));
                    batch.cpu_source_faces.push_back(
                        identity_stride_ints >= 3u
                            ? static_cast<int>(identity[base_index + 2u])
                            : vertex_index / 3);
                }
            } else {
                batch.cpu_source_submeshes.assign(static_cast<size_t>(batch.vertex_count), batch.source_submesh_index);
                batch.cpu_source_vertices.reserve(static_cast<size_t>(batch.vertex_count));
                batch.cpu_source_faces.reserve(static_cast<size_t>(batch.vertex_count));
                for (int vertex_index = 0; vertex_index < batch.vertex_count; ++vertex_index) {
                    batch.cpu_source_vertices.push_back(vertex_index);
                    batch.cpu_source_faces.push_back(vertex_index / 3);
                }
            }
            rebuild_batch_source_vertex_lookup(batch);
            rebuild_batch_source_face_vertex_lookup(batch);
            const bool cloth_loaded = load_cloth_runtime(batch, stats);
            D3D11_BUFFER_DESC desc{};
            desc.ByteWidth = static_cast<UINT>(expected);
            desc.Usage = cloth_loaded ? D3D11_USAGE_DYNAMIC : D3D11_USAGE_DEFAULT;
            desc.BindFlags = D3D11_BIND_VERTEX_BUFFER;
            desc.CPUAccessFlags = cloth_loaded ? D3D11_CPU_ACCESS_WRITE : 0;
            D3D11_SUBRESOURCE_DATA init{};
            init.pSysMem = batch.cpu_vertices.data();
            HRESULT hr = device_->CreateBuffer(&desc, &init, batch.vertex_buffer.GetAddressOf());
            if (FAILED(hr)) {
                stats.skipped.push_back("vertex buffer upload failed:" + std::to_string(batch.index));
            } else {
                uploaded_any_geometry = true;
            }
        }
        stats.geometry_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - geometry_start).count();

        auto texture_start = std::chrono::steady_clock::now();
        for (PreviewBatch& batch : batches) {
            batch.live_texture_bytes = 0;
            load_batch_texture(batch.base_dds, batch.base_png, batch.base_srv, "base", true, stats, batch.live_texture_bytes);
            load_batch_texture(batch.normal_dds, batch.normal_png, batch.normal_srv, "normal", false, stats, batch.live_texture_bytes);
            load_batch_texture(batch.material_dds, L"", batch.material_srv, "material", true, stats, batch.live_texture_bytes);
            load_batch_texture(batch.occlusion_dds, batch.occlusion_png, batch.occlusion_srv, "occlusion", false, stats, batch.live_texture_bytes);
            load_batch_texture(batch.roughness_dds, batch.roughness_png, batch.roughness_srv, "roughness", false, stats, batch.live_texture_bytes);
            load_batch_texture(batch.metalness_dds, batch.metalness_png, batch.metalness_srv, "metalness", false, stats, batch.live_texture_bytes);
            load_batch_texture(batch.specular_dds, batch.specular_png, batch.specular_srv, "specular", false, stats, batch.live_texture_bytes);
            load_batch_texture(batch.detail_dds, L"", batch.detail_srv, "detail", false, stats, batch.live_texture_bytes);
            load_batch_texture(batch.height_dds, batch.height_png, batch.height_srv, "height", false, stats, batch.live_texture_bytes);
            load_batch_texture(batch.emissive_dds, batch.emissive_png, batch.emissive_srv, "emissive", false, stats, batch.live_texture_bytes);
            for (int layer_index = 0; layer_index < batch.material_layer_count; ++layer_index) {
                PreviewMaterialLayer& layer = batch.material_layers[static_cast<size_t>(layer_index)];
                load_batch_texture(layer.diffuse_dds, L"", layer.diffuse_srv, "layer_base", true, stats, batch.live_texture_bytes);
                load_batch_texture(layer.mask_dds, L"", layer.mask_srv, "detail", false, stats, batch.live_texture_bytes);
                load_batch_texture(layer.material_dds, L"", layer.material_srv, "material", true, stats, batch.live_texture_bytes);
                load_batch_texture(layer.normal_dds, L"", layer.normal_srv, "normal", false, stats, batch.live_texture_bytes);
                load_batch_texture(layer.height_dds, L"", layer.height_srv, "height", false, stats, batch.live_texture_bytes);
            }
        }
        stats.texture_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - texture_start).count();
        if (stats.required_texture_failures > 0) {
            stats.texture_integrity = "missing_required";
        } else if (stats.texture_failures > 0) {
            stats.texture_integrity = "degraded";
        } else {
            stats.texture_integrity = "ok";
        }
        update_runtime_stats(stats);
        cdmw_native_diag::event(
            "upload_batches",
            {
                {"batches", std::to_string(stats.batch_count)},
                {"vertices", std::to_string(stats.vertex_count)},
                {"geometry_ms", std::to_string(stats.geometry_ms)},
                {"texture_ms", std::to_string(stats.texture_ms)},
                {"dds_base", std::to_string(stats.dds_uploaded.base)},
                {"dds_normal", std::to_string(stats.dds_uploaded.normal)},
                {"dds_material", std::to_string(stats.dds_uploaded.material)},
                {"dds_height", std::to_string(stats.dds_uploaded.height)},
                {"png_fallback", std::to_string(stats.png_fallback)},
                {"texture_failures", std::to_string(stats.texture_failures)},
                {"required_texture_failures", std::to_string(stats.required_texture_failures)},
                {"texture_integrity", stats.texture_integrity},
                {"texture_cache_entries", std::to_string(stats.texture_cache_entries)},
                {"texture_cache_releases", std::to_string(stats.texture_cache_releases)},
                {"estimated_texture_bytes", std::to_string(stats.estimated_texture_bytes)},
                {"texture_cache_bytes", std::to_string(stats.texture_cache_bytes)},
                {"live_texture_bytes", std::to_string(stats.live_texture_bytes)},
                {"skipped", std::to_string(stats.skipped.size())}
            });
        return uploaded_any_geometry;
    }

void Renderer::load_batch_texture(
        const std::wstring& dds_path,
        const std::wstring& png_fallback,
        ComPtr<ID3D11ShaderResourceView>& target,
        const char* slot,
        bool required_slot,
        RendererStats& stats,
        std::uint64_t& bound_texture_bytes) {
        const std::string slot_name(slot);
        const DirectX::CREATETEX_FLAGS create_flags =
            (slot_name == "base" || slot_name == "layer_base" || slot_name == "emissive")
                ? DirectX::CREATETEX_FORCE_SRGB
                : DirectX::CREATETEX_IGNORE_SRGB;
        std::uint64_t loaded_bytes = 0;
        if (!dds_path.empty() && fs::is_regular_file(fs::path(dds_path))) {
            TextureLoadInfo info{};
            HRESULT load_hr = S_OK;
            std::string fail_stage;
            if (load_srv_from_file(dds_path, true, target, &info, create_flags, stats, &load_hr, &fail_stage, &loaded_bytes)) {
                bound_texture_bytes += loaded_bytes;
                increment_slot(stats.dds_uploaded, slot_name);
                increment_slot(stats.textures_loaded, slot_name);
                if (slot_name == "base" || slot_name == "layer_base" || slot_name == "emissive") ++stats.srgb_color_uploads;
                else ++stats.linear_data_uploads;
                if (!info.format_name.empty()) {
                    ++stats.dds_upload_formats[info.format_name];
                }
                if ((slot_name == "base" || slot_name == "layer_base") && std::max(info.width, info.height) > 0 && std::max(info.width, info.height) < 512) {
                    ++stats.low_resolution_base_textures;
                }
                stats.texture_details.push_back(
                    slot_name + ":dds:" + filename_from_path(dds_path) + ":" +
                    info.format_name + ":" + std::to_string(info.width) + "x" + std::to_string(info.height));
                return;
            }
            ++stats.texture_failures;
            const std::string path_text = wide_to_utf8(dds_path);
            const std::string hr_text = hresult_hex(load_hr);
            const std::string stage_text = fail_stage.empty() ? "dds" : fail_stage;
            if (required_slot) ++stats.required_texture_failures;
            stats.failed_textures.push_back(slot_name + "|dds|" + path_text + "|" + stage_text + "|" + hr_text + "|" + (required_slot ? "required" : "optional") + "|DDS upload failed");
            stats.skipped.push_back(slot_name + " DDS upload failed:" + path_text + ":" + hr_text);
            cdmw_native_diag::event("dds_upload_failed", {{"slot", slot_name}, {"path", path_text}, {"stage", stage_text}, {"hresult", hr_text}, {"required", required_slot ? "true" : "false"}});
        }
        if (!png_fallback.empty() && fs::is_regular_file(fs::path(png_fallback))) {
            HRESULT load_hr = S_OK;
            std::string fail_stage;
            if (load_srv_from_file(png_fallback, false, target, nullptr, create_flags, stats, &load_hr, &fail_stage, &loaded_bytes)) {
                bound_texture_bytes += loaded_bytes;
                ++stats.png_fallback;
                increment_slot(stats.png_uploaded, slot_name);
                increment_slot(stats.textures_loaded, slot_name);
                if (slot_name == "base" || slot_name == "layer_base" || slot_name == "emissive") ++stats.srgb_color_uploads;
                else ++stats.linear_data_uploads;
                stats.texture_details.push_back(slot_name + ":png:" + filename_from_path(png_fallback));
                return;
            }
            ++stats.texture_failures;
            const std::string path_text = wide_to_utf8(png_fallback);
            const std::string hr_text = hresult_hex(load_hr);
            const std::string stage_text = fail_stage.empty() ? "wic" : fail_stage;
            if (required_slot) ++stats.required_texture_failures;
            stats.failed_textures.push_back(slot_name + "|png|" + path_text + "|" + stage_text + "|" + hr_text + "|" + (required_slot ? "required" : "optional") + "|PNG fallback failed");
            stats.skipped.push_back(slot_name + " PNG fallback failed:" + path_text + ":" + hr_text);
            cdmw_native_diag::event("png_fallback_failed", {{"slot", slot_name}, {"path", path_text}, {"stage", stage_text}, {"hresult", hr_text}, {"required", required_slot ? "true" : "false"}});
        }
    }

bool Renderer::load_srv_from_file(
        const std::wstring& path,
        bool dds,
        ComPtr<ID3D11ShaderResourceView>& target,
        TextureLoadInfo* info,
        DirectX::CREATETEX_FLAGS create_flags,
        RendererStats& stats,
        HRESULT* failed_hr,
        std::string* failed_stage,
        std::uint64_t* loaded_bytes) {
        if (loaded_bytes) *loaded_bytes = 0;
        prune_srv_cache_if_needed("texture_load_soft_cap");
        std::wstring cache_key = texture_cache_key(path, dds, create_flags);
        auto cached = srv_cache_.find(cache_key);
        if (cached != srv_cache_.end() && cached->second) {
            target = cached->second;
            ++stats.texture_cache_hits;
            auto cached_info = texture_info_cache_.find(cache_key);
            if (info) {
                if (cached_info != texture_info_cache_.end()) {
                    *info = cached_info->second;
                }
            }
            if (loaded_bytes && cached_info != texture_info_cache_.end()) {
                *loaded_bytes = static_cast<std::uint64_t>(cached_info->second.bytes);
            }
            return true;
        }
        DirectX::ScratchImage image;
        DirectX::TexMetadata metadata{};
        HRESULT hr = dds
            ? DirectX::LoadFromDDSFile(path.c_str(), DirectX::DDS_FLAGS_NONE, &metadata, image)
            : DirectX::LoadFromWICFile(path.c_str(), DirectX::WIC_FLAGS_NONE, &metadata, image);
        if (FAILED(hr)) {
            if (failed_hr) *failed_hr = hr;
            if (failed_stage) *failed_stage = dds ? "dds_decode" : "wic_decode";
            return false;
        }
        auto create_srv = [&](DirectX::CREATETEX_FLAGS flags) -> HRESULT {
            return DirectX::CreateShaderResourceViewEx(
                device_.Get(),
                image.GetImages(),
                image.GetImageCount(),
                metadata,
                D3D11_USAGE_DEFAULT,
                D3D11_BIND_SHADER_RESOURCE,
                0,
                0,
                flags,
                target.ReleaseAndGetAddressOf());
        };
        hr = create_srv(create_flags);
        if (FAILED(hr) && !dds && create_flags != static_cast<DirectX::CREATETEX_FLAGS>(0)) {
            // Some WIC-decoded PNGs from external model archives fail SRGB/linear
            // coercion even though the decoded image itself is valid. Retry with
            // default texture creation so the preview keeps the visible base map
            // instead of falling back to the white material color.
            hr = create_srv(static_cast<DirectX::CREATETEX_FLAGS>(0));
        }
        if (FAILED(hr)) {
            if (failed_hr) *failed_hr = hr;
            if (failed_stage) *failed_stage = "create_srv";
        }
        if (SUCCEEDED(hr)) {
            TextureLoadInfo loaded_info{};
            loaded_info.format_name = dxgi_format_name(metadata.format);
            loaded_info.width = metadata.width;
            loaded_info.height = metadata.height;
            loaded_info.bytes = image.GetPixelsSize();
            srv_cache_[cache_key] = target;
            texture_info_cache_[cache_key] = loaded_info;
            estimated_texture_bytes_ += static_cast<std::uint64_t>(loaded_info.bytes);
            if (loaded_bytes) {
                *loaded_bytes = static_cast<std::uint64_t>(loaded_info.bytes);
            }
            if (info) {
                *info = loaded_info;
            }
        }
        return SUCCEEDED(hr);
    }
