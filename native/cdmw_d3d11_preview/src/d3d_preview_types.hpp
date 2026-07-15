#pragma once

#include <DirectXMath.h>
#include <DirectXTex.h>
#include <Windows.h>
#include <windowsx.h>
#include <wincodec.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <dxgi.h>
#include <wrl/client.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <cstdlib>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <iostream>
#include <limits>
#include <map>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>

#include "../../common/native_diagnostics.h"

namespace cdmw_d3d11_preview {

using Microsoft::WRL::ComPtr;
namespace fs = std::filesystem;

static constexpr UINT kVertexStrideBytes = 23u * 4u;
static constexpr float kDefaultYawDegrees = -35.0f;
static constexpr float kDefaultPitchDegrees = 20.0f;
static constexpr float kFitDistance = 3.25f;
static constexpr float kVerticalFovDegrees = 45.0f;
static constexpr float kAlignmentAxisExtent = 0.95f;
static constexpr float kAlignmentAxisMarkerSize = 0.055f;
static constexpr float kAlignmentAxisLabelSize = 0.075f;
static const DirectX::XMFLOAT4 kFixedPreviewClearColor = DirectX::XMFLOAT4(0.082f, 0.098f, 0.114f, 1.0f);
static constexpr float kZoomSteps[] = {0.1f, 0.25f, 0.5f, 0.75f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f, 8.0f, 12.0f, 16.0f, 24.0f, 32.0f, 48.0f, 64.0f};
static constexpr float kMaxZoomFactor = 64.0f;
static constexpr UINT kCdmwSetZoomMessage = WM_APP + 0x431u;
static constexpr UINT kCdmwSetFitMessage = WM_APP + 0x432u;
static constexpr UINT kCdmwResetViewMessage = WM_APP + 0x433u;
static constexpr ULONG_PTR kCdmwCommandCopyData = 0x43444D57u; // "CDMW"
static constexpr ULONG_PTR kCdmwEventCopyData = 0x44334431u; // "D3D1"
static constexpr size_t kSrvCacheSoftMaxEntries = 512;
static constexpr std::uint64_t kSrvCacheSoftMaxBytes = 384ull * 1024ull * 1024ull;
static constexpr DWORD kIdleWaitMs = 50;
static constexpr double kParentHealthCheckMs = 1000.0;
static constexpr double kParentHangExitMs = 30000.0;
static constexpr UINT kParentHealthTimeoutMs = 750;
static constexpr int kMinSupportedPreviewSchemaVersion = 1;
static constexpr int kMaxSupportedPreviewSchemaVersion = 10;
static constexpr int kSupportedMaterialContractSchemaVersion = 2;
static constexpr int kSupportedMaterialChannelContractSchemaVersion = 2;
static constexpr int kSupportedTextureQualitySchemaVersion = 1;

struct Args {
    std::wstring backend = L"d3d11";
    fs::path preview_package;
    fs::path status_file;
    std::string theme_background = "#080b0e";
    std::string theme_text = "#c5ced8";
    uintptr_t parent_hwnd = 0;
    bool self_test = false;
    bool hidden = false;
    fs::path crash_dir;
    fs::path diagnostic_log;
};

struct SlotCounts {
    int base = 0;
    int normal = 0;
    int material = 0;
    int height = 0;
    int occlusion = 0;
    int roughness = 0;
    int metalness = 0;
    int specular = 0;
    int detail = 0;
    int emissive = 0;
};

static constexpr int kMaxMaterialLayers = 4;
static constexpr int kBaseSrvCount = 10;
static constexpr int kLayerSrvCount = kMaxMaterialLayers * 5;

struct ComInitScope {
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    bool needs_uninit = (hr == S_OK || hr == S_FALSE);

    ~ComInitScope() {
        if (needs_uninit) {
            CoUninitialize();
        }
    }

