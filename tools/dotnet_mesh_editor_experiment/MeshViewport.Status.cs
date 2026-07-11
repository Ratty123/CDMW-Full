using System.Globalization;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private static string MaterialDebugModeName(int mode)
    {
        return Math.Clamp(mode, 0, 6) switch
        {
            1 => "base",
            2 => "normal",
            3 => "roughness",
            4 => "metallic",
            5 => "emissive",
            6 => "specular",
            _ => "final",
        };
    }

    public Dictionary<string, object?> RendererStatusPayload()
    {
        return new Dictionary<string, object?>
        {
            ["backend"] = RendererBackend,
            ["gpu_backed"] = !_rendererBlocked && (_d3d11Viewport is not null || _gpuViewport is not null),
            ["renderer_blocked"] = _rendererBlocked,
            ["renderer_block_reason"] = _rendererBlockReason,
            ["production_d3d11_required"] = ProductionD3D11Required,
            ["developer_renderer_fallback"] = _options.DeveloperRendererFallback,
            ["d3d11_hlsl"] = _d3d11Viewport is not null,
            ["d3d11_status"] = _d3d11Viewport?.LastError ?? _lastD3D11Error,
            ["device_removed_reason"] = _d3d11Viewport?.DeviceRemovedReason ?? string.Empty,
            ["viewport"] = RenderSurfaceStatusPayload(),
            ["material_debug_mode"] = MaterialDebugModeName(MaterialDebugMode),
            ["display_mode"] = DisplayMode,
            ["show_solid"] = ShowSolid,
            ["show_wire"] = ShowWire,
            ["show_vertices"] = ShowVertices,
            ["textures_enabled"] = TexturesEnabled,
            ["material_parity_contract"] = "base_normal_roughness_metallic_emissive_specular_final_experiment_only",
            ["material_contract_gap"] = new[]
            {
                "material layers beyond simple slots",
                "direct compressed DDS upload parity",
                "native material category scalar rules",
                "sidecar tint parity",
                "normal-y policy parity",
            },
            ["capabilities"] = ActiveCapabilities(),
            ["geometry_resources"] = RendererResourceMetricsPayload(),
            ["material_slots"] = _materials.SlotCount,
            ["material_generation"] = _materials.Generation,
            ["material_signature"] = _materials.Signature,
            ["material_parameter_state_count"] = _materials.ParameterStateCount,
            ["material_parameter_roles"] = _materials.ParameterRoles,
            ["texture_references"] = _materials.TextureReferenceCount,
            ["resolved_texture_references"] = _materials.ResolvedTextureReferenceCount,
            ["existing_texture_files"] = _materials.ExistingTextureFileCount,
            ["decoded_texture_resources"] = _textureSet.DecodedCount,
            ["decodable_texture_files"] = _materials.DecodableTextureFileCount,
            ["dds_resources"] = _textureSet.DdsResourceCount,
            ["dds_decoded_resources"] = _textureSet.DdsDecodedCount,
            ["texture_load_failures"] = _textureSet.TextureLoadFailureCount,
            ["texture_decode_attempts"] = _textureSet.DecodeAttemptCount,
            ["texture_decode_successes"] = _textureSet.DecodeSuccessCount,
            ["texture_decode_reuses"] = _textureSet.DecodeReuseCount,
            ["incremental_texture_decodes"] = _textureSet.IncrementalDecodeCount,
            ["texture_decode_singleflight_joins"] = _textureSet.DecodeSingleflightJoinCount,
            ["decoded_bitmap_prunes"] = _textureSet.DecodedBitmapPruneCount,
            ["dds_upload_mode"] = "bitmap_rgba_upload",
            ["native_dds_parity"] = false,
            ["dds_native_dxgi_upload"] = false,
            ["dds_upload_format"] = "B8G8R8A8_UNorm",
            ["dds_decode"] = _textureSet.DdsDecodedCount > 0 ? "bitmap_decode_then_bgra32_upload" : (_textureSet.DdsResourceCount > 0 ? "header_verified_not_sampled" : "not_present_or_unverified"),
            ["dds_decode_tools"] = new[] { "managed_dds_decoder", "cd-texture-dx.exe", "texconv.exe" },
            ["shader_model"] = _rendererBlocked ? "blocked_renderer_unavailable" : (_d3d11Viewport is not null ? "hlsl_vs5_ps5_per_pixel_materials" : (_gpuViewport is not null ? "wpf_materials" : "gdi_fallback")),
        };
    }

    public string[] ActiveCapabilities()
    {
        var capabilities = new List<string>
        {
            "solid",
            "wire",
            "visible_selection",
            "xray_selection",
            "local_edge_topology",
            "local_edge_picking",
            "local_edge_overlay",
            "stable_edge_descriptors",
            "topology_generation",
            "material_manifest",
            "decoded_texture_resources",
            "material_debug_channels",
            "viewport_display_modes_v1",
            "strokes",
            "commands",
            "mesh_edit_revision_ack_v1",
            "host_tool_state_v1",
            "resident_material_updates_v2",
        };
        if (_rendererBlocked)
        {
            capabilities.Add("blocked_renderer_unavailable");
        }
        else if (_d3d11Viewport is not null)
        {
            capabilities.Add("d3d11_vortice_hlsl_material_renderer");
            capabilities.Add("d3d11_overlay_vertices_edges_faces_parts_wire_xray");
            capabilities.Add("resident_material_parameter_updates_v1");
            capabilities.Add("resident_texture_region_updates_v1");
        }
        else if (_gpuViewport is not null)
        {
            capabilities.Add("wpf_gpu_material_renderer");
        }
        else
        {
            capabilities.Add("winforms_gdi_fallback_renderer");
        }
        return capabilities.ToArray();
    }

    public Dictionary<string, object?> SelectionSnapshotPayload()
    {
        return new Dictionary<string, object?>
        {
            ["vertices_by_submesh"] = SelectionMapPayload(_selectedVertices),
            ["faces_by_submesh"] = SelectionMapPayload(_selectedFaces),
            ["edges_by_submesh"] = EdgeSelectionMapPayload(_selectedEdges),
            ["edges"] = _selectedEdges.OrderBy(id => id).ToArray(),
            ["edge_descriptors"] = EdgeDescriptorPayloads(_selectedEdges),
            ["topology_generation"] = _edgeTopology.Generation,
            ["source_indices"] = _selectedSources.OrderBy(id => id).ToArray(),
            ["sources"] = _selectedSources.OrderBy(id => id).ToArray(),
            ["target_mode"] = CurrentTargetMode(),
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
        };
    }

    private void NotifyLocalSelectionChanged()
    {
        EditorEventRequested?.Invoke("selection_request", new Dictionary<string, object?>
        {
            ["operation"] = "replace",
            ["target_mode"] = CurrentTargetMode(),
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
            ["local_selection"] = SelectionSnapshotPayload(),
        });
    }

    public bool TryHandleLocalCommand(string command, string targetMode)
    {
        _ = command;
        _ = targetMode;
        return false;
    }

    private static Dictionary<string, int[]> SelectionMapPayload(Dictionary<int, HashSet<int>> selection)
    {
        return selection
            .OrderBy(pair => pair.Key)
            .ToDictionary(pair => pair.Key.ToString(CultureInfo.InvariantCulture), pair => pair.Value.OrderBy(value => value).ToArray());
    }

    private Dictionary<string, int[][]> EdgeSelectionMapPayload(IEnumerable<int> edgeIds)
    {
        return edgeIds
            .Select(edgeId => _edgeTopology.EdgeById(edgeId))
            .Where(edge => edge is not null)
            .GroupBy(edge => edge!.SubmeshIndex)
            .OrderBy(group => group.Key)
            .ToDictionary(
                group => group.Key.ToString(CultureInfo.InvariantCulture),
                group => group
                    .Select(edge => new[] { edge!.VertexA, edge.VertexB })
                    .OrderBy(pair => pair[0])
                    .ThenBy(pair => pair[1])
                    .ToArray());
    }

    private Dictionary<string, object?>[] EdgeDescriptorPayloads(IEnumerable<int> edgeIds)
    {
        return edgeIds
            .Select(edgeId => _edgeTopology.EdgeById(edgeId))
            .Where(edge => edge is not null)
            .Select(edge => edge!.ToDescriptorPayload(_edgeTopology.Generation))
            .ToArray();
    }
}