    bool ok() const {
        return SUCCEEDED(hr) || hr == RPC_E_CHANGED_MODE;
    }
};
static constexpr int kTotalSrvCount = kBaseSrvCount + kLayerSrvCount;

struct PreviewMaterialLayer {
    std::wstring diffuse_dds;
    std::wstring mask_dds;
    std::wstring material_dds;
    std::wstring normal_dds;
    std::wstring height_dds;
    float weight = 0.0f;
    float channel_index = 0.0f;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float height_scale_hint = 0.0f;
    float tint[4] = {1.0f, 1.0f, 1.0f, 1.0f};
    std::string role;
    std::string evidence_grade;
    ComPtr<ID3D11ShaderResourceView> diffuse_srv;
    ComPtr<ID3D11ShaderResourceView> mask_srv;
    ComPtr<ID3D11ShaderResourceView> material_srv;
    ComPtr<ID3D11ShaderResourceView> normal_srv;
    ComPtr<ID3D11ShaderResourceView> height_srv;
};

struct ClothConstraint {
    int a = 0;
    int b = 0;
    float rest_length = 0.0f;
    float stiffness = 0.0f;
};

struct ClothRuntime {
    bool available = false;
    bool initialized = false;
    bool collision_enabled = true;
    std::string kind = "cloth";
    std::string material_name;
    std::wstring particle_file;
    std::wstring pin_file;
    std::wstring constraint_file;
    int particle_count = 0;
    int constraint_count = 0;
    float gravity = -10.0f;
    float damping = 0.65f;
    float air_resistance = 1.0f;
    float wind_response = 0.4f;
    int solver_iterations = 30;
    std::vector<DirectX::XMFLOAT3> rest_positions;
    std::vector<DirectX::XMFLOAT3> positions;
    std::vector<DirectX::XMFLOAT3> previous_positions;
    std::vector<float> pin_weights;
    std::vector<ClothConstraint> constraints;
    bool root_motion_initialized = false;
    bool non_translation_reanchored = false;
    DirectX::XMFLOAT3 last_root_translation{0.0f, 0.0f, 0.0f};
};

struct ClothCollider {
    int type = 0;
    DirectX::XMFLOAT3 a{0.0f, 0.0f, 0.0f};
    DirectX::XMFLOAT3 b{0.0f, 0.0f, 0.0f};
    float radius = 0.0f;
};

struct ClothPreviewState {
    bool enabled = false;
    bool paused = false;
    bool show_pins = false;
    bool show_colliders = false;
    float wind_strength = 0.0f;
    float wind_direction_degrees = 35.0f;
};

struct PreviewBatch {
    int index = 0;
    int vertex_count = 0;
    bool flip_v = false;
    bool invert_normal_y = true;
    bool alpha_cutout = false;
    bool two_sided = false;
    float alpha_threshold = 0.0f;
    float base_color[3] = {0.78f, 0.48f, 0.34f};
    std::wstring vertex_file;
    std::uint64_t vertex_offset = 0;
    std::uint64_t vertex_size = 0;
    std::wstring base_dds;
    std::wstring normal_dds;
    std::wstring material_dds;
    std::wstring occlusion_dds;
    std::wstring roughness_dds;
    std::wstring metalness_dds;
    std::wstring specular_dds;
    std::wstring detail_dds;
    std::wstring height_dds;
    std::wstring emissive_dds;
    std::wstring layer_diffuse_dds;
    std::wstring layer_mask_dds;
    std::wstring layer_material_dds;
    std::wstring layer_normal_dds;
    std::wstring layer_height_dds;
    std::wstring base_png;
    std::wstring normal_png;
    std::wstring occlusion_png;
    std::wstring roughness_png;
    std::wstring metalness_png;
    std::wstring specular_png;
    std::wstring height_png;
    std::wstring emissive_png;
    float normal_strength = 1.0f;
    float height_amount = 0.0f;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    bool roughness_hint_present = false;
    bool metalness_hint_present = false;
    bool specular_hint_present = false;
    float height_scale_hint = 0.0f;
    float emissive_intensity = 0.0f;
    float emissive_color[3] = {0.35f, 0.68f, 1.0f};
    bool emissive_color_authoritative = false;
    bool emissive_scalar_mask = false;
    float base_tint_strength = 0.0f;
    float texture_brightness = 1.0f;
    float texture_contrast = 1.0f;
    float texture_saturation = 1.0f;
    float texture_gamma = 1.0f;
    float texture_tint[3] = {1.0f, 1.0f, 1.0f};
    float texture_uv_scale[2] = {1.0f, 1.0f};
    float layer_weight = 0.0f;
    float layer_channel_index = 0.0f;
    float layer_roughness_hint = 0.0f;
    float layer_metalness_hint = 0.0f;
    float layer_specular_hint = 0.0f;
    float layer_height_scale_hint = 0.0f;
    float layer_tint[4] = {1.0f, 1.0f, 1.0f, 1.0f};
    std::string layer_role;
    std::string layer_evidence_grade;
    std::string material_shader_family = "generic";
    float material_family_code = 0.0f;
    float material_category_code = 0.0f;
    float material_category_confidence = 0.35f;
    bool material_response_promoted = false;
    bool low_authority_base_overlay = false;
    std::array<PreviewMaterialLayer, kMaxMaterialLayers> material_layers;
    int material_layer_count = 0;
    int source_submesh_index = -1;
    int source_local_submesh_index = -1;
    int source_component_index = 0;
    int source_vertex_count = 0;
    int source_face_count = 0;
    std::wstring identity_file;
    std::uint64_t identity_offset = 0;
    std::uint64_t identity_size = 0;
    std::uint64_t identity_stride_bytes = 0;
    std::string source_model_path;
    std::string source_component_label;
    std::string part_label;
    std::string editor_role;
    bool editor_editable = true;
    bool prefab_component = false;
    float highlight_strength = 0.0f;
    float normalization_center[3] = {0.0f, 0.0f, 0.0f};
    float normalization_scale = 1.0f;
    std::vector<DirectX::XMFLOAT3> cpu_positions;
    std::vector<int> cpu_source_submeshes;
    std::vector<int> cpu_source_vertices;
    std::vector<int> cpu_source_faces;
    std::map<std::pair<int, int>, std::vector<size_t>> cpu_source_vertex_lookup;
    std::map<std::pair<int, int>, std::set<int>> cpu_source_face_vertex_lookup;
    std::vector<float> cpu_vertices;
    ClothRuntime cloth;
    ComPtr<ID3D11Buffer> vertex_buffer;
    bool pending_vertex_upload = false;
    size_t pending_vertex_upload_min = std::numeric_limits<size_t>::max();
    size_t pending_vertex_upload_max = 0;
    ComPtr<ID3D11ShaderResourceView> base_srv;
    ComPtr<ID3D11ShaderResourceView> normal_srv;
    ComPtr<ID3D11ShaderResourceView> material_srv;
    ComPtr<ID3D11ShaderResourceView> occlusion_srv;
    ComPtr<ID3D11ShaderResourceView> roughness_srv;
    ComPtr<ID3D11ShaderResourceView> metalness_srv;
    ComPtr<ID3D11ShaderResourceView> specular_srv;
    ComPtr<ID3D11ShaderResourceView> detail_srv;
    ComPtr<ID3D11ShaderResourceView> height_srv;
    ComPtr<ID3D11ShaderResourceView> emissive_srv;
    ComPtr<ID3D11ShaderResourceView> layer_diffuse_srv;
    ComPtr<ID3D11ShaderResourceView> layer_mask_srv;
    ComPtr<ID3D11ShaderResourceView> layer_material_srv;
    ComPtr<ID3D11ShaderResourceView> layer_normal_srv;
    ComPtr<ID3D11ShaderResourceView> layer_height_srv;
    std::uint64_t live_texture_bytes = 0;
};

struct TriangleReplacementGroup {
    std::string payload;
    int source_submesh = -1;
    std::vector<float> positions;
    std::vector<float> normals;
    std::vector<float> uvs;
    std::vector<int> source_vertices;
    std::vector<int> source_faces;
    std::vector<int> indices;
    std::vector<float> position_transform;
    std::vector<float> normal_transform;
    std::vector<float> normalization_center;
    int source_vertex_start = -1;
    int source_vertex_range_count = 0;
    int source_face_start = -1;
    int source_face_range_count = 0;
    int source_vertex_identity_count = 0;
    int source_face_identity_count = 0;
    size_t source_vertex_count = 0;
    bool source_vertex_range = false;
    bool source_face_range = false;
    bool indexed_payload = false;
    bool source_space_positions = false;
    bool source_affine_positions = false;
    bool native_core_source_positions = false;
    float normalization_scale = 1.0f;
};

struct MeshEditState {
    bool enabled = false;
    std::string scope_mode = "all";
    std::string target_mode = "brush";
    std::string tool = "grab";
    std::string delete_mode = "release";
    std::string selection_mode = "brush";
    std::string selection_depth_mode = "visible";
    std::string falloff = "smooth";
    float radius_pixels = 24.0f;
    float strength = 0.5f;
    int smooth_iterations = 3;
    bool show_vertices = false;
    bool drag_active = false;
    bool selection_drag_active = false;
    std::string selection_operation = "replace";
    int stroke_id = 0;
    int start_x = 0;
    int start_y = 0;
    int last_x = 0;
    int last_y = 0;
    bool previewed = false;
    bool drag_uses_resident_selection = false;
    std::vector<DirectX::XMFLOAT2> selection_lasso_points;
    std::set<std::pair<int, int>> selected_vertices;
    std::set<std::tuple<int, int, int>> selected_edges;
    std::set<std::pair<int, int>> selected_faces;
    std::set<int> selected_sources;
    std::set<int> source_submesh_indices;
    std::chrono::steady_clock::time_point last_preview_event_time{};
};

struct AlignmentState {
    bool enabled = false;
    std::set<int> selected_source_submeshes;
    struct PartTransform {
        DirectX::XMFLOAT3 translation{0.0f, 0.0f, 0.0f};
        DirectX::XMFLOAT3 rotation{0.0f, 0.0f, 0.0f};
        DirectX::XMFLOAT3 scale{1.0f, 1.0f, 1.0f};
    };
    std::map<int, PartTransform> part_transforms;
    std::map<int, DirectX::XMFLOAT3> part_translation_drag_bases;
    std::map<int, DirectX::XMFLOAT3> part_rotation_drag_bases;
    std::string hover_axis;
    std::string drag_axis;
    bool drag_active = false;
    bool rotation_drag_active = false;
    bool rotation_drag_roll = false;
    float translation_sensitivity = 0.85f;
    float rotation_degrees_per_pixel = 0.18f;
    int last_x = 0;
    int last_y = 0;
    DirectX::XMFLOAT3 translation_total{0.0f, 0.0f, 0.0f};
    DirectX::XMFLOAT3 rotation_total{0.0f, 0.0f, 0.0f};
    DirectX::XMFLOAT3 scale_total{1.0f, 1.0f, 1.0f};
    DirectX::XMFLOAT3 translation_drag_base{0.0f, 0.0f, 0.0f};
    DirectX::XMFLOAT3 translation_drag_delta{0.0f, 0.0f, 0.0f};
    DirectX::XMFLOAT3 rotation_drag_base{0.0f, 0.0f, 0.0f};
    DirectX::XMFLOAT3 rotation_drag_delta{0.0f, 0.0f, 0.0f};
    std::chrono::steady_clock::time_point last_translation_change_sent{};
    std::chrono::steady_clock::time_point last_rotation_change_sent{};
    mutable bool origin_cache_valid = false;
    mutable DirectX::XMFLOAT3 origin_cache{0.0f, 0.0f, 0.0f};
};

struct SourcePartInteractionState {
    bool picking_enabled = false;
    int hovered_source_submesh = -1;
    bool click_pending = false;
    int click_source_submesh = -1;
    int start_x = 0;
    int start_y = 0;
};

struct SkeletonOverlayBoneState {
    int index = -1;
    int parent_index = -1;
    DirectX::XMFLOAT3 position{0.0f, 0.0f, 0.0f};
    DirectX::XMFLOAT3 parent_position{0.0f, 0.0f, 0.0f};
    bool has_position = false;
    bool has_parent_position = false;
};

struct SkeletonOverlayState {
    bool enabled = false;
    bool pose_enabled = false;
    int selected_bone_index = -1;
    std::vector<SkeletonOverlayBoneState> bones;
};

struct ScreenPoint {
    float x = 0.0f;
    float y = 0.0f;
};

enum class PreviewViewRole {
    All,
    Reference,
    Replacement,
};

static const char* preview_view_role_name(PreviewViewRole role) {
    switch (role) {
    case PreviewViewRole::Reference:
        return "reference";
    case PreviewViewRole::Replacement:
        return "replacement";
    case PreviewViewRole::All:
    default:
        return "all";
    }
}

struct PreviewRenderView {
    D3D11_VIEWPORT viewport{};
    PreviewViewRole role = PreviewViewRole::All;
    bool wireframe = false;
    bool no_depth = false;
    float reference_tint_alpha = 0.0f;
};

struct MeshEditScreenVertex {
    int batch_index = -1;
    int source_submesh_index = -1;
    int source_vertex_index = -1;
    DirectX::XMFLOAT3 position{0.0f, 0.0f, 0.0f};
    float screen_x = 0.0f;
    float screen_y = 0.0f;
    float depth_z = 1.0f;
};

struct MeshEditScreenVertexCache {
    bool valid = false;
    std::string key;
    std::vector<MeshEditScreenVertex> vertices;
};

struct MeshEditDepthMaskCache {
    bool valid = false;
    std::string key;
    int width = 0;
    int height = 0;
    float viewport_x = 0.0f;
    float viewport_y = 0.0f;
    float scale_x = 1.0f;
    float scale_y = 1.0f;
    std::vector<float> depths;
};

struct VertexDotInstance {
    float clip_x = 0.0f;
    float clip_y = 0.0f;
    float clip_z = 0.0f;
    float radius_x = 0.0f;
    float radius_y = 0.0f;
    float r = 1.0f;
    float g = 1.0f;
    float b = 1.0f;
    float a = 1.0f;
};

struct ConstantBuffer {
    DirectX::XMFLOAT4X4 mvp;
    DirectX::XMFLOAT4X4 normal_world;
    DirectX::XMFLOAT4 light_dir;
    DirectX::XMFLOAT4 base_color_flip;
    DirectX::XMFLOAT4 flags;
    DirectX::XMFLOAT4 flags2;
    DirectX::XMFLOAT4 material_params;
    DirectX::XMFLOAT4 material_hints;
    DirectX::XMFLOAT4 flags3;
    DirectX::XMFLOAT4 render_tuning;
    DirectX::XMFLOAT4 render_tuning2;
    DirectX::XMFLOAT4 render_tuning3;
    DirectX::XMFLOAT4 render_tuning4;
    DirectX::XMFLOAT4 editor_tint;
    DirectX::XMFLOAT4 flags4;
    DirectX::XMFLOAT4 flags5;
    DirectX::XMFLOAT4 emissive_params;
    DirectX::XMFLOAT4 material_value_params;
    DirectX::XMFLOAT4 material_color_params;
    DirectX::XMFLOAT4 material_tint_params;
    DirectX::XMFLOAT4 layer_params[kMaxMaterialLayers];
    DirectX::XMFLOAT4 layer_tint[kMaxMaterialLayers];
    DirectX::XMFLOAT4 layer_hints[kMaxMaterialLayers];
    DirectX::XMFLOAT4 layer_flags[kMaxMaterialLayers];
};

struct RendererStats {
    int batch_count = 0;
    int vertex_count = 0;
    int png_fallback = 0;
    int texture_cache_hits = 0;
    int low_resolution_base_textures = 0;
    int srgb_color_uploads = 0;
    int linear_data_uploads = 0;
    SlotCounts dds_candidates;
    SlotCounts dds_uploaded;
    SlotCounts png_uploaded;
    SlotCounts textures_loaded;
    int material_combiner_active_batches = 0;
    int material_layer_active_batches = 0;
    int material_layer_count = 0;
    int cloth_batch_count = 0;
    int cloth_particle_count = 0;
    int cloth_constraint_count = 0;
    int cloth_collider_count = 0;
    int pbd_hint_count = 0;
    int pbd_soft_hint_count = 0;
    int pbd_cloth_hint_count = 0;
    std::uint64_t cloth_simulation_steps = 0;
    std::map<std::string, int> material_combiner_outputs;
    std::map<std::string, int> material_combiner_decode_modes;
    std::map<std::string, int> material_layer_roles;
    std::map<std::string, int> dds_upload_formats;
    std::vector<std::string> texture_details;
    std::vector<std::string> failed_textures;
    int texture_failures = 0;
    int required_texture_failures = 0;
    std::string texture_integrity = "ok";
    bool device_lost = false;
    std::string device_loss_stage;
    std::string device_loss_hresult;
    std::string device_removed_reason;
    int present_failure_count = 0;
    int resize_failure_count = 0;
    std::string resize_failure_hresult;
    std::string resize_failure_reason;
    int manifest_schema_version = 0;
    int material_contract_schema = 0;
    int material_channel_contract_schema = 0;
    int texture_quality_schema = 0;
    int cloth_runtime_schema = 0;
    std::string render_diagnostic_mode;
    std::string lighting_preset;
    std::string placement_frame_kind;
    std::string grid_mode;
    float grid_y = 0.0f;
    bool placement_grid_valid = false;
    std::string reference_tint_mode;
    std::string reference_material_policy;
    bool physics_overlay_enabled = false;
    bool physics_overlay_cloth = false;
    int physics_shape_count = 0;
    int physics_anchor_count = 0;
    int physics_constraint_count = 0;
    bool cloth_runtime_debug_enabled = false;
    bool skeleton_overlay_enabled = false;
    int skeleton_bone_count = 0;
    bool skeleton_pose_enabled = false;
    int skeleton_selected_bone_index = -1;
    int skeleton_posed_bone_count = 0;
    int editable_value_group_count = 0;
    double manifest_ms = 0.0;
    double geometry_ms = 0.0;
    double texture_ms = 0.0;
    double first_frame_ms = 0.0;
    int texture_cache_entries = 0;
    int texture_cache_releases = 0;
    std::uint64_t estimated_texture_bytes = 0;
    std::uint64_t texture_cache_bytes = 0;
    std::uint64_t live_texture_bytes = 0;
    std::uint64_t process_working_set_bytes = 0;
    std::uint64_t process_private_bytes = 0;
    std::uint64_t frame_count = 0;
    std::uint64_t render_request_count = 0;
    std::uint64_t render_suppressed_count = 0;
    std::uint64_t mesh_edit_selection_event_count = 0;
    std::uint64_t parent_unresponsive_count = 0;
    std::string parent_health = "ok";
    std::string render_suppressed_reason = "";
    bool parent_renderable = true;
    int sampler_max_anisotropy = 1;
    float sampler_mip_lod_bias = 0.0f;
    int sampler_recreate_count = 0;
    std::vector<std::string> skipped;
};

struct TextureLoadInfo {
    std::string format_name;
    size_t width = 0;
    size_t height = 0;
    size_t bytes = 0;
};

struct ViewSettings {
    float orbit_sensitivity = 0.22f;
    float pan_sensitivity = 0.60f;
    bool invert_orbit_x = false;
    bool invert_orbit_y = false;
    bool invert_pan_x = false;
    bool invert_pan_y = false;
};

struct PreviewCameraState {
    float yaw = kDefaultYawDegrees;
    float pitch = kDefaultPitchDegrees;
    bool fit_to_view = true;
    float zoom_factor = 1.0f;
    float distance = kFitDistance;
    float pan_x = 0.0f;
    float pan_y = 0.0f;
    float pan_z = 0.0f;
};

struct PreviewRenderedCameraEvidence {
    bool valid = false;
    PreviewViewRole role = PreviewViewRole::All;
    PreviewCameraState camera;
    D3D11_VIEWPORT viewport{};
    DirectX::XMFLOAT4X4 world_view_projection{};
    std::uint64_t solid_draw_count = 0;
};

struct RenderTuning {
    int max_anisotropy = 16;
    int diagnostic_mode = 0;
    float mip_lod_bias = -2.0f;
    bool cull_back_faces = false;
    float light_azimuth_degrees = -10.0f;
    float light_elevation_degrees = 0.0f;
    int normal_y_mode = 0;
    float ao_strength = 0.45f;
    float roughness_bias = -0.04f;
    float metalness_scale = 1.45f;
    float environment_strength = 0.62f;
    float emissive_gain = 2.2f;
    float tone_exposure = 1.00f;
    float tone_contrast = 1.08f;
    float tone_gamma = 1.00f;
    std::string texture_address_mode = "wrap";
    float ambient_strength = 0.84f;
    float diffuse_wrap_bias = 0.58f;
    float diffuse_light_scale = 0.62f;
    float specular_base = 0.055f;
    float specular_max = 0.52f;
    float shininess_min = 28.0f;
    float shininess_max = 152.0f;
};


}  // namespace cdmw_d3d11_preview
